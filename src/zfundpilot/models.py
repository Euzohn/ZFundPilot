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
    id: int | None = None

    def normalize(self) -> Transaction:
        """根据已知字段补全 amount / shares / nav。就地修改并返回自身。"""
        a, s, n = self.amount, self.shares, self.nav
        if a and s and not n:
            self.nav = a / s if s else None
        elif a and n and not s:
            self.shares = a / n if n else None
        elif s and n and not a:
            self.amount = s * n
        # 三者都有则以给定值为准，不覆盖
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
        return cls(**{k: v for k, v in data.items() if k in known})


@dataclass
class Position:
    """由流水汇总出的持仓（单只基金 + 单渠道）。"""
    fund_code: str
    fund_name: str
    fund_type: str
    sector: str
    channel: str = ""                 # 购买渠道
    held_shares: float = 0.0          # 当前持有份额
    total_cost: float = 0.0           # 当前持仓成本（已扣卖出结转）
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
        """是否仍有持仓。"""
        return self.held_shares > 1e-6

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

    def to_dict(self) -> dict:
        return asdict(self)
