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
                patch.dict(sys.modules, {"akshare": fake}),
            ):
                with patch.object(fetch_dividend, "_LOOKBACK_DAYS", 36500):
                    events = fetch_dividend.check_dividends()

        assert len(events) == 1
        assert events[0].dividend_method == "cash"
