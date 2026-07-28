"""定投计划自动执行模块。

核心功能：
- 创建/修改/删除/查询定投计划
- 计算下一次执行日期
- 执行定投（创建买入交易）
- 批量执行所有到期计划
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from . import analysis, db, fetch_fund
from .models import ACTION_BUY, Transaction

logger = logging.getLogger(__name__)
_TZ = ZoneInfo("Asia/Shanghai")
CADENCES = ("daily", "week", "biweek", "month")


def _next_trading_day(fund_code: str, from_date: str) -> str | None:
    """从 from_date 起找下一个有净值数据的交易日。"""
    nav = db.get_nav_on_or_after(fund_code, from_date)
    return nav["date"] if nav else None


def _next_weekday(from_date: str, target_dow: int) -> str:
    """从 from_date 起找到下一个 target_dow（0=周一..6=周日）。"""
    d = datetime.strptime(from_date, "%Y-%m-%d").date()
    diff = (target_dow - d.weekday()) % 7
    if diff == 0:
        diff = 7
    return (d + timedelta(days=diff)).isoformat()


def _next_month_day(from_date: str, target_day: int) -> str:
    """下个月的 target_day，超限取月末。"""
    d = datetime.strptime(from_date, "%Y-%m-%d").date()
    year = d.year + (d.month // 12)
    month = (d.month % 12) + 1
    if month > 12:
        month = 1
        year += 1
    from calendar import monthrange
    max_day = monthrange(year, month)[1]
    return f"{year:04d}-{month:02d}-{min(target_day, max_day):02d}"


def calculate_next_run(plan: dict, from_date: str | None = None) -> str | None:
    """计算定投计划的下次执行日期。

    遇非交易日顺延到下一个有净值数据的交易日。
    """
    if from_date is None:
        from_date = plan.get("next_run") or datetime.now(_TZ).strftime("%Y-%m-%d")
    fund_code = plan["fund_code"]
    cadence = plan["cadence"]

    if cadence == "daily":
        d = datetime.strptime(from_date, "%Y-%m-%d") + timedelta(days=1)
        return _next_trading_day(fund_code, d.isoformat())

    if cadence in ("week", "biweek"):
        dow = plan.get("day_of_week")
        if dow is None:
            return None
        next_date = _next_weekday(from_date, dow)
        if cadence == "biweek":
            last_run = plan.get("last_run")
            if last_run:
                gap = (datetime.strptime(next_date, "%Y-%m-%d") -
                       datetime.strptime(last_run, "%Y-%m-%d")).days
                if gap < 14:
                    d = datetime.strptime(last_run, "%Y-%m-%d") + timedelta(days=14)
                    next_date = _next_weekday(d.isoformat(), dow)
        return _next_trading_day(fund_code, next_date)

    if cadence == "month":
        dom = plan.get("day_of_month")
        if dom is None:
            return None
        next_date = _next_month_day(from_date, dom)
        return _next_trading_day(fund_code, next_date)

    return None


def execute_plan(plan: dict, manual: bool = False) -> dict[str, Any]:
    """执行一次定投计划。

    创建一笔买入交易（nav=NULL，等 T+1 回填），
    更新计划的 last_run / last_tx_id。
    手动执行（manual=True）时不更新 next_run。

    返回执行结果 dict。
    """
    fund_code = plan["fund_code"]
    amount = plan["amount"]
    channel = plan.get("channel", "")
    note = plan.get("note", "定投")
    now = datetime.now(_TZ)
    today = now.strftime("%Y-%m-%d")
    is_after_three = now.hour >= 15

    # 自动计算手续费
    fee_result = fetch_fund.calc_purchase_fee(fund_code, amount)
    fee = fee_result.fee

    if is_after_three:
        full_note = f"{note} | T+1确认" if "T+1确认" not in note else note
    else:
        full_note = note

    tx = Transaction(
        fund_code=fund_code,
        action=ACTION_BUY,
        date=today,
        amount=amount,
        shares=None,
        nav=None,
        fee=fee,
        channel=channel,
        note=full_note,
    )
    tx_id = db.add_transaction(tx)
    analysis.clear_analysis_cache()

    db.update_auto_invest_plan(
        plan["id"],
        last_run=today,
        last_tx_id=tx_id,
    )

    if not manual:
        plan["last_run"] = today
        plan["next_run"] = calculate_next_run(plan)
        db.update_auto_invest_plan(
            plan["id"],
            next_run=plan["next_run"],
        )

    return {
        "ok": True,
        "tx_id": tx_id,
        "fund_code": fund_code,
        "amount": amount,
        "fee": fee,
        "date": today,
        "after_three": is_after_three,
    }


def run_all_due() -> list[dict[str, Any]]:
    """检查并执行所有到期的定投计划。

    返回执行结果列表。
    """
    today = datetime.now(_TZ).strftime("%Y-%m-%d")
    plans = db.get_due_auto_invest_plans(today)
    results: list[dict[str, Any]] = []
    for p in plans:
        try:
            result = execute_plan(p, manual=False)
            result["plan_id"] = p["id"]
            result["status"] = "success"
            logger.info("[auto_invest] 执行定投 plan#%d %s 金额 %.2f",
                        p["id"], p["fund_code"], p["amount"])
        except Exception as exc:
            logger.exception("[auto_invest] 定投执行失败 plan#%d", p["id"])
            result = {
                "plan_id": p["id"],
                "fund_code": p["fund_code"],
                "status": "error",
                "error": str(exc),
            }
        results.append(result)
    return results
