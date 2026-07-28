"""定投计划执行逻辑测试。

验证：
1. execute_plan 在 15:00 前不加 T+1 标记（用当天净值）
2. execute_plan 在 15:00 后加 T+1 标记（用次日净值）
3. 边界情况：15:00 整算 T+1，14:59 不算
4. 手动执行不更新 next_run
"""
from datetime import datetime
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

from zfundpilot.auto_invest import execute_plan

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
        """09:00 执行 → note 不含 T+1确认。"""
        mock_dt = datetime(2026, 1, 5, 9, 0, tzinfo=_TZ)
        with _PatchEnv(mock_dt) as env:
            result = execute_plan(_make_plan(), manual=True)
            assert result["after_three"] is False
            assert result["ok"] is True
            tx = env.mock_db.add_transaction.call_args[0][0]
            assert tx.note == "定投"
            assert "T+1确认" not in tx.note
            assert tx.nav is None
            assert tx.shares is None

    def test_after_15_adds_t1(self):
        """20:00 执行 → note 含 T+1确认。"""
        mock_dt = datetime(2026, 1, 5, 20, 0, tzinfo=_TZ)
        with _PatchEnv(mock_dt) as env:
            result = execute_plan(_make_plan(), manual=True)
            assert result["after_three"] is True
            tx = env.mock_db.add_transaction.call_args[0][0]
            assert "T+1确认" in tx.note
            assert tx.nav is None

    def test_boundary_15_is_t1(self):
        """15:00 整 → 算 T+1（边界）。"""
        mock_dt = datetime(2026, 1, 5, 15, 0, tzinfo=_TZ)
        with _PatchEnv(mock_dt) as env:
            result = execute_plan(_make_plan(), manual=True)
            assert result["after_three"] is True
            tx = env.mock_db.add_transaction.call_args[0][0]
            assert "T+1确认" in tx.note

    def test_boundary_14_59_no_t1(self):
        """14:59 → 不算 T+1（边界）。"""
        mock_dt = datetime(2026, 1, 5, 14, 59, tzinfo=_TZ)
        with _PatchEnv(mock_dt) as env:
            result = execute_plan(_make_plan(), manual=True)
            assert result["after_three"] is False
            tx = env.mock_db.add_transaction.call_args[0][0]
            assert "T+1确认" not in tx.note

    def test_note_already_has_t1(self):
        """note 已含 T+1确认 时不重复添加。"""
        mock_dt = datetime(2026, 1, 5, 20, 0, tzinfo=_TZ)
        with _PatchEnv(mock_dt) as env:
            result = execute_plan(_make_plan(note="定投 | T+1确认"), manual=True)
            assert result["after_three"] is True
            tx = env.mock_db.add_transaction.call_args[0][0]
            assert tx.note == "定投 | T+1确认"
            assert tx.note.count("T+1确认") == 1


class TestExecutePlanManual:
    """验证手动/自动执行的 next_run 更新逻辑。"""

    def test_manual_no_next_run_update(self):
        """手动执行不调用 update_auto_invest_plan 更新 next_run。"""
        mock_dt = datetime(2026, 1, 5, 9, 0, tzinfo=_TZ)
        with _PatchEnv(mock_dt) as env:
            execute_plan(_make_plan(), manual=True)
            assert env.mock_db.update_auto_invest_plan.call_count == 1
            call = env.mock_db.update_auto_invest_plan.call_args
            assert "next_run" not in call.kwargs

    def test_auto_updates_next_run(self):
        """自动执行调用 update_auto_invest_plan 两次（last_run + next_run）。"""
        mock_dt = datetime(2026, 1, 5, 9, 0, tzinfo=_TZ)
        with _PatchEnv(mock_dt) as env:
            env.mock_db.get_nav_on_or_after.return_value = {"date": "2026-01-12"}
            execute_plan(_make_plan(), manual=False)
            assert env.mock_db.update_auto_invest_plan.call_count == 2
            second_call = env.mock_db.update_auto_invest_plan.call_args_list[1]
            assert "next_run" in second_call.kwargs
