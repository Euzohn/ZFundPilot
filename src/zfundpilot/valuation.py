"""指数估值（宽基 PE/PB 百分位 + 估值温度）。

数据源：乐咕乐股（akshare ``stock_index_pe_lg`` / ``stock_index_pb_lg``），
月度长历史（2005 年至今，约 260 个点），仅覆盖 12 个宽基指数。
上游不直接提供百分位，本模块用历史序列自算。

设计边界：

- 只做宽基：行业/主题指数无免费 PE+PB 历史源（中证源仅近 20 日 PE 快照）。
- 百分位默认近 10 年（历史不足 10 年用全历史并标注）；窗口直接改变结论，
  UI 必须标注口径。
- 乐咕反爬脆弱（JS token + cookie/csrf，实测间歇失败）：缓存 +
  stale-if-error + 单只降级，绝不阻塞其他页面。
- 温度以 PE(TTM) 百分位分档；PB 百分位并列展示。仅供参考，非投资建议。
"""

from __future__ import annotations

import json
import logging
from concurrent.futures import ThreadPoolExecutor, wait
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from . import db

logger = logging.getLogger(__name__)

TTL_HOURS = 24.0
DEFAULT_WINDOW_YEARS = 10
REFRESH_TIMEOUT = 20.0
_MAX_WORKERS = 6

# 温度阈值（PE 百分位，百分比）
LOW_MAX = 30.0
HIGH_MIN = 70.0


@dataclass(frozen=True)
class IndexMeta:
    """内置宽基指数元数据（乐咕覆盖的 12 个指数）。"""

    code: str
    name: str
    lg_symbol: str
    keyword: str  # 跟踪基金名称匹配关键词
    exclude: tuple[str, ...] = ()  # 需要排除的更长关键词（防止子串误匹配）


# 顺序即 UI 展示顺序（重要宽基在前）。
# 乐咕 symbol_map 是硬编码的，新增指数需先确认上游支持。
INDEX_REGISTRY: tuple[IndexMeta, ...] = (
    IndexMeta("000300", "沪深300", "沪深300", "沪深300"),
    IndexMeta("000905", "中证500", "中证500", "中证500"),
    IndexMeta("000852", "中证1000", "中证1000", "中证1000"),
    IndexMeta("000016", "上证50", "上证50", "上证50"),
    IndexMeta("399673", "创业板50", "创业板50", "创业板50"),
    # 「中证100」是「中证1000」的子串，匹配跟踪基金时需排除后者
    IndexMeta("000903", "中证100", "中证100", "中证100", exclude=("中证1000",)),
    IndexMeta("000906", "中证800", "中证800", "中证800"),
    IndexMeta("000010", "上证180", "上证180", "上证180"),
    IndexMeta("000009", "上证380", "上证380", "上证380"),
    IndexMeta("399330", "深证100", "深证100", "深证100"),
    IndexMeta("000015", "上证红利", "上证红利", "上证红利"),
    IndexMeta("399324", "深证红利", "深证红利", "深证红利"),
)

INDEX_BY_CODE: dict[str, IndexMeta] = {m.code: m for m in INDEX_REGISTRY}


# ---------------------------------------------------------------------------
# 数值 / 日期工具
# ---------------------------------------------------------------------------
def _safe_float(value: Any) -> float | None:
    """安全转 float；None/NaN/非法字符串返回 None。"""
    try:
        num = float(value)
    except (TypeError, ValueError):
        return None
    if num != num:  # NaN
        return None
    return num


def _parse_date(value: Any) -> datetime | None:
    """把 ``YYYY-MM-DD`` / date / Timestamp 解析为 datetime；失败返回 None。"""
    if value is None:
        return None
    if hasattr(value, "strftime"):
        try:
            return datetime(value.year, value.month, value.day)
        except (AttributeError, TypeError, ValueError):
            return None
    try:
        return datetime.strptime(str(value)[:10], "%Y-%m-%d")
    except ValueError:
        return None


def _normalize_date(value: Any) -> str:
    """统一日期为 ``YYYY-MM-DD``；非法返回空串。"""
    parsed = _parse_date(value)
    return parsed.strftime("%Y-%m-%d") if parsed else ""


def _values(points: list[dict[str, Any]], field: str) -> list[float]:
    """提取字段的有效浮点序列（跳过缺失/非法值）。"""
    out: list[float] = []
    for point in points:
        num = _safe_float(point.get(field))
        if num is not None:
            out.append(num)
    return out


def _last_value(values: list[float | None]) -> float | None:
    """取最后一个有效值。"""
    for value in reversed(values):
        if value is not None:
            return value
    return None


# ---------------------------------------------------------------------------
# 百分位 / 窗口 / 温度
# ---------------------------------------------------------------------------
def percentile(values: list[float], current: float | None) -> float | None:
    """当前值在序列中的百分位：小于当前值的占比 × 100。

    窗口内没有数据或当前值缺失时返回 None。
    """
    if current is None:
        return None
    clean = [v for v in values if v is not None]
    if not clean:
        return None
    return round(sum(1 for v in clean if v < current) / len(clean) * 100, 1)


def rolling_percentiles(
    points: list[dict[str, Any]],
    field: str,
    years: int | None = DEFAULT_WINDOW_YEARS,
) -> list[float | None]:
    """逐点计算滚动百分位（按日期窗口，含当前点）。

    ``years=None`` 表示全历史展开（每个点用其之前全部数据）；否则每个点
    只用其前 ``years`` 年内的数据。与 :func:`select_window` / :func:`percentile`
    口径一致，保证历史曲线最后一点与列表当前百分位相同。
    """
    dates = [_parse_date(point.get("date")) for point in points]
    values = [_safe_float(point.get(field)) for point in points]
    threshold = timedelta(days=365.25 * years) if years else None

    out: list[float | None] = []
    start = 0
    for index, current in enumerate(values):
        if threshold is not None:
            while start < index:
                current_date = dates[index]
                start_date = dates[start]
                if (
                    current_date is None
                    or start_date is None
                    or current_date - start_date <= threshold
                ):
                    break
                start += 1
        if current is None:
            out.append(None)
            continue
        window = [v for v in values[start : index + 1] if v is not None]
        out.append(round(sum(1 for v in window if v < current) / len(window) * 100, 1))
    return out


def select_window(
    points: list[dict[str, Any]], years: int = DEFAULT_WINDOW_YEARS
) -> tuple[str, list[dict[str, Any]]]:
    """按历史长度选择百分位窗口。

    历史跨度不足 ``years`` 年（或日期非法）→ ``("all", 全部点)``；
    否则返回最近 ``years`` 年窗口 ``("10y", 窗口点)``。
    """
    if not points:
        return "all", []
    first = _parse_date(points[0].get("date"))
    last = _parse_date(points[-1].get("date"))
    if first is None or last is None:
        return "all", list(points)
    if last - first < timedelta(days=365.25 * years):
        return "all", list(points)
    cutoff = last - timedelta(days=365.25 * years)
    window = [
        point
        for point in points
        if (_parse_date(point.get("date")) or last) >= cutoff
    ]
    return f"{years}y", window


def classify_temperature(pe_percentile: float | None) -> str:
    """按 PE(TTM) 百分位分档：<30 低估 low / 30–70 合理 fair / >70 高估 high。"""
    if pe_percentile is None:
        return "unknown"
    if pe_percentile < LOW_MAX:
        return "low"
    if pe_percentile > HIGH_MIN:
        return "high"
    return "fair"


# ---------------------------------------------------------------------------
# 估值结果
# ---------------------------------------------------------------------------
@dataclass
class IndexValuation:
    """单只宽基指数的估值快照。"""

    index_code: str
    index_name: str
    keyword: str = ""
    pe: float | None = None
    pe_percentile: float | None = None
    pb: float | None = None
    pb_percentile: float | None = None
    window: str = "10y"
    window_months: int = 0
    history_months: int = 0
    temperature: str = "unknown"
    data_date: str = ""
    updated_at: str = ""
    stale: bool = False
    source: str = "legulegu"
    ok: bool = True
    message: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "index_code": self.index_code,
            "index_name": self.index_name,
            "keyword": self.keyword,
            "pe": self.pe,
            "pe_percentile": self.pe_percentile,
            "pb": self.pb,
            "pb_percentile": self.pb_percentile,
            "window": self.window,
            "window_months": self.window_months,
            "history_months": self.history_months,
            "temperature": self.temperature,
            "data_date": self.data_date,
            "updated_at": self.updated_at,
            "stale": self.stale,
            "source": self.source,
            "ok": self.ok,
            "message": self.message,
        }


def build_valuation(
    meta: IndexMeta,
    points: list[dict[str, Any]],
    years: int = DEFAULT_WINDOW_YEARS,
    window_override: str | None = None,
    source: str = "legulegu",
) -> IndexValuation:
    """由月度 PE/PB 序列构建估值快照（自算百分位与温度）。"""
    ordered = sorted(
        [p for p in points if p.get("date")], key=lambda p: str(p["date"])
    )
    if not ordered:
        return _placeholder(meta, message="无可用估值历史", source=source)

    if window_override == "all":
        window, window_points = "all", list(ordered)
    else:
        window, window_points = select_window(ordered, years)

    pe_series = [_safe_float(p.get("pe")) for p in ordered]
    pb_series = [_safe_float(p.get("pb")) for p in ordered]
    current_pe = _last_value(pe_series)
    current_pb = _last_value(pb_series)

    pe_percentile = percentile(_values(window_points, "pe"), current_pe)
    pb_percentile = percentile(_values(window_points, "pb"), current_pb)

    return IndexValuation(
        index_code=meta.code,
        index_name=meta.name,
        keyword=meta.keyword,
        pe=round(current_pe, 2) if current_pe is not None else None,
        pe_percentile=pe_percentile,
        pb=round(current_pb, 2) if current_pb is not None else None,
        pb_percentile=pb_percentile,
        window=window,
        window_months=len(window_points),
        history_months=len(ordered),
        temperature=classify_temperature(pe_percentile),
        data_date=str(ordered[-1].get("date") or ""),
        updated_at=_now_iso(),
        stale=False,
        source=source,
    )


def _placeholder(
    meta: IndexMeta, message: str = "估值数据暂不可用", source: str = "legulegu"
) -> IndexValuation:
    """无缓存且抓取失败时的降级占位。"""
    return IndexValuation(
        index_code=meta.code,
        index_name=meta.name,
        keyword=meta.keyword,
        temperature="unknown",
        source=source,
        ok=False,
        message=message,
    )


def _from_row(
    meta: IndexMeta, row: dict[str, Any], stale: bool
) -> IndexValuation:
    return IndexValuation(
        index_code=meta.code,
        index_name=meta.name,
        keyword=meta.keyword,
        pe=_safe_float(row.get("pe")),
        pe_percentile=_safe_float(row.get("pe_percentile")),
        pb=_safe_float(row.get("pb")),
        pb_percentile=_safe_float(row.get("pb_percentile")),
        window=str(row.get("window") or "10y"),
        window_months=int(row.get("window_months") or 0),
        history_months=int(row.get("history_months") or 0),
        temperature=str(row.get("temperature") or "unknown"),
        data_date=str(row.get("data_date") or ""),
        updated_at=str(row.get("updated_at") or ""),
        stale=stale,
        source=str(row.get("source") or "legulegu"),
        ok=True,
    )


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _is_stale(row: dict[str, Any] | None, ttl_hours: float) -> bool:
    if not row:
        return True
    raw = str(row.get("updated_at") or "")
    try:
        updated = datetime.fromisoformat(raw)
    except ValueError:
        return True
    return datetime.now() - updated > timedelta(hours=ttl_hours)


# ---------------------------------------------------------------------------
# 数据源
# ---------------------------------------------------------------------------
class ValuationProvider:
    """估值数据源抽象；付费源（理杏仁/韭圈儿）可按此接口扩展。"""

    name = "legulegu"

    def fetch_history(self, meta: IndexMeta) -> list[dict[str, Any]] | None:
        """返回按日期升序的 ``[{"date","pe","pb"}, ...]``；失败返回 None（不抛出）。"""
        raise NotImplementedError


def merge_series(pe_df: Any, pb_df: Any) -> list[dict[str, Any]]:
    """合并乐咕 PE / PB 月度序列（按日期，缺失值前向填充）。"""
    pe_map: dict[str, float] = {}
    for _, row in pe_df.iterrows():
        date = _normalize_date(row.get("日期"))
        value = _safe_float(row.get("滚动市盈率"))
        if date and value is not None:
            pe_map[date] = value

    pb_map: dict[str, float] = {}
    for _, row in pb_df.iterrows():
        date = _normalize_date(row.get("日期"))
        value = _safe_float(row.get("市净率"))
        if date and value is not None:
            pb_map[date] = value

    points: list[dict[str, Any]] = []
    last_pe: float | None = None
    last_pb: float | None = None
    for date in sorted(set(pe_map) | set(pb_map)):
        last_pe = pe_map.get(date, last_pe)
        last_pb = pb_map.get(date, last_pb)
        points.append({"date": date, "pe": last_pe, "pb": last_pb})
    return points


class LeguleguValuationProvider(ValuationProvider):
    """乐咕乐股：PE(TTM) + PB 月度长历史（仅 12 宽基，反爬脆弱）。"""

    name = "legulegu"

    def fetch_history(self, meta: IndexMeta) -> list[dict[str, Any]] | None:
        try:
            import akshare as ak
        except Exception as exc:  # noqa: BLE001 - 依赖缺失时降级
            logger.warning("akshare 不可用，指数估值降级: %s", exc)
            return None
        try:
            pe_df = ak.stock_index_pe_lg(symbol=meta.lg_symbol)
            pb_df = ak.stock_index_pb_lg(symbol=meta.lg_symbol)
        except Exception as exc:  # noqa: BLE001 - 反爬/网络失败一律降级
            logger.warning("乐咕估值抓取失败 %s(%s): %s", meta.code, meta.lg_symbol, exc)
            return None
        points = merge_series(pe_df, pb_df)
        if not points:
            logger.warning("乐咕估值返回空数据 %s(%s)", meta.code, meta.lg_symbol)
            return None
        return points


_PROVIDER: ValuationProvider | None = None


def get_provider() -> ValuationProvider:
    """返回默认估值数据源（测试可 monkeypatch 本函数）。"""
    global _PROVIDER
    if _PROVIDER is None:
        _PROVIDER = LeguleguValuationProvider()
    return _PROVIDER


# ---------------------------------------------------------------------------
# 缓存读写 / 刷新
# ---------------------------------------------------------------------------
def _store(val: IndexValuation, points: list[dict[str, Any]]) -> None:
    """写入缓存表（主线程串行写，payload 保存原始月度序列供换窗口重算）。"""
    payload = json.dumps(
        [
            {
                "date": str(p.get("date") or ""),
                "pe": _safe_float(p.get("pe")),
                "pb": _safe_float(p.get("pb")),
            }
            for p in points
        ],
        ensure_ascii=False,
        separators=(",", ":"),
    )
    db.upsert_index_valuation(
        index_code=val.index_code,
        index_name=val.index_name,
        pe=val.pe,
        pe_percentile=val.pe_percentile,
        pb=val.pb,
        pb_percentile=val.pb_percentile,
        window=val.window,
        window_months=val.window_months,
        temperature=val.temperature,
        history_months=val.history_months,
        data_date=val.data_date,
        source=val.source,
        payload=payload,
        updated_at=val.updated_at,
    )


def _fetch_many(
    codes: list[str], provider: ValuationProvider, timeout: float
) -> dict[str, list[dict[str, Any]] | None]:
    """有界并发抓取；超时/异常的单只返回 None（由调用方降级）。"""
    if not codes:
        return {}
    results: dict[str, list[dict[str, Any]] | None] = {}
    executor = ThreadPoolExecutor(max_workers=min(_MAX_WORKERS, len(codes)))
    try:
        futures = {
            executor.submit(provider.fetch_history, INDEX_BY_CODE[code]): code
            for code in codes
        }
        wait(set(futures), timeout=timeout)
        for future, code in futures.items():
            if not future.done():
                logger.warning("指数估值抓取超时 %s", code)
                results[code] = None
                continue
            try:
                results[code] = future.result()
            except Exception as exc:  # noqa: BLE001 - 单只失败不影响整页
                logger.warning("指数估值抓取异常 %s: %s", code, exc)
                results[code] = None
    finally:
        executor.shutdown(wait=False, cancel_futures=True)
    return results


def list_valuations(
    refresh: bool = False,
    provider: ValuationProvider | None = None,
    ttl_hours: float = TTL_HOURS,
    timeout: float = REFRESH_TIMEOUT,
    codes: list[str] | None = None,
) -> list[IndexValuation]:
    """返回宽基估值列表。

    缓存未过期直接返回；过期/为空时并发刷新，失败保留旧值并标 ``stale``，
    无旧值则降级为 ``ok=False``（不抛异常）。
    """
    metas = (
        [INDEX_BY_CODE[c] for c in codes if c in INDEX_BY_CODE]
        if codes
        else list(INDEX_REGISTRY)
    )
    rows = {row["index_code"]: dict(row) for row in db.get_index_valuations()}
    need = [
        meta.code
        for meta in metas
        if refresh or _is_stale(rows.get(meta.code), ttl_hours)
    ]
    fetched = _fetch_many(need, provider or get_provider(), timeout) if need else {}

    results: list[IndexValuation] = []
    for meta in metas:
        points = fetched.get(meta.code)
        if points:
            val = build_valuation(meta, points)
            _store(val, points)
            results.append(val)
            continue
        row = rows.get(meta.code)
        if row is not None:
            results.append(_from_row(meta, row, stale=_is_stale(row, ttl_hours)))
        else:
            results.append(_placeholder(meta))
    return results


def history_points(
    points: list[dict[str, Any]], window: str = "10y"
) -> list[dict[str, Any]]:
    """生成历史曲线数据（原始 PE/PB + 按日期窗口的滚动百分位）。"""
    ordered = sorted(
        [p for p in points if p.get("date")], key=lambda p: str(p["date"])
    )
    if not ordered:
        return []
    years = DEFAULT_WINDOW_YEARS if window == "10y" else None
    pe_pcts = rolling_percentiles(ordered, "pe", years)
    pb_pcts = rolling_percentiles(ordered, "pb", years)
    return [
        {
            "date": str(point.get("date") or ""),
            "pe": _safe_float(point.get("pe")),
            "pb": _safe_float(point.get("pb")),
            "pe_percentile": pe_pct,
            "pb_percentile": pb_pct,
        }
        for point, pe_pct, pb_pct in zip(ordered, pe_pcts, pb_pcts)
    ]


def get_history(
    code: str,
    window: str | None = None,
    provider: ValuationProvider | None = None,
    ttl_hours: float = TTL_HOURS,
    timeout: float = REFRESH_TIMEOUT,
) -> dict[str, Any] | None:
    """单只指数估值历史（含滚动百分位）。

    未知代码返回 None；已知代码但无数据返回 ``ok=False`` 的降级结构。
    """
    meta = INDEX_BY_CODE.get(code)
    if meta is None:
        return None

    row = db.get_index_valuation(code)
    row = dict(row) if row else None
    if row is None or _is_stale(row, ttl_hours):
        fetched = _fetch_many(
            [code], provider or get_provider(), timeout
        ).get(code)
        if fetched:
            val = build_valuation(meta, fetched)
            _store(val, fetched)
            win = window if window in ("10y", "all") else val.window
            return {
                "ok": True,
                "index": val.to_dict(),
                "points": history_points(fetched, win),
            }

    if row is None:
        return {
            "ok": False,
            "index": _placeholder(meta).to_dict(),
            "points": [],
        }

    payload = json.loads(row.get("payload") or "[]")
    win = window if window in ("10y", "all") else str(row.get("window") or "10y")
    return {
        "ok": True,
        "index": _from_row(meta, row, stale=_is_stale(row, ttl_hours)).to_dict(),
        "points": history_points(payload, win),
    }


# ---------------------------------------------------------------------------
# 跟踪基金
# ---------------------------------------------------------------------------
def tracking_funds(meta: IndexMeta, limit: int = 20) -> list[dict[str, Any]]:
    """按关键词从全市场基金池匹配跟踪该指数的基金（名称子串匹配）。"""
    try:
        from . import fund_filter
        from .fetch_fund import _classify_index

        universe = fund_filter.load_fund_universe()
    except Exception as exc:  # noqa: BLE001 - 池加载失败不影响估值主流程
        logger.warning("跟踪基金池加载失败: %s", exc)
        return []

    keyword = meta.keyword
    results: list[dict[str, Any]] = []
    for fund in universe:
        name = str(fund.get("name") or "")
        if not keyword or keyword not in name:
            continue
        if any(excluded in name for excluded in meta.exclude):
            continue
        fund_type = str(fund.get("type") or "")
        results.append(
            {
                "code": str(fund.get("code") or ""),
                "name": name,
                "type": fund_type,
                "sector": str(fund.get("sector") or ""),
                "index_tag": _classify_index(name, fund_type),
            }
        )
        if len(results) >= limit:
            break
    return results
