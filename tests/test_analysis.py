"""持仓汇总测试：移动加权平均成本法、多渠道分离、已实现盈亏。"""
from datetime import datetime as _datetime
from zoneinfo import ZoneInfo

from zfundpilot.analysis import (
    _build_data_status,
    _build_positions_from_transactions,
    calculate_summary,
    clear_analysis_cache,
)
from zfundpilot.models import (
    ACTION_BUY,
    ACTION_DIVIDEND,
    ACTION_REINVEST,
    ACTION_SELL,
    Fund,
    Position,
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

    def test_risk_level_inherited_from_fund(self):
        """Position 从 Fund 表继承风险等级；无 Fund 记录时为空。"""
        txs = [
            Transaction(fund_code="001", action=ACTION_BUY, date="2025-01-01",
                        amount=1000, shares=500, nav=2.0),
            Transaction(fund_code="002", action=ACTION_BUY, date="2025-01-01",
                        amount=1000, shares=500, nav=2.0),
        ]
        funds = {"001": Fund(fund_code="001", fund_name="A", risk_level="中高风险")}
        positions = _build_positions_from_transactions(txs, funds)
        assert positions[("001", "")].risk_level == "中高风险"
        assert positions[("002", "")].risk_level == ""


# ---------------------------------------------------------------------------
# 组合数据状态摘要 _build_data_status
# ---------------------------------------------------------------------------
_SHANGHAI = ZoneInfo("Asia/Shanghai")


def _freeze_now(monkeypatch, y: int, m: int, d: int) -> None:
    """冻结 analysis.datetime.now() 返回固定时间（Asia/Shanghai）。"""
    fixed = _datetime(y, m, d, 12, 0, tzinfo=_SHANGHAI)

    class _FrozenDT(_datetime):
        @classmethod
        def now(cls, tz=None):  # type: ignore[override]
            return fixed

    monkeypatch.setattr("zfundpilot.analysis.datetime", _FrozenDT)


def _weekday_trading_day(holidays: set[str] | None = None):
    holidays = holidays or set()

    def _is_trading_day(date_str: str) -> bool:
        if date_str in holidays:
            return False
        return _datetime.strptime(date_str, "%Y-%m-%d").date().weekday() < 5

    return _is_trading_day


def _pos(code: str, *, held: float, latest_date: str | None, fund_type: str = "股票型") -> Position:
    return Position(
        fund_code=code, fund_name=code, fund_type=fund_type, sector="",
        held_shares=held, latest_date=latest_date, latest_nav=1.0 if latest_date else None,
    )


class TestBuildDataStatus:
    def test_no_positions(self, monkeypatch):
        _freeze_now(monkeypatch, 2026, 10, 30)  # Friday
        monkeypatch.setattr("zfundpilot.analysis.db.is_trading_day", _weekday_trading_day())
        monkeypatch.setattr("zfundpilot.analysis.db.get_transactions_without_nav", lambda: [])
        ds = _build_data_status([])
        assert ds.missing_nav_fund_count == 0
        assert ds.stale_nav_fund_count == 0
        assert ds.pending_t1_transaction_count == 0

    def test_up_to_date_not_flagged(self, monkeypatch):
        _freeze_now(monkeypatch, 2026, 10, 30)  # Friday → normal_ref = Thu 2026-10-29
        monkeypatch.setattr("zfundpilot.analysis.db.is_trading_day", _weekday_trading_day())
        monkeypatch.setattr("zfundpilot.analysis.db.get_transactions_without_nav", lambda: [])
        ds = _build_data_status([_pos("001", held=100, latest_date="2026-10-29")])
        assert ds.stale_nav_fund_count == 0
        assert ds.missing_nav_fund_count == 0

    def test_stale_when_older_than_reference(self, monkeypatch):
        _freeze_now(monkeypatch, 2026, 10, 30)  # normal_ref = 2026-10-29
        monkeypatch.setattr("zfundpilot.analysis.db.is_trading_day", _weekday_trading_day())
        monkeypatch.setattr("zfundpilot.analysis.db.get_transactions_without_nav", lambda: [])
        ds = _build_data_status([_pos("001", held=100, latest_date="2026-10-28")])
        assert ds.stale_nav_fund_count == 1
        assert ds.missing_nav_fund_count == 0

    def test_missing_when_no_nav(self, monkeypatch):
        _freeze_now(monkeypatch, 2026, 10, 30)
        monkeypatch.setattr("zfundpilot.analysis.db.is_trading_day", _weekday_trading_day())
        monkeypatch.setattr("zfundpilot.analysis.db.get_transactions_without_nav", lambda: [])
        ds = _build_data_status([_pos("001", held=100, latest_date=None)])
        assert ds.missing_nav_fund_count == 1
        assert ds.stale_nav_fund_count == 0  # missing 与 stale 互斥

    def test_dedup_same_fund_multi_channel(self, monkeypatch):
        _freeze_now(monkeypatch, 2026, 10, 30)  # normal_ref = 2026-10-29
        monkeypatch.setattr("zfundpilot.analysis.db.is_trading_day", _weekday_trading_day())
        monkeypatch.setattr("zfundpilot.analysis.db.get_transactions_without_nav", lambda: [])
        # 同一基金两个渠道：一个较新、一个较旧 → 取最大，只计 0 次 stale
        ds = _build_data_status([
            _pos("001", held=100, latest_date="2026-10-29"),
            _pos("001", held=100, latest_date="2026-10-28"),
        ])
        assert ds.stale_nav_fund_count == 0
        assert ds.missing_nav_fund_count == 0

    def test_closed_position_not_counted(self, monkeypatch):
        _freeze_now(monkeypatch, 2026, 10, 30)
        monkeypatch.setattr("zfundpilot.analysis.db.is_trading_day", _weekday_trading_day())
        monkeypatch.setattr("zfundpilot.analysis.db.get_transactions_without_nav", lambda: [])
        ds = _build_data_status([_pos("001", held=0, latest_date=None)])
        assert ds.missing_nav_fund_count == 0
        assert ds.stale_nav_fund_count == 0

    def test_pending_buy_only_not_in_nav_count(self, monkeypatch):
        """仅有待确认买入金额、无份额的基金不计入净值口径。"""
        _freeze_now(monkeypatch, 2026, 10, 30)
        monkeypatch.setattr("zfundpilot.analysis.db.is_trading_day", _weekday_trading_day())
        monkeypatch.setattr("zfundpilot.analysis.db.get_transactions_without_nav", lambda: [])
        ds = _build_data_status([_pos("001", held=0, latest_date=None)])
        assert ds.missing_nav_fund_count == 0

    def test_qdii_extra_tolerance(self, monkeypatch):
        _freeze_now(monkeypatch, 2026, 10, 30)
        # normal_ref = Thu 2026-10-29；qdii_ref = Wed 2026-10-28（再容忍一个交易日）
        monkeypatch.setattr("zfundpilot.analysis.db.is_trading_day", _weekday_trading_day())
        monkeypatch.setattr("zfundpilot.analysis.db.get_transactions_without_nav", lambda: [])

        def _qdii(d: str) -> Position:
            return _pos("001", held=100, latest_date=d, fund_type="QDII")

        # 2026-10-28 == qdii_ref → 不报
        assert _build_data_status([_qdii("2026-10-28")]).stale_nav_fund_count == 0
        # 2026-10-27 早于 qdii_ref → 报
        assert _build_data_status([_qdii("2026-10-27")]).stale_nav_fund_count == 1

    def test_weekend_not_stale(self, monkeypatch):
        _freeze_now(monkeypatch, 2026, 10, 31)  # Saturday → normal_ref = Fri 2026-10-30
        monkeypatch.setattr("zfundpilot.analysis.db.is_trading_day", _weekday_trading_day())
        monkeypatch.setattr("zfundpilot.analysis.db.get_transactions_without_nav", lambda: [])
        # 周五的净值在周六不应被判过期
        ds = _build_data_status([_pos("001", held=100, latest_date="2026-10-30")])
        assert ds.stale_nav_fund_count == 0

    def test_holiday_not_stale(self, monkeypatch):
        _freeze_now(monkeypatch, 2026, 10, 2)  # Friday 但为国庆假期
        holidays = {"2026-10-01", "2026-10-02"}
        monkeypatch.setattr("zfundpilot.analysis.db.is_trading_day", _weekday_trading_day(holidays))
        monkeypatch.setattr("zfundpilot.analysis.db.get_transactions_without_nav", lambda: [])
        # 假期前最近交易日为 2026-09-30
        ds = _build_data_status([_pos("001", held=100, latest_date="2026-09-30")])
        assert ds.stale_nav_fund_count == 0
        ds2 = _build_data_status([_pos("001", held=100, latest_date="2026-09-29")])
        assert ds2.stale_nav_fund_count == 1

    def test_calendar_unavailable_fail_open(self, monkeypatch):
        """日历不可用（is_trading_day 恒 False）时只报 missing，不报 stale。"""
        _freeze_now(monkeypatch, 2026, 10, 30)
        monkeypatch.setattr("zfundpilot.analysis.db.is_trading_day", lambda s: False)
        monkeypatch.setattr("zfundpilot.analysis.db.get_transactions_without_nav", lambda: [])
        ds = _build_data_status([_pos("001", held=100, latest_date="2026-10-29")])
        assert ds.stale_nav_fund_count == 0
        assert ds.missing_nav_fund_count == 0

    def test_pending_t1_count(self, monkeypatch):
        _freeze_now(monkeypatch, 2026, 10, 30)
        monkeypatch.setattr("zfundpilot.analysis.db.is_trading_day", _weekday_trading_day())
        without_nav = [
            Transaction(fund_code="001", action=ACTION_BUY, date="2026-10-29",
                        amount=1000, is_t1=True),
            Transaction(fund_code="002", action=ACTION_SELL, date="2026-10-29",
                        shares=100, is_t1=True),
            Transaction(fund_code="003", action=ACTION_BUY, date="2026-10-29",
                        amount=1000, is_t1=False),
            Transaction(fund_code="004", action=ACTION_DIVIDEND, date="2026-10-29",
                        amount=10.0, is_t1=True),
        ]
        monkeypatch.setattr("zfundpilot.analysis.db.get_transactions_without_nav", lambda: without_nav)
        ds = _build_data_status([])
        # 仅 T+1 买入 + T+1 卖出 = 2；非 T+1 与分红不计
        assert ds.pending_t1_transaction_count == 2

    def test_does_not_mutate_positions(self, monkeypatch):
        _freeze_now(monkeypatch, 2026, 10, 30)
        monkeypatch.setattr("zfundpilot.analysis.db.is_trading_day", _weekday_trading_day())
        monkeypatch.setattr("zfundpilot.analysis.db.get_transactions_without_nav", lambda: [])
        p = _pos("001", held=100, latest_date="2026-10-28")
        original_date = p.latest_date
        _build_data_status([p])
        assert p.latest_date == original_date

    def test_summary_cache_refreshes_after_clear(self, monkeypatch):
        """清空分析缓存后 calculate_summary 重新计算 data_status，未清则命中旧摘要。"""
        _freeze_now(monkeypatch, 2026, 10, 30)  # normal_ref = 2026-10-29
        monkeypatch.setattr("zfundpilot.analysis.db.is_trading_day", _weekday_trading_day())
        monkeypatch.setattr("zfundpilot.analysis.db.get_transactions_without_nav", lambda: [])
        # 隔离数据库依赖：流水、净值曲线都返回空
        monkeypatch.setattr("zfundpilot.analysis._get_transactions_cached", lambda: [])
        monkeypatch.setattr("zfundpilot.analysis.build_portfolio_curve", lambda: {"date": []})

        stale = [_pos("001", held=100, latest_date="2026-10-28")]
        fresh = [_pos("001", held=100, latest_date="2026-10-29")]
        monkeypatch.setattr("zfundpilot.analysis.calculate_positions",
                            lambda include_closed=True: stale)

        clear_analysis_cache()
        try:
            s1 = calculate_summary()
            assert s1.data_status.stale_nav_fund_count == 1

            # 数据源变化但缓存未清 → 仍返回旧摘要，证明命中缓存
            monkeypatch.setattr("zfundpilot.analysis.calculate_positions",
                                lambda include_closed=True: fresh)
            s2 = calculate_summary()
            assert s2.data_status.stale_nav_fund_count == 1

            # 清缓存后 → 重新计算，反映最新数据
            clear_analysis_cache()
            s3 = calculate_summary()
            assert s3.data_status.stale_nav_fund_count == 0
        finally:
            clear_analysis_cache()
