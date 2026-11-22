"""定时任务调度模块。

使用 APScheduler BackgroundScheduler 在进程内运行 cron 定时任务，
默认工作日 21:00 自动拉取所有持仓基金净值。
"""

from __future__ import annotations

import logging
import re
import threading
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from . import (
    analysis,
    auto_invest,
    config,
    db,
    fetch_estimate,
    fetch_fund,
    fetch_macro,
    notification_service,
)
from .nav_update_state import nav_update_lock as _nav_update_lock
from .nav_update_state import nav_update_state as _nav_update_state

logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)s:     %(name)s - %(message)s",
)
logger = logging.getLogger(__name__)

_scheduler: BackgroundScheduler | None = None
_last_run: datetime | None = None
_last_results: list[dict[str, Any]] | None = None
_last_auto_invest_run: datetime | None = None
_auto_invest_lock = threading.Lock()

_PREF_KEY_ENABLED = "nav_auto_update"
_PREF_KEY_CRON = "nav_cron"
_PREF_KEY_DIVIDEND = "dividend_auto_check"
# 分红检测「今日已尝试」落盘标记：任务若将进程打崩（原生段错误无法被
# try/except 捕获），重启后引导逻辑据此跳过重跑，避免崩溃循环拖垮整站
_PREF_KEY_DIVIDEND_ATTEMPT = "dividend_check_last_attempt"
_PREF_KEY_TP_SL_ENABLED = "tp_sl_enabled"

_last_dividend_run: datetime | None = None
_last_tp_sl_run: datetime | None = None
_last_benchmark_run: datetime | None = None


def _update_benchmark_indices() -> None:
    """拉取并持久化基准指数历史收盘价 + 宏观财富水位（CPI/M2）。

    在净值更新后调用，确保 index_history 表保持最新。
    失败不阻塞主流程（已有 DB 缓存可用）。
    """
    global _last_benchmark_run
    logger.info("[scheduler] 基准指数/宏观水位更新开始")
    today = datetime.now(config.TIMEZONE).strftime("%Y-%m-%d")
    for code, name in config.BENCHMARK_INDICES.items():
        db_latest = db.get_index_latest_date(code)
        if db_latest and db_latest >= today:
            logger.debug("[scheduler] %s(%s) 已是最新 %s，跳过", name, code, db_latest)
            continue
        # fetch_index_history 会自动持久化到 DB
        hist = fetch_estimate.fetch_index_history(code, "2010-01-01", today)
        if hist:
            logger.info("[scheduler] %s(%s) 更新到 %s (%d 条)",
                        name, code, hist[-1]["date"], len(hist))
        else:
            logger.warning("[scheduler] %s(%s) 拉取失败", name, code)
    for code, name in config.MACRO_INDICES.items():
        # 宏观数据为月度，内部按新鲜度判断是否需要在线拉取（fetch_macro_history）
        hist = fetch_macro.fetch_macro_history(code, "2008-01-01", today)
        if hist:
            logger.info("[scheduler] %s(%s) 最新月份 %s (%d 条)",
                        name, code, hist[-1]["date"], len(hist))
        else:
            logger.warning("[scheduler] %s(%s) 拉取失败", name, code)
    _last_benchmark_run = datetime.now(config.TIMEZONE)


def _run_nav_update() -> None:
    """执行净值更新任务（由调度器调用）。

    与 api._nav_update_lock 共享锁，与手动触发互斥。
    """
    global _last_run, _last_results

    with _nav_update_lock:
        if _nav_update_state["running"]:
            logger.info("[scheduler] 净值更新正在进行中, 跳过定时任务")
            return
        _nav_update_state["running"] = True
        _nav_update_state["total"] = 0
        _nav_update_state["done"] = 0
        _nav_update_state["current"] = ""
        _nav_update_state["phase"] = ""
        _nav_update_state["results"] = []
        _nav_update_state["error"] = ""

    try:
        positions = analysis.calculate_positions()
        codes = [p.fund_code for p in positions if p.is_open]
        if not codes:
            logger.info("[scheduler] 无持仓基金，跳过")
            with _nav_update_lock:
                _nav_update_state["running"] = False
            _last_run = datetime.now(config.TIMEZONE)
            _last_results = []
            return

        _nav_update_state["total"] = len(codes)

        def _progress(i: int, total: int, code: str) -> None:
            _nav_update_state["done"] = i
            _nav_update_state["total"] = total
            _nav_update_state["current"] = code

        results = fetch_fund.update_all_holdings_nav(codes=codes, progress=_progress)
        _nav_update_state["phase"] = "backfill"
        updated = analysis.backfill_transaction_navs()
        if updated:
            db.log_audit("nav_backfill", ip=None,
                          detail={"count": len(updated), "items": updated})
        analysis.clear_analysis_cache()
        _last_results = [r.__dict__ for r in results]
        _last_run = datetime.now(config.TIMEZONE)
        _nav_update_state["results"] = [r.__dict__ for r in results]
        ok = sum(1 for r in results if r.ok)
        fail = len(results) - ok
        logger.info("[scheduler] 净值更新完成: %d 成功, %d 失败", ok, fail)

        def _set_phase(phase: str) -> None:
            _nav_update_state["phase"] = phase

        # 净值更新完成后自动执行止盈止损检查
        _set_phase("tp_sl")
        _run_tp_sl_check()
        # 持久化基准指数数据（确保离线可用）
        _set_phase("benchmark")
        _update_benchmark_indices()
        # 刷新基金元数据（申购状态/交易日历/风险等级）
        refresh_fund_metadata(on_phase=_set_phase)
        # 元数据写入后失效持仓缓存，确保接口立即返回新值
        analysis.clear_analysis_cache()
        # 通知中心（best-effort，失败不影响主任务）：净值失败聚合 + 数据健康每日评估
        notification_service.notify_nav_update_failed(results)
        notification_service.evaluate_data_health()
    except Exception as exc:  # noqa: BLE001
        logger.exception("[scheduler] 定时净值更新任务异常")
        _last_run = datetime.now(config.TIMEZONE)
        _last_results = None
        _nav_update_state["error"] = str(exc)
    finally:
        with _nav_update_lock:
            _nav_update_state["running"] = False
            _nav_update_state["current"] = ""
            _nav_update_state["phase"] = ""


def _convert_dow(dow: str) -> str:
    """将标准 cron day_of_week（0/7=周日, 1=周一）转为 APScheduler 编号（0=周一, 6=周日）。

    不能逐数字做 (n-1)%7 平移：以周日开头的范围/步进会变成 APScheduler
    非法表达式（'0-6'→'6-5'、'0/2'→'6/2'，CronTrigger 直接抛 ValueError，
    配在 NAV_CRON 里会导致启动失败）。因此先解析成星期集合（展开
    range/step，0 与 7 均为周日），再映射为 APScheduler 编号并压缩成
    连续区间输出（必要时多段 list）。
    """
    days: set[int] = set()
    for part in dow.split(","):
        part = part.strip()
        if not part:
            raise ValueError(f"无效的 day_of_week: {dow!r}")
        body = part
        step = 1
        if "/" in part:
            body, step_str = part.split("/", 1)
            step = int(step_str)
            if step <= 0:
                raise ValueError(f"无效的 day_of_week 步进: {dow!r}")
        if body == "*":
            start, end = 0, 7
        elif "-" in body:
            a, b = body.split("-", 1)
            start, end = int(a), int(b)
        else:
            start = int(body)
            # 带步进时单个数字语义为「该日起至周末」，如 0/2 → 0,2,4,6
            end = 7 if "/" in part else start
        if not 0 <= start <= end <= 7:
            raise ValueError(f"无效的 day_of_week 范围: {dow!r}")
        days.update(range(start, end + 1, step))
    if not days:
        raise ValueError(f"无效的 day_of_week: {dow!r}")
    # 0/7 均为周日；映射到 APScheduler 编号（0=周一 … 6=周日）
    aps = sorted({(d % 7 - 1) % 7 for d in days})
    if len(aps) == 7:
        return "*"
    # 压缩连续区间，如 [1,3,5,6] → "1,3,5-6"
    segments: list[str] = []
    start = prev = aps[0]
    for n in aps[1:]:
        if n == prev + 1:
            prev = n
            continue
        segments.append(str(start) if start == prev else f"{start}-{prev}")
        start = prev = n
    segments.append(str(start) if start == prev else f"{start}-{prev}")
    return ",".join(segments)


# 标准 cron 英文缩写 → 数字（0/7=周日, 1=周一 … 6=周六）
_DOW_NAMES = {"sun": 0, "mon": 1, "tue": 2, "wed": 3, "thu": 4, "fri": 5, "sat": 6}


def _normalize_dow_names(dow: str) -> str:
    """把 day_of_week 中的英文缩写归一化为标准 cron 数字，供 _convert_dow 统一转换。

    APScheduler 里名称无歧义（fri 恒指周五），数字却有歧义（标准 cron 0=周日，
    APScheduler 0=周一）。混合表达式（如 ``1-5,fri``）此前因含字母被整体跳过
    转换，数字部分按 APScheduler 编号误读（1-5 变成周二至周六）。这里先把名称
    替换为标准 cron 数字，再整体交给 _convert_dow。

    跨周日的回绕区间（如 ``fri-mon`` → 5-1）展开为显式星期列表，避免
    _convert_dow 拒绝 start>end（纯数字回绕区间仍按既有约定视为非法）。
    """
    def _sub_name(m: re.Match) -> str:
        name = m.group(0).lower()
        if name not in _DOW_NAMES:
            raise ValueError(f"无效的 day_of_week 名称: {m.group(0)!r}")
        return str(_DOW_NAMES[name])

    numeric = re.sub(r"[A-Za-z]{3}", _sub_name, dow)
    if any(c.isalpha() for c in numeric):
        raise ValueError(f"无效的 day_of_week: {dow!r}")

    parts: list[str] = []
    for part in numeric.split(","):
        part = part.strip()
        body, step = part, 1
        if "/" in part:
            body, step_str = part.split("/", 1)
            step = int(step_str)
        if "-" in body:
            a, b = body.split("-", 1)
            start, end = int(a), int(b)
            if start > end:
                days = list(range(start, 8)) + list(range(0, end + 1))
                if step > 1:
                    days = days[::step]
                parts.append(",".join(str(d) for d in days))
                continue
        parts.append(part)
    return ",".join(parts)


def _parse_cron(expr: str) -> CronTrigger:
    """将 cron 表达式解析为 CronTrigger。"""
    parts = expr.split()
    if len(parts) != 5:
        raise ValueError(f"无效的 cron 表达式: {expr}")

    dow = parts[4]
    if dow != "*":
        # 含字母（纯名称或混合）先归一化为数字，再统一做标准 cron→APScheduler
        # 编号转换；纯数字直接转换。避免混合表达式数字部分被误读。
        if any(c.isalpha() for c in dow):
            dow = _normalize_dow_names(dow)
        dow = _convert_dow(dow)

    return CronTrigger(
        minute=parts[0],
        hour=parts[1],
        day=parts[2],
        month=parts[3],
        day_of_week=dow,
        timezone=config.TIMEZONE,
    )


def _refresh_purchase_status() -> None:
    """刷新库内所有基金的申购状态（限购/暂停申购），供定投可投性校验。"""
    try:
        codes = [f.fund_code for f in db.get_funds()]
        if not codes:
            return
        n = fetch_fund.refresh_purchase_status(codes)
        logger.info("[scheduler] 申购状态刷新: %d/%d", n, len(codes))
    except Exception:  # noqa: BLE001
        logger.warning("[scheduler] 申购状态刷新失败", exc_info=True)


def _refresh_trade_calendar() -> None:
    """刷新 A 股交易日历（持久化到 trade_calendar 表），供定投可投性校验。"""
    try:
        n = fetch_fund.refresh_trade_calendar()
        logger.info("[scheduler] 交易日历刷新: %d 天", n)
        _ensure_trade_calendar_coverage()
    except Exception:  # noqa: BLE001
        logger.warning("[scheduler] 交易日历刷新失败", exc_info=True)


def _ensure_trade_calendar_coverage() -> None:
    """日历未覆盖未来 30 天（跨年/长休期更常见）时强制绕过 24h 缓存重拉。"""
    try:
        horizon = (datetime.now(config.TIMEZONE)
                   + timedelta(days=30)).strftime("%Y-%m-%d")
        if db.trade_calendar_covers(horizon):
            return
        logger.warning("[scheduler] 交易日历未覆盖 %s，强制刷新一次", horizon)
        n = fetch_fund.refresh_trade_calendar(force=True)
        logger.info("[scheduler] 交易日历强制刷新: %d 天", n)
    except Exception:  # noqa: BLE001
        logger.warning("[scheduler] 交易日历覆盖检查/强制刷新失败", exc_info=True)


def _bootstrap_trade_calendar() -> None:
    """启动时刷新交易日历并做覆盖检查（24h 缓存内则轻量返回）。

    覆盖「调度器主任务尚未触达」的启动窗口：首启即拿到最新日历与覆盖
    告警，缩小 fail-open（日历为空/超范围退化周末判断）的暴露时间。
    ``_refresh_trade_calendar`` 内部已兜底，作为线程目标安全。
    """
    _refresh_trade_calendar()


def _refresh_risk_levels() -> None:
    """刷新库内所有基金的风险等级，供持仓/纵览/体检页展示。"""
    try:
        codes = [f.fund_code for f in db.get_funds()]
        if not codes:
            return
        n = fetch_fund.refresh_risk_levels(codes)
        logger.info("[scheduler] 风险等级刷新: %d/%d", n, len(codes))
    except Exception:  # noqa: BLE001
        logger.warning("[scheduler] 风险等级刷新失败", exc_info=True)


def refresh_fund_metadata(
    on_phase: Callable[[str], None] | None = None,
) -> None:
    """刷新基金元数据（申购状态 / 交易日历 / 风险等级）。

    净值更新后 + 手动刷新（`/api/nav/update`）时调用，确保持仓/纵览/收益/体检
    页展示的元数据（尤其风险等级）与最新数据一致。

    ``on_phase`` 可选回调在每步开始前触发，供调用方上报进度阶段（如写入
    ``nav_update_state["phase"]``），让前端在净值抓取完成后仍能看到尾部进度。
    """
    if on_phase:
        on_phase("purchase_status")
    _refresh_purchase_status()
    if on_phase:
        on_phase("trade_calendar")
    _refresh_trade_calendar()
    if on_phase:
        on_phase("risk_levels")
    _refresh_risk_levels()


def _bootstrap_risk_levels() -> None:
    """启动时补全缺失的风险等级（部署 / 新基金首次采集）。

    仅处理 `risk_level` 为空的基金，避免每次重启都全量抓取。
    """
    try:
        missing = [f.fund_code for f in db.get_funds() if not f.risk_level]
        if not missing:
            return
        n = fetch_fund.refresh_risk_levels(missing)
        if n:
            analysis.clear_analysis_cache()
        logger.info("[scheduler] 风险等级启动补全: %d/%d", n, len(missing))
    except Exception:  # noqa: BLE001
        logger.warning("[scheduler] 风险等级启动补全失败", exc_info=True)


def _run_auto_invest() -> None:
    """执行定投计划检查任务（由调度器调用，每天 09:00）。"""
    global _last_auto_invest_run
    with _auto_invest_lock:
        logger.info("[scheduler] 定投计划检查开始")
        try:
            # 执行前强制刷新申购状态，避免用过期数据判断可投性
            fetch_fund.clear_purchase_status_cache()
            _refresh_purchase_status()
            # 执行前刷新交易日历，确保节假日 gate 用最新日历
            _refresh_trade_calendar()
            # 降级检测：执行日未被日历覆盖（fail-open 退化周末判断）时提醒，
            # 避免节假日照常执行而用户不知情（通知按日去重，best-effort）
            today_str = datetime.now(config.TIMEZONE).strftime("%Y-%m-%d")
            if not db.trade_calendar_covers(today_str):
                notification_service.notify_trade_calendar_degraded(today_str)
            results = auto_invest.run_all_due()
            _last_auto_invest_run = datetime.now(config.TIMEZONE)
            # 通知中心（best-effort）：三类 skip_code / error 逐计划发，holiday 不发
            notification_service.notify_auto_invest_results(results)
            if results:
                ok = sum(1 for r in results if r.get("status") == "success")
                fail = sum(1 for r in results if r.get("status") == "error")
                db.log_audit("auto_invest_execute", ip=None,
                              detail={"count": len(results), "ok": ok, "fail": fail,
                                      "items": results})
                logger.info("[scheduler] 定投执行: %d 成功, %d 失败", ok, fail)
            else:
                logger.info("[scheduler] 无到期定投计划")
        except Exception as exc:  # noqa: BLE001
            logger.exception("[scheduler] 定投计划检查异常")
            _last_auto_invest_run = datetime.now(config.TIMEZONE)
            notification_service.notify_auto_invest_task_error(str(exc))


def _run_dividend_check() -> None:
    """执行分红检测任务（由调度器调用，每天 09:30）。

    扫描持仓基金的未记录分红事件，新发现的存入 dividend_alerts 表。
    去重：dividend_alert_exists 查所有状态，已存在的不重复存。
    """
    global _last_dividend_run
    logger.info("[scheduler] 分红检测任务开始")
    try:
        # 先落盘「今日已尝试」再抓取：抓取路径若原生崩溃（如 SIGSEGV，
        # Python 无法捕获），得不到执行机会更新 _last_dividend_run；
        # 有了这个标记，重启后 _bootstrap_dividend_check 会跳过重跑，
        # 不会陷入「启动→立即执行→崩溃→重启」的无限循环（曾导致整站瘫痪）。
        # 标记写入是辅助防护：失败（如精简测试库无 preferences 表）不应
        # 中断主任务，生产环境 init_db 已建表，防护正常生效。
        try:
            db.upsert_preference(
                _PREF_KEY_DIVIDEND_ATTEMPT,
                datetime.now(config.TIMEZONE).strftime("%Y-%m-%d"),
            )
        except Exception:
            logger.warning(
                "[scheduler] 记录分红检测尝试标记失败，继续本次检测", exc_info=True
            )
        from . import fetch_dividend
        events = fetch_dividend.check_dividends()
        new_count = 0
        for ev in events:
            if not db.dividend_alert_exists(ev.fund_code, ev.ex_date, ev.channel):
                alert_id = db.add_dividend_alert({
                    "fund_code": ev.fund_code,
                    "fund_name": ev.fund_name,
                    "record_date": ev.record_date,
                    "ex_date": ev.ex_date,
                    "per_share": ev.per_share,
                    "pay_date": ev.pay_date,
                    "held_shares": ev.held_shares,
                    "estimated_amount": ev.estimated_amount,
                    "dividend_method": ev.dividend_method,
                    "channel": ev.channel,
                })
                notification_service.notify_dividend_alert(ev, alert_id)
                new_count += 1
        cleaned = fetch_dividend._last_cleanup_count
        if new_count or cleaned:
            db.log_audit("dividend_scan", ip=None,
                         detail={"found": len(events), "new": new_count,
                                 "cleaned": cleaned})
            logger.info("[scheduler] 分红检测完成: 发现 %d, 新增 %d 条提醒, 清理 %d 条幽灵提醒",
                        len(events), new_count, cleaned)
        else:
            logger.info("[scheduler] 分红检测完成: 发现 %d, 无新增提醒", len(events))
        _last_dividend_run = datetime.now(config.TIMEZONE)
    except Exception:
        logger.exception("[scheduler] 分红检测任务异常")
        _last_dividend_run = datetime.now(config.TIMEZONE)


def _get_tp_sl_enabled() -> bool:
    val = db.get_preference(_PREF_KEY_TP_SL_ENABLED)
    if val is None:
        return False
    return val == "true"


def _run_tp_sl_check() -> None:
    """执行止盈止损检查（净值更新后自动调用）。

    扫描所有持仓基金收益率，触发止盈/止损提醒。
    状态机：触发后 disarmed，收益率回落到复位线以下后重新 armed。
    """
    global _last_tp_sl_run
    if not _get_tp_sl_enabled():
        return
    logger.info("[scheduler] 止盈止损检查开始")
    try:
        cfg = db.get_tp_sl_config()
        tp_enabled = cfg["take_profit_enabled"] == "true"
        sl_enabled = cfg["stop_loss_enabled"] == "true"
        tp_threshold = float(cfg["take_profit"])
        sl_threshold = float(cfg["stop_loss"])
        reset_ratio = float(cfg["reset_ratio"])

        positions = analysis.calculate_positions(include_closed=False)
        today = datetime.now(config.TIMEZONE).strftime("%Y-%m-%d")
        new_count = 0

        # 批量预加载所有持仓的止盈止损状态（单次查询，避免 N+1）
        codes = [p.fund_code for p in positions]
        states = db.get_tp_sl_alert_states_batch(codes)

        for pos in positions:
            rr = pos.return_rate
            if rr is None:
                continue

            tp_state = states.get((pos.fund_code, "take_profit"))
            sl_state = states.get((pos.fund_code, "stop_loss"))

            if tp_enabled and rr >= tp_threshold:
                armed = tp_state is None or tp_state.get("armed", 1) == 1
                if armed and not db.tp_sl_alert_exists(pos.fund_code, "take_profit", today):
                    alert_id = db.add_tp_sl_alert({
                        "fund_code": pos.fund_code,
                        "fund_name": pos.fund_name,
                        "alert_type": "take_profit",
                        "triggered_return": rr,
                        "threshold": tp_threshold,
                    })
                    db.upsert_tp_sl_alert_state(
                        pos.fund_code, "take_profit",
                        last_alert_id=alert_id,
                        last_triggered_return=rr,
                        armed=0,
                    )
                    states[(pos.fund_code, "take_profit")] = {
                        "armed": 0, "last_alert_id": alert_id,
                        "last_triggered_return": rr,
                    }
                    new_count += 1
                    notification_service.notify_tp_sl_alert(
                        alert_id, fund_code=pos.fund_code,
                        fund_name=pos.fund_name, alert_type="take_profit",
                        triggered_return=rr, threshold=tp_threshold)

            if sl_enabled and rr <= sl_threshold:
                armed = sl_state is None or sl_state.get("armed", 1) == 1
                if armed and not db.tp_sl_alert_exists(pos.fund_code, "stop_loss", today):
                    alert_id = db.add_tp_sl_alert({
                        "fund_code": pos.fund_code,
                        "fund_name": pos.fund_name,
                        "alert_type": "stop_loss",
                        "triggered_return": rr,
                        "threshold": sl_threshold,
                    })
                    db.upsert_tp_sl_alert_state(
                        pos.fund_code, "stop_loss",
                        last_alert_id=alert_id,
                        last_triggered_return=rr,
                        armed=0,
                    )
                    states[(pos.fund_code, "stop_loss")] = {
                        "armed": 0, "last_alert_id": alert_id,
                        "last_triggered_return": rr,
                    }
                    new_count += 1
                    notification_service.notify_tp_sl_alert(
                        alert_id, fund_code=pos.fund_code,
                        fund_name=pos.fund_name, alert_type="stop_loss",
                        triggered_return=rr, threshold=sl_threshold)

            # 复位检查：收益率回落到复位线以下后重新 armed
            tp_reset = tp_threshold * reset_ratio
            sl_reset = sl_threshold * reset_ratio
            if tp_enabled:
                tp_st = states.get((pos.fund_code, "take_profit"))
                if tp_st and tp_st.get("armed", 1) == 0 and rr < tp_reset:
                    db.upsert_tp_sl_alert_state(pos.fund_code, "take_profit", armed=1)
                    states[(pos.fund_code, "take_profit")] = {
                        **tp_st, "armed": 1,
                    }
            if sl_enabled:
                sl_st = states.get((pos.fund_code, "stop_loss"))
                if sl_st and sl_st.get("armed", 1) == 0 and rr > sl_reset:
                    db.upsert_tp_sl_alert_state(pos.fund_code, "stop_loss", armed=1)
                    states[(pos.fund_code, "stop_loss")] = {
                        **sl_st, "armed": 1,
                    }

        if new_count:
            db.log_audit("tp_sl_alert", ip=None,
                         detail={"new": new_count})
            logger.info("[scheduler] 止盈止损检查完成: 新增 %d 条提醒", new_count)
        else:
            logger.info("[scheduler] 止盈止损检查完成: 无新增提醒")
        _last_tp_sl_run = datetime.now(config.TIMEZONE)
    except Exception:
        logger.exception("[scheduler] 止盈止损检查异常")
        _last_tp_sl_run = datetime.now(config.TIMEZONE)


def init_scheduler() -> None:
    """初始化并启动调度器。在 FastAPI startup 中调用。"""
    global _scheduler
    if _scheduler is not None:
        return

    _scheduler = BackgroundScheduler(timezone=config.TIMEZONE_STR)
    cron_expr = _get_cron()
    trigger = _parse_cron(cron_expr)

    enabled = _get_enabled()
    _scheduler.add_job(
        _run_nav_update,
        trigger=trigger,
        id="nav_update",
        max_instances=1,
        misfire_grace_time=3600,
        coalesce=True,
    )
    _scheduler.add_job(
        _run_auto_invest,
        trigger=CronTrigger(hour=9, minute=0, timezone=config.TIMEZONE),
        id="auto_invest",
        max_instances=1,
        misfire_grace_time=3600,
        coalesce=True,
    )
    _scheduler.add_job(
        _run_dividend_check,
        trigger=CronTrigger(hour=9, minute=30, timezone=config.TIMEZONE),
        id="dividend_check",
        max_instances=1,
        misfire_grace_time=3600,
        coalesce=True,
    )
    _scheduler.add_job(
        _run_daily_maintenance,
        trigger=CronTrigger(hour=10, minute=30, timezone=config.TIMEZONE),
        id="daily_maintenance",
        max_instances=1,
        misfire_grace_time=3600,
        coalesce=True,
    )
    _scheduler.start()
    logger.info("[scheduler] 调度器已启动, cron=%s, enabled=%s", cron_expr, enabled)

    if not enabled:
        _scheduler.pause_job("nav_update")
    else:
        threading.Thread(target=_bootstrap_check, args=(trigger,), daemon=True).start()
    threading.Thread(target=_bootstrap_auto_invest, daemon=True).start()

    if not _get_dividend_enabled():
        _scheduler.pause_job("dividend_check")
    else:
        threading.Thread(target=_bootstrap_dividend_check, daemon=True).start()

    # 启动补全缺失的风险等级（部署后无需等待定时任务即可展示）
    threading.Thread(target=_bootstrap_risk_levels, daemon=True).start()

    # 启动刷新交易日历 + 覆盖检查（缩小 fail-open 降级窗口）
    threading.Thread(target=_bootstrap_trade_calendar, daemon=True).start()


# 幂等操作记录保留期：TTL 90 天 + 30 天排障宽限，之后清理。
AGENT_OPERATIONS_PURGE_GRACE_DAYS = 30

# dismissed 通知保留期：30 天（按创建时间起算），read 永久保留。
NOTIFICATIONS_PURGE_DAYS = 30

# 审计日志保留期默认值：90 天（设置页可配，见 config.AUDIT_RETENTION_*）。
AUDIT_LOG_RETENTION_DAYS = config.AUDIT_RETENTION_DEFAULT_DAYS


def purge_agent_operations_daily() -> int:
    """清理过期较久的幂等操作记录（agent_operations）与审计日志，启动与每日任务共用。

    幂等操作只删除 expires_at 已过期且早于「now − 30 天宽限」的记录；TTL 内的
    重放/拒绝语义不受影响。审计日志保留期取设置页配置（preferences
    audit_retention_days，默认 90 天，下限 30 天，db.purge_audit_logs，B4 契约），
    每次清理实时解析，修改后下次清理即生效；其失败不影响幂等记录清理。
    失败由调用方决定是否吞掉（每日任务吞掉并记日志）。
    """
    now = datetime.now(config.TIMEZONE)
    cutoff = (now - timedelta(days=AGENT_OPERATIONS_PURGE_GRACE_DAYS)).isoformat()
    removed = db.purge_agent_operations(cutoff)
    retention_days = config.resolve_audit_retention_days(
        db.get_preference(config.AUDIT_RETENTION_PREF_KEY))
    try:
        purged = db.purge_audit_logs(retention_days)
        if purged:
            logger.info("[scheduler] 清理 %d 条超过 %d 天的审计日志",
                        purged, retention_days)
    except Exception:
        logger.exception("[scheduler] 清理审计日志异常")
    return removed


def purge_notifications_daily() -> int:
    """清理 dismissed 且创建超过 30 天的通知（read 永久保留）。"""
    now = datetime.now(config.TIMEZONE)
    cutoff = (now - timedelta(days=NOTIFICATIONS_PURGE_DAYS)).isoformat()
    return db.purge_dismissed_notifications(cutoff)


def _run_daily_maintenance() -> None:
    """每日维护：清理过期较久的幂等操作记录与 dismissed 通知，避免表无限增长。"""
    try:
        removed = purge_agent_operations_daily()
        if removed:
            logger.info("[scheduler] 清理 %d 条过期幂等操作记录", removed)
    except Exception:
        logger.exception("[scheduler] 清理幂等操作记录异常")
    try:
        removed = purge_notifications_daily()
        if removed:
            logger.info("[scheduler] 清理 %d 条过期 dismissed 通知", removed)
    except Exception:
        logger.exception("[scheduler] 清理 dismissed 通知异常")


def _bootstrap_auto_invest() -> None:
    """启动时检测：如果今日 09:00 已过且尚未运行过，立即执行定投检查。"""
    global _last_auto_invest_run
    if _last_auto_invest_run is not None:
        return
    now = datetime.now(config.TIMEZONE)
    if now.hour < 9:
        return
    today = now.strftime("%Y-%m-%d")
    if any(p.get("last_run") == today for p in db.get_auto_invest_plans()):
        _last_auto_invest_run = now
        return
    logger.info("[scheduler] 今日 09:00 已过, 立即执行定投检查")
    _run_auto_invest()


def _bootstrap_dividend_check() -> None:
    """启动时检测：如果今日 09:30 已过且开关开启且尚未运行过，立即执行分红检测。

    判断依据是 DB 里的「今日已尝试」标记而非仅内存变量：任务若原生崩溃
    （SIGSEGV），进程重启后内存变量归零，若无落盘标记会立即重跑 → 崩溃
    循环 → 整站不可用。落盘后同一进程每日最多尝试一次。
    """
    global _last_dividend_run
    if _last_dividend_run is not None:
        return
    if not _get_dividend_enabled():
        return
    now = datetime.now(config.TIMEZONE)
    if now.hour < 9 or (now.hour == 9 and now.minute < 30):
        return
    today = now.strftime("%Y-%m-%d")
    if db.get_preference(_PREF_KEY_DIVIDEND_ATTEMPT) == today:
        _last_dividend_run = now  # 今日已尝试过（可能曾崩溃），不再重试
        return
    logger.info("[scheduler] 今日 09:30 已过, 立即执行分红检测")
    _run_dividend_check()


def _bootstrap_check(trigger: CronTrigger) -> None:
    """启动时检测：如果今日 cron 时间已过且尚未运行过，立即执行。"""
    if _last_run is not None:
        return
    now = datetime.now(config.TIMEZONE)
    next_fire = trigger.get_next_fire_time(None, now)
    if next_fire is None or next_fire.date() == now.date():
        return
    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
    first_today = trigger.get_next_fire_time(None, midnight)
    if first_today and first_today.date() == now.date():
        logger.info("[scheduler] 今日 cron 已过, 立即执行净值更新")
        _run_nav_update()


def shutdown_scheduler() -> None:
    """停止调度器。在 FastAPI shutdown 中调用。"""
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
        logger.info("[scheduler] 调度器已停止")


def reset_scheduler() -> None:
    """安全清空调度器引用，供初始化失败后降级重建使用。

    init_scheduler 可能在创建实例后、start 之前抛错（如 cron 非法），
    此时实例未运行，shutdown_scheduler 会抛 SchedulerNotRunningError。
    本方法容忍未启动/半初始化实例，确保引用被清空、可重新 init。
    """
    global _scheduler
    if _scheduler is None:
        return
    try:
        _scheduler.shutdown(wait=False)
    except Exception:
        # 未 start 的实例 shutdown 会抛错，忽略即可
        logger.debug("[scheduler] 停止半初始化调度器异常（忽略）", exc_info=True)
    _scheduler = None


def _get_enabled() -> bool:
    """从 preferences 表读取是否启用。默认启用。"""
    val = db.get_preference(_PREF_KEY_ENABLED)
    if val is None:
        return True
    return val == "true"


def _get_cron() -> str:
    """从 preferences 表读取 cron 表达式，未设置时回退到环境变量默认值。"""
    val = db.get_preference(_PREF_KEY_CRON)
    if val:
        return val
    return config.NAV_CRON


def set_cron(cron_expr: str) -> None:
    """更新 cron 表达式并重新调度任务。"""
    trigger = _parse_cron(cron_expr)  # 验证表达式合法
    db.upsert_preference(_PREF_KEY_CRON, cron_expr)
    if _scheduler is not None:
        _scheduler.reschedule_job("nav_update", trigger=trigger)
        logger.info("[scheduler] cron 已更新: %s", cron_expr)


def set_enabled(enabled: bool) -> None:
    """启用/暂停定时任务，并持久化到 preferences 表。"""
    db.upsert_preference(_PREF_KEY_ENABLED, "true" if enabled else "false")
    if _scheduler is None:
        return
    if enabled:
        _scheduler.resume_job("nav_update")
        logger.info("[scheduler] 定时任务已启用")
    else:
        _scheduler.pause_job("nav_update")
        logger.info("[scheduler] 定时任务已暂停")


def _get_dividend_enabled() -> bool:
    """从 preferences 表读取分红自动检测是否启用。默认关闭。"""
    val = db.get_preference(_PREF_KEY_DIVIDEND)
    if val is None:
        return False
    return val == "true"


def set_dividend_enabled(enabled: bool) -> None:
    """启用/暂停分红自动检测任务，并持久化到 preferences 表。"""
    db.upsert_preference(_PREF_KEY_DIVIDEND, "true" if enabled else "false")
    if _scheduler is None:
        return
    if enabled:
        _scheduler.resume_job("dividend_check")
        logger.info("[scheduler] 分红自动检测已启用")
    else:
        _scheduler.pause_job("dividend_check")
        logger.info("[scheduler] 分红自动检测已暂停")


def get_status() -> dict[str, Any]:
    """返回调度器状态。"""
    enabled = _get_enabled()
    cron_expr = _get_cron()
    next_run: str | None = None
    if _scheduler is not None and enabled:
        job = _scheduler.get_job("nav_update")
        if job and job.next_run_time:
            next_run = job.next_run_time.strftime("%Y-%m-%d %H:%M:%S")
    return {
        "enabled": enabled,
        "cron": cron_expr,
        "next_run": next_run,
        "last_run": _last_run.strftime("%Y-%m-%d %H:%M:%S") if _last_run else None,
        "last_results": _last_results,
        "dividend_enabled": _get_dividend_enabled(),
        "dividend_last_run": (_last_dividend_run.strftime("%Y-%m-%d %H:%M:%S")
                              if _last_dividend_run else None),
        "tp_sl_enabled": _get_tp_sl_enabled(),
        "tp_sl_last_run": (_last_tp_sl_run.strftime("%Y-%m-%d %H:%M:%S")
                           if _last_tp_sl_run else None),
    }
