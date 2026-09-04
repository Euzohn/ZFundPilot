"""组合行业敞口聚合测试（基金穿透）。"""
from unittest.mock import patch

from zfundpilot.analysis import aggregate_industry_exposure
from zfundpilot.models import IndustryAllocation, IndustryAllocationResult, Position


def _pos(code, name, mv):
    return Position(
        fund_code=code, fund_name=name, fund_type="股票型", sector="权益",
        market_value=mv, held_shares=1, total_cost=mv, weight=0.5,
    )


def _alloc(code, rows):
    result = IndustryAllocationResult(fund_code=code, ok=True, message="成功", code="ok")
    result.allocations = [IndustryAllocation(industry=i, weight=w) for i, w in rows]
    return result


def _mock_fetch(allocations_map):
    def _side_effect(code):
        result = allocations_map.get(code)
        if result is None:
            return IndustryAllocationResult(fund_code=code, ok=False, message="no_data", code="no_data")
        return result

    return patch(
        "zfundpilot.fetch_fund.fetch_fund_industry_allocation",
        side_effect=_side_effect,
    )


def test_aggregate_multiple_funds():
    positions = [
        _pos("000001", "基金A", 100000),
        _pos("000002", "基金B", 50000),
    ]
    allocs = {
        "000001": _alloc("000001", [("制造业", 0.5), ("金融业", 0.3)]),
        "000002": _alloc("000002", [("制造业", 0.4), ("采矿业", 0.1)]),
    }
    with _mock_fetch(allocs):
        result = aggregate_industry_exposure(positions)

    assert result.ok
    assert result.total_market_value == 150000
    assert result.funds_count == 2
    assert result.funds_with_data == 2
    assert len(result.items) == 3

    items = {item.industry: item for item in result.items}
    # 制造业 = 100000*0.5 + 50000*0.4 = 70000
    assert items["制造业"].market_value == 70000
    assert items["制造业"].funds_count == 2
    assert items["制造业"].fund_codes == ["000001", "000002"]
    # 金融业 = 100000*0.3 = 30000
    assert items["金融业"].market_value == 30000
    assert items["金融业"].funds_count == 1
    # 采矿业 = 50000*0.1 = 5000
    assert items["采矿业"].market_value == 5000

    # 穿透 = 70000 + 30000 + 5000 = 105000；未穿透 = 150000 - 105000 = 45000
    assert result.penetrated_market_value == 105000
    assert result.unpenetrated_market_value == 45000
    # 权重 = 行业市值 / 组合总市值
    assert items["制造业"].weight == 70000 / 150000
    # 按市值降序
    assert [i.industry for i in result.items] == ["制造业", "金融业", "采矿业"]


def test_aggregate_fund_without_data_counts_unpenetrated():
    positions = [
        _pos("000001", "股票基金", 80000),
        _pos("000002", "债券基金", 20000),  # 无行业数据
    ]
    allocs = {
        "000001": _alloc("000001", [("制造业", 0.6)]),
    }
    with _mock_fetch(allocs):
        result = aggregate_industry_exposure(positions)

    assert result.ok
    assert result.funds_with_data == 1
    assert result.penetrated_market_value == 48000
    # 债券基金整个市值计入未穿透
    assert result.unpenetrated_market_value == 100000 - 48000
    assert len(result.items) == 1
    assert result.items[0].industry == "制造业"
    assert result.items[0].funds_count == 1


def test_aggregate_empty_portfolio():
    result = aggregate_industry_exposure([])
    assert not result.ok
    assert result.items == []
    assert result.total_market_value == 0


def test_aggregate_all_no_data():
    positions = [_pos("000001", "债券基金", 50000)]
    with _mock_fetch({}):
        result = aggregate_industry_exposure(positions)
    assert result.ok
    assert result.items == []
    assert result.funds_with_data == 0
    assert result.unpenetrated_market_value == 50000


def test_aggregate_latest_quarter():
    positions = [_pos("000001", "基金A", 100000)]
    allocs = {
        "000001": IndustryAllocationResult(
            fund_code="000001", ok=True, message="成功", code="ok",
            quarter="2025-06-30",
        ),
    }
    allocs["000001"].allocations = [IndustryAllocation(industry="制造业", weight=0.5)]
    with _mock_fetch(allocs):
        result = aggregate_industry_exposure(positions)
    assert result.quarter == "2025-06-30"


def test_aggregate_uses_calculate_positions_default():
    positions = [_pos("000001", "基金A", 100000)]
    allocs = {"000001": _alloc("000001", [("制造业", 0.5)])}
    with (
        patch("zfundpilot.analysis.calculate_positions", return_value=positions),
        _mock_fetch(allocs),
    ):
        result = aggregate_industry_exposure()
    assert result.ok
    assert result.items[0].market_value == 50000
