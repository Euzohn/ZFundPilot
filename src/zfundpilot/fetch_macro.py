"""宏观经济数据获取模块（CPI / M2，财富水位线）。

数据源（AkShare，均为国家统计局/央行官方月度数据）：
1. CPI: ak.macro_china_cpi() — 全国-当月 为同比指数（base 100=上年同月），
   通过链乘「全国-环比增长」重建定基价格水平（2008-01=100），
   得到累计通胀序列。2008-01 起。
2. M2: ak.macro_china_money_supply() — 货币和准货币(M2)-数量(亿元)，
   为货币存量绝对值，累计增速 = M2_latest / M2_baseline - 1。2008-01 起。

对外主要函数：
- fetch_macro_history(code, start, end)  获取累计财富水位序列（与指数基准同构）
- fetch_macro_latest(code)                最新可用月份（调度用）
- clear_macro_cache()                     清空内存缓存

复用 index_history 表持久化（code="CPI"/"M2"，source="macro"），
三级缓存：L1 内存（1h TTL）→ L2 SQLite → L3 AkShare 在线。
"""

from __future__ import annotations

import calendar
import logging
import re
import time
from datetime import datetime, timedelta

import akshare as ak
import pandas as pd

from . import config, db

logger = logging.getLogger(__name__)

_macro_cache: dict[str, tuple[float, list[dict]]] = {}
_MACRO_TTL = 3600  # 秒（1h，月度数据几乎不变）
# 宏观数据为月度，发布滞后约 10 天；最新月份距今 ≤45 天视为新鲜
_MACRO_FRESH_DAYS = 45

# 代码 → 名称（与 config.MACRO_INDICES 保持一致）
MACRO_SOURCES: dict[str, str] = {
    "CPI": "macro_china_cpi",
    "M2": "macro_china_money_supply",
}

_MONTH_RE = re.compile(r"(\d{4})年(\d{2})月份")


def _parse_cn_month(value: str) -> str | None:
    """解析 "2026年07月份" → "2026-07-31"（月末日期）。解析失败返回 None。"""
    m = _MONTH_RE.search(str(value))
    if not m:
        return None
    year, month = int(m.group(1)), int(m.group(2))
    if not 1 <= month <= 12:
        return None
    last_day = calendar.monthrange(year, month)[1]
    return f"{year:04d}-{month:02d}-{last_day:02d}"


def _safe_float(value: object, default: float = 0.0) -> float:
    try:
        f = float(value)
        if pd.isna(f):
            return default
        return f
    except (TypeError, ValueError):
        return default


def _build_cpi_level(df: pd.DataFrame) -> list[dict]:
    """链乘 CPI 环比增长，重建定基价格水平（2008-01=100）。

    全国-环比增长 为月度环比（%），价格水平 = 前值 × (1 + 环比/100)。
    AkShare 返回降序，先按日期升序再链乘，确保水平值与月份一一对应。
    返回 [{date: "YYYY-MM-DD"(月末), close: 定基价格水平}, ...] 升序。
    """
    rows = []
    for _, row in df.iterrows():
        d = _parse_cn_month(row.get("月份"))
        if not d:
            continue
        rows.append((d, _safe_float(row.get("全国-环比增长"))))
    rows.sort(key=lambda r: r[0])

    result: list[dict] = []
    level = 100.0
    for d, mom in rows:
        if mom != 0.0:
            level = level * (1 + mom / 100.0)
        result.append({"date": d, "close": round(level, 4)})
    return result


def _fetch_macro_full(code: str) -> list[dict]:
    """从 AkShare 拉取宏观数据全量序列，失败返回空列表。

    AkShare 返回降序（最新在前），统一转为按日期升序。
    """
    try:
        if code == "CPI":
            df = ak.macro_china_cpi()
            if df is None or len(df) == 0:
                return []
            result = _build_cpi_level(df)
        elif code == "M2":
            df = ak.macro_china_money_supply()
            if df is None or len(df) == 0:
                return []
            result = []
            for _, row in df.iterrows():
                d = _parse_cn_month(row.get("月份"))
                if not d:
                    continue
                close = _safe_float(row.get("货币和准货币(M2)-数量(亿元)"))
                if close > 0:
                    result.append({"date": d, "close": close})
        else:
            return []
        result.sort(key=lambda pt: pt["date"])
        return result
    except Exception:  # noqa: BLE001
        logger.exception("fetch_macro_history failed: %s", code)
        return []


def _macro_is_fresh(db_latest: str) -> bool:
    """宏观数据为月度，最新月份距今 ≤45 天（含发布滞后）即视为新鲜。"""
    try:
        latest = datetime.strptime(db_latest, "%Y-%m-%d").date()
    except ValueError:
        return False
    today = datetime.now(config.TIMEZONE).date()
    return (today - latest).days <= _MACRO_FRESH_DAYS


def fetch_macro_history(code: str, start_date: str, end_date: str) -> list[dict]:
    """获取宏观经济财富水位序列。

    三级数据源（L1 内存缓存 → L2 SQLite → L3 AkShare 在线），
    与 fetch_estimate.fetch_index_history 同构：
    - L1：内存缓存 1h TTL，命中即返回
    - L2：DB 持久化缓存（index_history 表，code="CPI"/"M2"），数据新鲜时直接返回
    - L3：在线拉取 AkShare，成功后持久化到 DB，再从 DB 返回

    离线场景：L3 失败时从 L2 DB 返回已有数据（可能非最新，但不空）。

    Args:
        code: "CPI" 或 "M2"
        start_date: 起始日期 "YYYY-MM-DD"
        end_date: 结束日期 "YYYY-MM-DD"

    Returns:
        [{date: "YYYY-MM-DD", close: 定基水平}, ...]，按日期升序。
        所有数据源都失败返回空列表。
    """
    if code not in MACRO_SOURCES:
        return []
    # L1：内存缓存
    cached = _macro_cache.get(code)
    if cached and time.time() - cached[0] < _MACRO_TTL:
        full = cached[1]
        return [pt for pt in full if start_date <= pt["date"] <= end_date]

    # L2/L3：DB 优先，宏观数据过期（月度）才在线拉取
    db_latest = db.get_index_latest_date(code)
    need_fetch = not db_latest or not _macro_is_fresh(db_latest)

    if need_fetch:
        full = _fetch_macro_full(code)
        if full:
            db.upsert_index_history(
                code, [(pt["date"], pt["close"]) for pt in full], source="macro"
            )
            _macro_cache[code] = (time.time(), full)
            return [pt for pt in full if start_date <= pt["date"] <= end_date]
        if db_latest:
            logger.info(
                "fetch_macro_history: 在线拉取失败，使用 DB 缓存 %s (最新 %s)",
                code, db_latest,
            )
        else:
            return []

    rows = db.get_index_history(code, start_date, end_date)
    if not rows:
        return []
    result = [{"date": r["date"], "close": float(r["close"])} for r in rows]
    all_rows = db.get_index_history(code)
    if all_rows:
        _macro_cache[code] = (
            time.time(),
            [{"date": r["date"], "close": float(r["close"])} for r in all_rows],
        )
    return result


def fetch_macro_baseline(code: str, start_date: str, end_date: str) -> tuple[list[dict], float] | None:
    """获取宏观序列及基期值（财富水位线计算的核心）。

    宏观为月度数据，基期 = 组合建仓日（start_date）之前最后一个月末水平；
    若建仓日之前无月末数据（如组合早于 2008 或刚建仓），退化为首个月末。
    取数窗口提前 60 天以确保能取到建仓前的月末基期点，
    使水位线在建仓日精确为 0，随后随通胀/货币扩张累积。

    Args:
        code: "CPI" 或 "M2"
        start_date: 组合起始日 "YYYY-MM-DD"
        end_date: 组合结束日 "YYYY-MM-DD"

    Returns:
        (hist, baseline_close)；hist 为升序序列，baseline_close 为基期水平值。
        无数据或基期为 0 时返回 None。
    """
    try:
        early = (datetime.strptime(start_date, "%Y-%m-%d") - timedelta(days=60)).strftime("%Y-%m-%d")
    except ValueError:
        return None
    hist = fetch_macro_history(code, early, end_date)
    if not hist:
        return None
    baseline_pts = [pt for pt in hist if pt["date"] <= start_date]
    baseline = baseline_pts[-1]["close"] if baseline_pts else hist[0]["close"]
    if baseline == 0:
        return None
    return hist, baseline


def fetch_macro_latest(code: str) -> str | None:
    """返回宏观数据在 DB 中的最新日期（调度用）。"""
    return db.get_index_latest_date(code)


def clear_macro_cache() -> None:
    """清空宏观数据内存缓存（DB 数据保留）。"""
    _macro_cache.clear()
