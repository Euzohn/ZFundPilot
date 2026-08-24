"""fetch_dividend 测试：分红检测、去重、缓存、列名匹配。"""

import sys
from types import ModuleType
from unittest.mock import MagicMock, patch

import pandas as pd

from zfundpilot import fetch_dividend
from zfundpilot.models import (
    ACTION_DIVIDEND,
    Fund,
    Position,
    Transaction,
)


def _fake_akshare(df):
    """构造假的 akshare 模块。"""
    fake = ModuleType("akshare")
    fake.fund_open_fund_info_em = MagicMock(return_value=df)
    return fake


def _div_df(rows):
    """构造分红送配详情 DataFrame。"""
    return pd.DataFrame(rows)


def _make_position(code, shares=1000.0):
    """构造一个 open position。"""
    return Position(
        fund_code=code, fund_name=f"基金{code}", fund_type="混合型",
        sector="权益", held_shares=shares, total_cost=1000,
    )


def _make_fund(code, method="cash"):
    return Fund(fund_code=code, fund_name=f"基金{code}", dividend_method=method)


class TestDateClose:
    def test_same_day(self):
        assert fetch_dividend._date_close("2025-09-22", "2025-09-22", tolerance=3)

    def test_within_tolerance(self):
        assert fetch_dividend._date_close("2025-09-20", "2025-09-22", tolerance=3)
        assert fetch_dividend._date_close("2025-09-25", "2025-09-22", tolerance=3)

    def test_outside_tolerance(self):
        assert not fetch_dividend._date_close("2025-09-15", "2025-09-22", tolerance=3)

    def test_invalid_date(self):
        assert not fetch_dividend._date_close("", "2025-09-22")
        assert not fetch_dividend._date_close("invalid", "2025-09-22")


class TestParseDividendRow:
    def test_real_akshare_format(self):
        """AkShare fund_open_fund_info_em(分红送配详情) 的真实返回格式。"""
        row = {
            "年份": "2026年",
            "权益登记日": "2026-01-19",
            "除息日": "2026-01-19",
            "每10份分红": "每10份派现金0.0500元",
            "分红发放日": "2026-01-21",
        }
        ev = fetch_dividend._parse_dividend_row(row, "161606", "融通通利")
        assert ev is not None
        assert ev.ex_date == "2026-01-19"
        assert ev.per_share == 0.005  # 0.0500 / 10
        assert ev.pay_date == "2026-01-21"

    def test_large_dividend(self):
        row = {
            "除息日": "2007-10-25",
            "每10份分红": "每10份派现金7.7000元",
            "分红发放日": "2007-10-29",
        }
        ev = fetch_dividend._parse_dividend_row(row, "161606", "test")
        assert ev is not None
        assert ev.per_share == 0.77

    def test_float_format_from_fh_em(self):
        """fund_fh_em 接口返回纯 float 格式。"""
        row = {
            "除息日": "2025-09-22",
            "分红": 0.0100,
            "分红发放日": "2025-09-23",
        }
        ev = fetch_dividend._parse_dividend_row(row, "000001", "test")
        assert ev is not None
        assert ev.per_share == 0.01

    def test_string_float_format(self):
        """纯数字字符串格式。"""
        row = {
            "除息日": "2025-03-21",
            "分红": "0.0105",
            "分红发放日": "2025-03-24",
        }
        ev = fetch_dividend._parse_dividend_row(row, "000005", "test")
        assert ev is not None
        assert ev.per_share == 0.0105

    def test_missing_ex_date(self):
        row = {"每10份分红": "每10份派现金0.0500元"}
        assert fetch_dividend._parse_dividend_row(row, "000001", "test") is None

    def test_invalid_per_share(self):
        row = {"除息日": "2025-09-22", "每10份分红": "无分红"}
        assert fetch_dividend._parse_dividend_row(row, "000001", "test") is None

    def test_zero_per_share(self):
        row = {"除息日": "2025-09-22", "每10份分红": "每10份派现金0.0000元"}
        assert fetch_dividend._parse_dividend_row(row, "000001", "test") is None


class TestFetchFundDividends:
    def test_cache_hit(self):
        df = _div_df([{"除息日": "2025-09-22", "每份分红": "0.01"}])
        fake = _fake_akshare(df)
        with patch.dict(sys.modules, {"akshare": fake}):
            with patch.dict(fetch_dividend._DIV_CACHE, {}, clear=True):
                fetch_dividend._fetch_fund_dividends("000001")
                assert fake.fund_open_fund_info_em.call_count == 1
                fetch_dividend._fetch_fund_dividends("000001")
                assert fake.fund_open_fund_info_em.call_count == 1

    def test_error_returns_empty(self):
        fake = ModuleType("akshare")
        fake.fund_open_fund_info_em = MagicMock(side_effect=Exception("network"))
        with patch.dict(sys.modules, {"akshare": fake}):
            with patch.dict(fetch_dividend._DIV_CACHE, {}, clear=True):
                result = fetch_dividend._fetch_fund_dividends("000001")
                assert result == []


class TestCheckDividends:
    def _setup_mocks(self, div_rows, held_codes, existing_txs=None, funds=None):
        positions = [_make_position(c) for c in held_codes]
        if funds is None:
            funds = [_make_fund(c) for c in held_codes]
        existing_txs = existing_txs or []
        return positions, funds, existing_txs

    def test_no_holdings(self):
        with (
            patch("zfundpilot.fetch_dividend.analysis.calculate_positions", return_value=[]),
            patch("zfundpilot.fetch_dividend.db.get_funds", return_value=[]),
            patch("zfundpilot.fetch_dividend.db.get_transactions", return_value=[]),
        ):
            assert fetch_dividend.check_dividends() == []

    def test_with_holdings_and_events(self):
        div_rows = [
            {"权益登记日": "2025-09-22", "除息日": "2025-09-22", "每份分红": "0.0100", "分红发放日": "2025-09-23"},
        ]
        df = _div_df(div_rows)
        fake = _fake_akshare(df)
        positions = [_make_position("000001", shares=10000)]
        funds_list = [_make_fund("000001", "cash")]

        with patch.dict(fetch_dividend._DIV_CACHE, {}, clear=True):
            with (
                patch("zfundpilot.fetch_dividend.analysis.calculate_positions", return_value=positions),
                patch("zfundpilot.fetch_dividend.db.get_funds", return_value=funds_list),
                patch("zfundpilot.fetch_dividend.db.get_transactions", return_value=[]),
                patch("zfundpilot.fetch_dividend.db.get_dividend_alerts", return_value=[]),
                patch.dict(sys.modules, {"akshare": fake}),
            ):
                # patch _LOOKBACK_DAYS to a large value so the event is within window
                with patch.object(fetch_dividend, "_LOOKBACK_DAYS", 36500):
                    events = fetch_dividend.check_dividends()

        assert len(events) == 1
        ev = events[0]
        assert ev.fund_code == "000001"
        assert ev.per_share == 0.01
        assert ev.held_shares == 10000
        assert ev.estimated_amount == 100.0
        assert ev.dividend_method == "cash"
        assert not ev.already_recorded

    def test_already_recorded_dedup(self):
        from datetime import datetime, timedelta
        ex_date = (datetime.now() - timedelta(days=10)).strftime("%Y-%m-%d")
        div_rows = [
            {"权益登记日": ex_date, "除息日": ex_date, "每份分红": "0.0100", "分红发放日": ex_date},
        ]
        df = _div_df(div_rows)
        fake = _fake_akshare(df)
        positions = [_make_position("000001")]
        funds_list = [_make_fund("000001")]
        existing_txs = [Transaction(
            id=1, fund_code="000001", action=ACTION_DIVIDEND,
            date=ex_date, amount=10.0, shares=None, nav=None,
            fee=0, channel="", note="",
        )]

        with patch.dict(fetch_dividend._DIV_CACHE, {}, clear=True):
            with (
                patch("zfundpilot.fetch_dividend.analysis.calculate_positions", return_value=positions),
                patch("zfundpilot.fetch_dividend.db.get_funds", return_value=funds_list),
                patch("zfundpilot.fetch_dividend.db.get_transactions", return_value=existing_txs),
                patch("zfundpilot.fetch_dividend.db.get_dividend_alerts", return_value=[]),
                patch.dict(sys.modules, {"akshare": fake}),
            ):
                with patch.object(fetch_dividend, "_LOOKBACK_DAYS", 36500):
                    events = fetch_dividend.check_dividends()

        assert len(events) == 0

    def test_lookback_filter(self):
        old_date = "2020-01-01"
        div_rows = [
            {"权益登记日": old_date, "除息日": old_date, "每份分红": "0.0100", "分红发放日": old_date},
        ]
        df = _div_df(div_rows)
        fake = _fake_akshare(df)
        positions = [_make_position("000001")]
        funds_list = [_make_fund("000001")]

        with patch.dict(fetch_dividend._DIV_CACHE, {}, clear=True):
            with (
                patch("zfundpilot.fetch_dividend.analysis.calculate_positions", return_value=positions),
                patch("zfundpilot.fetch_dividend.db.get_funds", return_value=funds_list),
                patch("zfundpilot.fetch_dividend.db.get_transactions", return_value=[]),
                patch("zfundpilot.fetch_dividend.db.get_dividend_alerts", return_value=[]),
                patch.dict(sys.modules, {"akshare": fake}),
            ):
                events = fetch_dividend.check_dividends()

        assert len(events) == 0

    def test_dividend_method_reinvest(self):
        from datetime import datetime, timedelta
        ex_date = (datetime.now() - timedelta(days=10)).strftime("%Y-%m-%d")
        div_rows = [
            {"权益登记日": ex_date, "除息日": ex_date, "每份分红": "0.0500", "分红发放日": ex_date},
        ]
        df = _div_df(div_rows)
        fake = _fake_akshare(df)
        positions = [_make_position("000001", shares=2000)]
        funds_list = [_make_fund("000001", "reinvest")]

        with patch.dict(fetch_dividend._DIV_CACHE, {}, clear=True):
            with (
                patch("zfundpilot.fetch_dividend.analysis.calculate_positions", return_value=positions),
                patch("zfundpilot.fetch_dividend.db.get_funds", return_value=funds_list),
                patch("zfundpilot.fetch_dividend.db.get_transactions", return_value=[]),
                patch("zfundpilot.fetch_dividend.db.get_dividend_alerts", return_value=[]),
                patch.dict(sys.modules, {"akshare": fake}),
            ):
                with patch.object(fetch_dividend, "_LOOKBACK_DAYS", 36500):
                    events = fetch_dividend.check_dividends()

        assert len(events) == 1
        assert events[0].dividend_method == "reinvest"
        assert events[0].estimated_amount == 100.0

    def test_fund_not_in_funds_dict_defaults_cash(self):
        from datetime import datetime, timedelta
        ex_date = (datetime.now() - timedelta(days=10)).strftime("%Y-%m-%d")
        div_rows = [
            {"权益登记日": ex_date, "除息日": ex_date, "每份分红": "0.0100", "分红发放日": ex_date},
        ]
        df = _div_df(div_rows)
        fake = _fake_akshare(df)
        positions = [_make_position("000001")]
        funds_list = []  # Fund not in funds dict

        with patch.dict(fetch_dividend._DIV_CACHE, {}, clear=True):
            with (
                patch("zfundpilot.fetch_dividend.analysis.calculate_positions", return_value=positions),
                patch("zfundpilot.fetch_dividend.db.get_funds", return_value=funds_list),
                patch("zfundpilot.fetch_dividend.db.get_transactions", return_value=[]),
                patch("zfundpilot.fetch_dividend.db.get_dividend_alerts", return_value=[]),
                patch.dict(sys.modules, {"akshare": fake}),
            ):
                with patch.object(fetch_dividend, "_LOOKBACK_DAYS", 36500):
                    events = fetch_dividend.check_dividends()

        assert len(events) == 1
        assert events[0].dividend_method == "cash"


class TestCleanupStaleAlerts:
    """_cleanup_stale_alerts 幽灵分红提醒清理测试。"""

    def test_phantom_alert_marked_ignored(self):
        """pending 提醒的 ex_date 不在 fetched_ex_dates 中 → 标记 ignored。"""
        pending_alerts = [
            {"id": 1, "fund_code": "000001", "ex_date": "2026-06-17"},
        ]
        fetched_ex_dates = {("000001", "2022-06-23")}  # 只有真实记录
        fetched_funds = {"000001"}

        with (
            patch("zfundpilot.fetch_dividend.db.get_dividend_alerts", return_value=pending_alerts),
            patch("zfundpilot.fetch_dividend.db.update_dividend_alert") as mock_update,
        ):
            cleaned = fetch_dividend._cleanup_stale_alerts(fetched_ex_dates, fetched_funds)

        assert cleaned == 1
        mock_update.assert_called_once()
        call_args = mock_update.call_args
        assert call_args[0][0] == 1  # alert_id
        assert call_args[1]["status"] == "ignored"
        assert "resolved_at" in call_args[1]

    def test_valid_alert_not_cleaned(self):
        """pending 提醒的 ex_date 在 fetched_ex_dates 中 → 不清理。"""
        pending_alerts = [
            {"id": 1, "fund_code": "000001", "ex_date": "2022-06-23"},
        ]
        fetched_ex_dates = {("000001", "2022-06-23")}
        fetched_funds = {"000001"}

        with (
            patch("zfundpilot.fetch_dividend.db.get_dividend_alerts", return_value=pending_alerts),
            patch("zfundpilot.fetch_dividend.db.update_dividend_alert") as mock_update,
        ):
            cleaned = fetch_dividend._cleanup_stale_alerts(fetched_ex_dates, fetched_funds)

        assert cleaned == 0
        mock_update.assert_not_called()

    def test_unfetched_fund_not_cleaned(self):
        """基金不在 fetched_funds 中（fetch error 或已清仓）→ 不清理。"""
        pending_alerts = [
            {"id": 1, "fund_code": "000999", "ex_date": "2026-06-17"},
        ]
        fetched_ex_dates = {("000001", "2022-06-23")}
        fetched_funds = {"000001"}  # 000999 不在其中

        with (
            patch("zfundpilot.fetch_dividend.db.get_dividend_alerts", return_value=pending_alerts),
            patch("zfundpilot.fetch_dividend.db.update_dividend_alert") as mock_update,
        ):
            cleaned = fetch_dividend._cleanup_stale_alerts(fetched_ex_dates, fetched_funds)

        assert cleaned == 0
        mock_update.assert_not_called()

    def test_multiple_alerts_partial_cleanup(self):
        """多条提醒，部分幽灵部分有效 → 只清理幽灵的。"""
        pending_alerts = [
            {"id": 1, "fund_code": "000001", "ex_date": "2026-06-17"},  # 幽灵
            {"id": 2, "fund_code": "000001", "ex_date": "2022-06-23"},  # 有效
            {"id": 3, "fund_code": "000002", "ex_date": "2026-06-17"},  # 000002 不在 fetched_funds
        ]
        fetched_ex_dates = {("000001", "2022-06-23"), ("000001", "2021-12-28")}
        fetched_funds = {"000001"}

        with (
            patch("zfundpilot.fetch_dividend.db.get_dividend_alerts", return_value=pending_alerts),
            patch("zfundpilot.fetch_dividend.db.update_dividend_alert") as mock_update,
        ):
            cleaned = fetch_dividend._cleanup_stale_alerts(fetched_ex_dates, fetched_funds)

        assert cleaned == 1
        mock_update.assert_called_once()
        assert mock_update.call_args[0][0] == 1  # 只清理 id=1

    def test_no_pending_alerts(self):
        """无 pending 提醒 → 0 清理。"""
        with (
            patch("zfundpilot.fetch_dividend.db.get_dividend_alerts", return_value=[]),
            patch("zfundpilot.fetch_dividend.db.update_dividend_alert") as mock_update,
        ):
            cleaned = fetch_dividend._cleanup_stale_alerts(set(), set())

        assert cleaned == 0
        mock_update.assert_not_called()


class TestDividendAlertsDB:
    """dividend_alerts 表 CRUD 测试（用临时数据库）。"""

    def _setup_db(self, tmp_path):
        """用临时数据库替换 config.DB_PATH 并初始化。"""
        import os

        from zfundpilot import config
        db_path = os.path.join(str(tmp_path), "test.db")
        # patch config.DB_PATH（db 模块用 config.DB_PATH 连接）
        import zfundpilot.db as db_module
        original = config.DB_PATH
        config.DB_PATH = db_path
        db_module.init_db()
        return db_module, original

    def _teardown(self, original):
        from zfundpilot import config
        config.DB_PATH = original

    def test_add_and_get_alert(self, tmp_path):
        db, original = self._setup_db(tmp_path)
        try:
            alert_id = db.add_dividend_alert({
                "fund_code": "000001", "fund_name": "华夏成长",
                "record_date": "2025-09-22", "ex_date": "2025-09-22",
                "per_share": 0.01, "pay_date": "2025-09-23",
                "held_shares": 10000, "estimated_amount": 100.0,
                "dividend_method": "cash",
            })
            assert alert_id > 0
            alerts = db.get_dividend_alerts()
            assert len(alerts) == 1
            assert alerts[0]["fund_code"] == "000001"
            assert alerts[0]["status"] == "pending"
        finally:
            self._teardown(original)

    def test_pending_count(self, tmp_path):
        db, original = self._setup_db(tmp_path)
        try:
            assert db.get_pending_alert_count() == 0
            db.add_dividend_alert({
                "fund_code": "000001", "ex_date": "2025-09-22",
                "per_share": 0.01, "held_shares": 1000,
                "estimated_amount": 10.0,
            })
            db.add_dividend_alert({
                "fund_code": "000002", "ex_date": "2025-09-22",
                "per_share": 0.02, "held_shares": 1000,
                "estimated_amount": 20.0,
            })
            assert db.get_pending_alert_count() == 2
            # 确认一条
            db.update_dividend_alert(1, status="confirmed", resolved_at="2025-09-23")
            assert db.get_pending_alert_count() == 1
        finally:
            self._teardown(original)

    def test_alert_exists_all_status(self, tmp_path):
        """ignored 的 alert 也算 exists（不再重复提醒）。"""
        db, original = self._setup_db(tmp_path)
        try:
            db.add_dividend_alert({
                "fund_code": "000001", "ex_date": "2025-09-22",
                "per_share": 0.01, "held_shares": 1000,
                "estimated_amount": 10.0,
            })
            assert db.dividend_alert_exists("000001", "2025-09-22")
            assert not db.dividend_alert_exists("000001", "2025-09-23")
            # 忽略后仍 exists
            db.update_dividend_alert(1, status="ignored", resolved_at="2025-09-23")
            assert db.dividend_alert_exists("000001", "2025-09-22")
        finally:
            self._teardown(original)

    def test_update_alert_fields(self, tmp_path):
        db, original = self._setup_db(tmp_path)
        try:
            alert_id = db.add_dividend_alert({
                "fund_code": "000001", "ex_date": "2025-09-22",
                "per_share": 0.01, "held_shares": 1000,
                "estimated_amount": 10.0,
            })
            db.update_dividend_alert(alert_id, status="confirmed",
                                     resolved_at="2025-09-23", tx_id=42)
            alerts = db.get_dividend_alerts()
            assert alerts[0]["status"] == "confirmed"
            assert alerts[0]["resolved_at"] == "2025-09-23"
            assert alerts[0]["tx_id"] == 42
        finally:
            self._teardown(original)

    def test_filter_by_status(self, tmp_path):
        db, original = self._setup_db(tmp_path)
        try:
            for i in range(3):
                db.add_dividend_alert({
                    "fund_code": f"00000{i+1}", "ex_date": "2025-09-22",
                    "per_share": 0.01, "held_shares": 1000,
                    "estimated_amount": 10.0,
                })
            db.update_dividend_alert(1, status="ignored")
            db.update_dividend_alert(2, status="confirmed")
            assert len(db.get_dividend_alerts("pending")) == 1
            assert len(db.get_dividend_alerts("ignored")) == 1
            assert len(db.get_dividend_alerts("confirmed")) == 1
            assert len(db.get_dividend_alerts()) == 3
        finally:
            self._teardown(original)

    def test_delete_alert(self, tmp_path):
        db, original = self._setup_db(tmp_path)
        try:
            alert_id = db.add_dividend_alert({
                "fund_code": "000001", "ex_date": "2025-09-22",
                "per_share": 0.01, "held_shares": 1000,
                "estimated_amount": 10.0,
            })
            assert db.delete_dividend_alert(alert_id) is True
            assert len(db.get_dividend_alerts()) == 0
            # 重复删除返回 False
            assert db.delete_dividend_alert(alert_id) is False
        finally:
            self._teardown(original)

    def test_delete_does_not_affect_tp_sl(self, tmp_path):
        """删除分红提醒不影响 tp_sl 提醒。"""
        db, original = self._setup_db(tmp_path)
        try:
            div_id = db.add_dividend_alert({
                "fund_code": "000001", "ex_date": "2025-09-22",
                "per_share": 0.01, "held_shares": 1000,
                "estimated_amount": 10.0,
            })
            # 手动插入一条 tp_sl 提醒
            with db.get_connection() as conn:
                tp_sl_id = conn.execute(
                    """INSERT INTO dividend_alerts
                       (fund_code, fund_name, ex_date, per_share, held_shares,
                        estimated_amount, alert_type, triggered_return, threshold, status)
                       VALUES(?,?,?,?,?,?,'take_profit',0.15,0.15,'pending')""",
                    ("000002", "基金B", "2025-09-22", 0, 0, 0),
                ).lastrowid
            # 删除分红提醒
            assert db.delete_dividend_alert(div_id) is True
            # tp_sl 提醒仍在
            assert len(db.get_dividend_alerts()) == 0  # get_dividend_alerts 只返回 dividend 类型
            with db.get_connection() as conn:
                row = conn.execute(
                    "SELECT * FROM dividend_alerts WHERE id=?", (tp_sl_id,)
                ).fetchone()
                assert row is not None
        finally:
            self._teardown(original)


class TestRunDividendCheck:
    """scheduler._run_dividend_check 去重逻辑测试。"""

    def test_new_alerts_added(self):
        """新发现的分红事件存入 alerts 表。"""
        from zfundpilot import scheduler
        events = [
            fetch_dividend.DividendEvent(
                fund_code="000001", fund_name="基金A",
                record_date="2025-09-22", ex_date="2025-09-22",
                per_share=0.01, pay_date="2025-09-23",
                held_shares=10000, estimated_amount=100.0,
                dividend_method="cash",
            ),
        ]
        with (
            patch("zfundpilot.fetch_dividend.check_dividends", return_value=events),
            patch("zfundpilot.scheduler.db.dividend_alert_exists", return_value=False),
            patch("zfundpilot.scheduler.db.add_dividend_alert") as mock_add,
            patch("zfundpilot.scheduler.db.log_audit"),
        ):
            scheduler._run_dividend_check()
            assert mock_add.call_count == 1

    def test_existing_alerts_skipped(self):
        """已存在的 alert（任意状态）不重复存。"""
        from zfundpilot import scheduler
        events = [
            fetch_dividend.DividendEvent(
                fund_code="000001", fund_name="基金A",
                record_date="2025-09-22", ex_date="2025-09-22",
                per_share=0.01, pay_date="2025-09-23",
                held_shares=10000, estimated_amount=100.0,
                dividend_method="cash",
            ),
        ]
        with (
            patch("zfundpilot.fetch_dividend.check_dividends", return_value=events),
            patch("zfundpilot.scheduler.db.dividend_alert_exists", return_value=True),
            patch("zfundpilot.scheduler.db.add_dividend_alert") as mock_add,
            patch("zfundpilot.scheduler.db.log_audit"),
        ):
            scheduler._run_dividend_check()
            assert mock_add.call_count == 0

    def test_no_events(self):
        """无分红事件时正常完成。"""
        from zfundpilot import scheduler
        with (
            patch("zfundpilot.fetch_dividend.check_dividends", return_value=[]),
            patch("zfundpilot.scheduler.db.dividend_alert_exists") as mock_exists,
            patch("zfundpilot.scheduler.db.add_dividend_alert") as mock_add,
            patch("zfundpilot.scheduler.db.log_audit"),
        ):
            scheduler._run_dividend_check()
            assert mock_add.call_count == 0
            assert mock_exists.call_count == 0

    def test_exception_handled(self):
        """check_dividends 抛异常时不崩溃。"""
        from zfundpilot import scheduler
        with patch("zfundpilot.fetch_dividend.check_dividends",
                   side_effect=Exception("network")):
            scheduler._run_dividend_check()  # 不应抛异常
