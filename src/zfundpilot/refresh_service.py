"""任务化服务：数据刷新与定投回测（持久化任务，可轮询）。

网页 ``/api/nav/update`` 把“净值抓取 + 交易回填 + 元数据刷新”混在一起；
Agent 需要的是**纯刷新**：只更新 ``nav_history`` 与 ``funds`` 元数据，绝不调用
``analysis.backfill_transaction_navs()`` 或触发定投。本模块为 Agent 提供持久化
刷新任务：创建即返回 ``job_id``（202），可轮询状态，任务间与网页/调度器共用
互斥锁串行执行。

同一套任务表也承载**只读定投回测**（``job_type="dca_backtest"``）：回测只读
净值并提供 ``result``，不写交易、计划或基金元数据；网页同步回测端点保持不变。

幂等：复用 ``agent_operations``（``operation=<job_type>``），同主体同幂等键
同参数返回原 ``job_id``；同键异参/过期返回冲突。
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import sqlite3
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from . import analysis, backtest, config, db, fetch_fund, scheduler
from .nav_update_state import nav_update_lock, nav_update_state

JOB_TYPE = "data_refresh"
BACKTEST_JOB_TYPE = "dca_backtest"
JOB_TTL_DAYS = 7
MAX_FUND_CODES = 50
IDEMPOTENCY_KEY_MIN = 16
IDEMPOTENCY_KEY_MAX = 128
FUND_CODE_RE = re.compile(r"^[0-9]{6}$")
IDEMPOTENCY_KEY_RE = re.compile(r"^[A-Za-z0-9._~+/=-]+$")
CONTRACT_VERSION = 1
BACKTEST_MAX_CONCURRENCY = 2
BACKTEST_MAX_FUNDS = 5
BACKTEST_MAX_AMOUNT = 1_000_000.0
BACKTEST_MAX_YEARS = 10
BACKTEST_MIN_POINTS = 10
BACKTEST_MAX_POINTS = 2000
BACKTEST_CADENCES = ("month", "week", "biweek")
# 并发已满时提示客户端等待的秒数（HTTP Retry-After）。
BACKTEST_RETRY_AFTER = 60


# 测试可替换：默认后台线程；HTTP/服务测试用同步执行避免轮询。
def _default_spawn(fn: Callable[[], None]) -> None:
    threading.Thread(target=fn, daemon=True).start()


_spawn: Callable[[Callable[[], None]], None] = _default_spawn
_current_job_id: int | None = None
# 回测按进程限制同时执行数；满额快速拒绝（429）而不是排队。
_backtest_gate = threading.BoundedSemaphore(BACKTEST_MAX_CONCURRENCY)
# 保护回测的「查幂等重放 → 占闸 → 建任务」声明段；执行阶段不持锁。
_backtest_lock = threading.Lock()


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
    # 仅 429 等需要提示客户端等待时使用；由 API 层转成 Retry-After 头。
    retry_after: int | None = None

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


def _digest(job_type: str, params: dict[str, Any]) -> str:
    """任务参数摘要：同一幂等键换参数时用于判定 ``idempotency_conflict``。

    刷新任务的参数形状保持 `{"contract", "fund_codes", "job_type"}` 不变，
    避免升级后同一幂等键的旧记录被误判为冲突。
    """
    canonical = json.dumps(
        {"contract": CONTRACT_VERSION, "job_type": job_type, **params},
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
    digest = _digest(JOB_TYPE, {"fund_codes": codes})
    now = _now()
    expires_at = (now + timedelta(days=JOB_TTL_DAYS)).isoformat()

    # 互斥声明：与网页 /api/nav/update 和调度器共用同一把锁与共享运行状态。
    # 只在声明阶段短暂持锁；后台执行阶段不持锁，避免阻塞网页端请求线程。
    global _current_job_id
    with nav_update_lock:
        # 先查幂等重放：任务运行中/超时重试都应拿回原 job_id，而不是 busy。
        with db.get_connection(write=True) as conn:
            replay = _replay(conn, principal, key_hash, digest, ip,
                             job_type=JOB_TYPE)
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

        data = {"job_id": 0, "status": "queued", "fund_count": len(codes),
                "expires_at": expires_at}
        with db.get_connection(write=True) as conn:
            job_id = db.insert_refresh_job(
                conn, principal_type=principal.kind, principal_id=principal.id,
                job_type=JOB_TYPE, params_digest=digest, status="queued",
                created_at=now.isoformat(), updated_at=now.isoformat(),
                expires_at=expires_at,
            )
            data["job_id"] = job_id
            audit_id = _audit(conn, principal, ip, "data_refresh_started", {
                "job_id": job_id, "fund_count": len(codes)})
            db.insert_operation(
                conn, principal_type=principal.kind, principal_id=principal.id,
                key_hash=key_hash, operation=JOB_TYPE, params_digest=digest,
                status="queued",
                result_json=json.dumps(
                    {"job_id": job_id, "data": data}, ensure_ascii=False),
                audit_id=audit_id, created_at=now.isoformat(),
                expires_at=(now + timedelta(days=90)).isoformat(),
            )

        nav_update_state.update({
            "running": True, "total": len(codes), "done": 0,
            "current": "", "phase": "", "error": "",
        })
        _current_job_id = job_id

    _spawn(lambda: _run_job(job_id, codes, principal))
    return RefreshResult(202, "queued", "刷新任务已创建", data, replayed=False)


def _replay(conn: sqlite3.Connection, principal: Any, key_hash: str,
            digest: str, ip: str | None, *,
            job_type: str = JOB_TYPE) -> RefreshResult | None:
    """按幂等键重放任务创建；同键异参/异操作/过期返回 409。"""
    op = db.get_operation(conn, principal.kind, principal.id, key_hash)
    if op is None:
        return None
    mismatch = op["params_digest"] != digest or op["operation"] != job_type
    expired = _expired(op["expires_at"])
    if mismatch or expired:
        code = "idempotency_expired" if expired else "idempotency_conflict"
        message = (
            "幂等键已过期，不能用同一键重试；请使用新的 Idempotency-Key"
            if expired else "同一 Idempotency-Key 已用于不同参数或不同操作")
        _audit(conn, principal, ip, _job_audit_action(job_type, "rejected"), {
            "reason": code, "operation_id": op["id"]})
        return RefreshResult(409, code, message, {"operation_id": op["id"]})
    try:
        payload = json.loads(op["result_json"] or "{}")
    except ValueError:
        payload = {}
    data = dict(payload.get("data") or {})
    data.setdefault("job_id", payload.get("job_id"))
    label = "回测" if job_type == BACKTEST_JOB_TYPE else "刷新"
    return RefreshResult(202, "replayed", f"{label}任务已创建（幂等重放）",
                         data, replayed=True)


def _job_audit_action(job_type: str, suffix: str) -> str:
    prefix = "dca_backtest" if job_type == BACKTEST_JOB_TYPE else "data_refresh"
    return f"{prefix}_{suffix}"


def _backtest_date(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(
            r"\d{4}-\d{2}-\d{2}", value):
        raise RefreshValidationError(field_name, "日期格式必须为 YYYY-MM-DD")
    try:
        datetime.strptime(value, "%Y-%m-%d")
    except ValueError:
        raise RefreshValidationError(field_name, "不是有效日期") from None
    return value


def validate_backtest_params(params: object) -> dict[str, Any]:
    """校验回测参数并返回规范化副本；字段错误抛 ``RefreshValidationError``。

    HTTP 入口已由 Pydantic 模型校验；服务层再校验一次，保证直接调用
    （测试或未来的 MCP 内嵌模式）不会绕过限额。
    """
    if not isinstance(params, dict):
        raise RefreshValidationError("params", "回测参数必须是对象")

    raw_codes = params.get("fund_codes")
    if not isinstance(raw_codes, list) or not raw_codes:
        raise RefreshValidationError(
            "fund_codes", "fund_codes 必须是非空数组")
    if len(raw_codes) > BACKTEST_MAX_FUNDS:
        raise RefreshValidationError(
            "fund_codes", f"单次最多回测 {BACKTEST_MAX_FUNDS} 只基金")
    codes: list[str] = []
    for item in raw_codes:
        if not isinstance(item, str) or not FUND_CODE_RE.fullmatch(item.strip()):
            raise RefreshValidationError(
                "fund_codes", "基金代码必须是 6 位数字")
        code = item.strip()
        if code not in codes:
            codes.append(code)

    start = _backtest_date(params.get("start_date"), "start_date")
    end = _backtest_date(params.get("end_date"), "end_date")
    start_dt = datetime.strptime(start, "%Y-%m-%d").date()
    end_dt = datetime.strptime(end, "%Y-%m-%d").date()
    if start_dt >= end_dt:
        raise RefreshValidationError(
            "end_date", "起始日期必须早于结束日期")
    if end_dt > _now().date():
        raise RefreshValidationError(
            "end_date", "结束日期不能晚于今天")
    months = (end_dt.year - start_dt.year) * 12 + (
        end_dt.month - start_dt.month)
    if months > BACKTEST_MAX_YEARS * 12 or (
            months == BACKTEST_MAX_YEARS * 12 and end_dt.day > start_dt.day):
        raise RefreshValidationError(
            "end_date", f"回测区间不能超过 {BACKTEST_MAX_YEARS} 年")

    amount = params.get("amount_per_period")
    if isinstance(amount, bool) or not isinstance(amount, (int, float)):
        raise RefreshValidationError(
            "amount_per_period", "amount_per_period 必须为数字")
    amount = float(amount)
    if not math.isfinite(amount) or amount <= 0:
        raise RefreshValidationError(
            "amount_per_period", "amount_per_period 必须为有限正数")
    if amount > BACKTEST_MAX_AMOUNT:
        raise RefreshValidationError(
            "amount_per_period",
            f"amount_per_period 不能超过 {BACKTEST_MAX_AMOUNT:g}")

    cadence = params.get("cadence", "month")
    if cadence not in BACKTEST_CADENCES:
        raise RefreshValidationError(
            "cadence", "cadence 必须是 month/week/biweek")
    includes: dict[str, bool] = {}
    include_defaults = {
        "include_lumpsum": True,
        "include_curve": True,
        "include_periods": False,
    }
    for key, default in include_defaults.items():
        value = params.get(key, default)
        if not isinstance(value, bool):
            raise RefreshValidationError(key, f"{key} 必须是布尔值")
        includes[key] = value

    max_points = params.get("max_points", 365)
    if isinstance(max_points, bool) or not isinstance(max_points, int):
        raise RefreshValidationError("max_points", "max_points 必须是整数")
    if not BACKTEST_MIN_POINTS <= max_points <= BACKTEST_MAX_POINTS:
        raise RefreshValidationError(
            "max_points",
            f"max_points 需在 {BACKTEST_MIN_POINTS}–{BACKTEST_MAX_POINTS} 之间")

    return {
        "fund_codes": codes,
        "start_date": start,
        "end_date": end,
        "amount_per_period": amount,
        "cadence": cadence,
        **includes,
        "max_points": max_points,
    }


def start_backtest(principal: Any, *, params: object,
                   idempotency_key: object, ip: str | None = None) -> RefreshResult:
    """创建只读定投回测任务；同键同参返回原 job_id，并发已满返回 429。"""
    clean = validate_backtest_params(params)
    key = validate_idempotency_key(idempotency_key)
    codes = clean["fund_codes"]
    key_hash = _key_hash(key)
    digest = _digest(BACKTEST_JOB_TYPE, clean)
    now = _now()
    expires_at = (now + timedelta(days=JOB_TTL_DAYS)).isoformat()

    with _backtest_lock:
        with db.get_connection(write=True) as conn:
            replay = _replay(conn, principal, key_hash, digest, ip,
                             job_type=BACKTEST_JOB_TYPE)
            if replay is not None:
                return replay

        if not _backtest_gate.acquire(blocking=False):
            with db.get_connection(write=True) as conn:
                _audit(conn, principal, ip, "dca_backtest_busy", {
                    "fund_count": len(codes),
                    "max_concurrency": BACKTEST_MAX_CONCURRENCY})
            return RefreshResult(
                429, "backtest_busy",
                "回测并发已满，请稍后重试",
                {"fund_count": len(codes),
                 "max_concurrency": BACKTEST_MAX_CONCURRENCY},
                retry_after=BACKTEST_RETRY_AFTER)

        try:
            data = {"job_id": 0, "status": "queued",
                    "fund_count": len(codes), "expires_at": expires_at}
            with db.get_connection(write=True) as conn:
                job_id = db.insert_refresh_job(
                    conn, principal_type=principal.kind,
                    principal_id=principal.id, job_type=BACKTEST_JOB_TYPE,
                    params_digest=digest, status="queued",
                    created_at=now.isoformat(), updated_at=now.isoformat(),
                    expires_at=expires_at,
                )
                data["job_id"] = job_id
                audit_id = _audit(conn, principal, ip, "dca_backtest_started", {
                    "job_id": job_id, "fund_count": len(codes)})
                db.insert_operation(
                    conn, principal_type=principal.kind,
                    principal_id=principal.id, key_hash=key_hash,
                    operation=BACKTEST_JOB_TYPE, params_digest=digest,
                    status="queued",
                    result_json=json.dumps(
                        {"job_id": job_id, "data": data}, ensure_ascii=False),
                    audit_id=audit_id, created_at=now.isoformat(),
                    expires_at=(now + timedelta(days=90)).isoformat(),
                )
        except BaseException:
            _backtest_gate.release()
            raise

    _spawn(lambda: _run_backtest_job(job_id, clean, principal))
    return RefreshResult(202, "queued", "回测任务已创建", data, replayed=False)


def _backtest_result_data(results: list[Any],
                          params: dict[str, Any]) -> dict[str, Any]:
    """把 ``BacktestResult`` 列表整理为任务结果（抽样曲线、按需返回明细）。"""
    payload: list[dict[str, Any]] = []
    for result in results:
        row = result.to_dict()
        curve = row.get("curve") or []
        periods = row.get("periods_detail") or []
        row["curve"] = (
            backtest.sample_points(curve, params["max_points"])
            if params["include_curve"] else []
        )
        row["periods_detail"] = periods if params["include_periods"] else []
        row["curve_points"] = len(row["curve"])
        row["periods_detail_count"] = len(periods)
        payload.append(row)

    failed = sum(1 for row in payload if row["status"] == "failed")
    ok = failed < len(payload) and bool(payload)
    message = ""
    if not ok:
        message = "所有基金回测失败，详见各结果的 status/code/message"
    elif failed:
        message = f"{failed} 个回测失败，详见各结果的 status/code/message"

    return {
        "ok": ok,
        "message": message,
        "simulation_note": (
            "定投与一次性投入为历史模拟，不是组合配置建议，也不代表未来收益；"
            "未模拟分红、拆分与红利再投资。"
        ),
        "requested": {
            "start_date": params["start_date"],
            "end_date": params["end_date"],
            "cadence": params["cadence"],
            "amount_per_period": params["amount_per_period"],
            "include_lumpsum": params["include_lumpsum"],
        },
        "fund_count": len(params["fund_codes"]),
        "result_count": len(payload),
        "failed_count": failed,
        "results": payload,
    }


def _run_backtest_job(job_id: int, params: dict[str, Any],
                      principal: Any) -> None:
    """后台执行：按基金逐个回测并推进进度，结果写入 ``result_json``。

    只读净值（``readonly_nav_rows``），不写交易、计划或基金元数据；
    每个基金独立执行，``done`` 为已完成数，``current`` 指向正在执行的基金。
    首次状态写入也在 try 内：即使它失败（如数据库忙），finally 仍归还并发名额。
    """
    codes = params["fund_codes"]
    try:
        ts = _now().isoformat()
        with db.get_connection(write=True) as conn:
            db.update_refresh_job(
                conn, job_id, status="running", total=len(codes),
                phase="backtest", updated_at=ts)
        results: list[Any] = []
        for index, code in enumerate(codes, start=1):
            ts = _now().isoformat()
            with db.get_connection(write=True) as conn:
                db.update_refresh_job(
                    conn, job_id, current=code, updated_at=ts)
            results.extend(backtest.run_dca_backtest(
                fund_codes=[code],
                start_date=params["start_date"],
                end_date=params["end_date"],
                amount_per_period=params["amount_per_period"],
                cadence=params["cadence"],
                include_lumpsum=params["include_lumpsum"],
                nav_provider=backtest.readonly_nav_rows,
            ))
            ts = _now().isoformat()
            with db.get_connection(write=True) as conn:
                db.update_refresh_job(
                    conn, job_id, done=index, updated_at=ts)

        data = _backtest_result_data(results, params)
        ts = _now().isoformat()
        with db.get_connection(write=True) as conn:
            db.update_refresh_job(
                conn, job_id, status="succeeded", done=len(codes),
                current="", phase="",
                result_json=json.dumps(data, ensure_ascii=False),
                updated_at=ts)
            _audit(conn, principal, None, "dca_backtest_succeeded", {
                "job_id": job_id, "result_count": data["result_count"],
                "failed_count": data["failed_count"]})
    except Exception as exc:  # noqa: BLE001
        ts = _now().isoformat()
        with db.get_connection(write=True) as conn:
            db.update_refresh_job(
                conn, job_id, status="failed", error=str(exc),
                result_json=json.dumps({"ok": False}, ensure_ascii=False),
                updated_at=ts)
            _audit(conn, principal, None, "dca_backtest_failed", {
                "job_id": job_id, "error": str(exc)[:200]})
    finally:
        _backtest_gate.release()


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
                404, "not_found", "未找到任务",
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
    首次状态写入也在 try 内：即使它失败（如数据库忙），finally 仍清除运行态，
    避免后续刷新永久 ``refresh_busy``。
    """
    try:
        now = _now().isoformat()
        with db.get_connection(write=True) as conn:
            db.update_refresh_job(
                conn, job_id, status="running", total=len(codes), updated_at=now)

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
