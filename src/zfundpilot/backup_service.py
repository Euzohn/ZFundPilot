"""备份导出、导入预检与可验证恢复（格式 v2）。

备份是带 ``manifest.json`` 的 ZIP：清单记录格式版本、创建时间、各表行数、
列顺序与 SHA-256；表数据以 JSONL 保存，保留 ``None`` 与数值类型，避免 CSV
的类型/空串歧义。恢复前必须通过预检，恢复时先自动生成当前数据的安全备份，
再在单个 SQLite 写事务中整体替换；任何失败都会回滚，不会破坏现有数据。

安全边界：
- 不导出审计日志、AI 用量、Agent token 摘要、幂等记录与临时刷新任务；
- 不导出 AI 密钥（存放在 ``data/ai_config.json``，需要单独迁移）；
- 只接受显式白名单表与固定列，拒绝未知文件、重复条目、路径穿越和超限 ZIP。
"""

from __future__ import annotations

import hashlib
import hmac
import io
import json
import re
import threading
import zipfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from . import __version__, analysis, config, db

FORMAT_NAME = "zfundpilot-backup"
FORMAT_VERSION = 2
MANIFEST_NAME = "manifest.json"
TABLE_DIR = "tables"
MAX_ZIP_BYTES = 256 * 1024 * 1024
MAX_UNCOMPRESSED_BYTES = 512 * 1024 * 1024
MAX_SINGLE_FILE_BYTES = 256 * 1024 * 1024
MAX_ENTRIES = 64
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")

# 可恢复表白名单与固定列顺序。未知表/列一律拒绝，避免备份文件注入。
TABLE_COLUMNS: dict[str, tuple[str, ...]] = {
    "funds": (
        "fund_code", "fund_name", "fund_type", "sector", "tracking_index",
        "purchase_status", "daily_limit", "min_purchase", "risk_level",
        "created_at", "updated_at", "dividend_method",
    ),
    "transactions": (
        "id", "fund_code", "action", "date", "amount", "shares", "nav",
        "fee", "channel", "note", "is_t1", "created_at", "conversion_id",
    ),
    "nav_history": (
        "id", "fund_code", "date", "nav", "accumulated_nav", "source",
        "created_at",
    ),
    "portfolio_snapshots": (
        "id", "date", "total_cost", "total_value", "total_profit",
        "total_return", "created_at",
    ),
    "auto_invest_plans": (
        "id", "fund_code", "amount", "cadence", "day_of_week", "day_of_month",
        "channel", "note", "enabled", "next_run", "last_run", "last_tx_id",
        "created_at", "updated_at",
    ),
    "watchlist": ("fund_code", "note", "group_name", "added_at", "revision"),
    "watchlist_tombstones": (
        "fund_code", "revision", "note", "group_name", "added_at", "deleted_at",
    ),
    "dividend_alerts": (
        "id", "fund_code", "fund_name", "record_date", "ex_date", "per_share",
        "pay_date", "held_shares", "estimated_amount", "dividend_method",
        "status", "created_at", "resolved_at", "tx_id", "alert_type",
        "triggered_return", "threshold",
    ),
    "preferences": ("key", "value"),
    "trade_calendar": ("date", "created_at"),
    "index_history": ("id", "code", "date", "close", "source", "created_at"),
    "tp_sl_alert_states": (
        "fund_code", "alert_type", "last_alert_id", "last_triggered_return",
        "handled_at", "armed", "updated_at",
    ),
}

# 唯一键用于预检重复行；与数据库约束保持一致（可有多组）。
UNIQUE_KEYS: dict[str, tuple[tuple[str, ...], ...]] = {
    "funds": (("fund_code",),),
    "transactions": (("id",),),
    "nav_history": (("fund_code", "date"),),
    "portfolio_snapshots": (("id",), ("date",)),
    "auto_invest_plans": (("id",),),
    "watchlist": (("fund_code",),),
    "watchlist_tombstones": (("fund_code",),),
    "dividend_alerts": (("id",),),
    "preferences": (("key",),),
    "trade_calendar": (("date",),),
    "index_history": (("id",), ("code", "date")),
    "tp_sl_alert_states": (("fund_code", "alert_type"),),
}

REQUIRED_VALUES: dict[str, tuple[str, ...]] = {
    "funds": ("fund_code",),
    "transactions": ("fund_code", "action", "date"),
    "nav_history": ("fund_code", "date", "nav"),
    "portfolio_snapshots": ("date", "total_cost", "total_value"),
    "auto_invest_plans": ("fund_code", "amount", "cadence"),
    "watchlist": ("fund_code",),
    "watchlist_tombstones": ("fund_code", "revision", "deleted_at"),
    "dividend_alerts": ("fund_code",),
    "preferences": ("key",),
    "trade_calendar": ("date",),
    "index_history": ("code", "date", "close"),
    "tp_sl_alert_states": ("fund_code", "alert_type"),
}

EXCLUDED_TABLES = {
    "audit_log": "审计日志含 IP/用户名，且恢复不应覆盖安全审计",
    "ai_usage": "AI 用量统计可重建",
    "agent_tokens": "凭据摘要不进入普通备份",
    "agent_operations": "临时幂等记录，恢复后无意义",
    "refresh_jobs": "临时刷新任务，恢复后无意义",
}

EXCLUDED_SECRETS = {
    "ai_config.json": "AI 密钥单独加密保存，普通 ZIP 不导出",
    "auth.json": "登录密码哈希与会话密钥不进入普通备份",
}

_restore_guard = threading.Lock()


class BackupValidationError(ValueError):
    """备份结构、版本或数据校验失败；不修改当前数据。"""

    def __init__(self, code: str, message: str, field_name: str = "file") -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.field = field_name


class BackupBusyError(RuntimeError):
    """已有恢复任务在进行；不排队，避免并发覆盖。"""


@dataclass
class Preview:
    format_version: int
    app_version: str
    created_at: str
    counts: dict[str, int]
    current_counts: dict[str, int]
    total_rows: int
    current_total_rows: int
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "format": FORMAT_NAME,
            "format_version": self.format_version,
            "app_version": self.app_version,
            "created_at": self.created_at,
            "tables": {
                name: {"rows": self.counts[name],
                       "current_rows": self.current_counts.get(name, 0)}
                for name in TABLE_COLUMNS
            },
            "total_rows": self.total_rows,
            "current_total_rows": self.current_total_rows,
            "replace_all": True,
            "can_restore": True,
            "warnings": self.warnings,
            "excluded": EXCLUDED_TABLES,
            "excluded_secrets": EXCLUDED_SECRETS,
            "safety_backup": "恢复前会在 data/backups 自动生成当前数据的安全备份",
        }


@dataclass
class RestoreResult:
    counts: dict[str, int]
    total_rows: int
    safety_backup: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": True,
            "restored": self.counts,
            "total_rows": self.total_rows,
            "safety_backup": self.safety_backup,
            "replace_all": True,
        }


def _now() -> datetime:
    return datetime.now(config.TIMEZONE)


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _read_limited(zf: zipfile.ZipFile, info: zipfile.ZipInfo,
                  limit: int) -> bytes:
    """分块读取并限制解压后大小，防止 ZIP 炸弹。"""
    if info.file_size > limit:
        raise BackupValidationError(
            "file_too_large", f"备份条目过大：{info.filename}")
    with zf.open(info) as fh:
        parts: list[bytes] = []
        total = 0
        while True:
            chunk = fh.read(64 * 1024)
            if not chunk:
                break
            total += len(chunk)
            if total > limit:
                raise BackupValidationError(
                    "file_too_large", f"备份条目解压后过大：{info.filename}")
            parts.append(chunk)
    return b"".join(parts)


def _safe_jsonl(rows: list[dict[str, Any]]) -> bytes:
    payload = "".join(
        json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n"
        for row in rows
    )
    return payload.encode("utf-8")


def _table_rows(conn: Any, table: str) -> list[dict[str, Any]]:
    cols = TABLE_COLUMNS[table]
    sql = f"SELECT {', '.join(cols)} FROM {table}"
    return [dict(row) for row in conn.execute(sql).fetchall()]


def export_backup_zip() -> bytes:
    """导出格式 v2 备份：manifest + ``tables/*.jsonl``。"""
    tables: dict[str, dict[str, Any]] = {}
    payloads: dict[str, bytes] = {}
    with db.get_connection() as conn:
        # 同一读事务保证各表来自同一快照，避免导出期间并发写入造成交叉不一致。
        conn.execute("BEGIN")
        for table in TABLE_COLUMNS:
            rows = _table_rows(conn, table)
            data = _safe_jsonl(rows)
            path = f"{TABLE_DIR}/{table}.jsonl"
            payloads[path] = data
            tables[table] = {
                "file": path,
                "columns": list(TABLE_COLUMNS[table]),
                "rows": len(rows),
                "sha256": _sha256(data),
            }

    manifest = {
        "format": FORMAT_NAME,
        "format_version": FORMAT_VERSION,
        "app_version": __version__,
        "created_at": _now().isoformat(),
        "tables": tables,
        "excluded": EXCLUDED_TABLES,
        "excluded_secrets": EXCLUDED_SECRETS,
        "notes": (
            "JSONL 保留 null 与数值类型；恢复会整体替换当前用户数据，"
            "并在恢复前自动生成安全备份。"
        ),
    }
    manifest_bytes = json.dumps(
        manifest, ensure_ascii=False, indent=2).encode("utf-8")

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(MANIFEST_NAME, manifest_bytes)
        for path, data in payloads.items():
            zf.writestr(path, data)
    return buf.getvalue()


def _load_manifest(zf: zipfile.ZipFile) -> dict[str, Any]:
    try:
        info = zf.getinfo(MANIFEST_NAME)
    except KeyError as exc:
        raise BackupValidationError(
            "missing_manifest",
            "备份缺少 manifest.json，可能是旧版备份或文件损坏",
        ) from exc
    raw = _read_limited(zf, info, 4 * 1024 * 1024)
    try:
        manifest = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BackupValidationError(
            "invalid_manifest", "manifest.json 不是有效的 UTF-8 JSON") from exc
    if not isinstance(manifest, dict):
        raise BackupValidationError("invalid_manifest", "manifest.json 格式不正确")
    if manifest.get("format") != FORMAT_NAME:
        raise BackupValidationError(
            "unknown_format", "不是 ZFundPilot 备份文件")
    version = manifest.get("format_version")
    if version != FORMAT_VERSION:
        raise BackupValidationError(
            "unsupported_version",
            f"备份格式版本 {version!r} 不受支持（当前 {FORMAT_VERSION}）",
        )
    return manifest


def _zip_members(zf: zipfile.ZipFile) -> dict[str, zipfile.ZipInfo]:
    infos = zf.infolist()
    if len(infos) > MAX_ENTRIES:
        raise BackupValidationError("too_many_entries", "备份条目过多")
    members: dict[str, zipfile.ZipInfo] = {}
    total = 0
    for info in infos:
        name = info.filename
        if name.startswith("/") or ".." in Path(name).parts:
            raise BackupValidationError(
                "unsafe_path", f"备份包含不安全路径：{name}")
        if name in members:
            raise BackupValidationError(
                "duplicate_entry", f"备份包含重复条目：{name}")
        if info.flag_bits & 0x1:
            raise BackupValidationError(
                "encrypted", "不支持加密 ZIP，请导出未加密备份")
        total += info.file_size
        if total > MAX_UNCOMPRESSED_BYTES:
            raise BackupValidationError(
                "file_too_large", "备份解压后总大小超出限制")
        members[name] = info
    return members


def _parse_table_rows(table: str, raw: bytes) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    allowed = set(TABLE_COLUMNS[table])
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise BackupValidationError(
            "invalid_encoding", f"{table} 不是有效的 UTF-8 文本") from exc
    for lineno, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise BackupValidationError(
                "invalid_row", f"{table} 第 {lineno} 行不是有效 JSON") from exc
        if not isinstance(row, dict):
            raise BackupValidationError(
                "invalid_row", f"{table} 第 {lineno} 行必须是对象")
        extra = set(row) - allowed
        if extra:
            raise BackupValidationError(
                "unknown_column",
                f"{table} 第 {lineno} 行包含未知列：{', '.join(sorted(extra))}",
            )
        rows.append(row)
    return rows


def _check_rows(table: str, rows: list[dict[str, Any]]) -> None:
    """检查必填值与唯一键重复；错误信息只含表名/行号，不含数据内容。"""
    required = REQUIRED_VALUES.get(table, ())
    for index, row in enumerate(rows, start=1):
        for key in required:
            if row.get(key) is None or row.get(key) == "":
                raise BackupValidationError(
                    "missing_value", f"{table} 第 {index} 行缺少 {key}")
    keys = UNIQUE_KEYS.get(table)
    if not keys:
        return
    for key_cols in keys:
        seen: set[tuple[Any, ...]] = set()
        for row in rows:
            value = tuple(row.get(k) for k in key_cols)
            if value in seen:
                raise BackupValidationError(
                    "duplicate_key",
                    f"{table} 存在重复键：{', '.join(key_cols)}",
                )
            seen.add(value)


def _inspect(data: bytes) -> tuple[Preview, dict[str, list[dict[str, Any]]]]:
    """完整预检：结构、版本、校验和、行数、必填与唯一键。"""
    if not data:
        raise BackupValidationError("empty_file", "备份文件为空")
    if len(data) > MAX_ZIP_BYTES:
        raise BackupValidationError("file_too_large", "备份文件超过大小限制")
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise BackupValidationError("invalid_zip", "不是有效的 ZIP 文件") from exc

    with zf:
        members = _zip_members(zf)
        manifest = _load_manifest(zf)
        tables_meta = manifest.get("tables")
        if not isinstance(tables_meta, dict):
            raise BackupValidationError(
                "invalid_manifest", "manifest.tables 缺失或格式不正确")
        unknown = set(tables_meta) - set(TABLE_COLUMNS)
        missing = set(TABLE_COLUMNS) - set(tables_meta)
        if unknown or missing:
            raise BackupValidationError(
                "table_mismatch",
                "备份表清单与当前版本不匹配："
                f"缺少 {sorted(missing)}，未知 {sorted(unknown)}",
            )

        counts: dict[str, int] = {}
        parsed: dict[str, list[dict[str, Any]]] = {}
        for table, columns in TABLE_COLUMNS.items():
            meta = tables_meta[table]
            if not isinstance(meta, dict) or meta.get("columns") != list(columns):
                raise BackupValidationError(
                    "column_mismatch", f"{table} 列定义与当前版本不兼容")
            path = meta.get("file")
            if path != f"{TABLE_DIR}/{table}.jsonl":
                raise BackupValidationError(
                    "invalid_path", f"{table} 的数据文件路径不合法")
            info = members.get(path)
            if info is None:
                raise BackupValidationError(
                    "missing_table", f"备份缺少数据文件：{path}")
            raw = _read_limited(zf, info, MAX_SINGLE_FILE_BYTES)
            expected = meta.get("sha256")
            if not isinstance(expected, str) or not SHA256_RE.fullmatch(expected):
                raise BackupValidationError(
                    "invalid_checksum", f"{table} 的校验和信息无效")
            if not hmac.compare_digest(_sha256(raw), expected):
                raise BackupValidationError(
                    "checksum_mismatch", f"{table} 校验和失败，备份可能已损坏")
            rows = _parse_table_rows(table, raw)
            if meta.get("rows") != len(rows):
                raise BackupValidationError(
                    "row_count_mismatch", f"{table} 行数与清单不一致")
            _check_rows(table, rows)
            parsed[table] = rows
            counts[table] = len(rows)

    created_at = manifest.get("created_at")
    app_version = manifest.get("app_version")
    if not isinstance(created_at, str):
        created_at = ""
    if not isinstance(app_version, str):
        app_version = ""
    current_counts = _current_counts()
    warnings = _preview_warnings(counts, current_counts, created_at, app_version)
    preview = Preview(
        format_version=FORMAT_VERSION,
        app_version=app_version,
        created_at=created_at,
        counts=counts,
        current_counts=current_counts,
        total_rows=sum(counts.values()),
        current_total_rows=sum(current_counts.values()),
        warnings=warnings,
    )
    return preview, parsed


def _current_counts() -> dict[str, int]:
    with db.get_connection() as conn:
        return {
            table: int(conn.execute(
                f"SELECT COUNT(*) FROM {table}").fetchone()[0])
            for table in TABLE_COLUMNS
        }


def _preview_warnings(counts: dict[str, int], current_counts: dict[str, int],
                      created_at: str, app_version: str) -> list[str]:
    warnings: list[str] = []
    if sum(current_counts.values()) > 0:
        warnings.append("恢复会整体替换当前全部用户数据，请先确认安全备份可用")
    if sum(counts.values()) == 0:
        warnings.append("备份中没有任何数据，恢复后会清空当前用户数据")
    if app_version and app_version != __version__:
        warnings.append(
            f"备份由版本 {app_version} 创建，当前版本 {__version__}；"
            "表结构已通过校验，但建议先在独立实例验证")
    if created_at:
        try:
            datetime.fromisoformat(created_at)
        except ValueError:
            warnings.append("备份创建时间格式异常")
    return warnings


def preview_backup(data: bytes) -> Preview:
    """只读预检，不修改任何数据。"""
    preview, _ = _inspect(data)
    return preview


def safety_backup_dir() -> Path:
    path = Path(config.DATA_DIR) / "backups"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _write_safety_backup(payload: bytes) -> str:
    name = f"pre_restore_{_now().strftime('%Y%m%d_%H%M%S_%f')}.zip"
    (safety_backup_dir() / name).write_bytes(payload)
    return name


def restore_backup(data: bytes, *, ip: str | None = None,
                   username: str | None = None) -> RestoreResult:
    """整体替换当前用户数据；先自动备份、单事务写入，失败全部回滚。"""
    if not _restore_guard.acquire(blocking=False):
        raise BackupBusyError("已有恢复任务正在进行")
    try:
        preview, parsed = _inspect(data)

        # 持写锁期间其他写操作会等待；安全备份读取的是恢复前已提交数据。
        with db.get_connection(write=True) as conn:
            safety_name = _write_safety_backup(export_backup_zip())

            for table in TABLE_COLUMNS:
                conn.execute(f"DELETE FROM {table}")

            inserted: dict[str, int] = {}
            for table, rows in parsed.items():
                cols = TABLE_COLUMNS[table]
                if rows:
                    placeholders = ",".join("?" for _ in cols)
                    conn.executemany(
                        f"INSERT INTO {table} ({','.join(cols)}) "
                        f"VALUES ({placeholders})",
                        [[row.get(c) for c in cols] for row in rows],
                    )
                inserted[table] = len(rows)

            # 恢复后旧幂等记录/刷新任务/待审批提案已失去意义，清掉避免重放或
            # 让旧提案指向已被替换的账本数据。
            conn.execute("DELETE FROM agent_operations")
            conn.execute("DELETE FROM refresh_jobs")
            conn.execute("DELETE FROM operation_proposals")

            db.log_audit(
                "restore_backup", ip=ip, username=username,
                detail={
                    "total_rows": preview.total_rows,
                    "safety_backup": safety_name,
                    "tables": inserted,
                },
                conn=conn,
            )
        analysis.clear_analysis_cache()
        return RestoreResult(
            counts=inserted,
            total_rows=sum(inserted.values()),
            safety_backup=safety_name,
        )
    finally:
        _restore_guard.release()
