"""compare 模块纯函数测试：收益率、风险指标、相关性、归一化。"""
from unittest.mock import patch

import numpy as np
import pandas as pd

from zfundpilot import fetch_fund
from zfundpilot.compare import (
    _calculate_calmar,
    _calculate_correlation,
    _calculate_max_drawdown,
    _calculate_period_return,
    _calculate_sharpe,
    _calculate_volatility,
    _calculate_win_rate,
    _get_fund_archive,
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

    def test_annualized_over_two_years(self):
        """两年（504 交易日）累计 100%、回撤 -20% → Calmar=(sqrt(2)-1)/0.2。

        回归：旧口径未年化，分子直接用累计收益 1.0 → 错误结果 5.0。
        """
        nav = pd.Series(np.concatenate([
            np.linspace(1.0, 1.5, 101),       # 上涨段
            np.linspace(1.5, 1.2, 101)[1:],   # 回撤段：mdd = (1.2-1.5)/1.5 = -0.2
            np.linspace(1.2, 2.0, 304)[1:],   # 回升段
        ]))
        assert len(nav) == 504
        calmar = _calculate_calmar(nav)
        expected = ((1 + 1.0) ** (252 / 504) - 1) / 0.2
        assert calmar is not None
        assert abs(calmar - expected) < 1e-6
        assert calmar < 5.0  # 旧未年化口径为 5.0

    def test_one_year_window_annual_equals_total(self):
        """252 交易日窗口：年化=累计，Calmar = 累计收益/|mdd| = 1.0/0.2 = 5.0。"""
        nav = pd.Series(np.concatenate([
            np.linspace(1.0, 1.5, 51),
            np.linspace(1.5, 1.2, 51)[1:],
            np.linspace(1.2, 2.0, 152)[1:],
        ]))
        assert len(nav) == 252
        calmar = _calculate_calmar(nav)
        assert calmar is not None
        assert abs(calmar - 5.0) < 1e-6


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

    def test_daily_returns_not_nav_levels(self):
        """共同上涨趋势 + 相反日度波动：水平相关近 1（旧口径伪相关），收益率相关应为负。"""
        n = 40
        idx = pd.date_range("2025-01-01", periods=n)
        trend = 100.0 + np.arange(n) * 2.0
        osc = np.where(np.arange(n) % 2 == 0, 0.5, -0.5)
        nav1 = pd.Series(trend + osc, index=idx)
        nav2 = pd.Series(trend - osc, index=idx)
        assert nav1.corr(nav2) > 0.9  # 净值水平口径虚高
        corr = _calculate_correlation(nav1, nav2)
        assert corr is not None
        assert corr < -0.5

    def test_proportional_navs_perfect(self):
        """净值成比例 → 日收益率完全相同 → 相关系数 1。"""
        idx = pd.date_range("2025-01-01", periods=20)
        nav1 = pd.Series(1.0 + np.arange(20) * 0.1, index=idx)
        nav2 = nav1 * 2.0
        corr = _calculate_correlation(nav1, nav2)
        assert corr is not None
        assert abs(corr - 1.0) < 1e-9

    def test_threshold_applies_to_returns(self):
        """样本阈值作用于收益率序列：10 个对齐点仅 9 个日收益 → None；11 点可算。"""
        idx10 = pd.date_range("2025-01-01", periods=10)
        nav1 = pd.Series(np.linspace(1.0, 2.0, 10), index=idx10)
        assert _calculate_correlation(nav1, nav1 * 1.5) is None
        idx11 = pd.date_range("2025-01-01", periods=11)
        nav1 = pd.Series(np.linspace(1.0, 2.0, 11), index=idx11)
        assert _calculate_correlation(nav1, nav1 * 1.5) is not None

    def test_constant_series_returns_none(self):
        """一只基金净值恒定（收益率零方差）→ 相关无定义 → None 而非 NaN。"""
        idx = pd.date_range("2025-01-01", periods=20)
        nav1 = pd.Series([1.0] * 20, index=idx)
        nav2 = pd.Series(1.0 + np.arange(20) * 0.01, index=idx)
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


# ---------------------------------------------------------------------------
# _get_fund_archive（天天基金档案页解析）
# ---------------------------------------------------------------------------
_ARCHIVE_HTML = """
<div class="bs_gl">
  <p>
    <label>成立日期：<span>2008-06-19</span></label>
    <label>基金经理：&nbsp;&nbsp;<a href="//fund.eastmoney.com/manager/30189744.html">张坤</a>&nbsp;&nbsp;<a href="//fund.eastmoney.com/manager/30808626.html">彭珂</a></label>
    <label>净资产规模：<span>
        67.77亿元
        （截止至：2026-06-30）</span></label>
  </p>
</div>
<table class="info w790"><tr><th>基金经理人</th><td><a href="//fund.eastmoney.com/manager/30189744.html">张坤</a>、<a href="//fund.eastmoney.com/manager/30808626.html">彭珂</a></td><th>成立来分红</th><td>每份累计1.79元</td></tr></table>
"""

_OVERVIEW_ONLY_HTML = """
<div class="bs_gl">
  <label>基金经理：&nbsp;&nbsp;<a href="//fund.eastmoney.com/manager/1.html">张三</a></label>
</div>
"""


class TestGetFundArchive:
    def test_parse_overview_and_table(self):
        with patch.object(fetch_fund, "_http_get", return_value=_ARCHIVE_HTML):
            archive = _get_fund_archive("110011")
        assert archive["inception"] == "2008-06-19"
        assert archive["scale"] == 67.77
        assert archive["manager"] == "张坤、彭珂"

    def test_manager_falls_back_to_overview(self):
        with patch.object(fetch_fund, "_http_get", return_value=_OVERVIEW_ONLY_HTML):
            archive = _get_fund_archive("000001")
        assert archive["manager"] == "张三"

    def test_legacy_scale_label(self):
        html = "<label>基金规模：12.34亿元</label>"
        with patch.object(fetch_fund, "_http_get", return_value=html):
            archive = _get_fund_archive("000002")
        assert archive["scale"] == 12.34

    def test_scale_in_table_cell(self):
        html = "<table><tr><th>净资产规模</th><td>8.88亿元（截止至：2026年06月30日）</td></tr></table>"
        with patch.object(fetch_fund, "_http_get", return_value=html):
            archive = _get_fund_archive("000003")
        assert archive["scale"] == 8.88

    def test_fetch_failure_returns_fallback(self):
        with patch.object(fetch_fund, "_http_get", side_effect=RuntimeError("boom")):
            archive = _get_fund_archive("000004")
        assert archive == {"inception": "", "scale": None, "manager": ""}
