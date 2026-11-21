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
import sqlite3
from datetime import datetime
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

import pytest

from zfundpilot import auto_invest, config, db, fetch_fund
from zfundpilot.auto_invest import (
    _next_trading_day,
    calculate_next_run,
    calculate_next_run_conn,
    execute_plan,
    run_all_due,
)
from zfundpilot.fetch_fund import CalcFeeResult
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
        self.mock_db.insert_transaction.return_value = 42
        self.mock_db.update_auto_invest_plan_conn = MagicMock()
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
            tx = env.mock_db.insert_transaction.call_args[0][1]
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
            tx = env.mock_db.insert_transaction.call_args[0][1]
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
            tx = env.mock_db.insert_transaction.call_args[0][1]
            assert tx.is_t1 is True

    def test_boundary_14_59_no_t1(self):
        """14:59 → 不算 T+1（边界）。"""
        mock_dt = datetime(2026, 1, 5, 14, 59, tzinfo=_TZ)
        plan = _make_plan()
        with _PatchEnv(mock_dt) as env:
            env.mock_db.get_auto_invest_plan.return_value = plan
            result = execute_plan(plan, manual=True)
            assert result["after_three"] is False
            tx = env.mock_db.insert_transaction.call_args[0][1]
            assert tx.is_t1 is False

    def test_note_preserved_with_t1(self):
        """note 不被 T+1 标记污染，is_t1 独立记录。"""
        mock_dt = datetime(2026, 1, 5, 20, 0, tzinfo=_TZ)
        plan = _make_plan(note="加仓")
        with _PatchEnv(mock_dt) as env:
            env.mock_db.get_auto_invest_plan.return_value = plan
            result = execute_plan(plan, manual=True)
            assert result["after_three"] is True
            tx = env.mock_db.insert_transaction.call_args[0][1]
            assert tx.note == "加仓"
            assert tx.is_t1 is True


class TestExecutePlanManual:
    """验证手动/自动执行的 next_run 更新逻辑。"""

    def test_manual_no_next_run_update(self):
        """手动执行不更新 next_run（仅 last_run/last_tx_id）。"""
        mock_dt = datetime(2026, 1, 5, 9, 0, tzinfo=_TZ)
        plan = _make_plan()
        with _PatchEnv(mock_dt) as env:
            env.mock_db.get_auto_invest_plan.return_value = plan
            execute_plan(plan, manual=True)
            assert env.mock_db.update_auto_invest_plan_conn.call_count == 1
            call = env.mock_db.update_auto_invest_plan_conn.call_args
            assert "next_run" not in call.kwargs

    def test_auto_updates_next_run(self):
        """自动执行在写事务内更新计划一次（last_run + next_run 原子写入）。"""
        mock_dt = datetime(2026, 1, 5, 9, 0, tzinfo=_TZ)
        plan = _make_plan()
        with _PatchEnv(mock_dt) as env:
            env.mock_db.get_auto_invest_plan.return_value = plan
            env.mock_db.get_nav_on_or_after.return_value = {"date": "2026-01-12"}
            execute_plan(plan, manual=False)
            assert env.mock_db.update_auto_invest_plan_conn.call_count == 1
            call = env.mock_db.update_auto_invest_plan_conn.call_args
            assert "next_run" in call.kwargs
            assert "last_run" in call.kwargs

    def test_auto_biweek_next_run_plus_14(self):
        """biweek 自动执行后 next_run = 执行日+14（回归：旧实现误成 +21）。"""
        mock_dt = datetime(2026, 1, 5, 9, 0, tzinfo=_TZ)  # 周一
        plan = _make_plan(cadence="biweek", day_of_week=0,
                          last_run=None, next_run="2026-01-05")
        with _PatchEnv(mock_dt) as env:
            env.mock_db.get_auto_invest_plan.return_value = plan
            env.mock_db.get_nav_on_or_after.return_value = None
            execute_plan(plan, manual=False)
            call = env.mock_db.update_auto_invest_plan_conn.call_args
            assert call.kwargs["next_run"] == "2026-01-19"

    def test_tx_and_bookkeeping_share_one_write_transaction(self):
        """流水插入与计划更新复用同一 write=True 连接（原子提交）。"""
        mock_dt = datetime(2026, 1, 5, 9, 0, tzinfo=_TZ)
        plan = _make_plan()
        with _PatchEnv(mock_dt) as env:
            env.mock_db.get_auto_invest_plan.return_value = plan
            env.mock_db.get_nav_on_or_after.return_value = None
            execute_plan(plan, manual=False)
            env.mock_db.get_connection.assert_called_once_with(write=True)
            conn = env.mock_db.get_connection.return_value.__enter__.return_value
            assert env.mock_db.insert_transaction.call_args[0][0] is conn
            assert env.mock_db.update_auto_invest_plan_conn.call_args[0][0] is conn

    def test_audit_shares_write_transaction_when_context_given(self):
        """传入 audit 上下文：执行审计与流水/簿记复用同一写事务连接。"""
        mock_dt = datetime(2026, 1, 5, 9, 0, tzinfo=_TZ)
        plan = _make_plan()
        with _PatchEnv(mock_dt) as env:
            env.mock_db.get_auto_invest_plan.return_value = plan
            execute_plan(plan, manual=True,
                         audit={"ip": "1.2.3.4", "username": "admin"})
            env.mock_db.log_audit.assert_called_once()
            call = env.mock_db.log_audit.call_args
            assert call.args[0] == "auto_invest_execute"
            assert call.kwargs["ip"] == "1.2.3.4"
            assert call.kwargs["username"] == "admin"
            assert call.kwargs["detail"]["plan_id"] == plan["id"]
            assert call.kwargs["detail"]["tx_id"] == 42
            conn = env.mock_db.get_connection.return_value.__enter__.return_value
            assert call.kwargs["conn"] is conn  # 同事务原子提交

    def test_no_audit_when_context_absent(self):
        """不传 audit：execute_plan 不写审计（兼容旧行为，由调用方记录）。"""
        mock_dt = datetime(2026, 1, 5, 9, 0, tzinfo=_TZ)
        plan = _make_plan()
        with _PatchEnv(mock_dt) as env:
            env.mock_db.get_auto_invest_plan.return_value = plan
            execute_plan(plan, manual=True)
            env.mock_db.log_audit.assert_not_called()


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
# biweek 双周调度测试（回归：重锚误成 +21 天）
# ---------------------------------------------------------------------------
class TestBiweekCadence:
    """验证 biweek 重锚口径：不早于 last_run+14 的第一个 dow。"""

    def test_reanchor_returns_plus_14_not_21(self):
        """last_run 落在 dow 当天 → 下次 = last_run+14（旧实现误成 +21）。"""
        with _PatchEnv(datetime(2026, 1, 5, 9, 0, tzinfo=_TZ)) as env:
            env.mock_db.get_nav_on_or_after.return_value = None
            plan = _make_plan(cadence="biweek", day_of_week=0,
                              last_run="2026-01-05", next_run="2026-01-05")
            result = calculate_next_run(plan, from_date="2026-01-05")
            assert result == "2026-01-19"

    def test_first_run_without_last_run(self):
        """last_run 为空（尚未执行过）→ 按 week 口径取下一个 dow。"""
        with _PatchEnv(datetime(2026, 1, 5, 9, 0, tzinfo=_TZ)) as env:
            env.mock_db.get_nav_on_or_after.return_value = None
            plan = _make_plan(cadence="biweek", day_of_week=0, last_run=None)
            result = calculate_next_run(plan, from_date="2026-01-05")
            assert result == "2026-01-12"

    def test_deferred_last_run_anchors_to_next_dow(self):
        """last_run 因节假日顺延不在 dow（周二）→ 取不早于 +14 的首个周一。"""
        with _PatchEnv(datetime(2026, 1, 6, 9, 0, tzinfo=_TZ)) as env:
            env.mock_db.get_nav_on_or_after.return_value = None
            plan = _make_plan(cadence="biweek", day_of_week=0,
                              last_run="2026-01-06", next_run="2026-01-06")
            # last_run+14=1/20 周二 → 顺延到 1/26 周一
            result = calculate_next_run(plan, from_date="2026-01-06")
            assert result == "2026-01-26"

    def test_missed_periods_not_caught_up(self):
        """last_run 远在过去（错过期）→ 锚定 from_date，不追补。"""
        with _PatchEnv(datetime(2026, 1, 5, 9, 0, tzinfo=_TZ)) as env:
            env.mock_db.get_nav_on_or_after.return_value = None
            plan = _make_plan(cadence="biweek", day_of_week=0,
                              last_run="2025-12-01", next_run="2025-12-15")
            result = calculate_next_run(plan, from_date="2026-01-05")
            assert result == "2026-01-12"

    def test_holiday_defers_plus_14_candidate(self):
        """+14 候选日遇法定节假日 → 顺延到下一个交易日。"""
        with _PatchEnv(datetime(2026, 1, 5, 9, 0, tzinfo=_TZ)) as env:
            env.mock_db.is_trading_day.side_effect = (
                lambda ds: ds != "2026-01-19")
            env.mock_db.get_nav_on_or_after.return_value = None
            plan = _make_plan(cadence="biweek", day_of_week=0,
                              last_run="2026-01-05", next_run="2026-01-05")
            result = calculate_next_run(plan, from_date="2026-01-05")
            assert result == "2026-01-20"

    def test_conn_variant_matches_web(self):
        """连接感知版（提案审批路径）与 web 版口径一致。"""
        conn = MagicMock()
        with patch("zfundpilot.auto_invest.db") as mock_db:
            mock_db.get_fund_conn.return_value = None
            mock_db.is_trading_day_conn.return_value = True
            mock_db.get_nav_on_or_after_conn.return_value = None
            plan = _make_plan(cadence="biweek", day_of_week=0,
                              last_run="2026-01-05", next_run="2026-01-05")
            assert calculate_next_run_conn(
                conn, plan, from_date="2026-01-05") == "2026-01-19"
            plan["last_run"] = "2026-01-06"
            assert calculate_next_run_conn(
                conn, plan, from_date="2026-01-06") == "2026-01-26"


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
        env.mock_db.insert_transaction.assert_not_called()

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
        env.mock_db.insert_transaction.assert_called_once()

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
        env.mock_db.insert_transaction.assert_called_once()

    def test_weekend_skipped(self):
        """所有基金遇周末(7/4 周六) → 跳过。"""
        mock_dt = datetime(2026, 7, 4, 9, 0, tzinfo=_TZ)
        plan = _make_plan(fund_code="001", next_run="2026-07-04", last_run=None)
        with _PatchEnv(mock_dt) as env:
            env.mock_db.get_due_auto_invest_plans.return_value = [plan]
            results = run_all_due()
        assert results[0]["status"] == "holiday"
        assert results[0]["reason"] == "周末"
        env.mock_db.insert_transaction.assert_not_called()


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
        env.mock_db.insert_transaction.assert_not_called()

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
        env.mock_db.insert_transaction.assert_not_called()

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
        env.mock_db.insert_transaction.assert_called_once()

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
        env.mock_db.insert_transaction.assert_not_called()

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
        env.mock_db.insert_transaction.assert_called_once()

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
        env.mock_db.insert_transaction.assert_not_called()


# ---------------------------------------------------------------------------
# 国内法定节假日 gate 测试（A 股交易日历）
# ---------------------------------------------------------------------------
class TestTradingCalendarGate:
    """验证国内法定节假日（非交易日）跳过定投执行。"""

    def test_cn_holiday_skipped(self):
        """国庆假期（10-1 周四，工作日但非交易日）→ 跳过，不建仓。"""
        mock_dt = datetime(2026, 10, 1, 9, 0, tzinfo=_TZ)
        plan = _make_plan(fund_code="001", next_run="2026-10-01", last_run=None)
        holidays = {"2026-10-01", "2026-10-02", "2026-10-05", "2026-10-06", "2026-10-07"}
        with _PatchEnv(mock_dt) as env:
            env.mock_db.get_due_auto_invest_plans.return_value = [plan]
            env.mock_db.is_trading_day.side_effect = lambda ds: ds not in holidays
            results = run_all_due()
        assert len(results) == 1
        assert results[0]["status"] == "holiday"
        assert results[0]["reason"] == "非交易日"
        env.mock_db.insert_transaction.assert_not_called()

    def test_cn_trading_day_executes(self):
        """假期后首个交易日（10-8 周四）→ 正常执行。"""
        mock_dt = datetime(2026, 10, 8, 9, 0, tzinfo=_TZ)
        plan = _make_plan(fund_code="001", next_run="2026-09-30", last_run=None)
        with _PatchEnv(mock_dt) as env:
            env.mock_db.get_due_auto_invest_plans.return_value = [plan]
            env.mock_db.get_auto_invest_plan.return_value = plan
            env.mock_db.is_trading_day.return_value = True
            env.mock_db.get_nav_on_or_after.return_value = None
            results = run_all_due()
        assert results[0]["status"] == "success"
        env.mock_db.insert_transaction.assert_called_once()


class TestNextTradingDayCNCalendar:
    """验证 _next_trading_day 跳过国内法定节假日。"""

    def test_skips_cn_holiday(self):
        """从 10-1（国庆）起 → 跳到 10-8（假期后首个交易日）。"""
        with patch("zfundpilot.auto_invest.db") as mock_db:
            mock_db.is_trading_day.side_effect = (
                lambda ds: not ("2026-10-01" <= ds <= "2026-10-07")
            )
            mock_db.get_nav_on_or_after.return_value = None
            result = _next_trading_day("001", "2026-10-01")
        assert result == "2026-10-08"

    def test_normal_weekday_unaffected(self):
        """普通工作日（10-8）→ 正常返回。"""
        with patch("zfundpilot.auto_invest.db") as mock_db:
            mock_db.is_trading_day.return_value = True
            mock_db.get_nav_on_or_after.return_value = None
            result = _next_trading_day("001", "2026-10-08")
        assert result == "2026-10-08"


# ---------------------------------------------------------------------------
# execute_plan 原子性测试（真实 SQLite：流水与簿记同事务提交/回滚）
# ---------------------------------------------------------------------------
class TestExecutePlanAtomicity:
    """回归：买入流水已落库但计划簿记未推进 → 调度器/重试重复买入。"""

    @pytest.fixture
    def real_db(self, monkeypatch, tmp_path):
        monkeypatch.setattr(config, "DB_PATH", str(tmp_path / "auto.db"))
        db._trade_cal_cache = None
        db._trade_cal_max = None
        db.init_db()
        db.upsert_fund(Fund(fund_code="001", fund_name="测试基金"))
        monkeypatch.setattr(
            fetch_fund, "calc_purchase_fee",
            lambda code, amount: CalcFeeResult(fee=0.0, code="purchase_rate"))
        yield
        db._trade_cal_cache = None
        db._trade_cal_max = None

    def _fix_now(self, monkeypatch, dt: datetime) -> None:
        mock_dt = MagicMock()
        mock_dt.now.return_value = dt
        mock_dt.strptime = datetime.strptime
        monkeypatch.setattr(auto_invest, "datetime", mock_dt)

    def _make_plan(self, **kw) -> int:
        defaults = dict(fund_code="001", amount=1000.0, cadence="week",
                        day_of_week=0, next_run="2026-01-05")
        defaults.update(kw)
        return db.add_auto_invest_plan(**defaults)

    @staticmethod
    def _all_tx() -> list[dict]:
        with db.get_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM transactions ORDER BY id").fetchall()
        return [dict(r) for r in rows]

    def test_success_commits_tx_and_bookkeeping(self, real_db, monkeypatch):
        """成功执行：一笔买入 + last_run/last_tx_id/next_run 全部推进。"""
        self._fix_now(monkeypatch, datetime(2026, 1, 5, 9, 0, tzinfo=_TZ))
        plan_id = self._make_plan()
        result = execute_plan(db.get_auto_invest_plan(plan_id), manual=False)
        assert result["ok"] is True
        rows = self._all_tx()
        assert len(rows) == 1
        assert rows[0]["date"] == "2026-01-05"
        assert rows[0]["action"] == "buy"
        plan = db.get_auto_invest_plan(plan_id)
        assert plan["last_run"] == "2026-01-05"
        assert plan["last_tx_id"] == rows[0]["id"]
        assert plan["next_run"] == "2026-01-12"

    def test_biweek_execution_next_run_plus_14(self, real_db, monkeypatch):
        """biweek 真实执行后 next_run = 执行日+14（不是 +21）。"""
        self._fix_now(monkeypatch, datetime(2026, 1, 5, 9, 0, tzinfo=_TZ))
        plan_id = self._make_plan(cadence="biweek")
        result = execute_plan(db.get_auto_invest_plan(plan_id), manual=False)
        assert result["ok"] is True
        assert db.get_auto_invest_plan(plan_id)["next_run"] == "2026-01-19"

    def test_plan_update_failure_rolls_back_buy(self, real_db, monkeypatch):
        """计划更新失败 → 买入流水整体回滚，计划簿记不变。"""
        self._fix_now(monkeypatch, datetime(2026, 1, 5, 9, 0, tzinfo=_TZ))
        plan_id = self._make_plan()

        def _boom(conn, pid, **kwargs):
            raise sqlite3.OperationalError("disk I/O error")

        monkeypatch.setattr(db, "update_auto_invest_plan_conn", _boom)
        with pytest.raises(sqlite3.OperationalError):
            execute_plan(db.get_auto_invest_plan(plan_id), manual=False)
        assert self._all_tx() == []
        plan = db.get_auto_invest_plan(plan_id)
        assert plan["last_run"] is None
        assert plan["last_tx_id"] is None
        assert plan["next_run"] == "2026-01-05"

    def test_retry_after_failure_no_duplicate(self, real_db, monkeypatch):
        """中途失败后重试成功 → 账本仅一笔买入（不重复建仓）。"""
        self._fix_now(monkeypatch, datetime(2026, 1, 5, 9, 0, tzinfo=_TZ))
        plan_id = self._make_plan()

        def _boom(conn, pid, **kwargs):
            raise sqlite3.OperationalError("database is locked")

        with monkeypatch.context() as m:
            m.setattr(db, "update_auto_invest_plan_conn", _boom)
            with pytest.raises(sqlite3.OperationalError):
                execute_plan(db.get_auto_invest_plan(plan_id), manual=False)
        # 故障恢复后重试（last_run 未推进，当日防重不生效，靠原子性兜底）
        result = execute_plan(db.get_auto_invest_plan(plan_id), manual=False)
        assert result["ok"] is True
        assert len(self._all_tx()) == 1

    def test_next_run_failure_writes_nothing(self, real_db, monkeypatch):
        """next_run 计算失败 → 不产生任何流水（先算后写）。"""
        self._fix_now(monkeypatch, datetime(2026, 1, 5, 9, 0, tzinfo=_TZ))
        plan_id = self._make_plan()

        def _boom(plan, from_date=None):
            raise RuntimeError("calendar broken")

        monkeypatch.setattr(auto_invest, "calculate_next_run", _boom)
        with pytest.raises(RuntimeError):
            execute_plan(db.get_auto_invest_plan(plan_id), manual=False)
        assert self._all_tx() == []
        assert db.get_auto_invest_plan(plan_id)["last_run"] is None
