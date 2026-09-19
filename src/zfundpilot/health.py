"""组合体检模块。

提供四维评分（配置/风险/流动性/收益）+ 综合体检报告，
供页面 `/api/portfolio/health` 和 AI 上下文使用。
"""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass
from typing import Any

from . import analysis, fetch_macro
from .config import HealthThresholds as HT
from .models import PortfolioSummary, Position
from .rebalance import Advice, generate_advice
from .risk import RiskReport, build_risk_report

logger = logging.getLogger(__name__)


@dataclass
class HealthDimension:
    name: str               # allocation / risk / liquidity / return
    score: int              # 0-100
    status: str             # good / warning / danger
    metrics: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class HealthReport:
    overall_score: int
    overall_tier: str       # excellent / good / fair / attention / danger
    dimensions: list[HealthDimension]
    stable_weight: float
    volatile_weight: float
    risk_report: RiskReport
    advice: list[Advice]
    summary: PortfolioSummary

    def to_dict(self) -> dict[str, Any]:
        return {
            "overall_score": self.overall_score,
            "overall_tier": self.overall_tier,
            "dimensions": [d.to_dict() for d in self.dimensions],
            "stable_weight": self.stable_weight,
            "volatile_weight": self.volatile_weight,
            "risk_report": {
                "max_drawdown": self.risk_report.max_drawdown,
                "volatility": self.risk_report.volatility,
                "max_single_weight": self.risk_report.max_single_weight,
                "max_single_name": self.risk_report.max_single_name,
                "hhi": self.risk_report.hhi,
                "equity_weight": self.risk_report.equity_weight,
                "bond_weight": self.risk_report.bond_weight,
                "qdii_weight": self.risk_report.qdii_weight,
                "flags": [
                    {"level": f.level, "code": f.code, "params": f.params, "title": f.title, "detail": f.detail}
                    for f in self.risk_report.flags
                ],
            },
            "advice": [
                {"code": a.code, "params": a.params, "category": a.category, "text": a.text}
                for a in self.advice
            ],
            "summary": self.summary.to_dict(),
        }


# ---------------------------------------------------------------------------
# 流动性计算
# ---------------------------------------------------------------------------

def calculate_liquidity(positions: list[Position]) -> tuple[float, float]:
    """返回 (stable_weight, volatile_weight)。

    stable = 债券型（T+1~T+3，波动低，适合做流动性缓冲）
    volatile = 权益类 + 其他（T+3+，波动大，赎回时机敏感）
    """
    if not positions:
        return 0.0, 0.0
    total = sum(p.market_value for p in positions)
    if total <= 0:
        return 0.0, 0.0

    stable = volatile = 0.0
    for p in positions:
        w = p.market_value / total
        if p.fund_type == "债券型":
            stable += w
        else:
            volatile += w
    return stable, volatile


# ---------------------------------------------------------------------------
# 评分函数
# ---------------------------------------------------------------------------

def _tier(score: int) -> str:
    if score >= HT.TIER_EXCELLENT:
        return "excellent"
    if score >= HT.TIER_GOOD:
        return "good"
    if score >= HT.TIER_FAIR:
        return "fair"
    if score >= HT.TIER_ATTENTION:
        return "attention"
    return "danger"


def _status(score: int) -> str:
    if score >= 70:
        return "good"
    if score >= 40:
        return "warning"
    return "danger"


def _score_allocation(report: RiskReport, summary: PortfolioSummary) -> HealthDimension:
    score = 100
    if report.max_single_weight >= 0.40:
        score -= 30
    elif report.max_single_weight >= 0.20:
        score -= 15
    if report.equity_weight >= 0.80:
        score -= 20
    if report.bond_weight < 0.05:
        score -= 10
    score = max(0, min(100, score))

    return HealthDimension("allocation", score, _status(score), {
        "max_single_weight": report.max_single_weight,
        "max_single_name": report.max_single_name,
        "hhi": report.hhi,
        "equity_weight": report.equity_weight,
        "bond_weight": report.bond_weight,
        "qdii_weight": report.qdii_weight,
        "holding_count": summary.holding_count,
    })


def _score_risk(report: RiskReport) -> HealthDimension:
    if report.max_drawdown is None or report.volatility is None:
        return HealthDimension("risk", 70, "warning", {
            "max_drawdown": report.max_drawdown,
            "volatility": report.volatility,
        })

    score = 100
    dd = report.max_drawdown
    vol = report.volatility
    if dd <= -0.20:
        score -= 30
    elif dd <= -0.15:
        score -= 20
    if vol >= 0.30:
        score -= 20
    elif vol >= 0.25:
        score -= 10
    score = max(0, min(100, score))

    return HealthDimension("risk", score, _status(score), {
        "max_drawdown": dd,
        "volatility": vol,
    })


def _score_liquidity(stable_weight: float, holding_count: int,
                     max_single_weight: float) -> HealthDimension:
    score = 50
    if stable_weight >= HT.STABLE_WEIGHT_GOOD:
        score += 30
    elif stable_weight >= HT.STABLE_WEIGHT_OK:
        score += 15
    if stable_weight < HT.STABLE_WEIGHT_MIN:
        score -= 10
    if holding_count >= HT.DIVERSITY_COUNT:
        score += 10
    if max_single_weight >= 0.40:
        score -= 10
    score = max(0, min(100, score))

    return HealthDimension("liquidity", score, _status(score), {
        "stable_weight": stable_weight,
        "volatile_weight": 1.0 - stable_weight,
        "holding_count": holding_count,
        "max_single_weight": max_single_weight,
    })


def _score_return(summary: PortfolioSummary, cpi_total: float | None) -> HealthDimension:
    ar = summary.annualized_return
    if ar is None:
        return HealthDimension("return", 50, "warning", {
            "annualized_return": None,
            "total_return": summary.total_return,
            "real_return": None,
            "cpi_inflation": cpi_total,
        })

    score = 50
    if ar > 0:
        score += HT.RETURN_POSITIVE
    if cpi_total is not None and summary.total_return > cpi_total:
        score += HT.RETURN_BEAT_CPI
    if ar < 0:
        score += HT.RETURN_NEGATIVE
    if ar < HT.RETURN_DEEP_LOSS:
        score += HT.RETURN_NEGATIVE
    score = max(0, min(100, score))

    real_return = summary.total_return - (cpi_total if cpi_total is not None else 0)
    return HealthDimension("return", score, _status(score), {
        "annualized_return": ar,
        "total_return": summary.total_return,
        "real_return": real_return if cpi_total is not None else None,
        "cpi_inflation": cpi_total,
    })


# ---------------------------------------------------------------------------
# 综合报告
# ---------------------------------------------------------------------------

def build_health_report() -> HealthReport:
    """一站式生成组合体检报告。"""
    positions = analysis.calculate_positions()
    summary = analysis.calculate_summary(positions)
    risk_report = build_risk_report(positions)
    advice = generate_advice(positions, risk_report)
    stable_weight, volatile_weight = calculate_liquidity(positions)

    # 空组合：无持仓可诊断，直接返回危险评级
    if not positions or summary.total_value <= 0:
        dims = [
            HealthDimension("allocation", 0, "danger", {}),
            HealthDimension("risk", 0, "danger", {}),
            HealthDimension("liquidity", 0, "danger", {}),
            HealthDimension("return", 0, "danger", {}),
        ]
        return HealthReport(0, "danger", dims, stable_weight, volatile_weight,
                            risk_report, advice, summary)

    # CPI 通胀（可选，网络失败不影响主流程）
    cpi_total: float | None = None
    try:
        curve = analysis.build_portfolio_curve()
        if not curve.empty and len(curve) >= 2:
            start = str(curve["date"].iloc[0])
            end = str(curve["date"].iloc[-1])
            cpi_res = fetch_macro.fetch_macro_baseline("CPI", start, end)
            if cpi_res:
                hist, baseline = cpi_res
                if hist and baseline > 0:
                    cpi_total = (hist[-1]["close"] / baseline) - 1
    except Exception:
        logger.debug("CPI 获取失败，体检收益维度仅用年化收益率评分", exc_info=True)

    dims = [
        _score_allocation(risk_report, summary),
        _score_risk(risk_report),
        _score_liquidity(stable_weight, summary.holding_count, risk_report.max_single_weight),
        _score_return(summary, cpi_total),
    ]
    overall = sum(d.score for d in dims) // len(dims)

    return HealthReport(
        overall_score=overall,
        overall_tier=_tier(overall),
        dimensions=dims,
        stable_weight=stable_weight,
        volatile_weight=volatile_weight,
        risk_report=risk_report,
        advice=advice,
        summary=summary,
    )
