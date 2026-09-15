"""XIRR 年化收益率测试。

验证：
1. xirr 二分法已知值校验
2. 边界/错误输入
3. _build_xirr_cashflows 现金流构建（buy/sell/dividend/reinvest）
4. 已清仓持仓 XIRR（无终端值）
5. reinvest 现金中性
"""
from datetime import date

from zfundpilot.models import Transaction
from zfundpilot.returns import _build_xirr_cashflows, xirr


class TestXirrAlgorithm:
    """纯算法测试：已知现金流 → 期望收益率。"""

    def test_simple_one_year(self):
        cf = [(date(2024, 1, 1), -10000.0), (date(2025, 1, 1), 11000.0)]
        r = xirr(cf)
        assert r is not None
        assert abs(r - 0.10) < 0.001

    def test_multi_year(self):
        # 3 年翻倍 → ~26% 年化
        cf = [(date(2021, 1, 1), -10000.0), (date(2024, 1, 1), 20000.0)]
        r = xirr(cf)
        assert r is not None
        assert abs(r - 0.26) < 0.01

    def test_short_period_high_return(self):
        # 1 个月 10% → 年化约 214%，仍在二分法上限内
        cf = [(date(2024, 1, 1), -10000.0), (date(2024, 2, 1), 11000.0)]
        r = xirr(cf)
        assert r is not None
        assert r > 1.0  # > 100%

    def test_extreme_return_beyond_bounds(self):
        # 月化 50% → 年化 >1000%，超出二分法上限 [‑0.999, 10.0]，返回 None
        cf = [(date(2024, 1, 1), -10000.0), (date(2024, 2, 1), 15000.0)]
        assert xirr(cf) is None

    def test_loss(self):
        cf = [(date(2024, 1, 1), -10000.0), (date(2025, 1, 1), 8000.0)]
        r = xirr(cf)
        assert r is not None
        assert r < 0

    def test_all_negative(self):
        cf = [(date(2024, 1, 1), -10000.0), (date(2024, 6, 1), -5000.0)]
        assert xirr(cf) is None

    def test_all_positive(self):
        cf = [(date(2024, 1, 1), 10000.0), (date(2024, 6, 1), 5000.0)]
        assert xirr(cf) is None

    def test_single_cashflow(self):
        assert xirr([(date(2024, 1, 1), -10000.0)]) is None

    def test_empty(self):
        assert xirr([]) is None

    def test_break_even(self):
        cf = [(date(2024, 1, 1), -10000.0), (date(2025, 1, 1), 10000.0)]
        r = xirr(cf)
        assert r is not None
        assert abs(r) < 0.0001

    def test_multiple_inflows(self):
        cf = [
            (date(2024, 1, 1), -10000.0),
            (date(2024, 4, 1), 200.0),
            (date(2024, 7, 1), 300.0),
            (date(2025, 1, 1), 10500.0),
        ]
        r = xirr(cf)
        assert r is not None
        assert r > 0.05  # 略高于 5%（10000 投 + 200/300 分红 + 终值 10500）


class TestBuildCashflows:
    """_build_xirr_cashflows 现金流构建测试。"""

    @staticmethod
    def _tx(**kw) -> Transaction:
        defaults = {"fund_code": "001", "action": "buy", "date": "2024-01-05", "amount": 1000.0}
        defaults.update(kw)
        return Transaction(**defaults)

    def test_buy_is_negative(self):
        cfs = _build_xirr_cashflows([self._tx(action="buy", amount=1000.0)], terminal_value=0, terminal_date=date(2025, 1, 1))
        # buy 流出存在，终端值=0 时不追加终端现金流
        assert cfs == [(date(2024, 1, 5), -1000.0)]

    def test_buy_with_terminal(self):
        cfs = _build_xirr_cashflows(
            [self._tx(action="buy", amount=10000.0)],
            terminal_value=12000.0,
            terminal_date=date(2025, 1, 1),
        )
        assert (date(2024, 1, 5), -10000.0) in cfs
        assert (date(2025, 1, 1), 12000.0) in cfs
        assert len(cfs) == 2

    def test_sell_is_positive(self):
        cfs = _build_xirr_cashflows(
            [self._tx(action="sell", amount=5000.0)],
            terminal_value=0,
            terminal_date=date(2025, 1, 1),
        )
        assert (date(2024, 1, 5), 5000.0) in cfs

    def test_dividend_is_positive(self):
        cfs = _build_xirr_cashflows(
            [self._tx(action="dividend", amount=100.0)],
            terminal_value=0,
            terminal_date=date(2025, 1, 1),
        )
        assert (date(2024, 1, 5), 100.0) in cfs

    def test_reinvest_is_skipped(self):
        cfs = _build_xirr_cashflows(
            [self._tx(action="reinvest", amount=100.0)],
            terminal_value=5000.0,
            terminal_date=date(2025, 1, 1),
        )
        # reinvest 跳过，仅剩终端值
        assert cfs == [(date(2025, 1, 1), 5000.0)]

    def test_terminal_not_added_when_zero(self):
        cfs = _build_xirr_cashflows(
            [self._tx(action="buy", amount=10000.0), self._tx(action="sell", amount=11000.0)],
            terminal_value=0,
            terminal_date=date(2025, 1, 1),
        )
        assert len(cfs) == 2
        assert (date(2024, 1, 5), -10000.0) in cfs
        assert (date(2024, 1, 5), 11000.0) in cfs

    def test_no_amount_skipped(self):
        cfs = _build_xirr_cashflows(
            [self._tx(action="buy", amount=None)],
            terminal_value=1000.0,
            terminal_date=date(2025, 1, 1),
        )
        assert cfs == [(date(2025, 1, 1), 1000.0)]

    def test_mixed_transactions(self):
        txs = [
            self._tx(action="buy", amount=10000.0),
            self._tx(action="dividend", amount=200.0),
            self._tx(action="reinvest", amount=200.0),
            self._tx(action="sell", amount=3000.0),
        ]
        cfs = _build_xirr_cashflows(txs, terminal_value=8000.0, terminal_date=date(2025, 1, 1))
        amounts_by_date = sorted((d.isoformat(), a) for d, a in cfs)
        assert amounts_by_date == [
            ("2024-01-05", -10000.0),
            ("2024-01-05", 200.0),
            ("2024-01-05", 3000.0),
            ("2025-01-01", 8000.0),
        ]


class TestClosedPositionXirr:
    """已清仓持仓 XIRR：所有卖出即终端，不加 terminal_value。"""

    def test_closed_position_xirr(self):
        txs = [
            Transaction(fund_code="001", action="buy", date="2024-01-01", amount=10000.0, nav=1.0),
            Transaction(fund_code="001", action="sell", date="2025-01-01", amount=11000.0, nav=1.1),
        ]
        cfs = _build_xirr_cashflows(txs, terminal_value=0, terminal_date=date(2025, 1, 1))
        r = xirr(cfs)
        assert r is not None
        assert abs(r - 0.10) < 0.001
