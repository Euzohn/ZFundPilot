"""持仓汇总测试：移动加权平均成本法、多渠道分离、已实现盈亏。"""
from zfundpilot.analysis import _build_positions_from_transactions
from zfundpilot.models import (
    ACTION_BUY,
    ACTION_DIVIDEND,
    ACTION_REINVEST,
    ACTION_SELL,
    Fund,
    Transaction,
)


class TestBuildPositions:
    def test_single_buy(self):
        txs = [Transaction(fund_code="001", action=ACTION_BUY, date="2025-01-01",
                           amount=1000, shares=500, nav=2.0)]
        funds = {"001": Fund(fund_code="001", fund_name="Test")}
        positions = _build_positions_from_transactions(txs, funds)
        assert len(positions) == 1
        pos = list(positions.values())[0]
        assert pos.held_shares == 500
        assert pos.total_cost == 1000
        assert pos.buy_count == 1
        assert pos.avg_cost_nav == 2.0

    def test_buy_then_sell_realized_pnl(self):
        """买入 500 份 @2.0，卖出 200 份 @3.0 → 已实现盈亏 200。"""
        txs = [
            Transaction(fund_code="001", action=ACTION_BUY, date="2025-01-01",
                        amount=1000, shares=500, nav=2.0),
            Transaction(fund_code="001", action=ACTION_SELL, date="2025-02-01",
                        amount=600, shares=200, nav=3.0),
        ]
        funds = {"001": Fund(fund_code="001", fund_name="Test")}
        positions = _build_positions_from_transactions(txs, funds)
        pos = list(positions.values())[0]
        assert pos.held_shares == 300
        assert pos.total_cost == 600      # 1000 - 200*2.0
        assert pos.realized_pnl == 200    # 600 - 200*2.0
        assert pos.sell_count == 1

    def test_different_channels_separate_positions(self):
        txs = [
            Transaction(fund_code="001", action=ACTION_BUY, date="2025-01-01",
                        amount=1000, shares=500, nav=2.0, channel="支付宝"),
            Transaction(fund_code="001", action=ACTION_BUY, date="2025-01-01",
                        amount=2000, shares=1000, nav=2.0, channel="理财通"),
        ]
        funds = {"001": Fund(fund_code="001", fund_name="Test")}
        positions = _build_positions_from_transactions(txs, funds)
        assert len(positions) == 2

    def test_full_sell_closes_position(self):
        txs = [
            Transaction(fund_code="001", action=ACTION_BUY, date="2025-01-01",
                        amount=1000, shares=500, nav=2.0),
            Transaction(fund_code="001", action=ACTION_SELL, date="2025-02-01",
                        amount=1100, shares=500, nav=2.2),
        ]
        funds = {"001": Fund(fund_code="001", fund_name="Test")}
        positions = _build_positions_from_transactions(txs, funds)
        pos = list(positions.values())[0]
        assert pos.held_shares == 0
        assert pos.total_cost == 0
        assert pos.realized_pnl == 100  # 1100 - 500*2.0
        assert not pos.is_open

    def test_avg_cost_after_partial_sell(self):
        """买入 1000 份 @1.0，再买入 500 份 @2.0 → 均价 1.333..."""
        txs = [
            Transaction(fund_code="001", action=ACTION_BUY, date="2025-01-01",
                        amount=1000, shares=1000, nav=1.0),
            Transaction(fund_code="001", action=ACTION_BUY, date="2025-02-01",
                        amount=1000, shares=500, nav=2.0),
        ]
        funds = {"001": Fund(fund_code="001", fund_name="Test")}
        positions = _build_positions_from_transactions(txs, funds)
        pos = list(positions.values())[0]
        assert pos.held_shares == 1500
        assert pos.total_cost == 2000
        assert abs(pos.avg_cost_nav - 2000 / 1500) < 1e-9

    def test_cash_dividend(self):
        """现金分红：计入已实现收益，份额和成本不变。"""
        txs = [
            Transaction(fund_code="001", action=ACTION_BUY, date="2025-01-01",
                        amount=1000, shares=1000, nav=1.0),
            Transaction(fund_code="001", action=ACTION_DIVIDEND, date="2025-03-01",
                        amount=50.0),
        ]
        funds = {"001": Fund(fund_code="001", fund_name="Test")}
        positions = _build_positions_from_transactions(txs, funds)
        pos = list(positions.values())[0]
        assert pos.held_shares == 1000       # 份额不变
        assert pos.total_cost == 1000        # 成本不变
        assert pos.realized_pnl == 50.0      # 分红计入已实现
        assert pos.dividend_count == 1
        assert pos.dividend_total == 50.0

    def test_reinvest(self):
        """红利再投资：份额+成本+已实现同时增加，总盈亏不变。"""
        txs = [
            Transaction(fund_code="001", action=ACTION_BUY, date="2025-01-01",
                        amount=1000, shares=1000, nav=1.0),
            Transaction(fund_code="001", action=ACTION_REINVEST, date="2025-03-01",
                        amount=50.0, shares=50.0, nav=1.0),
        ]
        funds = {"001": Fund(fund_code="001", fund_name="Test")}
        positions = _build_positions_from_transactions(txs, funds)
        pos = list(positions.values())[0]
        assert pos.held_shares == 1050       # 份额增加
        assert pos.total_cost == 1050        # 成本增加
        assert pos.realized_pnl == 50.0      # 分红计入已实现
        assert pos.dividend_count == 1
        assert pos.dividend_total == 50.0
        # 总盈亏 = 浮动(0) + 已实现(50) = 50
        # （当前无净值，market_value 用成本兜底，浮动=0）
        assert pos.total_pnl == 50.0

    def test_dividend_then_sell(self):
        """分红后卖出：已实现收益 = 分红 + 卖出差价。"""
        txs = [
            Transaction(fund_code="001", action=ACTION_BUY, date="2025-01-01",
                        amount=1000, shares=1000, nav=1.0),
            Transaction(fund_code="001", action=ACTION_DIVIDEND, date="2025-03-01",
                        amount=50.0),
            Transaction(fund_code="001", action=ACTION_SELL, date="2025-04-01",
                        amount=600, shares=500, nav=1.2),
        ]
        funds = {"001": Fund(fund_code="001", fund_name="Test")}
        positions = _build_positions_from_transactions(txs, funds)
        pos = list(positions.values())[0]
        # 已实现 = 分红50 + 卖出(600-500*1.0=100) = 150
        assert pos.realized_pnl == 150.0
        assert pos.held_shares == 500
        assert pos.total_cost == 500
