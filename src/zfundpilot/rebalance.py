"""再平衡建议模块。

⚠️ 重要：本模块只产出「结构优化建议」，不产出任何买入/卖出交易指令。
所有措辞聚焦于组合结构、风格暴露与占比，帮助用户做长期结构判断。
"""

from __future__ import annotations

from dataclasses import dataclass

from . import analysis
from .config import RiskThresholds as RT
from .models import Position
from .risk import RiskReport, build_risk_report


@dataclass
class Advice:
    """一条结构建议。"""
    category: str    # 集中度 / 结构 / 风格 / 板块
    text: str


def _sector_distribution(positions: list[Position]):
    df = analysis.distribution_by(positions, "sector")
    return df


def generate_advice(
    positions: list[Position] | None = None,
    report: RiskReport | None = None,
) -> list[Advice]:
    """基于持仓结构与风险报告生成结构优化建议列表。"""
    if positions is None:
        positions = analysis.calculate_positions()
    if report is None:
        report = build_risk_report(positions)

    advice: list[Advice] = []

    if not positions:
        return [Advice("提示", "当前没有持仓数据，先添加基金后再查看结构建议。")]

    # 1) 单基金集中度
    if report.max_single_weight >= RT.SINGLE_FUND_HIGH:
        advice.append(Advice(
            "集中度",
            f"单只基金「{report.max_single_name}」占比达 "
            f"{report.max_single_weight:.1%}，结构上高度依赖单一标的，"
            f"可考虑将单一基金控制在 {RT.SINGLE_FUND_HIGH:.0%} 以内以分散风险。",
        ))
    elif report.max_single_weight >= RT.SINGLE_FUND_WARN:
        advice.append(Advice(
            "集中度",
            f"最大单基金「{report.max_single_name}」占比 "
            f"{report.max_single_weight:.1%}，集中度中等偏高，可适度均衡。",
        ))

    # 2) 权益/防守结构
    if report.equity_weight >= RT.EQUITY_WARN:
        advice.append(Advice(
            "结构",
            f"权益类资产占比 {report.equity_weight:.1%}，组合偏成长/进攻；"
            f"若希望降低波动，可提高债券等低波动资产比例。",
        ))
    if report.bond_weight < RT.BOND_MIN:
        advice.append(Advice(
            "结构",
            f"债券型占比仅 {report.bond_weight:.1%}，防守型资产偏低，"
            f"组合缺乏下行缓冲，可考虑提升至 {RT.BOND_MIN:.0%} 以上。",
        ))

    # 3) 海外暴露
    if report.qdii_weight >= RT.QDII_WARN:
        advice.append(Advice(
            "风格",
            f"QDII/海外资产占比 {report.qdii_weight:.1%}，海外与汇率暴露较高，"
            f"注意与 A 股资产的相关性及汇率波动。",
        ))

    # 4) 板块集中
    sector_df = _sector_distribution(positions)
    if not sector_df.empty:
        top = sector_df.iloc[0]
        # 汇总科技/成长相关板块
        tech_keys = ["CPO", "半导体", "算力", "人工智能", "AI", "PCB",
                     "通信", "大科技", "科技", "机器人"]
        tech_weight = sector_df[
            sector_df["sector"].str.contains("|".join(tech_keys), na=False)
        ]["weight"].sum()

        if top["sector"] != "其它" and top["weight"] >= 0.20:
            advice.append(Advice(
                "板块",
                f"最大板块「{top['sector']}」占比 {top['weight']:.1%}，"
                f"板块集中度较高，单一主题回调时影响明显。",
            ))
        if tech_weight >= 0.50:
            advice.append(Advice(
                "板块",
                f"科技/成长相关板块合计约 {tech_weight:.1%}，"
                f"风格高度集中于科技成长，可考虑增加低相关性资产以平衡。",
            ))

    if not advice:
        advice.append(Advice(
            "结构", "当前组合结构相对均衡，暂无明显的结构性调整建议，"
                     "可保持并持续跟踪。",
        ))
    return advice


def format_advice_text(advice: list[Advice]) -> str:
    """把建议列表格式化为纯文本段落，便于展示或导出。"""
    lines = ["组合结构优化建议（非交易指令）：", ""]
    for i, a in enumerate(advice, start=1):
        lines.append(f"{i}. [{a.category}] {a.text}")
    return "\n".join(lines)


if __name__ == "__main__":
    from . import db
    db.init_db()
    for a in generate_advice():
        print(f"[{a.category}] {a.text}")
