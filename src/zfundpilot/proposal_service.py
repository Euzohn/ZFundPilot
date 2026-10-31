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
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from . import agent_tokens, analysis, config, db
from .models import Transaction
from .transaction_service import (
    ACTION_LABELS,
    CONTRACT_VERSION,
    transaction_row_digest,
    validate_add_transaction_params,
    validate_delete_transaction_params,
    validate_idempotency_key,
    validate_update_transaction_params,
)
from .transaction_service import (
    TransactionValidationError as ProposalValidationError,
)
from .transaction_service import (
    clean_text as _clean_text,
)

OPERATION_ADD_TRANSACTION = "add_transaction"
OPERATION_UPDATE_TRANSACTION = "update_transaction"
OPERATION_DELETE_TRANSACTION = "delete_transaction"
ALLOWED_OPERATIONS = frozenset({
    OPERATION_ADD_TRANSACTION,
    OPERATION_UPDATE_TRANSACTION,
    OPERATION_DELETE_TRANSACTION,
})
OPERATION_LABELS = {
    OPERATION_ADD_TRANSACTION: "新增交易",
    OPERATION_UPDATE_TRANSACTION: "修改交易",
    OPERATION_DELETE_TRANSACTION: "删除交易",
}

PROPOSAL_TTL_DAYS = 7
PROPOSAL_PURGE_DAYS = 30
MAX_PENDING_PER_OWNER = 20
REASON_MAX_LEN = 500

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
# update/delete 复用 transactions:propose（提议，非执行），不扩大 F0 直记 scope。
OPERATION_SCOPE = {
    OPERATION_ADD_TRANSACTION: agent_tokens.SCOPE_TRANSACTIONS_PROPOSE,
    OPERATION_UPDATE_TRANSACTION: agent_tokens.SCOPE_TRANSACTIONS_PROPOSE,
    OPERATION_DELETE_TRANSACTION: agent_tokens.SCOPE_TRANSACTIONS_PROPOSE,
}


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
# 输入校验与规范化（交易参数校验统一由 transaction_service 提供）
# ---------------------------------------------------------------------------
def validate_proposal_id(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ProposalValidationError("proposal_id", "proposal_id 必须是正整数")
    return value


def _digest(operation_type: str, params: dict) -> str:
    canonical = _canonical({
        "contract": CONTRACT_VERSION,
        "operation_type": operation_type,
        "params": params,
    })
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _build_summary(fund_name: str, operation_type: str,
                   params: dict,
                   extra_warnings: list[str] | None = None,
                   *, before: dict | sqlite3.Row | None = None) -> dict[str, Any]:
    warnings: list[str] = list(extra_warnings or [])
    if operation_type == OPERATION_ADD_TRANSACTION:
        action = params["action"]
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
    if operation_type == OPERATION_UPDATE_TRANSACTION:
        action = params["action"]
        before_fields = _row_snapshot(before) if before is not None else {}
        after_fields = {
            "fund_code": params["fund_code"], "action": params["action"],
            "date": params["date"], "amount": params.get("amount"),
            "shares": params.get("shares"), "nav": params.get("nav"),
            "fee": params.get("fee"), "channel": params.get("channel", ""),
            "is_t1": params.get("is_t1", False), "note": params.get("note", ""),
        }
        changed = sorted(
            k for k in after_fields
            if _norm_field(after_fields[k]) != _norm_field(before_fields.get(k)))
        if params.get("nav") is None:
            warnings.append("成交净值尚未确定，市值与收益可能暂时缺失")
        if params.get("is_t1"):
            warnings.append("T+1 确认：份额可能尚未到账，需后续核对")
        if params.get("action") == "sell":
            warnings.append("请核对卖出份额是否超过该渠道可用份额")
        return {
            "operation_type": operation_type,
            "operation_label": OPERATION_LABELS.get(operation_type, operation_type),
            "title": f"修改 {ACTION_LABELS.get(action, action)} {params['fund_code']}",
            "tx_id": params["tx_id"],
            "fund_code": params["fund_code"],
            "fund_name": fund_name,
            "action": action,
            "action_label": ACTION_LABELS.get(action, action),
            # 顶层字段填修改后值，使现有详情区直接展示新值；before 单列差异。
            "date": params["date"],
            "amount": params.get("amount"),
            "shares": params.get("shares"),
            "nav": params.get("nav"),
            "fee": params.get("fee"),
            "channel": params.get("channel", ""),
            "is_t1": params.get("is_t1", False),
            "note": params.get("note", ""),
            "before": before_fields,
            "after": after_fields,
            "changed_fields": changed,
            "warnings": warnings,
        }
    if operation_type == OPERATION_DELETE_TRANSACTION:
        before_fields = _row_snapshot(before) if before is not None else {}
        action = before_fields.get("action", "")
        fund_code = before_fields.get("fund_code", "")
        return {
            "operation_type": operation_type,
            "operation_label": OPERATION_LABELS.get(operation_type, operation_type),
            "title": f"删除 {ACTION_LABELS.get(action, action)} {fund_code}",
            "tx_id": params["tx_id"],
            "fund_code": fund_code,
            "fund_name": fund_name,
            "action": action,
            "action_label": ACTION_LABELS.get(action, action),
            # 顶层字段填目标行当前值，使现有详情区展示将被删除的行。
            "date": before_fields.get("date", ""),
            "amount": before_fields.get("amount"),
            "shares": before_fields.get("shares"),
            "nav": before_fields.get("nav"),
            "fee": before_fields.get("fee"),
            "channel": before_fields.get("channel", ""),
            "is_t1": before_fields.get("is_t1", False),
            "note": before_fields.get("note", ""),
            "before": before_fields,
            "reason": params.get("reason", ""),
            "warnings": warnings,
        }
    # 兜底：不应到达
    return {"operation_type": operation_type,
            "operation_label": OPERATION_LABELS.get(operation_type, operation_type),
            "warnings": warnings}


def _norm_field(value: Any) -> Any:
    """摘要比较用规范化：None 保持，数值 round(4)，其余原样。"""
    if value is None:
        return None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return round(float(value), 4)
    return value


def _row_snapshot(row: dict | sqlite3.Row | Transaction | None) -> dict[str, Any]:
    """从交易行生成展示用快照（与 transaction_row_digest 覆盖字段一致）。"""
    if row is None:
        return {}
    if isinstance(row, Transaction):
        row = {
            "fund_code": row.fund_code, "action": row.action, "date": row.date,
            "amount": row.amount, "shares": row.shares, "nav": row.nav,
            "fee": row.fee, "channel": row.channel, "note": row.note,
            "is_t1": row.is_t1,
        }
    elif not isinstance(row, dict):
        row = {k: row[k] for k in row.keys()}
    return {
        "fund_code": row.get("fund_code", ""),
        "action": row.get("action", ""),
        "date": row.get("date", ""),
        "amount": row.get("amount"),
        "shares": row.get("shares"),
        "nav": row.get("nav"),
        "fee": row.get("fee") or 0.0,
        "channel": row.get("channel") or "",
        "note": row.get("note") or "",
        "is_t1": bool(row.get("is_t1", False)),
    }


def fund_name_in_conn(conn: sqlite3.Connection, fund_code: str) -> str | None:
    row = conn.execute(
        "SELECT fund_name FROM funds WHERE fund_code=?", (fund_code,)
    ).fetchone()
    if row is None:
        return None
    return row["fund_name"] or fund_code


def proposal_row_to_dict(row: sqlite3.Row, now: datetime) -> dict[str, Any]:
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
        proposal_row_to_dict(row, _now()), replayed=True)


def _expire_stale(now: datetime) -> None:
    """惰性清理过期 pending 提案；独立短事务，避免嵌套写锁。"""
    db.expire_pending_proposals(now.isoformat())


def proposal_digest(clean: dict) -> str:
    """提案路径的参数摘要；降级去重与 create_proposal 共用。"""
    return _digest(OPERATION_ADD_TRANSACTION, clean)


def create_pending_proposal_conn(
    conn: sqlite3.Connection, principal: Principal, *,
    clean: dict, digest: str, now: datetime, ip: str | None,
    operation_type: str = OPERATION_ADD_TRANSACTION,
    fund_code: str | None = None,
    before: dict | sqlite3.Row | None = None,
    origin: str = "", reason: str = "",
    extra_warnings: list[str] | None = None,
) -> ProposalResult:
    """在调用方事务内创建待审提案；不写幂等记录。

    供 ``create_proposal``、可信直记降级路径与 F1 update/delete 共用，确保基金
    收录、pending 上限、摘要与审计语义一致。``operation_type`` 决定摘要与审计
    内容；``fund_code`` 缺省取 ``clean["fund_code"]``（delete 由调用方从目标行
    传入）；``before`` 为 update/delete 的目标行快照，用于展示前后差异；
    ``origin``/``reason`` 仅追加到 ``proposal_created`` 审计，复用既有 action。
    """
    resolved_fund_code = fund_code or clean.get("fund_code")
    if operation_type == OPERATION_DELETE_TRANSACTION:
        # 删除不强制目标基金仍在 funds 表（历史流水可能来自已移除基金）。
        fund_name = (fund_name_in_conn(conn, resolved_fund_code)
                     or resolved_fund_code or "")
    else:
        fund_name = (fund_name_in_conn(conn, resolved_fund_code)
                     if resolved_fund_code else None)
        if fund_name is None:
            _audit(conn, principal, ip, "proposal_create_rejected", {
                "reason": "fund_not_registered",
                "operation_type": operation_type,
                "fund_code": resolved_fund_code})
            return ProposalResult(
                409, "fund_not_registered",
                "基金尚未收录，请先在网页添加或刷新基金信息后再提案",
                {"fund_code": resolved_fund_code})

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

    summary = _build_summary(
        fund_name, operation_type, clean, extra_warnings, before=before)
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
    audit_detail: dict[str, Any] = {
        "proposal_id": proposal_id,
        "operation_type": operation_type,
        "fund_code": resolved_fund_code,
    }
    if operation_type == OPERATION_ADD_TRANSACTION:
        audit_detail["action"] = clean.get("action")
        audit_detail["amount"] = clean.get("amount")
        audit_detail["shares"] = clean.get("shares")
    else:
        audit_detail["tx_id"] = clean.get("tx_id")
    if origin:
        audit_detail["origin"] = origin
    if reason:
        audit_detail["reason"] = reason
    audit_id = _audit(
        conn, principal, ip, "proposal_created", audit_detail)
    db.update_proposal(conn, proposal_id, audit_id=audit_id)
    row = db.get_proposal(conn, proposal_id)
    return ProposalResult(
        201, "created", "提案已创建，等待网页管理员确认",
        proposal_row_to_dict(row, now))


# ---------------------------------------------------------------------------
# 创建 / 查询 / 取消（Agent）
# ---------------------------------------------------------------------------
def _validate_proposal_params(operation_type: str, params: object) -> dict:
    """按操作类型分派参数校验；返回规范化后的参数字典。"""
    if operation_type == OPERATION_ADD_TRANSACTION:
        return validate_add_transaction_params(params)
    if operation_type == OPERATION_UPDATE_TRANSACTION:
        return validate_update_transaction_params(params)
    if operation_type == OPERATION_DELETE_TRANSACTION:
        return validate_delete_transaction_params(params)
    raise ProposalValidationError(
        "operation_type", f"操作类型不受支持：{operation_type}")


def _resolve_target_row(
    conn: sqlite3.Connection, clean: dict, operation_type: str,
) -> tuple[sqlite3.Row | None, ProposalResult | None]:
    """定位 update/delete 的目标行并校验版本与转换腿；返回 (row, error)。"""
    del operation_type  # 目标定位规则对 update/delete 相同
    tx_id = int(clean["tx_id"])
    row = conn.execute(
        "SELECT * FROM transactions WHERE id=?", (tx_id,)).fetchone()
    if row is None:
        return None, ProposalResult(
            404, "target_not_found", f"未找到交易 {tx_id}",
            {"tx_id": tx_id})
    if transaction_row_digest(row) != clean["expected_digest"]:
        return None, ProposalResult(
            409, "target_changed",
            "目标交易已被修改，请通过 get_transaction 重新读取后再提案",
            {"tx_id": tx_id})
    if (row["conversion_id"] or "").strip():
        # §7：转换双腿必须成对处理，F1 不接受单腿修改/删除。
        return None, ProposalResult(
            409, "conversion_leg_isolated",
            "该交易属于基金转换腿，暂不支持单独修改/删除",
            {"tx_id": tx_id, "conversion_id": row["conversion_id"]})
    return row, None


def create_proposal(principal: Principal, *, operation_type: object,
                    params: object, idempotency_key: object,
                    ip: str | None = None) -> ProposalResult:
    """创建待审批提案；不写账本，只做校验、摘要与持久化。"""
    if not isinstance(operation_type, str) or (
            operation_type not in ALLOWED_OPERATIONS):
        raise ProposalValidationError(
            "operation_type",
            f"操作类型不受支持，当前仅支持：{', '.join(sorted(ALLOWED_OPERATIONS))}")
    clean = _validate_proposal_params(operation_type, params)
    key_hash = _key_hash(validate_idempotency_key(idempotency_key))
    digest = _digest(operation_type, clean)
    now = _now()
    _expire_stale(now)

    with db.get_connection(write=True) as conn:
        replay = _replay_create(
            conn, principal, key_hash, operation_type, digest, ip)
        if replay is not None:
            return replay

        before: dict | None = None
        fund_code = clean.get("fund_code")
        if operation_type in (
                OPERATION_UPDATE_TRANSACTION, OPERATION_DELETE_TRANSACTION):
            row, error = _resolve_target_row(conn, clean, operation_type)
            if error is not None:
                return error
            before = _row_snapshot(row)
            if operation_type == OPERATION_DELETE_TRANSACTION:
                fund_code = row["fund_code"]

        created = create_pending_proposal_conn(
            conn, principal, clean=clean, digest=digest, now=now, ip=ip,
            operation_type=operation_type, fund_code=fund_code, before=before)
        if not created.ok:
            return created
        proposal_id = int(created.data["proposal_id"])
        audit_id = created.data.get("audit_id")
        db.insert_operation(
            conn, principal_type=principal.kind, principal_id=principal.id,
            key_hash=key_hash, operation="create_proposal",
            params_digest=digest, status=STATUS_PENDING,
            result_json=json.dumps(
                {"proposal_id": proposal_id}, ensure_ascii=False),
            audit_id=audit_id, created_at=now.isoformat(),
            expires_at=(now + timedelta(days=90)).isoformat(),
        )
        return created


def get_proposal(principal: Principal, proposal_id: object) -> ProposalResult:
    """按归属读取提案；他人提案返回 404，不泄漏存在性。"""
    pid = validate_proposal_id(proposal_id)
    with db.get_connection() as conn:
        row = db.get_proposal_for_owner(
            conn, pid, principal.kind, principal.id)
    if row is None:
        return ProposalResult(404, "not_found", "未找到提案", {"proposal_id": pid})
    return ProposalResult(200, "ok", "提案详情", proposal_row_to_dict(row, _now()))


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
    items = [proposal_row_to_dict(row, now) for row in rows]
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
        200, "cancelled", "提案已取消", proposal_row_to_dict(updated, now))


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
    items = [proposal_row_to_dict(row, now) for row in rows]
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
    return ProposalResult(200, "ok", "提案详情", proposal_row_to_dict(row, _now()))


def token_error(token_row: sqlite3.Row | None, now: datetime) -> str:
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
        http_status, reason, message, proposal_row_to_dict(updated, now))


def _net_shares_conn(
    conn: sqlite3.Connection, fund_code: str, channel: str,
    *, exclude_tx_id: int | None = None,
) -> float:
    """同基金同渠道的累计净份额（buy/reinvest 加、sell 减），可排除目标行。"""
    rows = conn.execute(
        "SELECT id, action, shares FROM transactions "
        "WHERE fund_code=? AND COALESCE(channel,'')=?",
        (fund_code, channel or ""),
    ).fetchall()
    total = 0.0
    for r in rows:
        if exclude_tx_id is not None and int(r["id"]) == exclude_tx_id:
            continue
        shares = float(r["shares"] or 0.0)
        if r["action"] in ("buy", "reinvest"):
            total += shares
        elif r["action"] == "sell":
            total -= shares
    return total


def _share_contribution(action: str, shares: float | None) -> float:
    value = float(shares or 0.0)
    if action in ("buy", "reinvest"):
        return value
    if action == "sell":
        return -value
    return 0.0


def _share_conflict_after_change(
    conn: sqlite3.Connection, *, old_fund: str, old_channel: str,
    new_fund: str, new_channel: str, new_action: str,
    new_shares: float | None, tx_id: int,
) -> bool:
    """判断修改/删除后是否导致任一侧累计卖出超过累计买入。

    与直记预检 ``_available_shares`` 同口径（按基金+渠道累计，不区分日期）。
    update 改基金/渠道时双侧校验；delete 视为新侧贡献为 0。
    """
    tol = 1e-6
    old_base = _net_shares_conn(
        conn, old_fund, old_channel, exclude_tx_id=tx_id)
    if (old_fund, old_channel or "") == (new_fund, new_channel or ""):
        return old_base + _share_contribution(new_action, new_shares) < -tol
    old_after = old_base  # 目标行从旧侧移除
    new_base = _net_shares_conn(
        conn, new_fund, new_channel, exclude_tx_id=tx_id)
    new_after = new_base + _share_contribution(new_action, new_shares)
    return old_after < -tol or new_after < -tol


def _exec_add_transaction(conn: sqlite3.Connection, row: sqlite3.Row,
                          clean: dict, pid: int, reviewer: str,
                          now: datetime, ip: str | None):
    """执行 add_transaction；返回 (execution, audit_id) 或失败 ProposalResult。"""
    fund_name = fund_name_in_conn(conn, clean["fund_code"])
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
    return execution, audit_id


def _exec_update_transaction(conn: sqlite3.Connection, row: sqlite3.Row,
                             clean: dict, pid: int, reviewer: str,
                             now: datetime, ip: str | None):
    """执行 update_transaction：事务内复读目标行、校验版本/转换腿/份额后更新。"""
    tx_id = int(clean["tx_id"])
    target = db.get_transaction_conn(conn, tx_id)
    if target is None:
        return _mark_failure(
            conn, row, reviewer, now, ip, status=STATUS_CONFLICT,
            reason="target_deleted", message="目标交易已被删除，无需再修改")
    if transaction_row_digest(target) != clean["expected_digest"]:
        return _mark_failure(
            conn, row, reviewer, now, ip, status=STATUS_CONFLICT,
            reason="target_changed",
            message="目标交易已被修改，请重新读取后再提案")
    if (target["conversion_id"] or "").strip():
        return _mark_failure(
            conn, row, reviewer, now, ip, status=STATUS_CONFLICT,
            reason="conversion_leg_isolated",
            message="该交易属于基金转换腿，暂不支持单独修改")
    fund_name = fund_name_in_conn(conn, clean["fund_code"])
    if fund_name is None:
        return _mark_failure(
            conn, row, reviewer, now, ip, status=STATUS_CONFLICT,
            reason="fund_missing",
            message="基金已不在当前账本中，请先在网页添加后再提案")

    tx = Transaction(
        id=tx_id,
        fund_code=clean["fund_code"], action=clean["action"],
        date=clean["date"], amount=clean.get("amount"),
        shares=clean.get("shares"), nav=clean.get("nav"),
        fee=clean.get("fee") or 0.0, channel=clean.get("channel", ""),
        note=clean.get("note", ""), is_t1=bool(clean.get("is_t1")),
        conversion_id="",
    )
    tx.normalize()
    if not tx.is_valid():
        return _mark_failure(
            conn, row, reviewer, now, ip, status=STATUS_CONFLICT,
            reason="invalid_params", message="交易信息不完整，不能执行")

    if _share_conflict_after_change(
        conn,
        old_fund=target["fund_code"], old_channel=target["channel"] or "",
        new_fund=tx.fund_code, new_channel=tx.channel or "",
        new_action=tx.action, new_shares=tx.shares, tx_id=tx_id,
    ):
        return _mark_failure(
            conn, row, reviewer, now, ip, status=STATUS_CONFLICT,
            reason="insufficient_shares_after_change",
            message="修改后同基金同渠道累计卖出将超过买入，已拒绝")

    before = _row_snapshot(target)
    db.update_transaction_conn(conn, tx)
    db.log_audit(
        "update_transaction", ip=ip, username=reviewer,
        detail={"tx_id": tx_id, "before": before,
                "after": _row_snapshot(tx), "proposal_id": pid},
        conn=conn,
    )
    execution = {
        "ok": True, "tx_id": tx_id, "before": before,
        "after": _row_snapshot(tx),
    }
    audit_id = _audit(conn, None, ip, "proposal_approved", {
        "proposal_id": pid, "operation_type": row["operation_type"],
        "tx_id": tx_id}, reviewer=reviewer)
    return execution, audit_id


def _exec_delete_transaction(conn: sqlite3.Connection, row: sqlite3.Row,
                             clean: dict, pid: int, reviewer: str,
                             now: datetime, ip: str | None):
    """执行 delete_transaction：事务内复读、校验版本/转换腿/份额后删除。"""
    tx_id = int(clean["tx_id"])
    target = db.get_transaction_conn(conn, tx_id)
    if target is None:
        return _mark_failure(
            conn, row, reviewer, now, ip, status=STATUS_CONFLICT,
            reason="target_deleted", message="目标交易已被删除，无需再删除")
    if transaction_row_digest(target) != clean["expected_digest"]:
        return _mark_failure(
            conn, row, reviewer, now, ip, status=STATUS_CONFLICT,
            reason="target_changed",
            message="目标交易已被修改，请重新读取后再提案")
    if (target["conversion_id"] or "").strip():
        return _mark_failure(
            conn, row, reviewer, now, ip, status=STATUS_CONFLICT,
            reason="conversion_leg_isolated",
            message="该交易属于基金转换腿，暂不支持单独删除")

    if _share_conflict_after_change(
        conn,
        old_fund=target["fund_code"], old_channel=target["channel"] or "",
        new_fund=target["fund_code"], new_channel=target["channel"] or "",
        new_action="", new_shares=None, tx_id=tx_id,
        # 删除等价：旧侧排除目标行后，若已超卖则拒绝。
    ):
        # 仅当删除的是买入/再投资时可能触发；删除卖出不会。
        return _mark_failure(
            conn, row, reviewer, now, ip, status=STATUS_CONFLICT,
            reason="insufficient_shares_after_change",
            message="删除后同基金同渠道累计卖出将超过买入，已拒绝")

    before = _row_snapshot(target)
    db.delete_transaction_conn(conn, tx_id)
    db.log_audit(
        "delete_transaction", ip=ip, username=reviewer,
        detail={"tx_id": tx_id, "before": before, "proposal_id": pid},
        conn=conn,
    )
    execution = {"ok": True, "tx_id": tx_id, "before": before}
    audit_id = _audit(conn, None, ip, "proposal_approved", {
        "proposal_id": pid, "operation_type": row["operation_type"],
        "tx_id": tx_id}, reviewer=reviewer)
    return execution, audit_id


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
        token_err = token_error(token_row, now)
        if token_err:
            return _mark_failure(
                conn, row, reviewer, now, ip, status=STATUS_FAILED,
                reason=token_err,
                message="创建提案的 Agent token 已失效，请重新提案")
        scopes = frozenset((token_row["scopes"] or "").split())
        required = OPERATION_SCOPE.get(row["operation_type"])
        if required is None or required not in scopes:
            return _mark_failure(
                conn, row, reviewer, now, ip, status=STATUS_FAILED,
                reason="scope_revoked",
                message="创建提案的 Agent token 已失去对应权限，请重新提案")

        try:
            clean = _validate_proposal_params(
                row["operation_type"], json.loads(row["params_json"] or "{}"))
        except (ProposalValidationError, ValueError) as exc:
            return _mark_failure(
                conn, row, reviewer, now, ip, status=STATUS_CONFLICT,
                reason="invalid_params",
                message=getattr(exc, "message", "提案参数已不合法"))

        operation_type = row["operation_type"]
        if operation_type == OPERATION_ADD_TRANSACTION:
            outcome = _exec_add_transaction(
                conn, row, clean, pid, reviewer, now, ip)
        elif operation_type == OPERATION_UPDATE_TRANSACTION:
            outcome = _exec_update_transaction(
                conn, row, clean, pid, reviewer, now, ip)
        elif operation_type == OPERATION_DELETE_TRANSACTION:
            outcome = _exec_delete_transaction(
                conn, row, clean, pid, reviewer, now, ip)
        else:
            return _mark_failure(
                conn, row, reviewer, now, ip, status=STATUS_FAILED,
                reason="unsupported_operation",
                message="提案操作类型不受支持")
        if isinstance(outcome, ProposalResult):
            return outcome
        execution, audit_id = outcome
        db.update_proposal(
            conn, pid, status=STATUS_SUCCEEDED, reviewed_by=reviewer,
            reviewed_at=now.isoformat(),
            execution_result_json=json.dumps(execution, ensure_ascii=False),
            audit_id=audit_id, completed_at=now.isoformat())
        updated = db.get_proposal(conn, pid)

    analysis.clear_analysis_cache()
    return ProposalResult(
        200, "succeeded", "提案已批准并写入账本",
        proposal_row_to_dict(updated, now))


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
        200, "rejected", "提案已拒绝", proposal_row_to_dict(updated, now))


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
