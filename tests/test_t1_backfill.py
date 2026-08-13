"""T+1 交易净值回填逻辑测试。

验证：
1. _is_t1_transaction 正确识别 T+1 标记
2. _t1_nav_date 返回次日日期
3. backfill_transaction_navs 对 T+1 交易使用次日净值
4. recalculate_t1_transactions 修复历史错误回填
5. 回填时自动拉取手续费（买入/卖出）
"""
from unittest.mock import MagicMock, patch

from zfundpilot.analysis import (
    _is_t1_transaction,
    _t1_nav_date,
    backfill_transaction_navs,
    recalculate_t1_transactions,
)
from zfundpilot.models import ACTION_BUY, ACTION_SELL, Transaction


def _zero_fee(*_args, **_kwargs):
    """返回 fee=0 的 mock，保持现有断言不变。"""
    return MagicMock(fee=0)


class TestT1Detection:
    def test_t1_detected_from_field(self):
        tx = Transaction(fund_code="001", action=ACTION_BUY, date="2025-01-01",
                         amount=1000, is_t1=True)
        assert _is_t1_transaction(tx) is True

    def test_t1_with_other_note(self):
        tx = Transaction(fund_code="001", action=ACTION_BUY, date="2025-01-01",
                         amount=1000, note="加仓", is_t1=True)
        assert _is_t1_transaction(tx) is True

    def test_non_t1_transaction(self):
        tx = Transaction(fund_code="001", action=ACTION_BUY, date="2025-01-01",
                         amount=1000, note="加仓", is_t1=False)
        assert _is_t1_transaction(tx) is False

    def test_default_not_t1(self):
        tx = Transaction(fund_code="001", action=ACTION_BUY, date="2025-01-01",
                         amount=1000, note="")
        assert _is_t1_transaction(tx) is False


class TestT1NavDate:
    def test_next_day(self):
        tx = Transaction(fund_code="001", action=ACTION_BUY, date="2025-01-15",
                         amount=1000, is_t1=True)
        assert _t1_nav_date(tx) == "2025-01-16"

    def test_month_boundary(self):
        tx = Transaction(fund_code="001", action=ACTION_BUY, date="2025-01-31",
                         amount=1000, is_t1=True)
        assert _t1_nav_date(tx) == "2025-02-01"

    def test_year_boundary(self):
        tx = Transaction(fund_code="001", action=ACTION_BUY, date="2025-12-31",
                         amount=1000, is_t1=True)
        assert _t1_nav_date(tx) == "2026-01-01"


class TestBackfillT1:
    """验证 backfill_transaction_navs 对 T+1 交易使用次日净值。"""

    def test_t1_buy_uses_next_day_nav(self):
        """T+1 买入应使用次日净值，而非当日。"""
        t1_tx = Transaction(
            id=1, fund_code="001", action=ACTION_BUY, date="2025-01-15",
            amount=1000, is_t1=True,
        )
        normal_tx = Transaction(
            id=2, fund_code="002", action=ACTION_BUY, date="2025-01-15",
            amount=1000, is_t1=False,
        )

        with patch("zfundpilot.analysis.db") as mock_db, \
             patch("zfundpilot.analysis.fetch_fund") as mock_ff:
            mock_db.get_transactions_without_nav.return_value = [t1_tx, normal_tx]
            mock_ff.calc_purchase_fee.side_effect = _zero_fee

            # T+1 交易：返回次日净值 1.5
            # 普通交易：返回当日净值 1.0
            def mock_nav_on_or_after(code, date):
                if date == "2025-01-16":  # T+1 查次日
                    return {"nav": 1.5}
                if date == "2025-01-15":  # 普通查当日
                    return {"nav": 1.0}
                return None
            mock_db.get_nav_on_or_after.side_effect = mock_nav_on_or_after
            mock_db.update_transaction = MagicMock()

            updated = backfill_transaction_navs()

            assert len(updated) == 2
            # T+1 交易用了次日净值 1.5
            assert t1_tx.nav == 1.5
            assert t1_tx.shares == round((1000 - 0) / 1.5, 2)  # 666.67
            # 普通交易用了当日净值 1.0
            assert normal_tx.nav == 1.0
            assert normal_tx.shares == round((1000 - 0) / 1.0, 2)  # 1000.0

    def test_non_t1_buy_uses_same_day_nav(self):
        """普通买入使用当日净值。"""
        tx = Transaction(
            id=1, fund_code="001", action=ACTION_BUY, date="2025-01-15",
            amount=1000, is_t1=False,
        )

        with patch("zfundpilot.analysis.db") as mock_db, \
             patch("zfundpilot.analysis.fetch_fund") as mock_ff:
            mock_db.get_transactions_without_nav.return_value = [tx]
            mock_db.get_nav_on_or_after.return_value = {"nav": 1.2}
            mock_db.update_transaction = MagicMock()
            mock_ff.calc_purchase_fee.side_effect = _zero_fee

            updated = backfill_transaction_navs()

            assert len(updated) == 1
            assert tx.nav == 1.2
            # 确认查的是当日 2025-01-15
            mock_db.get_nav_on_or_after.assert_called_with("001", "2025-01-15")

    def test_buy_backfill_fetches_purchase_fee(self):
        """回填买入时应自动拉取申购手续费。"""
        tx = Transaction(
            id=1, fund_code="001", action=ACTION_BUY, date="2025-01-15",
            amount=1000, is_t1=False,
        )

        with patch("zfundpilot.analysis.db") as mock_db, \
             patch("zfundpilot.analysis.fetch_fund") as mock_ff:
            mock_db.get_transactions_without_nav.return_value = [tx]
            mock_db.get_nav_on_or_after.return_value = {"nav": 1.5}
            mock_db.update_transaction = MagicMock()
            mock_ff.calc_purchase_fee.return_value = MagicMock(fee=5.0)

            updated = backfill_transaction_navs()

            assert len(updated) == 1
            assert updated[0]["fee"] == 5.0
            # shares = (amount - fee) / nav = (1000 - 5) / 1.5 = 663.33
            assert tx.shares == round((1000 - 5) / 1.5, 2)
            assert tx.fee == 5.0
            mock_ff.calc_purchase_fee.assert_called_once_with("001", 1000)

    def test_sell_backfill_fetches_redemption_fee(self):
        """回填卖出时应自动拉取赎回手续费。"""
        tx = Transaction(
            id=1, fund_code="001", action=ACTION_SELL, date="2025-01-15",
            shares=100, is_t1=False,
        )

        with patch("zfundpilot.analysis.db") as mock_db, \
             patch("zfundpilot.analysis.fetch_fund") as mock_ff:
            mock_db.get_transactions_without_nav.return_value = [tx]
            mock_db.get_nav_on_or_after.return_value = {"nav": 1.5}
            mock_db.update_transaction = MagicMock()
            mock_ff.calc_redemption_fee.return_value = MagicMock(fee=3.0)

            updated = backfill_transaction_navs()

            assert len(updated) == 1
            assert updated[0]["fee"] == 3.0
            # amount = shares * nav - fee = 100 * 1.5 - 3 = 147.0
            assert tx.amount == round(100 * 1.5 - 3, 2)
            assert tx.fee == 3.0
            mock_ff.calc_redemption_fee.assert_called_once_with("001", "2025-01-15", 100)

    def test_backfill_preserves_existing_fee(self):
        """已有手续费的交易不再重新拉取。"""
        tx = Transaction(
            id=1, fund_code="001", action=ACTION_BUY, date="2025-01-15",
            amount=1000, fee=12.0, is_t1=False,
        )

        with patch("zfundpilot.analysis.db") as mock_db, \
             patch("zfundpilot.analysis.fetch_fund") as mock_ff:
            mock_db.get_transactions_without_nav.return_value = [tx]
            mock_db.get_nav_on_or_after.return_value = {"nav": 1.5}
            mock_db.update_transaction = MagicMock()

            updated = backfill_transaction_navs()

            assert len(updated) == 1
            assert updated[0]["fee"] == 12.0
            # shares = (amount - fee) / nav = (1000 - 12) / 1.5 = 658.67
            assert tx.shares == round((1000 - 12) / 1.5, 2)
            mock_ff.calc_purchase_fee.assert_not_called()


class TestRecalculateT1:
    """验证 recalculate_t1_transactions 修复历史错误回填。"""

    def _make_row(self, tx_data):
        """构造模拟 sqlite3.Row 的 dict。"""
        return dict(tx_data)

    def test_fixes_wrong_nav_for_t1_buy(self):
        """T+1 买入被错误回填了当日净值，应修复为次日净值。"""
        # 当日净值 1.0，次日净值 1.5
        # 交易被错误回填了 nav=1.0（当日）
        row = self._make_row({
            "id": 1, "fund_code": "001", "action": "buy", "date": "2025-01-15",
            "amount": 1000, "shares": 1000.0, "nav": 1.0, "fee": 0,
            "channel": "", "note": "定投", "is_t1": 1,
        })

        with patch("zfundpilot.analysis.db") as mock_db, \
             patch("zfundpilot.analysis.fetch_fund") as mock_ff:
            mock_conn = MagicMock()
            mock_conn.execute.return_value.fetchall.return_value = [row]
            mock_db.get_connection.return_value.__enter__ = MagicMock(return_value=mock_conn)
            mock_db.get_connection.return_value.__exit__ = MagicMock(return_value=None)

            # 当日净值 = 1.0（与 tx.nav 匹配，确认是错误回填）
            mock_db.get_nav_on_date.return_value = {"nav": 1.0}
            # 次日净值 = 1.5（正确净值）
            mock_db.get_nav_on_or_after.return_value = {"nav": 1.5}
            mock_db.update_transaction = MagicMock()
            mock_ff.calc_purchase_fee.side_effect = _zero_fee

            fixed = recalculate_t1_transactions()

            assert len(fixed) == 1
            assert fixed[0]["tx_id"] == 1
            assert fixed[0]["fund_code"] == "001"
            assert fixed[0]["old_nav"] == 1.0
            assert fixed[0]["new_nav"] == 1.5
            assert fixed[0]["old_shares"] == 1000.0
            assert fixed[0]["new_shares"] == round((1000 - 0) / 1.5, 2)
            assert fixed[0]["old_fee"] == 0
            assert fixed[0]["new_fee"] == 0
            # 验证 update_transaction 被调用，且 nav 已改为 1.5
            call_args = mock_db.update_transaction.call_args
            updated_tx = call_args[0][0]
            assert updated_tx.nav == 1.5
            assert updated_tx.shares == round((1000 - 0) / 1.5, 2)  # 666.67

    def test_skips_already_correct_t1(self):
        """T+1 交易已使用次日净值，不应被修复。"""
        row = self._make_row({
            "id": 1, "fund_code": "001", "action": "buy", "date": "2025-01-15",
            "amount": 1000, "shares": 666.67, "nav": 1.5, "fee": 0,
            "channel": "", "note": "定投", "is_t1": 1,
        })

        with patch("zfundpilot.analysis.db") as mock_db, \
             patch("zfundpilot.analysis.fetch_fund") as mock_ff:
            mock_conn = MagicMock()
            mock_conn.execute.return_value.fetchall.return_value = [row]
            mock_db.get_connection.return_value.__enter__ = MagicMock(return_value=mock_conn)
            mock_db.get_connection.return_value.__exit__ = MagicMock(return_value=None)

            # 当日净值 = 1.0（与 tx.nav=1.5 不匹配，说明不是错误回填）
            mock_db.get_nav_on_date.return_value = {"nav": 1.0}
            mock_db.get_nav_on_or_after.return_value = {"nav": 1.5}
            mock_db.update_transaction = MagicMock()
            mock_ff.calc_purchase_fee.side_effect = _zero_fee

            fixed = recalculate_t1_transactions()

            assert len(fixed) == 0
            mock_db.update_transaction.assert_not_called()

    def test_skips_non_t1_transactions(self):
        """非 T+1 交易不应被修复。"""
        row = self._make_row({
            "id": 1, "fund_code": "001", "action": "buy", "date": "2025-01-15",
            "amount": 1000, "shares": 1000.0, "nav": 1.0, "fee": 0,
            "channel": "", "note": "普通买入", "is_t1": 0,
        })

        with patch("zfundpilot.analysis.db") as mock_db, \
             patch("zfundpilot.analysis.fetch_fund"):
            mock_conn = MagicMock()
            mock_conn.execute.return_value.fetchall.return_value = [row]
            mock_db.get_connection.return_value.__enter__ = MagicMock(return_value=mock_conn)
            mock_db.get_connection.return_value.__exit__ = MagicMock(return_value=None)

            fixed = recalculate_t1_transactions()

            assert len(fixed) == 0
            mock_db.update_transaction.assert_not_called()

    def test_skips_when_next_day_nav_same(self):
        """次日净值与当日相同时，无需修复。"""
        row = self._make_row({
            "id": 1, "fund_code": "001", "action": "buy", "date": "2025-01-15",
            "amount": 1000, "shares": 1000.0, "nav": 1.0, "fee": 0,
            "channel": "", "note": "定投", "is_t1": 1,
        })

        with patch("zfundpilot.analysis.db") as mock_db, \
             patch("zfundpilot.analysis.fetch_fund") as mock_ff:
            mock_conn = MagicMock()
            mock_conn.execute.return_value.fetchall.return_value = [row]
            mock_db.get_connection.return_value.__enter__ = MagicMock(return_value=mock_conn)
            mock_db.get_connection.return_value.__exit__ = MagicMock(return_value=None)

            # 当日净值 = 1.0（与 tx.nav 匹配）
            mock_db.get_nav_on_date.return_value = {"nav": 1.0}
            # 次日净值也是 1.0（相同，无需修复）
            mock_db.get_nav_on_or_after.return_value = {"nav": 1.0}
            mock_db.update_transaction = MagicMock()
            mock_ff.calc_purchase_fee.side_effect = _zero_fee

            fixed = recalculate_t1_transactions()

            assert len(fixed) == 0
            mock_db.update_transaction.assert_not_called()
