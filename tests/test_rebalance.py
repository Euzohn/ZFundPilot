"""rebalance 模块测试：结构优化建议生成 + 四段可解释行动清单（P3 Phase 1）。"""
from zfundpilot.models import DataStatus, PortfolioSummary, Position
from zfundpilot.rebalance import (
    Advice,
    _reduce_row_to_weight,
    generate_advice,
)
from zfundpilot.risk import RiskReport


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


# ---------------------------------------------------------------------------
# P3 Phase 1：四段可解释结构（evidence/positions/simulation/risks）
# ---------------------------------------------------------------------------

def _by_code(advice, code):
    return next(a for a in advice if a.code == code)


class TestActionItemCompat:
    def test_old_constructor_still_works(self):
        a = Advice("x", {"k": 1}, "分类", "文本")
        assert a.evidence == []
        assert a.positions == []
        assert a.simulation is None
        assert a.risks == []

    def test_health_report_to_dict_carries_new_fields(self):
        from zfundpilot.health import HealthReport
        advice = generate_advice(positions=[], report=RiskReport())
        report = HealthReport(0, "danger", [], 0.0, 0.0, RiskReport(),
                              advice, PortfolioSummary())
        item = report.to_dict()["advice"][0]
        assert {"code", "params", "category", "text",
                "evidence", "positions", "simulation", "risks"} <= set(item)


class TestEvidenceAndRisks:
    def test_concentration_evidence_matches_trigger(self):
        positions = [_make_position("001", market_value=900),
                     _make_position("002", market_value=100)]
        report = _make_report(max_single_weight=0.9, max_single_name="Fund 001")
        a = _by_code(generate_advice(positions, report), "concentration_high")
        assert a.evidence == [{"metric": "max_single_weight", "value": 0.9,
                               "threshold": 0.40, "params": {"name": "Fund 001"}}]

    def test_involved_positions_concentration_is_top_fund(self):
        positions = [_make_position("001", market_value=900),
                     _make_position("002", market_value=100)]
        report = _make_report(max_single_weight=0.9, max_single_name="Fund 001")
        a = _by_code(generate_advice(positions, report), "concentration_high")
        assert len(a.positions) == 1
        assert a.positions[0]["fund_code"] == "001"
        assert abs(a.positions[0]["weight"] - 0.9) < 1e-9

    def test_involved_positions_equity_heavy_only_equity(self):
        positions = [_make_position("001", market_value=800),
                     _make_position("002", market_value=200, fund_type="债券型")]
        report = _make_report(equity_weight=0.8, bond_weight=0.2)
        a = _by_code(generate_advice(positions, report), "equity_heavy")
        assert [p["fund_code"] for p in a.positions] == ["001"]

    def test_risks_include_disclaimer_and_assumption(self):
        positions = [_make_position("001", market_value=900),
                     _make_position("002", market_value=100)]
        report = _make_report(max_single_weight=0.9, max_single_name="Fund 001")
        a = _by_code(generate_advice(positions, report), "concentration_high")
        codes = [r["code"] for r in a.risks]
        assert "not_investment_advice" in codes
        assert "model_limitation" in codes
        assert "simulation_assumption" in codes

    def test_data_stale_caveat_appended(self):
        positions = [_make_position("001", market_value=900),
                     _make_position("002", market_value=100)]
        report = _make_report(max_single_weight=0.9, max_single_name="Fund 001")
        ds = DataStatus(stale_nav_fund_count=2, missing_nav_fund_count=1)
        a = _by_code(generate_advice(positions, report, data_status=ds),
                     "concentration_high")
        stale = next(r for r in a.risks if r["code"] == "data_stale")
        assert stale["params"] == {"stale": 2, "missing": 1}

    def test_no_holding_and_balanced_risks(self):
        empty = generate_advice(positions=[], report=RiskReport())
        assert empty[0].risks == []
        positions = [_make_position("001", market_value=500),
                     _make_position("002", market_value=500)]
        report = _make_report(max_single_weight=0.15, equity_weight=0.4, bond_weight=0.4)
        balanced = _by_code(generate_advice(positions, report), "balanced")
        assert balanced.risks == [{"code": "not_investment_advice", "params": {}}]
        assert balanced.simulation is None
        assert balanced.evidence == []


class TestSimulation:
    def test_concentration_high_numbers_and_score(self):
        positions = [_make_position("001", market_value=500),
                     _make_position("002", market_value=300),
                     _make_position("003", market_value=200, fund_type="债券型")]
        report = _make_report(max_single_weight=0.5, max_single_name="Fund 001",
                              equity_weight=0.8, bond_weight=0.2)
        a = _by_code(generate_advice(positions, report), "concentration_high")
        sim = a.simulation
        assert sim["rule"] == "reduce_single_fund"
        assert sim["params"]["target"] == 0.40
        assert abs(sim["before"]["max_single_weight"] - 0.5) < 1e-9
        assert abs(sim["after"]["max_single_weight"] - 0.4) < 1e-9
        assert abs(sim["after"]["equity_weight"] - 0.76) < 1e-9
        assert abs(sim["after"]["bond_weight"] - 0.24) < 1e-9
        # 配置分：before 50（集中-30/权益-20），after 70（仅集中-30）
        assert sim["before"]["allocation_score"] == 50
        assert sim["after"]["allocation_score"] == 70

    def test_concentration_mid_target_warn(self):
        positions = [_make_position("001", market_value=700),
                     _make_position("002", market_value=300)]
        report = _make_report(max_single_weight=0.25, max_single_name="Fund 001")
        a = _by_code(generate_advice(positions, report), "concentration_mid")
        assert a.simulation["params"]["target"] == 0.20
        # 两只基金时腾出权重全给另一只：目标基金降到 20%，但组合最大权重
        # 诚实变为 80%（集中度转移）——what-if 演算如实展示该副作用。
        assert abs(a.simulation["after"]["max_single_weight"] - 0.8) < 1e-9

    def test_equity_heavy_transfers_to_bond(self):
        positions = [_make_position("001", market_value=800),
                     _make_position("002", market_value=200, fund_type="债券型")]
        report = _make_report(equity_weight=0.8, bond_weight=0.2)
        a = _by_code(generate_advice(positions, report), "equity_heavy")
        sim = a.simulation
        assert sim["rule"] == "equity_to_bond"
        assert sim["params"]["side"] == "equity"
        assert abs(sim["after"]["equity_weight"] - 0.7) < 1e-9
        assert abs(sim["after"]["bond_weight"] - 0.3) < 1e-9

    def test_equity_heavy_no_bond_unavailable(self):
        positions = [_make_position("001", market_value=600),
                     _make_position("002", market_value=400)]
        report = _make_report(equity_weight=1.0, bond_weight=0.0)
        a = _by_code(generate_advice(positions, report), "equity_heavy")
        assert a.simulation is None
        assert {"code": "simulation_unavailable", "params": {}} in a.risks

    def test_bond_low_raises_to_min(self):
        positions = [_make_position("001", market_value=950),
                     _make_position("002", market_value=50, fund_type="债券型")]
        report = _make_report(equity_weight=0.95, bond_weight=0.05)
        a = _by_code(generate_advice(positions, report), "bond_low")
        sim = a.simulation
        assert sim["params"]["side"] == "bond"
        assert abs(sim["after"]["bond_weight"] - 0.1) < 1e-9
        assert abs(sim["after"]["equity_weight"] - 0.9) < 1e-9

    def test_qdii_high_reduces_to_warn(self):
        positions = [_make_position("001", market_value=400, fund_type="QDII"),
                     _make_position("002", market_value=600)]
        report = _make_report(qdii_weight=0.4)
        a = _by_code(generate_advice(positions, report), "qdii_high")
        sim = a.simulation
        assert sim["rule"] == "reduce_qdii"
        assert abs(sim["after"]["qdii_weight"] - 0.3) < 1e-9

    def test_sector_concentrated_reduces_top_sector(self):
        positions = [_make_position("001", market_value=300, sector="半导体"),
                     _make_position("002", market_value=200, sector="半导体"),
                     _make_position("003", market_value=300, sector="消费"),
                     _make_position("004", market_value=200, fund_type="债券型")]
        report = _make_report(max_single_weight=0.3, equity_weight=0.8, bond_weight=0.2)
        a = _by_code(generate_advice(positions, report), "sector_concentrated")
        sim = a.simulation
        assert sim["rule"] == "reduce_sector"
        assert sim["params"]["sector"] == "半导体"
        assert abs(sim["before"]["top_sector_weight"] - 0.5) < 1e-9
        assert abs(sim["after"]["top_sector_weight"] - 0.48) < 1e-9

    def test_tech_heavy_reduces_to_threshold(self):
        positions = [_make_position("001", market_value=350, sector="半导体"),
                     _make_position("002", market_value=250, sector="算力"),
                     _make_position("003", market_value=250, sector="消费"),
                     _make_position("004", market_value=150, fund_type="债券型")]
        report = _make_report(max_single_weight=0.35, equity_weight=0.85, bond_weight=0.15)
        a = _by_code(generate_advice(positions, report), "tech_heavy")
        sim = a.simulation
        assert sim["rule"] == "reduce_tech"
        assert abs(sim["before"]["tech_weight"] - 0.6) < 1e-9
        assert abs(sim["after"]["tech_weight"] - 0.5) < 1e-9

    def test_single_position_unavailable(self):
        positions = [_make_position("001", market_value=1000)]
        report = _make_report(max_single_weight=0.95, max_single_name="Fund 001")
        a = _by_code(generate_advice(positions, report), "concentration_high")
        assert a.simulation is None

    def test_total_market_value_preserved(self):
        positions = [_make_position("001", market_value=900),
                     _make_position("002", market_value=100)]
        total = sum(p.market_value for p in positions)
        adjusted = _reduce_row_to_weight(positions, positions[0], 0.4, total)
        assert adjusted is not None
        assert abs(sum(p.market_value for p in adjusted) - total) < 1e-9
        assert abs(adjusted[0].market_value - 400) < 1e-9
        assert abs(adjusted[1].market_value - 600) < 1e-9
