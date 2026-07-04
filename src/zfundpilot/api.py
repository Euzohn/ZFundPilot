"""FastAPI REST API 层。

启动：
    uvicorn zfundpilot.api:app --reload --port 8000

所有业务逻辑复用 src/zfundpilot 下的现有模块，
本文件只做 HTTP 入参/出参的序列化与路由编排。
"""
from __future__ import annotations

import os
from typing import Any

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from pydantic import BaseModel

from . import analysis, data_io, db, fetch_fund, rebalance, risk
from .models import Fund, Transaction

app = FastAPI(title="ZFundPilot API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def _startup() -> None:
    db.init_db()


# ---------------------------------------------------------------------------
# 请求模型
# ---------------------------------------------------------------------------
class TransactionCreate(BaseModel):
    fund_code: str
    action: str
    date: str
    amount: float | None = None
    shares: float | None = None
    nav: float | None = None
    fee: float = 0.0
    channel: str = ""
    note: str = ""


class SectorUpdate(BaseModel):
    sector: str


class CSVImportConfirm(BaseModel):
    transactions: list[TransactionCreate]
    clear_existing: bool = False
    fetch_meta: bool = True


# ---------------------------------------------------------------------------
# 组合总览
# ---------------------------------------------------------------------------
@app.get("/api/summary")
def get_summary() -> dict[str, Any]:
    return analysis.calculate_summary().to_dict()


@app.get("/api/distribution/{field}")
def get_distribution(field: str) -> list[dict[str, Any]]:
    if field not in ("fund_type", "sector", "channel"):
        raise HTTPException(400, f"不支持的字段: {field}")
    positions = analysis.calculate_positions()
    df = analysis.distribution_by(positions, field)
    return df.to_dict(orient="records")


# ---------------------------------------------------------------------------
# 持仓
# ---------------------------------------------------------------------------
@app.get("/api/positions")
def get_positions(include_closed: bool = False) -> list[dict[str, Any]]:
    positions = analysis.calculate_positions(include_closed=include_closed)
    return [p.to_dict() for p in positions]


# ---------------------------------------------------------------------------
# 交易流水
# ---------------------------------------------------------------------------
@app.get("/api/transactions")
def get_transactions() -> list[dict[str, Any]]:
    return [t.to_dict() for t in db.get_transactions_desc()]


@app.post("/api/transactions")
def add_transaction(body: TransactionCreate) -> dict[str, Any]:
    _ensure_fund_exists(body.fund_code)
    tx = Transaction(
        fund_code=body.fund_code,
        action=body.action,
        date=body.date,
        amount=body.amount,
        shares=body.shares,
        nav=body.nav,
        fee=body.fee,
        channel=body.channel,
        note=body.note,
    )
    tx.normalize()
    if not tx.is_valid():
        raise HTTPException(400, "金额/份额/净值信息不足，至少需要其中两项")
    tx_id = db.add_transaction(tx)
    return {"id": tx_id, **tx.to_dict()}


@app.delete("/api/transactions/{tx_id}")
def delete_transaction(tx_id: int) -> dict[str, bool]:
    db.delete_transaction(tx_id)
    return {"ok": True}


@app.delete("/api/transactions")
def delete_all_transactions() -> dict[str, bool]:
    db.delete_all_transactions()
    return {"ok": True}


# ---------------------------------------------------------------------------
# 基金信息
# ---------------------------------------------------------------------------
@app.get("/api/funds")
def get_funds() -> list[dict[str, Any]]:
    return [f.to_dict() for f in db.get_funds()]


@app.get("/api/funds/{code}")
def get_fund(code: str) -> dict[str, Any]:
    fund = db.get_fund(code)
    if not fund:
        raise HTTPException(404, f"未找到基金 {code}")
    return fund.to_dict()


@app.post("/api/funds/{code}/fetch")
def fetch_meta(code: str) -> dict[str, Any]:
    meta = fetch_fund.fetch_fund_meta(code)
    if meta.ok:
        db.upsert_fund(Fund(code, meta.fund_name, meta.fund_type, meta.sector))
        fetch_fund.save_sector_mapping(code, meta.sector)
    return meta.__dict__


@app.put("/api/funds/{code}/sector")
def update_sector(code: str, body: SectorUpdate) -> dict[str, bool]:
    db.update_fund_sector(code, body.sector)
    fetch_fund.save_sector_mapping(code, body.sector)
    return {"ok": True}


# ---------------------------------------------------------------------------
# 净值
# ---------------------------------------------------------------------------
@app.post("/api/nav/update")
def update_nav() -> list[dict[str, Any]]:
    results = fetch_fund.update_all_holdings_nav()
    return [r.__dict__ for r in results]


@app.get("/api/nav/{code}")
def get_nav_history(code: str) -> list[dict[str, Any]]:
    rows = db.get_nav_history(code)
    return [dict(r) for r in rows]


@app.get("/api/nav/latest")
def get_latest_navs() -> list[dict[str, Any]]:
    codes = db.get_distinct_fund_codes()
    result = []
    for code in codes:
        latest = db.get_latest_nav(code)
        if latest:
            result.append({
                "fund_code": code,
                "date": latest["date"],
                "nav": float(latest["nav"]),
            })
    return result


# ---------------------------------------------------------------------------
# 组合曲线 & 风险 & 建议
# ---------------------------------------------------------------------------
@app.get("/api/portfolio/curve")
def get_portfolio_curve() -> list[dict[str, Any]]:
    curve = analysis.build_portfolio_curve()
    if curve.empty:
        return []
    return curve.to_dict(orient="records")


@app.get("/api/risk")
def get_risk_report() -> dict[str, Any]:
    report = risk.build_risk_report()
    return {
        "max_drawdown": report.max_drawdown,
        "volatility": report.volatility,
        "max_single_weight": report.max_single_weight,
        "max_single_name": report.max_single_name,
        "hhi": report.hhi,
        "equity_weight": report.equity_weight,
        "bond_weight": report.bond_weight,
        "qdii_weight": report.qdii_weight,
        "flags": [
            {"level": f.level, "title": f.title, "detail": f.detail}
            for f in report.flags
        ],
    }


@app.get("/api/rebalance")
def get_rebalance_advice() -> list[dict[str, str]]:
    advice = rebalance.generate_advice()
    return [{"category": a.category, "text": a.text} for a in advice]


# ---------------------------------------------------------------------------
# CSV 导入/导出
# ---------------------------------------------------------------------------
@app.get("/api/csv/template")
def download_template() -> Response:
    return Response(
        content=data_io.template_csv_bytes(),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=transactions_template.csv"},
    )


@app.get("/api/csv/export")
def export_transactions() -> Response:
    txs = db.get_transactions_desc()
    return Response(
        content=data_io.transactions_to_csv_bytes(txs),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=my_transactions.csv"},
    )


@app.post("/api/csv/parse")
async def parse_csv(file: UploadFile = File(...)) -> dict[str, Any]:
    content = await file.read()
    txs, errors = data_io.parse_transactions_csv(content)
    return {
        "transactions": [t.to_dict() for t in txs],
        "errors": errors,
    }


@app.post("/api/csv/import")
def confirm_import(body: CSVImportConfirm) -> dict[str, Any]:
    if body.clear_existing:
        db.delete_all_transactions()
    codes = {t.fund_code for t in body.transactions}
    if body.fetch_meta:
        for code in codes:
            _ensure_fund_exists(code)
    else:
        for code in codes:
            if not db.get_fund(code):
                db.upsert_fund(Fund(code, code))
    count = 0
    for t in body.transactions:
        tx = Transaction(
            fund_code=t.fund_code, action=t.action, date=t.date,
            amount=t.amount, shares=t.shares, nav=t.nav,
            fee=t.fee, channel=t.channel, note=t.note,
        )
        db.add_transaction(tx)
        count += 1
    return {"imported": count}


# ---------------------------------------------------------------------------
# 辅助
# ---------------------------------------------------------------------------
def _ensure_fund_exists(code: str, name: str = "", ftype: str = "其它",
                        sector: str = "") -> None:
    fund = db.get_fund(code)
    if fund and fund.fund_name and fund.fund_name != code:
        return
    if not name:
        meta = fetch_fund.fetch_fund_meta(code)
        if meta.ok:
            name, ftype, sector = meta.fund_name, meta.fund_type, meta.sector
    db.upsert_fund(Fund(code, name or code, ftype, sector))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("zfundpilot.api:app", host="127.0.0.1", port=8000, reload=True)


# ---------------------------------------------------------------------------
# 静态文件（生产模式：前端构建后由 FastAPI 统一服务）
# ---------------------------------------------------------------------------
# src/zfundpilot/api.py → 上溯三级 = 项目根 → frontend/dist
_frontend_dist = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "frontend", "dist",
)
if os.path.isdir(_frontend_dist):
    from fastapi.staticfiles import StaticFiles
    app.mount("/", StaticFiles(directory=_frontend_dist, html=True), name="frontend")
