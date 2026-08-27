"""持仓对账测试：截图份额 vs 已记录份额，生成差额调整交易。"""
from unittest.mock import patch

from zfundpilot.analysis import reconcile_holdings
from zfundpilot.models import Position


def _pos(code, name, shares, channel="", latest_nav=1.5):
    return Position(
        fund_code=code, fund_name=name, fund_type="混合", sector="权益",
        channel=channel, held_shares=shares, total_cost=shares * 1.0,
        latest_nav=latest_nav,
    )


def _mock_positions(positions):
    return patch("zfundpilot.analysis.calculate_positions", return_value=positions)


class TestReconcile:
    def test_delta_buy(self):
        """截图份额 > 已记录 → 建议买入。"""
        with _mock_positions([_pos("001", "测试A", 100, "支付宝", 2.0)]):
            result = reconcile_holdings(
                [{"fund_code": "001", "shares": 130}], channel="支付宝")
        items = result["items"]
        assert len(items) == 1
        assert items[0]["status"] == "buy"
        assert items[0]["delta"] == 30.0
        tx = items[0]["suggested_tx"]
        assert tx["action"] == "buy"
        assert tx["shares"] == 30.0
        assert tx["nav"] == 2.0
        assert tx["amount"] == 60.0
        assert "截图对账" in tx["note"]

    def test_delta_sell(self):
        """截图份额 < 已记录 → 建议卖出。"""
        with _mock_positions([_pos("001", "测试A", 100, "支付宝", 2.0)]):
            result = reconcile_holdings(
                [{"fund_code": "001", "shares": 70}], channel="支付宝")
        assert result["items"][0]["status"] == "sell"
        assert result["items"][0]["delta"] == -30.0
        tx = result["items"][0]["suggested_tx"]
        assert tx["action"] == "sell"
        assert tx["shares"] == 30.0

    def test_equal_shares(self):
        """份额一致 → ok，无建议交易。"""
        with _mock_positions([_pos("001", "测试A", 100, "支付宝")]):
            result = reconcile_holdings(
                [{"fund_code": "001", "shares": 100}], channel="支付宝")
        assert result["items"][0]["status"] == "ok"
        assert result["items"][0]["suggested_tx"] is None

    def test_new_fund(self):
        """截图有、系统无 → 新增买入。"""
        with _mock_positions([]):
            result = reconcile_holdings(
                [{"fund_code": "009", "shares": 200, "market_value": 400}])
        item = result["items"][0]
        assert item["status"] == "new"
        tx = item["suggested_tx"]
        assert tx["action"] == "buy"
        assert tx["shares"] == 200
        # market_value/shares = 2.0
        assert tx["nav"] == 2.0
        assert tx["amount"] == 400.0

    def test_maybe_sold(self):
        """系统有、截图无 → 疑似清仓。"""
        with _mock_positions([_pos("001", "测试A", 100, "支付宝", 2.0)]):
            result = reconcile_holdings([], channel="支付宝")
        assert len(result["items"]) == 1
        item = result["items"][0]
        assert item["status"] == "maybe_sold"
        assert item["screenshot_shares"] == 0.0
        tx = item["suggested_tx"]
        assert tx["action"] == "sell"
        assert tx["shares"] == 100.0

    def test_channel_filter(self):
        """按渠道过滤，只对比该渠道持仓。理财通份额不在截图范围 → 不标 maybe_sold。"""
        with _mock_positions([
            _pos("001", "测试A", 100, "支付宝", 2.0),
            _pos("001", "测试A", 50, "理财通", 2.0),
        ]):
            result = reconcile_holdings(
                [{"fund_code": "001", "shares": 100}], channel="支付宝")
        # 支付宝 100 份匹配 → ok；理财通不在截图范围，不对比
        assert len(result["items"]) == 1
        assert result["items"][0]["status"] == "ok"

    def test_maybe_sold_same_channel(self):
        """同渠道有持仓但截图无 → maybe_sold。"""
        with _mock_positions([
            _pos("001", "测试A", 100, "支付宝", 2.0),
            _pos("002", "测试B", 50, "支付宝", 1.5),
        ]):
            result = reconcile_holdings(
                [{"fund_code": "001", "shares": 100}], channel="支付宝")
        # 002 在支付宝渠道但截图无 → maybe_sold
        assert len(result["items"]) == 2
        maybe = [it for it in result["items"] if it["status"] == "maybe_sold"]
        assert len(maybe) == 1
        assert maybe[0]["fund_code"] == "002"

    def test_new_fund_no_market_value(self):
        """新基金无 market_value → nav/amount 留空让用户填。"""
        with _mock_positions([]):
            result = reconcile_holdings(
                [{"fund_code": "009", "shares": 200}])
        item = result["items"][0]
        tx = item["suggested_tx"]
        assert tx["nav"] is None
        assert tx["amount"] is None
        assert tx["shares"] == 200

    def test_skip_invalid_screenshot_item(self):
        """截图项无 fund_code 或 shares → 跳过。"""
        with _mock_positions([]):
            result = reconcile_holdings([
                {"fund_code": "", "shares": 100},
                {"fund_code": "001", "shares": None},
                {"fund_code": "001", "shares": "abc"},
            ])
        assert len(result["items"]) == 0
