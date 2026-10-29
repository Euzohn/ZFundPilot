"""任务化数据刷新服务（受控写入，仅净值/元数据，不触碰交易与计划）。

网页 ``/api/nav/update`` 把“净值抓取 + 交易回填 + 元数据刷新”混在一起；
Agent 需要的是**纯刷新**：只更新 ``nav_history`` 与 ``funds`` 元数据，绝不调用
``analysis.backfill_transaction_navs()`` 或触发定投。本模块为 Agent 提供持久化
刷新任务：创建即返回 ``job_id``（202），可轮询状态，任务间与网页/调度器共用
互斥锁串行执行。

幂等：复用 ``agent_operations``（``operation="data_refresh"``），同主体同幂等键
同参数返回原 ``job_id``；同键异参/过期返回冲突。
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from . import analysis, config, db, fetch_fund, scheduler
from .nav_update_state import nav_update_lock, nav_update_state

JOB_TYPE = "data_refresh"
JOB_TTL_DAYS = 7
MAX_FUND_CODES = 50
IDEMPOTENCY_KEY_MIN = 16
IDEMPOTENCY_KEY_MAX = 128
FUND_CODE_RE = re.compile(r"^[0-9]{6}$")
IDEMPOTENCY_KEY_RE = re.compile(r"^[A-Za-z0-9._~+/=-]+$")
CONTRACT_VERSION = 1


# 测试可替换：默认后台线程；HTTP/服务测试用同步执行避免轮询。
def _default_spawn(fn: Callable[[], None]) -> None:
    threading.Thread(target=fn, daemon=True).start()


_spawn: Callable[[Callable[[], None]], None] = _default_spawn
_current_job_id: int | None = None


class RefreshValidationError(ValueError):
    """输入校验失败（映射为 HTTP 422）；不创建任务、不写幂等记录。"""

    def __init__(self, field_name: str, message: str) -> None:
        super().__init__(message)
        self.field = field_name
        self.message = message


@dataclass(frozen=True)
class Principal:
    """刷新任务主体：与自选服务结构一致，但由本模块独立定义避免隐式耦合。"""

    kind: str  # "agent_token" | "web"
    id: str
    display: str

    def __post_init__(self) -> None:
        if self.kind not in ("agent_token", "web"):
            raise ValueError(f"未知刷新主体类型：{self.kind}")
        if not self.id:
            raise ValueError("刷新主体缺少 id")


@dataclass(frozen=True)
class RefreshResult:
    http_status: int
    code: str
    message: str
    data: dict = field(default_factory=dict)
    replayed: bool = False

    @property
    def ok(self) -> bool:
        return self.http_status < 400


def validate_fund_codes(value: object) -> list[str] | None:
    """校验基金代码列表；None 表示使用当前开仓持仓，不接受空列表。"""
    if value is None:
        return None
    if not isinstance(value, list):
        raise RefreshValidationError("fund_codes", "fund_codes 必须是数组")
    if not value:
        raise RefreshValidationError("fund_codes", "fund_codes 不能为空")
    if len(value) > MAX_FUND_CODES:
        raise RefreshValidationError(
            "fund_codes", f"单次最多刷新 {MAX_FUND_CODES} 只基金")
    codes: list[str] = []
    for item in value:
        if not isinstance(item, str) or not FUND_CODE_RE.fullmatch(item.strip()):
            raise RefreshValidationError(
                "fund_codes", "基金代码必须是 6 位数字")
        code = item.strip()
        if code not in codes:
            codes.append(code)
    return codes


def validate_idempotency_key(value: object) -> str:
    if not isinstance(value, str):
        raise RefreshValidationError(
            "idempotency_key", "缺少 Idempotency-Key 请求头")
    if not (IDEMPOTENCY_KEY_MIN <= len(value) <= IDEMPOTENCY_KEY_MAX):
        raise RefreshValidationError(
            "idempotency_key",
            f"Idempotency-Key 长度需在 {IDEMPOTENCY_KEY_MIN}–{IDEMPOTENCY_KEY_MAX} 之间")
    if not IDEMPOTENCY_KEY_RE.fullmatch(value):
        raise RefreshValidationError(
            "idempotency_key", "Idempotency-Key 含不支持的字符")
    return value


def _key_hash(key: str) -> str:
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def _digest(codes: list[str]) -> str:
    canonical = json.dumps(
        {"contract": CONTRACT_VERSION, "job_type": JOB_TYPE,
         "fund_codes": codes},
        sort_keys=True, ensure_ascii=False, separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _now() -> datetime:
    return datetime.now(config.TIMEZONE)


def _expired(expires_at: str | None) -> bool:
    if not expires_at:
        return False
    try:
        return datetime.fromisoformat(expires_at) <= _now()
    except (TypeError, ValueError):
        return True


def _open_holding_codes() -> list[str]:
    """当前开仓持仓基金代码（去重，按市值降序由 calculate_positions 保证）。"""
    positions = analysis.calculate_positions()
    seen: list[str] = []
    for p in positions:
        if p.is_open and p.fund_code not in seen:
            seen.append(p.fund_code)
    return seen[:MAX_FUND_CODES]


def start_refresh(principal: Any, *, fund_codes: object,
                  idempotency_key: object, ip: str | None = None) -> RefreshResult:
    """创建刷新任务；同键同参返回原 job_id，刷新中返回 ``refresh_busy``。"""
    codes = validate_fund_codes(fund_codes)
    key = validate_idempotency_key(idempotency_key)
    if codes is None:
        codes = _open_holding_codes()
    if not codes:
        raise RefreshValidationError(
            "fund_codes", "没有可刷新的基金：请先添加持仓或显式传入 fund_codes")

    key_hash = _key_hash(key)
    digest = _digest(codes)
    now = _now()

    # 互斥声明：与网页 /api/nav/update 和调度器共用同一把锁与共享运行状态。
    # 只在声明阶段短暂持锁；后台执行阶段不持锁，避免阻塞网页端请求线程。
    global _current_job_id
    with nav_update_lock:
        # 先查幂等重放：任务运行中/超时重试都应拿回原 job_id，而不是 busy。
        with db.get_connection(write=True) as conn:
            replay = _replay(conn, principal, key_hash, digest, ip)
            if replay is not None:
                return replay

        if nav_update_state["running"]:
            with db.get_connection(write=True) as conn:
                _audit(conn, principal, ip, "data_refresh_busy", {
                    "fund_count": len(codes),
                    "current_job_id": _current_job_id})
            return RefreshResult(
                409, "refresh_busy",
                "已有净值更新/刷新在运行，请稍后重试或轮询当前任务",
                {"fund_count": len(codes),
                 "current_job_id": _current_job_id})

        with db.get_connection(write=True) as conn:
            job_id = db.insert_refresh_job(
                conn, principal_type=principal.kind, principal_id=principal.id,
                job_type=JOB_TYPE, params_digest=digest, status="queued",
                created_at=now.isoformat(), updated_at=now.isoformat(),
                expires_at=(now + timedelta(days=JOB_TTL_DAYS)).isoformat(),
            )
            audit_id = _audit(conn, principal, ip, "data_refresh_started", {
                "job_id": job_id, "fund_count": len(codes)})
            db.insert_operation(
                conn, principal_type=principal.kind, principal_id=principal.id,
                key_hash=key_hash, operation=JOB_TYPE, params_digest=digest,
                status="queued",
                result_json=json.dumps({"job_id": job_id}, ensure_ascii=False),
                audit_id=audit_id, created_at=now.isoformat(),
                expires_at=(now + timedelta(days=90)).isoformat(),
            )

        nav_update_state.update({
            "running": True, "total": len(codes), "done": 0,
            "current": "", "phase": "", "error": "",
        })
        _current_job_id = job_id

    _spawn(lambda: _run_job(job_id, codes, principal))
    return RefreshResult(
        202, "queued", "刷新任务已创建",
        {"job_id": job_id, "status": "queued", "fund_count": len(codes),
         "expires_at": (now + timedelta(days=JOB_TTL_DAYS)).isoformat()},
        replayed=False)


def _replay(conn: sqlite3.Connection, principal: Any, key_hash: str,
            digest: str, ip: str | None) -> RefreshResult | None:
    op = db.get_operation(conn, principal.kind, principal.id, key_hash)
    if op is None:
        return None
    mismatch = op["params_digest"] != digest or op["operation"] != JOB_TYPE
    expired = _expired(op["expires_at"])
    if mismatch or expired:
        code = "idempotency_expired" if expired else "idempotency_conflict"
        message = (
            "幂等键已过期，不能用同一键重试；请使用新的 Idempotency-Key"
            if expired else "同一 Idempotency-Key 已用于不同参数或不同操作")
        _audit(conn, principal, ip, "data_refresh_rejected", {
            "reason": code, "operation_id": op["id"]})
        return RefreshResult(409, code, message, {"operation_id": op["id"]})
    try:
        payload = json.loads(op["result_json"] or "{}")
    except ValueError:
        payload = {}
    data = dict(payload.get("data") or {})
    data.setdefault("job_id", payload.get("job_id"))
    return RefreshResult(202, "replayed", "刷新任务已创建（幂等重放）",
                         data, replayed=True)


def _audit(conn: sqlite3.Connection, principal: Any, ip: str | None,
           action: str, detail: dict) -> int | None:
    return db.log_audit(
        action, ip=ip, username=principal.display,
        detail={**detail, "token_id": principal.id
                if getattr(principal, "kind", "") == "agent_token" else None},
        conn=conn,
    )


def get_job_status(principal: Any, job_id: object) -> RefreshResult:
    """按归属读取任务；他人任务视为不存在，返回 404。"""
    if isinstance(job_id, bool) or not isinstance(job_id, int) or job_id <= 0:
        raise RefreshValidationError("job_id", "job_id 必须是正整数")
    with db.get_connection() as conn:
        row = db.get_refresh_job(conn, job_id, principal.kind, principal.id)
        if row is None:
            return RefreshResult(
                404, "not_found", "未找到刷新任务",
                {"job_id": job_id})
    data = _job_row_to_dict(row)
    if (data["status"] in ("queued", "running")
            and _expired(data["expires_at"])):
        data["status"] = "interrupted"
    return RefreshResult(200, "ok", "任务状态", data)


def _job_row_to_dict(row: sqlite3.Row) -> dict:
    result: dict[str, Any] = {}
    if row["result_json"]:
        try:
            result = json.loads(row["result_json"])
        except ValueError:
            result = {}
    return {
        "job_id": row["id"],
        "job_type": row["job_type"],
        "status": row["status"],
        "progress": {
            "done": row["done"],
            "total": row["total"],
            "current": row["current"] or "",
            "phase": row["phase"] or "",
        },
        "result": result,
        "error": row["error"] or "",
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "expires_at": row["expires_at"],
        "can_cancel": False,
    }


def _run_job(job_id: int, codes: list[str], principal: Any) -> None:
    """后台执行：抓净值 + 刷元数据，绝不回填交易或执行定投。

    不持有 ``nav_update_lock`` 执行（仅启动时由 ``start_refresh`` 短暂声明），
    避免阻塞网页 ``/api/nav/update`` 的请求线程；结束/失败时在锁内清除运行态。
    """
    now = _now().isoformat()
    with db.get_connection(write=True) as conn:
        db.update_refresh_job(
            conn, job_id, status="running", total=len(codes), updated_at=now)
    try:
        def _progress(done: int, total: int, code: str) -> None:
            nav_update_state.update({"done": done, "total": total,
                                     "current": code})
            ts = _now().isoformat()
            with db.get_connection(write=True) as conn:
                db.update_refresh_job(
                    conn, job_id, done=done, current=code, updated_at=ts)

        results = fetch_fund.update_all_holdings_nav(
            codes=codes, progress=_progress)
        nav_update_state["results"] = [r.__dict__ for r in results]
        analysis.clear_analysis_cache()
        nav_update_state["phase"] = "metadata"
        ts = _now().isoformat()
        with db.get_connection(write=True) as conn:
            db.update_refresh_job(conn, job_id, phase="metadata", updated_at=ts)

        def _set_phase(phase: str) -> None:
            nav_update_state["phase"] = phase
            ts = _now().isoformat()
            with db.get_connection(write=True) as conn:
                db.update_refresh_job(conn, job_id, phase=phase, updated_at=ts)

        scheduler.refresh_fund_metadata(on_phase=_set_phase)
        analysis.clear_analysis_cache()

        updated = [r.fund_code for r in results if r.ok]
        errors = [{"fund_code": r.fund_code, "code": r.code,
                   "message": str(r.message)[:200]}
                  for r in results if not r.ok]
        result_json = json.dumps(
            {"ok": not errors, "updated": len(updated),
             "failed": len(errors),
             "partial": bool(errors) and bool(updated),
             "errors": errors},
            ensure_ascii=False)
        ts = _now().isoformat()
        with db.get_connection(write=True) as conn:
            db.update_refresh_job(
                conn, job_id, status="succeeded", done=len(results),
                current="", result_json=result_json, updated_at=ts)
            _audit(conn, principal, None, "data_refresh_succeeded", {
                "job_id": job_id, "updated": len(updated),
                "failed": len(errors)})
    except Exception as exc:  # noqa: BLE001
        ts = _now().isoformat()
        with db.get_connection(write=True) as conn:
            db.update_refresh_job(
                conn, job_id, status="failed", error=str(exc),
                result_json=json.dumps({"ok": False}, ensure_ascii=False),
                updated_at=ts)
            _audit(conn, principal, None, "data_refresh_failed", {
                "job_id": job_id, "error": str(exc)[:200]})
    finally:
        global _current_job_id
        with nav_update_lock:
            nav_update_state.update({
                "running": False, "current": "", "phase": ""})
            _current_job_id = None


def mark_interrupted_on_startup() -> int:
    """应用启动时调用：遗留 queued/running 任务标记 interrupted，并清理旧记录。"""
    now = _now()
    # 任务本身 7 天有效；记录再多留 30 天便于排障，之后删除。
    db.purge_refresh_jobs((now - timedelta(days=30)).isoformat())
    return db.mark_interrupted_refresh_jobs(now.isoformat())
