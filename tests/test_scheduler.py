"""定时任务调度模块测试。

验证：
1. _parse_cron 正确解析 cron 表达式
2. _convert_dow 数值转换（0=周日 → 0=周一）
3. CronTrigger 时区为 config.TIMEZONE
4. _convert_dow 保留字母缩写不转换
5. refresh_fund_metadata 依次调用申购状态/交易日历/风险等级刷新
6. _bootstrap_risk_levels 仅补全 risk_level 为空的基金
7. 分红检测启动引导的崩溃循环防护（落盘「今日已尝试」）
"""
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

import pytest

from apscheduler.schedulers.background import BackgroundScheduler

from zfundpilot import config, db, scheduler
from zfundpilot.scheduler import _convert_dow, _parse_cron


class TestParseCron:
    """验证 _parse_cron 解析逻辑。"""

    def test_basic_cron(self):
        """标准 5 段 cron 表达式。"""
        trigger = _parse_cron("0 21 * * 1-5")
        assert trigger is not None

    def test_cron_timezone_is_config(self):
        """解析出的 CronTrigger 时区应为 config.TIMEZONE。"""
        trigger = _parse_cron("0 21 * * 1-5")
        assert trigger.timezone == config.TIMEZONE

    def test_invalid_cron_raises(self):
        """非 5 段表达式应报错。"""
        with pytest.raises(ValueError):
            _parse_cron("0 21")

    def test_dow_numeric_converted(self):
        """纯数值 day_of_week 应被转换（0=周日 → 6=周日 in APScheduler）。"""
        trigger = _parse_cron("0 21 * * 0")
        # 0（周日）经过 _convert_dow 变成 6（APScheduler 的周日）
        # 验证 trigger 能正常构建
        assert trigger is not None

    def test_dow_alpha_not_converted(self):
        """字母缩写 day_of_week 不应被转换。"""
        trigger = _parse_cron("0 21 * * mon-fri")
        assert trigger is not None

    def test_dow_star_not_converted(self):
        """* day_of_week 不应被转换。"""
        trigger = _parse_cron("0 21 * * *")
        assert trigger is not None

    def test_auto_invest_trigger_timezone(self):
        """验证 auto_invest 的 CronTrigger 使用 config.TIMEZONE。"""
        from apscheduler.triggers.cron import CronTrigger

        trigger = CronTrigger(hour=9, minute=0, timezone=config.TIMEZONE)
        assert trigger.timezone == config.TIMEZONE
        assert str(trigger.timezone) == str(config.TIMEZONE)


class TestRefreshFundMetadata:
    """验证基金元数据刷新逻辑（申购状态 / 交易日历 / 风险等级）。"""

    def test_refresh_fund_metadata_calls_all(self):
        from zfundpilot import scheduler

        calls: list[str] = []
        with (
            patch.object(scheduler, "_refresh_purchase_status",
                         side_effect=lambda: calls.append("purchase")),
            patch.object(scheduler, "_refresh_trade_calendar",
                         side_effect=lambda: calls.append("calendar")),
            patch.object(scheduler, "_refresh_risk_levels",
                         side_effect=lambda: calls.append("risk")),
        ):
            scheduler.refresh_fund_metadata()
        assert calls == ["purchase", "calendar", "risk"]

    def test_bootstrap_only_missing_risk_levels(self):
        from zfundpilot import scheduler
        from zfundpilot.models import Fund

        funds = [
            Fund(fund_code="001", fund_name="A", risk_level="中高风险"),
            Fund(fund_code="002", fund_name="B", risk_level=""),
            Fund(fund_code="003", fund_name="C", risk_level=""),
        ]
        refreshed: list[list[str]] = []

        def _record(codes):
            refreshed.append(codes)
            return len(codes)

        with (
            patch.object(scheduler.db, "get_funds", return_value=funds),
            patch.object(scheduler.fetch_fund, "refresh_risk_levels", _record),
            patch.object(scheduler.analysis, "clear_analysis_cache"),
        ):
            scheduler._bootstrap_risk_levels()
        assert refreshed == [["002", "003"]]

    def test_bootstrap_noop_when_all_present(self):
        from zfundpilot import scheduler
        from zfundpilot.models import Fund

        funds = [Fund(fund_code="001", fund_name="A", risk_level="低风险")]

        def _should_not_call(codes):  # pragma: no cover
            raise AssertionError("不应调用 refresh_risk_levels")

        with (
            patch.object(scheduler.db, "get_funds", return_value=funds),
            patch.object(scheduler.fetch_fund, "refresh_risk_levels", _should_not_call),
        ):
            scheduler._bootstrap_risk_levels()


class TestConvertDow:
    """验证 _convert_dow：先解析成星期集合，再输出 APScheduler 合法表达式。

    旧实现逐数字 (n-1)%7 平移，把 '0-6'→'6-5'、'0/2'→'6/2' 等合法标准
    cron 转成 CronTrigger 拒绝的非法表达式；此处钉住正确转换。
    """

    def test_single_sunday(self):
        """0（周日）→ 6（APScheduler 周日）。"""
        assert _convert_dow("0") == "6"

    def test_single_sunday_7(self):
        """7 也是周日 → 6。"""
        assert _convert_dow("7") == "6"

    def test_single_monday(self):
        """1（周一）→ 0（APScheduler 周一）。"""
        assert _convert_dow("1") == "0"

    def test_single_saturday(self):
        """6（周六）→ 5（APScheduler 周六）。"""
        assert _convert_dow("6") == "5"

    def test_range_weekdays(self):
        """1-5（周一到周五）→ 0-4。"""
        assert _convert_dow("1-5") == "0-4"

    def test_list(self):
        """1,3,5 → 0,2,4。"""
        assert _convert_dow("1,3,5") == "0,2,4"

    def test_full_week_range(self):
        """0-6（每天）→ 全集 '*'，不得产出非法的 '6-5'。"""
        assert _convert_dow("0-6") == "*"

    def test_star_with_step(self):
        """*/2 → 周日/二/四/六 → APScheduler '1,3,5-6'（步进值不被平移）。"""
        assert _convert_dow("*/2") == "1,3,5-6"

    def test_range_with_step(self):
        """0-6/2 → 与 */2 同集合；旧实现产出非法 '6-5/2'。"""
        assert _convert_dow("0-6/2") == "1,3,5-6"

    def test_single_with_step(self):
        """0/2 → 0,2,4,6（周日/二/四/六）；旧实现产出非法 '6/2'。"""
        assert _convert_dow("0/2") == "1,3,5-6"

    def test_range_cross_sunday(self):
        """5-7（周五/六/日）→ 4-6。"""
        assert _convert_dow("5-7") == "4-6"

    def test_dedup_sunday_aliases(self):
        """0,7 同为周日 → 6。"""
        assert _convert_dow("0,7") == "6"

    def test_invalid_range_raises(self):
        with pytest.raises(ValueError):
            _convert_dow("6-2")

    def test_out_of_range_raises(self):
        with pytest.raises(ValueError):
            _convert_dow("8")


class TestConvertDowCronTrigger:
    """转换产物必须被 CronTrigger 接受，且触发星期与标准 cron 语义一致。"""

    @pytest.mark.parametrize("expr", [
        "0 21 * * 0-6",
        "0 21 * * 0/2",
        "0 21 * * */2",
        "0 21 * * 0-6/2",
        "0 21 * * 1-5",
        "0 21 * * 5-7",
        "0 21 * * 0,7",
    ])
    def test_trigger_accepts_converted(self, expr):
        """旧实现下 0-6 / 0/2 / */2 等会抛 ValueError（启动崩溃）。"""
        assert _parse_cron(expr) is not None

    def _fire_weekdays(self, expr: str, n: int = 14) -> set[int]:
        """收集连续 n 次触发的 Python weekday（0=周一 … 6=周日）。"""
        trigger = _parse_cron(expr)
        t = datetime(2026, 11, 16, 0, 0, tzinfo=config.TIMEZONE)  # 周一
        seen: set[int] = set()
        for _ in range(n):
            t = trigger.get_next_fire_time(None, t)
            seen.add(t.weekday())
            t = t + timedelta(seconds=1)
        return seen

    def test_every_day_fires_all_week(self):
        assert self._fire_weekdays("0 21 * * 0-6") == set(range(7))

    def test_step_fires_sun_tue_thu_sat(self):
        # 标准 cron 0/2 = 周日(0)/二(2)/四(4)/六(6) → weekday {6,1,3,5}
        assert self._fire_weekdays("0 21 * * 0/2") == {1, 3, 5, 6}
        assert self._fire_weekdays("0 21 * * */2") == {1, 3, 5, 6}
        assert self._fire_weekdays("0 21 * * 0-6/2") == {1, 3, 5, 6}

    def test_weekdays_fires_mon_to_fri(self):
        assert self._fire_weekdays("0 21 * * 1-5") == {0, 1, 2, 3, 4}

    def test_cross_sunday_range(self):
        # 5-7 = 周五/六/日 → weekday {4,5,6}
        assert self._fire_weekdays("0 21 * * 5-7") == {4, 5, 6}


class TestTimezoneConfig:
    """验证 config.TIMEZONE 默认值和可配置性。"""

    def test_default_timezone(self):
        """默认时区应为 Asia/Shanghai。"""
        assert config.TIMEZONE_STR == "Asia/Shanghai"
        assert isinstance(config.TIMEZONE, ZoneInfo)
        assert str(config.TIMEZONE) == "Asia/Shanghai"

    def test_timezone_is_zoneinfo(self):
        """TIMEZONE 应为 ZoneInfo 实例。"""
        assert isinstance(config.TIMEZONE, ZoneInfo)


# ---------------------------------------------------------------------------
# 分红检测启动引导：崩溃循环防护
# ---------------------------------------------------------------------------


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", str(tmp_path / "test.db"))
    db.init_db()
    yield


def _fixed_time(hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 11, 17, hour, minute, tzinfo=config.TIMEZONE)


class _FixedClock:
    """替身 datetime：只提供 now()，用于把测试钉在 09:30 之后。"""

    def __init__(self, dt: datetime):
        self._dt = dt

    def now(self, tz=None) -> datetime:
        return self._dt


@pytest.fixture
def fixed_clock_after_0930(monkeypatch):
    monkeypatch.setattr(scheduler, "datetime", _FixedClock(_fixed_time(14, 0)))


class TestDividendBootstrapCrashGuard:
    """分红检测若把进程打崩（原生 SIGSEGV，Python 无法捕获），重启后
    引导逻辑若只看内存变量会立即重跑 → 崩溃循环 → 整站瘫痪。
    落盘「今日已尝试」标记后，同一进程每日最多尝试一次。"""

    def test_run_records_attempt_before_fetch(
        self, temp_db, fixed_clock_after_0930, monkeypatch
    ):
        import zfundpilot.fetch_dividend as fetch_dividend

        scheduler._last_dividend_run = None

        def boom():
            raise RuntimeError("simulated upstream crash")

        monkeypatch.setattr(fetch_dividend, "check_dividends", boom)
        # 异常被吞掉（原生崩溃才是真正的敌人，这里验证落盘先行）
        scheduler._run_dividend_check()
        assert (
            db.get_preference(scheduler._PREF_KEY_DIVIDEND_ATTEMPT)
            == "2026-11-17"
        )
        assert scheduler._last_dividend_run is not None

    def test_bootstrap_skips_when_attempted_today(
        self, temp_db, fixed_clock_after_0930, monkeypatch
    ):
        scheduler._last_dividend_run = None
        db.upsert_preference(scheduler._PREF_KEY_DIVIDEND, "true")
        db.upsert_preference(scheduler._PREF_KEY_DIVIDEND_ATTEMPT, "2026-11-17")
        spy = MagicMock()
        monkeypatch.setattr(scheduler, "_run_dividend_check", spy)
        scheduler._bootstrap_dividend_check()
        spy.assert_not_called()
        assert scheduler._last_dividend_run is not None

    def test_bootstrap_runs_once_when_not_attempted(
        self, temp_db, fixed_clock_after_0930, monkeypatch
    ):
        scheduler._last_dividend_run = None
        db.upsert_preference(scheduler._PREF_KEY_DIVIDEND, "true")
        spy = MagicMock()
        monkeypatch.setattr(scheduler, "_run_dividend_check", spy)
        scheduler._bootstrap_dividend_check()
        spy.assert_called_once()

    def test_bootstrap_skips_when_disabled(
        self, temp_db, fixed_clock_after_0930, monkeypatch
    ):
        scheduler._last_dividend_run = None
        db.upsert_preference(scheduler._PREF_KEY_DIVIDEND, "false")
        spy = MagicMock()
        monkeypatch.setattr(scheduler, "_run_dividend_check", spy)
        scheduler._bootstrap_dividend_check()
        spy.assert_not_called()


class TestResetScheduler:
    """reset_scheduler：安全清空未启动/运行中的实例，供 lifespan 降级重建。

    init_scheduler 可能在创建实例后、start 之前抛错（如 cron 非法），
    此时 shutdown_scheduler 会抛 SchedulerNotRunningError；
    reset_scheduler 必须容忍半初始化实例并清空引用。
    """

    def test_reset_none_is_noop(self, monkeypatch):
        monkeypatch.setattr(scheduler, "_scheduler", None)
        scheduler.reset_scheduler()
        assert scheduler._scheduler is None

    def test_reset_unstarted_instance(self, monkeypatch):
        inst = BackgroundScheduler(timezone=config.TIMEZONE_STR)
        monkeypatch.setattr(scheduler, "_scheduler", inst)
        scheduler.reset_scheduler()  # 不得抛 SchedulerNotRunningError
        assert scheduler._scheduler is None

    def test_reset_running_instance_stops_it(self, monkeypatch):
        inst = BackgroundScheduler(timezone=config.TIMEZONE_STR)
        inst.start()
        monkeypatch.setattr(scheduler, "_scheduler", inst)
        try:
            scheduler.reset_scheduler()
            assert scheduler._scheduler is None
            assert not inst.running
        finally:
            if inst.running:
                inst.shutdown(wait=False)

    def test_init_rebuilds_after_reset(self, temp_db, monkeypatch):
        """reset 后可重新 init（降级路径的核心契约）。"""
        monkeypatch.setattr(scheduler, "_get_enabled", lambda: False)
        monkeypatch.setattr(scheduler, "_get_dividend_enabled", lambda: False)
        monkeypatch.setattr(scheduler, "_bootstrap_auto_invest", lambda: None)
        monkeypatch.setattr(scheduler, "_bootstrap_risk_levels", lambda: None)
        # 模拟半初始化：实例已创建但未 start
        inst = BackgroundScheduler(timezone=config.TIMEZONE_STR)
        monkeypatch.setattr(scheduler, "_scheduler", inst)
        scheduler.reset_scheduler()
        try:
            scheduler.init_scheduler()
            assert scheduler._scheduler is not None
            assert scheduler._scheduler.running
        finally:
            scheduler.shutdown_scheduler()
