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

from . import agent_tokens, analysis, auto_invest, config, db
from .models import Transaction
from .transaction_service import (
    _DIGEST_RE,
    ACTION_LABELS,
    AMOUNT_TOLERANCE,
    CONTRACT_VERSION,
    FUND_CODE_RE,
    _duplicate_in_ledger,
    _duplicate_pending_proposal,
    _number,
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
# F5：定投计划维护。计划操作永不写 transactions 表，也不触发调度器执行；
# 启停必须走显式 toggle_plan（不得藏在 create/update 的普通参数中）。
OPERATION_CREATE_PLAN = "create_plan"
OPERATION_UPDATE_PLAN = "update_plan"
OPERATION_TOGGLE_PLAN = "toggle_plan"
OPERATION_DELETE_PLAN = "delete_plan"
PLAN_OPERATIONS = frozenset({
    OPERATION_CREATE_PLAN,
    OPERATION_UPDATE_PLAN,
    OPERATION_TOGGLE_PLAN,
    OPERATION_DELETE_PLAN,
})
# F6.1：提醒处理。只推进提醒状态机（pending → confirmed/ignored），
# 不写 transactions 表，也不支持 pending 回滚（人工走网页更正）。
OPERATION_RESOLVE_ALERT = "resolve_alert"
ALLOWED_OPERATIONS = frozenset({
    OPERATION_ADD_TRANSACTION,
    OPERATION_UPDATE_TRANSACTION,
    OPERATION_DELETE_TRANSACTION,
    OPERATION_ADD_CONVERSION,
    OPERATION_DELETE_CONVERSION,
    OPERATION_BATCH_IMPORT,
    *PLAN_OPERATIONS,
    OPERATION_RESOLVE_ALERT,
})
OPERATION_LABELS = {
    OPERATION_ADD_TRANSACTION: "新增交易",
    OPERATION_UPDATE_TRANSACTION: "修改交易",
    OPERATION_DELETE_TRANSACTION: "删除交易",
    OPERATION_ADD_CONVERSION: "基金转换",
    OPERATION_DELETE_CONVERSION: "删除转换",
    OPERATION_BATCH_IMPORT: "批量导入",
    OPERATION_CREATE_PLAN: "创建定投",
    OPERATION_UPDATE_PLAN: "修改定投",
    OPERATION_TOGGLE_PLAN: "启停定投",
    OPERATION_DELETE_PLAN: "删除定投",
    OPERATION_RESOLVE_ALERT: "处理提醒",
}

# 计划展示标签（summary_json 与既有中文标题口径一致）。
CADENCE_LABELS = {
    "daily": "每日",
    "week": "每周",
    "biweek": "每两周",
    "month": "每月",
}
_WEEKDAY_CHARS = "一二三四五六日"  # day_of_week 0=周一
PLAN_CONFIG_FIELDS = (
    "fund_code", "amount", "cadence", "day_of_week", "day_of_month",
    "channel", "note",
)

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
# 账本提案复用 transactions:propose（提议，非执行），不扩大 F0 直记 scope；
# 定投计划提案使用独立的 plans:propose（F5），与账本授权可分离签发。
OPERATION_SCOPE = {
    OPERATION_ADD_TRANSACTION: agent_tokens.SCOPE_TRANSACTIONS_PROPOSE,
    OPERATION_UPDATE_TRANSACTION: agent_tokens.SCOPE_TRANSACTIONS_PROPOSE,
    OPERATION_DELETE_TRANSACTION: agent_tokens.SCOPE_TRANSACTIONS_PROPOSE,
    OPERATION_ADD_CONVERSION: agent_tokens.SCOPE_TRANSACTIONS_PROPOSE,
    OPERATION_DELETE_CONVERSION: agent_tokens.SCOPE_TRANSACTIONS_PROPOSE,
    OPERATION_BATCH_IMPORT: agent_tokens.SCOPE_TRANSACTIONS_PROPOSE,
    OPERATION_CREATE_PLAN: agent_tokens.SCOPE_PLANS_PROPOSE,
    OPERATION_UPDATE_PLAN: agent_tokens.SCOPE_PLANS_PROPOSE,
    OPERATION_TOGGLE_PLAN: agent_tokens.SCOPE_PLANS_PROPOSE,
    OPERATION_DELETE_PLAN: agent_tokens.SCOPE_PLANS_PROPOSE,
    OPERATION_RESOLVE_ALERT: agent_tokens.SCOPE_ALERTS_PROPOSE,
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
                   fund_names: dict[str, str] | None = None,
                   plan_context: dict | None = None) -> dict[str, Any]:
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
    if operation_type == OPERATION_CREATE_PLAN:
        schedule = _plan_schedule_label(
            params["cadence"], params.get("day_of_week"),
            params.get("day_of_month"))
        return {
            "operation_type": operation_type,
            "operation_label": OPERATION_LABELS.get(operation_type, operation_type),
            "title": f"创建定投计划 {params['fund_code']}（默认停用）",
            "fund_code": params["fund_code"],
            "fund_name": fund_name,
            "amount": params.get("amount"),
            "cadence": params["cadence"],
            "cadence_label": CADENCE_LABELS.get(
                params["cadence"], params["cadence"]),
            "schedule": schedule,
            "day_of_week": params.get("day_of_week"),
            "day_of_month": params.get("day_of_month"),
            "channel": params.get("channel", ""),
            "note": params.get("note", ""),
            "enabled": False,
            "next_run": (plan_context or {}).get("next_run"),
            "scheduler_hint": (
                "计划创建后为停用状态，调度器不会执行；"
                "启用需另行提交 toggle_plan 提案"),
            "warnings": warnings,
        }
    if operation_type == OPERATION_UPDATE_PLAN:
        before_fields = _plan_snapshot(before) if before is not None else {}
        merged = _merge_plan_patch(before_fields, params)
        next_preview = (plan_context or {}).get("next_run")
        after_fields = {
            **{key: merged.get(key) for key in PLAN_CONFIG_FIELDS},
            "cadence_label": CADENCE_LABELS.get(merged.get("cadence") or "", ""),
            "enabled": bool(before_fields.get("enabled")),
            "next_run": next_preview,
            "last_run": before_fields.get("last_run"),
        }
        changed = sorted(
            key for key in PLAN_CONFIG_FIELDS
            if _norm_field(before_fields.get(key))
            != _norm_field(merged.get(key)))
        return {
            "operation_type": operation_type,
            "operation_label": OPERATION_LABELS.get(operation_type, operation_type),
            "title": f"修改定投计划 #{params['plan_id']}",
            "plan_id": params["plan_id"],
            "fund_code": merged.get("fund_code") or "",
            "fund_name": fund_name,
            "amount": merged.get("amount"),
            "cadence": merged.get("cadence"),
            "cadence_label": CADENCE_LABELS.get(
                merged.get("cadence") or "", merged.get("cadence") or ""),
            "schedule": _plan_schedule_label(
                merged.get("cadence") or "", merged.get("day_of_week"),
                merged.get("day_of_month")),
            "day_of_week": merged.get("day_of_week"),
            "day_of_month": merged.get("day_of_month"),
            "channel": merged.get("channel") or "",
            "note": merged.get("note") or "",
            "enabled": bool(before_fields.get("enabled")),
            "next_run": next_preview,
            "before": before_fields,
            "after": after_fields,
            "changed_fields": changed,
            "scheduler_hint": (
                "计划启用中：批准后下次执行日期将按新配置重算"
                if before_fields.get("enabled")
                else "计划停用中：调度器不受影响"),
            "warnings": warnings,
        }
    if operation_type == OPERATION_TOGGLE_PLAN:
        before_fields = _plan_snapshot(before) if before is not None else {}
        target_enabled = bool(params["enable"])
        next_run = before_fields.get("next_run")
        due_now = bool((plan_context or {}).get("backfill_due"))
        if target_enabled and due_now:
            scheduler_hint = "启用后调度器将尽快补投一期（与网页启停行为一致）"
        elif target_enabled and next_run:
            scheduler_hint = f"启用后下次执行 {next_run}"
        elif target_enabled:
            scheduler_hint = "启用后调度器将按频率重新排期"
        else:
            scheduler_hint = "停用后调度器不再执行该计划"
        return {
            "operation_type": operation_type,
            "operation_label": OPERATION_LABELS.get(operation_type, operation_type),
            "title": (
                f"{'启用' if target_enabled else '停用'}定投计划 "
                f"#{params['plan_id']}"),
            "plan_id": params["plan_id"],
            "fund_code": before_fields.get("fund_code", ""),
            "fund_name": fund_name,
            "amount": before_fields.get("amount"),
            "cadence": before_fields.get("cadence", ""),
            "cadence_label": before_fields.get("cadence_label", ""),
            "schedule": _plan_schedule_label(
                before_fields.get("cadence", ""),
                before_fields.get("day_of_week"),
                before_fields.get("day_of_month")),
            "channel": before_fields.get("channel", ""),
            "note": before_fields.get("note", ""),
            "enabled_before": bool(before_fields.get("enabled")),
            "enabled_after": target_enabled,
            "next_run": next_run,
            "scheduler_hint": scheduler_hint,
            "warnings": warnings,
        }
    if operation_type == OPERATION_DELETE_PLAN:
        before_fields = _plan_snapshot(before) if before is not None else {}
        return {
            "operation_type": operation_type,
            "operation_label": OPERATION_LABELS.get(operation_type, operation_type),
            "title": f"删除定投计划 #{params['plan_id']}",
            "plan_id": params["plan_id"],
            "fund_code": before_fields.get("fund_code", ""),
            "fund_name": fund_name,
            "amount": before_fields.get("amount"),
            "cadence": before_fields.get("cadence", ""),
            "cadence_label": before_fields.get("cadence_label", ""),
            "schedule": _plan_schedule_label(
                before_fields.get("cadence", ""),
                before_fields.get("day_of_week"),
                before_fields.get("day_of_month")),
            "channel": before_fields.get("channel", ""),
            "note": before_fields.get("note", ""),
            "enabled": bool(before_fields.get("enabled")),
            "next_run": before_fields.get("next_run"),
            "last_run": before_fields.get("last_run"),
            "scheduler_hint": (
                "删除后调度器不再执行该计划；历史交易不受影响"),
            "before": before_fields,
            "warnings": warnings,
        }
    if operation_type == OPERATION_RESOLVE_ALERT:
        before_fields = _alert_snapshot(before) if before is not None else {}
        alert_type = params["alert_type"]
        alert_label = {
            "dividend": "分红提醒",
            "take_profit": "止盈提醒",
            "stop_loss": "止损提醒",
        }.get(alert_type, alert_type)
        target_status = params["status"]
        if alert_type == "dividend" and target_status == "confirmed" and (
                params.get("tx_id") is None):
            warnings.append(
                "未关联分红流水：仅把提醒标记为已处理，不写入或匹配交易")
        return {
            "operation_type": operation_type,
            "operation_label": OPERATION_LABELS.get(operation_type, operation_type),
            "title": f"处理{alert_label} #{params['alert_id']}",
            "alert_id": params["alert_id"],
            "alert_type": alert_type,
            "alert_type_label": alert_label,
            "fund_code": before_fields.get("fund_code", ""),
            "fund_name": fund_name,
            "before_status": before_fields.get("status"),
            "after_status": target_status,
            "linked_tx_id": params.get("tx_id"),
            "record_date": before_fields.get("record_date"),
            "ex_date": before_fields.get("ex_date"),
            "pay_date": before_fields.get("pay_date"),
            "per_share": before_fields.get("per_share"),
            "held_shares": before_fields.get("held_shares"),
            "estimated_amount": before_fields.get("estimated_amount"),
            "dividend_method": before_fields.get("dividend_method"),
            "triggered_return": before_fields.get("triggered_return"),
            "threshold": before_fields.get("threshold"),
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


ALERT_TYPES = frozenset({"dividend", "take_profit", "stop_loss"})
# 提醒摘要覆盖「可变更业务字段」：任何状态推进或 tx 关联都会改变摘要，
# 供 resolve_alert 的 expected_digest 做版本前置（防并发覆盖）。
ALERT_DIGEST_FIELDS = (
    "status", "resolved_at", "tx_id",
    "record_date", "ex_date", "per_share", "pay_date", "held_shares",
    "estimated_amount", "dividend_method", "triggered_return", "threshold",
)
ALERT_DISPLAY_FIELDS = (
    "id", "alert_type", "fund_code", "fund_name", "status",
    "record_date", "ex_date", "pay_date", "per_share", "held_shares",
    "estimated_amount", "dividend_method", "triggered_return", "threshold",
    "resolved_at", "tx_id",
)


def alert_row_digest(row: sqlite3.Row | dict) -> str:
    """对提醒行的业务字段做规范 SHA-256（F6.1 版本前置）。

    分红与止盈止损同表（``dividend_alerts``）；``alert_type`` 为 NULL 的旧行
    按 ``dividend`` 归一，与 ``list_alerts`` 输出口径一致。
    """
    data = dict(row) if isinstance(row, sqlite3.Row) else row
    payload: dict[str, Any] = {
        "id": int(data.get("id") or 0),
        "alert_type": data.get("alert_type") or "dividend",
        "fund_code": data.get("fund_code") or "",
    }
    for name in ALERT_DIGEST_FIELDS:
        payload[name] = _norm_field(data.get(name))
    return hashlib.sha256(_canonical(payload).encode("utf-8")).hexdigest()


def _alert_snapshot(row: sqlite3.Row | dict) -> dict[str, Any]:
    """提醒展示快照（只含可读字段，不含内部 token/审计信息）。"""
    data = dict(row) if isinstance(row, sqlite3.Row) else row
    snapshot = {field: data.get(field) for field in ALERT_DISPLAY_FIELDS}
    snapshot["alert_type"] = data.get("alert_type") or "dividend"
    return snapshot


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
    plan_context: dict[str, Any] = {}
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
    elif operation_type in PLAN_OPERATIONS:
        extra = list(extra_warnings or [])
        if operation_type == OPERATION_CREATE_PLAN:
            fund_name = fund_name_in_conn(conn, resolved_fund_code)
            if fund_name is None:
                _audit(conn, principal, ip, "proposal_create_rejected", {
                    "reason": "fund_not_registered",
                    "operation_type": operation_type,
                    "fund_code": resolved_fund_code})
                return ProposalResult(
                    409, "fund_not_registered",
                    "基金尚未收录，请先在网页添加或刷新基金信息后再提案",
                    {"fund_code": resolved_fund_code})
            duplicate = conn.execute(
                "SELECT id FROM auto_invest_plans WHERE fund_code=? "
                "AND cadence=? AND COALESCE(channel,'')=? "
                "AND ROUND(amount,4)=ROUND(?,4) ORDER BY id LIMIT 1",
                (clean["fund_code"], clean["cadence"],
                 clean.get("channel", ""), clean["amount"])).fetchone()
            if duplicate is not None:
                extra.append(
                    f"已存在相同配置的定投计划 #{duplicate['id']}，"
                    "请确认是否重复创建")
            pending_dup = conn.execute(
                "SELECT 1 FROM operation_proposals WHERE operation_type=? "
                "AND status='pending' AND params_digest=? LIMIT 1",
                (OPERATION_CREATE_PLAN, digest)).fetchone()
            if pending_dup is not None:
                extra.append(
                    "已存在相同配置的待审创建提案，审批时可能互相冲突")
            plan_context["next_run"] = auto_invest.calculate_next_run_conn(
                conn, {
                    "fund_code": clean["fund_code"],
                    "cadence": clean["cadence"],
                    "day_of_week": clean.get("day_of_week"),
                    "day_of_month": clean.get("day_of_month"),
                    "next_run": None, "last_run": None,
                })
        else:
            # 计划行可能引用已被移除的基金：展示尽力取名称，不阻断操作。
            fund_name = (fund_name_in_conn(conn, resolved_fund_code)
                         or resolved_fund_code or "")
            before_data = _plan_snapshot(before) if before is not None else {}
            plan_id = clean.get("plan_id")
            rows = conn.execute(
                "SELECT id, params_json FROM operation_proposals "
                "WHERE status='pending' AND operation_type IN (?,?,?,?)",
                tuple(PLAN_OPERATIONS)).fetchall()
            related = 0
            for other in rows:
                try:
                    other_params = json.loads(other["params_json"] or "{}")
                except ValueError:
                    continue
                if other_params.get("plan_id") == plan_id:
                    related += 1
            if related:
                extra.append(
                    f"该计划已有 {related} 个待审提案，建议先处理再提交新提案")
            if operation_type == OPERATION_UPDATE_PLAN:
                merged = _merge_plan_patch(before_data, clean)
                # 仅用于展示预览；缺基金/频率时跳过（不应发生，防御）。
                if merged.get("fund_code") and merged.get("cadence"):
                    plan_context["next_run"] = (
                        auto_invest.calculate_next_run_conn(
                            conn, {
                                **merged,
                                "next_run": before_data.get("next_run"),
                                "last_run": before_data.get("last_run"),
                            }))
            elif operation_type == OPERATION_TOGGLE_PLAN:
                today = datetime.now(config.TIMEZONE).strftime("%Y-%m-%d")
                plan_context["backfill_due"] = bool(
                    clean["enable"] and before_data.get("next_run")
                    and before_data["next_run"] <= today)
        extra_warnings = extra
    elif operation_type == OPERATION_RESOLVE_ALERT:
        # 提醒可能引用已从 funds 表移除的基金：展示尽力取名称，不阻断处理。
        fund_name = (fund_name_in_conn(conn, resolved_fund_code)
                     or resolved_fund_code or "")
        extra = list(extra_warnings or [])
        related = conn.execute(
            "SELECT COUNT(*) FROM operation_proposals "
            "WHERE status='pending' AND operation_type=?",
            (OPERATION_RESOLVE_ALERT,)).fetchone()[0]
        if related:
            extra.append(
                f"当前有 {related} 个待审提醒处理提案，建议先处理再提交新提案")
        extra_warnings = extra
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
        fund_names=batch_fund_names, plan_context=plan_context)
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
    elif operation_type in PLAN_OPERATIONS:
        if clean.get("plan_id") is not None:
            audit_detail["plan_id"] = clean.get("plan_id")
        if operation_type == OPERATION_CREATE_PLAN:
            audit_detail["amount"] = clean.get("amount")
            audit_detail["cadence"] = clean.get("cadence")
    elif operation_type == OPERATION_RESOLVE_ALERT:
        audit_detail["alert_id"] = clean.get("alert_id")
        audit_detail["alert_type"] = clean.get("alert_type")
        audit_detail["status"] = clean.get("status")
        if clean.get("tx_id") is not None:
            audit_detail["tx_id"] = clean.get("tx_id")
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


# ---------------------------------------------------------------------------
# F5：定投计划参数校验
# ---------------------------------------------------------------------------
# 计划操作永不接受的字段：启停必须显式走 toggle_plan；调度器簿记由服务端
# 维护。显式拒绝避免外部把状态藏进普通参数（roadmap 硬约束）。
PLAN_FORBIDDEN_FIELDS = {
    "enabled": "启停必须提交独立的 toggle_plan 提案，不能藏在其他操作参数中",
    "next_run": "next_run 由服务端/调度器维护，不接受外部指定",
    "last_run": "last_run 由调度器维护，不接受外部指定",
    "last_tx_id": "last_tx_id 由调度器维护，不接受外部指定",
}


def _reject_plan_forbidden_fields(params: dict) -> None:
    for key, message in PLAN_FORBIDDEN_FIELDS.items():
        if key in params:
            raise ProposalValidationError(key, message)


def _validate_plan_ref(params: dict) -> tuple[int, str]:
    """校验并返回 (plan_id, expected_digest)；计划版 update/toggle/delete 共用。"""
    plan_id = params.get("plan_id")
    if isinstance(plan_id, bool) or not isinstance(plan_id, int) or plan_id <= 0:
        raise ProposalValidationError("plan_id", "plan_id 必须是正整数")
    expected_digest = params.get("expected_digest")
    if not isinstance(expected_digest, str) or not _DIGEST_RE.fullmatch(
            expected_digest.strip().lower()):
        raise ProposalValidationError(
            "expected_digest",
            "expected_digest 必须是 64 位十六进制"
            "（取自 list_auto_invest_plans 返回的 row_digest）")
    return plan_id, expected_digest.strip().lower()


def _validate_plan_day(field: str, value: object,
                       low: int, high: int, hint: str = "") -> None:
    """day_of_week/day_of_month 校验；None 表示不适用（或显式清除）。"""
    if value is None:
        return
    if (isinstance(value, bool) or not isinstance(value, int)
            or not low <= value <= high):
        raise ProposalValidationError(field, f"{field} 范围 {low}-{high}{hint}")


def _validate_plan_config(config: dict) -> None:
    """校验一份**完整**计划配置（create 原样；update 为当前行 ∪ patch）。

    与网页 ``AutoInvestPlanCreate`` 交叉规则一致并更严格：非对应频率的
    day 字段必须为 None（update 可用显式 null 清除），避免残留字段歧义。
    """
    fund_code = config.get("fund_code")
    if not isinstance(fund_code, str) or not FUND_CODE_RE.fullmatch(
            fund_code.strip()):
        raise ProposalValidationError("fund_code", "基金代码必须是 6 位数字")
    amount = _number(config.get("amount"), "amount")
    if amount is None or amount <= 0:
        raise ProposalValidationError("amount", "定投金额必须大于 0")
    cadence = config.get("cadence")
    if cadence not in auto_invest.CADENCES:
        raise ProposalValidationError(
            "cadence", f"频率仅支持 {' / '.join(auto_invest.CADENCES)}")
    _validate_plan_day("day_of_week", config.get("day_of_week"), 0, 6,
                       "（0=周一）")
    _validate_plan_day("day_of_month", config.get("day_of_month"), 1, 31)
    dow = config.get("day_of_week")
    dom = config.get("day_of_month")
    if cadence in ("week", "biweek"):
        if dow is None:
            raise ProposalValidationError(
                "day_of_week",
                "week/biweek 频率需指定 day_of_week（0-6，0=周一）")
        if dom is not None:
            raise ProposalValidationError(
                "day_of_month",
                "week/biweek 频率不支持 day_of_month，请显式置为 null")
    elif cadence == "month":
        if dom is None:
            raise ProposalValidationError(
                "day_of_month", "month 频率需指定 day_of_month（1-31）")
        if dow is not None:
            raise ProposalValidationError(
                "day_of_week",
                "month 频率不支持 day_of_week，请显式置为 null")
    else:  # daily
        if dow is not None:
            raise ProposalValidationError(
                "day_of_week",
                "daily 频率不支持 day_of_week，请显式置为 null")
        if dom is not None:
            raise ProposalValidationError(
                "day_of_month",
                "daily 频率不支持 day_of_month，请显式置为 null")


def _plan_config_from_params(params: dict) -> dict[str, Any]:
    """提取计划配置字段；缺省 None 交由 ``_validate_plan_config`` 判定。"""
    return {
        "fund_code": params.get("fund_code"),
        "amount": params.get("amount"),
        "cadence": params.get("cadence"),
        "day_of_week": params.get("day_of_week"),
        "day_of_month": params.get("day_of_month"),
        "channel": params.get("channel", ""),
        "note": params.get("note", "定投"),
    }


def validate_create_plan_params(params: object) -> dict[str, Any]:
    """校验 ``create_plan``：完整计划配置；新计划强制停用（不接受 enabled）。"""
    if not isinstance(params, dict):
        raise ProposalValidationError("params", "params 必须是对象")
    _reject_plan_forbidden_fields(params)
    unknown = set(params) - set(PLAN_CONFIG_FIELDS)
    if unknown:
        raise ProposalValidationError(
            "params", f"包含不支持的参数：{', '.join(sorted(unknown))}")
    config = _plan_config_from_params(params)
    _validate_plan_config(config)
    return {
        "fund_code": config["fund_code"].strip(),
        "amount": round(float(config["amount"]), 4),
        "cadence": config["cadence"],
        "day_of_week": config["day_of_week"],
        "day_of_month": config["day_of_month"],
        "channel": _clean_text(config["channel"], "channel", REASON_MAX_LEN),
        "note": _clean_text(config["note"], "note", REASON_MAX_LEN),
    }


def validate_update_plan_params(params: object) -> dict[str, Any]:
    """校验 ``update_plan``：部分字段 patch + 版本前置；不含启停字段。

    patch 中显式 null 表示清除 day 字段；合并后的完整配置必须满足
    ``_validate_plan_config``（由调用方在读取当前行后执行）。
    """
    if not isinstance(params, dict):
        raise ProposalValidationError("params", "params 必须是对象")
    _reject_plan_forbidden_fields(params)
    allowed = {"plan_id", "expected_digest", *PLAN_CONFIG_FIELDS}
    unknown = set(params) - allowed
    if unknown:
        raise ProposalValidationError(
            "params", f"包含不支持的参数：{', '.join(sorted(unknown))}")
    plan_id, expected_digest = _validate_plan_ref(params)
    patch: dict[str, Any] = {}
    if "fund_code" in params:
        value = params["fund_code"]
        if not isinstance(value, str) or not FUND_CODE_RE.fullmatch(
                value.strip()):
            raise ProposalValidationError("fund_code", "基金代码必须是 6 位数字")
        patch["fund_code"] = value.strip()
    if "amount" in params:
        amount = _number(params["amount"], "amount")
        if amount is None or amount <= 0:
            raise ProposalValidationError("amount", "定投金额必须大于 0")
        patch["amount"] = round(float(amount), 4)
    if "cadence" in params:
        if params["cadence"] not in auto_invest.CADENCES:
            raise ProposalValidationError(
                "cadence", f"频率仅支持 {' / '.join(auto_invest.CADENCES)}")
        patch["cadence"] = params["cadence"]
    if "day_of_week" in params:
        _validate_plan_day("day_of_week", params["day_of_week"], 0, 6,
                           "（0=周一）")
        patch["day_of_week"] = params["day_of_week"]
    if "day_of_month" in params:
        _validate_plan_day("day_of_month", params["day_of_month"], 1, 31)
        patch["day_of_month"] = params["day_of_month"]
    if "channel" in params:
        patch["channel"] = _clean_text(
            params["channel"], "channel", REASON_MAX_LEN)
    if "note" in params:
        patch["note"] = _clean_text(params["note"], "note", REASON_MAX_LEN)
    if not patch:
        raise ProposalValidationError("params", "至少需要一个可修改字段")
    return {"plan_id": plan_id, "expected_digest": expected_digest, **patch}


def validate_toggle_plan_params(params: object) -> dict[str, Any]:
    """校验 ``toggle_plan``：显式 enable 布尔 + 版本前置。"""
    if not isinstance(params, dict):
        raise ProposalValidationError("params", "params 必须是对象")
    allowed = {"plan_id", "expected_digest", "enable"}
    unknown = set(params) - allowed
    if unknown:
        raise ProposalValidationError(
            "params", f"包含不支持的参数：{', '.join(sorted(unknown))}")
    plan_id, expected_digest = _validate_plan_ref(params)
    if "enable" not in params:
        raise ProposalValidationError(
            "enable", "enable 必填（true=启用，false=停用）")
    enable = params["enable"]
    if not isinstance(enable, bool):
        raise ProposalValidationError("enable", "enable 必须是布尔值")
    return {"plan_id": plan_id, "expected_digest": expected_digest,
            "enable": enable}


def validate_delete_plan_params(params: object) -> dict[str, Any]:
    """校验 ``delete_plan``：版本前置即可（不删历史交易）。"""
    if not isinstance(params, dict):
        raise ProposalValidationError("params", "params 必须是对象")
    allowed = {"plan_id", "expected_digest"}
    unknown = set(params) - allowed
    if unknown:
        raise ProposalValidationError(
            "params", f"包含不支持的参数：{', '.join(sorted(unknown))}")
    plan_id, expected_digest = _validate_plan_ref(params)
    return {"plan_id": plan_id, "expected_digest": expected_digest}


def validate_resolve_alert_params(params: object) -> dict[str, Any]:
    """校验 ``resolve_alert``：提醒类型/ID/目标状态 + 版本前置 + 可选 tx_id。

    只允许 ``pending -> confirmed|ignored`` 单向推进，不支持回滚到 pending。
    ``tx_id`` 仅用于把**已存在**的分红/再投资流水关联到分红提醒；止盈止损
    提醒不接受 tx_id。
    """
    if not isinstance(params, dict):
        raise ProposalValidationError("params", "params 必须是对象")
    allowed = {"alert_type", "alert_id", "expected_digest", "status", "tx_id"}
    unknown = set(params) - allowed
    if unknown:
        raise ProposalValidationError(
            "params", f"包含不支持的参数：{', '.join(sorted(unknown))}")
    alert_type = params.get("alert_type")
    if alert_type not in ALERT_TYPES:
        raise ProposalValidationError(
            "alert_type", f"alert_type 仅支持 {' / '.join(sorted(ALERT_TYPES))}")
    alert_id = params.get("alert_id")
    if isinstance(alert_id, bool) or not isinstance(alert_id, int) or alert_id <= 0:
        raise ProposalValidationError("alert_id", "alert_id 必须是正整数")
    expected_digest = params.get("expected_digest")
    if not isinstance(expected_digest, str) or not _DIGEST_RE.fullmatch(
            expected_digest.strip().lower()):
        raise ProposalValidationError(
            "expected_digest",
            "expected_digest 必须是 64 位十六进制"
            "（取自 list_alerts 返回的 row_digest）")
    status = params.get("status")
    if status not in ("confirmed", "ignored"):
        raise ProposalValidationError(
            "status", "status 仅支持 confirmed / ignored"
            "（不支持回滚为 pending，误处理请走网页更正）")
    tx_id = params.get("tx_id")
    if tx_id is not None:
        if isinstance(tx_id, bool) or not isinstance(tx_id, int) or tx_id <= 0:
            raise ProposalValidationError("tx_id", "tx_id 必须是正整数")
        if alert_type != "dividend" or status != "confirmed":
            raise ProposalValidationError(
                "tx_id", "tx_id 仅支持分红提醒且 status=confirmed 时关联")
    return {
        "alert_type": alert_type,
        "alert_id": alert_id,
        "expected_digest": expected_digest.strip().lower(),
        "status": status,
        "tx_id": tx_id,
    }


def _merge_plan_patch(row: dict | sqlite3.Row, clean: dict) -> dict[str, Any]:
    """把 update patch 合并到当前行配置；patch 显式 null 表示清除该字段。"""
    base = dict(row) if isinstance(row, sqlite3.Row) else row
    return {
        key: clean[key] if key in clean else base.get(key)
        for key in PLAN_CONFIG_FIELDS
    }


def _plan_snapshot(row: dict | sqlite3.Row) -> dict[str, Any]:
    """从计划行生成展示快照（配置字段 + 调度器状态，用于前后对比）。"""
    data = dict(row) if isinstance(row, sqlite3.Row) else row
    return {
        "fund_code": data.get("fund_code") or "",
        "amount": data.get("amount"),
        "cadence": data.get("cadence") or "",
        "cadence_label": CADENCE_LABELS.get(data.get("cadence") or "", ""),
        "day_of_week": data.get("day_of_week"),
        "day_of_month": data.get("day_of_month"),
        "channel": data.get("channel") or "",
        "note": data.get("note") or "",
        "enabled": bool(data.get("enabled")),
        "next_run": data.get("next_run"),
        "last_run": data.get("last_run"),
    }


def _plan_schedule_label(
        cadence: str, day_of_week: int | None,
        day_of_month: int | None) -> str:
    """人类可读的排期标签：每日 / 每周四 / 每两周的周四 / 每月15日。"""
    if cadence == "week" and day_of_week is not None:
        return f"每周{_WEEKDAY_CHARS[day_of_week]}"
    if cadence == "biweek" and day_of_week is not None:
        return f"每两周的周{_WEEKDAY_CHARS[day_of_week]}"
    if cadence == "month" and day_of_month is not None:
        return f"每月{day_of_month}日"
    return CADENCE_LABELS.get(cadence, cadence)


def _resolve_plan_row(
        conn: sqlite3.Connection, clean: dict,
) -> tuple[sqlite3.Row | None, ProposalResult | None]:
    """定位 update/toggle/delete 的目标计划并校验版本；返回 (row, error)。"""
    plan_id = int(clean["plan_id"])
    row = db.get_auto_invest_plan_conn(conn, plan_id)
    if row is None:
        return None, ProposalResult(
            404, "target_not_found", f"未找到定投计划 {plan_id}",
            {"plan_id": plan_id})
    if auto_invest.plan_row_digest(row) != clean["expected_digest"]:
        return None, ProposalResult(
            409, "target_changed",
            "目标定投计划已被修改，请通过 list_auto_invest_plans 重新读取"
            "row_digest 后再提案",
            {"plan_id": plan_id})
    return row, None


def _validate_alert_tx_link(
        conn: sqlite3.Connection, alert: sqlite3.Row,
        tx_id: int) -> ProposalResult | None:
    """校验分红提醒关联的流水：存在、分红/再投资、同基金、未被占用。"""
    tx = db.get_transaction_conn(conn, tx_id)
    if tx is None:
        return ProposalResult(
            409, "tx_not_found", f"未找到要关联的交易 {tx_id}",
            {"alert_id": alert["id"], "tx_id": tx_id})
    if tx["action"] not in ("dividend", "reinvest"):
        return ProposalResult(
            409, "tx_mismatch",
            "关联流水必须是分红或红利再投资交易",
            {"alert_id": alert["id"], "tx_id": tx_id, "action": tx["action"]})
    if (tx["fund_code"] or "").strip() != (alert["fund_code"] or "").strip():
        return ProposalResult(
            409, "tx_mismatch", "关联流水与提醒的基金不一致",
            {"alert_id": alert["id"], "tx_id": tx_id})
    linked = conn.execute(
        "SELECT id FROM dividend_alerts WHERE tx_id=? AND id<>? LIMIT 1",
        (tx_id, alert["id"])).fetchone()
    if linked is not None:
        return ProposalResult(
            409, "tx_already_linked",
            f"该流水已关联提醒 #{linked['id']}，不能重复关联",
            {"alert_id": alert["id"], "tx_id": tx_id,
             "linked_alert_id": linked["id"]})
    return None


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
    if operation_type == OPERATION_CREATE_PLAN:
        return validate_create_plan_params(params)
    if operation_type == OPERATION_UPDATE_PLAN:
        return validate_update_plan_params(params)
    if operation_type == OPERATION_TOGGLE_PLAN:
        return validate_toggle_plan_params(params)
    if operation_type == OPERATION_DELETE_PLAN:
        return validate_delete_plan_params(params)
    if operation_type == OPERATION_RESOLVE_ALERT:
        return validate_resolve_alert_params(params)
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
        elif operation_type in PLAN_OPERATIONS:
            if operation_type == OPERATION_CREATE_PLAN:
                fund_code = clean["fund_code"]
            else:
                row, error = _resolve_plan_row(conn, clean)
                if error is not None:
                    return error
                before = _plan_snapshot(row)
                fund_code = clean.get("fund_code") or row["fund_code"]
                if operation_type == OPERATION_UPDATE_PLAN:
                    if ("fund_code" in clean
                            and fund_name_in_conn(
                                conn, clean["fund_code"]) is None):
                        _audit(conn, principal, ip,
                               "proposal_create_rejected", {
                                   "reason": "fund_not_registered",
                                   "operation_type": operation_type,
                                   "fund_code": clean["fund_code"],
                                   "plan_id": clean["plan_id"]})
                        return ProposalResult(
                            409, "fund_not_registered",
                            "基金尚未收录，请先在网页添加或刷新基金信息后再提案",
                            {"fund_code": clean["fund_code"],
                             "plan_id": clean["plan_id"]})
                    # 合并后整体校验：patch 与当前行必须构成合法完整配置。
                    _validate_plan_config(_merge_plan_patch(row, clean))
                elif operation_type == OPERATION_TOGGLE_PLAN:
                    if clean["enable"] == bool(row["enabled"]):
                        raise ProposalValidationError(
                            "enable", "计划已处于该状态，无需启停（请核对 "
                            "row_digest 是否为最新）")
        elif operation_type == OPERATION_RESOLVE_ALERT:
            alert = db.get_dividend_alert_conn(conn, int(clean["alert_id"]))
            if alert is None:
                return ProposalResult(
                    404, "target_not_found", "未找到该提醒，可能已被删除",
                    {"alert_id": clean["alert_id"]})
            actual_type = alert["alert_type"] or "dividend"
            if actual_type != clean["alert_type"]:
                raise ProposalValidationError(
                    "alert_type",
                    f"提醒类型不匹配：该提醒实际为 {actual_type}")
            if (alert["status"] or "pending") != "pending":
                return ProposalResult(
                    409, "not_pending", "该提醒已处理，无需重复提案",
                    {"alert_id": alert["id"], "status": alert["status"]})
            if alert_row_digest(alert) != clean["expected_digest"]:
                return ProposalResult(
                    409, "target_changed",
                    "提醒内容已变化，请通过 list_alerts 重新读取 "
                    "row_digest 后再提案",
                    {"alert_id": alert["id"]})
            tx_id = clean.get("tx_id")
            if tx_id is not None:
                error = _validate_alert_tx_link(conn, alert, tx_id)
                if error is not None:
                    return error
            before = _alert_snapshot(alert)
            fund_code = alert["fund_code"]

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


def _plan_target_or_failure(
        conn: sqlite3.Connection, proposal_row: sqlite3.Row, clean: dict,
        reviewer: str, now: datetime, ip: str | None, *, action: str):
    """审批期复读计划行并校验配置摘要；返回 (row, failure)。

    ``action`` 用于失败文案（修改/启停/删除）。计划已被删除或配置/启停
    已变（摘要失配）时返回 conflict，不覆盖他人的改动。
    """
    plan_id = int(clean["plan_id"])
    target = db.get_auto_invest_plan_conn(conn, plan_id)
    if target is None:
        return None, _mark_failure(
            conn, proposal_row, reviewer, now, ip, status=STATUS_CONFLICT,
            reason="target_deleted",
            message=f"目标定投计划已被删除，无需再{action}",
            extra={"plan_id": plan_id})
    if auto_invest.plan_row_digest(target) != clean["expected_digest"]:
        return None, _mark_failure(
            conn, proposal_row, reviewer, now, ip, status=STATUS_CONFLICT,
            reason="target_changed",
            message="目标定投计划已被修改，请重新读取 row_digest 后再提案",
            extra={"plan_id": plan_id})
    return target, None


def _exec_create_plan(conn: sqlite3.Connection, row: sqlite3.Row,
                      clean: dict, pid: int, reviewer: str,
                      now: datetime, ip: str | None):
    """执行 create_plan：强制 enabled=0，next_run 按执行时点计算。

    F5 永不写 transactions 表，也不触发调度器执行；新计划必须由管理员另行
    批准 toggle_plan 才会被调度器捡起。
    """
    fund_name = fund_name_in_conn(conn, clean["fund_code"])
    if fund_name is None:
        return _mark_failure(
            conn, row, reviewer, now, ip, status=STATUS_CONFLICT,
            reason="fund_missing",
            message="基金已不在当前账本中，请先在网页添加后再提案")
    plan_config = {
        "fund_code": clean["fund_code"], "amount": clean["amount"],
        "cadence": clean["cadence"],
        "day_of_week": clean.get("day_of_week"),
        "day_of_month": clean.get("day_of_month"),
    }
    next_run = auto_invest.calculate_next_run_conn(
        conn, {**plan_config, "next_run": None, "last_run": None})
    plan_id = db.add_auto_invest_plan_conn(
        conn, fund_code=clean["fund_code"], amount=clean["amount"],
        cadence=clean["cadence"], day_of_week=clean.get("day_of_week"),
        day_of_month=clean.get("day_of_month"),
        channel=clean.get("channel", ""), note=clean.get("note", "定投"),
        next_run=next_run, enabled=0)
    db.log_audit(
        "auto_invest_plan_create", ip=ip, username=reviewer,
        detail={"plan_id": plan_id, "fund_code": clean["fund_code"],
                "cadence": clean["cadence"], "amount": clean["amount"],
                "enabled": 0, "proposal_id": pid},
        conn=conn,
    )
    execution = {
        "ok": True, "plan_id": plan_id, "enabled": False,
        "fund_code": clean["fund_code"], "amount": clean["amount"],
        "cadence": clean["cadence"], "next_run": next_run,
    }
    audit_id = _audit(conn, None, ip, "proposal_approved", {
        "proposal_id": pid, "operation_type": row["operation_type"],
        "plan_id": plan_id}, reviewer=reviewer)
    return execution, audit_id


def _exec_update_plan(conn: sqlite3.Connection, row: sqlite3.Row,
                      clean: dict, pid: int, reviewer: str,
                      now: datetime, ip: str | None):
    """执行 update_plan：复读目标、校验摘要，写 patch 后重算 next_run。"""
    target, failure = _plan_target_or_failure(
        conn, row, clean, reviewer, now, ip, action="修改")
    if failure is not None:
        return failure
    if ("fund_code" in clean
            and fund_name_in_conn(conn, clean["fund_code"]) is None):
        return _mark_failure(
            conn, row, reviewer, now, ip, status=STATUS_CONFLICT,
            reason="fund_missing",
            message="基金已不在当前账本中，请先在网页添加后再提案",
            extra={"plan_id": int(clean["plan_id"])})
    try:
        merged = _merge_plan_patch(target, clean)
        _validate_plan_config(merged)
    except ProposalValidationError as exc:
        return _mark_failure(
            conn, row, reviewer, now, ip, status=STATUS_CONFLICT,
            reason="invalid_params", message=exc.message,
            extra={"plan_id": int(clean["plan_id"]), "field": exc.field})
    before = _plan_snapshot(target)
    next_run = auto_invest.calculate_next_run_conn(
        conn, {
            **merged,
            "next_run": before.get("next_run"),
            "last_run": before.get("last_run"),
        })
    db.update_auto_invest_plan_conn(
        conn, int(clean["plan_id"]),
        **{key: merged[key] for key in PLAN_CONFIG_FIELDS},
        next_run=next_run)
    after = _plan_snapshot({
        **merged, "enabled": target["enabled"], "next_run": next_run,
        "last_run": before.get("last_run"),
    })
    db.log_audit(
        "auto_invest_plan_update", ip=ip, username=reviewer,
        detail={"plan_id": int(clean["plan_id"]), "before": before,
                "after": after, "proposal_id": pid},
        conn=conn,
    )
    execution = {
        "ok": True, "plan_id": int(clean["plan_id"]),
        "before": before, "after": after,
    }
    audit_id = _audit(conn, None, ip, "proposal_approved", {
        "proposal_id": pid, "operation_type": row["operation_type"],
        "plan_id": int(clean["plan_id"])}, reviewer=reviewer)
    return execution, audit_id


def _exec_toggle_plan(conn: sqlite3.Connection, row: sqlite3.Row,
                      clean: dict, pid: int, reviewer: str,
                      now: datetime, ip: str | None):
    """执行 toggle_plan：只翻转 enabled，不重算 next_run（网页一致）。

    启用后若 next_run 已过期，调度器会尽快补投一期；执行结果附带 warning
    提示，避免管理员在审批后被补投意外。
    """
    target, failure = _plan_target_or_failure(
        conn, row, clean, reviewer, now, ip, action="启停")
    if failure is not None:
        return failure
    plan_id = int(clean["plan_id"])
    enable = bool(clean["enable"])
    if enable == bool(target["enabled"]):
        return _mark_failure(
            conn, row, reviewer, now, ip, status=STATUS_CONFLICT,
            reason="invalid_params",
            message="计划已处于目标状态，请重新读取 row_digest 后再提案",
            extra={"plan_id": plan_id})
    db.update_auto_invest_plan_conn(
        conn, plan_id, enabled=1 if enable else 0)
    today = now.strftime("%Y-%m-%d")
    warnings: list[str] = []
    if enable and target["next_run"] and target["next_run"] <= today:
        warnings.append(
            "next_run 已到期，调度器将尽快补投一期（与网页启停行为一致）")
    db.log_audit(
        "auto_invest_plan_toggle", ip=ip, username=reviewer,
        detail={"plan_id": plan_id, "enabled": 1 if enable else 0,
                "proposal_id": pid},
        conn=conn,
    )
    execution = {
        "ok": True, "plan_id": plan_id, "enabled": enable,
        "next_run": target["next_run"], "warnings": warnings,
    }
    audit_id = _audit(conn, None, ip, "proposal_approved", {
        "proposal_id": pid, "operation_type": row["operation_type"],
        "plan_id": plan_id, "enabled": enable}, reviewer=reviewer)
    return execution, audit_id


def _exec_delete_plan(conn: sqlite3.Connection, row: sqlite3.Row,
                      clean: dict, pid: int, reviewer: str,
                      now: datetime, ip: str | None):
    """执行 delete_plan：只删计划行，历史交易与调度器簿记不动。"""
    target, failure = _plan_target_or_failure(
        conn, row, clean, reviewer, now, ip, action="删除")
    if failure is not None:
        return failure
    plan_id = int(clean["plan_id"])
    before = _plan_snapshot(target)
    db.delete_auto_invest_plan_conn(conn, plan_id)
    db.log_audit(
        "auto_invest_plan_delete", ip=ip, username=reviewer,
        detail={"plan_id": plan_id, "before": before, "proposal_id": pid},
        conn=conn,
    )
    execution = {"ok": True, "plan_id": plan_id, "before": before}
    audit_id = _audit(conn, None, ip, "proposal_approved", {
        "proposal_id": pid, "operation_type": row["operation_type"],
        "plan_id": plan_id}, reviewer=reviewer)
    return execution, audit_id


def _exec_resolve_alert(conn: sqlite3.Connection, row: sqlite3.Row,
                        clean: dict, pid: int, reviewer: str,
                        now: datetime, ip: str | None):
    """执行 resolve_alert：只推进提醒状态机，不写账本。"""
    alert_id = int(clean["alert_id"])
    target = db.get_dividend_alert_conn(conn, alert_id)
    if target is None:
        return _mark_failure(
            conn, row, reviewer, now, ip, status=STATUS_CONFLICT,
            reason="target_deleted", message="目标提醒已被删除，无需再处理",
            extra={"alert_id": alert_id})
    actual_type = target["alert_type"] or "dividend"
    if actual_type != clean["alert_type"]:
        return _mark_failure(
            conn, row, reviewer, now, ip, status=STATUS_CONFLICT,
            reason="alert_type_changed",
            message="提醒类型已变化，请重新读取后再提案",
            extra={"alert_id": alert_id})
    # 先判状态：任何状态推进都会改变摘要，若先比摘要只会得到笼统的
    # target_changed，反而丢失「已处理」这一更可操作的提示。
    if (target["status"] or "pending") != "pending":
        return _mark_failure(
            conn, row, reviewer, now, ip, status=STATUS_CONFLICT,
            reason="not_pending", message="提醒已处理，不能重复审批",
            extra={"alert_id": alert_id, "status": target["status"]})
    if alert_row_digest(target) != clean["expected_digest"]:
        return _mark_failure(
            conn, row, reviewer, now, ip, status=STATUS_CONFLICT,
            reason="target_changed",
            message="提醒已被处理或修改，请重新读取 row_digest 后再提案",
            extra={"alert_id": alert_id})

    tx_id = clean.get("tx_id")
    if tx_id is not None:
        error = _validate_alert_tx_link(conn, target, int(tx_id))
        if error is not None:
            return _mark_failure(
                conn, row, reviewer, now, ip, status=STATUS_CONFLICT,
                reason=error.code, message=error.message,
                extra={"alert_id": alert_id, "tx_id": int(tx_id)})

    before = _alert_snapshot(target)
    status = clean["status"]
    resolved_at = now.isoformat()
    db.update_dividend_alert_conn(
        conn, alert_id, status=status, resolved_at=resolved_at, tx_id=tx_id)
    # 审计事件与网页对齐：分红归 dividend_alert_update，止盈止损归
    # tp_sl_alert_update；detail 带 proposal_id 区分来源。
    web_action = (
        "dividend_alert_update" if actual_type == "dividend"
        else "tp_sl_alert_update")
    db.log_audit(
        web_action, ip=ip, username=reviewer,
        detail={"id": alert_id, "status": status, "tx_id": tx_id,
                "proposal_id": pid},
        conn=conn,
    )
    execution = {
        "ok": True, "alert_id": alert_id, "alert_type": actual_type,
        "before_status": before.get("status"), "status": status,
        "resolved_at": resolved_at, "tx_id": tx_id,
    }
    audit_id = _audit(conn, None, ip, "proposal_approved", {
        "proposal_id": pid, "operation_type": row["operation_type"],
        "alert_id": alert_id, "alert_type": actual_type,
        "status": status}, reviewer=reviewer)
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
        elif operation_type == OPERATION_CREATE_PLAN:
            outcome = _exec_create_plan(
                conn, row, clean, pid, reviewer, now, ip)
        elif operation_type == OPERATION_UPDATE_PLAN:
            outcome = _exec_update_plan(
                conn, row, clean, pid, reviewer, now, ip)
        elif operation_type == OPERATION_TOGGLE_PLAN:
            outcome = _exec_toggle_plan(
                conn, row, clean, pid, reviewer, now, ip)
        elif operation_type == OPERATION_DELETE_PLAN:
            outcome = _exec_delete_plan(
                conn, row, clean, pid, reviewer, now, ip)
        elif operation_type == OPERATION_RESOLVE_ALERT:
            outcome = _exec_resolve_alert(
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
    message = ("提案已批准，提醒状态已更新"
               if operation_type == OPERATION_RESOLVE_ALERT
               else "提案已批准并写入账本")
    return ProposalResult(
        200, "succeeded", message,
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
