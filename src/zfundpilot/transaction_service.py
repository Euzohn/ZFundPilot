"""Agent 可信单笔直记服务（F0）。

在管理员显式授予 ``transactions:create`` 的 Agent token 上，允许把**用户明确
陈述已在外部平台完成**的单笔普通买入/卖出直接写入账本；其余场景保持既有
提案审批路径。本模块同时提供提案与直记共用的参数校验，确保两条路径永不漂移。

安全边界（服务端可校验 / 不可校验）::

    可校验：凭证、scope、写总闸、结构化参数、基金收录、重复候选、卖出份额、
            单笔与每日额度、未来日期
    不可校验：自然语言是否确由用户发出；不接受任何 Agent 自证字段

执行结果最多一种（交易或提案），由 ``execution_mode`` 显式区分；业务写入、
幂等记录与审计在同一 ``BEGIN IMMEDIATE`` 事务内提交。降级产生的提案复用
创建者提案的校验与 pending 上限，且重放永不把提案升级为直写。
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

from . import agent_tokens, analysis, config, db
from .models import ACTION_BUY, ACTION_SELL, Transaction

if TYPE_CHECKING:  # pragma: no cover - 仅类型检查，避免与 proposal_service 循环导入
    from .proposal_service import Principal

OPERATION_RECORD_TRANSACTION = "record_transaction"
# 执行策略标记：直记与提案使用不同幂等域，同键跨域重试不会互相命中。
IDEMPOTENCY_POLICY = "direct-write-v1"
DIRECT_ACTIONS = frozenset({ACTION_BUY, ACTION_SELL})
ACTION_LABELS = {
    "buy": "买入",
    "sell": "卖出",
    "dividend": "现金分红",
    "reinvest": "红利再投资",
}
DIRECT_SOURCE = "agent"
IDEMPOTENCY_TTL_DAYS = 90
AMOUNT_TOLERANCE = 1e-6

CONTRACT_VERSION = 1
IDEMPOTENCY_KEY_MIN = 16
IDEMPOTENCY_KEY_MAX = 128
NOTE_MAX_LEN = 500
CHANNEL_MAX_LEN = 50
MAX_NUMBER = 1e12

FUND_CODE_RE = re.compile(r"^[0-9]{6}$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
IDEMPOTENCY_KEY_RE = re.compile(r"^[A-Za-z0-9._~+/=-]+$")

# 降级提案的 warnings 文案：解释为何没有直记，提示人工核对。
DOWNGRADE_WARNINGS = {
    "duplicate_candidate": "诊断：账本或待审提案中已存在疑似相同交易，请核对后再批准",
    "insufficient_shares": "诊断：卖出份额可能超过当前可用份额，请核对持仓与 T+1 确认",
    "amount_exceeds_cap": "诊断：单笔金额超过 Agent 直记上限，已转人工确认",
}


class TransactionValidationError(ValueError):
    """共享参数校验失败（映射为 HTTP 422）；不写幂等记录、不消耗额度。"""

    def __init__(self, field_name: str, message: str) -> None:
        super().__init__(message)
        self.field = field_name
        self.message = message


class FutureDateError(TransactionValidationError):
    """直记请求日期晚于今天（Asia/Shanghai）；仅直记路径拒绝。"""

    def __init__(self, date: str, today: str) -> None:
        super().__init__(
            "date",
            f"直记日期不能晚于今天（{today}）；未来交易请使用提案审批",
        )
        self.date = date
        self.today = today


@dataclass(frozen=True)
class DirectWriteResult:
    """执行结果；结构镜像 ``proposal_service.ProposalResult``。"""

    http_status: int
    code: str
    message: str
    data: dict = field(default_factory=dict)
    replayed: bool = False

    @property
    def ok(self) -> bool:
        return self.http_status < 400


def _now() -> datetime:
    return datetime.now(config.TIMEZONE)


def _key_hash(key: str) -> str:
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def _canonical(payload: dict) -> str:
    return json.dumps(
        payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def _digest(params: dict) -> str:
    canonical = _canonical({
        "contract": CONTRACT_VERSION,
        "operation": OPERATION_RECORD_TRANSACTION,
        "policy": IDEMPOTENCY_POLICY,
        "params": params,
    })
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# 共享输入校验（提案路径与直记路径唯一来源）
# ---------------------------------------------------------------------------
def validate_idempotency_key(value: object) -> str:
    if not isinstance(value, str):
        raise TransactionValidationError(
            "idempotency_key", "缺少 Idempotency-Key 请求头")
    if not (IDEMPOTENCY_KEY_MIN <= len(value) <= IDEMPOTENCY_KEY_MAX):
        raise TransactionValidationError(
            "idempotency_key",
            f"Idempotency-Key 长度需在 "
            f"{IDEMPOTENCY_KEY_MIN}–{IDEMPOTENCY_KEY_MAX} 之间")
    if not IDEMPOTENCY_KEY_RE.fullmatch(value):
        raise TransactionValidationError(
            "idempotency_key", "Idempotency-Key 含不支持的字符")
    return value


def clean_text(value: object, field_name: str, max_len: int) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise TransactionValidationError(field_name, f"{field_name} 必须是字符串")
    text = value.strip()
    if "\x00" in text:
        raise TransactionValidationError(field_name, f"{field_name} 不能包含空字符")
    if len(text) > max_len:
        raise TransactionValidationError(
            field_name, f"{field_name} 最多 {max_len} 个字符")
    return text


def _number(value: object, field_name: str) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TransactionValidationError(field_name, f"{field_name} 必须是数字")
    number = float(value)
    if not math.isfinite(number):
        raise TransactionValidationError(field_name, f"{field_name} 必须是有限数字")
    if number < 0:
        raise TransactionValidationError(field_name, f"{field_name} 不能为负数")
    if number > MAX_NUMBER:
        raise TransactionValidationError(field_name, f"{field_name} 超出上限")
    return number


def validate_add_transaction_params(params: object) -> dict[str, Any]:
    """校验并规范化 ``add_transaction`` 参数，返回交易字段字典。"""
    if not isinstance(params, dict):
        raise TransactionValidationError("params", "params 必须是对象")
    allowed = {
        "fund_code", "action", "date", "amount", "shares", "nav",
        "fee", "channel", "note", "is_t1",
    }
    unknown = set(params) - allowed
    if unknown:
        raise TransactionValidationError(
            "params", f"包含不支持的参数：{', '.join(sorted(unknown))}")

    fund_code = params.get("fund_code")
    if not isinstance(fund_code, str) or not FUND_CODE_RE.fullmatch(
            fund_code.strip()):
        raise TransactionValidationError("fund_code", "基金代码必须是 6 位数字")
    fund_code = fund_code.strip()

    action = params.get("action")
    if action not in ACTION_LABELS:
        raise TransactionValidationError(
            "action", f"操作方向必须是：{', '.join(ACTION_LABELS)}")

    date = params.get("date")
    if not isinstance(date, str) or not DATE_RE.fullmatch(date.strip()):
        raise TransactionValidationError("date", "日期必须是 YYYY-MM-DD")
    date = date.strip()
    try:
        datetime.strptime(date, "%Y-%m-%d")
    except ValueError as exc:
        raise TransactionValidationError("date", "日期不是有效日期") from exc

    amount = _number(params.get("amount"), "amount")
    shares = _number(params.get("shares"), "shares")
    nav = _number(params.get("nav"), "nav")
    fee = _number(params.get("fee"), "fee") or 0.0
    channel = clean_text(params.get("channel"), "channel", CHANNEL_MAX_LEN)
    note = clean_text(params.get("note"), "note", NOTE_MAX_LEN)

    is_t1 = params.get("is_t1", False)
    if not isinstance(is_t1, bool):
        raise TransactionValidationError("is_t1", "is_t1 必须是布尔值")

    tx = Transaction(
        fund_code=fund_code, action=action, date=date,
        amount=amount, shares=shares, nav=nav, fee=fee,
        channel=channel, note=note, is_t1=is_t1,
    )
    tx.normalize()
    if not tx.is_valid():
        raise TransactionValidationError(
            "params", "交易信息不完整：买入/再投资需金额或份额，卖出需份额，分红需金额")
    if tx.action == ACTION_BUY and (tx.amount is None or tx.amount <= 0):
        raise TransactionValidationError("amount", "买入金额必须大于 0")

    return {
        "fund_code": tx.fund_code,
        "action": tx.action,
        "date": tx.date,
        "amount": tx.amount,
        "shares": tx.shares,
        "nav": tx.nav,
        "fee": tx.fee,
        "channel": tx.channel,
        "note": tx.note,
        "is_t1": tx.is_t1,
    }


def validate_direct_params(params: object) -> dict[str, Any]:
    """直记专用校验：仅 buy/sell，且日期不得晚于今天。"""
    clean = validate_add_transaction_params(params)
    if clean["action"] not in DIRECT_ACTIONS:
        raise TransactionValidationError(
            "action", "可信直记仅支持 buy / sell；分红、再投资等请使用提案")
    today = _now().date().isoformat()
    if clean["date"] > today:
        raise FutureDateError(clean["date"], today)
    return clean


# ---------------------------------------------------------------------------
# 事务内复核、额度与预检
# ---------------------------------------------------------------------------
def _audit(conn: sqlite3.Connection, principal: Principal, ip: str | None,
           action: str, detail: dict) -> int | None:
    return db.log_audit(
        action, ip=ip, username=principal.display,
        detail={**detail, "token_id": principal.id}, conn=conn,
    )


def _reject(conn: sqlite3.Connection, principal: Principal, ip: str | None,
            http_status: int, code: str, message: str, *,
            detail: dict | None = None, params: dict | None = None) -> DirectWriteResult:
    audit_detail: dict[str, Any] = {"reason": code}
    if params:
        audit_detail.update({
            "fund_code": params.get("fund_code"),
            "action": params.get("action"),
            "date": params.get("date"),
            "amount": params.get("amount"),
            "shares": params.get("shares"),
        })
    if detail:
        for key in ("tx_id", "proposal_id", "available", "cap", "used", "limit"):
            if key in detail:
                audit_detail[key] = detail[key]
    _audit(conn, principal, ip, "agent_direct_rejected", audit_detail)
    return DirectWriteResult(
        http_status, code, message, dict(detail or {}))


def _token_row(conn: sqlite3.Connection,
               principal: Principal) -> sqlite3.Row | None:
    try:
        token_id = int(principal.id)
    except (TypeError, ValueError):
        return None
    return db.get_agent_token_conn(conn, token_id)


def _check_principal_conn(conn: sqlite3.Connection, principal: Principal,
                          now: datetime, ip: str | None,
                          params: dict) -> DirectWriteResult | None:
    """事务内复核 token 状态、直记 scope 与写总闸。"""
    from .proposal_service import token_error  # 延迟导入避免循环依赖

    token_row = _token_row(conn, principal)
    error = token_error(token_row, now)
    if error:
        return _reject(
            conn, principal, ip, 401, error,
            "Agent token 已失效，请重新签发后再试", params=params)
    scopes = frozenset((token_row["scopes"] or "").split())
    if agent_tokens.SCOPE_TRANSACTIONS_CREATE not in scopes:
        return _reject(
            conn, principal, ip, 403, "scope_revoked",
            "Agent token 已失去可信直记权限，请使用提案审批", params=params)
    if not db.agent_write_enabled_conn(conn):
        return _reject(
            conn, principal, ip, 403, "write_disabled",
            "Agent 写能力未启用，请联系管理员开启", params=params)
    return None


def _day_start(now: datetime) -> datetime:
    return now.replace(hour=0, minute=0, second=0, microsecond=0)


def _next_day_start(now: datetime) -> datetime:
    return _day_start(now) + timedelta(days=1)


def _quota_snapshot(conn: sqlite3.Connection, principal: Principal,
                    now: datetime) -> tuple[int, float]:
    """统计今日本主体直记工具产出：笔数含降级，金额只累计直写成功。"""
    rows = conn.execute(
        "SELECT result_json FROM agent_operations "
        "WHERE principal_type=? AND principal_id=? AND operation=? "
        "AND created_at>=?",
        (principal.kind, principal.id, OPERATION_RECORD_TRANSACTION,
         _day_start(now).isoformat()),
    ).fetchall()
    amount = 0.0
    for row in rows:
        try:
            payload = json.loads(row["result_json"] or "{}")
        except ValueError:
            continue
        if payload.get("execution_mode") != "direct":
            continue
        receipt = payload.get("receipt") or {}
        try:
            amount += float(receipt.get("amount") or 0.0)
        except (TypeError, ValueError):
            continue
    return len(rows), amount


def _quota_data(now: datetime, used: int, amount_used: float) -> dict[str, Any]:
    return {
        "used": used,
        "count_limit": int(config.AGENT_TX_DAILY_COUNT),
        "amount_used": round(amount_used, 2),
        "amount_limit": float(config.AGENT_TX_DAILY_AMOUNT),
        "reset_at": _next_day_start(now).isoformat(),
    }


def _same_number(left: object, right: object) -> bool:
    try:
        if left is None or right is None:
            return False
        return abs(float(left) - float(right)) <= AMOUNT_TOLERANCE
    except (TypeError, ValueError):
        return False


def _duplicate_in_ledger(conn: sqlite3.Connection,
                         clean: dict) -> int | None:
    """同基金 + 渠道 + 日期 + 方向且金额或份额精确匹配（容差 1e-6）。"""
    clauses = ["fund_code=?", "COALESCE(channel,'')=?", "date=?", "action=?"]
    values: list[Any] = [
        clean["fund_code"], clean.get("channel") or "",
        clean["date"], clean["action"]]
    matches: list[str] = []
    if clean.get("amount") is not None:
        matches.append("(amount IS NOT NULL AND ABS(amount - ?) <= ?)")
        values.extend([float(clean["amount"]), AMOUNT_TOLERANCE])
    if clean.get("shares") is not None:
        matches.append("(shares IS NOT NULL AND ABS(shares - ?) <= ?)")
        values.extend([float(clean["shares"]), AMOUNT_TOLERANCE])
    if not matches:
        return None
    row = conn.execute(
        "SELECT id FROM transactions WHERE " + " AND ".join(clauses)
        + " AND (" + " OR ".join(matches) + ") ORDER BY id DESC LIMIT 1",
        values,
    ).fetchone()
    return int(row["id"]) if row else None


def _pending_proposal_rows(conn: sqlite3.Connection,
                           now: datetime) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM operation_proposals "
        "WHERE operation_type='add_transaction' AND status='pending' "
        "AND expires_at>?",
        (now.isoformat(),),
    ).fetchall()


def _params_from_row(row: sqlite3.Row) -> dict:
    try:
        params = json.loads(row["params_json"] or "{}")
    except ValueError:
        return {}
    return params if isinstance(params, dict) else {}


def _duplicate_pending_proposal(conn: sqlite3.Connection, clean: dict,
                                now: datetime) -> int | None:
    """含待审提案的重复候选：避免直记与稍后批准的提案重复入账。"""
    for row in _pending_proposal_rows(conn, now):
        params = _params_from_row(row)
        if (params.get("fund_code") != clean["fund_code"]
                or (params.get("channel") or "") != (clean.get("channel") or "")
                or params.get("date") != clean["date"]
                or params.get("action") != clean["action"]):
            continue
        if (_same_number(params.get("amount"), clean.get("amount"))
                or _same_number(params.get("shares"), clean.get("shares"))):
            return int(row["id"])
    return None


def _available_shares(conn: sqlite3.Connection, clean: dict,
                      now: datetime) -> float:
    """同基金同渠道可用份额，扣除全部主体待审卖出提案的份额。"""
    row = conn.execute(
        "SELECT COALESCE(SUM(CASE action "
        "WHEN 'buy' THEN shares WHEN 'reinvest' THEN shares "
        "WHEN 'sell' THEN -shares ELSE 0 END), 0) AS available "
        "FROM transactions WHERE fund_code=? AND COALESCE(channel,'')=?",
        (clean["fund_code"], clean.get("channel") or ""),
    ).fetchone()
    available = float(row["available"] or 0.0)
    for proposal in _pending_proposal_rows(conn, now):
        params = _params_from_row(proposal)
        if (params.get("action") != "sell"
                or params.get("fund_code") != clean["fund_code"]
                or (params.get("channel") or "") != (clean.get("channel") or "")):
            continue
        try:
            available -= float(params.get("shares") or 0.0)
        except (TypeError, ValueError):
            continue
    return available


def _soft_failure(conn: sqlite3.Connection, clean: dict,
                  now: datetime) -> tuple[str, dict[str, Any]] | None:
    """按 §5 顺序返回首个软性失败；无异常返回 None。"""
    duplicate_tx = _duplicate_in_ledger(conn, clean)
    if duplicate_tx is not None:
        return "duplicate_candidate", {"tx_id": duplicate_tx}

    duplicate_proposal = _duplicate_pending_proposal(conn, clean, now)
    if duplicate_proposal is not None:
        return "duplicate_candidate", {"proposal_id": duplicate_proposal}

    if clean["action"] == ACTION_SELL and clean.get("shares") is not None:
        available = _available_shares(conn, clean, now)
        if float(clean["shares"]) > available + AMOUNT_TOLERANCE:
            return "insufficient_shares", {
                "available": round(available, 4),
                "requested": clean["shares"],
            }

    amount = clean.get("amount")
    if (amount is not None
            and float(amount) > float(config.AGENT_TX_MAX_AMOUNT)):
        return "amount_exceeds_cap", {
            "cap": float(config.AGENT_TX_MAX_AMOUNT),
            "amount": amount,
        }
    return None


# ---------------------------------------------------------------------------
# 响应构造
# ---------------------------------------------------------------------------
def _direct_receipt(tx: Transaction, fund_name: str) -> dict[str, Any]:
    unconfirmed: list[str] = []
    if tx.nav is None or tx.is_t1:
        unconfirmed.append("nav")
    if tx.shares is None or tx.is_t1:
        unconfirmed.append("shares")
    warnings: list[str] = []
    if tx.nav is None:
        warnings.append("成交净值尚未确定，市值与收益可能暂时缺失")
    if tx.is_t1:
        warnings.append("T+1 确认：份额可能尚未到账，需后续核对")
    return {
        "fund_code": tx.fund_code,
        "fund_name": fund_name,
        "action": tx.action,
        "action_label": ACTION_LABELS.get(tx.action, tx.action),
        "date": tx.date,
        "amount": tx.amount,
        "shares": tx.shares,
        "nav": tx.nav,
        "fee": tx.fee,
        "channel": tx.channel,
        "note": tx.note,
        "is_t1": tx.is_t1,
        "unconfirmed_fields": unconfirmed,
        "warnings": warnings,
    }


def _proposal_receipt(row: sqlite3.Row, now: datetime) -> dict[str, Any]:
    from .proposal_service import proposal_row_to_dict
    return proposal_row_to_dict(row, now)


def _proposal_mode_data(principal: Principal, *, code: str, message: str,
                        proposal_id: int, operation_id: int | None,
                        replayed: bool, now: datetime,
                        used: int, amount_used: float,
                        proposal_row: sqlite3.Row) -> dict[str, Any]:
    return {
        "ok": True,
        "code": code,
        "message": message,
        "replayed": replayed,
        "execution_mode": "proposal",
        "transaction_id": None,
        "operation_id": operation_id,
        "proposal_id": proposal_id,
        "receipt": _proposal_receipt(proposal_row, now),
        "daily_quota": _quota_data(now, used, amount_used),
        "verify_path": "/proposals",
    }


def _direct_mode_data(*, code: str, message: str, replayed: bool,
                      tx_id: int, operation_id: int | None,
                      receipt: dict, now: datetime,
                      used: int, amount_used: float) -> dict[str, Any]:
    return {
        "ok": True,
        "code": code,
        "message": message,
        "replayed": replayed,
        "execution_mode": "direct",
        "transaction_id": tx_id,
        "operation_id": operation_id,
        "proposal_id": None,
        "receipt": receipt,
        "daily_quota": _quota_data(now, used, amount_used),
        "verify_path": "/transactions",
    }


# ---------------------------------------------------------------------------
# 幂等重放
# ---------------------------------------------------------------------------
def _replay(conn: sqlite3.Connection, principal: Principal, key_hash: str,
            digest: str, now: datetime,
            ip: str | None) -> DirectWriteResult | None:
    op = db.get_operation(conn, principal.kind, principal.id, key_hash)
    if op is None:
        return None
    expired = False
    if op["expires_at"]:
        try:
            expired = datetime.fromisoformat(op["expires_at"]) <= now
        except (TypeError, ValueError):
            expired = True
    if op["operation"] != OPERATION_RECORD_TRANSACTION or (
            op["params_digest"] != digest) or expired:
        code = "idempotency_expired" if expired else "idempotency_conflict"
        message = (
            "幂等键已过期，不能用同一键重试；请使用新的 Idempotency-Key"
            if expired else
            "同一 Idempotency-Key 已用于不同参数或不同操作")
        _audit(conn, principal, ip, "agent_direct_rejected", {
            "reason": code, "operation_id": op["id"]})
        return DirectWriteResult(409, code, message, {"operation_id": op["id"]})

    try:
        payload = json.loads(op["result_json"] or "{}")
    except ValueError:
        payload = {}
    used, amount_used = _quota_snapshot(conn, principal, now)
    mode = payload.get("execution_mode")

    if mode == "direct":
        receipt = payload.get("receipt") or {}
        return DirectWriteResult(
            200, "replayed", "交易已记录（幂等重放）",
            _direct_mode_data(
                code="replayed", message="交易已记录（幂等重放）",
                replayed=True, tx_id=int(payload.get("transaction_id") or 0),
                operation_id=int(op["id"]), receipt=receipt, now=now,
                used=used, amount_used=amount_used),
            replayed=True)

    if mode == "proposal":
        proposal_id = payload.get("proposal_id")
        row = db.get_proposal(conn, int(proposal_id)) if proposal_id else None
        if row is None:
            _audit(conn, principal, ip, "agent_direct_rejected", {
                "reason": "idempotency_conflict", "operation_id": op["id"]})
            return DirectWriteResult(
                409, "idempotency_conflict",
                "原提案已不存在，请使用新的 Idempotency-Key",
                {"operation_id": op["id"]})
        message = "提案状态（幂等重放）"
        return DirectWriteResult(
            200, "replayed", message,
            _proposal_mode_data(
                principal, code="replayed", message=message,
                proposal_id=int(row["id"]), operation_id=int(op["id"]),
                replayed=True, now=now, used=used, amount_used=amount_used,
                proposal_row=row),
            replayed=True)

    _audit(conn, principal, ip, "agent_direct_rejected", {
        "reason": "idempotency_conflict", "operation_id": op["id"]})
    return DirectWriteResult(
        409, "idempotency_conflict",
        "幂等记录格式不受支持，请使用新的 Idempotency-Key",
        {"operation_id": op["id"]})


# ---------------------------------------------------------------------------
# 直记 / 降级
# ---------------------------------------------------------------------------
def _insert_operation(conn: sqlite3.Connection, principal: Principal,
                      key_hash: str, digest: str, payload: dict,
                      now: datetime, audit_id: int | None) -> int:
    return db.insert_operation(
        conn, principal_type=principal.kind, principal_id=principal.id,
        key_hash=key_hash, operation=OPERATION_RECORD_TRANSACTION,
        params_digest=digest, status="succeeded",
        result_json=json.dumps(payload, ensure_ascii=False, sort_keys=True),
        audit_id=audit_id, created_at=now.isoformat(),
        expires_at=(now + timedelta(days=IDEMPOTENCY_TTL_DAYS)).isoformat(),
    )


def _link_operation_audit(conn: sqlite3.Connection, operation_id: int,
                          audit_id: int | None) -> None:
    conn.execute(
        "UPDATE agent_operations SET audit_id=? WHERE id=?",
        (audit_id, operation_id))


def _record_direct(conn: sqlite3.Connection, principal: Principal,
                   clean: dict, *, key_hash: str, digest: str,
                   fund_name: str, now: datetime, ip: str | None,
                   used: int, amount_used: float) -> DirectWriteResult:
    tx = Transaction(
        fund_code=clean["fund_code"], action=clean["action"],
        date=clean["date"], amount=clean.get("amount"),
        shares=clean.get("shares"), nav=clean.get("nav"),
        fee=clean.get("fee") or 0.0, channel=clean.get("channel", ""),
        note=clean.get("note", ""), is_t1=bool(clean.get("is_t1")),
        source=DIRECT_SOURCE,
    )
    tx.normalize()
    tx_id = db.insert_transaction(conn, tx)
    receipt = _direct_receipt(tx, fund_name)

    business_audit = db.log_audit(
        "add_transaction", ip=ip, username=principal.display,
        detail={
            "tx_id": tx_id, "fund_code": tx.fund_code,
            "action": tx.action, "date": tx.date,
            "amount": tx.amount, "shares": tx.shares,
            "source": DIRECT_SOURCE,
        },
        conn=conn,
    )
    operation_id = _insert_operation(
        conn, principal, key_hash, digest,
        {"execution_mode": "direct", "transaction_id": tx_id,
         "receipt": receipt},
        now, business_audit)
    process_audit = _audit(conn, principal, ip, "agent_direct_add", {
        "tx_id": tx_id, "operation_id": operation_id,
        "fund_code": tx.fund_code, "action": tx.action,
        "date": tx.date, "amount": tx.amount, "shares": tx.shares,
        "source": DIRECT_SOURCE,
    })
    _link_operation_audit(conn, operation_id, process_audit)

    return DirectWriteResult(
        201, "recorded", "交易已直接写入账本",
        _direct_mode_data(
            code="recorded", message="交易已直接写入账本", replayed=False,
            tx_id=tx_id, operation_id=operation_id, receipt=receipt,
            now=now, used=used + 1, amount_used=amount_used + (tx.amount or 0.0)))


def _record_downgrade(conn: sqlite3.Connection, principal: Principal,
                      clean: dict, *, key_hash: str, digest: str,
                      reason: str, detail: dict, now: datetime,
                      ip: str | None, used: int,
                      amount_used: float) -> DirectWriteResult:
    """软性失败：复用同主体同参 pending 提案，否则新建并转人工审批。"""
    from .proposal_service import (
        create_pending_proposal_conn,
        proposal_digest,
    )

    proposal_params_digest = proposal_digest(clean)
    existing = conn.execute(
        "SELECT * FROM operation_proposals WHERE principal_type=? "
        "AND principal_id=? AND params_digest=? AND status='pending' "
        "ORDER BY id DESC LIMIT 1",
        (principal.kind, principal.id, proposal_params_digest),
    ).fetchone()
    replayed = False
    if existing is not None and not _proposal_expired(existing, now):
        row = existing
        replayed = True
    else:
        created = create_pending_proposal_conn(
            conn, principal, clean=clean,
            digest=proposal_params_digest, now=now, ip=ip,
            origin="direct_downgrade", reason=reason,
            extra_warnings=[DOWNGRADE_WARNINGS.get(reason, reason)],
        )
        if not created.ok:
            # pending 上限等提案侧拒绝原样透传；不写直记幂等记录。
            return DirectWriteResult(
                created.http_status, created.code, created.message,
                dict(created.data))
        row = db.get_proposal(conn, int(created.data["proposal_id"]))

    operation_id = _insert_operation(
        conn, principal, key_hash, digest,
        {"execution_mode": "proposal", "proposal_id": int(row["id"])},
        now, None)
    process_audit = _audit(conn, principal, ip, "agent_direct_downgraded", {
        "reason": reason, "proposal_id": int(row["id"]),
        "operation_id": operation_id, "fund_code": clean["fund_code"],
        "action": clean["action"], "date": clean["date"],
        **{k: v for k, v in detail.items() if k in (
            "tx_id", "available", "cap", "amount")},
    })
    _link_operation_audit(conn, operation_id, process_audit)

    message = ("疑似重复或超出直记边界，已转交网页审批"
               if reason != "duplicate_candidate"
               else "检测到疑似重复交易，已转交网页审批")
    return DirectWriteResult(
        200 if replayed else 201, "downgraded", message,
        _proposal_mode_data(
            principal, code="downgraded", message=message,
            proposal_id=int(row["id"]), operation_id=operation_id,
            replayed=replayed, now=now, used=used + 1,
            amount_used=amount_used, proposal_row=row),
        replayed=replayed)


def _proposal_expired(row: sqlite3.Row, now: datetime) -> bool:
    expires_at = row["expires_at"]
    if not expires_at:
        return False
    try:
        return datetime.fromisoformat(expires_at) <= now
    except (TypeError, ValueError):
        return True


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------
def record_transaction_direct(principal: Principal, *, params: object,
                              idempotency_key: object,
                              ip: str | None = None) -> DirectWriteResult:
    """按 §5 顺序执行：校验 → 重放 → 事务内复核 → 预检 → 直记/降级。"""
    clean = validate_direct_params(params)
    key_hash = _key_hash(validate_idempotency_key(idempotency_key))
    digest = _digest(clean)
    now = _now()

    with db.get_connection(write=True) as conn:
        replay = _replay(conn, principal, key_hash, digest, now, ip)
        if replay is not None:
            return replay

        blocked = _check_principal_conn(conn, principal, now, ip, clean)
        if blocked is not None:
            return blocked

        from .proposal_service import fund_name_in_conn
        fund_name = fund_name_in_conn(conn, clean["fund_code"])
        if fund_name is None:
            return _reject(
                conn, principal, ip, 409, "fund_not_registered",
                "基金尚未收录，请先在网页添加或刷新基金信息后再试",
                detail={"fund_code": clean["fund_code"]}, params=clean)

        used, amount_used = _quota_snapshot(conn, principal, now)
        reset_at = _next_day_start(now).isoformat()
        if used >= config.AGENT_TX_DAILY_COUNT:
            return _reject(
                conn, principal, ip, 429, "daily_quota_exceeded",
                f"今日直记笔数已达上限（{config.AGENT_TX_DAILY_COUNT} 笔），明日再试",
                detail={"used": used, "limit": int(config.AGENT_TX_DAILY_COUNT),
                        "reset_at": reset_at},
                params=clean)

        amount = clean.get("amount")
        if (amount is not None
                and amount_used + float(amount)
                > float(config.AGENT_TX_DAILY_AMOUNT) + AMOUNT_TOLERANCE):
            return _reject(
                conn, principal, ip, 429, "daily_quota_exceeded",
                "今日直记金额已达上限，明日再试或改用提案审批",
                detail={"used": round(amount_used, 2),
                        "limit": float(config.AGENT_TX_DAILY_AMOUNT),
                        "reset_at": reset_at},
                params=clean)

        failure = _soft_failure(conn, clean, now)
        if failure is not None:
            reason, detail = failure
            token_row = _token_row(conn, principal)
            scopes = frozenset(((token_row["scopes"] if token_row else "") or "").split())
            if agent_tokens.SCOPE_TRANSACTIONS_PROPOSE not in scopes:
                messages = {
                    "duplicate_candidate": "检测到疑似重复交易，且 Token 无提案权限，已拒绝",
                    "insufficient_shares": "卖出份额超过可用份额，且 Token 无提案权限，已拒绝",
                    "amount_exceeds_cap": "单笔金额超过直记上限，且 Token 无提案权限，已拒绝",
                }
                return _reject(
                    conn, principal, ip, 409, reason,
                    messages.get(reason, "预检未通过，已拒绝"),
                    detail=detail, params=clean)
            return _record_downgrade(
                conn, principal, clean, key_hash=key_hash, digest=digest,
                reason=reason, detail=detail, now=now, ip=ip,
                used=used, amount_used=amount_used)

        result = _record_direct(
            conn, principal, clean, key_hash=key_hash, digest=digest,
            fund_name=fund_name, now=now, ip=ip,
            used=used, amount_used=amount_used)

    analysis.clear_analysis_cache()
    return result
