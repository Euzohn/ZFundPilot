"""基金实时估值获取模块。

数据源：AkShare fund_value_estimation_em（东方财富基金估值表）
替代已下线的 fundgz.1234567.com.cn JSONP API。

一次调用获取全市场基金估值 + 公布净值，30s 内存缓存。
仅权益类基金（股票型/混合型/指数型/QDII）有估值数据，债券型/货币型无估值。

对外主要函数：
- fetch_estimate(fund_code)         获取单只基金实时估值
- fetch_estimates(fund_codes)      批量获取
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

import akshare as ak
import pandas as pd

_TZ = ZoneInfo("Asia/Shanghai")

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
    gztime = datetime.now(_TZ).strftime("%Y-%m-%d %H:%M")

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
    """获取全市场基金估值（带缓存）。"""
    cached = _batch_cache.get(_BATCH_KEY)
    if cached and time.time() - cached[0] < _CACHE_TTL:
        return cached[1]
    try:
        df = ak.fund_value_estimation_em()
        all_ests = _parse_dataframe(df)
        _batch_cache[_BATCH_KEY] = (time.time(), all_ests)
        return all_ests
    except Exception:  # noqa: BLE001
        return []


def fetch_estimate(fund_code: str) -> FundEstimate:
    """获取单只基金的实时估值。不抛异常。"""
    fund_code = fund_code.strip()
    if not fund_code:
        return FundEstimate(fund_code, ok=False, message="基金代码为空")
    for est in _get_all_estimates():
        if est.fund_code == fund_code:
            return est
    return FundEstimate(fund_code, ok=False, message="未找到")


def fetch_estimates(fund_codes: list[str]) -> list[FundEstimate]:
    """批量获取基金估值。"""
    all_ests = _get_all_estimates()
    if not all_ests:
        return [FundEstimate(code, ok=False, message="获取失败") for code in fund_codes]
    est_map = {e.fund_code: e for e in all_ests}
    return [
        est_map.get(code, FundEstimate(code, ok=False, message="未找到"))
        for code in fund_codes
    ]


def clear_estimate_cache() -> None:
    _batch_cache.clear()
