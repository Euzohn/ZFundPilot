"""收益率计算模块（XIRR 年化内部收益率）。

只含纯数学算法，不依赖项目其它模块，供 analysis/backtest 共用。
"""

from __future__ import annotations

import datetime as dt

from .models import ACTION_BUY, ACTION_DIVIDEND, ACTION_SELL, Transaction


def xirr(cashflows: list[tuple[dt.date, float]]) -> float | None:
    """计算 XIRR（年化内部收益率），二分法求解。

    cashflows: [(date, amount), ...]，负数=流出（投入），正数=流入（变现）
    返回小数（0.15 表示 15%），无解返回 None。
    """
    if len(cashflows) < 2:
        return None

    d0 = cashflows[0][0]

    def npv(rate: float) -> float:
        total = 0.0
        for d, amt in cashflows:
            years = (d - d0).days / 365.0
            total += amt / ((1 + rate) ** years)
        return total

    lo, hi = -0.999, 10.0
    npv_lo = npv(lo)
    npv_hi = npv(hi)

    if npv_lo * npv_hi > 0:
        return None

    for _ in range(200):
        mid = (lo + hi) / 2
        npv_mid = npv(mid)
        if abs(npv_mid) < 1e-7:
            return mid
        if npv_mid * npv_lo < 0:
            hi = mid
        else:
            lo = mid
            npv_lo = npv_mid

    return (lo + hi) / 2


def _build_xirr_cashflows(
    transactions: list[Transaction],
    terminal_value: float,
    terminal_date: dt.date,
) -> list[tuple[dt.date, float]]:
    """从交易流水构建 XIRR 现金流。

    BUY    → 负（流出）
    SELL   → 正（流入，净收入含手续费按 Transaction 约定）
    DIVIDEND → 正（现金分红流入）
    REINVEST → 跳过（现金中性：同日分红出 + 买入入）
    终端值: 正（持仓未卖，用市值作"假设变现"），仅 terminal_value > 0 时加入
    """
    cashflows: list[tuple[dt.date, float]] = []
    for tx in transactions:
        tx.normalize()
        if not tx.amount:
            continue
        d = dt.date.fromisoformat(tx.date)
        if tx.action == ACTION_BUY:
            cashflows.append((d, -(tx.amount)))
        elif tx.action == ACTION_SELL:
            cashflows.append((d, tx.amount))
        elif tx.action == ACTION_DIVIDEND:
            cashflows.append((d, tx.amount))
        # REINVEST: skip（现金中性）
    if terminal_value > 0:
        cashflows.append((terminal_date, terminal_value))
    return cashflows
