"""风险指标测试：最大回撤、波动率。"""
import pandas as pd

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
