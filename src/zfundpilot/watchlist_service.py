"""自选维护业务服务（受控写入）。

网页与 Agent 共用本模块，避免把路由函数直接当写工具调用：

- 单一事务内完成幂等检查、版本校验、业务写入、业务结果审计；
- 同主体同幂等键只执行一次，重放返回原结果；同键换参数返回冲突；
- 所有写入都以 revision 做前置条件，防止覆盖网页/Agent 的并发修改；
- 删除保留墓碑前值与单调版本，供网页管理员确认后恢复。
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta

from . import config, db

OPERATION_TTL_DAYS = 90
NOTE_MAX_LEN = 500
GROUP_MAX_LEN = 50
IDEMPOTENCY_KEY_MIN = 16
IDEMPOTENCY_KEY_MAX = 128
CONTRACT_VERSION = 1
MAX_REVISION = 2**53

FUND_CODE_RE = re.compile(r"^[0-9]{6}$")
IDEMPOTENCY_KEY_RE = re.compile(r"^[A-Za-z0-9._~+/=-]+$")

_UNSET = object()
# 对调用方公开的哨兵：表示“本次不修改该字段”。
UNSET = _UNSET


class WatchlistValidationError(ValueError):
    """输入校验失败（映射为 HTTP 422）；不占用幂等键、不写业务数据。"""

    def __init__(self, field_name: str, message: str) -> None:
        super().__init__(message)
        self.field = field_name
        self.message = message


@dataclass(frozen=True)
class Principal:
    """写入主体：区分网页管理员与具体 Agent token，幂等与审计按主体隔离。"""

    kind: str  # "agent_token" | "web"
    id: str
    display: str

    def __post_init__(self) -> None:
        if self.kind not in ("agent_token", "web"):
            raise ValueError(f"未知写入主体类型：{self.kind}")
        if not self.id:
            raise ValueError("写入主体缺少 id")


@dataclass(frozen=True)
class WatchlistResult:
    """业务结果；服务层不抛业务异常，由调用方映射为 HTTP 状态。"""

    http_status: int
    code: str
    message: str
    data: dict = field(default_factory=dict)
    replayed: bool = False

    @property
    def ok(self) -> bool:
        return self.http_status < 400


# ---------------------------------------------------------------------------
# 输入校验与规范化
# ---------------------------------------------------------------------------
def validate_fund_code(value: object) -> str:
    if not isinstance(value, str):
        raise WatchlistValidationError("fund_code", "基金代码必须是字符串")
    code = value.strip()
    if not FUND_CODE_RE.fullmatch(code):
        raise WatchlistValidationError("fund_code", "基金代码必须是 6 位数字")
    return code


def validate_note(value: object) -> str:
    if not isinstance(value, str):
        raise WatchlistValidationError("note", "备注必须是字符串")
    note = value.strip()
    if "\x00" in note:
        raise WatchlistValidationError("note", "备注不能包含空字符")
    if len(note) > NOTE_MAX_LEN:
        raise WatchlistValidationError(
            "note", f"备注最多 {NOTE_MAX_LEN} 个字符")
    return note


def validate_group_name(value: object) -> str:
    if not isinstance(value, str):
        raise WatchlistValidationError("group_name", "分组必须是字符串")
    group = value.strip()
    if "\x00" in group:
        raise WatchlistValidationError("group_name", "分组不能包含空字符")
    if len(group) > GROUP_MAX_LEN:
        raise WatchlistValidationError(
            "group_name", f"分组最多 {GROUP_MAX_LEN} 个字符")
    return group


def validate_expected_revision(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise WatchlistValidationError(
            "expected_revision", "expected_revision 必须是整数")
    if not (1 <= value <= MAX_REVISION):
        raise WatchlistValidationError(
            "expected_revision", "expected_revision 超出有效范围")
    return value


def validate_idempotency_key(value: object) -> str:
    if not isinstance(value, str):
        raise WatchlistValidationError(
            "idempotency_key", "缺少 Idempotency-Key 请求头")
    if not (IDEMPOTENCY_KEY_MIN <= len(value) <= IDEMPOTENCY_KEY_MAX):
        raise WatchlistValidationError(
            "idempotency_key",
            f"Idempotency-Key 长度需在 "
            f"{IDEMPOTENCY_KEY_MIN}–{IDEMPOTENCY_KEY_MAX} 之间")
    if not IDEMPOTENCY_KEY_RE.fullmatch(value):
        raise WatchlistValidationError(
            "idempotency_key", "Idempotency-Key 含不支持的字符")
    return value


def _key_hash(key: str) -> str:
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def _digest(operation: str, payload: dict) -> str:
    canonical = json.dumps(
        {"contract": CONTRACT_VERSION, "operation": operation, **payload},
        sort_keys=True, ensure_ascii=False, separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _now() -> datetime:
    return datetime.now(config.TIMEZONE)


def _item_data(row: sqlite3.Row) -> dict:
    return {
        "fund_code": row["fund_code"],
        "note": row["note"] or "",
        "group_name": row["group_name"] or "",
        "added_at": row["added_at"],
        "revision": row["revision"],
    }


# ---------------------------------------------------------------------------
# 幂等重放与结果落库
# ---------------------------------------------------------------------------
def _expired(expires_at: str | None) -> bool:
    if not expires_at:
        return False
    try:
        return datetime.fromisoformat(expires_at) <= _now()
    except (TypeError, ValueError):
        return True


def _replay(conn: sqlite3.Connection, principal: Principal, key_hash: str,
            operation: str, digest: str, ip: str | None) -> WatchlistResult | None:
    """查找同主体同键的历史结果；不存在返回 None。

    同键不同参数/操作直接冲突，绝不执行第二次；过期键同样拒绝复用。
    """
    op = db.get_operation(conn, principal.kind, principal.id, key_hash)
    if op is None:
        return None

    mismatch = op["params_digest"] != digest or op["operation"] != operation
    expired = _expired(op["expires_at"])
    if mismatch or expired:
        code = "idempotency_expired" if expired else "idempotency_conflict"
        message = (
            "幂等键已过期，不能用同一键重试；请使用新的 Idempotency-Key"
            if expired else
            "同一 Idempotency-Key 已用于不同参数或不同操作"
        )
        db.log_audit(
            "watchlist_write_rejected", ip=ip, username=principal.display,
            detail={"operation": operation, "reason": code,
                    "token_id": principal.id if principal.kind == "agent_token"
                    else None},
            conn=conn,
        )
        return WatchlistResult(409, code, message, {"operation_id": op["id"]})

    try:
        payload = json.loads(op["result_json"] or "{}")
    except ValueError:
        payload = {}
    data = dict(payload.get("data") or {})
    data["operation_id"] = op["id"]
    data["audit_id"] = op["audit_id"]
    return WatchlistResult(
        int(payload.get("http_status", 200)),
        str(payload.get("code", "replayed")),
        str(payload.get("message", "")),
        data,
        replayed=True,
    )


def _finish(conn: sqlite3.Connection, principal: Principal, key_hash: str,
            operation: str, digest: str, result: WatchlistResult,
            audit_action: str, audit_detail: dict,
            ip: str | None) -> WatchlistResult:
    """同一事务内写业务结果审计与幂等记录。"""
    audit_id = db.log_audit(
        audit_action, ip=ip, username=principal.display,
        detail={
            **audit_detail,
            "operation": operation,
            "result": result.code,
            "http_status": result.http_status,
            "replayed": False,
        },
        conn=conn,
    )
    now = _now()
    operation_id = db.insert_operation(
        conn,
        principal_type=principal.kind,
        principal_id=principal.id,
        key_hash=key_hash,
        operation=operation,
        params_digest=digest,
        status=result.code,
        result_json=json.dumps(
            {"http_status": result.http_status, "code": result.code,
             "message": result.message, "data": result.data},
            ensure_ascii=False,
        ),
        audit_id=audit_id,
        created_at=now.isoformat(),
        expires_at=(now + timedelta(days=OPERATION_TTL_DAYS)).isoformat(),
    )
    return replace(result, data={
        **result.data, "operation_id": operation_id, "audit_id": audit_id,
    })


# ---------------------------------------------------------------------------
# 业务操作
# ---------------------------------------------------------------------------
def add_item(principal: Principal, *, fund_code: object, note: object = "",
             group_name: object = "", idempotency_key: object,
             ip: str | None = None) -> WatchlistResult:
    """新增自选；已存在返回冲突，不覆盖已有备注或分组。"""
    code = validate_fund_code(fund_code)
    clean_note = validate_note("" if note is None else note)
    clean_group = validate_group_name("" if group_name is None else group_name)
    key_hash = _key_hash(validate_idempotency_key(idempotency_key))
    digest = _digest("add", {"fund_code": code, "note": clean_note,
                             "group_name": clean_group})

    with db.get_connection(write=True) as conn:
        replay = _replay(conn, principal, key_hash, "add", digest, ip)
        if replay is not None:
            return replay

        if not db.fund_exists(conn, code):
            return _finish(
                conn, principal, key_hash, "add", digest,
                WatchlistResult(
                    409, "fund_not_registered",
                    "基金尚未收录，请先在网页基金页添加或刷新基金信息",
                    {"fund_code": code},
                ),
                "watchlist_add", {"fund_code": code, "changed": False}, ip,
            )

        existing = db.get_watchlist_item(conn, code)
        if existing is not None:
            return _finish(
                conn, principal, key_hash, "add", digest,
                WatchlistResult(
                    409, "already_exists", "该基金已在自选中",
                    {"fund_code": code,
                     "revision": existing["revision"],
                     "after": _item_data(existing)},
                ),
                "watchlist_add", {"fund_code": code, "changed": False}, ip,
            )

        tomb = db.get_watchlist_tombstone(conn, code)
        revision = (tomb["revision"] + 1) if tomb is not None else 1
        db.insert_watchlist_item(conn, code, clean_note, clean_group, revision)
        if tomb is not None:
            db.delete_watchlist_tombstone(conn, code)

        row = db.get_watchlist_item(conn, code)
        return _finish(
            conn, principal, key_hash, "add", digest,
            WatchlistResult(
                200, "created", "已添加到自选",
                {"fund_code": code, "revision": revision, "changed": True,
                 "before": None, "after": _item_data(row)},
            ),
            "watchlist_add",
            {"fund_code": code, "changed": True, "revision": revision,
             "group_name": clean_group, "note_len": len(clean_note)},
            ip,
        )


def update_item(principal: Principal, *, fund_code: object,
                expected_revision: object, note: object = _UNSET,
                group_name: object = _UNSET, idempotency_key: object,
                ip: str | None = None) -> WatchlistResult:
    """按 revision 更新备注/分组；未提供的字段保持不变。"""
    code = validate_fund_code(fund_code)
    expected = validate_expected_revision(expected_revision)
    patch: dict[str, str] = {}
    if note is not _UNSET:
        patch["note"] = validate_note(note)
    if group_name is not _UNSET:
        patch["group_name"] = validate_group_name(group_name)
    if not patch:
        raise WatchlistValidationError(
            "patch", "至少提供一个要修改的字段：note 或 group_name")

    key_hash = _key_hash(validate_idempotency_key(idempotency_key))
    digest = _digest("update", {"fund_code": code, "patch": patch,
                                "expected_revision": expected})

    with db.get_connection(write=True) as conn:
        replay = _replay(conn, principal, key_hash, "update", digest, ip)
        if replay is not None:
            return replay

        row = db.get_watchlist_item(conn, code)
        if row is None:
            return _finish(
                conn, principal, key_hash, "update", digest,
                WatchlistResult(
                    404, "not_found", "该基金不在自选中",
                    {"fund_code": code},
                ),
                "watchlist_update", {"fund_code": code, "changed": False}, ip,
            )

        if row["revision"] != expected:
            return _finish(
                conn, principal, key_hash, "update", digest,
                WatchlistResult(
                    409, "revision_conflict",
                    "自选已被修改，请重新读取后再试",
                    {"fund_code": code, "current_revision": row["revision"],
                     "current": _item_data(row)},
                ),
                "watchlist_update",
                {"fund_code": code, "changed": False,
                 "revision": row["revision"], "reason": "revision_conflict"},
                ip,
            )

        before = _item_data(row)
        new_note = patch.get("note", before["note"])
        new_group = patch.get("group_name", before["group_name"])
        changed = (new_note != before["note"]
                   or new_group != before["group_name"])

        if changed:
            revision = row["revision"] + 1
            db.update_watchlist_item(conn, code, new_note, new_group, revision)
        else:
            revision = row["revision"]

        after_row = db.get_watchlist_item(conn, code)
        return _finish(
            conn, principal, key_hash, "update", digest,
            WatchlistResult(
                200, "updated" if changed else "unchanged",
                "自选已更新" if changed else "内容未变化",
                {"fund_code": code, "revision": revision, "changed": changed,
                 "before": before, "after": _item_data(after_row)},
            ),
            "watchlist_update",
            {"fund_code": code, "changed": changed, "revision": revision,
             "fields": sorted(patch)},
            ip,
        )


def remove_item(principal: Principal, *, fund_code: object,
                expected_revision: object, idempotency_key: object,
                ip: str | None = None) -> WatchlistResult:
    """按 revision 删除自选，并保留可恢复前值与单调版本。"""
    code = validate_fund_code(fund_code)
    expected = validate_expected_revision(expected_revision)
    key_hash = _key_hash(validate_idempotency_key(idempotency_key))
    digest = _digest("remove", {"fund_code": code,
                                "expected_revision": expected})

    with db.get_connection(write=True) as conn:
        replay = _replay(conn, principal, key_hash, "remove", digest, ip)
        if replay is not None:
            return replay

        row = db.get_watchlist_item(conn, code)
        if row is None:
            return _finish(
                conn, principal, key_hash, "remove", digest,
                WatchlistResult(
                    404, "not_found", "该基金不在自选中",
                    {"fund_code": code},
                ),
                "watchlist_remove", {"fund_code": code, "changed": False}, ip,
            )

        if row["revision"] != expected:
            return _finish(
                conn, principal, key_hash, "remove", digest,
                WatchlistResult(
                    409, "revision_conflict",
                    "自选已被修改，请重新读取后再试",
                    {"fund_code": code, "current_revision": row["revision"],
                     "current": _item_data(row)},
                ),
                "watchlist_remove",
                {"fund_code": code, "changed": False,
                 "revision": row["revision"], "reason": "revision_conflict"},
                ip,
            )

        before = _item_data(row)
        revision = row["revision"] + 1
        db.delete_watchlist_item(conn, code)
        db.upsert_watchlist_tombstone(
            conn, code, revision, before["note"], before["group_name"],
            before["added_at"], _now().isoformat(),
        )
        return _finish(
            conn, principal, key_hash, "remove", digest,
            WatchlistResult(
                200, "removed", "已从自选移除",
                {"fund_code": code, "revision": revision, "changed": True,
                 "before": before, "after": None},
            ),
            "watchlist_remove",
            {"fund_code": code, "changed": True, "revision": revision},
            ip,
        )


def restore_item(principal: Principal, *, fund_code: object,
                 expected_revision: object, idempotency_key: object,
                 ip: str | None = None) -> WatchlistResult:
    """网页管理员恢复已删除自选；不接受 Agent 调用。

    仅当对象仍处于对应墓碑版本时允许恢复，避免覆盖删除后的重建或后续修改。
    """
    if principal.kind != "web":
        raise WatchlistValidationError(
            "principal", "仅网页管理员可以恢复已删除的自选")

    code = validate_fund_code(fund_code)
    expected = validate_expected_revision(expected_revision)
    key_hash = _key_hash(validate_idempotency_key(idempotency_key))
    digest = _digest("restore", {"fund_code": code,
                                 "expected_revision": expected})

    with db.get_connection(write=True) as conn:
        replay = _replay(conn, principal, key_hash, "restore", digest, ip)
        if replay is not None:
            return replay

        tomb = db.get_watchlist_tombstone(conn, code)
        if tomb is None:
            return _finish(
                conn, principal, key_hash, "restore", digest,
                WatchlistResult(
                    404, "not_found", "没有可恢复的删除记录",
                    {"fund_code": code},
                ),
                "watchlist_restore", {"fund_code": code, "changed": False}, ip,
            )

        if tomb["revision"] != expected:
            return _finish(
                conn, principal, key_hash, "restore", digest,
                WatchlistResult(
                    409, "revision_conflict",
                    "删除记录已变化，请重新读取后再试",
                    {"fund_code": code, "current_revision": tomb["revision"]},
                ),
                "watchlist_restore",
                {"fund_code": code, "changed": False,
                 "revision": tomb["revision"], "reason": "revision_conflict"},
                ip,
            )

        if not db.fund_exists(conn, code):
            return _finish(
                conn, principal, key_hash, "restore", digest,
                WatchlistResult(
                    409, "fund_not_registered",
                    "基金基础信息已不存在，无法恢复自选",
                    {"fund_code": code},
                ),
                "watchlist_restore", {"fund_code": code, "changed": False}, ip,
            )

        existing = db.get_watchlist_item(conn, code)
        if existing is not None:
            return _finish(
                conn, principal, key_hash, "restore", digest,
                WatchlistResult(
                    409, "already_exists", "该基金已在自选中",
                    {"fund_code": code, "revision": existing["revision"]},
                ),
                "watchlist_restore", {"fund_code": code, "changed": False}, ip,
            )

        revision = tomb["revision"] + 1
        db.insert_watchlist_item(
            conn, code, tomb["note"] or "", tomb["group_name"] or "", revision)
        db.delete_watchlist_tombstone(conn, code)
        row = db.get_watchlist_item(conn, code)
        return _finish(
            conn, principal, key_hash, "restore", digest,
            WatchlistResult(
                200, "restored", "已恢复自选",
                {"fund_code": code, "revision": revision, "changed": True,
                 "before": None, "after": _item_data(row)},
            ),
            "watchlist_restore",
            {"fund_code": code, "changed": True, "revision": revision},
            ip,
        )


def list_deleted() -> list[dict]:
    """列出可恢复的删除记录（仅网页管理员使用）。"""
    return db.get_watchlist_tombstones()
