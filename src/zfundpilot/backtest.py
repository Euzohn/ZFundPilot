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
import math
import re
from bisect import bisect_left
from collections.abc import Callable

import pandas as pd

from . import db, fetch_fund, risk
from .models import BacktestResult
from .returns import xirr

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
            # 首期不得早于请求起日，避免把起日前的投入算进区间
            if d < start:
                d = start
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
def _purchase_fee_from_rates(
    fee_rates: fetch_fund.FeeRates, amount: float
) -> float:
    """用本次模拟的费率快照计算申购费，避免每期重复联网。

    与 ``fetch_fund.calc_purchase_fee`` 的分档规则一致；费率未知或缺失时返回 0，
    由调用方通过 ``fee_ok`` 与 caveats 说明。
    """
    if not fee_rates.ok or not fee_rates.purchase:
        return 0.0

    for tier in fee_rates.purchase:
        if amount < tier.min_amount:
            continue
        if tier.max_amount is not None and amount >= tier.max_amount:
            continue
        if tier.is_fixed:
            return float(tier.fixed_fee)
        return round(amount * tier.rate, 2)

    last = fee_rates.purchase[-1]
    if last.is_fixed:
        return float(last.fixed_fee)
    return round(amount * last.rate, 2)


def _fee_caveats(fee_rates: fetch_fund.FeeRates) -> list[str]:
    """说明费率缺失时的假设，避免把未知费用误报为零成本。"""
    caveats: list[str] = []
    if not fee_rates.ok:
        caveats.append("费率表获取失败，申购费与赎回费按 0 计，实际费用可能更高。")
        return caveats
    if not fee_rates.purchase:
        caveats.append("未取得申购费率，申购费按 0 计。")
    if not fee_rates.redemption:
        caveats.append("未取得赎回费率，赎回费按 0 计。")
    return caveats


def _simulation_caveats(fee_rates: fetch_fund.FeeRates) -> list[str]:
    """所有回测结果共享的口径说明，外加本次费率状态。"""
    return [
        "定投与一次性投入均为历史模拟，不代表未来收益，也不构成配置建议。",
        "未模拟分红、拆分与红利再投资，仅使用单位净值。",
        "最大回撤与夏普比率基于投入后的市值曲线，定投现金流会影响可比性。",
        *_fee_caveats(fee_rates),
    ]


def _failed_result(
    code: str,
    fund_name: str,
    strategy: str,
    start_date: str,
    end_date: str,
    amount: float,
    cadence: str,
    status_code: str,
    message: str,
    data_source: str,
    caveats: list[str],
    *,
    data_start: str = "",
    data_end: str = "",
    fee_ok: bool = False,
) -> BacktestResult:
    """数据不足或无法计算时的显式失败结果，不输出看似有效的零收益指标。"""
    return BacktestResult(
        fund_code=code, fund_name=fund_name, strategy=strategy,
        period_start=start_date, period_end=end_date,
        cadence=cadence, amount_per_period=round(amount, 2),
        status="failed", code=status_code, message=message,
        data_source=data_source, data_start=data_start, data_end=data_end,
        valuation_date=data_end, fee_ok=fee_ok, caveats=caveats,
    )


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
    data_source: str = "",
) -> BacktestResult:
    """定投模拟。

    - 计划扣款日不早于请求起日；
    - 多个计划期落到同一净值日时只执行第一期并计入 ``skipped_periods``；
    - 期末估值、赎回费持有天数与 XIRR 终值统一使用最后一个净值日。
    """
    planned_dates = _generate_investment_dates(start_date, end_date, cadence)
    timeline = nav_dates  # 净值日期即时间轴
    caveats = _simulation_caveats(fee_rates)

    if not planned_dates:
        return _failed_result(
            code, fund_name, "dca", start_date, end_date, amount, cadence,
            "no_periods", "请求区间内没有可执行的计划扣款日",
            data_source, caveats,
            data_start=nav_dates[0] if nav_dates else "",
            data_end=nav_dates[-1] if nav_dates else "",
            fee_ok=bool(fee_rates.ok))

    purchase_fee = _purchase_fee_from_rates(fee_rates, amount)
    valuation_date = nav_dates[-1]

    share_delta = pd.Series(0.0, index=timeline)
    cost_delta = pd.Series(0.0, index=timeline)
    periods_detail: list[dict] = []
    lots: list[tuple[str, float]] = []
    total_fees = 0.0
    total_invested = 0.0
    actual_periods = 0
    skipped_periods = 0
    used_nav_dates: set[str] = set()
    cumulative_shares = 0.0

    for planned in planned_dates:
        idx = _resolve_nav_date(nav_dates, planned)
        if idx is None:
            skipped_periods += 1
            continue
        actual_date = nav_dates[idx]
        if actual_date in used_nav_dates:
            # 不把多期投入堆到同一净值日，避免虚增当日份额与费用
            skipped_periods += 1
            continue
        used_nav_dates.add(actual_date)

        nav = float(navs.iloc[idx])
        fee = purchase_fee
        invested = amount - fee
        shares = invested / nav if nav > 0 else 0.0

        share_delta.iloc[idx] += shares
        cost_delta.iloc[idx] += amount
        cumulative_shares += shares
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
            "cumulative_shares": round(cumulative_shares, 4),
            "cumulative_invested": round(total_invested, 2),
        })

    if actual_periods == 0:
        return _failed_result(
            code, fund_name, "dca", start_date, end_date, amount, cadence,
            "no_periods",
            "请求区间内没有可执行的计划扣款日（净值数据未覆盖扣款日）",
            data_source, caveats,
            data_start=nav_dates[0], data_end=nav_dates[-1],
            fee_ok=bool(fee_rates.ok))

    final_nav = float(navs.iloc[-1])
    final_value = float(share_delta.cumsum().iloc[-1] * final_nav)
    redemption_fee = _calc_redemption_fee_simulated(
        lots, valuation_date, final_nav, fee_rates
    )
    net_final_value = round(final_value - redemption_fee, 2)
    total_fees = round(total_fees + redemption_fee, 2)
    total_return = (net_final_value - total_invested) / total_invested if total_invested else 0.0

    # XIRR 终值日与估值日保持一致（最后一个可用净值日）
    cashflows = [
        (_parse_date(p["actual_date"]), -p["amount"])
        for p in periods_detail
    ]
    cashflows.append((_parse_date(valuation_date), net_final_value))
    annualized = xirr(cashflows)

    # 曲线
    curve = _build_curve(timeline, navs, share_delta, cost_delta)

    # 最大回撤（基于组合市值曲线）
    value_series = pd.Series([c["value"] for c in curve])
    max_dd = risk.calculate_max_drawdown(value_series)

    # 夏普比率
    sharpe = _calc_sharpe(annualized, curve)

    status = "partial" if skipped_periods else "ok"
    message = ""
    if status == "partial":
        message = (
            f"{skipped_periods} 个计划期未执行：净值未覆盖或与其他期落在同一净值日"
        )
        caveats = [
            *caveats,
            "部分计划期未执行，投入总额低于按完整计划计算的金额。",
        ]

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
        status=status,
        code="partial_coverage" if status == "partial" else "",
        message=message,
        data_source=data_source,
        data_start=nav_dates[0],
        data_end=nav_dates[-1],
        valuation_date=valuation_date,
        skipped_periods=skipped_periods,
        fee_ok=bool(fee_rates.ok),
        caveats=caveats,
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
    data_source: str = "",
) -> BacktestResult:
    """一次性投入模拟。"""
    caveats = _simulation_caveats(fee_rates)
    if not nav_dates or total_amount <= 0:
        return _failed_result(
            code, fund_name, "lumpsum", start_date, end_date, total_amount, "",
            "insufficient_nav", "净值数据不足，无法模拟一次性投入",
            data_source, caveats,
            data_start=nav_dates[0] if nav_dates else "",
            data_end=nav_dates[-1] if nav_dates else "",
            fee_ok=bool(fee_rates.ok))

    timeline = nav_dates
    valuation_date = nav_dates[-1]
    buy_date = nav_dates[0]
    buy_nav = float(navs.iloc[0])

    fee = _purchase_fee_from_rates(fee_rates, total_amount)
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
        lots, valuation_date, final_nav, fee_rates
    )
    net_final_value = round(final_value - redemption_fee, 2)
    total_fees = round(fee + redemption_fee, 2)
    total_return = (net_final_value - total_amount) / total_amount if total_amount else 0.0

    # XIRR 终值日与估值日保持一致
    cashflows = [
        (_parse_date(buy_date), -total_amount),
        (_parse_date(valuation_date), net_final_value),
    ]
    annualized = xirr(cashflows)

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
        status="ok",
        data_source=data_source,
        data_start=nav_dates[0],
        data_end=nav_dates[-1],
        valuation_date=valuation_date,
        fee_ok=bool(fee_rates.ok),
        caveats=caveats,
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


_DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")


def _normalise_nav_row(row: object) -> dict | None:
    """把数据库行或 NavPoint 统一为 {date, nav}，拒绝非法日期与非正/非有限净值。

    ``sqlite3.Row`` 只支持下标访问，``NavPoint`` 只支持属性访问，两者都要兼容。
    """
    try:
        date_value = row["date"]  # type: ignore[index]
        nav = row["nav"]  # type: ignore[index]
    except (KeyError, IndexError, TypeError):
        date_value = getattr(row, "date", None)
        nav = getattr(row, "nav", None)

    date = str(date_value or "").strip()
    if not _DATE_RE.fullmatch(date) or nav is None:
        return None
    try:
        dt.date.fromisoformat(date)
        value = float(nav)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(value) or value <= 0:
        return None
    return {"date": date, "nav": value}


def clean_nav_rows(
    rows: list | None,
    start_date: str | None = None,
    end_date: str | None = None,
) -> list[dict]:
    """清洗净值：去重（同日后值覆盖）、按日期升序、按请求区间裁剪。"""
    by_date: dict[str, dict] = {}
    for row in rows or []:
        item = _normalise_nav_row(row)
        if item is None:
            continue
        if start_date and item["date"] < start_date:
            continue
        if end_date and item["date"] > end_date:
            continue
        by_date[item["date"]] = item
    return [by_date[d] for d in sorted(by_date)]


def _coverage_better(new: list[dict], old: list[dict]) -> bool:
    """判断新数据集是否比旧数据集覆盖更完整。"""
    if not old:
        return bool(new)
    if not new:
        return False
    if new[-1]["date"] != old[-1]["date"]:
        return new[-1]["date"] > old[-1]["date"]
    if new[0]["date"] != old[0]["date"]:
        return new[0]["date"] < old[0]["date"]
    return len(new) > len(old)


def readonly_nav_rows(
    fund_code: str,
    start_date: str,
    end_date: str,
    *,
    allow_fetch: bool = True,
    stale_after_days: int = 7,
) -> tuple[list[dict], str]:
    """只读获取净值数据：优先数据库，覆盖不足时内存抓取，绝不写库。

    返回 ``(清洗后的行, 数据来源)``。来源为 ``database`` / ``remote`` /
    ``database+remote`` / ``none``。外部抓取只在数据不足或明显过期时触发；
    不调用 ``update_fund_nav()``，因此不会创建基金或改写正式净值表。
    """
    db_rows = db.get_nav_history_by_period(fund_code, start_date, end_date)
    rows = clean_nav_rows(db_rows, start_date, end_date)
    source = "database" if rows else "none"

    if not allow_fetch:
        return rows, source

    # 起止日可能是周末/节假日，允许首末净值与请求边界相差几天；
    # 只有缺口明显（例如数据库只覆盖区间中段）才触发外部抓取。
    need_fetch = len(rows) < 2
    if not need_fetch:
        first = dt.date.fromisoformat(rows[0]["date"])
        requested_start = dt.date.fromisoformat(start_date)
        need_fetch = (first - requested_start).days > stale_after_days
    if not need_fetch:
        last = dt.date.fromisoformat(rows[-1]["date"])
        requested_end = dt.date.fromisoformat(end_date)
        need_fetch = (requested_end - last).days > stale_after_days

    if not need_fetch:
        return rows, source

    try:
        points = fetch_fund.fetch_nav_history(fund_code)
    except Exception:  # noqa: BLE001
        logger.warning("backtest: 只读拉取净值失败 %s", fund_code, exc_info=True)
        return rows, source

    fetched = clean_nav_rows(points, start_date, end_date)
    if _coverage_better(fetched, rows):
        # 只有数据库确有可用行时才标记为混合来源；无效行不算贡献
        return fetched, ("database+remote" if rows else "remote")
    return rows, source


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
    nav_provider: Callable[[str, str, str], tuple[list[dict], str]] | None = None,
) -> list[BacktestResult]:
    """定投回测主入口。

    对每只基金分别跑定投策略，可选附加上一次性投入对照。
    返回结果列表（dca 在前，lumpsum 在后）。

    ``nav_provider`` 为可选的数据提供器，返回 ``(净值行, 数据来源)``。
    Agent 只读入口传入 :func:`readonly_nav_rows`，从而避免调用写库的
    ``_ensure_nav_data()``；网页入口保持原有自动补数行为。
    """
    results: list[BacktestResult] = []

    for code in fund_codes:
        code = code.strip()
        if not code:
            continue

        if nav_provider is None:
            # 网页入口：保留原有的自动补数行为（会写正式净值库）
            _ensure_nav_data(code, start_date, end_date)
            rows = db.get_nav_history_by_period(code, start_date, end_date)
            data_source = "database" if rows else "none"
        else:
            rows, data_source = nav_provider(code, start_date, end_date)

        rows = clean_nav_rows(rows, start_date, end_date)
        if not rows:
            data_source = "none"

        fund = db.get_fund(code)
        fund_name = fund.fund_name if fund else code

        if len(rows) < 2:
            data_start = rows[0]["date"] if rows else ""
            data_end = rows[-1]["date"] if rows else ""
            caveats = [
                "净值数据不足，未生成收益指标，也未计算费用。",
                "定投与一次性投入均为历史模拟，不代表未来收益，也不构成配置建议。",
            ]
            results.append(_failed_result(
                code, fund_name, "dca", start_date, end_date,
                amount_per_period, cadence, "insufficient_nav",
                "请求区间内有效净值少于 2 个", data_source, caveats,
                data_start=data_start, data_end=data_end))
            if include_lumpsum:
                results.append(_failed_result(
                    code, fund_name, "lumpsum", start_date, end_date,
                    amount_per_period, "", "insufficient_nav",
                    "请求区间内有效净值少于 2 个", data_source, caveats,
                    data_start=data_start, data_end=data_end))
            continue

        nav_dates = [r["date"] for r in rows]
        navs = pd.Series(
            {r["date"]: float(r["nav"]) for r in rows}, index=nav_dates
        )

        fee_rates = fetch_fund.fetch_fund_fee_rates(code)

        dca_result = _run_dca(
            code, fund_name, nav_dates, navs,
            start_date, end_date, amount_per_period, cadence, fee_rates,
            data_source,
        )
        results.append(dca_result)

        if include_lumpsum and dca_result.invested_capital > 0:
            lump_result = _run_lumpsum(
                code, fund_name, nav_dates, navs,
                start_date, end_date, dca_result.invested_capital, fee_rates,
                data_source,
            )
            results.append(lump_result)

    return results
