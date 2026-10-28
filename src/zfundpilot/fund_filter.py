"""基金筛选模块。

从天天基金全市场基金池中按条件筛选候选基金，
选中后可加入现有基金对比流程。
"""

from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor, wait
from dataclasses import dataclass

from . import compare as _compare
from . import config
from .fetch_fund import _guess_fund_type, _guess_sector

logger = logging.getLogger(__name__)

_UNIVERSE_URL = "https://fund.eastmoney.com/js/fundcode_search.js"
_UNIVERSE_PATH = os.path.join(config.DATA_DIR, "fund_universe.json")
_UNIVERSE_TTL = 86400

_EXECUTOR = ThreadPoolExecutor(max_workers=6)

_MAX_METRICS_FUNDS = 30

# 指标增强会访问外部接口。Agent 侧限制同时进行的增强请求数，
# 避免慢请求无限堆积；额度在后台任务真正结束后才释放。
_ENRICH_MAX_CONCURRENCY = 2
_ENRICH_TIMEOUT = 20.0
_ENRICH_GATE = threading.BoundedSemaphore(_ENRICH_MAX_CONCURRENCY)


class EnrichmentBusy(RuntimeError):
    """指标增强并发已满，调用方应快速拒绝而不是排队。"""


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
    code: str = ""


@dataclass
class MetricsEnrichment:
    """一次指标增强的结果统计（供 Agent 解释覆盖范围）。"""

    requested: bool = True
    limit: int = _MAX_METRICS_FUNDS
    attempted: int = 0
    succeeded: int = 0
    failed: int = 0
    timed_out: int = 0
    complete: bool = False

    def to_dict(self) -> dict:
        return {
            "requested": self.requested,
            "limit": self.limit,
            "attempted": self.attempted,
            "succeeded": self.succeeded,
            "failed": self.failed,
            "timed_out": self.timed_out,
            "complete": self.complete,
        }


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
            logger.debug("基金池缓存读取失败", exc_info=True)

    data = _fetch_universe_from_web()
    if data:
        os.makedirs(os.path.dirname(_UNIVERSE_PATH), exist_ok=True)
        with open(_UNIVERSE_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
    return data


def _enrich_snapshot(item: FundFilterItem) -> dict:
    """采集单只基金的档案与指标快照，不修改入参对象。

    可能抛异常；调用方决定降级为失败还是忽略。
    """
    nav = _compare._get_cached_nav(item.code)
    archive = _compare._get_fund_archive(item.code)
    snapshot: dict = {
        "scale": archive.get("scale"),
        "manager": archive.get("manager", ""),
        "inception_date": archive.get("inception", ""),
        "returns": {},
        "risk": {},
    }
    if nav.empty:
        return snapshot

    snapshot["returns"] = {
        "1w": _compare._calculate_period_return(nav, 5),
        "1m": _compare._calculate_period_return(nav, 22),
        "3m": _compare._calculate_period_return(nav, 66),
        "6m": _compare._calculate_period_return(nav, 132),
        "1y": _compare._calculate_period_return(nav, 252),
        "ytd": _compare._calculate_period_return(nav, _compare._ytd_trading_days(nav)),
        "since": (nav.iloc[-1] - nav.iloc[0]) / nav.iloc[0] if len(nav) > 1 else None,
    }
    snapshot["risk"] = {
        "max_drawdown": _compare._calculate_max_drawdown(nav),
        "volatility": _compare._calculate_volatility(nav),
        "sharpe": _compare._calculate_sharpe(nav),
    }
    return snapshot


def _enrich_one(item: FundFilterItem) -> None:
    """为单个 FundFilterItem 补充规模/经理/成立日期/收益/风险指标。"""
    try:
        snapshot = _enrich_snapshot(item)
    except Exception as exc:  # noqa: BLE001
        logger.warning("指标补充失败 %s: %s", item.code, exc)
        item.returns = {}
        item.risk = {}
        return

    item.scale = snapshot["scale"]
    item.manager = snapshot["manager"]
    item.inception_date = snapshot["inception_date"]
    item.returns = snapshot["returns"]
    item.risk = snapshot["risk"]


def _enrich_with_metrics(items: list[FundFilterItem]) -> None:
    """用线程池对 items 并发补充收益/风险指标（最多 _MAX_METRICS_FUNDS 只）。"""
    targets = items[:_MAX_METRICS_FUNDS]
    futures = [_EXECUTOR.submit(_enrich_one, it) for it in targets]
    for f in futures:
        try:
            f.result(timeout=60)
        except Exception as exc:
            logger.warning("指标补充超时或失败: %s", exc)


def enrich_page_metrics(
    items: list[FundFilterItem], timeout: float = _ENRICH_TIMEOUT
) -> tuple[dict[str, dict], MetricsEnrichment]:
    """有界地对当前页前 N 项补指标，返回 {基金代码: 快照} 与统计。

    与 ``_enrich_with_metrics`` 的区别：
    - 并发额度满了立即抛 ``EnrichmentBusy``，不排队；
    - 超时只返回已完成项，未完成项不写入结果，避免序列化时被后台线程改写；
    - 额度在后台任务全部结束后释放，超时不会提前放行。

    仅修改快照字典，不修改 ``items``。
    """
    targets = items[:_MAX_METRICS_FUNDS]
    stats = MetricsEnrichment(attempted=len(targets))
    if not targets:
        stats.complete = True
        return {}, stats

    if not _ENRICH_GATE.acquire(blocking=False):
        raise EnrichmentBusy("指标增强并发已满，请稍后再试")

    futures: dict[Future, FundFilterItem] = {}
    submit_error: Exception | None = None
    try:
        for item in targets:
            futures[_EXECUTOR.submit(_enrich_snapshot, item)] = item
    except Exception as exc:  # noqa: BLE001
        submit_error = exc

    if not futures:
        if submit_error is not None:
            _ENRICH_GATE.release()
            raise submit_error
        _ENRICH_GATE.release()
        stats.complete = True
        return {}, stats

    lock = threading.Lock()
    pending: set[Future] = set(futures)
    released = False

    def _release_when_done(fut: Future) -> None:
        nonlocal released
        with lock:
            pending.discard(fut)
            if not pending and not released:
                released = True
                _ENRICH_GATE.release()

    for fut in futures:
        fut.add_done_callback(_release_when_done)

    if submit_error is not None:
        # 已提交的任务仍会通过回调释放额度；这里直接报告提交失败。
        raise submit_error

    wait(set(futures), timeout=timeout)

    snapshots: dict[str, dict] = {}
    for fut, item in futures.items():
        if not fut.done():
            stats.timed_out += 1
            continue
        try:
            snapshots[item.code] = fut.result()
        except Exception as exc:  # noqa: BLE001
            logger.warning("指标补充失败 %s: %s", item.code, exc)
            stats.failed += 1

    stats.succeeded = len(snapshots)
    stats.complete = stats.succeeded + stats.failed == stats.attempted
    return snapshots, stats


def filter_funds(
    types: list[str] | None = None,
    sectors: list[str] | None = None,
    keyword: str = "",
    limit: int = 50,
    offset: int = 0,
    with_metrics: bool = False,
) -> FilterResponse:
    """按条件筛选基金候选池。with_metrics=True 时对前 _MAX_METRICS_FUNDS 只补充收益/风险指标。"""
    universe = load_fund_universe()
    if not universe:
        return FilterResponse(funds=[], total=0, ok=False, message="基金池加载失败，请稍后重试", code="universe_failed")

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

    if with_metrics and items:
        _enrich_with_metrics(items)

    return FilterResponse(funds=items, total=total)


# ---------------------------------------------------------------------------
# 名称 → 代码解析（截图导入用）
# ---------------------------------------------------------------------------
_CLASS_RE = re.compile(r"[A-Za-z]类?$")
_TYPE_SUFFIXES = (
    "联接", "ETF联接", "ETF", "FOF", "混合", "指数", "债券",
    "股票", "发起式", "证券投资基金", "基金", "类",
)


def _normalize_name(name: str) -> str:
    """去除基金名称尾部的类别字母和类型后缀，用于模糊匹配。"""
    n = name.strip()
    changed = True
    while changed:
        changed = False
        n = _CLASS_RE.sub("", n).strip()
        for suf in _TYPE_SUFFIXES:
            if n.endswith(suf):
                n = n[: -len(suf)].strip()
                changed = True
                break
    return n


def _candidate(code: str, name: str) -> dict:
    return {"code": code, "name": name}


def resolve_fund_code(name: str) -> dict:
    """根据基金名称解析代码。

    返回 {"code": str|None, "candidates": [{"code","name"}], "status": str}。
    status: "exact"（唯一匹配，code 已填） | "multiple"（多候选，前端下拉选） | "none"（无匹配，前端手填）。
    匹配策略：精确 → 双向子串包含 → 归一化后子串包含。
    """
    name = (name or "").strip()
    if not name:
        return {"code": None, "candidates": [], "status": "none"}

    universe = load_fund_universe()
    if not universe:
        return {"code": None, "candidates": [], "status": "none"}

    # 1. 精确匹配
    exact = [f for f in universe if f["name"] == name]
    if len(exact) == 1:
        return {"code": exact[0]["code"], "candidates": [], "status": "exact"}
    if len(exact) > 1:
        return {"code": None, "candidates": [_candidate(f["code"], f["name"]) for f in exact], "status": "multiple"}

    # 2. 双向子串包含（截图名是全名子串，或全名是截图名子串）
    substr = [f for f in universe if name in f["name"] or f["name"] in name]
    if len(substr) == 1:
        return {"code": substr[0]["code"], "candidates": [], "status": "exact"}

    # 3. 归一化后双向子串包含（处理 A/C 类、联接、混合等后缀差异）
    norm = _normalize_name(name)
    norm_matches: list[dict] = []
    if norm and norm != name:
        for f in universe:
            fn = _normalize_name(f["name"])
            if norm in fn or fn in norm:
                norm_matches.append(f)
        if len(norm_matches) == 1:
            return {"code": norm_matches[0]["code"], "candidates": [], "status": "exact"}

    # 合并候选
    seen = {f["code"] for f in substr}
    combined = list(substr) + [f for f in norm_matches if f["code"] not in seen]
    if len(combined) == 1:
        return {"code": combined[0]["code"], "candidates": [], "status": "exact"}
    if combined:
        return {
            "code": None,
            "candidates": [_candidate(f["code"], f["name"]) for f in combined[:20]],
            "status": "multiple",
        }

    return {"code": None, "candidates": [], "status": "none"}


def verify_fund_code(code: str) -> bool:
    """校验 6 位代码是否存在于基金池中。防视觉模型编造代码。"""
    code = (code or "").strip()
    if not code:
        return False
    universe = load_fund_universe()
    if not universe:
        return False
    return any(f["code"] == code for f in universe)
