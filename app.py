"""ZFundPilot 主界面（Streamlit）。

运行：
    streamlit run app.py

页面结构（侧边栏切换）：
    1. 组合总览
    2. 交易录入（表单 + CSV 导入/导出）
    3. 持仓明细（按基金/渠道汇总）
    4. 交易流水
    5. 净值更新
    6. 收益分析
    7. 风险与建议

模型：交易流水驱动，持仓按 (基金 + 渠道) 用移动加权平均成本法汇总。
设计原则：只做数据分析与风险管理，不做任何交易指令。
"""

from __future__ import annotations

import pandas as pd
import plotly.express as px
import streamlit as st

import analysis
import config
import data_io
import db
import fetch_fund
import rebalance
import risk
from models import (ACTION_BUY, ACTION_SELL, ACTION_LABELS, Fund, Transaction)

# ---------------------------------------------------------------------------
# 初始化
# ---------------------------------------------------------------------------
st.set_page_config(page_title="ZFundPilot 个人基金分析", page_icon="📦", layout="wide")
db.init_db()


# ---------------------------------------------------------------------------
# 公共工具
# ---------------------------------------------------------------------------
def money(v) -> str:
    if v is None:
        return "—"
    return f"¥{v:,.2f}"


def pct(v, digits: int = 2) -> str:
    if v is None:
        return "—"
    return f"{v * 100:.{digits}f}%"


def nav_str(v) -> str:
    return "—" if v is None else f"{v:.4f}"


def signed_money(v) -> str:
    if v is None:
        return "—"
    sign = "+" if v >= 0 else "-"
    return f"{sign}¥{abs(v):,.2f}"


LEVEL_STYLE = {
    "danger": ("🔴", "error"),
    "warning": ("🟠", "warning"),
    "info": ("🔵", "info"),
}


def _ensure_fund_exists(code: str, name: str = "", ftype: str = "其它",
                        sector: str = "") -> None:
    """确保基金在 funds 表中存在，缺失时联网补全。"""
    fund = db.get_fund(code)
    if fund and fund.fund_name and fund.fund_name != code:
        return
    if not name:
        meta = fetch_fund.fetch_fund_meta(code)
        if meta.ok:
            name, ftype, sector = meta.fund_name, meta.fund_type, meta.sector
    db.upsert_fund(Fund(code, name or code, ftype, sector))


# ---------------------------------------------------------------------------
# 页面：组合总览
# ---------------------------------------------------------------------------
def page_overview():
    st.header("📊 组合总览")

    positions = analysis.calculate_positions(include_closed=True)
    open_positions = [p for p in positions if p.is_open]
    if not open_positions and not positions:
        st.info("还没有交易记录。请到「交易录入」添加买入/卖出流水或导入 CSV。")
        return

    summary = analysis.calculate_summary(positions)

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("当前持仓成本", money(summary.total_cost))
    c2.metric("当前市值", money(summary.total_value))
    c3.metric("浮动盈亏", signed_money(summary.unrealized_pnl),
              delta=pct(summary.total_return))
    c4.metric("已实现盈亏", signed_money(summary.realized_pnl))

    c5, c6, c7, c8 = st.columns(4)
    c5.metric("总盈亏（浮动+已实现）", signed_money(summary.total_pnl))
    c6.metric("累计买入 / 卖出",
              f"{money(summary.total_buy)} / {money(summary.total_sell)}")
    c7.metric("持仓数量", f"{summary.holding_count} 个")
    c8.metric("净值日期", summary.as_of_date or "未更新")

    if summary.max_single_name:
        st.caption(f"最大单持仓：{summary.max_single_name} "
                   f"占比 {pct(summary.max_single_weight)}")

    st.divider()

    col1, col2, col3 = st.columns(3)
    with col1:
        st.subheader("资产类型")
        df = analysis.distribution_by(open_positions, "fund_type")
        if not df.empty:
            fig = px.pie(df, names="fund_type", values="market_value", hole=0.4)
            fig.update_traces(textposition="inside", textinfo="percent+label")
            st.plotly_chart(fig, width="stretch")

    with col2:
        st.subheader("渠道分布")
        df = analysis.distribution_by(open_positions, "channel")
        if not df.empty:
            df["channel"] = df["channel"].replace("", "未标注")
            fig = px.pie(df, names="channel", values="market_value", hole=0.4)
            fig.update_traces(textposition="inside", textinfo="percent+label")
            st.plotly_chart(fig, width="stretch")

    with col3:
        st.subheader("板块分布")
        df = analysis.distribution_by(open_positions, "sector")
        if not df.empty:
            fig = px.bar(df.head(12), x="market_value", y="sector",
                         orientation="h")
            fig.update_layout(yaxis={"categoryorder": "total ascending"},
                              xaxis_title="市值", yaxis_title="")
            st.plotly_chart(fig, width="stretch")


# ---------------------------------------------------------------------------
# 页面：交易录入
# ---------------------------------------------------------------------------
def page_add_transaction():
    st.header("➕ 交易录入")

    tab_form, tab_csv = st.tabs(["📝 单笔录入", "📁 CSV 批量导入/导出"])

    # --- 单笔录入 ---
    with tab_form:
        st.markdown("**第一步：输入代码，自动获取基金信息**")
        lc1, lc2 = st.columns([3, 1])
        lc1.text_input("基金代码 *", key="tx_code", placeholder="如 011612")
        if lc2.button("🔍 获取基金信息", width="stretch"):
            code = st.session_state.get("tx_code", "").strip()
            if not code:
                st.warning("请先输入基金代码")
            else:
                with st.spinner("查询中..."):
                    meta = fetch_fund.fetch_fund_meta(code)
                if meta.ok:
                    db.upsert_fund(Fund(code, meta.fund_name, meta.fund_type,
                                        meta.sector))
                    fetch_fund.save_sector_mapping(code, meta.sector)
                    st.session_state["tx_meta"] = meta.fund_name
                    st.success(f"已识别：{meta.fund_name}（{meta.fund_type}）"
                               f"{' 板块:' + meta.sector if meta.sector else ''}")
                else:
                    st.error(f"获取失败：{meta.message}")

        meta_name = st.session_state.get("tx_meta", "")
        if meta_name:
            st.caption(f"当前基金：{meta_name}")

        st.markdown("**第二步：填写交易信息**")
        with st.form("add_tx", clear_on_submit=True):
            c1, c2, c3 = st.columns(3)
            action_label = c1.selectbox("操作 *", ["买入", "卖出"])
            date = c2.date_input("成交日期 *", value=None)
            channel = c3.selectbox("渠道", config.CHANNELS,
                                   index=config.CHANNELS.index(config.DEFAULT_CHANNEL))

            st.caption("金额 / 份额 / 净值：填写其中任意两项即可，系统自动补全第三项。")
            c4, c5, c6 = st.columns(3)
            amount = c4.number_input("金额", min_value=0.0, step=100.0, value=0.0)
            shares = c5.number_input("份额", min_value=0.0, step=1.0, value=0.0)
            nav = c6.number_input("成交净值", min_value=0.0, step=0.0001,
                                  format="%.4f", value=0.0)

            c7, c8 = st.columns(2)
            fee = c7.number_input("手续费", min_value=0.0, step=1.0, value=0.0)
            custom_channel = c8.text_input("自定义渠道（可选，覆盖上面选择）",
                                           placeholder="如 招商银行")

            note = st.text_input("备注", placeholder="可选")

            submitted = st.form_submit_button("✅ 保存交易", type="primary")
            if submitted:
                code = st.session_state.get("tx_code", "").strip()
                filled = sum(1 for v in (amount, shares, nav) if v > 0)
                if not code:
                    st.error("基金代码不能为空（第一步输入）")
                elif date is None:
                    st.error("请选择成交日期")
                elif filled < 2:
                    st.error("金额 / 份额 / 净值 至少填写两项")
                else:
                    _ensure_fund_exists(code)
                    tx = Transaction(
                        fund_code=code,
                        action=ACTION_BUY if action_label == "买入" else ACTION_SELL,
                        date=str(date),
                        amount=amount or None,
                        shares=shares or None,
                        nav=nav or None,
                        fee=fee,
                        channel=custom_channel.strip() or channel,
                        note=note.strip(),
                    )
                    tx.normalize()
                    db.add_transaction(tx)
                    st.session_state.pop("tx_meta", None)
                    st.success(f"已保存：{action_label} {code} "
                               f"{money(tx.amount)}（{tx.channel}）")

    # --- CSV 导入/导出 ---
    with tab_csv:
        st.subheader("批量导入交易流水")
        st.markdown("必填列：`fund_code`、`action`（买入/卖出）、`date`；"
                    "`amount`/`shares`/`nav` 至少两项；`channel` 为渠道。支持中文表头。")
        st.download_button("⬇️ 下载 CSV 模板", data=data_io.template_csv_bytes(),
                           file_name="transactions_template.csv", mime="text/csv")

        uploaded = st.file_uploader("上传 CSV 文件", type=["csv"])
        if uploaded is not None:
            txs, errors = data_io.parse_transactions_csv(uploaded.getvalue())
            if txs:
                st.success(f"解析成功 {len(txs)} 笔，预览：")
                st.dataframe(_tx_preview_df(txs), width="stretch", hide_index=True)
            if errors:
                with st.expander(f"⚠️ {len(errors)} 条提示/警告"):
                    for e in errors:
                        st.text(e)
            if txs:
                mode = st.radio("导入方式", ["追加到现有流水", "清空后重新导入"],
                                horizontal=True)
                fetch_meta = st.checkbox("导入时自动获取缺失的基金名称/类型/板块",
                                         value=True)
                if st.button("📥 确认导入", type="primary"):
                    if mode == "清空后重新导入":
                        db.delete_all_transactions()
                    codes = {t.fund_code for t in txs}
                    if fetch_meta:
                        prog = st.progress(0.0, text="获取基金信息...")
                        for i, code in enumerate(sorted(codes), start=1):
                            _ensure_fund_exists(code)
                            prog.progress(i / len(codes))
                        prog.empty()
                    else:
                        for code in codes:
                            if not db.get_fund(code):
                                db.upsert_fund(Fund(code, code))
                    for t in txs:
                        db.add_transaction(t)
                    st.success(f"已导入 {len(txs)} 笔交易")
                    st.rerun()

        st.divider()
        st.subheader("导出交易流水")
        all_tx = db.get_transactions_desc()
        if all_tx:
            st.download_button("⬇️ 导出为 CSV",
                               data=data_io.transactions_to_csv_bytes(all_tx),
                               file_name="my_transactions.csv", mime="text/csv")
        else:
            st.caption("暂无可导出的交易。")


def _tx_preview_df(txs: list[Transaction]) -> pd.DataFrame:
    rows = [{
        "代码": t.fund_code, "操作": ACTION_LABELS.get(t.action, t.action),
        "日期": t.date, "金额": round(t.amount, 2) if t.amount else None,
        "份额": round(t.shares, 2) if t.shares else None,
        "净值": t.nav, "渠道": t.channel, "备注": t.note,
    } for t in txs]
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# 页面：持仓明细
# ---------------------------------------------------------------------------
def page_positions():
    st.header("💼 持仓明细")

    show_closed = st.checkbox("显示已清仓持仓（查看历史已实现收益）", value=False)
    positions = analysis.calculate_positions(include_closed=True)
    if not positions:
        st.info("暂无持仓。请先到「交易录入」添加交易。")
        return

    view = positions if show_closed else [p for p in positions if p.is_open]
    if not view:
        st.info("当前没有在持仓位。勾选上方可查看已清仓记录。")
        return

    rows = []
    for p in view:
        rows.append({
            "代码": p.fund_code,
            "名称": p.fund_name,
            "渠道": p.channel or "未标注",
            "类型": p.fund_type,
            "板块": p.sector or "—",
            "持有份额": round(p.held_shares, 2),
            "持仓成本": round(p.total_cost, 2),
            "均价": nav_str(p.avg_cost_nav),
            "最新净值": nav_str(p.latest_nav),
            "当前市值": round(p.market_value, 2),
            "浮动盈亏": round(p.unrealized_pnl, 2),
            "浮动收益率": pct(p.return_rate),
            "已实现": round(p.realized_pnl, 2),
            "占比": pct(p.weight) if p.is_open else "—",
            "状态": "持有" if p.is_open else "已清仓",
        })
    st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)
    st.caption(f"共 {len(view)} 个持仓（按 基金 + 渠道 拆分）")

    # 同一基金跨渠道合并视图
    st.divider()
    st.subheader("按基金合并（跨渠道）")
    open_positions = [p for p in view if p.is_open]
    if open_positions:
        merged: dict[str, dict] = {}
        for p in open_positions:
            m = merged.setdefault(p.fund_code, {
                "名称": p.fund_name, "市值": 0.0, "成本": 0.0,
                "浮动盈亏": 0.0, "渠道数": 0,
            })
            m["市值"] += p.market_value
            m["成本"] += p.total_cost
            m["浮动盈亏"] += p.unrealized_pnl
            m["渠道数"] += 1
        mrows = []
        for code, m in merged.items():
            mrows.append({
                "代码": code, "名称": m["名称"],
                "市值": round(m["市值"], 2), "成本": round(m["成本"], 2),
                "浮动盈亏": round(m["浮动盈亏"], 2),
                "收益率": pct(m["市值"] / m["成本"] - 1 if m["成本"] else None),
                "渠道数": m["渠道数"],
            })
        mrows.sort(key=lambda x: x["市值"], reverse=True)
        st.dataframe(pd.DataFrame(mrows), width="stretch", hide_index=True)


# ---------------------------------------------------------------------------
# 页面：交易流水
# ---------------------------------------------------------------------------
def page_transactions():
    st.header("📜 交易流水")

    txs = db.get_transactions_desc()
    if not txs:
        st.info("暂无交易流水。")
        return

    funds = {f.fund_code: f for f in db.get_funds()}
    rows = []
    for t in txs:
        t.normalize()
        fund = funds.get(t.fund_code)
        rows.append({
            "ID": t.id,
            "日期": t.date,
            "操作": ACTION_LABELS.get(t.action, t.action),
            "代码": t.fund_code,
            "名称": fund.fund_name if fund else t.fund_code,
            "渠道": t.channel or "未标注",
            "金额": round(t.amount, 2) if t.amount else None,
            "份额": round(t.shares, 2) if t.shares else None,
            "净值": t.nav,
            "手续费": t.fee,
            "备注": t.note,
        })
    st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)
    st.caption(f"共 {len(txs)} 笔交易")

    with st.expander("🗑️ 删除交易"):
        opts = {f"[{t.id}] {t.date} {ACTION_LABELS.get(t.action)} "
                f"{t.fund_code} {money(t.amount)}（{t.channel or '未标注'}）": t.id
                for t in txs}
        sel = st.selectbox("选择要删除的交易", list(opts.keys()))
        col_a, col_b = st.columns([1, 4])
        if col_a.button("删除", type="secondary"):
            db.delete_transaction(opts[sel])
            st.success("已删除")
            st.rerun()
        if col_b.button("⚠️ 清空全部交易"):
            db.delete_all_transactions()
            st.success("已清空")
            st.rerun()


# ---------------------------------------------------------------------------
# 页面：净值更新
# ---------------------------------------------------------------------------
def page_nav_update():
    st.header("🔄 净值更新")

    codes = db.get_distinct_fund_codes()
    last_update = db.get_nav_last_update()

    c1, c2 = st.columns(2)
    c1.metric("待更新基金数", f"{len(codes)} 只")
    c2.metric("净值最近更新", last_update or "未更新")

    if not codes:
        st.info("暂无交易基金，先去录入交易。")
        return

    st.caption("数据源：AkShare 优先，失败自动切换天天基金。首次抓取较慢。")
    if st.button("🚀 更新全部基金净值", type="primary"):
        progress = st.progress(0.0, text="准备中...")
        status = st.empty()

        def on_progress(i, total, code):
            progress.progress(i / total, text=f"更新中 {i}/{total}：{code}")

        results = fetch_fund.update_all_holdings_nav(progress=on_progress)
        progress.empty()
        ok = [r for r in results if r.ok]
        fail = [r for r in results if not r.ok]
        status.success(f"完成：成功 {len(ok)} 只，失败 {len(fail)} 只")
        if fail:
            with st.expander(f"❌ {len(fail)} 只更新失败"):
                for r in fail:
                    st.text(f"{r.fund_code}：{r.message}")

    st.divider()
    st.subheader("各基金最新净值")
    funds = {f.fund_code: f for f in db.get_funds()}
    rows = []
    for code in codes:
        latest = db.get_latest_nav(code)
        fund = funds.get(code)
        rows.append({
            "代码": code,
            "名称": fund.fund_name if fund else code,
            "最新日期": latest["date"] if latest else "—",
            "最新净值": nav_str(latest["nav"]) if latest else "—",
        })
    st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)


# ---------------------------------------------------------------------------
# 页面：收益分析
# ---------------------------------------------------------------------------
def page_returns():
    st.header("📈 收益分析")

    positions = analysis.calculate_positions(include_closed=True)
    if not positions:
        st.info("暂无交易数据。")
        return

    summary = analysis.calculate_summary(positions)
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("当前市值", money(summary.total_value))
    c2.metric("浮动盈亏", signed_money(summary.unrealized_pnl))
    c3.metric("已实现盈亏", signed_money(summary.realized_pnl))
    c4.metric("总收益率", pct(summary.total_return))

    st.subheader("组合收益曲线")
    curve = analysis.build_portfolio_curve()
    if curve.empty or len(curve) < 2:
        st.caption("净值历史不足，先到「净值更新」抓取数据后再查看曲线。")
    else:
        fig = px.line(curve, x="date", y=["total_value", "invested_cost"])
        fig.update_layout(xaxis_title="", yaxis_title="金额",
                          legend_title="", legend=dict(orientation="h"))
        newnames = {"total_value": "组合市值", "invested_cost": "累计净投入"}
        fig.for_each_trace(lambda t: t.update(name=newnames.get(t.name, t.name)))
        st.plotly_chart(fig, width="stretch")

    st.subheader("单基金收益明细")
    open_positions = [p for p in positions if p.is_open]
    rows = []
    for p in open_positions:
        rows.append({
            "代码": p.fund_code, "名称": p.fund_name, "渠道": p.channel or "未标注",
            "持仓成本": round(p.total_cost, 2),
            "当前市值": round(p.market_value, 2),
            "浮动盈亏": round(p.unrealized_pnl, 2),
            "浮动收益率": pct(p.return_rate),
            "已实现": round(p.realized_pnl, 2),
            "占比": pct(p.weight),
        })
    if rows:
        st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)

    # 收益率排序
    chart_rows = [{"名称": f"{p.fund_name}·{p.channel or '未标注'}",
                   "收益率": p.return_rate}
                  for p in open_positions if p.return_rate is not None]
    if chart_rows:
        st.subheader("浮动收益率排序")
        cdf = pd.DataFrame(chart_rows).sort_values("收益率")
        fig = px.bar(cdf, x="收益率", y="名称", orientation="h",
                     color="收益率", color_continuous_scale="RdYlGn")
        fig.update_layout(yaxis_title="", xaxis_tickformat=".1%")
        st.plotly_chart(fig, width="stretch")


# ---------------------------------------------------------------------------
# 页面：风险与建议
# ---------------------------------------------------------------------------
def page_risk():
    st.header("🛡️ 风险与建议")

    positions = [p for p in analysis.calculate_positions(include_closed=True)
                 if p.is_open]
    if not positions:
        st.info("暂无持仓数据。")
        return

    report = risk.build_risk_report(positions)

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("最大回撤",
              pct(report.max_drawdown) if report.max_drawdown is not None else "数据不足")
    c2.metric("年化波动率",
              pct(report.volatility) if report.volatility is not None else "数据不足")
    c3.metric("最大单基金占比", pct(report.max_single_weight),
              help=report.max_single_name)
    c4.metric("集中度 HHI", f"{report.hhi:.3f}")

    c5, c6, c7 = st.columns(3)
    c5.metric("权益类占比", pct(report.equity_weight))
    c6.metric("债券类占比", pct(report.bond_weight))
    c7.metric("QDII 占比", pct(report.qdii_weight))

    st.divider()
    st.subheader("⚠️ 风险提示")
    for f in report.flags:
        icon, kind = LEVEL_STYLE.get(f.level, ("🔵", "info"))
        getattr(st, kind)(f"{icon} **{f.title}** — {f.detail}")

    st.divider()
    st.subheader("🧭 结构优化建议")
    st.caption("以下为组合结构建议，非交易指令。")
    for i, a in enumerate(rebalance.generate_advice(positions, report), start=1):
        st.markdown(f"**{i}. [{a.category}]** {a.text}")


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------
PAGES = {
    "📊 组合总览": page_overview,
    "➕ 交易录入": page_add_transaction,
    "💼 持仓明细": page_positions,
    "📜 交易流水": page_transactions,
    "🔄 净值更新": page_nav_update,
    "📈 收益分析": page_returns,
    "🛡️ 风险与建议": page_risk,
}


def main():
    st.sidebar.title("📦 ZFundPilot")
    st.sidebar.caption("个人基金分析与风险管理系统")
    choice = st.sidebar.radio("导航", list(PAGES.keys()))
    st.sidebar.divider()
    st.sidebar.caption("⚠️ 仅用于数据分析与风险管理，\n不构成任何投资建议或交易指令。")
    PAGES[choice]()


if __name__ == "__main__":
    main()
