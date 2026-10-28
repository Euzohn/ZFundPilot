"""backtest 模块纯函数测试：日期生成、XIRR、费用计算、曲线构建。"""
import datetime as dt

import pandas as pd

from zfundpilot import backtest
from zfundpilot.backtest import (
    _build_curve,
    _calc_redemption_fee_simulated,
    _generate_investment_dates,
    _parse_date,
    _resolve_nav_date,
    clean_nav_rows,
    readonly_nav_rows,
    run_dca_backtest,
)
from zfundpilot.fetch_fund import FeeRates, PurchaseTier, RedemptionTier
from zfundpilot.returns import xirr


# ---------------------------------------------------------------------------
# _parse_date
# ---------------------------------------------------------------------------
class TestParseDate:
    def test_valid(self):
        assert _parse_date("2025-03-15") == dt.date(2025, 3, 15)

    def test_leap_year(self):
        assert _parse_date("2024-02-29") == dt.date(2024, 2, 29)


# ---------------------------------------------------------------------------
# _generate_investment_dates
# ---------------------------------------------------------------------------
class TestGenerateInvestmentDates:
    def test_monthly(self):
        dates = _generate_investment_dates("2025-01-01", "2025-06-30", "month")
        assert dates == [
            "2025-01-01", "2025-02-01", "2025-03-01",
            "2025-04-01", "2025-05-01", "2025-06-01",
        ]

    def test_weekly(self):
        dates = _generate_investment_dates("2025-01-01", "2025-01-22", "week")
        assert dates == [
            "2025-01-01", "2025-01-08", "2025-01-15", "2025-01-22",
        ]

    def test_biweekly(self):
        dates = _generate_investment_dates("2025-01-01", "2025-02-28", "biweek")
        assert dates == ["2025-01-01", "2025-01-15", "2025-01-29", "2025-02-12", "2025-02-26"]

    def test_monthly_starts_at_requested_start(self):
        # 首期不得早于请求起日，否则会把起日前的投入算进区间
        dates = _generate_investment_dates("2025-06-15", "2025-06-15", "month")
        assert dates == ["2025-06-15"]

    def test_empty_when_start_after_end(self):
        dates = _generate_investment_dates("2025-06-01", "2025-01-01", "month")
        assert dates == []

    def test_monthly_cross_year(self):
        dates = _generate_investment_dates("2025-11-01", "2026-02-28", "month")
        assert dates == ["2025-11-01", "2025-12-01", "2026-01-01", "2026-02-01"]


# ---------------------------------------------------------------------------
# _resolve_nav_date
# ---------------------------------------------------------------------------
class TestResolveNavDate:
    def test_exact_match(self):
        dates = ["2025-01-01", "2025-01-02", "2025-01-03"]
        assert _resolve_nav_date(dates, "2025-01-02") == 1

    def test_between_dates(self):
        dates = ["2025-01-01", "2025-01-05", "2025-01-10"]
        assert _resolve_nav_date(dates, "2025-01-03") == 1

    def test_before_all(self):
        dates = ["2025-01-05", "2025-01-10"]
        assert _resolve_nav_date(dates, "2025-01-01") == 0

    def test_after_all(self):
        dates = ["2025-01-01", "2025-01-05"]
        assert _resolve_nav_date(dates, "2025-01-10") is None

    def test_empty_list(self):
        assert _resolve_nav_date([], "2025-01-01") is None


# ---------------------------------------------------------------------------
# xirr
# ---------------------------------------------------------------------------
class TestXirr:
    def test_simple_positive_return(self):
        cashflows = [
            (dt.date(2020, 1, 1), -1000),
            (dt.date(2021, 1, 1), 1100),
        ]
        result = xirr(cashflows)
        assert result is not None
        assert 0.09 < result < 0.11  # ~10%

    def test_no_solution(self):
        cashflows = [
            (dt.date(2020, 1, 1), 1000),
            (dt.date(2021, 1, 1), 1100),
        ]
        result = xirr(cashflows)
        assert result is None

    def test_single_cashflow(self):
        assert xirr([(dt.date(2020, 1, 1), -1000)]) is None

    def test_zero_return(self):
        cashflows = [
            (dt.date(2020, 1, 1), -1000),
            (dt.date(2021, 1, 1), 1000),
        ]
        result = xirr(cashflows)
        assert result is not None
        assert abs(result) < 0.01

    def test_multi_period(self):
        cashflows = [
            (dt.date(2020, 1, 1), -500),
            (dt.date(2020, 7, 1), -500),
            (dt.date(2021, 1, 1), 1100),
        ]
        result = xirr(cashflows)
        assert result is not None
        assert 0.05 < result < 0.15


# ---------------------------------------------------------------------------
# _calc_redemption_fee_simulated
# ---------------------------------------------------------------------------
class TestCalcRedemptionFee:
    def _make_fee_rates(self, tiers: list[tuple[int, int | None, float]]) -> FeeRates:
        fr = FeeRates(fund_code="test", ok=True)
        fr.redemption = [
            RedemptionTier(min_days=mn, max_days=mx, rate=r) for mn, mx, r in tiers
        ]
        return fr

    def test_no_fee_when_no_rates(self):
        fr = FeeRates(fund_code="test", ok=False)
        assert _calc_redemption_fee_simulated([], "2025-01-10", 2.0, fr) == 0.0

    def test_fee_within_first_tier(self):
        fr = self._make_fee_rates([(0, 7, 0.015)])
        lots = [("2025-01-05", 100)]
        # 5 days held, within 0-7 tier → 0.015 fee
        fee = _calc_redemption_fee_simulated(lots, "2025-01-10", 2.0, fr)
        assert abs(fee - 3.0) < 0.01  # 100 * 2.0 * 0.015 = 3.0

    def test_fee_after_long_hold(self):
        fr = self._make_fee_rates([(0, 7, 0.015), (8, 365, 0.005), (366, None, 0.0)])
        lots = [("2024-01-02", 100)]
        fee = _calc_redemption_fee_simulated(lots, "2025-01-01", 2.0, fr)
        # 364 days held → tier 8-365 → 0.005
        assert abs(fee - 1.0) < 0.01  # 100 * 2.0 * 0.005 = 1.0

    def test_zero_lots(self):
        fr = self._make_fee_rates([(0, 365, 0.01)])
        assert _calc_redemption_fee_simulated([], "2025-01-10", 2.0, fr) == 0.0

    def test_multiple_lots(self):
        fr = self._make_fee_rates([(0, 365, 0.01)])
        lots = [("2025-01-01", 100), ("2025-01-05", 200)]
        fee = _calc_redemption_fee_simulated(lots, "2025-01-10", 2.0, fr)
        # Both lots in same tier
        assert abs(fee - 6.0) < 0.01  # (100+200) * 2.0 * 0.01

    def test_no_redemption_tiers(self):
        fr = FeeRates(fund_code="test", ok=True)
        fr.redemption = []
        lots = [("2025-01-01", 100)]
        fee = _calc_redemption_fee_simulated(lots, "2025-01-10", 2.0, fr)
        assert fee == 0.0


# ---------------------------------------------------------------------------
# _build_curve
# ---------------------------------------------------------------------------
class TestBuildCurve:
    def test_basic(self):
        timeline = ["2025-01-01", "2025-01-02", "2025-01-03"]
        navs = pd.Series([1.0, 1.1, 1.2], index=timeline)
        share_delta = pd.Series([100.0, 0.0, 50.0], index=timeline)
        cost_delta = pd.Series([100.0, 0.0, 50.0], index=timeline)
        curve = _build_curve(timeline, navs, share_delta, cost_delta)
        # All 3 dates have cumulative investment > 0
        assert len(curve) == 3
        assert curve[0]["date"] == "2025-01-01"
        assert curve[0]["invested"] == 100.0
        assert curve[0]["value"] == 100.0
        assert curve[0]["return"] == 0.0
        assert curve[2]["date"] == "2025-01-03"
        assert curve[2]["invested"] == 150.0
        assert curve[2]["value"] == 180.0  # 150 shares * 1.2 nav
        assert abs(curve[2]["return"] - 0.2) < 0.01

    def test_skips_zero_investment(self):
        timeline = ["2025-01-01", "2025-01-02"]
        navs = pd.Series([1.0, 1.1], index=timeline)
        share_delta = pd.Series([0.0, 100.0], index=timeline)
        cost_delta = pd.Series([0.0, 100.0], index=timeline)
        curve = _build_curve(timeline, navs, share_delta, cost_delta)
        assert len(curve) == 1
        assert curve[0]["date"] == "2025-01-02"


# ---------------------------------------------------------------------------
# 数据清洗与只读数据提供
# ---------------------------------------------------------------------------
class TestCleanNavRows:
    def test_rejects_invalid_and_dedupes(self):
        rows = [
            {"date": "2024-01-02", "nav": 1.0},
            {"date": "2024-01-02", "nav": 1.2},
            {"date": "2024-13-01", "nav": 1.0},
            {"date": "2024-01-03", "nav": 0},
            {"date": "2024-01-04", "nav": float("nan")},
            {"date": "2024-01-05", "nav": "bad"},
        ]
        assert clean_nav_rows(rows) == [{"date": "2024-01-02", "nav": 1.2}]

    def test_accepts_row_like_objects(self):
        class RowLike:
            def __init__(self, date, nav):
                self._data = {"date": date, "nav": nav}

            def __getitem__(self, key):
                return self._data[key]

        rows = [RowLike("2024-01-02", 1.0), RowLike("2024-02-02", 1.1)]

        assert [r["date"] for r in clean_nav_rows(rows)] == [
            "2024-01-02", "2024-02-02"]

    def test_clips_to_requested_period(self):
        rows = [
            {"date": "2023-12-31", "nav": 0.9},
            {"date": "2024-01-02", "nav": 1.0},
            {"date": "2024-02-02", "nav": 1.1},
        ]
        assert [r["date"] for r in clean_nav_rows(
            rows, "2024-01-01", "2024-01-31")] == ["2024-01-02"]


class TestReadonlyNavRows:
    def test_does_not_write_when_fetching(self, monkeypatch):
        points = [
            type("Point", (), {"date": "2024-01-02", "nav": 1.0})(),
            type("Point", (), {"date": "2024-02-01", "nav": 1.1})(),
        ]
        monkeypatch.setattr(
            backtest.db, "get_nav_history_by_period", lambda code, s, e: [])
        monkeypatch.setattr(
            backtest.fetch_fund, "fetch_nav_history", lambda code: points)

        def _forbidden(code):  # pragma: no cover - 写库时才会被调用
            raise AssertionError("readonly_nav_rows must not write NAV data")

        monkeypatch.setattr(
            backtest.fetch_fund, "update_fund_nav", _forbidden)

        rows, source = readonly_nav_rows(
            "000001", "2024-01-01", "2024-02-01")

        assert source == "remote"
        assert [r["date"] for r in rows] == ["2024-01-02", "2024-02-01"]

    def test_prefers_database_when_covered(self, monkeypatch):
        db_rows = [{"date": "2024-01-02", "nav": 1.0},
                   {"date": "2024-02-01", "nav": 1.1}]
        monkeypatch.setattr(
            backtest.db, "get_nav_history_by_period",
            lambda code, s, e: db_rows)

        def _unexpected(code):  # pragma: no cover
            raise AssertionError("should not fetch remote data")

        monkeypatch.setattr(
            backtest.fetch_fund, "fetch_nav_history", _unexpected)

        rows, source = readonly_nav_rows(
            "000001", "2024-01-02", "2024-02-01")

        assert source == "database"
        assert rows == db_rows

    def test_start_on_non_trading_day_does_not_refetch(self, monkeypatch):
        db_rows = [{"date": "2024-01-02", "nav": 1.0},
                   {"date": "2024-02-01", "nav": 1.1}]
        monkeypatch.setattr(
            backtest.db, "get_nav_history_by_period",
            lambda code, s, e: db_rows)

        def _unexpected(code):  # pragma: no cover
            raise AssertionError("weekend/holiday start must not refetch")

        monkeypatch.setattr(backtest.fetch_fund, "fetch_nav_history", _unexpected)

        rows, source = readonly_nav_rows(
            "000001", "2024-01-01", "2024-02-01")

        assert source == "database"
        assert rows == db_rows

    def test_remote_failure_keeps_database_rows(self, monkeypatch):
        db_rows = [{"date": "2024-01-02", "nav": 1.0},
                   {"date": "2024-02-01", "nav": 1.1}]
        monkeypatch.setattr(
            backtest.db, "get_nav_history_by_period",
            lambda code, s, e: db_rows)

        def _boom(code):
            raise RuntimeError("network down")

        monkeypatch.setattr(backtest.fetch_fund, "fetch_nav_history", _boom)

        rows, source = readonly_nav_rows(
            "000001", "2024-01-01", "2024-12-31")

        assert source == "database"
        assert rows == db_rows


# ---------------------------------------------------------------------------
# 定投口径与失败语义
# ---------------------------------------------------------------------------
def _rates(ok: bool = True) -> FeeRates:
    return FeeRates(
        fund_code="000001",
        ok=ok,
        purchase=[PurchaseTier(min_amount=0, rate=0.001)] if ok else [],
        redemption=([RedemptionTier(min_days=0, max_days=6, rate=0.015),
                     RedemptionTier(min_days=7, max_days=None, rate=0.005)]
                    if ok else []),
    )


class TestDcaSemantics:
    def test_skips_duplicate_nav_dates_and_reports_partial(self):
        rows = [{"date": "2024-01-01", "nav": 1.0},
                {"date": "2024-02-01", "nav": 1.1}]
        dates = [r["date"] for r in rows]
        navs = pd.Series({r["date"]: r["nav"] for r in rows}, index=dates)

        result = backtest._run_dca(
            "000001", "测试", dates, navs, "2024-01-01", "2024-02-01",
            100, "week", _rates(), "database")

        assert result.status == "partial"
        assert result.code == "partial_coverage"
        assert result.total_periods == 2
        assert result.skipped_periods == 3
        assert result.periods_detail[1]["actual_date"] == "2024-02-01"

    def test_valuation_date_uses_last_nav_not_requested_end(self):
        rows = [{"date": "2024-01-02", "nav": 1.0},
                {"date": "2024-02-01", "nav": 1.1},
                {"date": "2024-03-01", "nav": 1.2}]
        dates = [r["date"] for r in rows]
        navs = pd.Series({r["date"]: r["nav"] for r in rows}, index=dates)

        result = backtest._run_dca(
            "000001", "测试", dates, navs, "2024-01-01", "2024-12-31",
            1000, "month", _rates(), "database")

        assert result.status == "ok"
        assert result.period_end == "2024-12-31"
        assert result.valuation_date == "2024-03-01"
        assert result.data_end == "2024-03-01"
        assert result.periods_detail[-1]["actual_date"] == "2024-03-01"

    def test_fee_unknown_is_flagged_not_silent_zero(self):
        rows = [{"date": "2024-01-02", "nav": 1.0},
                {"date": "2024-02-01", "nav": 1.1}]
        dates = [r["date"] for r in rows]
        navs = pd.Series({r["date"]: r["nav"] for r in rows}, index=dates)

        result = backtest._run_dca(
            "000001", "测试", dates, navs, "2024-01-01", "2024-02-01",
            100, "month", _rates(ok=False), "remote")

        assert result.fee_ok is False
        assert result.total_fees == 0
        assert any("费率表获取失败" in item for item in result.caveats)


class TestRunDcaBacktestFailure:
    def test_insufficient_nav_is_explicit_failure(self, monkeypatch):
        monkeypatch.setattr(
            backtest, "readonly_nav_rows", lambda code, s, e: ([], "none"))
        monkeypatch.setattr(backtest.db, "get_fund", lambda code: None)

        results = run_dca_backtest(
            ["000001"], "2024-01-01", "2024-02-01", 100,
            nav_provider=backtest.readonly_nav_rows)

        assert len(results) == 2
        assert all(r.status == "failed" for r in results)
        assert all(r.code == "insufficient_nav" for r in results)
        assert all(r.net_final_value == 0 for r in results)
