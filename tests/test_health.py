"""组合体检评分模型测试。

验证：
1. calculate_liquidity 流动性权重计算
2. 四维评分函数（配置/风险/流动性/收益）
3. 定级边界值
4. 数据缺失降级
"""
from unittest.mock import patch

from zfundpilot.health import (
    _score_allocation,
    _score_liquidity,
    _score_return,
    _score_risk,
    _tier,
    calculate_liquidity,
)
from zfundpilot.models import PortfolioSummary, Position
from zfundpilot.risk import RiskReport

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _pos(fund_type: str, market_value: float, fund_name: str = "", weight: float = 0.0,
         fund_code: str = "000000") -> Position:
    return Position(
        fund_code=fund_code, fund_name=fund_name or f"fund_{fund_code}",
        fund_type=fund_type, sector="",
        channel="", tracking_index="",
        market_value=market_value, weight=weight,
    )


def _summary(total_return=0.05, annualized=0.06, holding_count=3) -> PortfolioSummary:
    return PortfolioSummary(
        total_return=total_return,
        annualized_return=annualized,
        holding_count=holding_count or 0,
        total_cost=50000, total_value=52500,
    )


def _report(max_single_weight=0.25, max_single_name="fund_a", hhi=0.12,
            equity_weight=0.65, bond_weight=0.20, qdii_weight=0.15,
            max_drawdown=-0.12, volatility=0.18) -> RiskReport:
    return RiskReport(
        max_single_weight=max_single_weight, max_single_name=max_single_name,
        hhi=hhi, equity_weight=equity_weight, bond_weight=bond_weight,
        qdii_weight=qdii_weight,
        max_drawdown=max_drawdown, volatility=volatility,
    )


# ---------------------------------------------------------------------------
# calculate_liquidity
# ---------------------------------------------------------------------------

class TestCalculateLiquidity:
    def test_all_bond(self):
        positions = [
            _pos("债券型", 5000), _pos("债券型", 5000),
        ]
        s, v = calculate_liquidity(positions)
        assert s == 1.0
        assert v == 0.0

    def test_all_equity(self):
        positions = [
            _pos("股票型", 3000), _pos("混合型", 3000), _pos("指数型", 4000),
        ]
        s, v = calculate_liquidity(positions)
        assert s == 0.0
        assert v == 1.0

    def test_mixed(self):
        positions = [
            _pos("债券型", 2000),
            _pos("股票型", 3000),
            _pos("QDII", 5000),
        ]
        s, v = calculate_liquidity(positions)
        assert abs(s - 0.2) < 0.01
        assert abs(v - 0.8) < 0.01

    def test_empty(self):
        s, v = calculate_liquidity([])
        assert s == 0.0 and v == 0.0

    def test_zero_value(self):
        s, v = calculate_liquidity([_pos("债券型", 0), _pos("股票型", 0)])
        assert s == 0.0 and v == 0.0


# ---------------------------------------------------------------------------
# _tier
# ---------------------------------------------------------------------------

class TestTier:
    def test_excellent(self):
        assert _tier(85) == "excellent"
        assert _tier(80) == "excellent"

    def test_good(self):
        assert _tier(72) == "good"
        assert _tier(60) == "good"

    def test_fair(self):
        assert _tier(50) == "fair"
        assert _tier(40) == "fair"

    def test_attention(self):
        assert _tier(30) == "attention"
        assert _tier(20) == "attention"

    def test_danger(self):
        assert _tier(15) == "danger"
        assert _tier(0) == "danger"


# ---------------------------------------------------------------------------
# _score_allocation
# ---------------------------------------------------------------------------

class TestScoreAllocation:
    def test_balanced(self):
        dim = _score_allocation(_report(max_single_weight=0.15, equity_weight=0.55, bond_weight=0.30),
                                _summary())
        assert dim.score >= 90

    def test_high_single_fund(self):
        dim = _score_allocation(_report(max_single_weight=0.42), _summary())
        assert dim.score <= 70  # -30

    def test_equity_heavy(self):
        dim = _score_allocation(_report(equity_weight=0.85, bond_weight=0.03), _summary())
        assert dim.score <= 70  # -20 -10


# ---------------------------------------------------------------------------
# _score_risk
# ---------------------------------------------------------------------------

class TestScoreRisk:
    def test_low_risk(self):
        dim = _score_risk(_report(max_drawdown=-0.05, volatility=0.10))
        assert dim.score >= 90

    def test_high_drawdown(self):
        dim = _score_risk(_report(max_drawdown=-0.18))
        assert dim.score <= 80  # -20

    def test_deep_drawdown(self):
        dim = _score_risk(_report(max_drawdown=-0.22))
        assert dim.score <= 70  # -30

    def test_no_data(self):
        dim = _score_risk(_report(max_drawdown=None, volatility=None))
        assert dim.score == 70  # neutral, status warning

    def test_high_volatility(self):
        dim = _score_risk(_report(volatility=0.30))
        assert dim.score <= 80  # -20 (>= 0.30)


# ---------------------------------------------------------------------------
# _score_liquidity
# ---------------------------------------------------------------------------

class TestScoreLiquidity:
    def test_good_liquidity(self):
        dim = _score_liquidity(stable_weight=0.25, holding_count=6, max_single_weight=0.15)
        assert dim.score >= 80  # base 50 + 30 + 10

    def test_thin_liquidity(self):
        dim = _score_liquidity(stable_weight=0.03, holding_count=2, max_single_weight=0.10)
        assert dim.score <= 40  # base 50 - 10 (stable < 5%)

    def test_concentrated(self):
        dim = _score_liquidity(stable_weight=0.12, holding_count=3, max_single_weight=0.45)
        assert dim.score <= 65  # base 50 + 15 - 10 (concentrated)

    def test_multiple_diverse(self):
        dim = _score_liquidity(stable_weight=0.08, holding_count=7, max_single_weight=0.20)
        assert dim.score >= 60  # base 50 + 10 (diverse)


# ---------------------------------------------------------------------------
# _score_return
# ---------------------------------------------------------------------------

class TestScoreReturn:
    def test_positive_beat_cpi(self):
        dim = _score_return(_summary(total_return=0.15, annualized=0.08), cpi_total=0.05)
        assert dim.score >= 80  # base 50 + 15 + 15

    def test_positive_lose_to_cpi(self):
        dim = _score_return(_summary(total_return=0.03, annualized=0.02), cpi_total=0.05)
        assert dim.score == 65  # base 50 + 15

    def test_negative_return(self):
        dim = _score_return(_summary(total_return=-0.05, annualized=-0.03), cpi_total=0.03)
        assert dim.score <= 30  # base 50 - 20

    def test_deep_loss(self):
        dim = _score_return(_summary(total_return=-0.15, annualized=-0.12), cpi_total=0.03)
        assert dim.score <= 10  # base 50 - 20 - 20

    def test_no_cpi_data(self):
        dim = _score_return(_summary(total_return=0.10, annualized=0.07), cpi_total=None)
        assert dim.score == 65  # base 50 + 15, no CPI bonus

    def test_no_annualized(self):
        dim = _score_return(_summary(annualized=None), cpi_total=0.03)
        assert dim.score == 50  # neutral
        assert dim.metrics["annualized_return"] is None


# ---------------------------------------------------------------------------
# build_health_report integration
# ---------------------------------------------------------------------------

class TestBuildHealthReport:
    def test_empty_portfolio(self):
        """空持仓产出的体检报告：各维度最低分，danger 定级。"""
        from zfundpilot.health import build_health_report
        empty_positions: list[Position] = []
        empty_summary = PortfolioSummary()
        empty_report = _report(
            max_single_weight=0.0, max_single_name="", hhi=0.0,
            equity_weight=0.0, bond_weight=0.0, qdii_weight=0.0,
            max_drawdown=None, volatility=None,
        )
        empty_advice: list = []

        with patch("zfundpilot.health.analysis.calculate_positions", return_value=empty_positions), \
             patch("zfundpilot.health.analysis.calculate_summary", return_value=empty_summary), \
             patch("zfundpilot.health.build_risk_report", return_value=empty_report), \
             patch("zfundpilot.health.generate_advice", return_value=empty_advice), \
             patch("zfundpilot.health.fetch_macro.fetch_macro_baseline", return_value=None):
            hr = build_health_report()
            assert hr.overall_tier == "danger"
            assert hr.overall_score <= 20
            assert len(hr.dimensions) == 4
            assert hr.stable_weight == 0.0
            assert hr.volatile_weight == 0.0

    def test_healthy_portfolio(self):
        """健康组合产出优秀评级。"""
        from zfundpilot.health import build_health_report

        positions = [
            _pos("债券型", 3000, fund_name="BondF", weight=0.3),
            _pos("股票型", 2500, fund_name="StockA", weight=0.25),
            _pos("混合型", 2000, fund_name="MixedB", weight=0.2),
            _pos("指数型", 1500, fund_name="IndexC", weight=0.15),
            _pos("QDII", 1000, fund_name="QDII_D", weight=0.1),
        ]
        summary = PortfolioSummary(
            total_return=0.25, annualized_return=0.10, holding_count=5,
            total_cost=8000, total_value=10000,
        )
        report = _report(
            max_single_weight=0.30, max_single_name="BondF", hhi=0.22,
            equity_weight=0.60, bond_weight=0.30, qdii_weight=0.10,
            max_drawdown=-0.08, volatility=0.12,
        )
        advice: list = []

        with patch("zfundpilot.health.analysis.calculate_positions", return_value=positions), \
             patch("zfundpilot.health.analysis.calculate_summary", return_value=summary), \
             patch("zfundpilot.health.build_risk_report", return_value=report), \
             patch("zfundpilot.health.generate_advice", return_value=advice), \
             patch("zfundpilot.health.fetch_macro.fetch_macro_baseline", return_value=([{"date": "2025-01-01", "close": 105.0}], 100.0)):
            hr = build_health_report()
            assert hr.overall_score >= 80
            assert hr.overall_tier == "excellent"
            assert hr.stable_weight == 0.3
