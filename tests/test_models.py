"""Transaction 模型测试：normalize 补全 + is_valid 校验。"""
from zfundpilot.models import (
    ACTION_BUY,
    ACTION_DIVIDEND,
    ACTION_REINVEST,
    ACTION_SELL,
    Transaction,
)


class TestNormalize:
    def test_from_amount_and_shares(self):
        tx = Transaction(fund_code="001", action=ACTION_BUY, date="2025-01-01",
                         amount=1000, shares=500)
        tx.normalize()
        assert tx.nav == 2.0

    def test_from_amount_and_nav(self):
        tx = Transaction(fund_code="001", action=ACTION_BUY, date="2025-01-01",
                         amount=1000, nav=2.0)
        tx.normalize()
        assert tx.shares == 500.0

    def test_from_shares_and_nav(self):
        tx = Transaction(fund_code="001", action=ACTION_BUY, date="2025-01-01",
                         shares=500, nav=2.0)
        tx.normalize()
        assert tx.amount == 1000.0

    def test_all_three_given_not_overwritten(self):
        tx = Transaction(fund_code="001", action=ACTION_BUY, date="2025-01-01",
                         amount=1000, shares=500, nav=3.0)
        tx.normalize()
        assert tx.nav == 3.0
        assert tx.amount == 1000
        assert tx.shares == 500


class TestIsValid:
    def test_valid_buy(self):
        tx = Transaction(fund_code="001", action=ACTION_BUY, date="2025-01-01",
                         amount=1000, shares=500)
        assert tx.is_valid()

    def test_valid_sell(self):
        tx = Transaction(fund_code="001", action=ACTION_SELL, date="2025-01-01",
                         amount=600, shares=200)
        assert tx.is_valid()

    def test_invalid_action(self):
        tx = Transaction(fund_code="001", action="invalid", date="2025-01-01",
                         amount=1000, shares=500)
        assert not tx.is_valid()

    def test_missing_amount_and_shares(self):
        tx = Transaction(fund_code="001", action=ACTION_BUY, date="2025-01-01")
        assert not tx.is_valid()

    def test_valid_dividend(self):
        """分红只需金额。"""
        tx = Transaction(fund_code="001", action=ACTION_DIVIDEND, date="2025-01-01",
                         amount=50.0)
        assert tx.is_valid()

    def test_invalid_dividend_no_amount(self):
        tx = Transaction(fund_code="001", action=ACTION_DIVIDEND, date="2025-01-01",
                         shares=100)
        assert not tx.is_valid()

    def test_valid_reinvest_with_shares(self):
        """再投资只需份额。"""
        tx = Transaction(fund_code="001", action=ACTION_REINVEST, date="2025-01-01",
                         shares=34.48, nav=1.45)
        assert tx.is_valid()

    def test_valid_reinvest_with_amount(self):
        """再投资有金额也行。"""
        tx = Transaction(fund_code="001", action=ACTION_REINVEST, date="2025-01-01",
                         amount=50.0, nav=1.45)
        assert tx.is_valid()

    def test_invalid_reinvest_empty(self):
        tx = Transaction(fund_code="001", action=ACTION_REINVEST, date="2025-01-01")
        assert not tx.is_valid()

    def test_normalize_reinvest_shares_nav(self):
        """再投资：份额 + 净值 → 自动算金额。"""
        tx = Transaction(fund_code="001", action=ACTION_REINVEST, date="2025-01-01",
                         shares=34.48, nav=1.45)
        tx.normalize()
        assert abs(tx.amount - 50.0) < 0.01
