"""账本操作提案服务（Agent 提案 + 网页确认 + 服务端执行）。

E 阶段先开放 ``add_transaction`` 一种操作：Agent 只能创建待审批提案，管理员在
网页确认后由服务端在同一 SQLite 事务内完成状态迁移、业务写入与审计；Agent
token 永远拿不到直接写账本或通用执行入口。

状态机::

    pending ──approve──> succeeded
       │  │  │
       │  │  └─reject──> rejected
       │  └────cancel──> cancelled
       └───────expire──> expired
   审批失败: pending ──> failed | conflict

- 提案默认 7 天过期；过期后不可审批。
- 创建使用 Idempotency-Key，同键同参返回原提案，同键异参返回 409。
- 审批使用 ``BEGIN IMMEDIATE`` + 状态复读，保证并发下只成功一次。
- 执行前重新校验实例认证、写开关、创建者 token 与业务规则；执行不联网。
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from . import agent_tokens, analysis, config, db
from .models import ACTION_BUY, ACTIONS, Transaction

OPERATION_ADD_TRANSACTION = "add_transaction"
ALLOWED_OPERATIONS = frozenset({OPERATION_ADD_TRANSACTION})
OPERATION_LABELS = {
    OPERATION_ADD_TRANSACTION: "新增交易",
}

PROPOSAL_TTL_DAYS = 7
PROPOSAL_PURGE_DAYS = 30
MAX_PENDING_PER_OWNER = 20
IDEMPOTENCY_KEY_MIN = 16
IDEMPOTENCY_KEY_MAX = 128
CONTRACT_VERSION = 1
NOTE_MAX_LEN = 500
CHANNEL_MAX_LEN = 50
REASON_MAX_LEN = 500
MAX_NUMBER = 1e12

FUND_CODE_RE = re.compile(r"^[0-9]{6}$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
IDEMPOTENCY_KEY_RE = re.compile(r"^[A-Za-z0-9._~+/=-]+$")

STATUS_PENDING = "pending"
STATUS_SUCCEEDED = "succeeded"
STATUS_FAILED = "failed"
STATUS_CONFLICT = "conflict"
STATUS_REJECTED = "rejected"
STATUS_CANCELLED = "cancelled"
STATUS_EXPIRED = "expired"

TERMINAL_STATUSES = frozenset({
    STATUS_SUCCEEDED, STATUS_FAILED, STATUS_CONFLICT,
    STATUS_REJECTED, STATUS_CANCELLED, STATUS_EXPIRED,
})

# 提案 scope 与操作类型的对应关系：服务端同时校验，不接受任意操作。
OPERATION_SCOPE = {
    OPERATION_ADD_TRANSACTION: agent_tokens.SCOPE_TRANSACTIONS_PROPOSE,
}


class ProposalValidationError(ValueError):
    """输入校验失败（映射为 HTTP 422）；不创建提案、不写幂等记录。"""

    def __init__(self, field_name: str, message: str) -> None:
        super().__init__(message)
        self.field = field_name
        self.message = message


@dataclass(frozen=True)
class Principal:
    """提案主体：当前仅 Agent token 可创建提案。"""

    kind: str
    id: str
    display: str

    def __post_init__(self) -> None:
        if self.kind != "agent_token":
            raise ValueError(f"提案主体类型不受支持：{self.kind}")
        if not self.id:
            raise ValueError("提案主体缺少 id")


@dataclass(frozen=True)
class ProposalResult:
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


def _expired(expires_at: str | None, now: datetime) -> bool:
    if not expires_at:
        return False
    try:
        return datetime.fromisoformat(expires_at) <= now
    except (TypeError, ValueError):
        return True


def _key_hash(key: str) -> str:
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def _canonical(payload: dict) -> str:
    return json.dumps(
        payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


# ---------------------------------------------------------------------------
# 输入校验与规范化
# ---------------------------------------------------------------------------
def validate_idempotency_key(value: object) -> str:
    if not isinstance(value, str):
        raise ProposalValidationError(
            "idempotency_key", "缺少 Idempotency-Key 请求头")
    if not (IDEMPOTENCY_KEY_MIN <= len(value) <= IDEMPOTENCY_KEY_MAX):
        raise ProposalValidationError(
            "idempotency_key",
            f"Idempotency-Key 长度需在 "
            f"{IDEMPOTENCY_KEY_MIN}–{IDEMPOTENCY_KEY_MAX} 之间")
    if not IDEMPOTENCY_KEY_RE.fullmatch(value):
        raise ProposalValidationError(
            "idempotency_key", "Idempotency-Key 含不支持的字符")
    return value


def validate_proposal_id(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ProposalValidationError("proposal_id", "proposal_id 必须是正整数")
    return value


def _clean_text(value: object, field_name: str, max_len: int) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise ProposalValidationError(field_name, f"{field_name} 必须是字符串")
    text = value.strip()
    if "\x00" in text:
        raise ProposalValidationError(field_name, f"{field_name} 不能包含空字符")
    if len(text) > max_len:
        raise ProposalValidationError(
            field_name, f"{field_name} 最多 {max_len} 个字符")
    return text


def _number(value: object, field_name: str, *, required: bool = False) -> float | None:
    if value is None:
        if required:
            raise ProposalValidationError(field_name, f"{field_name} 不能为空")
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ProposalValidationError(field_name, f"{field_name} 必须是数字")
    number = float(value)
    if not math.isfinite(number):
        raise ProposalValidationError(field_name, f"{field_name} 必须是有限数字")
    if number < 0:
        raise ProposalValidationError(field_name, f"{field_name} 不能为负数")
    if number > MAX_NUMBER:
        raise ProposalValidationError(field_name, f"{field_name} 超出上限")
    return number


def _validate_add_transaction(params: object) -> dict[str, Any]:
    """校验并规范化 ``add_transaction`` 参数，返回交易字段字典。"""
    if not isinstance(params, dict):
        raise ProposalValidationError("params", "params 必须是对象")
    allowed = {
        "fund_code", "action", "date", "amount", "shares", "nav",
        "fee", "channel", "note", "is_t1",
    }
    unknown = set(params) - allowed
    if unknown:
        raise ProposalValidationError(
            "params", f"包含不支持的参数：{', '.join(sorted(unknown))}")

    fund_code = params.get("fund_code")
    if not isinstance(fund_code, str) or not FUND_CODE_RE.fullmatch(
            fund_code.strip()):
        raise ProposalValidationError("fund_code", "基金代码必须是 6 位数字")
    fund_code = fund_code.strip()

    action = params.get("action")
    if action not in ACTIONS:
        raise ProposalValidationError(
            "action", f"操作方向必须是：{', '.join(ACTIONS)}")

    date = params.get("date")
    if not isinstance(date, str) or not DATE_RE.fullmatch(date.strip()):
        raise ProposalValidationError("date", "日期必须是 YYYY-MM-DD")
    date = date.strip()
    try:
        datetime.strptime(date, "%Y-%m-%d")
    except ValueError as exc:
        raise ProposalValidationError("date", "日期不是有效日期") from exc

    amount = _number(params.get("amount"), "amount")
    shares = _number(params.get("shares"), "shares")
    nav = _number(params.get("nav"), "nav")
    fee = _number(params.get("fee"), "fee") or 0.0
    channel = _clean_text(params.get("channel"), "channel", CHANNEL_MAX_LEN)
    note = _clean_text(params.get("note"), "note", NOTE_MAX_LEN)

    is_t1 = params.get("is_t1", False)
    if not isinstance(is_t1, bool):
        raise ProposalValidationError("is_t1", "is_t1 必须是布尔值")

    tx = Transaction(
        fund_code=fund_code, action=action, date=date,
        amount=amount, shares=shares, nav=nav, fee=fee,
        channel=channel, note=note, is_t1=is_t1,
    )
    tx.normalize()
    if not tx.is_valid():
        raise ProposalValidationError(
            "params", "交易信息不完整：买入/再投资需金额或份额，卖出需份额，分红需金额")
    if tx.action == ACTION_BUY and (tx.amount is None or tx.amount <= 0):
        raise ProposalValidationError("amount", "买入金额必须大于 0")

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


ACTION_LABELS = {
    "buy": "买入",
    "sell": "卖出",
    "dividend": "现金分红",
    "reinvest": "红利再投资",
}


def _digest(operation_type: str, params: dict) -> str:
    canonical = _canonical({
        "contract": CONTRACT_VERSION,
        "operation_type": operation_type,
        "params": params,
    })
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _build_summary(fund_name: str, operation_type: str,
                   params: dict) -> dict[str, Any]:
    action = params["action"]
    warnings: list[str] = []
    if operation_type == OPERATION_ADD_TRANSACTION:
        if params.get("nav") is None:
            warnings.append("成交净值尚未确定，市值与收益可能暂时缺失")
        if params.get("is_t1"):
            warnings.append("T+1 确认：份额可能尚未到账，需后续核对")
        if params.get("action") == "sell":
            warnings.append("请核对卖出份额是否超过该渠道可用份额")
    return {
        "operation_type": operation_type,
        "operation_label": OPERATION_LABELS.get(operation_type, operation_type),
        "title": f"{ACTION_LABELS.get(action, action)} {params['fund_code']}",
        "fund_code": params["fund_code"],
        "fund_name": fund_name,
        "action": action,
        "action_label": ACTION_LABELS.get(action, action),
        "date": params["date"],
        "amount": params.get("amount"),
        "shares": params.get("shares"),
        "nav": params.get("nav"),
        "fee": params.get("fee"),
        "channel": params.get("channel", ""),
        "is_t1": params.get("is_t1", False),
        "note": params.get("note", ""),
        "warnings": warnings,
    }


def _fund_name(conn: sqlite3.Connection, fund_code: str) -> str | None:
    row = conn.execute(
        "SELECT fund_name FROM funds WHERE fund_code=?", (fund_code,)
    ).fetchone()
    if row is None:
        return None
    return row["fund_name"] or fund_code


def _row_to_dict(row: sqlite3.Row, now: datetime) -> dict[str, Any]:
    status = row["status"]
    if status == STATUS_PENDING and _expired(row["expires_at"], now):
        status = STATUS_EXPIRED
    try:
        summary = json.loads(row["summary_json"] or "{}")
    except ValueError:
        summary = {}
    try:
        params = json.loads(row["params_json"] or "{}")
    except ValueError:
        params = {}
    try:
        execution = (json.loads(row["execution_result_json"])
                     if row["execution_result_json"] else None)
    except ValueError:
        execution = None
    return {
        "proposal_id": row["id"],
        "operation_type": row["operation_type"],
        "operation_label": OPERATION_LABELS.get(
            row["operation_type"], row["operation_type"]),
        "status": status,
        "risk_level": row["risk_level"] or "medium",
        "created_at": row["created_at"],
        "expires_at": row["expires_at"],
        "reviewed_by": row["reviewed_by"],
        "reviewed_at": row["reviewed_at"],
        "rejection_reason": row["rejection_reason"] or "",
        "execution_result": execution,
        "audit_id": row["audit_id"],
        "completed_at": row["completed_at"],
        "summary": summary,
        "params": params,
        "can_cancel": status == STATUS_PENDING,
        "can_approve": status == STATUS_PENDING,
    }


# ---------------------------------------------------------------------------
# 审计与幂等
# ---------------------------------------------------------------------------
def _audit(conn: sqlite3.Connection, principal: Principal | None,
           ip: str | None, action: str, detail: dict,
           reviewer: str | None = None) -> int | None:
    return db.log_audit(
        action, ip=ip,
        username=reviewer or (principal.display if principal else None),
        detail={**detail, "token_id": principal.id if principal else None},
        conn=conn,
    )


def _replay_create(conn: sqlite3.Connection, principal: Principal,
                   key_hash: str, operation_type: str, digest: str,
                   ip: str | None) -> ProposalResult | None:
    op = db.get_operation(conn, principal.kind, principal.id, key_hash)
    if op is None:
        return None
    mismatch = (
        op["params_digest"] != digest
        or op["operation"] != "create_proposal"
    )
    if mismatch or _expired(op["expires_at"], _now()):
        code = ("idempotency_expired"
                if _expired(op["expires_at"], _now())
                else "idempotency_conflict")
        message = (
            "幂等键已过期，不能用同一键重试；请使用新的 Idempotency-Key"
            if code == "idempotency_expired" else
            "同一 Idempotency-Key 已用于不同参数或不同操作")
        _audit(conn, principal, ip, "proposal_create_rejected", {
            "reason": code, "operation_type": operation_type,
            "operation_id": op["id"]})
        return ProposalResult(409, code, message, {"operation_id": op["id"]})

    try:
        payload = json.loads(op["result_json"] or "{}")
    except ValueError:
        payload = {}
    proposal_id = payload.get("proposal_id")
    row = db.get_proposal(conn, int(proposal_id)) if proposal_id else None
    if row is None:
        return ProposalResult(
            409, "idempotency_conflict",
            "原提案已不存在，请使用新的 Idempotency-Key",
            {"operation_id": op["id"]})
    return ProposalResult(
        200, "replayed", "提案已创建（幂等重放）",
        _row_to_dict(row, _now()), replayed=True)


def _expire_stale(now: datetime) -> None:
    """惰性清理过期 pending 提案；独立短事务，避免嵌套写锁。"""
    db.expire_pending_proposals(now.isoformat())


# ---------------------------------------------------------------------------
# 创建 / 查询 / 取消（Agent）
# ---------------------------------------------------------------------------
def create_proposal(principal: Principal, *, operation_type: object,
                    params: object, idempotency_key: object,
                    ip: str | None = None) -> ProposalResult:
    """创建待审批提案；不写账本，只做校验、摘要与持久化。"""
    if not isinstance(operation_type, str) or (
            operation_type not in ALLOWED_OPERATIONS):
        raise ProposalValidationError(
            "operation_type",
            f"操作类型不受支持，当前仅支持：{', '.join(sorted(ALLOWED_OPERATIONS))}")
    clean = _validate_add_transaction(params)
    key_hash = _key_hash(validate_idempotency_key(idempotency_key))
    digest = _digest(operation_type, clean)
    now = _now()
    _expire_stale(now)

    with db.get_connection(write=True) as conn:
        replay = _replay_create(
            conn, principal, key_hash, operation_type, digest, ip)
        if replay is not None:
            return replay

        fund_name = _fund_name(conn, clean["fund_code"])
        if fund_name is None:
            _audit(conn, principal, ip, "proposal_create_rejected", {
                "reason": "fund_not_registered",
                "operation_type": operation_type,
                "fund_code": clean["fund_code"]})
            return ProposalResult(
                409, "fund_not_registered",
                "基金尚未收录，请先在网页添加或刷新基金信息后再提案",
                {"fund_code": clean["fund_code"]})

        pending = int(conn.execute(
            "SELECT COUNT(*) FROM operation_proposals "
            "WHERE principal_type=? AND principal_id=? AND status='pending'",
            (principal.kind, principal.id)).fetchone()[0])
        if pending >= MAX_PENDING_PER_OWNER:
            _audit(conn, principal, ip, "proposal_create_rejected", {
                "reason": "too_many_pending",
                "operation_type": operation_type})
            return ProposalResult(
                409, "too_many_pending",
                f"待处理提案过多（上限 {MAX_PENDING_PER_OWNER}），请先处理或取消",
                {"pending": pending, "limit": MAX_PENDING_PER_OWNER})

        summary = _build_summary(fund_name, operation_type, clean)
        params_json = json.dumps(clean, ensure_ascii=False, sort_keys=True)
        summary_json = json.dumps(summary, ensure_ascii=False, sort_keys=True)
        expires_at = (now + timedelta(days=PROPOSAL_TTL_DAYS)).isoformat()

        proposal_id = db.insert_proposal(
            conn,
            principal_type=principal.kind, principal_id=principal.id,
            token_prefix=principal.display.split(":", 1)[-1]
            if ":" in principal.display else "",
            operation_type=operation_type, status=STATUS_PENDING,
            params_json=params_json, params_digest=digest,
            summary_json=summary_json, risk_level="medium",
            created_at=now.isoformat(), expires_at=expires_at,
        )
        audit_id = _audit(conn, principal, ip, "proposal_created", {
            "proposal_id": proposal_id, "operation_type": operation_type,
            "fund_code": clean["fund_code"], "action": clean["action"],
            "amount": clean.get("amount"), "shares": clean.get("shares")})
        db.update_proposal(conn, proposal_id, audit_id=audit_id)
        db.insert_operation(
            conn, principal_type=principal.kind, principal_id=principal.id,
            key_hash=key_hash, operation="create_proposal",
            params_digest=digest, status=STATUS_PENDING,
            result_json=json.dumps(
                {"proposal_id": proposal_id}, ensure_ascii=False),
            audit_id=audit_id, created_at=now.isoformat(),
            expires_at=(now + timedelta(days=90)).isoformat(),
        )
        row = db.get_proposal(conn, proposal_id)
        return ProposalResult(
            201, "created", "提案已创建，等待网页管理员确认",
            _row_to_dict(row, now))


def get_proposal(principal: Principal, proposal_id: object) -> ProposalResult:
    """按归属读取提案；他人提案返回 404，不泄漏存在性。"""
    pid = validate_proposal_id(proposal_id)
    with db.get_connection() as conn:
        row = db.get_proposal_for_owner(
            conn, pid, principal.kind, principal.id)
    if row is None:
        return ProposalResult(404, "not_found", "未找到提案", {"proposal_id": pid})
    return ProposalResult(200, "ok", "提案详情", _row_to_dict(row, _now()))


def list_own_proposals(principal: Principal, *, status: str | None = None,
                       limit: int = 50, offset: int = 0) -> ProposalResult:
    """Agent 查看自己创建的提案列表。"""
    _validate_status_filter(status)
    now = _now()
    _expire_stale(now)
    with db.get_connection() as conn:
        total = int(conn.execute(
            "SELECT COUNT(*) FROM operation_proposals WHERE principal_type=? "
            "AND principal_id=?" + (" AND status=?" if status else ""),
            ((principal.kind, principal.id, status) if status
             else (principal.kind, principal.id))).fetchone()[0])
        rows = conn.execute(
            "SELECT * FROM operation_proposals WHERE principal_type=? "
            "AND principal_id=?" + (" AND status=?" if status else "")
            + " ORDER BY id DESC LIMIT ? OFFSET ?",
            ((principal.kind, principal.id, status) if status
             else (principal.kind, principal.id)) + (limit, offset),
        ).fetchall()
    items = [_row_to_dict(row, now) for row in rows]
    return ProposalResult(200, "ok", "提案列表", {
        "count": len(items), "total": total, "items": items,
        "pagination": {"limit": limit, "offset": offset, "total": total},
    })


def cancel_proposal(principal: Principal, proposal_id: object,
                    ip: str | None = None) -> ProposalResult:
    """Agent 取消自己尚未审批的提案；已处理或过期不可取消。"""
    pid = validate_proposal_id(proposal_id)
    now = _now()
    with db.get_connection(write=True) as conn:
        row = db.get_proposal_for_owner(
            conn, pid, principal.kind, principal.id)
        if row is None:
            return ProposalResult(
                404, "not_found", "未找到提案", {"proposal_id": pid})
        if row["status"] != STATUS_PENDING:
            return ProposalResult(
                409, "not_pending", "提案已处理，不能取消",
                {"proposal_id": pid, "status": row["status"]})
        if _expired(row["expires_at"], now):
            db.update_proposal(
                conn, pid, status=STATUS_EXPIRED,
                completed_at=now.isoformat())
            _audit(conn, principal, ip, "proposal_expired", {
                "proposal_id": pid})
            return ProposalResult(
                409, "expired", "提案已过期，不能取消", {"proposal_id": pid})

        audit_id = _audit(conn, principal, ip, "proposal_cancelled", {
            "proposal_id": pid, "operation_type": row["operation_type"]})
        db.update_proposal(
            conn, pid, status=STATUS_CANCELLED, completed_at=now.isoformat(),
            audit_id=audit_id)
        updated = db.get_proposal(conn, pid)
    return ProposalResult(
        200, "cancelled", "提案已取消", _row_to_dict(updated, now))


VALID_STATUSES = frozenset({
    STATUS_PENDING, STATUS_SUCCEEDED, STATUS_FAILED, STATUS_CONFLICT,
    STATUS_REJECTED, STATUS_CANCELLED, STATUS_EXPIRED,
})


def _validate_status_filter(status: str | None) -> None:
    if status is not None and status not in VALID_STATUSES:
        raise ProposalValidationError(
            "status", f"status 必须是：{', '.join(sorted(VALID_STATUSES))}")


# ---------------------------------------------------------------------------
# 网页管理：列表 / 详情 / 批准 / 拒绝
# ---------------------------------------------------------------------------
def list_proposals(*, status: str | None = None, limit: int = 50,
                   offset: int = 0) -> ProposalResult:
    """管理员查看全部提案；返回待处理数量供导航角标使用。"""
    _validate_status_filter(status)
    now = _now()
    _expire_stale(now)
    with db.get_connection() as conn:
        total = db.count_proposals(conn, status)
        pending = db.count_proposals(conn, STATUS_PENDING)
        rows = db.list_proposals(
            conn, status=status, limit=limit, offset=offset)
    items = [_row_to_dict(row, now) for row in rows]
    return ProposalResult(200, "ok", "提案列表", {
        "count": len(items), "total": total, "pending_count": pending,
        "items": items,
        "pagination": {"limit": limit, "offset": offset, "total": total},
    })


def get_proposal_admin(proposal_id: object) -> ProposalResult:
    pid = validate_proposal_id(proposal_id)
    with db.get_connection() as conn:
        row = db.get_proposal(conn, pid)
    if row is None:
        return ProposalResult(404, "not_found", "未找到提案", {"proposal_id": pid})
    return ProposalResult(200, "ok", "提案详情", _row_to_dict(row, _now()))


def _token_error(token_row: sqlite3.Row | None, now: datetime) -> str:
    """复核创建者 token；返回稳定错误码，空串表示仍有效。"""
    if token_row is None:
        return "token_missing"
    if token_row["revoked_at"]:
        return "token_revoked"
    expires_at = token_row["expires_at"]
    if expires_at:
        try:
            if datetime.fromisoformat(expires_at) <= now:
                return "token_expired"
        except (TypeError, ValueError):
            return "token_invalid"
    return ""


def _mark_failure(conn: sqlite3.Connection, row: sqlite3.Row, reviewer: str,
                  now: datetime, ip: str | None, *, status: str, reason: str,
                  message: str, http_status: int = 409) -> ProposalResult:
    audit_id = _audit(conn, None, ip, f"proposal_{status}", {
        "proposal_id": row["id"], "operation_type": row["operation_type"],
        "reason": reason}, reviewer=reviewer)
    db.update_proposal(
        conn, row["id"], status=status, reviewed_by=reviewer,
        reviewed_at=now.isoformat(),
        execution_result_json=json.dumps(
            {"ok": False, "reason": reason, "message": message},
            ensure_ascii=False),
        audit_id=audit_id, completed_at=now.isoformat())
    updated = db.get_proposal(conn, row["id"])
    return ProposalResult(
        http_status, reason, message, _row_to_dict(updated, now))


def approve_proposal(proposal_id: object, *, reviewer: str,
                     ip: str | None = None) -> ProposalResult:
    """管理员批准并立即执行；状态迁移、业务写入与审计在同一事务内完成。"""
    pid = validate_proposal_id(proposal_id)
    now = _now()
    _expire_stale(now)
    with db.get_connection(write=True) as conn:
        row = db.get_proposal(conn, pid)
        if row is None:
            return ProposalResult(
                404, "not_found", "未找到提案", {"proposal_id": pid})
        if row["status"] != STATUS_PENDING:
            if row["status"] == STATUS_EXPIRED:
                return ProposalResult(
                    409, "expired", "提案已过期，请重新提案",
                    {"proposal_id": pid, "status": row["status"]})
            return ProposalResult(
                409, "not_pending", "提案已处理，不能重复审批",
                {"proposal_id": pid, "status": row["status"]})
        if _expired(row["expires_at"], now):
            db.update_proposal(
                conn, pid, status=STATUS_EXPIRED,
                completed_at=now.isoformat())
            _audit(conn, None, ip, "proposal_expired", {
                "proposal_id": pid}, reviewer=reviewer)
            return ProposalResult(
                409, "expired", "提案已过期，请重新提案", {"proposal_id": pid})
        if not config.AUTH_ENABLED:
            return ProposalResult(
                403, "auth_disabled",
                "未启用管理员认证，不能执行提案", {"proposal_id": pid})
        # 事务内复核 DB 权威值：多 worker 下其他进程关闭总闸后立即生效。
        if not db.agent_write_enabled_conn(conn):
            return ProposalResult(
                403, "write_disabled",
                "Agent 写能力未启用，不能执行提案", {"proposal_id": pid})

        try:
            token_id = int(row["principal_id"])
        except (TypeError, ValueError):
            token_row = None
        else:
            token_row = db.get_agent_token_conn(conn, token_id)
        token_error = _token_error(token_row, now)
        if token_error:
            return _mark_failure(
                conn, row, reviewer, now, ip, status=STATUS_FAILED,
                reason=token_error,
                message="创建提案的 Agent token 已失效，请重新提案")
        scopes = frozenset((token_row["scopes"] or "").split())
        required = OPERATION_SCOPE.get(row["operation_type"])
        if required is None or required not in scopes:
            return _mark_failure(
                conn, row, reviewer, now, ip, status=STATUS_FAILED,
                reason="scope_revoked",
                message="创建提案的 Agent token 已失去对应权限，请重新提案")

        try:
            clean = _validate_add_transaction(
                json.loads(row["params_json"] or "{}"))
        except (ProposalValidationError, ValueError) as exc:
            return _mark_failure(
                conn, row, reviewer, now, ip, status=STATUS_CONFLICT,
                reason="invalid_params",
                message=getattr(exc, "message", "提案参数已不合法"))

        fund_name = _fund_name(conn, clean["fund_code"])
        if fund_name is None:
            return _mark_failure(
                conn, row, reviewer, now, ip, status=STATUS_CONFLICT,
                reason="fund_missing",
                message="基金已不在当前账本中，请先在网页添加后再提案")

        tx = Transaction(
            fund_code=clean["fund_code"], action=clean["action"],
            date=clean["date"], amount=clean.get("amount"),
            shares=clean.get("shares"), nav=clean.get("nav"),
            fee=clean.get("fee") or 0.0, channel=clean.get("channel", ""),
            note=clean.get("note", ""), is_t1=bool(clean.get("is_t1")),
        )
        tx.normalize()
        if not tx.is_valid():
            return _mark_failure(
                conn, row, reviewer, now, ip, status=STATUS_CONFLICT,
                reason="invalid_params", message="交易信息不完整，不能执行")
        tx_id = db.insert_transaction(conn, tx)
        db.log_audit(
            "add_transaction", ip=ip, username=reviewer,
            detail={"tx_id": tx_id, "fund_code": tx.fund_code,
                    "action": tx.action, "date": tx.date,
                    "amount": tx.amount, "shares": tx.shares,
                    "proposal_id": pid},
            conn=conn,
        )

        execution = {
            "ok": True, "tx_id": tx_id, "fund_code": tx.fund_code,
            "action": tx.action, "date": tx.date, "amount": tx.amount,
            "shares": tx.shares, "nav": tx.nav, "fee": tx.fee,
            "channel": tx.channel,
        }
        audit_id = _audit(conn, None, ip, "proposal_approved", {
            "proposal_id": pid, "operation_type": row["operation_type"],
            "tx_id": tx_id, "fund_code": tx.fund_code,
            "action": tx.action}, reviewer=reviewer)
        db.update_proposal(
            conn, pid, status=STATUS_SUCCEEDED, reviewed_by=reviewer,
            reviewed_at=now.isoformat(),
            execution_result_json=json.dumps(execution, ensure_ascii=False),
            audit_id=audit_id, completed_at=now.isoformat())
        updated = db.get_proposal(conn, pid)

    analysis.clear_analysis_cache()
    return ProposalResult(
        200, "succeeded", "提案已批准并写入账本",
        _row_to_dict(updated, now))


def reject_proposal(proposal_id: object, *, reviewer: str, reason: str = "",
                    ip: str | None = None) -> ProposalResult:
    """管理员拒绝提案；不写账本，只记录决定与原因。"""
    pid = validate_proposal_id(proposal_id)
    clean_reason = _clean_text(reason, "reason", REASON_MAX_LEN)
    now = _now()
    _expire_stale(now)
    with db.get_connection(write=True) as conn:
        row = db.get_proposal(conn, pid)
        if row is None:
            return ProposalResult(
                404, "not_found", "未找到提案", {"proposal_id": pid})
        if row["status"] != STATUS_PENDING:
            if row["status"] == STATUS_EXPIRED:
                return ProposalResult(
                    409, "expired", "提案已过期，不能拒绝",
                    {"proposal_id": pid, "status": row["status"]})
            return ProposalResult(
                409, "not_pending", "提案已处理，不能重复审批",
                {"proposal_id": pid, "status": row["status"]})
        if _expired(row["expires_at"], now):
            db.update_proposal(
                conn, pid, status=STATUS_EXPIRED,
                completed_at=now.isoformat())
            _audit(conn, None, ip, "proposal_expired", {
                "proposal_id": pid}, reviewer=reviewer)
            return ProposalResult(
                409, "expired", "提案已过期，不能拒绝", {"proposal_id": pid})
        audit_id = _audit(conn, None, ip, "proposal_rejected", {
            "proposal_id": pid, "operation_type": row["operation_type"],
            "reason": clean_reason}, reviewer=reviewer)
        db.update_proposal(
            conn, pid, status=STATUS_REJECTED, reviewed_by=reviewer,
            reviewed_at=now.isoformat(), rejection_reason=clean_reason,
            audit_id=audit_id, completed_at=now.isoformat())
        updated = db.get_proposal(conn, pid)
    return ProposalResult(
        200, "rejected", "提案已拒绝", _row_to_dict(updated, now))


def mark_stale_on_startup() -> int:
    """应用启动时：过期 pending 提案，并清理较久的已结束记录。"""
    now = _now()
    expired = db.expire_pending_proposals(now.isoformat())
    db.purge_proposals(
        (now - timedelta(days=PROPOSAL_PURGE_DAYS)).isoformat())
    return expired


def count_pending() -> int:
    """待处理提案数量（供网页导航角标使用）。"""
    now = _now()
    _expire_stale(now)
    with db.get_connection() as conn:
        return db.count_proposals(conn, STATUS_PENDING)
