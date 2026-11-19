"""再平衡建议模块（可解释行动清单）。

⚠️ 重要：本模块只产出「结构优化建议」，不产出任何买入/卖出交易指令。
所有措辞聚焦于组合结构、风格暴露与占比，帮助用户做长期结构判断。

P3 Phase 1：每条建议在原有 code/params/category/text 之外附加四段可解释结构
（evidence 依据 / positions 涉及持仓 / simulation 模拟调整前后 / risks 风险限制），
全部为稳定 code + params（i18n 由前端映射，后端不直出自由文本）。
simulation 是 what-if 假设演算（纯函数、不落库、不写交易），不是操作指令。
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field, replace
from types import SimpleNamespace
from typing import Any

from . import analysis, config
from .config import RiskThresholds as RT
from .models import DataStatus, Position
from .risk import (
    RiskReport,
    build_risk_report,
    calculate_concentration,
    structure_weights,
)

# 科技/成长相关板块关键词（与 generate_advice 的 tech_heavy 判定共用）
TECH_SECTOR_KEYS = ["CPO", "半导体", "算力", "人工智能", "AI", "PCB",
                    "通信", "大科技", "科技", "机器人"]
# 板块集中 / 科技偏重的触发阈值（advice 与 simulation 目标共用，保持口径一致）
SECTOR_CONCENTRATION_THRESHOLD = 0.20
TECH_HEAVY_THRESHOLD = 0.50
# 涉及持仓列表上限（避免 UI/响应过长）
_INVOLVED_CAP = 8


@dataclass
class Advice:
    """一条结构建议（行动清单条目）。

    旧四字段（code/params/category/text）保持不变，向后兼容；
    新四段默认空，由 generate_advice 统一填充。
    """
    code: str                  # stable machine code for i18n
    params: dict[str, Any]     # dynamic values for interpolation
    category: str              # Chinese category (backward compat)
    text: str                  # Chinese display text (backward compat)
    evidence: list[dict[str, Any]] = field(default_factory=list)
    positions: list[dict[str, Any]] = field(default_factory=list)
    simulation: dict[str, Any] | None = None
    risks: list[dict[str, Any]] = field(default_factory=list)


def _sector_distribution(positions: list[Position]):
    df = analysis.distribution_by(positions, "sector")
    return df


def _is_tech_sector(sector: str) -> bool:
    return any(k in (sector or "") for k in TECH_SECTOR_KEYS)


def _is_equity(p: Position) -> bool:
    return p.fund_type in config.EQUITY_LIKE_TYPES


def _is_bond(p: Position) -> bool:
    return p.fund_type == "债券型"


def _is_qdii(p: Position) -> bool:
    return p.fund_type == "QDII"


def generate_advice(
    positions: list[Position] | None = None,
    report: RiskReport | None = None,
    data_status: DataStatus | None = None,
) -> list[Advice]:
    """基于持仓结构与风险报告生成结构优化建议列表（含四段可解释结构）。

    data_status 可选：传入时 risks 段会追加数据延迟/缺失 caveat（口径复用
    analysis._build_data_status，不在此重复计算）。
    """
    if positions is None:
        positions = analysis.calculate_positions()
    if report is None:
        report = build_risk_report(positions)

    advice: list[Advice] = []

    if not positions:
        return [Advice("no_holding", {}, "提示", "当前没有持仓数据，先添加基金后再查看结构建议。")]

    # 1) 单基金集中度
    if report.max_single_weight >= RT.SINGLE_FUND_HIGH:
        advice.append(Advice(
            "concentration_high",
            {"name": report.max_single_name, "weight": report.max_single_weight,
             "threshold": RT.SINGLE_FUND_HIGH},
            "集中度",
            f"单只基金「{report.max_single_name}」占比达 "
            f"{report.max_single_weight:.1%}，结构上高度依赖单一标的，"
            f"可考虑将单一基金控制在 {RT.SINGLE_FUND_HIGH:.0%} 以内以分散风险。",
        ))
    elif report.max_single_weight >= RT.SINGLE_FUND_WARN:
        advice.append(Advice(
            "concentration_mid",
            {"name": report.max_single_name, "weight": report.max_single_weight},
            "集中度",
            f"最大单基金「{report.max_single_name}」占比 "
            f"{report.max_single_weight:.1%}，集中度中等偏高，可适度均衡。",
        ))

    # 2) 权益/防守结构
    if report.equity_weight >= RT.EQUITY_WARN:
        advice.append(Advice(
            "equity_heavy",
            {"weight": report.equity_weight, "threshold": RT.EQUITY_WARN},
            "结构",
            f"权益类资产占比 {report.equity_weight:.1%}，组合偏成长/进攻；"
            f"若希望降低波动，可提高债券等低波动资产比例。",
        ))
    if report.bond_weight < RT.BOND_MIN:
        advice.append(Advice(
            "bond_low",
            {"weight": report.bond_weight, "threshold": RT.BOND_MIN},
            "结构",
            f"债券型占比仅 {report.bond_weight:.1%}，防守型资产偏低，"
            f"组合缺乏下行缓冲，可考虑提升至 {RT.BOND_MIN:.0%} 以上。",
        ))

    # 3) 海外暴露
    if report.qdii_weight >= RT.QDII_WARN:
        advice.append(Advice(
            "qdii_high",
            {"weight": report.qdii_weight, "threshold": RT.QDII_WARN},
            "风格",
            f"QDII/海外资产占比 {report.qdii_weight:.1%}，海外与汇率暴露较高，"
            f"注意与 A 股资产的相关性及汇率波动。",
        ))

    # 4) 板块集中
    sector_df = _sector_distribution(positions)
    if not sector_df.empty:
        top = sector_df.iloc[0]
        # 汇总科技/成长相关板块
        tech_weight = sector_df[
            sector_df["sector"].str.contains("|".join(TECH_SECTOR_KEYS), na=False)
        ]["weight"].sum()

        if top["sector"] != "其它" and top["weight"] >= SECTOR_CONCENTRATION_THRESHOLD:
            advice.append(Advice(
                "sector_concentrated",
                {"sector": top["sector"], "weight": float(top["weight"])},
                "板块",
                f"最大板块「{top['sector']}」占比 {top['weight']:.1%}，"
                f"板块集中度较高，单一主题回调时影响明显。",
            ))
        if tech_weight >= TECH_HEAVY_THRESHOLD:
            advice.append(Advice(
                "tech_heavy",
                {"weight": float(tech_weight)},
                "板块",
                f"科技/成长相关板块合计约 {tech_weight:.1%}，"
                f"风格高度集中于科技成长，可考虑增加低相关性资产以平衡。",
            ))

    if not advice:
        advice.append(Advice(
            "balanced", {}, "结构",
            "当前组合结构相对均衡，暂无明显的结构性调整建议，"
            "可保持并持续跟踪。",
        ))

    # 四段可解释结构（evidence/positions/simulation/risks）
    for a in advice:
        a.evidence = _build_evidence(a, report)
        a.positions = _build_involved(a.code, positions)
        a.simulation = _build_simulation(a.code, positions)
        a.risks = _build_risks(a.code, a.simulation, data_status)
    return advice


# ---------------------------------------------------------------------------
# 四段结构构建（全部 code + params，无自由文本）
# ---------------------------------------------------------------------------

def _build_evidence(a: Advice, report: RiskReport) -> list[dict[str, Any]]:
    """依据：触发该建议的指标值与阈值（口径与触发规则一致）。"""
    code = a.code
    if code == "concentration_high":
        return [{"metric": "max_single_weight", "value": report.max_single_weight,
                 "threshold": RT.SINGLE_FUND_HIGH,
                 "params": {"name": report.max_single_name}}]
    if code == "concentration_mid":
        return [{"metric": "max_single_weight", "value": report.max_single_weight,
                 "threshold": RT.SINGLE_FUND_WARN,
                 "params": {"name": report.max_single_name}}]
    if code == "equity_heavy":
        return [{"metric": "equity_weight", "value": report.equity_weight,
                 "threshold": RT.EQUITY_WARN, "params": {}}]
    if code == "bond_low":
        return [{"metric": "bond_weight", "value": report.bond_weight,
                 "threshold": RT.BOND_MIN, "params": {}}]
    if code == "qdii_high":
        return [{"metric": "qdii_weight", "value": report.qdii_weight,
                 "threshold": RT.QDII_WARN, "params": {}}]
    if code == "sector_concentrated":
        return [{"metric": "sector_weight", "value": a.params.get("weight", 0.0),
                 "threshold": SECTOR_CONCENTRATION_THRESHOLD,
                 "params": {"sector": a.params.get("sector", "")}}]
    if code == "tech_heavy":
        return [{"metric": "tech_weight", "value": a.params.get("weight", 0.0),
                 "threshold": TECH_HEAVY_THRESHOLD, "params": {}}]
    return []


def _active(positions: list[Position]) -> list[Position]:
    return [p for p in positions if p.is_open and p.market_value > 0]


def _position_ref(p: Position) -> dict[str, Any]:
    return {"fund_code": p.fund_code, "name": p.fund_name,
            "channel": p.channel, "weight": p.weight}


def _build_involved(code: str, positions: list[Position]) -> list[dict[str, Any]]:
    """涉及持仓：按建议类型筛选，权重降序，最多 _INVOLVED_CAP 条。"""
    active = _active(positions)
    total = sum(p.market_value for p in active)
    active = sorted(_reweight(active, total), key=lambda p: p.weight, reverse=True)
    if code in ("concentration_high", "concentration_mid"):
        if not active:
            return []
        return [_position_ref(active[0])]
    if code == "equity_heavy":
        active = [p for p in active if _is_equity(p)]
    elif code == "bond_low":
        active = [p for p in active if _is_equity(p) or _is_bond(p)]
    elif code == "qdii_high":
        active = [p for p in active if _is_qdii(p)]
    elif code == "sector_concentrated":
        df = _sector_distribution(positions)
        if df.empty:
            return []
        top_sector = df.iloc[0]["sector"]
        active = [p for p in active if (p.sector or "其它") == top_sector]
    elif code == "tech_heavy":
        active = [p for p in active if _is_tech_sector(p.sector)]
    return [_position_ref(p) for p in active[:_INVOLVED_CAP]]


def _build_risks(code: str, simulation: dict[str, Any] | None,
                 data_status: DataStatus | None) -> list[dict[str, Any]]:
    """风险/限制：固定声明 + 演算假设/不可演算 + 数据质量 caveat。"""
    if code == "no_holding":
        return []
    if code == "balanced":
        return [{"code": "not_investment_advice", "params": {}}]
    risks: list[dict[str, Any]] = [
        {"code": "not_investment_advice", "params": {}},
        {"code": "model_limitation", "params": {}},
    ]
    if simulation is not None:
        risks.append({"code": "simulation_assumption",
                      "params": {"rule": simulation["rule"]}})
    else:
        risks.append({"code": "simulation_unavailable", "params": {}})
    if data_status is not None and (
        data_status.stale_nav_fund_count > 0 or data_status.missing_nav_fund_count > 0
    ):
        risks.append({"code": "data_stale", "params": {
            "stale": data_status.stale_nav_fund_count,
            "missing": data_status.missing_nav_fund_count,
        }})
    return risks


# ---------------------------------------------------------------------------
# simulation：what-if 假设演算（纯函数，不落库、不写交易、不联网）
# ---------------------------------------------------------------------------

def _reweight(positions: list[Position], total: float) -> list[Position]:
    """按新市值重算 weight（总市值不变的假设演算）。"""
    return [replace(p, weight=(p.market_value / total if total > 0 else 0.0))
            for p in positions]


def _reduce_row_to_weight(active: list[Position], target: Position,
                          target_weight: float, total: float) -> list[Position] | None:
    """把单一持仓降至目标权重，腾出市值按比例分配到其他持仓。"""
    new_mv = target_weight * total
    if new_mv >= target.market_value:
        return None
    others = [p for p in active if p is not target]
    other_total = sum(p.market_value for p in others)
    if not others or other_total <= 0:
        return None
    delta = target.market_value - new_mv
    result = []
    for p in active:
        if p is target:
            result.append(replace(p, market_value=new_mv))
        else:
            result.append(replace(p, market_value=p.market_value + delta * p.market_value / other_total))
    return _reweight(result, total)


def _reduce_group_to_weight(active: list[Position], pred: Callable[[Position], bool],
                            target_weight: float, total: float) -> list[Position] | None:
    """把一组持仓合计降至目标权重，腾出市值按比例分配到组外持仓。"""
    group = [p for p in active if pred(p)]
    rest = [p for p in active if not pred(p)]
    group_mv = sum(p.market_value for p in group)
    target_mv = target_weight * total
    if not group or not rest or group_mv <= target_mv:
        return None
    rest_total = sum(p.market_value for p in rest)
    if rest_total <= 0:
        return None
    delta = group_mv - target_mv
    factor = target_mv / group_mv
    result = []
    for p in active:
        if pred(p):
            result.append(replace(p, market_value=p.market_value * factor))
        else:
            result.append(replace(p, market_value=p.market_value + delta * p.market_value / rest_total))
    return _reweight(result, total)


def _transfer_between(active: list[Position], src_pred: Callable[[Position], bool],
                      dst_pred: Callable[[Position], bool],
                      amount: float) -> list[Position] | None:
    """从 src 组转出 amount 市值到 dst 组（各按现有市值比例）。"""
    if amount <= 0:
        return None
    src = [p for p in active if src_pred(p)]
    dst = [p for p in active if dst_pred(p)]
    src_mv = sum(p.market_value for p in src)
    dst_mv = sum(p.market_value for p in dst)
    if not src or not dst or src_mv < amount or dst_mv <= 0:
        return None
    factor = (src_mv - amount) / src_mv
    result = []
    for p in active:
        if src_pred(p):
            result.append(replace(p, market_value=p.market_value * factor))
        elif dst_pred(p):
            result.append(replace(p, market_value=p.market_value + amount * p.market_value / dst_mv))
        else:
            result.append(p)
    total = sum(p.market_value for p in result)
    return _reweight(result, total)


def _simulation_metrics(positions: list[Position]) -> dict[str, Any]:
    """前后对比指标：集中度/结构/板块/科技占比 + 体检配置维度分。

    全部用既有纯函数重算，口径与体检/风险页一致；配置分复用
    health._score_allocation（延迟导入避免循环依赖）。
    """
    max_w, max_name, hhi = calculate_concentration(positions)
    equity, bond, qdii = structure_weights(positions)
    df = _sector_distribution(positions)
    top_sector_weight = float(df.iloc[0]["weight"]) if not df.empty else 0.0
    tech_weight = 0.0
    if not df.empty:
        tech_weight = float(df[
            df["sector"].str.contains("|".join(TECH_SECTOR_KEYS), na=False)
        ]["weight"].sum())

    from . import health  # 延迟导入：health 模块级导入 rebalance
    rr = RiskReport(max_single_weight=max_w, max_single_name=max_name, hhi=hhi,
                    equity_weight=equity, bond_weight=bond, qdii_weight=qdii)
    summary_ns = SimpleNamespace(holding_count=len({p.fund_code for p in positions}))
    allocation_score = health._score_allocation(rr, summary_ns).score

    return {
        "max_single_weight": max_w,
        "equity_weight": equity,
        "bond_weight": bond,
        "qdii_weight": qdii,
        "top_sector_weight": top_sector_weight,
        "tech_weight": tech_weight,
        "allocation_score": allocation_score,
    }


def _build_simulation(code: str, positions: list[Position]) -> dict[str, Any] | None:
    """按建议类型执行假设演算；无法演算（持仓不足/无目标类别）返回 None。

    规则（P3 规划 §4.2，D6）：降阈值 + 腾出权重按比例再分配，总市值不变。
    """
    active = _active(positions)
    if len(active) < 2:
        return None
    total = sum(p.market_value for p in active)
    if total <= 0:
        return None
    active = _reweight(active, total)

    equity_pred = _is_equity
    bond_pred = _is_bond
    qdii_pred = _is_qdii

    adjusted: list[Position] | None = None
    rule = ""
    params: dict[str, Any] = {}

    if code in ("concentration_high", "concentration_mid"):
        target_w = (RT.SINGLE_FUND_HIGH if code == "concentration_high"
                    else RT.SINGLE_FUND_WARN)
        top = max(active, key=lambda p: p.weight)
        adjusted = _reduce_row_to_weight(active, top, target_w, total)
        rule = "reduce_single_fund"
        params = {"fund_code": top.fund_code, "name": top.fund_name,
                  "channel": top.channel, "target": target_w}
    elif code == "equity_heavy":
        equity_mv = sum(p.market_value for p in active if equity_pred(p))
        adjusted = _transfer_between(active, equity_pred, bond_pred,
                                     equity_mv - RT.EQUITY_WARN * total)
        rule = "equity_to_bond"
        params = {"target": RT.EQUITY_WARN, "side": "equity"}
    elif code == "bond_low":
        bond_mv = sum(p.market_value for p in active if bond_pred(p))
        adjusted = _transfer_between(active, equity_pred, bond_pred,
                                     RT.BOND_MIN * total - bond_mv)
        rule = "equity_to_bond"
        params = {"target": RT.BOND_MIN, "side": "bond"}
    elif code == "qdii_high":
        adjusted = _reduce_group_to_weight(active, qdii_pred, RT.QDII_WARN, total)
        rule = "reduce_qdii"
        params = {"target": RT.QDII_WARN}
    elif code == "sector_concentrated":
        df = _sector_distribution(active)
        if df.empty:
            return None
        top_sector = df.iloc[0]["sector"]
        adjusted = _reduce_group_to_weight(
            active, lambda p: (p.sector or "其它") == top_sector,
            SECTOR_CONCENTRATION_THRESHOLD, total)
        rule = "reduce_sector"
        params = {"sector": top_sector, "target": SECTOR_CONCENTRATION_THRESHOLD}
    elif code == "tech_heavy":
        adjusted = _reduce_group_to_weight(
            active, lambda p: _is_tech_sector(p.sector), TECH_HEAVY_THRESHOLD, total)
        rule = "reduce_tech"
        params = {"target": TECH_HEAVY_THRESHOLD}
    else:
        return None

    if adjusted is None:
        return None
    return {
        "rule": rule,
        "params": params,
        "before": _simulation_metrics(active),
        "after": _simulation_metrics(adjusted),
    }


if __name__ == "__main__":
    from . import db
    db.init_db()
    for a in generate_advice():
        print(f"[{a.category}] {a.text}")
