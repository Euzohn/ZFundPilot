"""基金对比功能模块。

核心：输入多个基金代码，输出多维度对比数据。
所有计算基于基金净值历史 + 基本信息 + 费率。
"""

from __future__ import annotations

import asyncio
import logging
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, asdict

import pandas as pd

from . import config, fetch_fund
from .fetch_fund import fetch_nav_history, fetch_fund_fee_rates, fetch_fund_meta
from .models import NavPoint

logger = logging.getLogger(__name__)

_EXECUTOR = ThreadPoolExecutor(max_workers=6)

# 缓存：净值历史
_nav_cache: dict[str, dict] = {}
_NAV_CACHE_TTL = 3600  # 1 小时

# 缓存：基本信息
_meta_cache: dict[str, dict] = {}
_META_CACHE_TTL = 86400  # 24 小时


@dataclass
class FundCompareItem:
    code: str
    name: str = ""
    type: str = ""
    sector: str = ""
    inception_date: str = ""
    scale: float | None = None        # 基金规模（亿元）
    manager: str = ""
    management_fee: float | None = None
    custodian_fee: float | None = None
    sales_fee: float | None = None
    returns: dict[str, float | None] = None    # { "1w", "1m", "3m", "6m", "1y", "3y", "ytd", "since" }
    risk: dict[str, float | None] = None       # { "max_drawdown", "volatility", "sharpe", "calmar", "win_rate" }
    estimate: dict[str, float | str | bool | None] | None = None
    latest_nav: float | None = None
    latest_date: str | None = None
    ok: bool = True
    message: str = ""


@dataclass
class CompareResponse:
    funds: list[FundCompareItem]
    correlations: list[list[float | None]] = None
    nav_series: dict[str, list[dict[str, float | str]]] = None
    ok: bool = True
    message: str = ""


def _nav_to_series(points: list[NavPoint]) -> pd.Series:
    """将 NavPoint 列表转为 date-indexed pandas Series。"""
    if not points:
        return pd.Series(dtype=float)
    dates = [p.date for p in points]
    navs = [p.nav for p in points]
    s = pd.Series(navs, index=pd.to_datetime(dates))
    s = s[~s.index.duplicated(keep="last")]
    s.sort_index(inplace=True)
    return s


def _get_cached_nav(fund_code: str) -> pd.Series:
    now = time.time()
    cached = _nav_cache.get(fund_code)
    if cached and now - cached["ts"] < _NAV_CACHE_TTL:
        return cached["data"]

    try:
        points = fetch_nav_history(fund_code)
    except Exception as exc:
        logger.warning("获取净值失败 %s: %s", fund_code, exc)
        _nav_cache[fund_code] = {"ts": now, "data": pd.Series(dtype=float)}
        return pd.Series(dtype=float)

    series = _nav_to_series(points)
    _nav_cache[fund_code] = {"ts": now, "data": series}
    return series


def _get_cached_meta(fund_code: str) -> dict:
    now = time.time()
    cached = _meta_cache.get(fund_code)
    if cached and now - cached["ts"] < _META_CACHE_TTL:
        return cached["data"]

    meta = fetch_fund_meta(fund_code)
    result = {"name": meta.fund_name, "type": meta.fund_type, "sector": meta.sector, "ok": meta.ok}
    _meta_cache[fund_code] = {"ts": now, "data": result}
    return result


def _get_fund_archive(fund_code: str) -> dict:
    """从天天基金档案页获取成立日期、规模、基金经理。
    
    这是额外的数据源，失败不影响整体对比。
    """
    fallback = {"inception": "", "scale": None, "manager": ""}
    try:
        url = f"https://fundf10.eastmoney.com/jbgk_{fund_code}.html"
        text = fetch_fund._http_get(url)
        import re
        inception = ""
        m = re.search(r"成立日期.*?(\d{4}-\d{2}-\d{2})", text)
        if m:
            inception = m.group(1)
        scale = None
        m = re.search(r"基金规模[：:]\s*([\d.]+)\s*亿元", text)
        if m:
            scale = float(m.group(1))
        manager = ""
        m = re.search(r"基金经理[：:]\s*([^<]+)", text)
        if m:
            manager = m.group(1).strip()
        return {"inception": inception, "scale": scale, "manager": manager}
    except Exception:
        return fallback


def _calculate_period_return(nav: pd.Series, periods: int) -> float | None:
    """计算指定交易日前的收益率。periods=22 ≈ 1个月。"""
    if len(nav) < 2:
        return None
    latest = nav.iloc[-1]
    idx = max(0, len(nav) - 1 - periods)
    earlier = nav.iloc[idx]
    if earlier == 0:
        return None
    return (latest - earlier) / earlier


def _calculate_max_drawdown(nav: pd.Series) -> float | None:
    if len(nav) < 5:
        return None
    peak = nav.expanding().max()
    dd = (nav - peak) / peak
    return float(dd.min())


def _calculate_volatility(nav: pd.Series, trading_days: int = 252) -> float | None:
    if len(nav) < 10:
        return None
    daily_returns = nav.pct_change().dropna()
    if len(daily_returns) < 5:
        return None
    return float(daily_returns.std() * (trading_days ** 0.5))


def _calculate_sharpe(nav: pd.Series, rf: float = 0.02) -> float | None:
    vol = _calculate_volatility(nav)
    if vol is None or vol == 0:
        return None
    daily_returns = nav.pct_change().dropna()
    if len(daily_returns) < 5:
        return None
    avg_daily_return = daily_returns.mean()
    annual_return = (1 + avg_daily_return) ** 252 - 1
    return (annual_return - rf) / vol


def _calculate_calmar(nav: pd.Series) -> float | None:
    mdd = _calculate_max_drawdown(nav)
    if mdd is None or mdd == 0:
        return None
    if len(nav) < 2:
        return None
    total_return = (nav.iloc[-1] - nav.iloc[0]) / nav.iloc[0]
    return total_return / abs(mdd) if mdd != 0 else None


def _calculate_win_rate(nav: pd.Series) -> float | None:
    if len(nav) < 30:
        return None
    daily_returns = nav.pct_change().dropna()
    if len(daily_returns) < 5:
        return None
    monthly = daily_returns.resample("ME").apply(lambda x: (1 + x).prod() - 1).dropna()
    if len(monthly) < 3:
        return None
    wins = (monthly > 0).sum()
    return wins / len(monthly)


def _calculate_correlation(nav1: pd.Series, nav2: pd.Series) -> float | None:
    """计算两只基金的 Pearson 相关系数（对齐日期）。"""
    if nav1.empty or nav2.empty:
        return None
    combined = pd.concat([nav1, nav2], axis=1, join="inner").dropna()
    if len(combined) < 10:
        return None
    return float(combined.iloc[:, 0].corr(combined.iloc[:, 1]))


def _normalize_nav(nav: pd.Series, base: int = 100) -> list[dict[str, float | str]]:
    """归一化到基期=100，返回 [{date, value}]。"""
    if nav.empty or nav.iloc[0] == 0:
        return []
    ratio = base / nav.iloc[0]
    result = []
    for date, val in nav.items():
        result.append({"date": str(date.date()), "value": round(float(val) * ratio, 2)})
    return result


def _build_fund_item(fund_code: str) -> FundCompareItem:
    """构建单只基金的对比数据。"""
    try:
        meta = _get_cached_meta(fund_code)
        if not meta.get("ok"):
            return FundCompareItem(code=fund_code, ok=False, message=meta.get("message", "获取基本信息失败"))
    except Exception as exc:
        return FundCompareItem(code=fund_code, ok=False, message=str(exc))

    nav = _get_cached_nav(fund_code)
    archive = _get_fund_archive(fund_code)

    if nav.empty:
        returns = {}
        risk = {}
    else:
        returns = {
            "1w": _calculate_period_return(nav, 5),
            "1m": _calculate_period_return(nav, 22),
            "3m": _calculate_period_return(nav, 66),
            "6m": _calculate_period_return(nav, 132),
            "1y": _calculate_period_return(nav, 252),
            "3y": _calculate_period_return(nav, 756),
            "ytd": _calculate_period_return(nav, _ytd_trading_days(nav)),
            "since": (nav.iloc[-1] - nav.iloc[0]) / nav.iloc[0] if len(nav) > 1 else None,
        }
        risk = {
            "max_drawdown": _calculate_max_drawdown(nav),
            "volatility": _calculate_volatility(nav),
            "sharpe": _calculate_sharpe(nav),
            "calmar": _calculate_calmar(nav),
            "win_rate": _calculate_win_rate(nav),
        }

    latest_nav = float(nav.iloc[-1]) if not nav.empty else None
    latest_date = str(nav.index[-1].date()) if not nav.empty else None

    # 费率
    fee = fetch_fund_fee_rates(fund_code)
    management_fee = fee.management_fee if fee.ok else None
    custodian_fee = fee.custodian_fee if fee.ok else None
    sales_fee = fee.sales_fee if fee.ok else None

    return FundCompareItem(
        code=fund_code,
        name=meta.get("name", ""),
        type=meta.get("type", "其它"),
        sector=meta.get("sector", ""),
        inception_date=archive.get("inception", ""),
        scale=archive.get("scale"),
        manager=archive.get("manager", ""),
        management_fee=management_fee,
        custodian_fee=custodian_fee,
        sales_fee=sales_fee,
        returns=returns,
        risk=risk,
        latest_nav=latest_nav,
        latest_date=latest_date,
        ok=True,
        message="",
    )


def _ytd_trading_days(nav: pd.Series) -> int:
    """计算今年至今的交易日数。"""
    if nav.empty:
        return 0
    this_year = nav.index.year.max()
    ytd = nav[nav.index.year == this_year]
    return len(ytd)


def compare_funds(fund_codes: list[str]) -> CompareResponse:
    """并发对比多只基金。"""
    codes = list(dict.fromkeys(c.strip() for c in fund_codes if c.strip()))
    if not codes:
        return CompareResponse(ok=False, message="基金代码列表为空")

    if len(codes) > 20:
        return CompareResponse(ok=False, message="一次最多对比 20 只基金")

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        items = loop.run_until_complete(_async_compare(codes))
    finally:
        loop.close()

    ok_items = [f for f in items if f.ok]
    if not ok_items:
        return CompareResponse(funds=items, ok=False, message="所有基金获取失败")

    correlations = None
    if len(ok_items) >= 2:
        navs = {f.code: _get_cached_nav(f.code) for f in ok_items}
        correlations = _build_correlation_matrix(ok_items, navs)

    nav_series = None
    if ok_items:
        navs = {f.code: _get_cached_nav(f.code) for f in ok_items}
        nav_series = {}
        for code, nav in navs.items():
            if not nav.empty:
                normalized = _normalize_nav(nav)
                if normalized:
                    nav_series[code] = normalized

    return CompareResponse(
        funds=items,
        correlations=correlations,
        nav_series=nav_series,
        ok=True,
        message="",
    )


async def _async_compare(codes: list[str]) -> list[FundCompareItem]:
    """使用线程池并发获取所有基金数据。"""
    loop = asyncio.get_event_loop()
    tasks = [loop.run_in_executor(_EXECUTOR, _build_fund_item, code) for code in codes]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    items: list[FundCompareItem] = []
    for i, r in enumerate(results):
        if isinstance(r, Exception):
            items.append(FundCompareItem(code=codes[i], ok=False, message=str(r)))
        else:
            items.append(r)
    return items


def _build_correlation_matrix(
    items: list[FundCompareItem],
    navs: dict[str, pd.Series],
) -> list[list[float | None]]:
    n = len(items)
    matrix = [[None] * n for _ in range(n)]
    for i in range(n):
        matrix[i][i] = 1.0
        for j in range(i + 1, n):
            corr = _calculate_correlation(navs.get(items[i].code, pd.Series(dtype=float)),
                                          navs.get(items[j].code, pd.Series(dtype=float)))
            matrix[i][j] = corr
            matrix[j][i] = corr
    return matrix


def clear_compare_cache() -> None:
    _nav_cache.clear()
    _meta_cache.clear()