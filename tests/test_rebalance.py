"""rebalance 模块测试：结构优化建议生成。"""
from unittest.mock import patch

from zfundpilot.models import Position
from zfundpilot.risk import RiskReport
from zfundpilot.rebalance import Advice, generate_advice


def _make_position(code="001", held_shares=100, market_value=1000, total_cost=1000, **kw):
    return Position(
        fund_code=code, fund_name=kw.get("name", f"Fund {code}"),
        fund_type=kw.get("fund_type", "股票型"),
        sector=kw.get("sector", ""),
        held_shares=held_shares, total_cost=total_cost, market_value=market_value,
        channel=kw.get("channel", ""),
    )


def _make_report(**kw):
    defaults = dict(
        max_single_weight=kw.get("max_single_weight", 0.4),
        max_single_name=kw.get("max_single_name", "Fund A"),
        equity_weight=kw.get("equity_weight", 0.6),
        bond_weight=kw.get("bond_weight", 0.3),
        qdii_weight=kw.get("qdii_weight", 0.0),
    )
    return RiskReport(**defaults)


class TestGenerateAdvice:
    def test_empty_positions(self):
        advice = generate_advice(positions=[], report=_make_report())
        assert len(advice) == 1
        assert advice[0].code == "no_holding"

    def test_balanced_portfolio(self):
        positions = [_make_position("001", market_value=500), _make_position("002", market_value=500)]
        report = _make_report(max_single_weight=0.15, equity_weight=0.4, bond_weight=0.4)
        advice = generate_advice(positions=positions, report=report)
        codes = [a.code for a in advice]
        assert "balanced" in codes

    def test_concentration_high(self):
        positions = [_make_position("001", market_value=900), _make_position("002", market_value=100)]
        report = _make_report(max_single_weight=0.9, max_single_name="Fund 001")
        advice = generate_advice(positions=positions, report=report)
        codes = [a.code for a in advice]
        assert "concentration_high" in codes

    def test_concentration_mid(self):
        positions = [_make_position("001", market_value=700), _make_position("002", market_value=300)]
        report = _make_report(max_single_weight=0.25, max_single_name="Fund 001")
        advice = generate_advice(positions=positions, report=report)
        codes = [a.code for a in advice]
        assert "concentration_mid" in codes

    def test_equity_heavy(self):
        positions = [_make_position("001", market_value=1000)]
        report = _make_report(equity_weight=0.8)
        advice = generate_advice(positions=positions, report=report)
        codes = [a.code for a in advice]
        assert "equity_heavy" in codes

    def test_bond_low(self):
        positions = [_make_position("001", market_value=1000)]
        report = _make_report(bond_weight=0.05)
        advice = generate_advice(positions=positions, report=report)
        codes = [a.code for a in advice]
        assert "bond_low" in codes

    def test_qdii_high(self):
        positions = [_make_position("001", market_value=1000)]
        report = _make_report(qdii_weight=0.35)
        advice = generate_advice(positions=positions, report=report)
        codes = [a.code for a in advice]
        assert "qdii_high" in codes

    def test_advice_has_required_fields(self):
        positions = [_make_position("001", market_value=1000)]
        report = _make_report(max_single_weight=0.95, max_single_name="Fund 001")
        advice = generate_advice(positions=positions, report=report)
        for a in advice:
            assert isinstance(a, Advice)
            assert a.code
            assert isinstance(a.params, dict)
            assert a.category
            assert a.text
