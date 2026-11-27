"""fetch_dividend 测试：分红检测、去重、缓存、列名匹配。"""

import sys
import time
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


def _make_position(code, shares=1000.0, channel=""):
    """构造一个 open position。"""
    return Position(
        fund_code=code, fund_name=f"基金{code}", fund_type="混合型",
        sector="权益", held_shares=shares, total_cost=1000,
        channel=channel,
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

    def test_error_without_cache_returns_none(self):
        """抓取失败且无缓存 → None（失败），不得与「无分红」([]) 混淆。

        旧实现返回 []，重启后首次扫描的瞬时失败会被当成「成功抓取且无
        分红」，_cleanup_stale_alerts 误把该基金全部 pending 提醒 ignored。
        """
        fake = ModuleType("akshare")
        fake.fund_open_fund_info_em = MagicMock(side_effect=Exception("network"))
        with patch.dict(sys.modules, {"akshare": fake}):
            with patch.dict(fetch_dividend._DIV_CACHE, {}, clear=True):
                result = fetch_dividend._fetch_fund_dividends("000001")
                assert result is None

    def test_error_with_stale_cache_returns_cached(self):
        """抓取失败但有过期缓存 → 回退 stale 数据。"""
        stale = [{"除息日": "2025-09-22", "每份分红": "0.01"}]
        fake = ModuleType("akshare")
        fake.fund_open_fund_info_em = MagicMock(side_effect=Exception("network"))
        with patch.dict(sys.modules, {"akshare": fake}):
            with patch.dict(fetch_dividend._DIV_CACHE, {
                "000001": {"ts": 0.0, "data": stale},  # ts=0 必然过期
            }, clear=True):
                result = fetch_dividend._fetch_fund_dividends("000001")
                assert result == stale

    def test_empty_df_returns_empty_list(self):
        """上游返回空表（真正无分红）→ []，不是 None。"""
        fake = _fake_akshare(_div_df([]))
        with patch.dict(sys.modules, {"akshare": fake}):
            with patch.dict(fetch_dividend._DIV_CACHE, {}, clear=True):
                result = fetch_dividend._fetch_fund_dividends("000001")
                assert result == []

    def test_empty_df_falls_back_to_stale_cache(self):
        """空响应且缓存仍在回退时效内 → 回退 stale 数据，防瞬时空响应误清。"""
        stale = [{"除息日": "2025-09-22", "每份分红": "0.01"}]
        fake = _fake_akshare(_div_df([]))
        with patch.dict(sys.modules, {"akshare": fake}):
            with patch.dict(fetch_dividend._DIV_CACHE, {
                # 超过 6h 新鲜 TTL 但仍在 48h 回退时效内
                "000001": {"ts": time.time() - 3600, "data": stale},
            }, clear=True):
                result = fetch_dividend._fetch_fund_dividends("000001")
                assert result == stale

    def test_empty_df_aged_cache_returns_empty(self):
        """空响应且缓存老化超回退时效 → 视为真正空，放行幽灵清理。

        无上限回退曾把幽灵「养永生」：坏数据一旦入缓存，源修正为空后
        永远回退坏缓存，fetched_ex_dates 恒含幽灵记录、清理永不触发
        （如 019172 摩根纳斯达克100 的假 2026-11-30 分红）。
        """
        stale = [{"除息日": "2025-09-22", "每份分红": "0.01"}]
        fake = _fake_akshare(_div_df([]))
        with patch.dict(sys.modules, {"akshare": fake}):
            with patch.dict(fetch_dividend._DIV_CACHE, {
                "000001": {"ts": 0.0, "data": stale},  # ts=0 必然老化
            }, clear=True):
                result = fetch_dividend._fetch_fund_dividends("000001")
                assert result == []

    def test_no_tables_falls_back_to_fresh_cache(self):
        """「No tables found」空响应且缓存仍新鲜 → 回退 stale 数据。"""
        stale = [{"除息日": "2025-09-22", "每份分红": "0.01"}]
        fake = ModuleType("akshare")
        fake.fund_open_fund_info_em = MagicMock(
            side_effect=Exception("No tables found"))
        with patch.dict(sys.modules, {"akshare": fake}):
            with patch.dict(fetch_dividend._DIV_CACHE, {
                "000001": {"ts": time.time() - 3600, "data": stale},
            }, clear=True):
                result = fetch_dividend._fetch_fund_dividends("000001")
                assert result == stale

    def test_no_tables_aged_cache_returns_empty(self):
        """「No tables found」空响应且缓存老化 → 视为真正空，放行幽灵清理。"""
        stale = [{"除息日": "2025-09-22", "每份分红": "0.01"}]
        fake = ModuleType("akshare")
        fake.fund_open_fund_info_em = MagicMock(
            side_effect=Exception("No tables found"))
        with patch.dict(sys.modules, {"akshare": fake}):
            with patch.dict(fetch_dividend._DIV_CACHE, {
                "000001": {"ts": 0.0, "data": stale},
            }, clear=True):
                result = fetch_dividend._fetch_fund_dividends("000001")
                assert result == []

    def test_no_tables_exception_returns_empty_list(self):
        """「No tables found」是上游明确的空响应（无分红记录）→ []。"""
        fake = ModuleType("akshare")
        fake.fund_open_fund_info_em = MagicMock(
            side_effect=Exception("No tables found"))
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
        assert fetch_dividend._last_cleanup_count == 0

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

    def test_ghost_healed_when_source_corrected_to_empty(self):
        """端到端：坏数据入缓存生成幽灵提醒 → 源修正为空表且缓存老化 →
        下次扫描幽灵自动 ignored（此前无上限回退使幽灵永久残留）。"""
        from datetime import datetime, timedelta
        ghost_ex = (datetime.now() - timedelta(days=5)).strftime("%Y-%m-%d")
        bad_rows = [{"权益登记日": ghost_ex, "除息日": ghost_ex,
                     "每10份分红": "每10份派现金2.4310元", "分红发放日": ghost_ex}]
        pending = [{"id": 1, "fund_code": "000001", "ex_date": ghost_ex, "channel": ""}]
        fake = _fake_akshare(_div_df([]))  # 源现已修正为空表
        positions = [_make_position("000001")]
        funds_list = [_make_fund("000001")]

        with patch.dict(fetch_dividend._DIV_CACHE, {
            "000001": {"ts": 0.0, "data": bad_rows},  # 坏缓存已老化
        }, clear=True):
            with (
                patch("zfundpilot.fetch_dividend.analysis.calculate_positions", return_value=positions),
                patch("zfundpilot.fetch_dividend.db.get_funds", return_value=funds_list),
                patch("zfundpilot.fetch_dividend.db.get_transactions", return_value=[]),
                patch("zfundpilot.fetch_dividend.db.get_dividend_alerts", return_value=pending),
                patch("zfundpilot.fetch_dividend.db.update_dividend_alert") as mock_update,
                patch("zfundpilot.fetch_dividend.notification_service.sync_alert_status"),
                patch.dict(sys.modules, {"akshare": fake}),
            ):
                events = fetch_dividend.check_dividends()

        assert events == []
        assert fetch_dividend._last_cleanup_count == 1
        mock_update.assert_called_once()
        assert mock_update.call_args[0][0] == 1
        assert mock_update.call_args[1]["status"] == "ignored"

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

    def test_multi_channel_events_split(self):
        """同一基金多渠道持仓 → 每渠道各一条事件，份额/金额按渠道拆分。"""
        from datetime import datetime, timedelta
        ex_date = (datetime.now() - timedelta(days=10)).strftime("%Y-%m-%d")
        div_rows = [
            {"权益登记日": ex_date, "除息日": ex_date, "每份分红": "0.0100", "分红发放日": ex_date},
        ]
        df = _div_df(div_rows)
        fake = _fake_akshare(df)
        positions = [
            _make_position("000001", shares=1000, channel="支付宝"),
            _make_position("000001", shares=3000, channel="理财通"),
        ]
        funds_list = [_make_fund("000001")]

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

        assert len(events) == 2
        by_channel = {ev.channel: ev for ev in events}
        assert by_channel["支付宝"].held_shares == 1000
        assert by_channel["支付宝"].estimated_amount == 10.0
        assert by_channel["理财通"].held_shares == 3000
        assert by_channel["理财通"].estimated_amount == 30.0

    def test_dedup_per_channel(self):
        """已记录渠道 A 的分红，只抑制渠道 A 的事件，渠道 B 仍提醒。"""
        from datetime import datetime, timedelta
        ex_date = (datetime.now() - timedelta(days=10)).strftime("%Y-%m-%d")
        div_rows = [
            {"权益登记日": ex_date, "除息日": ex_date, "每份分红": "0.0100", "分红发放日": ex_date},
        ]
        df = _div_df(div_rows)
        fake = _fake_akshare(df)
        positions = [
            _make_position("000001", shares=1000, channel="支付宝"),
            _make_position("000001", shares=3000, channel="理财通"),
        ]
        funds_list = [_make_fund("000001")]
        existing_txs = [Transaction(
            id=1, fund_code="000001", action=ACTION_DIVIDEND,
            date=ex_date, amount=10.0, shares=None, nav=None,
            fee=0, channel="支付宝", note="",
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

        assert len(events) == 1
        assert events[0].channel == "理财通"

    def test_fetches_run_serially(self):
        """回归：分红抓取必须串行（max_concurrent == 1）。

        akshare「分红送配详情」路径含 V8 eval 与 pd.read_html(lxml) 两个
        原生调用，3 线程并发实测 SIGSEGV（exit 139，曾致整站崩溃循环）。
        若本用例失败，说明 _MAX_WORKERS 被调回 >1，先读 _MAX_WORKERS 注释。
        """
        import threading
        import time as _time

        codes = [f"00000{i}" for i in range(1, 7)]
        positions = [_make_position(c) for c in codes]
        funds_list = [_make_fund(c) for c in codes]

        lock = threading.Lock()
        state = {"current": 0, "max": 0}

        def slow_fetch(fund_code: str) -> list[dict]:
            with lock:
                state["current"] += 1
                state["max"] = max(state["max"], state["current"])
            _time.sleep(0.03)
            with lock:
                state["current"] -= 1
            return []

        with (
            patch("zfundpilot.fetch_dividend.analysis.calculate_positions", return_value=positions),
            patch("zfundpilot.fetch_dividend.db.get_funds", return_value=funds_list),
            patch("zfundpilot.fetch_dividend.db.get_transactions", return_value=[]),
            patch("zfundpilot.fetch_dividend.db.get_dividend_alerts", return_value=[]),
            patch("zfundpilot.fetch_dividend._fetch_fund_dividends", side_effect=slow_fetch),
        ):
            fetch_dividend.check_dividends()

        assert state["max"] == 1, (
            f"分红抓取出现并发（max_concurrent={state['max']}），"
            "会触发 akshare read_html/lxml 原生段错误，见 _MAX_WORKERS 注释"
        )


class TestCleanupStaleAlerts:
    """_cleanup_stale_alerts 幽灵分红提醒清理测试。"""

    def test_phantom_alert_marked_ignored(self):
        """pending 提醒的 ex_date 不在 fetched_ex_dates 中 → 标记 ignored。"""
        pending_alerts = [
            {"id": 1, "fund_code": "000001", "ex_date": "2026-06-17"},
        ]
        fetched_ex_dates = {("000001", "2022-06-23", "")}  # 只有真实记录
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
        fetched_ex_dates = {("000001", "2022-06-23", "")}
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
        fetched_ex_dates = {("000001", "2022-06-23", "")}
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
        fetched_ex_dates = {("000001", "2022-06-23", ""), ("000001", "2021-12-28", "")}
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

    def test_channel_match_not_cleaned(self):
        """提醒渠道与抓取到的渠道一致 → 不清理。"""
        pending_alerts = [
            {"id": 1, "fund_code": "008115", "ex_date": "2026-11-18",
             "channel": "支付宝"},
        ]
        fetched_ex_dates = {("008115", "2026-11-18", "支付宝")}

        with (
            patch("zfundpilot.fetch_dividend.db.get_dividend_alerts", return_value=pending_alerts),
            patch("zfundpilot.fetch_dividend.db.update_dividend_alert") as mock_update,
        ):
            cleaned = fetch_dividend._cleanup_stale_alerts(
                fetched_ex_dates, {"008115"}
            )

        assert cleaned == 0
        mock_update.assert_not_called()

    def test_channel_mismatch_cleaned(self):
        """提醒渠道在抓取结果中没有（渠道已清仓/变化）→ 按幽灵清理。"""
        pending_alerts = [
            {"id": 1, "fund_code": "008115", "ex_date": "2026-11-18",
             "channel": "理财通"},
        ]
        fetched_ex_dates = {("008115", "2026-11-18", "支付宝")}

        with (
            patch("zfundpilot.fetch_dividend.db.get_dividend_alerts", return_value=pending_alerts),
            patch("zfundpilot.fetch_dividend.db.update_dividend_alert") as mock_update,
        ):
            cleaned = fetch_dividend._cleanup_stale_alerts(
                fetched_ex_dates, {"008115"}
            )

        assert cleaned == 1
        assert mock_update.call_args[0][0] == 1

    def test_legacy_alert_without_channel_cleaned(self):
        """旧库无渠道的提醒（''）在多渠道抓取结果中 → 清理后按渠道重建。

        单渠道持仓的旧提醒会在迁移时回填渠道，此处模拟无法判定的情况。
        """
        pending_alerts = [
            {"id": 1, "fund_code": "008115", "ex_date": "2026-11-18"},
        ]
        fetched_ex_dates = {
            ("008115", "2026-11-18", "支付宝"),
            ("008115", "2026-11-18", "理财通"),
        }

        with (
            patch("zfundpilot.fetch_dividend.db.get_dividend_alerts", return_value=pending_alerts),
            patch("zfundpilot.fetch_dividend.db.update_dividend_alert") as mock_update,
        ):
            cleaned = fetch_dividend._cleanup_stale_alerts(
                fetched_ex_dates, {"008115"}
            )

        assert cleaned == 1
        assert mock_update.call_args[0][0] == 1


    def test_empty_fetch_cleanup(self):
        """基金无分红历史（fetch 返回空）→ fetched_funds 包含 code → ghost 被清理。

        复现 017641 摩根标普500 QDII 场景：AkShare 返回空 DataFrame，
        fund 不加入 fetched_funds 导致 ghost alert 永远不被清理。
        修复：fetched_funds.add(code) 移到 if not rows 之前。
        """
        pending_alerts = [
            {"id": 1, "fund_code": "017641", "ex_date": "2026-06-26"},
        ]
        fetched_ex_dates = set()  # 空基金无任何 ex_date
        fetched_funds = {"017641"}  # 修复后空 fetch 也加入 fetched_funds

        with (
            patch("zfundpilot.fetch_dividend.db.get_dividend_alerts", return_value=pending_alerts),
            patch("zfundpilot.fetch_dividend.db.update_dividend_alert") as mock_update,
        ):
            cleaned = fetch_dividend._cleanup_stale_alerts(fetched_ex_dates, fetched_funds)

        assert cleaned == 1
        mock_update.assert_called_once()
        assert mock_update.call_args[1]["status"] == "ignored"

    def test_ttl_cleanup_old_pending(self):
        """pending 超 _LOOKBACK_DAYS 天 → 自动 ignore（兜底清理）。

        created_at 用 SQLite datetime('now','localtime') 格式（朴素无时区），
        验证代码对朴素 datetime 补时区后能正确比较。
        """
        from datetime import datetime, timedelta

        old_date = (datetime.now() - timedelta(days=91)).strftime("%Y-%m-%d %H:%M:%S")
        pending_alerts = [
            {"id": 1, "fund_code": "000001", "ex_date": "2026-06-26",
             "created_at": old_date},
        ]
        fetched_ex_dates = set()
        fetched_funds = set()

        with (
            patch("zfundpilot.fetch_dividend.db.get_dividend_alerts", return_value=pending_alerts),
            patch("zfundpilot.fetch_dividend.db.update_dividend_alert") as mock_update,
        ):
            cleaned = fetch_dividend._cleanup_stale_alerts(fetched_ex_dates, fetched_funds)

        assert cleaned == 1
        assert mock_update.call_args[1]["status"] == "ignored"

    def test_ttl_not_clean_recent(self):
        """pending 不到 _LOOKBACK_DAYS 天 → 不被 TTL 清理。"""
        from datetime import datetime, timedelta

        recent_date = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d %H:%M:%S")
        pending_alerts = [
            {"id": 1, "fund_code": "000001", "ex_date": "2026-06-26",
             "created_at": recent_date},
        ]
        fetched_ex_dates = set()
        fetched_funds = set()

        with (
            patch("zfundpilot.fetch_dividend.db.get_dividend_alerts", return_value=pending_alerts),
            patch("zfundpilot.fetch_dividend.db.update_dividend_alert") as mock_update,
        ):
            cleaned = fetch_dividend._cleanup_stale_alerts(fetched_ex_dates, fetched_funds)

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

    def test_add_alert_with_channel(self, tmp_path):
        """add_dividend_alert 写入渠道，get_dividend_alerts 能读回。"""
        db, original = self._setup_db(tmp_path)
        try:
            db.add_dividend_alert({
                "fund_code": "008115", "ex_date": "2026-11-18",
                "per_share": 0.01, "held_shares": 723.9,
                "estimated_amount": 7.24, "channel": "支付宝",
            })
            alerts = db.get_dividend_alerts()
            assert len(alerts) == 1
            assert alerts[0]["channel"] == "支付宝"
        finally:
            self._teardown(original)

    def test_alert_exists_per_channel(self, tmp_path):
        """同一基金同一除息日，不同渠道互不影响。"""
        db, original = self._setup_db(tmp_path)
        try:
            db.add_dividend_alert({
                "fund_code": "008115", "ex_date": "2026-11-18",
                "per_share": 0.01, "held_shares": 723.9,
                "estimated_amount": 7.24, "channel": "支付宝",
            })
            assert db.dividend_alert_exists("008115", "2026-11-18", "支付宝")
            assert not db.dividend_alert_exists("008115", "2026-11-18", "理财通")
            # 不传渠道 = 只匹配空渠道旧提醒
            assert not db.dividend_alert_exists("008115", "2026-11-18")
        finally:
            self._teardown(original)

    def test_unique_allows_multiple_channels(self, tmp_path):
        """UNIQUE 含 channel：同基金同除息日不同渠道可各存一条。"""
        db, original = self._setup_db(tmp_path)
        try:
            id1 = db.add_dividend_alert({
                "fund_code": "008115", "ex_date": "2026-11-18",
                "per_share": 0.01, "held_shares": 500,
                "estimated_amount": 5.0, "channel": "支付宝",
            })
            id2 = db.add_dividend_alert({
                "fund_code": "008115", "ex_date": "2026-11-18",
                "per_share": 0.01, "held_shares": 300,
                "estimated_amount": 3.0, "channel": "理财通",
            })
            assert id1 != id2
            assert len(db.get_dividend_alerts()) == 2
            # 同渠道重复插入被 IGNORE
            db.add_dividend_alert({
                "fund_code": "008115", "ex_date": "2026-11-18",
                "per_share": 0.01, "held_shares": 999,
                "estimated_amount": 9.99, "channel": "支付宝",
            })
            assert len(db.get_dividend_alerts()) == 2
        finally:
            self._teardown(original)


class TestRunDividendCheck:
    """scheduler._run_dividend_check 去重逻辑测试。"""

    def setup_method(self):
        fetch_dividend._last_cleanup_count = 0

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


class TestCheckDividendsGhostCleanup:
    """check_dividends 空 fetch + ghost 清理集成测试。"""

    def setup_method(self):
        fetch_dividend._last_cleanup_count = 0
        fetch_dividend._DIV_CACHE.clear()

    def test_empty_fetch_cleanup_ghost(self):
        """空 fetch 结果的基金：fetched_funds 包含 code → ghost 被清理。

        复现 017641 场景：AkShare 对该基金返回空 DataFrame，
        check_dividends 不应跳过它的 ghost alert。
        """
        from zfundpilot import analysis

        pos = MagicMock(fund_code="017641", is_open=True, held_shares=100, channel="")
        pos.fund_name = "摩根标普500指数"

        fund = MagicMock(fund_code="017641", fund_name="摩根标普500", dividend_method="cash")

        # _fetch_fund_dividends 返回空 → 模拟 AkShare 对 QDII 无分红数据
        with (
            patch.object(analysis, "calculate_positions", return_value=[pos]),
            patch("zfundpilot.fetch_dividend.db.get_funds", return_value=[fund]),
            patch("zfundpilot.fetch_dividend._fetch_fund_dividends", return_value=[]),
            patch("zfundpilot.fetch_dividend.db.get_dividend_alerts", return_value=[
                {"id": 1, "fund_code": "017641", "ex_date": "2026-06-26"},
            ]),
            patch("zfundpilot.fetch_dividend.db.update_dividend_alert") as mock_update,
            patch("zfundpilot.fetch_dividend.db.get_transactions", return_value=[]),
        ):
            fetch_dividend.check_dividends()

        assert mock_update.call_count == 1
        assert mock_update.call_args[1]["status"] == "ignored"

    def test_none_fetch_preserves_alert(self):
        """fetch 返回 None（失败无缓存）：不加入 fetched_funds → 提醒保留。

        复现重启后首次扫描瞬时失败场景：若把 None 当空数据，pending 提醒
        会被误标 ignored 且永不重建（dividend_alert_exists 查所有状态）。
        """
        from zfundpilot import analysis

        pos = MagicMock(fund_code="000001", is_open=True, held_shares=1000, channel="")
        fund = MagicMock(fund_code="000001", fund_name="基金A", dividend_method="cash")

        with (
            patch.object(analysis, "calculate_positions", return_value=[pos]),
            patch("zfundpilot.fetch_dividend.db.get_funds", return_value=[fund]),
            patch("zfundpilot.fetch_dividend._fetch_fund_dividends",
                  return_value=None),
            patch("zfundpilot.fetch_dividend.db.get_dividend_alerts", return_value=[
                {"id": 1, "fund_code": "000001", "ex_date": "2026-06-26"},
            ]),
            patch("zfundpilot.fetch_dividend.db.update_dividend_alert") as mock_update,
            patch("zfundpilot.fetch_dividend.db.get_transactions", return_value=[]),
        ):
            events = fetch_dividend.check_dividends()

        assert events == []
        mock_update.assert_not_called()

    def test_exception_fetch_preserves_alert(self):
        """fetch 异常的基金：不加入 fetched_funds → ghost 不被清理。"""
        from zfundpilot import analysis

        pos = MagicMock(fund_code="000001", is_open=True, held_shares=1000, channel="")
        fund = MagicMock(fund_code="000001", fund_name="基金A", dividend_method="cash")

        with (
            patch.object(analysis, "calculate_positions", return_value=[pos]),
            patch("zfundpilot.fetch_dividend.db.get_funds", return_value=[fund]),
            patch("zfundpilot.fetch_dividend._fetch_fund_dividends",
                  side_effect=Exception("network error")),
            patch("zfundpilot.fetch_dividend.db.get_dividend_alerts", return_value=[
                {"id": 1, "fund_code": "000001", "ex_date": "2026-06-26"},
            ]),
            patch("zfundpilot.fetch_dividend.db.update_dividend_alert") as mock_update,
            patch("zfundpilot.fetch_dividend.db.get_transactions", return_value=[]),
        ):
            fetch_dividend.check_dividends()

        mock_update.assert_not_called()


class TestDividendAlertsChannelMigration:
    """dividend_alerts 旧库升级：加 channel 列 + 4 列唯一约束 + 单渠道回填。"""

    OLD_SCHEMA = """
        CREATE TABLE dividend_alerts (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            fund_code        TEXT NOT NULL,
            fund_name        TEXT DEFAULT '',
            record_date      TEXT,
            ex_date          TEXT,
            per_share        REAL,
            pay_date         TEXT,
            held_shares      REAL,
            estimated_amount REAL,
            dividend_method  TEXT DEFAULT 'cash',
            status           TEXT DEFAULT 'pending',
            created_at       TEXT DEFAULT (datetime('now','localtime')),
            resolved_at      TEXT,
            tx_id            INTEGER,
            alert_type       TEXT DEFAULT 'dividend',
            triggered_return REAL,
            threshold        REAL,
            UNIQUE(fund_code, ex_date, alert_type)
        );
    """

    def _setup_db(self, tmp_path):
        from zfundpilot import config
        from zfundpilot import db as db_module
        original = config.DB_PATH
        config.DB_PATH = tmp_path / "mig.db"
        db_module.init_db()
        return db_module, config, original

    def _downgrade(self, db):
        """把新库还原成 0.27.0 的旧 schema，模拟升级现场。"""
        with db.get_connection() as conn:
            conn.execute("DROP TABLE dividend_alerts")
            conn.executescript(self.OLD_SCHEMA)

    def _add_buy(self, db, channel):
        db.add_transaction(Transaction(
            fund_code="008115", action="buy", date="2026-10-01",
            amount=1000.0, shares=723.9, nav=1.38, fee=0,
            channel=channel, note="",
        ))

    def test_migration_adds_channel_and_backfills_single_channel(self, tmp_path):
        """旧库单渠道持仓 → 回填 channel，约束改为 4 列 UNIQUE，幂等。"""
        from zfundpilot import analysis

        db, config, original = self._setup_db(tmp_path)
        try:
            self._downgrade(db)
            with db.get_connection() as conn:
                conn.execute(
                    "INSERT INTO dividend_alerts (fund_code, ex_date, status) "
                    "VALUES ('008115', '2026-11-18', 'pending')"
                )
            self._add_buy(db, "支付宝")
            analysis.clear_analysis_cache()

            db.init_db()

            alerts = db.get_dividend_alerts()
            assert len(alerts) == 1
            assert alerts[0]["channel"] == "支付宝"
            with db.get_connection() as conn:
                sql = conn.execute(
                    "SELECT sql FROM sqlite_master "
                    "WHERE type='table' AND name='dividend_alerts'"
                ).fetchone()["sql"]
            assert "UNIQUE(fund_code, ex_date, alert_type, channel)" in sql
            assert "channel" in sql

            # 幂等：再跑一次不重复迁移、不丢数据
            db.init_db()
            alerts = db.get_dividend_alerts()
            assert len(alerts) == 1
            assert alerts[0]["channel"] == "支付宝"
        finally:
            analysis.clear_analysis_cache()
            config.DB_PATH = original

    def test_migration_leaves_multichannel_ambiguous(self, tmp_path):
        """旧库多渠道持仓 → 无法判定归属，保留空渠道待扫描按渠道重建。"""
        from zfundpilot import analysis

        db, config, original = self._setup_db(tmp_path)
        try:
            self._downgrade(db)
            with db.get_connection() as conn:
                conn.execute(
                    "INSERT INTO dividend_alerts (fund_code, ex_date, status) "
                    "VALUES ('008115', '2026-11-18', 'pending')"
                )
            self._add_buy(db, "支付宝")
            self._add_buy(db, "理财通")
            analysis.clear_analysis_cache()

            db.init_db()

            alerts = db.get_dividend_alerts()
            assert len(alerts) == 1
            assert (alerts[0]["channel"] or "") == ""
        finally:
            analysis.clear_analysis_cache()
            config.DB_PATH = original
