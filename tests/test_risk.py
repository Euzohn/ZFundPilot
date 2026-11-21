"""风险指标测试：最大回撤、波动率、组合现金流调整口径。"""
import pandas as pd

from zfundpilot import risk
from zfundpilot.risk import calculate_max_drawdown, calculate_volatility


class TestMaxDrawdown:
    def test_normal_drawdown(self):
        values = pd.Series([100, 120, 90, 110])
        dd = calculate_max_drawdown(values)
        assert dd is not None
        assert dd < 0
        # peak=120, trough=90 → (90-120)/120 = -0.25
        assert abs(dd - (-0.25)) < 1e-6

    def test_no_drawdown(self):
        values = pd.Series([100, 110, 120])
        dd = calculate_max_drawdown(values)
        assert dd == 0.0

    def test_too_short(self):
        assert calculate_max_drawdown(pd.Series([100])) is None
        assert calculate_max_drawdown(pd.Series([])) is None

    def test_recovery_after_drawdown(self):
        values = pd.Series([100, 80, 120])
        dd = calculate_max_drawdown(values)
        # peak=100, trough=80 → -0.20 (later 120 doesn't erase the drawdown)
        assert abs(dd - (-0.20)) < 1e-6


class TestVolatility:
    def test_normal_case(self):
        values = pd.Series([100, 102, 101, 103, 105])
        vol = calculate_volatility(values, annualize=False)
        assert vol is not None
        assert vol > 0

    def test_too_short(self):
        assert calculate_volatility(pd.Series([100, 101]), annualize=False) is None
        assert calculate_volatility(pd.Series([100]), annualize=False) is None

    def test_constant_series(self):
        values = pd.Series([100, 100, 100, 100])
        vol = calculate_volatility(values, annualize=False)
        assert vol == 0.0


class TestPortfolioDrawdownAndVol:
    """组合回撤/波动须剔除申赎现金流。

    回归：旧实现直接在原始市值序列上计算，部分赎回 50% 被记为 -50% 回撤，
    大额申购被 pct_change 当作日收益夸大波动率。
    """

    @staticmethod
    def _patch_curve(monkeypatch, values, costs):
        dates = pd.date_range("2025-01-01", periods=len(values)).strftime("%Y-%m-%d").tolist()
        df = pd.DataFrame({
            "date": dates,
            "total_value": values,
            "invested_cost": costs,
            "total_return": [v / c - 1 for v, c in zip(values, costs)],
        })
        monkeypatch.setattr("zfundpilot.risk.analysis.build_portfolio_curve", lambda: df)

    def test_partial_redemption_not_drawdown(self, monkeypatch):
        """赎回 50%：市值与投入成本同额下降 → 调整收益为 0，无回撤无波动。"""
        self._patch_curve(monkeypatch, [1000, 1000, 500, 500], [1000, 1000, 500, 500])
        dd, vol = risk.portfolio_drawdown_and_vol()
        assert dd == 0.0
        assert vol == 0.0

    def test_subscription_not_volatility(self, monkeypatch):
        """大额申购：市值翻倍但成本同增 → 不产生虚假波动。"""
        self._patch_curve(monkeypatch, [1000, 2000, 2000, 2000], [1000, 2000, 2000, 2000])
        dd, vol = risk.portfolio_drawdown_and_vol()
        assert dd == 0.0
        assert vol == 0.0

    def test_cash_dividend_not_drawdown(self, monkeypatch):
        """现金分红（曲线口径成本同减）→ 不记为回撤。"""
        self._patch_curve(monkeypatch, [1000, 1000, 950, 950], [1000, 1000, 950, 950])
        dd, vol = risk.portfolio_drawdown_and_vol()
        assert dd == 0.0
        assert vol == 0.0

    def test_real_market_drawdown_preserved(self, monkeypatch):
        """无申赎时真实行情回撤保留：1000→1100→900→950，mdd=(900-1100)/1100。"""
        self._patch_curve(monkeypatch, [1000, 1100, 900, 950], [1000] * 4)
        dd, vol = risk.portfolio_drawdown_and_vol()
        assert dd is not None
        assert abs(dd - (-2 / 11)) < 1e-9
        assert vol is not None
        assert vol > 0

    def test_empty_curve(self, monkeypatch):
        empty = pd.DataFrame(columns=["date", "total_value", "invested_cost", "total_return"])
        monkeypatch.setattr("zfundpilot.risk.analysis.build_portfolio_curve", lambda: empty)
        assert risk.portfolio_drawdown_and_vol() == (None, None)
