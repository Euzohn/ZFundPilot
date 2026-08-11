"""数据结构定义。

核心模型（交易流水驱动）：
- Fund         基金基础信息（代码/名称/类型/板块），一只基金一条
- Transaction  一笔买入或卖出流水
- Position     由流水汇总计算出的当前持仓（含已实现/未实现收益）
- PortfolioSummary  组合层面的汇总

金额单位为元，占比/收益率为小数（0.15 表示 15%）。
持仓成本采用「移动加权平均成本法」：卖出时按当前均价结转成本，
差额计入已实现收益，剩余份额继续持有。
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

# 交易方向
ACTION_BUY = "buy"
ACTION_SELL = "sell"
ACTION_DIVIDEND = "dividend"        # 现金分红
ACTION_REINVEST = "reinvest"        # 红利再投资
ACTIONS = (ACTION_BUY, ACTION_SELL, ACTION_DIVIDEND, ACTION_REINVEST)
ACTION_LABELS = {
    ACTION_BUY: "买入",
    ACTION_SELL: "卖出",
    ACTION_DIVIDEND: "分红",
    ACTION_REINVEST: "再投资",
}


@dataclass
class Fund:
    """基金基础信息。"""
    fund_code: str
    fund_name: str = ""
    fund_type: str = "其它"
    sector: str = ""
    tracking_index: str = ""
    dividend_method: str = "cash"  # 'cash'（现金分红）/ 'reinvest'（红利再投资）

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_row(cls, row) -> Fund:
        data = dict(row)
        known = {f for f in cls.__dataclass_fields__}  # type: ignore[attr-defined]
        return cls(**{k: v for k, v in data.items() if k in known})


@dataclass
class NavPoint:
    """一条基金净值记录。"""
    fund_code: str
    date: str            # YYYY-MM-DD
    nav: float           # 单位净值
    accumulated_nav: float | None = None
    source: str = "akshare"


@dataclass
class Transaction:
    """一笔买入/卖出流水。

    amount 金额、shares 份额、nav 成交净值三者中给出任意两个即可，
    normalize() 会自动补全第三个。fee 为手续费（可选）。
    channel 为购买渠道（支付宝/理财通等），同一基金不同渠道分开计算持仓。
    """
    fund_code: str
    action: str                       # buy / sell
    date: str                         # YYYY-MM-DD
    amount: float | None = None    # 成交金额（正数）
    shares: float | None = None    # 成交份额（正数）
    nav: float | None = None       # 成交净值
    fee: float = 0.0                  # 手续费
    channel: str = ""                 # 购买渠道
    note: str = ""
    is_t1: bool = False              # T+1 确认（15:00 后下单，按次日净值确认）
    id: int | None = None

    def normalize(self) -> Transaction:
        """根据已知字段补全 amount / shares / nav，按 action 类型处理手续费。

        买入：amount = shares × nav + fee（用户付份额价值 + 手续费）
        卖出：amount = shares × nav - fee（用户收份额价值 - 手续费）
        分红/再投资：无手续费
        三者都有时不覆盖。
        """
        a, s, n = self.amount, self.shares, self.nav
        fee = self.fee or 0.0
        if self.action == ACTION_BUY:
            if a and s and not n:
                self.nav = round((a - fee) / s, 4) if s else None
            elif a and n and not s:
                self.shares = round((a - fee) / n, 2) if n else None
            elif s and n and not a:
                self.amount = round(s * n + fee, 2)
        elif self.action == ACTION_SELL:
            if a and s and not n:
                self.nav = round((a + fee) / s, 4) if s else None
            elif a and n and not s:
                self.shares = round((a + fee) / n, 2) if n else None
            elif s and n and not a:
                self.amount = round(s * n - fee, 2)
        else:
            # dividend / reinvest：无手续费
            if a and s and not n:
                self.nav = round(a / s, 4) if s else None
            elif a and n and not s:
                self.shares = round(a / n, 2) if n else None
            elif s and n and not a:
                self.amount = round(s * n, 2)
        return self

    def is_valid(self) -> bool:
        """校验：方向合法，买入/再投资至少有金额或份额，卖出至少有份额，分红至少有金额。"""
        if self.action not in ACTIONS:
            return False
        if self.action == ACTION_DIVIDEND:
            return bool(self.amount)
        if self.action == ACTION_SELL:
            return bool(self.shares)
        # buy / reinvest：有金额或份额即可（净值可能尚未公布）
        return bool(self.amount or self.shares)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_row(cls, row) -> Transaction:
        data = dict(row)
        known = {f for f in cls.__dataclass_fields__}  # type: ignore[attr-defined]
        kwargs = {k: v for k, v in data.items() if k in known}
        if "is_t1" in kwargs:
            kwargs["is_t1"] = bool(kwargs["is_t1"])
        return cls(**kwargs)


@dataclass
class Position:
    """由流水汇总出的持仓（单只基金 + 单渠道）。"""
    fund_code: str
    fund_name: str
    fund_type: str
    sector: str
    channel: str = ""                 # 购买渠道
    tracking_index: str = ""           # 跟踪指数关键词（指数型基金用于实时估值）
    held_shares: float = 0.0          # 当前持有份额
    total_cost: float = 0.0           # 当前持仓成本（已扣卖出结转）
    pending_buy_cost: float = 0.0     # 待确认买入金额（份额未确认，不参与市值/盈亏计算，仅用于 is_open 判断）
    avg_cost_nav: float | None = None  # 持仓均价
    latest_nav: float | None = None
    latest_date: str | None = None
    market_value: float = 0.0         # 当前市值
    unrealized_pnl: float = 0.0       # 浮动盈亏
    realized_pnl: float = 0.0         # 已实现盈亏（历次卖出累计）
    return_rate: float | None = None   # 浮动收益率
    weight: float = 0.0               # 当前市值占组合比例
    buy_count: int = 0
    sell_count: int = 0
    dividend_count: int = 0           # 分红/再投资次数
    dividend_total: float = 0.0       # 累计分红金额（含再投资）

    @property
    def total_pnl(self) -> float:
        """总盈亏 = 浮动 + 已实现。"""
        return self.unrealized_pnl + self.realized_pnl

    @property
    def is_open(self) -> bool:
        """是否仍有持仓（含待确认：有成本或待确认金额但份额未知）。"""
        return (self.held_shares > 1e-6
                or self.total_cost > 1e-6
                or self.pending_buy_cost > 1e-6)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["total_pnl"] = self.total_pnl
        d["is_open"] = self.is_open
        return d


@dataclass
class PortfolioSummary:
    """组合层面的汇总结果。"""
    total_cost: float = 0.0           # 当前持仓成本
    total_value: float = 0.0          # 当前市值
    unrealized_pnl: float = 0.0       # 浮动盈亏
    realized_pnl: float = 0.0         # 已实现盈亏
    total_pnl: float = 0.0            # 总盈亏
    total_return: float = 0.0         # 浮动收益率（市值/成本-1）
    total_buy: float = 0.0            # 累计买入金额
    total_sell: float = 0.0           # 累计卖出金额
    total_dividend: float = 0.0       # 累计分红金额（含再投资）
    holding_count: int = 0            # 当前持仓基金数
    max_single_weight: float = 0.0
    max_single_name: str = ""
    as_of_date: str | None = None
    daily_pnl: float = 0.0          # 今日收益金额
    daily_return: float = 0.0       # 今日收益率
    week_pnl: float = 0.0           # 本周收益
    week_return: float = 0.0        # 本周收益率
    month_pnl: float = 0.0          # 本月收益
    month_return: float = 0.0       # 本月收益率
    year_pnl: float = 0.0           # 今年收益
    year_return: float = 0.0        # 今年收益率

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class BacktestResult:
    """定投/一次性投入回测结果（单只基金 × 单策略）。

    strategy: "dca"（定投）或 "lumpsum"（一次性投入）
    curve: [{date, invested, value, return}, ...] 每日数据点
    periods_detail: 每期买入明细（仅 dca 有，lumpsum 为空）
    """
    fund_code: str
    fund_name: str
    strategy: str                    # "dca" / "lumpsum"
    period_start: str
    period_end: str
    cadence: str = ""                # "month" / "biweek" / "week"（lumpsum 为空）
    amount_per_period: float = 0.0
    total_periods: int = 0
    invested_capital: float = 0.0    # 总投入金额（含手续费）
    total_fees: float = 0.0          # 总手续费（申购 + 赎回）
    final_value: float = 0.0         # 期末市值（未扣赎回费）
    redemption_fee: float = 0.0       # 期末赎回费
    net_final_value: float = 0.0     # 实际到手 = final_value - redemption_fee
    total_return: float = 0.0        # (net_final_value - invested_capital) / invested_capital
    annualized_return: float | None = None   # XIRR 年化
    max_drawdown: float | None = None
    sharpe_ratio: float | None = None
    curve: list[dict] = None          # type: ignore[assignment]
    periods_detail: list[dict] = None  # type: ignore[assignment]

    def __post_init__(self):
        if self.curve is None:
            self.curve = []
        if self.periods_detail is None:
            self.periods_detail = []

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Holding:
    """基金重仓股（单只）。"""
    stock_code: str
    stock_name: str = ""
    weight: float = 0.0           # 占净值比例（小数，0.05 = 5%）
    shares: float = 0.0           # 持股数（万股）
    market_value: float = 0.0     # 持仓市值（万元）
    quarter: str = ""             # 报告期，如 "2026-Q2"


@dataclass
class FundHoldingsResult:
    """基金持仓查询结果（重仓股 + 资产配置）。"""
    fund_code: str
    ok: bool = False
    message: str = ""
    code: str = ""
    holdings: list[Holding] = None        # type: ignore[assignment]
    stock_ratio: float = 0.0              # 股票占净值比
    bond_ratio: float = 0.0               # 债券占净值比
    cash_ratio: float = 0.0               # 现金占净值比
    other_ratio: float = 0.0              # 其他占净值比
    quarter: str = ""                     # 报告期

    def __post_init__(self):
        if self.holdings is None:
            self.holdings = []

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class RankingPoint:
    """一条同类排名数据（排名百分位，越低越好）。"""
    date: str            # YYYY-MM-DD
    percentile: float    # 排名百分位（0-100，12.5 = 前 12.5%）


@dataclass
class FundRankingResult:
    """基金同类排名走势查询结果。"""
    fund_code: str
    ok: bool = False
    message: str = ""
    code: str = ""
    points: list[RankingPoint] = None    # type: ignore[assignment]

    def __post_init__(self):
        if self.points is None:
            self.points = []

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class FundProfile:
    """基金档案信息（经理 / 规模 / 费率）。"""
    fund_code: str
    ok: bool = False
    message: str = ""
    code: str = ""
    manager: str = ""
    manager_career_days: int | None = None   # 基金经理累计从业天数
    scale: float | None = None               # 现任基金资产总规模（亿元）
    tenure_return: float | None = None       # 基金经理任期收益（%）
    management_fee: float | None = None      # 管理费（年化）
    custodian_fee: float | None = None       # 托管费（年化）
    sales_fee: float | None = None           # 销售服务费（年化）
    risk_level: str = ""                     # 风险等级（低风险/中低风险/中风险/中高风险/高风险）

    def to_dict(self) -> dict:
        return asdict(self)
