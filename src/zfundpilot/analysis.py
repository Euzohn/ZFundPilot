"""收益计算模块（交易流水驱动）。

持仓由 transactions 流水按 (基金代码 + 渠道) 汇总计算，
采用「移动加权平均成本法」：

  买入：held_shares += 份额；total_cost += 金额(+手续费)
        avg_cost_nav = total_cost / held_shares
  卖出：按当前均价结转成本
        结转成本 = 卖出份额 * avg_cost_nav
        已实现盈亏 += 卖出金额 - 结转成本 - 手续费
        held_shares -= 卖出份额；total_cost -= 结转成本

  浮动盈亏 = 当前市值 - 当前持仓成本
  浮动收益率 = 当前市值 / 当前持仓成本 - 1

同一只基金在不同渠道（支付宝/理财通等）视为独立持仓，成本分别计算。
"""

from __future__ import annotations

import time
from collections import OrderedDict
from typing import Any

import pandas as pd

_cache: dict[str, tuple[float, Any]] = {}
_CACHE_TTL = 60  # 秒


def clear_analysis_cache() -> None:
    _cache.clear()


def _cache_get(key: str) -> Any | None:
    if key in _cache:
        ts, val = _cache[key]
        if time.time() - ts < _CACHE_TTL:
            return val
        del _cache[key]
    return None


def _cache_set(key: str, val: Any) -> None:
    _cache[key] = (time.time(), val)

from . import db
from .models import (
    ACTION_BUY,
    ACTION_DIVIDEND,
    ACTION_REINVEST,
    ACTION_SELL,
    Fund,
    PortfolioSummary,
    Position,
    Transaction,
)


# ---------------------------------------------------------------------------
# 流水 -> 持仓
# ---------------------------------------------------------------------------
def _position_key(fund_code: str, channel: str) -> tuple[str, str]:
    return (fund_code, channel or "")


def _build_positions_from_transactions(
    transactions: list[Transaction],
    funds: dict[str, Fund],
) -> OrderedDict[tuple[str, str], Position]:
    """按 (基金, 渠道) 用均价法汇总流水，返回持仓字典（含已清仓的）。"""
    positions: OrderedDict[tuple[str, str], Position] = OrderedDict()

    # 流水需按日期升序处理，保证卖出时均价正确
    for tx in sorted(transactions, key=lambda t: (t.date or "", t.id or 0)):
        tx.normalize()
        # 分红只需金额；卖出/再投资需要金额和份额；买入只需金额（待确认的暂不记份额）
        if tx.action == ACTION_DIVIDEND:
            if not tx.amount:
                continue
        elif tx.action == ACTION_SELL:
            if not tx.amount or not tx.shares:
                continue
        elif tx.action == ACTION_REINVEST:
            if not tx.amount or not tx.shares:
                continue
        # ACTION_BUY：有金额即可（份额可能待确认）
        key = _position_key(tx.fund_code, tx.channel)
        if key not in positions:
            fund = funds.get(tx.fund_code)
            positions[key] = Position(
                fund_code=tx.fund_code,
                fund_name=fund.fund_name if fund else tx.fund_code,
                fund_type=fund.fund_type if fund else "其它",
                sector=fund.sector if fund else "",
                channel=tx.channel or "",
            )
        pos = positions[key]

        if tx.action == ACTION_BUY:
            if tx.shares:
                pos.held_shares += tx.shares
            pos.total_cost += tx.amount
            pos.buy_count += 1
        elif tx.action == ACTION_SELL:
            # 结转成本按当前均价
            avg = (pos.total_cost / pos.held_shares) if pos.held_shares > 1e-9 else 0.0
            sell_shares = min(tx.shares, pos.held_shares)  # 防止卖超
            cost_out = sell_shares * avg
            pos.realized_pnl += tx.amount - cost_out
            pos.held_shares -= sell_shares
            pos.total_cost -= cost_out
            pos.sell_count += 1
            if pos.held_shares < 1e-6:
                pos.held_shares = 0.0
                pos.total_cost = 0.0
        elif tx.action == ACTION_DIVIDEND:
            # 现金分红：计入已实现收益，份额和成本不变
            pos.realized_pnl += tx.amount
            pos.dividend_count += 1
            pos.dividend_total += tx.amount
        elif tx.action == ACTION_REINVEST:
            # 红利再投资：份额增加，成本增加（=分红金额），同时计入已实现收益
            # 金额和成本同时增加，相互抵消，总盈亏不变
            pos.held_shares += tx.shares
            pos.total_cost += tx.amount
            pos.realized_pnl += tx.amount
            pos.dividend_count += 1
            pos.dividend_total += tx.amount

    # 计算均价
    for pos in positions.values():
        pos.avg_cost_nav = (pos.total_cost / pos.held_shares
                            if pos.held_shares > 1e-9 else None)
    return positions


def _apply_market_value(pos: Position) -> None:
    """填充最新净值、市值、浮动盈亏、收益率。"""
    latest = db.get_latest_nav(pos.fund_code)
    if latest:
        pos.latest_nav = float(latest["nav"])
        pos.latest_date = latest["date"]

    if pos.held_shares > 0 and pos.latest_nav is not None:
        pos.market_value = pos.held_shares * pos.latest_nav
    else:
        # 无净值时用成本兜底
        pos.market_value = pos.total_cost

    pos.unrealized_pnl = pos.market_value - pos.total_cost
    pos.return_rate = (pos.market_value / pos.total_cost - 1
                       if pos.total_cost > 1e-9 else None)


# ---------------------------------------------------------------------------
# 对外接口
# ---------------------------------------------------------------------------
def calculate_positions(include_closed: bool = False) -> list[Position]:
    """返回当前持仓列表（按市值降序），默认只含未清仓的。

    include_closed=True 时也返回已清仓持仓（用于查看历史已实现收益）。
    """
    ck = f"positions:{include_closed}"
    cached = _cache_get(ck)
    if cached is not None:
        return cached
    transactions = db.get_transactions()
    funds = {f.fund_code: f for f in db.get_funds()}
    pos_map = _build_positions_from_transactions(transactions, funds)

    positions = list(pos_map.values())
    for pos in positions:
        _apply_market_value(pos)

    if not include_closed:
        positions = [p for p in positions if p.is_open]

    # 市值占比（仅对持仓中的）
    total_value = sum(p.market_value for p in positions if p.is_open)
    if total_value > 0:
        for p in positions:
            p.weight = p.market_value / total_value if p.is_open else 0.0

    positions.sort(key=lambda p: p.market_value, reverse=True)
    _cache_set(ck, positions)
    return positions


def calculate_summary(positions: list[Position] | None = None) -> PortfolioSummary:
    """组合汇总。含浮动 + 已实现盈亏、累计买卖金额。"""
    positions_provided = positions is not None
    if positions is None:
        cached = _cache_get("summary")
        if cached is not None:
            return cached
        positions = calculate_positions(include_closed=True)

    open_positions = [p for p in positions if p.is_open]

    total_cost = sum(p.total_cost for p in open_positions)
    total_value = sum(p.market_value for p in open_positions)
    unrealized = sum(p.unrealized_pnl for p in open_positions)
    realized = sum(p.realized_pnl for p in positions)  # 含已清仓的历史收益

    # 累计买入/卖出/分红金额，直接从流水统计更准
    total_buy = total_sell = total_dividend = 0.0
    for tx in db.get_transactions():
        tx.normalize()
        if not tx.amount:
            continue
        if tx.action == ACTION_BUY:
            total_buy += tx.amount
        elif tx.action == ACTION_SELL:
            total_sell += tx.amount
        elif tx.action in (ACTION_DIVIDEND, ACTION_REINVEST):
            total_dividend += tx.amount

    summary = PortfolioSummary(
        total_cost=total_cost,
        total_value=total_value,
        unrealized_pnl=unrealized,
        realized_pnl=realized,
        total_pnl=unrealized + realized,
        total_return=(total_value / total_cost - 1) if total_cost > 1e-9 else 0.0,
        total_buy=total_buy,
        total_sell=total_sell,
        total_dividend=total_dividend,
        holding_count=len(open_positions),
    )

    if open_positions:
        top = max(open_positions, key=lambda p: p.weight)
        summary.max_single_weight = top.weight
        summary.max_single_name = top.fund_name
        summary.as_of_date = max(
            (p.latest_date for p in open_positions if p.latest_date), default=None)

    # 今日收益 = 每只基金 (latest_nav - prev_nav) × held_shares 直接算
    daily_pnl = 0.0
    prev_value = 0.0
    for p in open_positions:
        if not p.held_shares or not p.latest_nav:
            continue
        prev = db.get_prev_nav(p.fund_code)
        if prev:
            prev_nav = float(prev["nav"])
            daily_pnl += p.held_shares * (p.latest_nav - prev_nav)
            prev_value += p.held_shares * prev_nav
    summary.daily_pnl = round(daily_pnl, 2)
    summary.daily_return = (daily_pnl / prev_value) if prev_value > 0 else 0.0

    # 周/月/年收益 = (Δ市值 - Δ投入成本)，扣除期间资金流入流出
    try:
        import datetime as dt
        curve = build_portfolio_curve()
        if len(curve) >= 2 and summary.total_value > 0:
            dates = curve["date"].tolist()
            values = curve["total_value"].tolist()
            costs = curve["invested_cost"].tolist()

            def _find_start_idx(target_date: str) -> int | None:
                """找曲线中 <= target_date 的最近一个点的索引。"""
                for i in range(len(dates) - 1, -1, -1):
                    if dates[i] <= target_date:
                        return i
                return None

            end_val = values[-1]
            end_cost = costs[-1]
            today = dt.date.today()
            week_start = (today - dt.timedelta(days=today.weekday() + 7)).isoformat()
            month_start = today.replace(day=1).isoformat()
            year_start = today.replace(month=1, day=1).isoformat()

            for start_date, pnl_attr, ret_attr in [
                (week_start, "week_pnl", "week_return"),
                (month_start, "month_pnl", "month_return"),
                (year_start, "year_pnl", "year_return"),
            ]:
                idx = _find_start_idx(start_date)
                if idx is not None:
                    start_val = values[idx]
                    start_cost = costs[idx]
                    if start_val > 0:
                        pnl = (end_val - start_val) - (end_cost - start_cost)
                        setattr(summary, pnl_attr, round(pnl, 2))
                        setattr(summary, ret_attr, pnl / start_val)
    except Exception:  # noqa: BLE001
        pass

    if not positions_provided:
        _cache_set("summary", summary)
    return summary


# ---------------------------------------------------------------------------
# 分布统计（按基金聚合，跨渠道合并）
# ---------------------------------------------------------------------------
def distribution_by(positions: list[Position], field: str) -> pd.DataFrame:
    """按指定字段（fund_type / sector / channel）聚合市值与占比。"""
    open_positions = [p for p in positions if p.is_open]
    if not open_positions:
        return pd.DataFrame(columns=[field, "market_value", "weight"])

    rows = [{field: getattr(p, field) or "其它", "market_value": p.market_value}
            for p in open_positions]
    df = pd.DataFrame(rows)
    grouped = (df.groupby(field, as_index=False)["market_value"].sum()
               .sort_values("market_value", ascending=False))
    total = grouped["market_value"].sum()
    grouped["weight"] = grouped["market_value"] / total if total > 0 else 0.0
    return grouped.reset_index(drop=True)


def positions_to_dataframe(positions: list[Position]) -> pd.DataFrame:
    if not positions:
        return pd.DataFrame()
    return pd.DataFrame([p.to_dict() for p in positions])


# ---------------------------------------------------------------------------
# 组合历史收益曲线
# ---------------------------------------------------------------------------
def build_portfolio_curve() -> pd.DataFrame:
    """基于流水与净值历史，还原组合每日市值曲线。

    做法：对每只(基金,渠道)持仓，按流水累积每日持有份额，
    再乘以当日净值得市值，最后跨持仓求和。
    返回列：date, total_value, invested_cost, total_return
    起点取最早一笔交易日期。
    """
    cached = _cache_get("portfolio_curve")
    if cached is not None:
        return cached
    transactions = db.get_transactions()
    if not transactions:
        return pd.DataFrame(columns=["date", "total_value", "invested_cost", "total_return"])

    for t in transactions:
        t.normalize()
    tx_sorted = sorted(transactions, key=lambda t: (t.date or "", t.id or 0))
    start_date = tx_sorted[0].date

    codes = sorted({t.fund_code for t in transactions})

    # 收集所有净值日期作为时间轴
    nav_map: dict[str, pd.Series] = {}
    all_dates: set[str] = set()
    for code in codes:
        rows = db.get_nav_history(code)
        if not rows:
            continue
        s = pd.Series({r["date"]: float(r["nav"]) for r in rows})
        nav_map[code] = s
        all_dates.update(s.index)

    if not all_dates:
        return pd.DataFrame(columns=["date", "total_value", "invested_cost", "total_return"])

    timeline = sorted(d for d in all_dates if d >= start_date)
    if not timeline:
        return pd.DataFrame(columns=["date", "total_value", "invested_cost", "total_return"])

    # 每只基金：按日期累积净买入份额；同时累积净投入成本
    total_value = pd.Series(0.0, index=timeline)
    invested = pd.Series(0.0, index=timeline)

    # 预处理每个基金的份额/成本变动事件
    for code in codes:
        if code not in nav_map:
            continue
        navs = nav_map[code].reindex(timeline).ffill()

        # 构造每日累计份额
        share_delta = pd.Series(0.0, index=timeline)
        cost_delta = pd.Series(0.0, index=timeline)
        pending_value_delta = pd.Series(0.0, index=timeline)
        for t in tx_sorted:
            if t.fund_code != code:
                continue
            if not t.shares:
                # 待确认买入：占位金额，避免 P&L 出现虚假亏损
                if t.action == ACTION_BUY and t.amount:
                    d = t.date if t.date >= start_date else start_date
                    idx = _first_ge(timeline, d)
                    if idx is not None:
                        cost_delta.iloc[idx] += t.amount
                        pending_value_delta.iloc[idx] += t.amount
                continue
            if t.action == ACTION_DIVIDEND:
                continue  # 现金分红不改变份额
            d = t.date if t.date >= start_date else start_date
            # 找到时间轴上 >= d 的第一个点
            idx = _first_ge(timeline, d)
            if idx is None:
                continue
            # 待确认卖出：份额已知、金额未知，用净值估算占位
            if t.action == ACTION_SELL and not t.amount:
                nav_at_idx = navs.iloc[idx] if idx < len(navs) else 0.0
                if nav_at_idx and pd.notna(nav_at_idx):
                    pending_value_delta.iloc[idx] += t.shares * nav_at_idx
            # 买入/再投资 = +份额, 卖出 = -份额
            sign = -1.0 if t.action == ACTION_SELL else 1.0
            share_delta.iloc[idx] += sign * t.shares
            cost_delta.iloc[idx] += sign * (t.amount or 0.0)

        held = share_delta.cumsum().clip(lower=0)
        invested_code = cost_delta.cumsum().clip(lower=0)
        pending_cum = pending_value_delta.cumsum()
        total_value = total_value.add(held * navs + pending_cum, fill_value=0.0)
        invested = invested.add(invested_code, fill_value=0.0)

    curve = pd.DataFrame({
        "date": timeline,
        "total_value": total_value.values,
        "invested_cost": invested.values,
    })
    curve = curve[curve["invested_cost"] > 0].reset_index(drop=True)
    if curve.empty:
        return curve
    curve["total_return"] = curve["total_value"] / curve["invested_cost"] - 1
    _cache_set("portfolio_curve", curve)
    return curve


def build_channel_daily_pnl() -> list[dict[str, Any]]:
    """按渠道拆分的每日收益，用于堆叠柱状图。

    对每个 (基金, 渠道) 持仓独立累积份额和成本，
    每日 P&L = Δ市值 - Δ成本，按渠道分别计算。
    返回 [{date, "支付宝": 120.5, "理财通": -30.2, ...}, ...]
    """
    cached = _cache_get("channel_daily_pnl")
    if cached is not None:
        return cached
    transactions = db.get_transactions()
    if not transactions:
        return []

    for t in transactions:
        t.normalize()
    tx_sorted = sorted(transactions, key=lambda t: (t.date or "", t.id or 0))
    start_date = tx_sorted[0].date

    keys = sorted({(t.fund_code, t.channel or "") for t in transactions})
    codes = sorted({k[0] for k in keys})

    nav_map: dict[str, pd.Series] = {}
    all_dates: set[str] = set()
    for code in codes:
        rows = db.get_nav_history(code)
        if not rows:
            continue
        s = pd.Series({r["date"]: float(r["nav"]) for r in rows})
        nav_map[code] = s
        all_dates.update(s.index)

    if not all_dates:
        return []

    timeline = sorted(d for d in all_dates if d >= start_date)
    if not timeline:
        return []

    channel_values: dict[str, pd.Series] = {}
    channel_costs: dict[str, pd.Series] = {}

    for code, channel in keys:
        if code not in nav_map:
            continue
        navs = nav_map[code].reindex(timeline).ffill()

        share_delta = pd.Series(0.0, index=timeline)
        cost_delta = pd.Series(0.0, index=timeline)
        pending_value_delta = pd.Series(0.0, index=timeline)
        for t in tx_sorted:
            if t.fund_code != code or (t.channel or "") != channel:
                continue
            if not t.shares:
                if t.action == ACTION_BUY and t.amount:
                    d = t.date if t.date >= start_date else start_date
                    idx = _first_ge(timeline, d)
                    if idx is not None:
                        cost_delta.iloc[idx] += t.amount
                        pending_value_delta.iloc[idx] += t.amount
                continue
            if t.action == ACTION_DIVIDEND:
                continue
            d = t.date if t.date >= start_date else start_date
            idx = _first_ge(timeline, d)
            if idx is None:
                continue
            if t.action == ACTION_SELL and not t.amount:
                nav_at_idx = navs.iloc[idx] if idx < len(navs) else 0.0
                if nav_at_idx and pd.notna(nav_at_idx):
                    pending_value_delta.iloc[idx] += t.shares * nav_at_idx
            sign = -1.0 if t.action == ACTION_SELL else 1.0
            share_delta.iloc[idx] += sign * t.shares
            cost_delta.iloc[idx] += sign * (t.amount or 0.0)

        held = share_delta.cumsum().clip(lower=0)
        invested = cost_delta.cumsum().clip(lower=0)
        pending_cum = pending_value_delta.cumsum()
        value_series = held * navs + pending_cum

        ch = channel or "其它"
        if ch not in channel_values:
            channel_values[ch] = pd.Series(0.0, index=timeline)
            channel_costs[ch] = pd.Series(0.0, index=timeline)
        channel_values[ch] = channel_values[ch].add(value_series, fill_value=0.0)
        channel_costs[ch] = channel_costs[ch].add(invested, fill_value=0.0)

    channels = sorted(channel_values.keys())

    result: list[dict[str, Any]] = []
    for i in range(1, len(timeline)):
        row: dict[str, Any] = {"date": timeline[i]}
        for ch in channels:
            dv = channel_values[ch].iloc[i] - channel_values[ch].iloc[i - 1]
            dc = channel_costs[ch].iloc[i] - channel_costs[ch].iloc[i - 1]
            row[ch] = round(float(dv - dc), 2)
        result.append(row)

    _cache_set("channel_daily_pnl", result)
    return result


def _first_ge(sorted_list: list[str], value: str) -> int | None:
    """返回有序列表中第一个 >= value 的索引。"""
    import bisect
    i = bisect.bisect_left(sorted_list, value)
    return i if i < len(sorted_list) else None


if __name__ == "__main__":
    db.init_db()
    positions = calculate_positions(include_closed=True)
    summary = calculate_summary(positions)
    print(f"持仓 {summary.holding_count} 个  成本 {summary.total_cost:.2f}  "
          f"市值 {summary.total_value:.2f}")
    print(f"浮动盈亏 {summary.unrealized_pnl:.2f}  已实现 {summary.realized_pnl:.2f}  "
          f"总盈亏 {summary.total_pnl:.2f}")
    for p in positions:
        tag = "" if p.is_open else "[已清仓]"
        print(f"  {p.fund_name[:18]:20} {p.channel:6} 份额{p.held_shares:.1f} "
              f"浮动{p.unrealized_pnl:.1f} 已实现{p.realized_pnl:.1f} {tag}")
