"""基金实时估值获取模块。

数据源：
1. AkShare fund_value_estimation_em（东方财富基金估值表）— 主源，目前不可用
2. 指数/ETF 实时行情兜底 — 对指数型基金，用跟踪指数或 ETF 的实时涨跌估算

一次调用获取全市场基金估值 + 公布净值，30s 内存缓存。
仅权益类基金（股票型/混合型/指数型/QDII）有估值数据，债券型/货币型无估值。

对外主要函数：
- fetch_estimate(fund_code)         获取单只基金实时估值
- fetch_estimates(fund_codes)      批量获取
- fetch_index_quotes(keywords)     获取指数/ETF 实时涨跌（指数估值兜底）
- estimate_from_index(...)         用指数涨跌构建 FundEstimate
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime

import akshare as ak
import pandas as pd

from . import config

_batch_cache: dict[str, tuple[float, list[FundEstimate]]] = {}
_BATCH_KEY = "__batch__"
_CACHE_TTL = 30  # 秒


@dataclass
class FundEstimate:
    """单只基金的实时估值结果。"""
    fund_code: str
    fund_name: str = ""
    jzrq: str = ""          # 上一交易日净值日期
    dwjz: float = 0.0       # 上一交易日单位净值
    gsz: float = 0.0        # 估算净值 / 公布净值
    gszzl: float = 0.0      # 估算涨跌幅 / 实际涨跌幅 (%)
    gztime: str = ""        # 数据时间
    ok: bool = False
    message: str = ""
    code: str = ""          # stable machine code for i18n


def _safe_float(val: object) -> float:
    """安全解析为 float，处理 '--' / 空 / NaN。"""
    if val is None:
        return 0.0
    s = str(val).strip()
    if not s or s == "--":
        return 0.0
    try:
        f = float(s)
        return 0.0 if f != f else f  # NaN check
    except (ValueError, TypeError):
        return 0.0


def _safe_pct(val: object) -> float:
    """解析 '0.98%' → 0.98。"""
    if val is None:
        return 0.0
    s = str(val).strip().replace("%", "")
    if not s or s == "--":
        return 0.0
    try:
        return float(s)
    except (ValueError, TypeError):
        return 0.0


def _parse_dataframe(df: pd.DataFrame) -> list[FundEstimate]:
    """解析 AkShare 估值表为 FundEstimate 列表。"""
    # 列名含动态日期，按模式匹配
    est_nav_col = next((c for c in df.columns if "估算数据" in c and "估算值" in c), None)
    est_pct_col = next((c for c in df.columns if "估算数据" in c and "估算增长率" in c), None)
    pub_nav_col = next((c for c in df.columns if "公布数据" in c and "单位净值" in c), None)
    pub_pct_col = next((c for c in df.columns if "公布数据" in c and "日增长率" in c), None)
    prev_nav_col = next(
        (c for c in df.columns
         if c.endswith("-单位净值") and "公布" not in c and "估算" not in c),
        None,
    )

    # 从列名提取日期
    prev_date = prev_nav_col.split("-单位净值")[0] if prev_nav_col else ""
    # 尝试从估值列名提取估算日期
    est_date = ""
    if est_nav_col:
        parts = est_nav_col.split("-")
        if len(parts) >= 3 and len(parts[0]) == 4:
            est_date = "-".join(parts[:3])
    gztime = f"{est_date} 15:00" if est_date else (
        f"{prev_date} {datetime.now(config.TIMEZONE).strftime('%H:%M')}"
        if prev_date else datetime.now(config.TIMEZONE).strftime("%Y-%m-%d %H:%M")
    )

    results: list[FundEstimate] = []
    for _, row in df.iterrows():
        code = str(row.get("基金代码", "")).strip()
        if not code:
            continue
        name = str(row.get("基金名称", ""))
        gsz_est = _safe_float(row[est_nav_col]) if est_nav_col else 0
        gszzl_est = _safe_pct(row[est_pct_col]) if est_pct_col else 0
        pub_nav = _safe_float(row[pub_nav_col]) if pub_nav_col else 0
        pub_pct = _safe_pct(row[pub_pct_col]) if pub_pct_col else 0
        dwjz = _safe_float(row[prev_nav_col]) if prev_nav_col else 0

        # 有公布净值 → 用实际值 (ok=False)；仅有估算 → ok=True
        if pub_nav > 0:
            ok = False
            gsz = pub_nav
            gszzl = pub_pct
        else:
            ok = gsz_est > 0
            gsz = gsz_est
            gszzl = gszzl_est

        results.append(FundEstimate(
            fund_code=code,
            fund_name=name,
            jzrq=prev_date,
            dwjz=dwjz,
            gsz=gsz,
            gszzl=gszzl,
            gztime=gztime,
            ok=ok,
        ))

    return results


def _get_all_estimates() -> list[FundEstimate]:
    """获取全市场基金估值（带缓存，失败时 stale-if-error）。"""
    cached = _batch_cache.get(_BATCH_KEY)
    if cached and time.time() - cached[0] < _CACHE_TTL:
        return cached[1]
    try:
        df = ak.fund_value_estimation_em()
        all_ests = _parse_dataframe(df)
        _batch_cache[_BATCH_KEY] = (time.time(), all_ests)
        return all_ests
    except Exception:  # noqa: BLE001
        if cached:
            return cached[1]
        _batch_cache[_BATCH_KEY] = (time.time(), [])
        return []


def fetch_estimate(fund_code: str) -> FundEstimate:
    """获取单只基金的实时估值。不抛异常。"""
    fund_code = fund_code.strip()
    if not fund_code:
        return FundEstimate(fund_code, ok=False, message="基金代码为空", code="code_empty")
    for est in _get_all_estimates():
        if est.fund_code == fund_code:
            return est
    return FundEstimate(fund_code, ok=False, message="未找到", code="not_found")


def fetch_estimates(fund_codes: list[str]) -> list[FundEstimate]:
    """批量获取基金估值。"""
    all_ests = _get_all_estimates()
    if not all_ests:
        return [FundEstimate(code, ok=False, message="获取失败", code="fetch_failed") for code in fund_codes]
    est_map = {e.fund_code: e for e in all_ests}
    return [
        est_map.get(code, FundEstimate(code, ok=False, message="未找到", code="not_found"))
        for code in fund_codes
    ]


def clear_estimate_cache() -> None:
    _batch_cache.clear()


# ---------------------------------------------------------------------------
# 指数/ETF 实时行情（指数型基金估值兜底）
# ---------------------------------------------------------------------------
_index_spot_cache: tuple[float, dict[str, float]] = (0.0, {})
_etf_spot_cache: tuple[float, dict[str, float]] = (0.0, {})
_INDEX_CACHE_TTL = 30   # 秒
_ETF_CACHE_TTL = 60     # 秒（ETF 拉取较慢，缓存更久）


def _fetch_index_spot() -> dict[str, float]:
    """合并三个指数实时 API → {名称: 涨跌幅}。"""
    result: dict[str, float] = {}
    try:
        df = ak.stock_zh_index_spot_sina()
        for _, row in df.iterrows():
            name = str(row.get("名称", "")).strip()
            pct = _safe_float(row.get("涨跌幅"))
            if name and pct:
                result[name] = pct
    except Exception:  # noqa: BLE001
        pass
    try:
        df = ak.index_global_spot_em()
        for _, row in df.iterrows():
            name = str(row.get("名称", "")).strip()
            pct = _safe_float(row.get("涨跌幅"))
            if name and pct:
                result[name] = pct
    except Exception:  # noqa: BLE001
        pass
    try:
        df = ak.stock_hk_index_spot_em()
        for _, row in df.iterrows():
            name = str(row.get("名称", "")).strip()
            pct = _safe_float(row.get("涨跌幅"))
            if name and pct:
                result[name] = pct
    except Exception:  # noqa: BLE001
        pass
    return result


def _fetch_etf_spot() -> dict[str, float]:
    """ETF 实时行情 → {名称: 涨跌幅}。"""
    result: dict[str, float] = {}
    try:
        df = ak.fund_etf_spot_em()
        for _, row in df.iterrows():
            name = str(row.get("名称", "")).strip()
            pct = _safe_float(row.get("涨跌幅"))
            if name and pct:
                result[name] = pct
    except Exception:  # noqa: BLE001
        pass
    return result


def _get_index_spot_cached() -> dict[str, float]:
    global _index_spot_cache
    if _index_spot_cache[0] and time.time() - _index_spot_cache[0] < _INDEX_CACHE_TTL:
        return _index_spot_cache[1]
    data = _fetch_index_spot()
    _index_spot_cache = (time.time(), data)
    return data


def _get_etf_spot_cached() -> dict[str, float]:
    global _etf_spot_cache
    if _etf_spot_cache[0] and time.time() - _etf_spot_cache[0] < _ETF_CACHE_TTL:
        return _etf_spot_cache[1]
    data = _fetch_etf_spot()
    _etf_spot_cache = (time.time(), data)
    return data


def _match_keyword(keyword: str, name_map: dict[str, float]) -> float | None:
    """在 {名称: 涨跌幅} 中匹配关键词。

    匹配策略：精确 → 包含 → 逐字缩短（前缀子串）。
    """
    if keyword in name_map:
        return name_map[keyword]
    for name, pct in name_map.items():
        if keyword in name or name in keyword:
            return pct
    for length in range(len(keyword) - 1, 2, -1):
        substr = keyword[:length]
        for name, pct in name_map.items():
            if substr in name:
                return pct
    return None


def fetch_index_quotes(keywords: list[str]) -> dict[str, float]:
    """批量获取指数/ETF 实时涨跌幅。

    返回 {keyword: 涨跌幅}。先查指数实时行情（快），
    未匹配的关键词再查 ETF 实时行情（慢，仅按需）。
    """
    if not keywords:
        return {}

    index_map = _get_index_spot_cached()
    result: dict[str, float] = {}
    unmatched: list[str] = []

    for kw in keywords:
        matched = _match_keyword(kw, index_map)
        if matched is not None:
            result[kw] = matched
        else:
            unmatched.append(kw)

    if unmatched:
        etf_map = _get_etf_spot_cached()
        for kw in unmatched:
            matched = _match_keyword(kw, etf_map)
            if matched is not None:
                result[kw] = matched

    return result


def estimate_from_index(
    fund_code: str,
    fund_name: str,
    tracking_index: str,
    prev_nav: float,
    prev_date: str,
) -> FundEstimate:
    """用跟踪指数/ETF 的实时涨跌构建 FundEstimate。"""
    quotes = fetch_index_quotes([tracking_index])
    change_pct = quotes.get(tracking_index)
    if change_pct is None or prev_nav <= 0:
        return FundEstimate(
            fund_code, ok=False,
            message="无指数行情", code="no_index_quote",
        )
    gsz = round(prev_nav * (1 + change_pct / 100), 4)
    now_str = datetime.now(config.TIMEZONE).strftime("%Y-%m-%d %H:%M")
    return FundEstimate(
        fund_code=fund_code,
        fund_name=fund_name,
        jzrq=prev_date,
        dwjz=prev_nav,
        gsz=gsz,
        gszzl=round(change_pct, 2),
        gztime=now_str,
        ok=True,
        message="指数估值",
        code="index_estimate",
    )


def clear_index_cache() -> None:
    """清空指数/ETF 行情缓存。"""
    global _index_spot_cache, _etf_spot_cache
    _index_spot_cache = (0.0, {})
    _etf_spot_cache = (0.0, {})
