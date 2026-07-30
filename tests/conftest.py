"""共享测试 fixtures。"""
from datetime import datetime
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

import pytest

_TZ = ZoneInfo("Asia/Shanghai")


@pytest.fixture
def make_plan():
    """工厂函数：构造定投计划 dict，可覆盖任意字段。"""
    def _make(**overrides) -> dict:
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
    return _make


@pytest.fixture
def make_tx_row():
    """工厂函数：构造交易 dict（模拟 sqlite3.Row），可覆盖任意字段。"""
    def _make(**overrides) -> dict:
        base = {
            "id": 1,
            "fund_code": "001",
            "action": "buy",
            "date": "2026-01-05",
            "amount": 1000.0,
            "shares": None,
            "nav": None,
            "fee": 0.0,
            "channel": "",
            "note": "",
            "is_t1": 0,
            "created_at": "2026-01-05",
        }
        base.update(overrides)
        return base
    return _make


class PatchAutoInvest:
    """统一 patch auto_invest 模块的 datetime + db + fetch_fund + analysis。

    用法:
        with PatchAutoInvest(datetime(2026, 1, 5, 9, 0, tzinfo=_TZ)) as env:
            result = execute_plan(plan, manual=True)
            tx = env.mock_db.add_transaction.call_args[0][0]
    """

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

