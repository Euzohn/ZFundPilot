"""compare 模块纯函数测试：收益率、风险指标、相关性、归一化。"""
import pandas as pd
import pytest

from zfundpilot.compare import (
    _calculate_calmar,
    _calculate_correlation,
    _calculate_max_drawdown,
    _calculate_period_return,
    _calculate_sharpe,
    _calculate_volatility,
    _calculate_win_rate,
    _nav_to_series,
    _normalize_nav,
)
from zfundpilot.models import NavPoint


# ---------------------------------------------------------------------------
# _nav_to_series
# ---------------------------------------------------------------------------
class TestNavToSeries:
    def test_basic(self):
        points = [
            NavPoint(fund_code="000001", date="2025-01-01", nav=1.0),
            NavPoint(fund_code="000001", date="2025-01-02", nav=1.1),
            NavPoint(fund_code="000001", date="2025-01-03", nav=1.2),
        ]
        s = _nav_to_series(points)
        assert len(s) == 3
        assert s.iloc[0] == 1.0
        assert s.iloc[-1] == 1.2

    def test_empty(self):
        s = _nav_to_series([])
        assert s.empty

    def test_dedup_last(self):
        points = [
            NavPoint(fund_code="000001", date="2025-01-01", nav=1.0),
            NavPoint(fund_code="000001", date="2025-01-01", nav=1.5),
        ]
        s = _nav_to_series(points)
        assert len(s) == 1
        assert s.iloc[0] == 1.5

    def test_sorted_by_date(self):
        points = [
            NavPoint(fund_code="000001", date="2025-01-03", nav=1.2),
            NavPoint(fund_code="000001", date="2025-01-01", nav=1.0),
            NavPoint(fund_code="000001", date="2025-01-02", nav=1.1),
        ]
        s = _nav_to_series(points)
        assert list(s.index) == sorted(s.index)


# ---------------------------------------------------------------------------
# _calculate_period_return
# ---------------------------------------------------------------------------
class TestCalculatePeriodReturn:
    def test_basic(self):
        nav = pd.Series([1.0, 1.1, 1.2, 1.3, 1.4], index=pd.date_range("2025-01-01", periods=5))
        ret = _calculate_period_return(nav, 2)
        assert ret is not None
        assert abs(ret - 0.1667) < 0.01  # (1.4-1.2)/1.2

    def test_too_short(self):
        nav = pd.Series([1.0])
        assert _calculate_period_return(nav, 5) is None

    def test_single_point(self):
        nav = pd.Series([1.0])
        assert _calculate_period_return(nav, 0) is None

    def test_zero_earlier(self):
        nav = pd.Series([0.0, 1.0], index=pd.date_range("2025-01-01", periods=2))
        assert _calculate_period_return(nav, 1) is None

    def test_full_period(self):
        nav = pd.Series([1.0, 1.1, 1.2], index=pd.date_range("2025-01-01", periods=3))
        ret = _calculate_period_return(nav, 10)
        assert ret is not None
        assert abs(ret - 0.2) < 0.01


# ---------------------------------------------------------------------------
# _calculate_max_drawdown
# ---------------------------------------------------------------------------
class TestMaxDrawdown:
    def test_basic(self):
        nav = pd.Series([1.0, 1.2, 1.1, 1.3, 0.9, 1.0])
        mdd = _calculate_max_drawdown(nav)
        assert mdd is not None
        assert mdd < 0  # drawdown is negative

    def test_monotonic_up(self):
        nav = pd.Series([1.0 + i * 0.1 for i in range(10)])
        mdd = _calculate_max_drawdown(nav)
        assert mdd is not None
        assert abs(mdd) < 0.001

    def test_too_short(self):
        nav = pd.Series([1.0, 1.1])
        assert _calculate_max_drawdown(nav) is None


# ---------------------------------------------------------------------------
# _calculate_volatility
# ---------------------------------------------------------------------------
class TestVolatility:
    def test_basic(self):
        nav = pd.Series([1.0 + i * 0.01 + (i % 2) * 0.005 for i in range(30)])
        vol = _calculate_volatility(nav)
        assert vol is not None
        assert vol > 0

    def test_too_short(self):
        nav = pd.Series([1.0] * 5)
        assert _calculate_volatility(nav) is None

    def test_constant_series(self):
        nav = pd.Series([1.0] * 20)
        vol = _calculate_volatility(nav)
        # constant → std=0, vol=0 (not None, since len >= 10)
        assert vol is not None
        assert vol == 0.0


# ---------------------------------------------------------------------------
# _calculate_sharpe
# ---------------------------------------------------------------------------
class TestSharpe:
    def test_basic(self):
        nav = pd.Series([1.0 + i * 0.001 for i in range(30)])
        sharpe = _calculate_sharpe(nav)
        assert sharpe is not None
        assert sharpe > 0  # positive trend

    def test_too_short(self):
        nav = pd.Series([1.0] * 5)
        assert _calculate_sharpe(nav) is None


# ---------------------------------------------------------------------------
# _calculate_calmar
# ---------------------------------------------------------------------------
class TestCalmar:
    def test_basic(self):
        nav = pd.Series([1.0, 1.1, 1.2, 1.0, 1.3])
        calmar = _calculate_calmar(nav)
        assert calmar is not None

    def test_too_short(self):
        nav = pd.Series([1.0])
        assert _calculate_calmar(nav) is None

    def test_no_drawdown(self):
        nav = pd.Series([1.0, 1.1, 1.2, 1.3])
        calmar = _calculate_calmar(nav)
        assert calmar is None  # mdd = 0 → division by zero guard


# ---------------------------------------------------------------------------
# _calculate_win_rate
# ---------------------------------------------------------------------------
class TestWinRate:
    def test_all_positive(self):
        idx = pd.date_range("2025-01-01", periods=60)
        nav = pd.Series([1.0 + i * 0.01 for i in range(60)], index=idx)
        wr = _calculate_win_rate(nav)
        assert wr is not None
        assert wr == 1.0

    def test_too_short(self):
        idx = pd.date_range("2025-01-01", periods=10)
        nav = pd.Series([1.0] * 10, index=idx)
        assert _calculate_win_rate(nav) is None


# ---------------------------------------------------------------------------
# _calculate_correlation
# ---------------------------------------------------------------------------
class TestCorrelation:
    def test_perfect_positive(self):
        nav1 = pd.Series([1.0 + i * 0.1 for i in range(20)])
        nav2 = pd.Series([2.0 + i * 0.2 for i in range(20)])
        corr = _calculate_correlation(nav1, nav2)
        assert corr is not None
        assert abs(corr - 1.0) < 0.001

    def test_empty(self):
        nav1 = pd.Series([1.0, 1.1])
        nav2 = pd.Series(dtype=float)
        assert _calculate_correlation(nav1, nav2) is None

    def test_too_few_overlapping(self):
        nav1 = pd.Series([1.0, 1.1])
        nav2 = pd.Series([1.0, 1.1])
        assert _calculate_correlation(nav1, nav2) is None


# ---------------------------------------------------------------------------
# _normalize_nav
# ---------------------------------------------------------------------------
class TestNormalizeNav:
    def test_basic(self):
        nav = pd.Series([2.0, 2.5, 3.0], index=pd.to_datetime(["2025-01-01", "2025-01-02", "2025-01-03"]))
        result = _normalize_nav(nav)
        assert len(result) == 3
        assert result[0]["value"] == 100.0  # base=100
        assert abs(result[1]["value"] - 125.0) < 0.1
        assert abs(result[2]["value"] - 150.0) < 0.1

    def test_empty(self):
        assert _normalize_nav(pd.Series(dtype=float)) == []

    def test_zero_first(self):
        nav = pd.Series([0.0, 1.0])
        assert _normalize_nav(nav) == []
