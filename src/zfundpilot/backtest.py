"""定投策略回测模块。

功能：
- 对指定基金在历史净值上模拟定投（Dollar Cost Averaging）
- 与「一次性投入」方案对比
- 计算年化收益率（XIRR）、最大回撤、夏普比率
- 计入申购费和赎回费（复用 fetch_fund 的费率表）

定投频率：月（每月1号）/ 双周（每14天）/ 周（每7天）
扣款日遇到非交易日（无净值）时跳到下一个有净值的交易日。
"""
from __future__ import annotations

import datetime as dt
import logging
from bisect import bisect_left

import pandas as pd

from . import db, fetch_fund, risk
from .models import BacktestResult

logger = logging.getLogger(__name__)

RISK_FREE_RATE = 0.03  # 无风险利率（国内1年期国债收益率近似）


# ---------------------------------------------------------------------------
# 日期工具
# ---------------------------------------------------------------------------
def _parse_date(date_str: str) -> dt.date:
    parts = date_str.split("-")
    return dt.date(int(parts[0]), int(parts[1]), int(parts[2]))


def _generate_investment_dates(
    start_date: str, end_date: str, cadence: str
) -> list[str]:
    """按频率生成计划扣款日列表（ISO 格式，含 start，不含超过 end 的日期）。"""
    start = _parse_date(start_date)
    end = _parse_date(end_date)
    dates: list[str] = []

    if cadence == "month":
        y, m = start.year, start.month
        while True:
            d = dt.date(y, m, 1)
            if d > end:
                break
            dates.append(d.isoformat())
            m += 1
            if m > 12:
                m = 1
                y += 1
    elif cadence == "biweek":
        d = start
        while d <= end:
            dates.append(d.isoformat())
            d += dt.timedelta(days=14)
    elif cadence == "week":
        d = start
        while d <= end:
            dates.append(d.isoformat())
            d += dt.timedelta(days=7)
    return dates


def _resolve_nav_date(
    nav_dates: list[str], planned_date: str
) -> int | None:
    """在有序净值日期列表中找到 >= planned_date 的第一个索引，无则返回 None。"""
    idx = bisect_left(nav_dates, planned_date)
    return idx if idx < len(nav_dates) else None


# ---------------------------------------------------------------------------
# 费用计算
# ---------------------------------------------------------------------------
def _calc_purchase_fee(code: str, amount: float) -> float:
    """申购手续费（复用 fetch_fund.calc_purchase_fee）。费率未知时返回 0。"""
    result = fetch_fund.calc_purchase_fee(code, amount)
    return result.fee


def _calc_redemption_fee_simulated(
    lots: list[tuple[str, float]],
    sell_date: str,
    sell_nav: float,
    fee_rates: fetch_fund.FeeRates,
) -> float:
    """模拟赎回手续费（FIFO 按持有天数匹配费率档）。

    lots: [(buy_date, shares), ...] 模拟买入批次
    """
    if not fee_rates.ok or not fee_rates.redemption:
        return 0.0

    sell_dt = _parse_date(sell_date)
    total_fee = 0.0

    for buy_date, shares in lots:
        days = (sell_dt - _parse_date(buy_date)).days
        if days < 0:
            days = 0
        rate = 0.0
        for tier in fee_rates.redemption:
            if days >= tier.min_days:
                if tier.max_days is None or days <= tier.max_days:
                    rate = tier.rate
                    break
        total_fee += shares * sell_nav * rate

    return round(total_fee, 2)


# ---------------------------------------------------------------------------
# XIRR（牛顿迭代 + 二分法兜底）
# ---------------------------------------------------------------------------
def _xirr(cashflows: list[tuple[dt.date, float]]) -> float | None:
    """计算 XIRR（年化内部收益率）。

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


# ---------------------------------------------------------------------------
# 单基金回测
# ---------------------------------------------------------------------------
def _build_curve(
    timeline: list[str],
    navs: pd.Series,
    share_delta: pd.Series,
    cost_delta: pd.Series,
) -> list[dict]:
    """从份额/成本增量序列构建每日曲线数据。"""
    held = share_delta.cumsum().clip(lower=0)
    invested = cost_delta.cumsum().clip(lower=0)
    value = held * navs

    curve: list[dict] = []
    for i in range(len(timeline)):
        inv = float(invested.iloc[i])
        val = float(value.iloc[i])
        if inv <= 0:
            continue
        ret = val / inv - 1.0 if inv > 0 else 0.0
        curve.append({
            "date": timeline[i],
            "invested": round(inv, 2),
            "value": round(val, 2),
            "return": round(ret, 4),
        })
    return curve


def _run_dca(
    code: str,
    fund_name: str,
    nav_dates: list[str],
    navs: pd.Series,
    start_date: str,
    end_date: str,
    amount: float,
    cadence: str,
    fee_rates: fetch_fund.FeeRates,
) -> BacktestResult:
    """定投模拟。"""
    planned_dates = _generate_investment_dates(start_date, end_date, cadence)
    timeline = nav_dates  # 净值日期即时间轴

    share_delta = pd.Series(0.0, index=timeline)
    cost_delta = pd.Series(0.0, index=timeline)
    periods_detail: list[dict] = []
    lots: list[tuple[str, float]] = []
    total_fees = 0.0
    total_invested = 0.0
    actual_periods = 0

    for planned in planned_dates:
        idx = _resolve_nav_date(nav_dates, planned)
        if idx is None:
            break
        actual_date = nav_dates[idx]
        nav = float(navs.iloc[idx])

        fee = _calc_purchase_fee(code, amount)
        invested = amount - fee
        shares = invested / nav if nav > 0 else 0.0

        share_delta.iloc[idx] += shares
        cost_delta.iloc[idx] += amount
        lots.append((actual_date, shares))
        total_fees += fee
        total_invested += amount
        actual_periods += 1

        periods_detail.append({
            "planned_date": planned,
            "actual_date": actual_date,
            "nav": round(nav, 4),
            "amount": round(amount, 2),
            "fee": round(fee, 2),
            "invested": round(invested, 2),
            "shares": round(shares, 4),
            "cumulative_shares": round(share_delta.cumsum().iloc[idx], 4),
            "cumulative_invested": round(total_invested, 2),
        })

    if actual_periods == 0:
        return BacktestResult(
            fund_code=code, fund_name=fund_name, strategy="dca",
            period_start=start_date, period_end=end_date,
            cadence=cadence, amount_per_period=amount,
        )

    final_nav = float(navs.iloc[-1])
    final_value = float(share_delta.cumsum().iloc[-1] * final_nav)
    redemption_fee = _calc_redemption_fee_simulated(
        lots, end_date, final_nav, fee_rates
    )
    net_final_value = round(final_value - redemption_fee, 2)
    total_fees = round(total_fees + redemption_fee, 2)
    total_return = (net_final_value - total_invested) / total_invested if total_invested else 0.0

    # XIRR
    cashflows = [
        (_parse_date(p["actual_date"]), -p["amount"])
        for p in periods_detail
    ]
    cashflows.append((_parse_date(end_date), net_final_value))
    annualized = _xirr(cashflows)

    # 曲线
    curve = _build_curve(timeline, navs, share_delta, cost_delta)

    # 最大回撤（基于组合市值曲线）
    value_series = pd.Series([c["value"] for c in curve])
    max_dd = risk.calculate_max_drawdown(value_series)

    # 夏普比率
    sharpe = _calc_sharpe(annualized, curve)

    return BacktestResult(
        fund_code=code, fund_name=fund_name, strategy="dca",
        period_start=start_date, period_end=end_date,
        cadence=cadence, amount_per_period=amount,
        total_periods=actual_periods,
        invested_capital=round(total_invested, 2),
        total_fees=total_fees,
        final_value=round(final_value, 2),
        redemption_fee=round(redemption_fee, 2),
        net_final_value=net_final_value,
        total_return=round(total_return, 4),
        annualized_return=round(annualized, 4) if annualized is not None else None,
        max_drawdown=round(max_dd, 4) if max_dd is not None else None,
        sharpe_ratio=round(sharpe, 4) if sharpe is not None else None,
        curve=curve,
        periods_detail=periods_detail,
    )


def _run_lumpsum(
    code: str,
    fund_name: str,
    nav_dates: list[str],
    navs: pd.Series,
    start_date: str,
    end_date: str,
    total_amount: float,
    fee_rates: fetch_fund.FeeRates,
) -> BacktestResult:
    """一次性投入模拟。"""
    if not nav_dates or total_amount <= 0:
        return BacktestResult(
            fund_code=code, fund_name=fund_name, strategy="lumpsum",
            period_start=start_date, period_end=end_date,
        )

    timeline = nav_dates
    buy_date = nav_dates[0]
    buy_nav = float(navs.iloc[0])

    fee = _calc_purchase_fee(code, total_amount)
    invested = total_amount - fee
    shares = invested / buy_nav if buy_nav > 0 else 0.0

    share_delta = pd.Series(0.0, index=timeline)
    cost_delta = pd.Series(0.0, index=timeline)
    share_delta.iloc[0] = shares
    cost_delta.iloc[0] = total_amount

    lots = [(buy_date, shares)]
    final_nav = float(navs.iloc[-1])
    final_value = shares * final_nav
    redemption_fee = _calc_redemption_fee_simulated(
        lots, end_date, final_nav, fee_rates
    )
    net_final_value = round(final_value - redemption_fee, 2)
    total_fees = round(fee + redemption_fee, 2)
    total_return = (net_final_value - total_amount) / total_amount if total_amount else 0.0

    # XIRR
    cashflows = [
        (_parse_date(buy_date), -total_amount),
        (_parse_date(end_date), net_final_value),
    ]
    annualized = _xirr(cashflows)

    curve = _build_curve(timeline, navs, share_delta, cost_delta)

    value_series = pd.Series([c["value"] for c in curve])
    max_dd = risk.calculate_max_drawdown(value_series)
    sharpe = _calc_sharpe(annualized, curve)

    return BacktestResult(
        fund_code=code, fund_name=fund_name, strategy="lumpsum",
        period_start=start_date, period_end=end_date,
        cadence="",
        amount_per_period=round(total_amount, 2),
        total_periods=1,
        invested_capital=round(total_amount, 2),
        total_fees=total_fees,
        final_value=round(final_value, 2),
        redemption_fee=round(redemption_fee, 2),
        net_final_value=net_final_value,
        total_return=round(total_return, 4),
        annualized_return=round(annualized, 4) if annualized is not None else None,
        max_drawdown=round(max_dd, 4) if max_dd is not None else None,
        sharpe_ratio=round(sharpe, 4) if sharpe is not None else None,
        curve=curve,
        periods_detail=[],
    )


def _calc_sharpe(
    annualized_return: float | None,
    curve: list[dict],
) -> float | None:
    """夏普比率 = (年化收益 - 无风险利率) / 年化波动率。"""
    if annualized_return is None or len(curve) < 3:
        return None
    values = pd.Series([c["value"] for c in curve])
    vol = risk.calculate_volatility(values, annualize=True)
    if vol is None or vol <= 0:
        return None
    return (annualized_return - RISK_FREE_RATE) / vol


# ---------------------------------------------------------------------------
# 数据准备
# ---------------------------------------------------------------------------
def _ensure_nav_data(fund_code: str, start_date: str, end_date: str) -> None:
    """确保基金在请求区间内有净值数据，不足则自动拉取。"""
    rows = db.get_nav_history_by_period(fund_code, start_date, end_date)
    if len(rows) >= 2:
        return
    # 区间内数据不足，拉取全量净值
    existing = db.get_nav_history(fund_code)
    if not existing:
        try:
            fetch_fund.update_fund_nav(fund_code)
        except Exception:
            logger.warning("backtest: 拉取净值失败 %s", fund_code, exc_info=True)
    else:
        # 有数据但可能未覆盖请求区间两端，尝试补拉
        first_date = existing[0]["date"]
        last_date = existing[-1]["date"]
        if start_date < first_date or end_date > last_date:
            try:
                fetch_fund.update_fund_nav(fund_code)
            except Exception:
                logger.warning("backtest: 补拉净值失败 %s", fund_code, exc_info=True)


# ---------------------------------------------------------------------------
# 对外接口
# ---------------------------------------------------------------------------
def run_dca_backtest(
    fund_codes: list[str],
    start_date: str,
    end_date: str,
    amount_per_period: float,
    cadence: str = "month",
    include_lumpsum: bool = True,
) -> list[BacktestResult]:
    """定投回测主入口。

    对每只基金分别跑定投策略，可选附加上一次性投入对照。
    返回结果列表（dca 在前，lumpsum 在后）。
    """
    results: list[BacktestResult] = []

    for code in fund_codes:
        code = code.strip()
        if not code:
            continue

        # 确保净值数据
        _ensure_nav_data(code, start_date, end_date)

        rows = db.get_nav_history_by_period(code, start_date, end_date)
        if len(rows) < 2:
            results.append(BacktestResult(
                fund_code=code, fund_name=code, strategy="dca",
                period_start=start_date, period_end=end_date,
                cadence=cadence, amount_per_period=amount_per_period,
            ))
            if include_lumpsum:
                results.append(BacktestResult(
                    fund_code=code, fund_name=code, strategy="lumpsum",
                    period_start=start_date, period_end=end_date,
                ))
            continue

        nav_dates = [r["date"] for r in rows]
        navs = pd.Series(
            {r["date"]: float(r["nav"]) for r in rows}, index=nav_dates
        )

        fund = db.get_fund(code)
        fund_name = fund.fund_name if fund else code

        fee_rates = fetch_fund.fetch_fund_fee_rates(code)

        dca_result = _run_dca(
            code, fund_name, nav_dates, navs,
            start_date, end_date, amount_per_period, cadence, fee_rates,
        )
        results.append(dca_result)

        if include_lumpsum:
            total = amount_per_period * dca_result.total_periods
            lump_result = _run_lumpsum(
                code, fund_name, nav_dates, navs,
                start_date, end_date, total, fee_rates,
            )
            results.append(lump_result)

    return results
