"""风险分析模块。

提供：
- 最大回撤（max drawdown）
- 年化波动率（volatility）
- 集中度（最大单基金占比、HHI）
- 结构占比（权益 / 债券 / QDII）
- 风险提示规则（generate_risk_flags）

所有指标基于已有数据计算，数据不足时安全降级为 None。
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from . import analysis, config, db
from .config import RiskThresholds as RT
from .models import Position


@dataclass
class RiskFlag:
    """一条风险提示。"""
    level: str      # info / warning / danger
    title: str
    detail: str


@dataclass
class RiskReport:
    """完整风险报告。"""
    max_drawdown: float | None = None
    volatility: float | None = None
    max_single_weight: float = 0.0
    max_single_name: str = ""
    hhi: float = 0.0                     # 赫芬达尔指数，衡量集中度
    equity_weight: float = 0.0
    bond_weight: float = 0.0
    qdii_weight: float = 0.0
    flags: list[RiskFlag] = None         # type: ignore[assignment]

    def __post_init__(self):
        if self.flags is None:
            self.flags = []


# ---------------------------------------------------------------------------
# 基础指标
# ---------------------------------------------------------------------------
def calculate_max_drawdown(values: pd.Series) -> float | None:
    """最大回撤，返回负数（-0.15 表示 -15%）。数据不足返回 None。"""
    if values is None or len(values) < 2:
        return None
    arr = values.astype(float).values
    running_max = np.maximum.accumulate(arr)
    # 避免除零
    with np.errstate(divide="ignore", invalid="ignore"):
        drawdowns = (arr - running_max) / running_max
    dd = float(np.nanmin(drawdowns))
    return dd


def calculate_volatility(values: pd.Series,
                         annualize: bool = True) -> float | None:
    """基于日收益率标准差的波动率。数据不足返回 None。"""
    if values is None or len(values) < 3:
        return None
    returns = values.astype(float).pct_change().dropna()
    if returns.empty:
        return None
    vol = float(returns.std())
    if annualize:
        vol *= np.sqrt(config.TRADING_DAYS_PER_YEAR)
    return vol


def calculate_concentration(positions: list[Position]) -> tuple[float, str, float]:
    """返回 (最大单基金占比, 该基金名称, HHI)。"""
    if not positions:
        return 0.0, "", 0.0
    top = max(positions, key=lambda p: p.weight)
    hhi = sum(p.weight ** 2 for p in positions)
    return top.weight, top.fund_name, hhi


def structure_weights(positions: list[Position]) -> tuple[float, float, float]:
    """返回 (权益类占比, 债券类占比, QDII占比)。"""
    if not positions:
        return 0.0, 0.0, 0.0
    total = sum(p.market_value for p in positions)
    if total <= 0:
        return 0.0, 0.0, 0.0

    equity = bond = qdii = 0.0
    for p in positions:
        w = p.market_value / total
        if p.fund_type in config.EQUITY_LIKE_TYPES:
            equity += w
        if p.fund_type == "债券型":
            bond += w
        if p.fund_type == "QDII":
            qdii += w
    return equity, bond, qdii


# ---------------------------------------------------------------------------
# 组合回撤/波动（基于组合收益曲线）
# ---------------------------------------------------------------------------
def portfolio_drawdown_and_vol() -> tuple[float | None, float | None]:
    curve = analysis.build_portfolio_curve()
    if curve.empty:
        return None, None
    values = curve.set_index("date")["total_value"]
    return calculate_max_drawdown(values), calculate_volatility(values)


# ---------------------------------------------------------------------------
# 风险提示规则
# ---------------------------------------------------------------------------
def generate_risk_flags(report: RiskReport) -> list[RiskFlag]:
    flags: list[RiskFlag] = []

    # 集中度
    if report.max_single_weight >= RT.SINGLE_FUND_HIGH:
        flags.append(RiskFlag(
            "danger", "单基金集中度过高",
            f"{report.max_single_name} 占比 {report.max_single_weight:.1%}，"
            f"超过 {RT.SINGLE_FUND_HIGH:.0%}，建议控制单一基金暴露。",
        ))
    elif report.max_single_weight >= RT.SINGLE_FUND_WARN:
        flags.append(RiskFlag(
            "warning", "单基金集中度偏高",
            f"{report.max_single_name} 占比 {report.max_single_weight:.1%}，"
            f"超过 {RT.SINGLE_FUND_WARN:.0%}。",
        ))

    # 权益占比
    if report.equity_weight >= RT.EQUITY_WARN:
        flags.append(RiskFlag(
            "warning", "权益/成长风格偏重",
            f"权益类资产占比 {report.equity_weight:.1%}，"
            f"超过 {RT.EQUITY_WARN:.0%}，组合波动可能较大。",
        ))

    # 债券占比
    if report.bond_weight < RT.BOND_MIN:
        flags.append(RiskFlag(
            "warning", "防守型资产偏低",
            f"债券型占比仅 {report.bond_weight:.1%}，"
            f"低于 {RT.BOND_MIN:.0%}，组合缺乏缓冲。",
        ))

    # QDII 占比
    if report.qdii_weight >= RT.QDII_WARN:
        flags.append(RiskFlag(
            "info", "海外暴露较高",
            f"QDII 占比 {report.qdii_weight:.1%}，"
            f"超过 {RT.QDII_WARN:.0%}，注意汇率与海外市场波动。",
        ))

    # 回撤
    if report.max_drawdown is not None and report.max_drawdown <= RT.DRAWDOWN_HIGH:
        flags.append(RiskFlag(
            "danger", "历史回撤较大",
            f"组合最大回撤 {report.max_drawdown:.1%}，"
            f"低于 {RT.DRAWDOWN_HIGH:.0%}，属高风险区间。",
        ))

    # 波动率
    if report.volatility is not None and report.volatility >= RT.VOLATILITY_HIGH:
        flags.append(RiskFlag(
            "info", "波动率偏高",
            f"组合年化波动率约 {report.volatility:.1%}，"
            f"超过 {RT.VOLATILITY_HIGH:.0%}。",
        ))

    if not flags:
        flags.append(RiskFlag("info", "暂无明显风险提示",
                              "当前组合各项风险指标处于设定阈值内。"))
    return flags


def build_risk_report(positions: list[Position] | None = None) -> RiskReport:
    """一站式生成风险报告。"""
    if positions is None:
        positions = analysis.calculate_positions()

    max_w, max_name, hhi = calculate_concentration(positions)
    equity, bond, qdii = structure_weights(positions)
    dd, vol = portfolio_drawdown_and_vol()

    report = RiskReport(
        max_drawdown=dd,
        volatility=vol,
        max_single_weight=max_w,
        max_single_name=max_name,
        hhi=hhi,
        equity_weight=equity,
        bond_weight=bond,
        qdii_weight=qdii,
    )
    report.flags = generate_risk_flags(report)
    return report


if __name__ == "__main__":
    db.init_db()
    rep = build_risk_report()
    print("最大单基金占比：", f"{rep.max_single_weight:.2%}")
    print("权益占比：", f"{rep.equity_weight:.2%}")
    print("债券占比：", f"{rep.bond_weight:.2%}")
    for f in rep.flags:
        print(f"[{f.level}] {f.title} - {f.detail}")
