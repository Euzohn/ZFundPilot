"""基金分红数据抓取与检测。"""
import logging
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, replace
from datetime import datetime, timedelta

from . import ak_compat, analysis, config, db, notification_service
from .models import ACTION_DIVIDEND, ACTION_REINVEST

logger = logging.getLogger(__name__)

# 按基金缓存分红历史，TTL 6 小时（日内不变）
_DIV_CACHE: dict[str, dict] = {}
_DIV_CACHE_TTL = 6 * 3600

# 「源确认无分红」（空表 / No tables found）回退 stale 缓存的最大时效：
# 缓存超过此时效则视为真正空（返回 []），让 _cleanup_stale_alerts 能清掉
# 源数据修正后残留的幽灵提醒。无上限回退曾把幽灵「养永生」：坏数据一旦
# 入缓存，源修正为空后每次抓取仍回退坏缓存，fetched_ex_dates 永远含幽灵
# 记录、清理永不触发（如 019172 摩根纳斯达克100 的假 2026-11-30 分红）。
# 必须 > 扫描周期（每日）：有效分红每天非空抓取会刷新缓存（始终受保护），
# 单次瞬时空响应命中昨日缓存仍回退；只有幽灵的缓存会老化超限被放行清理。
_STALE_FALLBACK_MAX_AGE = 48 * 3600

# 检测窗口：最近 N 天的分红事件
_LOOKBACK_DAYS = 90

# 分红抓取线程数：必须为 1（串行）。
# akshare fund_open_fund_info_em('分红送配详情') 每次调用都会：
#   1) 无条件下载整份 pingzhongdata/{code}.js 并在 mini_racer(V8) 里 eval
#      ——本模块已导入 ak_compat（V8 类级进程锁生效），且整段调用另持
#      ak_compat.serialized() 全生命周期锁（含上下文销毁，防并发创建+销毁竞态）；
#   2) 用 pd.read_html(StringIO(...)) 解析分红页表格（lxml/libxml2），
#      lxml 解析并发线程不安全，实测服务器（V8 锁已生效）3 线程并发仍
#      SIGSEGV（退出码 139），单次调用 exit=0。
# 串行同时消除两条原生并发路径。分红检测是后台低频任务（缓存 6h），
# 串行 N×~1s 完全可接受。改动前先看 CHANGELOG「分红检测崩溃循环」条目。
_MAX_WORKERS = 1

# 最近一次 check_dividends 清理的幽灵提醒数量（供 scan 端点读取）
_last_cleanup_count: int = 0


def _match_col(columns, candidates) -> str | None:
    """在 DataFrame 列中模糊匹配候选名。"""
    cols = list(columns)
    for cand in candidates:
        for c in cols:
            if cand in str(c).lower() or cand in str(c):
                return c
    return None


@dataclass
class DividendEvent:
    """单条分红事件。"""
    fund_code: str
    fund_name: str
    record_date: str       # 权益登记日
    ex_date: str           # 除息日
    per_share: float       # 每份分红(元/份)
    pay_date: str          # 分红发放日
    held_shares: float = 0.0       # 当前持仓份额（按渠道拆分）
    estimated_amount: float = 0.0  # 预估分红金额 = held_shares × per_share
    dividend_method: str = "cash"  # 基金的默认分红方式
    channel: str = ""              # 购买渠道（同一基金多渠道各出一条事件）
    already_recorded: bool = False  # 是否已有对应渠道的交易


def _fetch_fund_dividends(fund_code: str) -> list[dict] | None:
    """获取单只基金的完整分红历史（带缓存）。

    返回值区分「失败」与「真正无分红」：
    - None：抓取失败且无可用缓存。调用方不得把该基金视为「已成功抓取」，
      否则瞬时失败会被当成「无分红」，_cleanup_stale_alerts 会误把其
      pending 提醒全部 ignored（ignored 后不再重建，提醒永久丢失）。
    - []：上游确认无分红记录（空表/空响应）。
    - 抓取失败或空响应时，缓存仍在 _STALE_FALLBACK_MAX_AGE 内则回退 stale
      数据避免瞬时抖动；空响应且缓存已老化则视为真正空（放行幽灵清理）。
    """
    now = time.time()
    cached = _DIV_CACHE.get(fund_code)
    if cached and now - cached["ts"] < _DIV_CACHE_TTL:
        return cached["data"]

    try:
        import akshare as ak
        # 整段调用持进程序列化锁（含 V8 上下文销毁），见 ak_compat.serialized。
        with ak_compat.serialized():
            df = ak.fund_open_fund_info_em(symbol=fund_code, indicator="分红送配详情")
        if df is None or df.empty:
            # 空响应：缓存仍新鲜则回退，避免瞬时空响应被当成「无分红」；
            # 缓存老化则视为源已确认无分红，放行幽灵清理（见常量注释）
            if cached and now - cached["ts"] < _STALE_FALLBACK_MAX_AGE:
                return cached["data"]
            return []
        records = df.to_dict("records")
        _DIV_CACHE[fund_code] = {"ts": now, "data": records}
        return records
    except Exception as e:
        msg = str(e)
        if "no text parsed" in msg or "No tables found" in msg:
            # 上游明确返回空表：该基金无分红记录，属「真正空」而非失败
            logger.debug("[fetch_dividend] %s 无分红记录（空响应）", fund_code)
            if cached and now - cached["ts"] < _STALE_FALLBACK_MAX_AGE:
                return cached["data"]
            return []
        logger.warning("[fetch_dividend] 获取 %s 分红数据失败: %s", fund_code, e)
        if cached:
            return cached["data"]
        return None


def _parse_per_share(raw) -> float | None:
    """从分红金额字段解析每股分红(元/份)。

    AkShare 返回格式如 "每10份派现金0.0500元"，需提取 0.0500 并 /10。
    fund_fh_em 接口可能返回纯 float 如 0.0100，直接使用。
    """
    if isinstance(raw, (int, float)):
        v = float(raw)
        return v if v > 0 else None
    s = str(raw).strip()
    m = re.search(r"现金(\d+\.?\d*)\s*元", s)
    if not m:
        m = re.search(r"(\d+\.?\d+)\s*元", s)
    if m:
        amount = float(m.group(1))
        if "10" in s[:5]:
            amount /= 10
        return amount if amount > 0 else None
    # fallback: 纯数字字符串
    try:
        v = float(s)
        return v if v > 0 else None
    except ValueError:
        return None


def _parse_dividend_row(row: dict, fund_code: str, fund_name: str) -> DividendEvent | None:
    """解析单行分红数据为 DividendEvent。列名模糊匹配。"""
    col_record = _match_col(row.keys(), ["权益登记日", "登记日"])
    col_ex = _match_col(row.keys(), ["除息日", "除息日期"])
    col_per = _match_col(row.keys(), ["每10份分红", "每份分红", "分红"])
    col_pay = _match_col(row.keys(), ["分红发放日", "发放日"])
    if not col_ex or not col_per:
        return None
    per_share = _parse_per_share(row.get(col_per, 0))
    if not per_share:
        return None
    return DividendEvent(
        fund_code=fund_code,
        fund_name=fund_name,
        record_date=str(row.get(col_record, "")).strip()[:10],
        ex_date=str(row.get(col_ex, "")).strip()[:10],
        per_share=per_share,
        pay_date=str(row.get(col_pay, "")).strip()[:10],
    )


def _date_close(d1: str, d2: str, tolerance: int = 3) -> bool:
    """判断两个日期字符串是否在 tolerance 天内。"""
    try:
        date1 = datetime.strptime(d1[:10], "%Y-%m-%d")
        date2 = datetime.strptime(d2[:10], "%Y-%m-%d")
        return abs((date1 - date2).days) <= tolerance
    except (ValueError, TypeError):
        return False


def _cleanup_stale_alerts(
    fetched_ex_dates: set[tuple[str, str, str]],
    fetched_funds: set[str],
) -> int:
    """校验 pending 分红提醒是否仍存在于源数据中，不存在则标记为 ignored。

    提醒按 (基金, 除息日, 渠道) 逐条判定，两层清理：
    1. fetched_funds 中的基金：源数据无此 (ex_date, channel) → ignored
       （幽灵数据清理；旧库无渠道的提醒会在多渠道/渠道变化时按渠道重建）
    2. pending 超 _LOOKBACK_DAYS 天：自动 ignore（兜底，覆盖基金已清仓/
       抓取持续失败/缓存返回旧数据等场景）

    返回清理数量。
    """
    pending = db.get_dividend_alerts(status="pending")
    now = datetime.now(config.TIMEZONE)
    cutoff = now - timedelta(days=_LOOKBACK_DAYS)
    cleaned = 0
    for alert in pending:
        code = alert["fund_code"]
        ex_date = alert.get("ex_date", "")
        channel = alert.get("channel") or ""
        # --- 兜底：pending 超 90 天 → 自动 ignore ---
        created = alert.get("created_at", "")
        if created:
            try:
                created_dt = datetime.fromisoformat(created)
                if created_dt.tzinfo is None:
                    created_dt = created_dt.replace(tzinfo=config.TIMEZONE)
                if created_dt < cutoff:
                    db.update_dividend_alert(
                        alert["id"],
                        status="ignored",
                        resolved_at=now.isoformat(),
                    )
                    notification_service.sync_alert_status(alert["id"], "ignored")
                    logger.info(
                        "[fetch_dividend] 自动清理过期分红提醒: %s %s "
                        "(pending 超 %d 天)",
                        code, ex_date, _LOOKBACK_DAYS,
                    )
                    cleaned += 1
                    continue
            except (ValueError, TypeError):
                pass
        # --- 正常：fetched_funds 中无此 ex_date → ignored ---
        if not ex_date:
            continue
        if code not in fetched_funds:
            continue
        if (code, ex_date, channel) in fetched_ex_dates:
            continue
        db.update_dividend_alert(
            alert["id"],
            status="ignored",
            resolved_at=now.isoformat(),
        )
        notification_service.sync_alert_status(alert["id"], "ignored")
        logger.info(
            "[fetch_dividend] 自动清理幽灵分红提醒: %s %s %s (源数据已无此记录)",
            code, ex_date, channel or "(无渠道)",
        )
        cleaned += 1
    return cleaned


def check_dividends() -> list[DividendEvent]:
    """检查持仓基金的分红事件，返回未记录的分红列表。

    1. 获取当前持仓（所有 is_open 的基金，按渠道拆分）
    2. 串行抓取每只持仓基金的分红历史（必须串行，见 _MAX_WORKERS 注释）
    3. 过滤最近 _LOOKBACK_DAYS 天的事件；同一基金多渠道各出一条（份额/金额按渠道）
    4. 查已有 dividend/reinvest 交易做去重（同渠道同日期附近才算已记录）
    5. 按基金 dividend_method 预选 action

    同时校验现有 pending 提醒是否仍存在于源数据中，不存在则自动标记为 ignored。
    清理数量存入 _last_cleanup_count 供调用方（scan 端点）读取。
    """
    global _last_cleanup_count
    _last_cleanup_count = 0
    positions = analysis.calculate_positions()
    # 同一基金可能多渠道持仓：按 (fund_code, channel) 逐条出事件，
    # 否则多渠道时 held_shares 会被最后一条持仓覆盖、金额少算。
    positions_by_code: dict[str, list] = {}
    for p in positions:
        if p.is_open:
            positions_by_code.setdefault(p.fund_code, []).append(p)
    if not positions_by_code:
        return []

    funds = {f.fund_code: f for f in db.get_funds()}

    all_events: list[DividendEvent] = []
    cutoff = (datetime.now(config.TIMEZONE) - timedelta(days=_LOOKBACK_DAYS)).strftime("%Y-%m-%d")

    fetched_ex_dates: set[tuple[str, str, str]] = set()
    fetched_funds: set[str] = set()

    with ThreadPoolExecutor(max_workers=_MAX_WORKERS) as pool:
        future_map = {
            pool.submit(_fetch_fund_dividends, code): code
            for code in positions_by_code
        }
        for future in as_completed(future_map):
            code = future_map[future]
            fund = funds.get(code)
            fund_name = fund.fund_name if fund else code
            method = fund.dividend_method if fund else "cash"
            try:
                rows = future.result()
            except Exception:
                logger.debug("分红数据拉取失败 %s", code, exc_info=True)
                continue
            if rows is None:
                # 抓取失败（无缓存）：不计入 fetched_funds，保留其 pending
                # 提醒交由 90 天兜底处理，避免瞬时失败误清理分红提醒
                logger.debug("[fetch_dividend] %s 分红抓取失败，本轮跳过其提醒清理", code)
                continue
            fetched_funds.add(code)
            if not rows:
                continue
            for row in rows:
                ev = _parse_dividend_row(row, code, fund_name)
                if not ev or not ev.ex_date:
                    continue
                for pos in positions_by_code[code]:
                    fetched_ex_dates.add(
                        (code, ev.ex_date, pos.channel or "")
                    )
                if ev.ex_date < cutoff:
                    continue
                for pos in positions_by_code[code]:
                    channel = pos.channel or ""
                    all_events.append(replace(
                        ev,
                        held_shares=pos.held_shares,
                        estimated_amount=round(pos.held_shares * ev.per_share, 2),
                        dividend_method=method,
                        channel=channel,
                    ))

    try:
        cleaned = _cleanup_stale_alerts(fetched_ex_dates, fetched_funds)
        _last_cleanup_count = cleaned
        if cleaned:
            logger.info("[fetch_dividend] 清理 %d 条幽灵分红提醒", cleaned)
    except Exception:
        logger.exception("[fetch_dividend] _cleanup_stale_alerts 异常")
        _last_cleanup_count = 0

    if not all_events:
        return []

    # 批量过滤：只取相关基金的分红/再投资流水（避免全表扫描）
    relevant_codes = list({ev.fund_code for ev in all_events})
    existing_txs = db.get_transactions(
        fund_codes=relevant_codes,
        actions=[ACTION_DIVIDEND, ACTION_REINVEST],
    )
    # 按 fund_code 分组，O(D×K) 替代 O(D×N)
    tx_by_code: dict[str, list] = {}
    for tx in existing_txs:
        tx_by_code.setdefault(tx.fund_code, []).append(tx)

    for ev in all_events:
        for tx in tx_by_code.get(ev.fund_code, []):
            if (tx.channel or "") != ev.channel:
                continue
            if _date_close(tx.date, ev.ex_date, tolerance=3):
                ev.already_recorded = True
                break

    return [ev for ev in all_events if not ev.already_recorded]
