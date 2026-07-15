"""定时任务调度模块。

使用 APScheduler BackgroundScheduler 在进程内运行 cron 定时任务，
默认工作日 21:00 自动拉取所有持仓基金净值。
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from . import config, db, fetch_fund, analysis

logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)s:     %(name)s - %(message)s",
)
logger = logging.getLogger(__name__)

_scheduler: BackgroundScheduler | None = None
_last_run: datetime | None = None
_last_results: list[dict[str, Any]] | None = None

_PREF_KEY_ENABLED = "nav_auto_update"
_PREF_KEY_CRON = "nav_cron"


def _run_nav_update() -> None:
    """执行净值更新任务（由调度器调用）。"""
    global _last_run, _last_results
    logger.info("[scheduler] 定时净值更新任务开始")
    try:
        positions = analysis.calculate_positions()
        codes = [p.fund_code for p in positions if p.is_open]
        if not codes:
            logger.info("[scheduler] 无持仓基金，跳过")
            _last_run = datetime.now()
            _last_results = []
            return
        results = fetch_fund.update_all_holdings_nav(codes=codes)
        _last_results = [r.__dict__ for r in results]
        _last_run = datetime.now()
        ok = sum(1 for r in results if r.ok)
        fail = len(results) - ok
        logger.info("[scheduler] 净值更新完成: %d 成功, %d 失败", ok, fail)
    except Exception:
        logger.exception("[scheduler] 定时净值更新任务异常")
        _last_run = datetime.now()
        _last_results = None


def _parse_cron(expr: str) -> CronTrigger:
    """将 cron 表达式解析为 CronTrigger。"""
    parts = expr.split()
    if len(parts) != 5:
        raise ValueError(f"无效的 cron 表达式: {expr}")
    return CronTrigger(
        minute=parts[0],
        hour=parts[1],
        day=parts[2],
        month=parts[3],
        day_of_week=parts[4],
    )


def init_scheduler() -> None:
    """初始化并启动调度器。在 FastAPI startup 中调用。"""
    global _scheduler
    if _scheduler is not None:
        return

    _scheduler = BackgroundScheduler(timezone="Asia/Shanghai")
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
    _scheduler.start()
    logger.info("[scheduler] 调度器已启动, cron=%s, enabled=%s", cron_expr, enabled)

    if not enabled:
        _scheduler.pause_job("nav_update")
    else:
        _bootstrap_check(trigger)


def _bootstrap_check(trigger: CronTrigger) -> None:
    """启动时检测：如果今日 cron 时间已过且尚未运行过，立即执行。"""
    if _last_run is not None:
        return
    now = datetime.now()
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
    }
