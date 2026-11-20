"""指数估值（宽基 PE/PB 百分位 + 估值温度）。

数据源（主）：韭圈儿 ``pre.jiucaishuo.com/v4/open-ai/index-data``，免鉴权
JSON POST，单请求返回单只指数的每日 PE/PB/ROE 完整历史（2008 年至今
约 2600+ 点，12 个宽基全覆盖，含深证 399 系）；失败时回退乐咕乐股
（akshare ``stock_index_pe_lg`` / ``stock_index_pb_lg``，月度历史）。
上游不直接提供百分位，本模块用历史序列自算。

选型背景：乐咕对服务器 IP 整站 504（频控封禁）且免费端点在收紧，
韭圈儿实测服务器/本地均可达；韭圈儿接口为纯 JSON（无 V8/无 lxml），
彻底规避原生并发崩溃风险，故提为主源。蛋卷（9/12、无历史）与中证
官方文件（无 PB、仅近 20 日）留作后备选项未接入。

设计边界：

- 只做宽基：行业/主题指数无免费 PE+PB 历史源（中证源仅近 20 日 PE 快照）。
- 百分位默认近 10 年（历史不足 10 年用全历史并标注）；窗口直接改变结论，
  UI 必须标注口径。
- 上游反爬/可用性脆弱：缓存 + stale-if-error + 单只降级，绝不阻塞其他页面。
- akshare 用 PyMiniRacer(V8) 解 JS token，V8 非线程安全：py_mini_racer
  由 `ak_compat._ensure_v8_serialized()` 做进程级串行（覆盖乐咕/新浪/
  交易日历等所有 V8 使用方）；本模块另加单 worker 串行 + 最小请求间隔 +
  退避重试，满足反爬限速的同时绝不并发撞 V8（韭圈儿为直连 requests
  POST，不涉及 V8/lxml，但仍走同一串行队列与限速）。
- 请求只做有界等待（列表 10s），超时项转后台继续抓取并逐只落库，
  前端在 `refreshing=true` 时轮询渐进填充。
- 旧版 akshare（≤1.18.x）乐咕请求不带 timeout，上游挂起会永远阻塞：
  本模块给未显式指定 timeout 的 requests 调用注入默认超时 (10s, 30s)。
- 失败冷却：单只抓取失败后 5 分钟内不再自动重提（手动刷新/展开历史除外），
  否则上游不可达时每次轮询都重提失败项，队列永远不空、页面永远「刷新中」。
- 全站熔断：连续失败达阈值（如上游 WAF 封禁服务器 IP、整站 504）后全局
  静默 1 小时不再自动抓取——仅靠单只 5 分钟冷却仍会每 5 分钟打一轮请求，
  可能让频控封禁一直续期。手动刷新/展开历史可穿透，任一成功立即恢复。
- 温度以 PE(TTM) 百分位分档；PB 百分位并列展示。仅供参考，非投资建议。
"""

from __future__ import annotations

import json
import logging
import threading
import time
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor, wait
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from . import ak_compat, db

logger = logging.getLogger(__name__)

TTL_HOURS = 24.0
DEFAULT_WINDOW_YEARS = 10
REFRESH_TIMEOUT = 20.0
LIST_REFRESH_TIMEOUT = 10.0

# 乐咕反爬约束（实测）：akshare 用 PyMiniRacer(V8) 解 JS token，V8 非线程安全，
# 多线程并发会让进程直接 SIGTRAP；上游对突发请求还会返回 429/504。
# 因此所有乐咕调用必须串行，并保持请求间隔 + 退避重试。
_REQUEST_INTERVAL = 1.5  # 两次上游请求的最小间隔（秒）
_MAX_ATTEMPTS = 3
_RETRY_BACKOFF = (4.0, 8.0)  # 第 1/2 次失败后的等待（秒）

# _V8_LOCK 串行乐咕域内的「请求间隔 + 调用」；实际 akshare 调用另嵌套
# ak_compat.serialized()（进程级全生命周期锁），把 V8 上下文的创建/销毁与
# 其余 V8 使用方（交易日历等）统一到同一把锁，防跨锁域销毁竞态。
_V8_LOCK = threading.Lock()
_last_request_ts = 0.0

# 韭圈儿历史估值接口（免鉴权，服务器/本地实测可达）：
# POST https://pre.jiucaishuo.com/v4/open-ai/index-data
#   {"code":"000300.SH","start_time":"2008-01-01"}
# → {"code":0,"data":[["日期","收盘价","pe","pb","roe"],[...日度行...]]}
# 单请求返回单只指数完整历史（升序）；纯 JSON，无 V8/lxml 原生崩溃风险。
# 实测连发数十次无限流；仍与乐咕共用同一串行队列 + 最小间隔，礼貌限速。
_JQ_API_URL = "https://pre.jiucaishuo.com/v4/open-ai/index-data"
_JQ_HEADERS = {
    "Content-Type": "application/json",
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/101.0.4951.64 Safari/537.36"
    ),
}
_JQ_START = "2008-01-01"  # 上游最早数据；换取全窗口灵活性
_JQ_TIMEOUT = (10.0, 30.0)  # (连接, 读取) 秒
_JQ_MAX_ATTEMPTS = 2  # API 无反爬：1 次重试足够，限制回退链总耗时

# 旧版 akshare（如曾钉住的 1.18.82）乐咕请求不带 timeout：
# 上游挂起/网络不可达时请求会永远阻塞，串行队列卡死在第一只指数，
# 前端一直显示「刷新中」却永远没有数据。给未显式指定 timeout 的 requests
# 调用注入默认超时兜底（新版 akshare 自带 timeout，不受影响）。
_HTTP_TIMEOUT = (10.0, 30.0)  # (连接, 读取) 秒
_timeout_patched = False

# 单只最近一次抓取失败原因（供降级占位透出到 UI，便于定位网络/反爬问题）
_last_errors: dict[str, str] = {}

# 失败冷却：上游不可达时若每次请求都重提刚失败的指数，串行队列永远不空，
# refreshing 永远为 true（页面永远「刷新中」）。失败后冷却期内不再自动重提，
# 让页面落定为降级态；手动刷新（refresh=true）与展开单只历史不受冷却限制。
_FAILURE_COOLDOWN = 300.0  # 秒
_last_failed_at: dict[str, float] = {}

# 全站熔断：单只冷却挡不住「整站不可用」——12 只全失败时，每 5 分钟冷却
# 到期仍会重提一整轮（12 只 × 重试 3 次），高频请求可能让上游频控封禁
# 一直续期（实测乐咕对服务器 IP 整站 504）。连续失败（跨指数累计）达到
# 阈值后全局静默 1 小时，让 IP 真正冷却；期间自动请求（含前端轮询）不再
# 触碰上游。手动刷新与展开单只历史可穿透；任一只成功立即合闸恢复。
# 写入只发生在单 worker 线程，读取在 HTTP 线程（float 赋值原子，无需加锁）。
_BREAKER_THRESHOLD = 6  # 连续失败次数
_BREAKER_COOLDOWN = 3600.0  # 秒
_breaker_until = 0.0
_consecutive_failures = 0


def _note_failure() -> None:
    global _consecutive_failures, _breaker_until
    _consecutive_failures += 1
    if _consecutive_failures >= _BREAKER_THRESHOLD:
        _breaker_until = time.monotonic() + _BREAKER_COOLDOWN


def _note_success() -> None:
    global _consecutive_failures, _breaker_until
    _consecutive_failures = 0
    _breaker_until = 0.0


def _ensure_requests_timeout() -> None:
    """幂等地给 requests 注入默认超时（仅对未显式传 timeout 的调用生效）。"""
    global _timeout_patched
    if _timeout_patched:
        return
    import requests

    original = requests.Session.request

    def request_with_timeout(self: Any, method: str, url: str, **kwargs: Any) -> Any:
        kwargs.setdefault("timeout", _HTTP_TIMEOUT)
        return original(self, method, url, **kwargs)

    requests.Session.request = request_with_timeout  # type: ignore[method-assign]
    _timeout_patched = True


def _record_error(code: str, exc: Exception | str) -> None:
    _last_errors[code] = str(exc)[:200]

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


def _span_months(points: list[dict[str, Any]]) -> int:
    """序列首末日期覆盖的月数（含首尾月）；无有效日期返回 0。

    源频率无关：乐咕月频 150 点 ≈ 150 个月，韭圈儿日频 2640 点 ≈ 227 个月。
    直接拿点数当「月数」会让日频源显示成几千个月，故按日期跨度计算。
    """
    if not points:
        return 0
    first = _parse_date(points[0].get("date"))
    last = _parse_date(points[-1].get("date"))
    if not first or not last:
        return 0
    return max(0, (last.year - first.year) * 12 + (last.month - first.month) + 1)


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
        window_months=_span_months(window_points),
        history_months=_span_months(ordered),
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


def _lg_call(fn: Callable[..., Any], symbol: str) -> Any:
    """串行调用乐咕接口：V8 锁 + 最小请求间隔 + 指数退避重试。

    实际调用嵌套 ``ak_compat.serialized()``：V8 上下文「构造→执行→销毁」
    整段持进程级锁，与其余 V8 使用方（交易日历等）串行；间隔等待/退避 sleep
    保持在 serialized() 之外，不持锁空等。
    """
    global _last_request_ts
    _ensure_requests_timeout()
    last_exc: Exception | None = None
    for attempt in range(_MAX_ATTEMPTS):
        with _V8_LOCK:
            delay = _REQUEST_INTERVAL - (time.monotonic() - _last_request_ts)
            if delay > 0:
                time.sleep(delay)
            try:
                with ak_compat.serialized():
                    result = fn(symbol=symbol)
            except Exception as exc:  # noqa: BLE001 - 429/网络错误统一重试
                last_exc = exc
            else:
                _last_request_ts = time.monotonic()
                return result
            _last_request_ts = time.monotonic()
        if attempt < _MAX_ATTEMPTS - 1:
            backoff = _RETRY_BACKOFF[min(attempt, len(_RETRY_BACKOFF) - 1)]
            if backoff > 0:
                time.sleep(backoff)
    raise last_exc  # type: ignore[misc]


def _jq_symbol(code: str) -> str:
    """纯数字指数代码 → 韭圈儿 ``代码.交易所`` 后缀。

    实测规则：000xxx（沪市/中证系列）→ ``.SH``；399xxx（深市）→ ``.SZ``。
    例：000300 → 000300.SH；399330 → 399330.SZ。
    """
    return f"{code}.SZ" if code.startswith("399") else f"{code}.SH"


def _parse_jq_points(data: Any) -> list[dict[str, Any]]:
    """解析韭圈儿二维表 → ``[{"date","pe","pb"}, ...]``（按日期升序）。

    表形态：首行表头 ``["日期","收盘价","pe","pb","roe"]``，其后为日度行，
    日期已为 ``YYYY-MM-DD`` 字符串。pe/pb 非法或 ≤0 记为 None（百分位计算跳过）。
    """
    if not isinstance(data, list) or len(data) < 2:
        return []
    header = [str(h) for h in data[0]]
    try:
        i_date, i_pe, i_pb = header.index("日期"), header.index("pe"), header.index("pb")
    except ValueError:
        return []
    points: list[dict[str, Any]] = []
    for row in data[1:]:
        if not isinstance(row, list) or len(row) <= max(i_date, i_pe, i_pb):
            continue
        date = _normalize_date(row[i_date])
        if not date:
            continue
        pe = _safe_float(row[i_pe])
        pb = _safe_float(row[i_pb])
        # 韭圈儿停牌/异常日会给 0，视为缺失（否则会污染历史百分位）
        points.append({
            "date": date,
            "pe": pe if pe is not None and pe > 0 else None,
            "pb": pb if pb is not None and pb > 0 else None,
        })
    points.sort(key=lambda p: p["date"])
    return points


def _jq_call(meta: IndexMeta) -> list[dict[str, Any]]:
    """请求韭圈儿单只指数历史：共用串行限速间隔 + 轻量重试。

    纯 JSON POST（无 V8/lxml），仍与乐咕共用 ``_last_request_ts`` 限制
    最小请求间隔，避免多源并发突发。失败抛出，由 Provider 转降级。
    """
    global _last_request_ts
    import requests

    last_exc: Exception | None = None
    for attempt in range(_JQ_MAX_ATTEMPTS):
        delay = _REQUEST_INTERVAL - (time.monotonic() - _last_request_ts)
        if delay > 0:
            time.sleep(delay)
        try:
            resp = requests.post(
                _JQ_API_URL,
                json={"code": _jq_symbol(meta.code), "start_time": _JQ_START},
                headers=_JQ_HEADERS,
                timeout=_JQ_TIMEOUT,
            )
            _last_request_ts = time.monotonic()
            resp.raise_for_status()
            payload = resp.json()
            if payload.get("code") not in (0, None):
                raise RuntimeError(f"上游返回错误: {payload.get('message') or payload}")
            points = _parse_jq_points(payload.get("data"))
            if not points:
                raise RuntimeError("韭圈儿返回空数据")
            return points
        except Exception as exc:  # noqa: BLE001 - 网络/结构错误统一重试
            _last_request_ts = time.monotonic()
            last_exc = exc
        if attempt < _JQ_MAX_ATTEMPTS - 1:
            time.sleep(2.0)
    raise last_exc  # type: ignore[misc]


class LeguleguValuationProvider(ValuationProvider):
    """乐咕乐股：PE(TTM) + PB 月度长历史（仅 12 宽基，反爬脆弱）。"""

    name = "legulegu"

    def fetch_history(self, meta: IndexMeta) -> list[dict[str, Any]] | None:
        try:
            import akshare as ak
        except Exception as exc:  # noqa: BLE001 - 依赖缺失时降级
            logger.warning("akshare 不可用，指数估值降级: %s", exc)
            _record_error(meta.code, exc)
            return None
        try:
            pe_df = _lg_call(ak.stock_index_pe_lg, meta.lg_symbol)
            pb_df = _lg_call(ak.stock_index_pb_lg, meta.lg_symbol)
        except Exception as exc:  # noqa: BLE001 - 反爬/网络失败一律降级
            logger.warning("乐咕估值抓取失败 %s(%s): %s", meta.code, meta.lg_symbol, exc)
            _record_error(meta.code, exc)
            return None
        points = merge_series(pe_df, pb_df)
        if not points:
            logger.warning("乐咕估值返回空数据 %s(%s)", meta.code, meta.lg_symbol)
            _record_error(meta.code, "上游返回空数据")
            return None
        _last_errors.pop(meta.code, None)
        return points


_PROVIDER: ValuationProvider | None = None


class JiucaishuoValuationProvider(ValuationProvider):
    """韭圈儿：每日 PE/PB 完整历史（2008 至今），12 宽基全覆盖（主源）。"""

    name = "jiucaishuo"

    def fetch_history(self, meta: IndexMeta) -> list[dict[str, Any]] | None:
        try:
            points = _jq_call(meta)
        except Exception as exc:  # noqa: BLE001 - 网络/结构失败一律降级
            logger.warning("韭圈儿估值抓取失败 %s(%s): %s", meta.code, _jq_symbol(meta.code), exc)
            _record_error(meta.code, f"韭圈儿: {exc}")
            return None
        _last_errors.pop(meta.code, None)
        return points


class FallbackValuationProvider(ValuationProvider):
    """主源失败自动回退备用源；``name`` 记录实际产出数据的源（供落库标注）。"""

    name = "fallback"

    def __init__(self, primary: ValuationProvider, secondary: ValuationProvider) -> None:
        self.primary = primary
        self.secondary = secondary

    def fetch_history(self, meta: IndexMeta) -> list[dict[str, Any]] | None:
        for provider in (self.primary, self.secondary):
            points = provider.fetch_history(meta)
            if points:
                # 实例属性覆盖类属性：落库 source 如实记录本次数据来源
                self.name = provider.name
                return points
        self.name = self.primary.name
        return None


def get_provider() -> ValuationProvider:
    """返回默认估值数据源（测试可 monkeypatch 本函数）。

    韭圈儿为主源（服务器实测可达、12/12 覆盖、纯 JSON 无原生崩溃风险）；
    乐咕为备用源（本地可用、反爬脆弱，仅供韭圈儿失败时兜底）。
    """
    global _PROVIDER
    if _PROVIDER is None:
        _PROVIDER = FallbackValuationProvider(
            JiucaishuoValuationProvider(),
            LeguleguValuationProvider(),
        )
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


# 单 worker 串行队列：既满足乐咕的串行/限流要求，也天然避免重复抓取；
# 任务内部逐只落库，HTTP 请求超时后仍在后台继续，下次调用即可读到。
_EXECUTOR = ThreadPoolExecutor(max_workers=1, thread_name_prefix="valuation")
_inflight: dict[str, Future] = {}
_inflight_lock = threading.Lock()


def _fetch_and_store(
    code: str, provider: ValuationProvider
) -> tuple[IndexValuation, list[dict[str, Any]]] | None:
    """抓取单只并立即落库（后台继续完成时也能被下次请求读到）。"""
    global _current_code
    meta = INDEX_BY_CODE[code]
    _current_code = code
    try:
        try:
            points = provider.fetch_history(meta)
        except Exception as exc:  # noqa: BLE001 - 记录原因后交由上层降级
            _record_error(code, exc)
            _last_failed_at[code] = time.monotonic()
            _note_failure()
            raise
        if not points:
            _last_failed_at[code] = time.monotonic()
            _note_failure()
            return None
        val = build_valuation(meta, points, source=provider.name)
        _store(val, points)
        _last_errors.pop(code, None)
        _last_failed_at.pop(code, None)
        _note_success()
        return val, points
    finally:
        _current_code = None


def _submit_missing(
    codes: list[str], provider: ValuationProvider, force: bool = False
) -> dict[str, Future]:
    """复用已在途任务，只为缺失代码提交新任务（单飞，避免重复抓取）。

    冷却期内刚失败的代码不再自动重提（``force=True`` 除外），
    防止上游不可达时队列永远不空、页面永远「刷新中」。
    全站熔断打开期间（连续失败达阈值）自动请求整体静默，
    不再触碰上游；``force=True``（手动刷新/展开历史）可穿透。
    """
    futures: dict[str, Future] = {}
    now = time.monotonic()
    if not force and now < _breaker_until:
        return futures
    with _inflight_lock:
        for code in codes:
            future = _inflight.get(code)
            if future is not None and not future.done():
                futures[code] = future
                continue
            _inflight.pop(code, None)
            failed_at = _last_failed_at.get(code)
            if (
                not force
                and failed_at is not None
                and now - failed_at < _FAILURE_COOLDOWN
            ):
                continue
            future = _EXECUTOR.submit(_fetch_and_store, code, provider)
            _inflight[code] = future
            futures[code] = future
    return futures


def is_refreshing() -> bool:
    """是否有后台抓取仍在进行（前端据此轮询进度）。"""
    with _inflight_lock:
        for code, future in list(_inflight.items()):
            if future.done():
                _inflight.pop(code, None)
        return bool(_inflight)


# 单 worker 当前正在抓取的指数代码（任务间隙为 None）
_current_code: str | None = None


def refresh_progress() -> dict[str, Any]:
    """后台刷新进度快照（前端展示「当前正在做什么」）。

    ``remaining`` 为排队+在抓的任务数；``current`` 为正在抓取的指数名；
    ``failed`` 为最近一次抓取失败且尚未成功的指数数。
    """
    with _inflight_lock:
        for code, future in list(_inflight.items()):
            if future.done():
                _inflight.pop(code, None)
        remaining = len(_inflight)
    current = _current_code
    meta = INDEX_BY_CODE.get(current) if current else None
    return {
        "total": len(INDEX_REGISTRY),
        "remaining": remaining,
        "current": meta.name if meta else None,
        "current_code": current,
        "failed": len(_last_failed_at),
    }


def _fetch_many(
    codes: list[str], provider: ValuationProvider, timeout: float, force: bool = False
) -> dict[str, tuple[IndexValuation, list[dict[str, Any]]] | None]:
    """有界等待：返回已完成的结果；超时项留在后台继续抓取并落库。"""
    if not codes:
        return {}
    futures = _submit_missing(codes, provider, force=force)
    wait(set(futures.values()), timeout=timeout)
    results: dict[str, tuple[IndexValuation, list[dict[str, Any]]] | None] = {}
    for code, future in futures.items():
        if not future.done():
            results[code] = None
            continue
        try:
            results[code] = future.result()
        except Exception as exc:  # noqa: BLE001 - 单只失败不影响整页
            logger.warning("指数估值抓取异常 %s: %s", code, exc)
            results[code] = None
        finally:
            with _inflight_lock:
                if _inflight.get(code) is future:
                    _inflight.pop(code, None)
    return results


def list_valuations(
    refresh: bool = False,
    provider: ValuationProvider | None = None,
    ttl_hours: float = TTL_HOURS,
    timeout: float = LIST_REFRESH_TIMEOUT,
    codes: list[str] | None = None,
) -> list[IndexValuation]:
    """返回宽基估值列表。

    缓存未过期直接返回；过期/为空时抓取，最多等待 ``timeout`` 秒：
    已完成的立即返回，超时项转后台继续抓取（逐只落库），下次调用即可见。
    抓取失败保留旧值并标 ``stale``，无旧值则降级为 ``ok=False``（不抛异常）。
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
    fetched = (
        _fetch_many(need, provider or get_provider(), timeout, force=refresh)
        if need
        else {}
    )
    if fetched:
        # 后台任务可能已写入新行，重新读取以便未完成项拿到最新缓存
        rows = {row["index_code"]: dict(row) for row in db.get_index_valuations()}

    results: list[IndexValuation] = []
    for meta in metas:
        result = fetched.get(meta.code)
        if result:
            results.append(result[0])
            continue
        row = rows.get(meta.code)
        if row is not None:
            results.append(_from_row(meta, row, stale=_is_stale(row, ttl_hours)))
        else:
            results.append(
                _placeholder(meta, message=_last_errors.get(meta.code) or "估值数据暂不可用")
            )
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
        # 展开单只是用户显式动作，不受失败冷却限制
        fetched = _fetch_many(
            [code], provider or get_provider(), timeout, force=True
        ).get(code)
        if fetched:
            val, points = fetched
            win = window if window in ("10y", "all") else val.window
            return {
                "ok": True,
                "index": val.to_dict(),
                "points": history_points(points, win),
            }
        # 超时的任务可能刚在后台落库，回读一次
        refreshed = db.get_index_valuation(code)
        if refreshed is not None:
            row = dict(refreshed)

    if row is None:
        return {
            "ok": False,
            "index": _placeholder(
                meta, message=_last_errors.get(code) or "估值数据暂不可用"
            ).to_dict(),
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
