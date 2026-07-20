"""基金筛选模块。

从天天基金全市场基金池中按条件筛选候选基金，
选中后可加入现有基金对比流程。
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

from . import config
from .fetch_fund import _guess_fund_type, _guess_sector

logger = logging.getLogger(__name__)

_UNIVERSE_URL = "https://fund.eastmoney.com/js/fundcode_search.js"
_UNIVERSE_PATH = os.path.join(config.DATA_DIR, "fund_universe.json")
_UNIVERSE_TTL = 86400

_EXECUTOR = ThreadPoolExecutor(max_workers=6)

_MAX_METRICS_FUNDS = 30


@dataclass
class FundFilterItem:
    code: str
    name: str
    type: str
    sector: str
    scale: float | None = None
    manager: str = ""
    inception_date: str = ""
    returns: dict[str, float | None] = None
    risk: dict[str, float | None] = None


@dataclass
class FilterResponse:
    funds: list[FundFilterItem]
    total: int
    ok: bool = True
    message: str = ""


def _fetch_universe_from_web() -> list[dict]:
    """从天天基金拉取全市场基金列表并分类。"""
    import urllib.request

    try:
        req = urllib.request.Request(
            _UNIVERSE_URL,
            headers={"User-Agent": "Mozilla/5.0", "Referer": "https://fund.eastmoney.com/"},
        )
        with urllib.request.urlopen(req, timeout=20) as resp:
            text = resp.read().decode("utf-8")

        m = re.search(r"var r\s*=\s*(\[.*\])\s*;", text, re.DOTALL)
        if not m:
            raise ValueError("无法匹配 fundcode_search.js 数据")

        raw = json.loads(m.group(1))
        result: list[dict] = []
        seen: set[str] = set()
        for item in raw:
            code = str(item[0])
            name = str(item[2])
            raw_type = str(item[3])
            if code in seen:
                continue
            seen.add(code)
            fund_type = _guess_fund_type(raw_type, name)
            sector = _guess_sector(name)
            result.append({"code": code, "name": name, "type": fund_type, "sector": sector})

        logger.info("基金宇宙加载完成: %d 只", len(result))
        return result
    except Exception as exc:
        logger.warning("获取基金宇宙失败: %s", exc)
        return []


def load_fund_universe(force_refresh: bool = False) -> list[dict]:
    """加载基金宇宙（本地缓存优先）。"""
    if not force_refresh and os.path.exists(_UNIVERSE_PATH):
        try:
            age = time.time() - os.path.getmtime(_UNIVERSE_PATH)
            if age < _UNIVERSE_TTL:
                with open(_UNIVERSE_PATH, encoding="utf-8") as f:
                    return json.load(f)
        except Exception:
            pass

    data = _fetch_universe_from_web()
    if data:
        os.makedirs(os.path.dirname(_UNIVERSE_PATH), exist_ok=True)
        with open(_UNIVERSE_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
    return data


def filter_funds(
    types: list[str] | None = None,
    sectors: list[str] | None = None,
    keyword: str = "",
    limit: int = 50,
    offset: int = 0,
) -> FilterResponse:
    """按条件筛选基金候选池。"""
    universe = load_fund_universe()
    if not universe:
        return FilterResponse(funds=[], total=0, ok=False, message="基金池加载失败，请稍后重试")

    matched = universe
    if types:
        matched = [f for f in matched if f["type"] in types]
    if sectors:
        matched = [f for f in matched if f["sector"] in sectors]
    if keyword:
        kw = keyword.strip()
        if kw:
            matched = [f for f in matched if kw in f["name"] or kw in f["code"]]

    matched.sort(key=lambda f: f["code"])
    total = len(matched)
    page = matched[offset : offset + limit]

    items = [FundFilterItem(code=f["code"], name=f["name"], type=f["type"], sector=f["sector"]) for f in page]

    return FilterResponse(funds=items, total=total)
