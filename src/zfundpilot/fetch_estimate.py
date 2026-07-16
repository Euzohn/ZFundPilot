"""基金实时估值获取模块。

数据源：天天基金 fundgz API
URL: http://fundgz.1234567.com.cn/js/{fund_code}.js
返回 JSONP: jsonpgz({"fundcode":"005827","name":"易方达蓝筹精选混合",
                     "jzrq":"2026-07-15","dwjz":"1.5378",
                     "gsz":"1.5230","gszzl":"-0.96","gztime":"2026-07-16 15:00"});

仅权益类基金（股票型/混合型/指数型/QDII）有估值数据，债券型/货币型无估值。

对外主要函数：
- fetch_estimate(fund_code)         获取单只基金实时估值
- fetch_estimates(fund_codes)      批量获取（带限速）
"""

from __future__ import annotations

import json
import re
import time
import urllib.request
from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

_TZ = ZoneInfo("Asia/Shanghai")

_estimate_cache: dict[str, tuple[float, FundEstimate]] = {}
_CACHE_TTL = 30  # 秒


@dataclass
class FundEstimate:
    """单只基金的实时估值结果。"""
    fund_code: str
    fund_name: str = ""
    jzrq: str = ""          # 上一交易日净值日期
    dwjz: float = 0.0       # 上一交易日单位净值
    gsz: float = 0.0        # 估算净值
    gszzl: float = 0.0      # 估算涨跌幅 (%)
    gztime: str = ""        # 估算时间
    ok: bool = False
    message: str = ""


def _http_get(url: str, timeout: int = 10) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", errors="ignore")


def fetch_estimate(fund_code: str) -> FundEstimate:
    """获取单只基金的实时估值。不抛异常。"""
    fund_code = fund_code.strip()
    if not fund_code:
        return FundEstimate(fund_code, ok=False, message="基金代码为空")

    cached = _estimate_cache.get(fund_code)
    if cached and time.time() - cached[0] < _CACHE_TTL:
        return cached[1]

    try:
        text = _http_get(f"http://fundgz.1234567.com.cn/js/{fund_code}.js")
        m = re.search(r"jsonpgz\((.+)\);?", text)
        if not m:
            return FundEstimate(fund_code, ok=False, message="解析失败")
        data = json.loads(m.group(1))
        est = FundEstimate(
            fund_code=data.get("fundcode", fund_code),
            fund_name=data.get("name", ""),
            jzrq=data.get("jzrq", ""),
            dwjz=float(data.get("dwjz", 0)),
            gsz=float(data.get("gsz", 0)),
            gszzl=float(data.get("gszzl", 0)),
            gztime=data.get("gztime", ""),
            ok=True,
        )
        if est.jzrq and est.gztime and est.jzrq == est.gztime[:10]:
            est.ok = False
            est.message = "净值已更新"
        elif est.gztime and est.gztime[:10] != datetime.now(_TZ).strftime("%Y-%m-%d"):
            est.ok = False
            est.message = "非交易时段"
        _estimate_cache[fund_code] = (time.time(), est)
        return est
    except Exception as exc:  # noqa: BLE001
        return FundEstimate(fund_code, ok=False, message=str(exc))


def fetch_estimates(fund_codes: list[str]) -> list[FundEstimate]:
    """批量获取基金实时估值。带 0.3s 限速。"""
    results: list[FundEstimate] = []
    for code in fund_codes:
        results.append(fetch_estimate(code))
        time.sleep(0.3)
    return results


def clear_estimate_cache() -> None:
    _estimate_cache.clear()
