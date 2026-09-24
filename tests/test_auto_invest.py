"""定投计划执行逻辑测试。

验证：
1. execute_plan 在 15:00 前不加 T+1 标记（用当天净值）
2. execute_plan 在 15:00 后加 T+1 标记（用次日净值）
3. 边界情况：15:00 整算 T+1，14:59 不算
4. 手动执行不更新 next_run
5. calculate_next_run 各频率计算正确
6. _next_trading_day 周末跳过
7. 错过期不追补（锚定 today）
"""
from datetime import datetime
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

from zfundpilot.auto_invest import (
    _next_trading_day,
    calculate_next_run,
    execute_plan,
    run_all_due,
)
from zfundpilot.models import Fund

_TZ = ZoneInfo("Asia/Shanghai")


def _make_plan(**overrides) -> dict:
    base = {
        "id": 1,
        "fund_code": "001",
        "amount": 1000,
        "cadence": "week",
        "day_of_week": 0,
        "day_of_month": None,
        "channel": "",
        "note": "定投",
        "enabled": 1,
        "last_run": None,
        "last_tx_id": None,
        "next_run": "2026-01-05",
    }
    base.update(overrides)
    return base


class _PatchEnv:
    """统一 patch datetime + db + fetch_fund + analysis。"""

    def __init__(self, mock_dt: datetime):
        self._patches: list = []
        self._dt = mock_dt

    def __enter__(self):
        dt_patch = patch("zfundpilot.auto_invest.datetime")
        mock_datetime = dt_patch.start()
        mock_datetime.now.return_value = self._dt
        mock_datetime.strptime = datetime.strptime
        mock_datetime.side_effect = lambda *a, **kw: datetime(*a, **kw)
        self._patches.append(dt_patch)

        db_patch = patch("zfundpilot.auto_invest.db")
        self.mock_db = db_patch.start()
        self.mock_db.add_transaction.return_value = 42
        self.mock_db.update_auto_invest_plan = MagicMock()
        self.mock_db.get_auto_invest_plan.return_value = None  # will be set per test
        self._patches.append(db_patch)

        fee_patch = patch("zfundpilot.auto_invest.fetch_fund")
        self.mock_fetch = fee_patch.start()
        self.mock_fetch.calc_purchase_fee.return_value = MagicMock(fee=1.5)
        self._patches.append(fee_patch)

        analysis_patch = patch("zfundpilot.auto_invest.analysis")
        self.mock_analysis = analysis_patch.start()
        self.mock_analysis.clear_analysis_cache = MagicMock()
        self._patches.append(analysis_patch)

        return self

    def __exit__(self, *args):
        for p in reversed(self._patches):
            p.stop()


class TestExecutePlanT1Logic:
    """验证 execute_plan 的 15:00 T+1 判定逻辑。"""

    def test_before_15_no_t1(self):
        """09:00 执行 → is_t1=False。"""
        mock_dt = datetime(2026, 1, 5, 9, 0, tzinfo=_TZ)
        plan = _make_plan()
        with _PatchEnv(mock_dt) as env:
            env.mock_db.get_auto_invest_plan.return_value = plan
            result = execute_plan(plan, manual=True)
            assert result["after_three"] is False
            assert result["ok"] is True
            tx = env.mock_db.add_transaction.call_args[0][0]
            assert tx.note == "定投"
            assert tx.is_t1 is False
            assert tx.nav is None
            assert tx.shares is None

    def test_after_15_adds_t1(self):
        """20:00 执行 → is_t1=True。"""
        mock_dt = datetime(2026, 1, 5, 20, 0, tzinfo=_TZ)
        plan = _make_plan()
        with _PatchEnv(mock_dt) as env:
            env.mock_db.get_auto_invest_plan.return_value = plan
            result = execute_plan(plan, manual=True)
            assert result["after_three"] is True
            tx = env.mock_db.add_transaction.call_args[0][0]
            assert tx.is_t1 is True
            assert tx.nav is None

    def test_boundary_15_is_t1(self):
        """15:00 整 → 算 T+1（边界）。"""
        mock_dt = datetime(2026, 1, 5, 15, 0, tzinfo=_TZ)
        plan = _make_plan()
        with _PatchEnv(mock_dt) as env:
            env.mock_db.get_auto_invest_plan.return_value = plan
            result = execute_plan(plan, manual=True)
            assert result["after_three"] is True
            tx = env.mock_db.add_transaction.call_args[0][0]
            assert tx.is_t1 is True

    def test_boundary_14_59_no_t1(self):
        """14:59 → 不算 T+1（边界）。"""
        mock_dt = datetime(2026, 1, 5, 14, 59, tzinfo=_TZ)
        plan = _make_plan()
        with _PatchEnv(mock_dt) as env:
            env.mock_db.get_auto_invest_plan.return_value = plan
            result = execute_plan(plan, manual=True)
            assert result["after_three"] is False
            tx = env.mock_db.add_transaction.call_args[0][0]
            assert tx.is_t1 is False

    def test_note_preserved_with_t1(self):
        """note 不被 T+1 标记污染，is_t1 独立记录。"""
        mock_dt = datetime(2026, 1, 5, 20, 0, tzinfo=_TZ)
        plan = _make_plan(note="加仓")
        with _PatchEnv(mock_dt) as env:
            env.mock_db.get_auto_invest_plan.return_value = plan
            result = execute_plan(plan, manual=True)
            assert result["after_three"] is True
            tx = env.mock_db.add_transaction.call_args[0][0]
            assert tx.note == "加仓"
            assert tx.is_t1 is True


class TestExecutePlanManual:
    """验证手动/自动执行的 next_run 更新逻辑。"""

    def test_manual_no_next_run_update(self):
        """手动执行不调用 update_auto_invest_plan 更新 next_run。"""
        mock_dt = datetime(2026, 1, 5, 9, 0, tzinfo=_TZ)
        plan = _make_plan()
        with _PatchEnv(mock_dt) as env:
            env.mock_db.get_auto_invest_plan.return_value = plan
            execute_plan(plan, manual=True)
            assert env.mock_db.update_auto_invest_plan.call_count == 1
            call = env.mock_db.update_auto_invest_plan.call_args
            assert "next_run" not in call.kwargs

    def test_auto_updates_next_run(self):
        """自动执行调用 update_auto_invest_plan 一次（last_run + next_run 原子写入）。"""
        mock_dt = datetime(2026, 1, 5, 9, 0, tzinfo=_TZ)
        plan = _make_plan()
        with _PatchEnv(mock_dt) as env:
            env.mock_db.get_auto_invest_plan.return_value = plan
            env.mock_db.get_nav_on_or_after.return_value = {"date": "2026-01-12"}
            execute_plan(plan, manual=False)
            assert env.mock_db.update_auto_invest_plan.call_count == 1
            call = env.mock_db.update_auto_invest_plan.call_args
            assert "next_run" in call.kwargs
            assert "last_run" in call.kwargs


# ---------------------------------------------------------------------------
# calculate_next_run 测试
# ---------------------------------------------------------------------------
class TestCalculateNextRun:
    """验证 calculate_next_run 各频率 + 周末跳过 + 错过期不追补。"""

    def test_daily_with_nav(self):
        """daily 计划有净值数据 → 返回下一个交易日。"""
        with _PatchEnv(datetime(2026, 1, 5, 9, 0, tzinfo=_TZ)) as env:
            env.mock_db.get_nav_on_or_after.return_value = {"date": "2026-01-06"}
            plan = _make_plan(cadence="daily", next_run="2026-01-05")
            result = calculate_next_run(plan, from_date="2026-01-05")
            assert result == "2026-01-06"

    def test_daily_weekend_skip(self):
        """daily 计划周五 → 周六无净值 → 跳到周一。"""
        with _PatchEnv(datetime(2026, 1, 5, 9, 0, tzinfo=_TZ)) as env:
            env.mock_db.get_nav_on_or_after.return_value = None
            plan = _make_plan(cadence="daily", next_run="2026-01-09")
            result = calculate_next_run(plan, from_date="2026-01-09")
            assert result == "2026-01-12"  # 周五+1=周六 → skip → 周一

    def test_week_cadence(self):
        """week 计划 day_of_week=0（周一）→ 下一个周一。"""
        with _PatchEnv(datetime(2026, 1, 5, 9, 0, tzinfo=_TZ)) as env:
            env.mock_db.get_nav_on_or_after.return_value = None
            plan = _make_plan(cadence="week", day_of_week=0, next_run="2026-01-05")
            result = calculate_next_run(plan, from_date="2026-01-05")
            assert result == "2026-01-12"  # 1/5 周一 → 下周一 1/12

    def test_month_cadence(self):
        """month 计划 day_of_month=15, from=1/5 → 当月 1/15（周四, 无需顺延）。"""
        with _PatchEnv(datetime(2026, 1, 5, 9, 0, tzinfo=_TZ)) as env:
            env.mock_db.get_nav_on_or_after.return_value = None
            plan = _make_plan(cadence="month", day_of_month=15, next_run="2026-01-05")
            result = calculate_next_run(plan, from_date="2026-01-05")
            assert result == "2026-01-15"  # 1/15 周四

    def test_month_past_day_goes_next_month(self):
        """month 计划 day_of_month=5, from=1/10 → 5 号已过 → 下月 2/5（周四）。"""
        with _PatchEnv(datetime(2026, 1, 10, 9, 0, tzinfo=_TZ)) as env:
            env.mock_db.get_nav_on_or_after.return_value = None
            plan = _make_plan(cadence="month", day_of_month=5, next_run="2026-01-10")
            result = calculate_next_run(plan, from_date="2026-01-10")
            assert result == "2026-02-05"  # 2/5 周四

    def test_month_end_clamp(self):
        """month 计划 day_of_month=31, from=1/5 → 当月 1/31（周六 → 顺延到 2/2 周一）。"""
        with _PatchEnv(datetime(2026, 1, 5, 9, 0, tzinfo=_TZ)) as env:
            env.mock_db.get_nav_on_or_after.return_value = None
            plan = _make_plan(cadence="month", day_of_month=31, next_run="2026-01-05")
            result = calculate_next_run(plan, from_date="2026-01-05")
            assert result == "2026-02-02"  # 1/31 周六 → 2/2 周一

    def test_catch_up_skip(self):
        """next_run 在过去 → 锚定 today，跳过错过的期数。"""
        with _PatchEnv(datetime(2026, 7, 30, 9, 0, tzinfo=_TZ)) as env:
            env.mock_db.get_nav_on_or_after.return_value = None
            plan = _make_plan(
                cadence="month", day_of_month=10,
                next_run="2026-05-10",  # 远在过去
            )
            result = calculate_next_run(plan)  # from_date=None → max(next_run, today)
            assert result == "2026-08-10"  # 从 today=7/30 算下月 10 号

    def test_week_missing_dow_returns_none(self):
        """week 计划 day_of_week=None → 返回 None。"""
        plan = _make_plan(cadence="week", day_of_week=None)
        assert calculate_next_run(plan, from_date="2026-01-05") is None

    def test_month_missing_dom_returns_none(self):
        """month 计划 day_of_month=None → 返回 None。"""
        plan = _make_plan(cadence="month", day_of_month=None)
        assert calculate_next_run(plan, from_date="2026-01-05") is None

    def test_unknown_cadence_returns_none(self):
        """未知 cadence → 返回 None。"""
        plan = _make_plan(cadence="hourly")
        assert calculate_next_run(plan, from_date="2026-01-05") is None


# ---------------------------------------------------------------------------
# _next_trading_day 测试
# ---------------------------------------------------------------------------
class TestNextTradingDay:
    """验证 _next_trading_day 周末跳过 + 净值数据 fallback。"""

    def test_with_nav_data(self):
        """有净值数据 → 返回净值日期。"""
        with patch("zfundpilot.auto_invest.db") as mock_db:
            mock_db.get_nav_on_or_after.return_value = {"date": "2026-01-06"}
            result = _next_trading_day("001", "2026-01-05")
            assert result == "2026-01-06"

    def test_saturday_skips_to_monday(self):
        """周六无净值数据 → 跳到周一。"""
        with patch("zfundpilot.auto_invest.db") as mock_db:
            mock_db.get_nav_on_or_after.return_value = None
            result = _next_trading_day("001", "2026-01-03")  # 2026-01-03 是周六
            assert result == "2026-01-05"  # 周一

    def test_sunday_skips_to_monday(self):
        """周日无净值数据 → 跳到周一。"""
        with patch("zfundpilot.auto_invest.db") as mock_db:
            mock_db.get_nav_on_or_after.return_value = None
            result = _next_trading_day("001", "2026-01-04")  # 2026-01-04 是周日
            assert result == "2026-01-05"  # 周一

    def test_weekday_no_nav_returns_same(self):
        """工作日无净值数据 → 返回同一天。"""
        with patch("zfundpilot.auto_invest.db") as mock_db:
            mock_db.get_nav_on_or_after.return_value = None
            result = _next_trading_day("001", "2026-01-05")  # 周一
            assert result == "2026-01-05"


# ---------------------------------------------------------------------------
# _next_trading_day QDII 美股休市跳过测试
# ---------------------------------------------------------------------------
class TestNextTradingDayQDII:
    """验证 QDII 基金 _next_trading_day 跳过美股休市日。"""

    def test_qdii_skips_independence_day(self):
        """QDII 基金从独立日 observed(7/3 周五) 起 → 跳到 7/6 周一。"""
        with patch("zfundpilot.auto_invest.db") as mock_db:
            mock_db.get_fund.return_value = MagicMock(fund_type="QDII")
            mock_db.get_nav_on_or_after.return_value = None
            result = _next_trading_day("001", "2026-07-03")  # 独立日 observed
            assert result == "2026-07-06"  # 跳过 7/3(休市) + 7/4-5(周末)

    def test_qdii_skips_thanksgiving(self):
        """QDII 基金从感恩节(11/26 周四)起 → 跳到 11/27 周五。"""
        with patch("zfundpilot.auto_invest.db") as mock_db:
            mock_db.get_fund.return_value = MagicMock(fund_type="QDII")
            mock_db.get_nav_on_or_after.return_value = None
            result = _next_trading_day("001", "2026-11-26")
            assert result == "2026-11-27"

    def test_qdii_normal_day_unaffected(self):
        """QDII 基金在普通交易日 → 正常返回。"""
        with patch("zfundpilot.auto_invest.db") as mock_db:
            mock_db.get_fund.return_value = MagicMock(fund_type="QDII")
            mock_db.get_nav_on_or_after.return_value = None
            result = _next_trading_day("001", "2026-07-06")  # 周一，普通交易日
            assert result == "2026-07-06"

    def test_non_qdii_not_affected_by_us_holiday(self):
        """非 QDII 基金在美股休市日 → 不跳过（国内基金照常）。"""
        with patch("zfundpilot.auto_invest.db") as mock_db:
            mock_db.get_fund.return_value = MagicMock(fund_type="指数型")
            mock_db.get_nav_on_or_after.return_value = None
            result = _next_trading_day("001", "2026-07-03")  # 独立日 observed
            assert result == "2026-07-03"  # 国内基金不跳美股休市


# ---------------------------------------------------------------------------
# run_all_due 休市/周末跳过测试
# ---------------------------------------------------------------------------
class TestRunAllDueHolidayGate:
    """验证 run_all_due 在美股休市/周末跳过定投执行。"""

    def test_qdii_skipped_on_us_holiday(self):
        """QDII 计划在美股休市日(7/3) → 跳过，不建仓。"""
        mock_dt = datetime(2026, 7, 3, 9, 0, tzinfo=_TZ)  # 独立日 observed 周五
        plan = _make_plan(fund_code="001", next_run="2026-07-03", last_run=None)
        with _PatchEnv(mock_dt) as env:
            env.mock_db.get_due_auto_invest_plans.return_value = [plan]
            env.mock_db.get_fund.return_value = MagicMock(fund_type="QDII")
            results = run_all_due()
        assert len(results) == 1
        assert results[0]["status"] == "holiday"
        assert results[0]["reason"] == "美股休市"
        env.mock_db.add_transaction.assert_not_called()

    def test_qdii_executes_on_normal_day(self):
        """QDII 计划在普通交易日(7/6 周一) → 正常执行。"""
        mock_dt = datetime(2026, 7, 6, 9, 0, tzinfo=_TZ)
        plan = _make_plan(fund_code="001", next_run="2026-07-06", last_run=None)
        with _PatchEnv(mock_dt) as env:
            env.mock_db.get_due_auto_invest_plans.return_value = [plan]
            env.mock_db.get_auto_invest_plan.return_value = plan
            env.mock_db.get_fund.return_value = MagicMock(fund_type="QDII")
            env.mock_db.get_nav_on_or_after.return_value = None
            results = run_all_due()
        assert results[0]["status"] == "success"
        env.mock_db.add_transaction.assert_called_once()

    def test_non_qdii_executes_on_us_holiday(self):
        """非 QDII 计划在美股休市日(7/3) → 照常执行（国内基金不受影响）。"""
        mock_dt = datetime(2026, 7, 3, 9, 0, tzinfo=_TZ)
        plan = _make_plan(fund_code="001", next_run="2026-07-03", last_run=None)
        with _PatchEnv(mock_dt) as env:
            env.mock_db.get_due_auto_invest_plans.return_value = [plan]
            env.mock_db.get_auto_invest_plan.return_value = plan
            env.mock_db.get_fund.return_value = MagicMock(fund_type="指数型")
            env.mock_db.get_nav_on_or_after.return_value = None
            results = run_all_due()
        assert results[0]["status"] == "success"
        env.mock_db.add_transaction.assert_called_once()

    def test_weekend_skipped(self):
        """所有基金遇周末(7/4 周六) → 跳过。"""
        mock_dt = datetime(2026, 7, 4, 9, 0, tzinfo=_TZ)
        plan = _make_plan(fund_code="001", next_run="2026-07-04", last_run=None)
        with _PatchEnv(mock_dt) as env:
            env.mock_db.get_due_auto_invest_plans.return_value = [plan]
            results = run_all_due()
        assert results[0]["status"] == "holiday"
        assert results[0]["reason"] == "周末"
        env.mock_db.add_transaction.assert_not_called()


# ---------------------------------------------------------------------------
# 申购状态可投性 gate 测试（暂停申购/限购/购买起点）
# ---------------------------------------------------------------------------
class TestPurchasableGate:
    """验证 execute_plan 依据申购状态跳过或告警。"""

    def test_suspended_skipped(self):
        """暂停申购 → 自动执行跳过，不建仓。"""
        mock_dt = datetime(2026, 1, 5, 9, 0, tzinfo=_TZ)
        plan = _make_plan(fund_code="160213", amount=1000)
        with _PatchEnv(mock_dt) as env:
            env.mock_db.get_auto_invest_plan.return_value = plan
            env.mock_db.get_fund.return_value = Fund(
                fund_code="160213", purchase_status="暂停申购"
            )
            result = execute_plan(plan, manual=False)
        assert result["ok"] is False
        assert result["skipped"] is True
        assert result["skip_code"] == "suspended"
        env.mock_db.add_transaction.assert_not_called()

    def test_closed_period_skipped(self):
        """封闭期 → 跳过。"""
        mock_dt = datetime(2026, 1, 5, 9, 0, tzinfo=_TZ)
        plan = _make_plan(fund_code="001", amount=1000)
        with _PatchEnv(mock_dt) as env:
            env.mock_db.get_auto_invest_plan.return_value = plan
            env.mock_db.get_fund.return_value = Fund(
                fund_code="001", purchase_status="封闭期"
            )
            result = execute_plan(plan, manual=False)
        assert result["skip_code"] == "suspended"

    def test_limit_exceeded_skipped(self):
        """限大额且金额超日累计限额 → 跳过。"""
        mock_dt = datetime(2026, 1, 5, 9, 0, tzinfo=_TZ)
        plan = _make_plan(fund_code="001", amount=1000)
        with _PatchEnv(mock_dt) as env:
            env.mock_db.get_auto_invest_plan.return_value = plan
            env.mock_db.get_fund.return_value = Fund(
                fund_code="001", purchase_status="限大额", daily_limit=100
            )
            result = execute_plan(plan, manual=False)
        assert result["skip_code"] == "limit_exceeded"
        assert result["detail"]["daily_limit"] == 100
        env.mock_db.add_transaction.assert_not_called()

    def test_limit_not_exceeded_executes(self):
        """限大额但金额未超限 → 正常执行。"""
        mock_dt = datetime(2026, 1, 5, 9, 0, tzinfo=_TZ)
        plan = _make_plan(fund_code="001", amount=1000)
        with _PatchEnv(mock_dt) as env:
            env.mock_db.get_auto_invest_plan.return_value = plan
            env.mock_db.get_fund.return_value = Fund(
                fund_code="001", purchase_status="限大额", daily_limit=2000
            )
            env.mock_db.get_nav_on_or_after.return_value = None
            result = execute_plan(plan, manual=False)
        assert result["ok"] is True
        env.mock_db.add_transaction.assert_called_once()

    def test_below_minimum_skipped(self):
        """金额低于购买起点 → 跳过。"""
        mock_dt = datetime(2026, 1, 5, 9, 0, tzinfo=_TZ)
        plan = _make_plan(fund_code="001", amount=100)
        with _PatchEnv(mock_dt) as env:
            env.mock_db.get_auto_invest_plan.return_value = plan
            env.mock_db.get_fund.return_value = Fund(
                fund_code="001", purchase_status="开放申购", min_purchase=1000
            )
            result = execute_plan(plan, manual=False)
        assert result["skip_code"] == "below_minimum"
        env.mock_db.add_transaction.assert_not_called()

    def test_open_purchase_executes(self):
        """开放申购且无限额 → 正常执行。"""
        mock_dt = datetime(2026, 1, 5, 9, 0, tzinfo=_TZ)
        plan = _make_plan(fund_code="001", amount=1000)
        with _PatchEnv(mock_dt) as env:
            env.mock_db.get_auto_invest_plan.return_value = plan
            env.mock_db.get_fund.return_value = Fund(
                fund_code="001", purchase_status="开放申购"
            )
            env.mock_db.get_nav_on_or_after.return_value = None
            result = execute_plan(plan, manual=False)
        assert result["ok"] is True
        assert result["warnings"] == []

    def test_unknown_status_executes(self):
        """状态未知（空）→ 放行，避免误伤。"""
        mock_dt = datetime(2026, 1, 5, 9, 0, tzinfo=_TZ)
        plan = _make_plan(fund_code="001", amount=1000)
        with _PatchEnv(mock_dt) as env:
            env.mock_db.get_auto_invest_plan.return_value = plan
            env.mock_db.get_fund.return_value = Fund(fund_code="001")
            env.mock_db.get_nav_on_or_after.return_value = None
            result = execute_plan(plan, manual=False)
        assert result["ok"] is True

    def test_manual_suspended_warns_but_executes(self):
        """手动执行遇暂停申购 → 仍建仓但带 warnings。"""
        mock_dt = datetime(2026, 1, 5, 9, 0, tzinfo=_TZ)
        plan = _make_plan(fund_code="001", amount=1000)
        with _PatchEnv(mock_dt) as env:
            env.mock_db.get_auto_invest_plan.return_value = plan
            env.mock_db.get_fund.return_value = Fund(
                fund_code="001", purchase_status="暂停申购"
            )
            result = execute_plan(plan, manual=True)
        assert result["ok"] is True
        assert result["warnings"] == ["suspended"]
        env.mock_db.add_transaction.assert_called_once()

    def test_run_all_due_suspended_status(self):
        """run_all_due 对暂停申购计划标记 status=suspended 不建仓。"""
        mock_dt = datetime(2026, 7, 6, 9, 0, tzinfo=_TZ)  # 周一
        plan = _make_plan(fund_code="001", next_run="2026-07-06", last_run=None)
        with _PatchEnv(mock_dt) as env:
            env.mock_db.get_due_auto_invest_plans.return_value = [plan]
            env.mock_db.get_auto_invest_plan.return_value = plan
            env.mock_db.get_fund.return_value = Fund(
                fund_code="001", purchase_status="暂停申购"
            )
            results = run_all_due()
        assert results[0]["status"] == "suspended"
        env.mock_db.add_transaction.assert_not_called()
