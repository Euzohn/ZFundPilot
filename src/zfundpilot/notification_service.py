"""统一站内提醒中心（P3 Phase 2）——best-effort 编排层。

只存业务引用与展示态（notifications 表），业务状态仍在原表；标题全部
稳定 code+params（i18n 纪律，禁后端自由中文）。

🔴 硬性安全约束：所有写入 **best-effort**——独立 try/except + warning 日志、
独立连接/事务（绝不与业务写同事务）、绝不上抛异常。通知失败不得影响
分红落库/定投执行/净值更新/提案审批（范式：scheduler 分红尝试标记）。

事件源（6 类 source_type）：
- dividend     分红提醒（scheduler 扫描与 /api/dividends/scan 共用落库路径）
- tpsl         止盈止损触发
- auto_invest  定投跳过（三类 skip_code）/失败/整任务异常；holiday 正常休市不发
- job          Agent 刷新/回测任务 failed、启动 interrupted（仅 running）
- nav_update   scheduler 每日净值更新失败聚合（网页手动刷新失败不发，即时可见）
- data_health  净值更新后数据健康评估，每日一条聚合（stale/missing/pending_t1 任一 >0）
"""

from __future__ import annotations

import functools
import logging
from datetime import datetime
from typing import Any

from . import config, db

logger = logging.getLogger(__name__)


def _best_effort(fn):
    """装饰器：吞掉一切异常仅 warning——通知层任何入口绝不上抛。

    覆盖参数构造阶段（如遍历结果/读取事件字段），不只是 db 写入阶段，
    确保畸形输入也不会把异常抛进调用方（scheduler/提案审批）的主流程。
    """
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except Exception:  # noqa: BLE001
            logger.warning("[notifications] %s 失败（不影响主业务）",
                           fn.__name__, exc_info=True)
            return None
    return wrapper

SOURCE_TYPES = ("dividend", "tpsl", "auto_invest", "job", "nav_update", "data_health")

# 定投可投性校验的三类 skip_code（auto_invest.execute_plan）；
# holiday（正常休市）与 skipped（今日已执行）不发通知。
_INVEST_SKIP_CODES = ("suspended", "limit_exceeded", "below_minimum")

# 业务提醒状态 → 通知展示态
_ALERT_STATUS_MAP = {"confirmed": "read", "ignored": "dismissed", "pending": "unread"}


def notify(source_type: str, source_id: str | int, dedupe_key: str,
           title_code: str, title_params: dict | None = None) -> bool:
    """写入一条通知（dedupe_key 去重）。失败仅 warning，绝不上抛。

    返回是否新插入（False = 同键已存在或写入失败）。
    """
    try:
        return db.add_notification(
            source_type=source_type, source_id=str(source_id),
            dedupe_key=dedupe_key, title_code=title_code,
            title_params=title_params)
    except Exception:  # noqa: BLE001
        logger.warning("[notifications] 通知写入失败（不影响主业务）: %s",
                       dedupe_key, exc_info=True)
        return False


def sync_alert_status(alert_id: int | None, business_status: str | None) -> None:
    """业务提醒状态联动（best-effort）：confirmed→read、ignored→dismissed、
    pending→unread。分红与止盈止损共用 dividend_alerts 表，按 source_id
    在两类来源中同步（至多命中一类）。
    """
    if not alert_id or business_status not in _ALERT_STATUS_MAP:
        return
    target = _ALERT_STATUS_MAP[business_status]
    try:
        for source_type in ("dividend", "tpsl"):
            db.sync_notification_by_source(source_type, str(alert_id), status=target)
    except Exception:  # noqa: BLE001
        logger.warning("[notifications] 提醒状态联动失败（不影响主业务）: alert#%s",
                       alert_id, exc_info=True)


def invalidate_alert(alert_id: int | None) -> None:
    """业务提醒被删除（用户删除等）→ 对应通知 dismissed（UI 失效降级）。"""
    if not alert_id:
        return
    try:
        for source_type in ("dividend", "tpsl"):
            db.sync_notification_by_source(source_type, str(alert_id),
                                           status="dismissed")
    except Exception:  # noqa: BLE001
        logger.warning("[notifications] 提醒失效联动失败（不影响主业务）: alert#%s",
                       alert_id, exc_info=True)


# ---------------------------------------------------------------------------
# 各事件源写入助手（调用方在业务写成功/提交后调用）
# ---------------------------------------------------------------------------
@_best_effort
def notify_dividend_alert(ev: Any, alert_id: int) -> None:
    """分红提醒落库成功后（scheduler 与 /api/dividends/scan 共用）。"""
    notify("dividend", alert_id,
           f"dividend:{ev.fund_code}:{ev.ex_date}:{ev.channel}",
           "dividend_detected",
           {"fund_code": ev.fund_code, "fund_name": ev.fund_name,
            "ex_date": ev.ex_date, "channel": ev.channel or "",
            "per_share": ev.per_share,
            "estimated_amount": ev.estimated_amount})


@_best_effort
def notify_tp_sl_alert(alert_id: int, *, fund_code: str, fund_name: str,
                       alert_type: str, triggered_return: float,
                       threshold: float) -> None:
    """止盈止损产生 pending alert 时。"""
    notify("tpsl", alert_id, f"tpsl:{alert_id}", "tp_sl_triggered",
           {"fund_code": fund_code, "fund_name": fund_name,
            "alert_type": alert_type, "triggered_return": triggered_return,
            "threshold": threshold})


@_best_effort
def notify_auto_invest_results(results: list[dict]) -> None:
    """定投执行结果逐计划发通知：仅三类 skip_code 与 error；
    success/holiday/skipped（今日已执行）不发。
    """
    for r in results:
        status = r.get("status", "")
        plan_id = r.get("plan_id", "")
        date = r.get("date") or datetime.now(config.TIMEZONE).strftime("%Y-%m-%d")
        if status in _INVEST_SKIP_CODES:
            notify("auto_invest", plan_id,
                   f"auto_invest:{plan_id}:{date}:{status}",
                   "auto_invest_skipped",
                   {"plan_id": plan_id, "fund_code": r.get("fund_code", ""),
                    "skip_code": status, "date": date,
                    "detail": str(r.get("detail") or "")[:200]})
        elif status == "error":
            notify("auto_invest", plan_id,
                   f"auto_invest:{plan_id}:{date}:error",
                   "auto_invest_error",
                   {"plan_id": plan_id, "fund_code": r.get("fund_code", ""),
                    "date": date, "error": str(r.get("error") or "")[:200]})


@_best_effort
def notify_auto_invest_task_error(error: str) -> None:
    """定投整任务异常（run_all_due 之前/之外抛错）发一条。"""
    date = datetime.now(config.TIMEZONE).strftime("%Y-%m-%d")
    notify("auto_invest", "", f"auto_invest:task:{date}:error",
           "auto_invest_task_error",
           {"date": date, "error": str(error)[:200]})


@_best_effort
def notify_trade_calendar_degraded(date: str) -> bool | None:
    """定投检查日未被交易日历覆盖（fail-open 退化，节假日可能照常执行）。

    按日期去重：同日多次检查（手动刷新/重启引导）不重发。
    返回是否新插入（False = 同日已发或写入失败）。
    """
    return notify("auto_invest", date,
                  f"auto_invest:trade_calendar_degraded:{date}",
                  "trade_calendar_degraded", {"date": date})


@_best_effort
def notify_job_failed(job_id: int, job_type: str, error: str) -> None:
    """Agent 刷新/回测任务落 failed 后（两类 job 同模式）。"""
    notify("job", job_id, f"job:failed:{job_id}", "job_failed",
           {"job_id": job_id, "job_type": job_type,
            "error": str(error)[:200]})


@_best_effort
def notify_job_interrupted(job_id: int) -> None:
    """启动批量标记 interrupted 时仅对 running 任务发（queued 未开始，控噪）。"""
    notify("job", job_id, f"job:interrupted:{job_id}", "job_interrupted",
           {"job_id": job_id})


@_best_effort
def notify_nav_update_failed(results: list) -> None:
    """scheduler 每日净值更新结束后统计失败只数 >0 发一条聚合。

    网页手动刷新失败不单独发（用户正在操作页面，即时可见）。
    """
    failed = [r for r in results if not r.ok]
    if not failed:
        return
    date = datetime.now(config.TIMEZONE).strftime("%Y-%m-%d")
    notify("nav_update", date, f"nav_update:failed:{date}",
           "nav_update_failed",
           {"date": date, "count": len(failed),
            "funds": [{"fund_code": r.fund_code,
                       "message": str(r.message)[:200]}
                      for r in failed[:20]]})


def evaluate_data_health() -> None:
    """scheduler 净值更新完成后评估一次数据健康（best-effort）。

    stale/missing/pending_t1 任一 >0 → 每日一条聚合通知（明细进 params），
    dedupe_key 按日期，同日重复评估不重发。
    """
    try:
        from . import analysis  # 延迟导入，避免模块环
        positions = analysis.calculate_positions()
        status = analysis._build_data_status(positions)
        if not (status.stale_nav_fund_count or status.missing_nav_fund_count
                or status.pending_t1_transaction_count):
            return
        date = datetime.now(config.TIMEZONE).strftime("%Y-%m-%d")
        notify("data_health", date, f"data:health:{date}",
               "data_health_abnormal",
               {"date": date,
                "stale_nav_fund_count": status.stale_nav_fund_count,
                "missing_nav_fund_count": status.missing_nav_fund_count,
                "pending_t1_transaction_count": status.pending_t1_transaction_count})
    except Exception:  # noqa: BLE001
        logger.warning("[notifications] 数据健康评估失败（不影响主业务）", exc_info=True)
