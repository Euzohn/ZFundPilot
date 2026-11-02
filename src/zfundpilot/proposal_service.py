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
    AMOUNT_TOLERANCE,
    CONTRACT_VERSION,
    _duplicate_in_ledger,
    _duplicate_pending_proposal,
    _parse_pending_rows,
    _pending_proposal_rows,
    _same_number,
    build_conversion_legs,
    transaction_row_digest,
    validate_add_conversion_params,
    validate_add_transaction_params,
    validate_delete_conversion_params,
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
OPERATION_ADD_CONVERSION = "add_conversion"
OPERATION_DELETE_CONVERSION = "delete_conversion"
OPERATION_BATCH_IMPORT = "batch_import"
ALLOWED_OPERATIONS = frozenset({
    OPERATION_ADD_TRANSACTION,
    OPERATION_UPDATE_TRANSACTION,
    OPERATION_DELETE_TRANSACTION,
    OPERATION_ADD_CONVERSION,
    OPERATION_DELETE_CONVERSION,
    OPERATION_BATCH_IMPORT,
})
OPERATION_LABELS = {
    OPERATION_ADD_TRANSACTION: "新增交易",
    OPERATION_UPDATE_TRANSACTION: "修改交易",
    OPERATION_DELETE_TRANSACTION: "删除交易",
    OPERATION_ADD_CONVERSION: "基金转换",
    OPERATION_DELETE_CONVERSION: "删除转换",
    OPERATION_BATCH_IMPORT: "批量导入",
}

PROPOSAL_TTL_DAYS = 7
PROPOSAL_PURGE_DAYS = 30
MAX_PENDING_PER_OWNER = 20
REASON_MAX_LEN = 500
MAX_BATCH_ITEMS = 50

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
    OPERATION_ADD_CONVERSION: agent_tokens.SCOPE_TRANSACTIONS_PROPOSE,
    OPERATION_DELETE_CONVERSION: agent_tokens.SCOPE_TRANSACTIONS_PROPOSE,
    OPERATION_BATCH_IMPORT: agent_tokens.SCOPE_TRANSACTIONS_PROPOSE,
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
                   *, before: dict | sqlite3.Row | None = None,
                   fund_names: dict[str, str] | None = None) -> dict[str, Any]:
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
    if operation_type == OPERATION_ADD_CONVERSION:
        if params.get("from_nav") is None or params.get("to_nav") is None:
            warnings.append("成交净值尚未确定，市值与收益可能暂时缺失")
        if params.get("is_t1"):
            warnings.append("T+1 确认：转入份额可能尚未到账，需后续核对")
        warnings.append("请核对转出份额是否超过该渠道可用份额")
        from_tx, to_tx = build_conversion_legs(params)
        return {
            "operation_type": operation_type,
            "operation_label": OPERATION_LABELS.get(operation_type, operation_type),
            "title": f"转换 {params['from_code']} → {params['to_code']}",
            "fund_code": params["from_code"],
            "fund_name": fund_name,
            "action": "conversion",
            "action_label": "转换",
            "date": params["date"],
            "amount": None,
            "shares": from_tx.shares,
            "nav": from_tx.nav,
            "fee": from_tx.fee,
            "channel": params.get("channel", ""),
            "is_t1": params.get("is_t1", False),
            "note": params.get("note", ""),
            "conversion": {
                "from": {
                    "fund_code": from_tx.fund_code,
                    "action": from_tx.action, "action_label": "卖出",
                    "shares": from_tx.shares,
                    "nav": from_tx.nav,
                    "fee": from_tx.fee,
                },
                "to": {
                    "fund_code": to_tx.fund_code,
                    "action": to_tx.action, "action_label": "买入",
                    "amount": to_tx.amount,
                    "shares": to_tx.shares,
                    "nav": to_tx.nav,
                    "fee": to_tx.fee,
                },
            },
            "warnings": warnings,
        }
    if operation_type == OPERATION_DELETE_CONVERSION:
        before_pair = before if isinstance(before, dict) else {}
        from_snap = before_pair.get("from", {}) or {}
        to_snap = before_pair.get("to", {}) or {}
        from_code = from_snap.get("fund_code", "")
        to_code = to_snap.get("fund_code", "")
        return {
            "operation_type": operation_type,
            "operation_label": OPERATION_LABELS.get(operation_type, operation_type),
            "title": f"删除转换 {from_code} → {to_code}",
            "fund_code": from_code,
            "fund_name": fund_name,
            "action": "conversion",
            "action_label": "转换",
            "date": from_snap.get("date", ""),
            "amount": None,
            "shares": from_snap.get("shares"),
            "nav": from_snap.get("nav"),
            "fee": from_snap.get("fee"),
            "channel": from_snap.get("channel", ""),
            "is_t1": from_snap.get("is_t1", False),
            "note": from_snap.get("note", ""),
            "conversion_id": params.get("conversion_id", ""),
            "reason": params.get("reason", ""),
            "conversion": {
                "from": from_snap,
                "to": to_snap,
            },
            "before": before_pair,
            "warnings": warnings,
        }
    if operation_type == OPERATION_BATCH_IMPORT:
        items = params.get("transactions") or []
        names = fund_names or {}
        actions: dict[str, int] = {}
        funds: dict[str, str] = {}
        amount_total = 0.0
        dates: list[str] = []
        for item in items:
            action = item.get("action", "")
            actions[action] = actions.get(action, 0) + 1
            code = item.get("fund_code", "")
            if code and code not in funds:
                funds[code] = names.get(code) or code
            amount = item.get("amount")
            if amount is not None:
                amount_total += float(amount)
            if item.get("date"):
                dates.append(item["date"])
        if any(item.get("nav") is None for item in items):
            warnings.append("部分条目成交净值尚未确定，市值与收益可能暂时缺失")
        if any(item.get("is_t1") for item in items):
            warnings.append("部分条目为 T+1 确认：份额可能尚未到账，需后续核对")
        if any(item.get("action") == "sell" for item in items):
            warnings.append("请核对各卖出条目的份额是否超过对应渠道最终可用份额")
        ignored = params.get("ignored_fields") or []
        if ignored:
            warnings.append(
                "已忽略不支持的批量字段：" + "、".join(ignored)
                + "（永不执行清空或联网拉取）")
        return {
            "operation_type": operation_type,
            "operation_label": OPERATION_LABELS.get(operation_type, operation_type),
            "title": f"批量导入 {len(items)} 条交易",
            "count": len(items),
            "actions": actions,
            "funds": [{"fund_code": code, "fund_name": name}
                      for code, name in funds.items()],
            "date_range": {
                "from": min(dates) if dates else "",
                "to": max(dates) if dates else "",
            },
            "amount_total": amount_total,
            "note": params.get("note", ""),
            "items": [_batch_item_view(item, names) for item in items],
            "warnings": warnings,
        }
    # 兜底：不应到达
    return {"operation_type": operation_type,
            "operation_label": OPERATION_LABELS.get(operation_type, operation_type),
            "warnings": warnings}


def _batch_item_view(item: dict, fund_names: dict[str, str]) -> dict[str, Any]:
    """把批量条目渲染为展示字典（供提案详情逐条展示）。"""
    action = item.get("action", "")
    code = item.get("fund_code", "")
    return {
        "fund_code": code,
        "fund_name": fund_names.get(code, ""),
        "action": action,
        "action_label": ACTION_LABELS.get(action, action),
        "date": item.get("date", ""),
        "amount": item.get("amount"),
        "shares": item.get("shares"),
        "nav": item.get("nav"),
        "fee": item.get("fee"),
        "channel": item.get("channel", ""),
        "note": item.get("note", ""),
        "is_t1": item.get("is_t1", False),
    }


def _batch_internal_duplicate(transactions: list[dict]) -> tuple[int, int] | None:
    """检测批量条目间的重复：同基金+渠道+日期+方向且金额或份额相近。

    返回首个重复对的 ``(index, other_index)``；无重复返回 ``None``。
    """
    for i, left in enumerate(transactions):
        for j in range(i + 1, len(transactions)):
            right = transactions[j]
            if (left.get("fund_code") != right.get("fund_code")
                    or (left.get("channel") or "") != (right.get("channel") or "")
                    or left.get("date") != right.get("date")
                    or left.get("action") != right.get("action")):
                continue
            if (_same_number(left.get("amount"), right.get("amount"))
                    or _same_number(left.get("shares"), right.get("shares"))):
                return i, j
    return None


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
    batch_fund_names: dict[str, str] = {}
    if operation_type == OPERATION_BATCH_IMPORT:
        # 批量：逐条校验基金已收录 + 批内重复硬拒绝；与账本/待审提案重复仅 warning。
        transactions = clean.get("transactions") or []
        for idx, item in enumerate(transactions):
            code = item.get("fund_code")
            name = fund_name_in_conn(conn, code) if code else None
            if name is None:
                _audit(conn, principal, ip, "proposal_create_rejected", {
                    "reason": "fund_not_registered",
                    "operation_type": operation_type,
                    "index": idx, "fund_code": code})
                return ProposalResult(
                    409, "fund_not_registered",
                    "基金尚未收录，请先在网页添加或刷新基金信息后再提案",
                    {"index": idx, "fund_code": code})
            batch_fund_names[code] = name
        duplicate = _batch_internal_duplicate(transactions)
        if duplicate is not None:
            first, other = duplicate
            _audit(conn, principal, ip, "proposal_create_rejected", {
                "reason": "batch_internal_duplicate",
                "operation_type": operation_type,
                "index": first, "other_index": other})
            return ProposalResult(
                409, "batch_internal_duplicate",
                "批量条目中存在重复交易，请检查后再提交",
                {"index": first, "other_index": other})
        parsed_pending = _parse_pending_rows(
            _pending_proposal_rows(conn, now))
        ledger_dups: list[int] = []
        pending_dups: list[int] = []
        for idx, item in enumerate(transactions):
            if _duplicate_in_ledger(conn, item) is not None:
                ledger_dups.append(idx)
            if _duplicate_pending_proposal(
                    conn, item, now, principal, parsed=parsed_pending) is not None:
                pending_dups.append(idx)
        extra = list(extra_warnings or [])
        if ledger_dups:
            extra.append(
                "第 " + "、".join(str(i) for i in ledger_dups)
                + " 条与账本已有流水疑似重复，请核对")
        if pending_dups:
            extra.append(
                "第 " + "、".join(str(i) for i in pending_dups)
                + " 条与待审提案疑似重复，请核对")
        extra_warnings = extra
        resolved_fund_code = (
            transactions[0].get("fund_code") if transactions else None)
        fund_name = batch_fund_names.get(resolved_fund_code, "")
    elif operation_type == OPERATION_DELETE_TRANSACTION:
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
        fund_name, operation_type, clean, extra_warnings, before=before,
        fund_names=batch_fund_names)
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
    elif operation_type == OPERATION_BATCH_IMPORT:
        audit_detail["count"] = len(clean.get("transactions") or [])
        audit_detail.pop("fund_code", None)
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
class BatchValidationError(ProposalValidationError):
    """批量导入参数校验失败；携带首条出错条目的索引与逐条问题。

    ``index`` 为出错条目在 ``transactions`` 数组中的下标；``item_issues``
    为该条目的字段级问题列表（与单条 ``add_transaction`` 校验一致）。
    """

    def __init__(self, index: int, item_issues: list[dict],
                 message: str = "") -> None:
        self.index = index
        self.item_issues = item_issues
        super().__init__(
            f"transactions[{index}]", message or "批量条目校验失败")


def validate_batch_import_params(params: object) -> dict[str, Any]:
    """校验 ``batch_import`` 参数：结构 + 逐条 ``add_transaction`` 校验。

    返回 ``{"transactions": [clean, ...], "note": str}``。``clear_existing``
    等不接受字段在调用方忽略并 warning（此处不报错）；``fund_name`` 不接受，
    每条必须 ``fund_code``（由 ``validate_add_transaction_params`` 保证）。

    任一条条目校验失败 → 抛 ``BatchValidationError``（首条出错条目）。
    """
    if not isinstance(params, dict):
        raise ProposalValidationError("params", "params 必须是对象")
    # 顶层仅接受 transactions/note；clear_existing/fetch_meta 识别后忽略，
    # 其余字段视为笔误直接拒绝，避免拼写错误被静默吞掉。``ignored_fields``
    # 是服务端回写的忽略清单，审批期重新校验时必须放行。
    unknown = set(params) - {"transactions", "note", "clear_existing",
                             "fetch_meta", "ignored_fields"}
    if unknown:
        raise ProposalValidationError(
            "params", f"包含不支持的参数：{', '.join(sorted(unknown))}")
    transactions = params.get("transactions")
    if not isinstance(transactions, list):
        raise ProposalValidationError(
            "transactions", "transactions 必须是数组")
    if not transactions:
        raise ProposalValidationError(
            "transactions", "transactions 不能为空")
    if len(transactions) > MAX_BATCH_ITEMS:
        raise ProposalValidationError(
            "transactions",
            f"批量条目数超过 {MAX_BATCH_ITEMS} 上限")
    note = _clean_text(params.get("note"), "note", REASON_MAX_LEN)
    cleaned: list[dict[str, Any]] = []
    for idx, item in enumerate(transactions):
        try:
            clean = validate_add_transaction_params(item)
        except ProposalValidationError as exc:
            raise BatchValidationError(
                idx, [{"field": exc.field, "code": "invalid_item",
                       "message": exc.message}],
                f"第 {idx} 条交易校验失败：{exc.message}") from exc
        if "dividend_alert_id" in clean:
            # 批量不支持分红提醒原子关联（见设计 §0/Q6），提示改用单条提案。
            raise BatchValidationError(
                idx, [{"field": "dividend_alert_id",
                       "code": "unsupported_in_batch",
                       "message": "批量导入不支持关联分红提醒，请改用单条分红提案"}],
                f"第 {idx} 条不支持 dividend_alert_id")
        cleaned.append(clean)
    result: dict[str, Any] = {"transactions": cleaned, "note": note}
    # 永不接受的字段：忽略并记录为 warning，不因笔误整体失败。
    ignore_keys = {"clear_existing", "fetch_meta"}
    carried = params.get("ignored_fields")
    if carried is not None:
        # 审批期重新校验会复读创建时回写的忽略清单；外部若直接传入，
        # 必须是字符串数组，否则 set() 遇到不可哈希元素会抛未捕获 TypeError。
        if (not isinstance(carried, list)
                or not all(isinstance(v, str) for v in carried)):
            raise ProposalValidationError(
                "ignored_fields", "ignored_fields 必须是字符串数组")
    carried_keys = set(carried) if isinstance(carried, list) else set()
    ignored = sorted((set(params) & ignore_keys) | (carried_keys & ignore_keys))
    if ignored:
        result["ignored_fields"] = ignored
    return result


def _validate_proposal_params(operation_type: str, params: object) -> dict:
    """按操作类型分派参数校验；返回规范化后的参数字典。"""
    if operation_type == OPERATION_ADD_TRANSACTION:
        return validate_add_transaction_params(params)
    if operation_type == OPERATION_UPDATE_TRANSACTION:
        return validate_update_transaction_params(params)
    if operation_type == OPERATION_DELETE_TRANSACTION:
        return validate_delete_transaction_params(params)
    if operation_type == OPERATION_ADD_CONVERSION:
        return validate_add_conversion_params(params)
    if operation_type == OPERATION_DELETE_CONVERSION:
        return validate_delete_conversion_params(params)
    if operation_type == OPERATION_BATCH_IMPORT:
        return validate_batch_import_params(params)
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


def _resolve_conversion_pair(
        conn: sqlite3.Connection, clean: dict,
) -> tuple[tuple[sqlite3.Row, sqlite3.Row] | None, ProposalResult | None]:
    """定位 delete_conversion 的两腿并校验版本；返回 ((from_row, to_row), error)。

    要求 conversion_id 恰好关联 2 条流水且分别为 sell/buy 标准对，否则
    ``conversion_leg_mismatch``；任一腿 digest 不匹配 ``target_changed``
    （区分 ``leg: from/to``）。
    """
    cid = clean["conversion_id"]
    rows = db.get_conversion_pair_conn(conn, cid)
    if len(rows) != 2:
        return None, ProposalResult(
            404, "conversion_not_found",
            "未找到该转换对，或已非成对存在", {"conversion_id": cid})
    from_row = next((r for r in rows if r["action"] == "sell"), None)
    to_row = next((r for r in rows if r["action"] == "buy"), None)
    if from_row is None or to_row is None:
        return None, ProposalResult(
            409, "conversion_leg_mismatch",
            "该 conversion_id 关联的两条流水非标准转换对（缺卖出腿或买入腿）",
            {"conversion_id": cid})
    if transaction_row_digest(from_row) != clean["expected_from_digest"]:
        return None, ProposalResult(
            409, "target_changed",
            "转出腿已被修改，请通过 get_transaction 重新读取后再提案",
            {"conversion_id": cid, "leg": "from"})
    if transaction_row_digest(to_row) != clean["expected_to_digest"]:
        return None, ProposalResult(
            409, "target_changed",
            "转入腿已被修改，请通过 get_transaction 重新读取后再提案",
            {"conversion_id": cid, "leg": "to"})
    return (from_row, to_row), None


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
        elif operation_type == OPERATION_ADD_CONVERSION:
            fund_code = clean["from_code"]
            # 创建期校验转出+转入基金均已收录，保证审批路径不联网。
            if fund_name_in_conn(conn, clean["to_code"]) is None:
                _audit(conn, principal, ip, "proposal_create_rejected", {
                    "reason": "fund_not_registered",
                    "operation_type": operation_type,
                    "fund_code": clean["to_code"]})
                return ProposalResult(
                    409, "fund_not_registered",
                    "基金尚未收录，请先在网页添加或刷新基金信息后再提案",
                    {"fund_code": clean["to_code"]})
        elif operation_type == OPERATION_DELETE_CONVERSION:
            pair, error = _resolve_conversion_pair(conn, clean)
            if error is not None:
                return error
            from_row, to_row = pair
            fund_code = from_row["fund_code"]
            before = {"from": _row_snapshot(from_row),
                      "to": _row_snapshot(to_row)}

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
                  message: str, http_status: int = 409,
                  extra: dict | None = None) -> ProposalResult:
    execution: dict[str, Any] = {
        "ok": False, "reason": reason, "message": message}
    if extra:
        execution.update(extra)
    audit_detail: dict[str, Any] = {
        "proposal_id": row["id"], "operation_type": row["operation_type"],
        "reason": reason}
    if extra:
        for key in ("index", "other_index", "executed_before_failure"):
            if key in extra:
                audit_detail[key] = extra[key]
    audit_id = _audit(conn, None, ip, f"proposal_{status}", audit_detail,
                      reviewer=reviewer)
    db.update_proposal(
        conn, row["id"], status=status, reviewed_by=reviewer,
        reviewed_at=now.isoformat(),
        execution_result_json=json.dumps(execution, ensure_ascii=False),
        audit_id=audit_id, completed_at=now.isoformat())
    updated = db.get_proposal(conn, row["id"])
    data = proposal_row_to_dict(updated, now)
    if extra:
        data.update(extra)
    return ProposalResult(
        http_status, reason, message, data)


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
    # F2：dividend_alert_id 关联分红提醒（仅 dividend/reinvest）。
    # 先校验提醒状态，再写流水，避免失败时把流水留在已提交事务中。
    alert_id = clean.get("dividend_alert_id")
    alert = None
    if alert_id is not None:
        alert = db.get_dividend_alert_conn(conn, int(alert_id))
        if alert is None:
            return _mark_failure(
                conn, row, reviewer, now, ip, status=STATUS_CONFLICT,
                reason="dividend_alert_not_found",
                message="关联的分红提醒已不存在，请重新提案")
        if (alert["status"] or "") != "pending":
            return _mark_failure(
                conn, row, reviewer, now, ip, status=STATUS_CONFLICT,
                reason="dividend_alert_resolved",
                message="关联的分红提醒已处理（confirmed/ignored），请重新提案")
        if (alert["alert_type"] or "dividend") != "dividend":
            return _mark_failure(
                conn, row, reviewer, now, ip, status=STATUS_CONFLICT,
                reason="dividend_alert_type_mismatch",
                message="该提醒不是分红类型，不能关联分红/再投资流水")
        if (alert["fund_code"] or "") != tx.fund_code:
            return _mark_failure(
                conn, row, reviewer, now, ip, status=STATUS_CONFLICT,
                reason="dividend_alert_fund_mismatch",
                message="分红提醒的基金与流水基金不一致")

    tx_id = db.insert_transaction(conn, tx)

    if alert is not None:
        db.update_dividend_alert_conn(
            conn, int(alert_id), status="confirmed",
            tx_id=tx_id, resolved_at=now.isoformat())
        db.log_audit(
            "dividend_alert_confirm", ip=ip, username=reviewer,
            detail={"alert_id": int(alert_id), "tx_id": tx_id,
                    "proposal_id": pid},
            conn=conn,
        )

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


def _exec_batch_import(conn: sqlite3.Connection, row: sqlite3.Row,
                       clean: dict, pid: int, reviewer: str,
                       now: datetime, ip: str | None):
    """执行批量导入：先整体校验，全部通过后再逐条写入（无半完成）。

    任何一条校验失败（基金被删、参数失效、卖出导致最终余额为负）都在写入
    前返回，因此无需依赖事务回滚即可保证「全部成功或全部不做」。份额按
    「基金+渠道」最终累计余额口径校验，批内按数组顺序累加。
    """
    transactions = clean.get("transactions") or []
    prepared: list[Transaction] = []
    share_deltas: dict[tuple[str, str], float] = {}
    for idx, item in enumerate(transactions):
        fund_name = fund_name_in_conn(conn, item["fund_code"])
        if fund_name is None:
            return _mark_failure(
                conn, row, reviewer, now, ip, status=STATUS_CONFLICT,
                reason="fund_missing",
                message="基金已不在当前账本中，请先在网页添加后再提交",
                extra={"index": idx, "fund_code": item["fund_code"],
                       "executed_before_failure": 0})
        tx = Transaction(
            fund_code=item["fund_code"], action=item["action"],
            date=item["date"], amount=item.get("amount"),
            shares=item.get("shares"), nav=item.get("nav"),
            fee=item.get("fee") or 0.0, channel=item.get("channel", ""),
            note=item.get("note", ""), is_t1=bool(item.get("is_t1")),
        )
        tx.normalize()
        if not tx.is_valid():
            return _mark_failure(
                conn, row, reviewer, now, ip, status=STATUS_CONFLICT,
                reason="invalid_params",
                message="批量中某条交易信息不完整，不能执行",
                extra={"index": idx, "executed_before_failure": 0})
        key = (tx.fund_code, tx.channel or "")
        base = _net_shares_conn(conn, tx.fund_code, tx.channel)
        running = share_deltas.get(key, 0.0)
        contribution = _share_contribution(tx.action, tx.shares)
        if base + running + contribution < -AMOUNT_TOLERANCE:
            return _mark_failure(
                conn, row, reviewer, now, ip, status=STATUS_CONFLICT,
                reason="insufficient_shares_after_change",
                message="批量中某条卖出超过该渠道最终可用份额，请核对",
                extra={"index": idx, "fund_code": tx.fund_code,
                       "channel": tx.channel,
                       "available": base + running,
                       "executed_before_failure": 0})
        share_deltas[key] = running + contribution
        prepared.append(tx)

    tx_ids: list[int] = []
    for idx, tx in enumerate(prepared):
        tx_id = db.insert_transaction(conn, tx)
        tx_ids.append(tx_id)
        db.log_audit(
            "add_transaction", ip=ip, username=reviewer,
            detail={"tx_id": tx_id, "fund_code": tx.fund_code,
                    "action": tx.action, "date": tx.date,
                    "amount": tx.amount, "shares": tx.shares,
                    "proposal_id": pid, "batch_index": idx},
            conn=conn,
        )
    execution = {"ok": True, "tx_ids": tx_ids, "count": len(tx_ids)}
    audit_id = _audit(conn, None, ip, "proposal_approved", {
        "proposal_id": pid, "operation_type": row["operation_type"],
        "count": len(tx_ids), "tx_ids": tx_ids}, reviewer=reviewer)
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


def _conversion_share_warnings(
        conn: sqlite3.Connection, from_tx: Transaction) -> list[str]:
    """转换转出份额超过该渠道可用份额时返回 warning；不阻断（§6.2）。"""
    warnings: list[str] = []
    available = _net_shares_conn(
        conn, from_tx.fund_code, from_tx.channel or "")
    if float(from_tx.shares or 0.0) > available + 1e-6:
        warnings.append("转出份额可能超过该渠道可用份额，请核对持仓")
    return warnings


def _exec_add_conversion(conn: sqlite3.Connection, row: sqlite3.Row,
                         clean: dict, pid: int, reviewer: str,
                         now: datetime, ip: str | None):
    """执行 add_conversion：复核基金收录与腿完整性后成对写入。

    审批路径不联网抓净值；缺失净值留空由既有回填流程后续补齐。
    份额不足仅 warning 不阻断（转换常用于补录历史/迁移持仓）。
    """
    from_name = fund_name_in_conn(conn, clean["from_code"])
    to_name = fund_name_in_conn(conn, clean["to_code"])
    if from_name is None or to_name is None:
        return _mark_failure(
            conn, row, reviewer, now, ip, status=STATUS_CONFLICT,
            reason="fund_missing",
            message="转出或转入基金已不在账本中，请先在网页添加后再提案")

    from_tx, to_tx = build_conversion_legs(clean)
    if not from_tx.is_valid() or (
            not clean.get("is_t1") and not to_tx.is_valid()):
        return _mark_failure(
            conn, row, reviewer, now, ip, status=STATUS_CONFLICT,
            reason="invalid_params", message="转换信息不完整，不能执行")

    warnings = _conversion_share_warnings(conn, from_tx)
    from_id, to_id = db.add_conversion_conn(conn, from_tx, to_tx)
    db.log_audit(
        "add_conversion", ip=ip, username=reviewer,
        detail={"from_id": from_id, "to_id": to_id,
                "from_code": from_tx.fund_code, "to_code": to_tx.fund_code,
                "date": from_tx.date, "proposal_id": pid},
        conn=conn,
    )
    execution = {
        "ok": True, "from_id": from_id, "to_id": to_id,
        "from": _row_snapshot(from_tx), "to": _row_snapshot(to_tx),
        "warnings": warnings,
    }
    audit_id = _audit(conn, None, ip, "proposal_approved", {
        "proposal_id": pid, "operation_type": row["operation_type"],
        "from_id": from_id, "to_id": to_id}, reviewer=reviewer)
    return execution, audit_id


def _exec_delete_conversion(conn: sqlite3.Connection, row: sqlite3.Row,
                            clean: dict, pid: int, reviewer: str,
                            now: datetime, ip: str | None):
    """执行 delete_conversion：事务内复读两腿、校验版本后成对删除。

    份额连带仅校验买入腿（to）删除是否致转入基金后续超卖；卖出腿（from）
    删除释放份额，恒放行。
    """
    pair, error = _resolve_conversion_pair(conn, clean)
    if error is not None:
        return _mark_failure(
            conn, row, reviewer, now, ip, status=STATUS_CONFLICT,
            reason=error.code, message=error.message)

    from_row, to_row = pair
    if _share_conflict_after_change(
        conn,
        old_fund=to_row["fund_code"], old_channel=to_row["channel"] or "",
        new_fund=to_row["fund_code"], new_channel=to_row["channel"] or "",
        new_action="", new_shares=None, tx_id=int(to_row["id"]),
    ):
        return _mark_failure(
            conn, row, reviewer, now, ip, status=STATUS_CONFLICT,
            reason="insufficient_shares_after_change",
            message="删除后转入基金同渠道累计卖出将超过买入，已拒绝")

    before = {"from": _row_snapshot(from_row), "to": _row_snapshot(to_row)}
    db.delete_conversion_pair_conn(conn, clean["conversion_id"])
    db.log_audit(
        "delete_conversion", ip=ip, username=reviewer,
        detail={"conversion_id": clean["conversion_id"],
                "from_id": int(from_row["id"]), "to_id": int(to_row["id"]),
                "proposal_id": pid},
        conn=conn,
    )
    execution = {
        "ok": True, "conversion_id": clean["conversion_id"],
        "from_id": int(from_row["id"]), "to_id": int(to_row["id"]),
        "before": before,
    }
    audit_id = _audit(conn, None, ip, "proposal_approved", {
        "proposal_id": pid, "operation_type": row["operation_type"],
        "conversion_id": clean["conversion_id"]}, reviewer=reviewer)
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
        except BatchValidationError as exc:
            return _mark_failure(
                conn, row, reviewer, now, ip, status=STATUS_CONFLICT,
                reason="invalid_params",
                message=exc.message,
                extra={"index": exc.index, "issues": exc.item_issues})
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
        elif operation_type == OPERATION_ADD_CONVERSION:
            outcome = _exec_add_conversion(
                conn, row, clean, pid, reviewer, now, ip)
        elif operation_type == OPERATION_DELETE_CONVERSION:
            outcome = _exec_delete_conversion(
                conn, row, clean, pid, reviewer, now, ip)
        elif operation_type == OPERATION_BATCH_IMPORT:
            outcome = _exec_batch_import(
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
