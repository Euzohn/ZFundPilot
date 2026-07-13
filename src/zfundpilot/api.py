"""FastAPI REST API 层。

启动：
    uvicorn zfundpilot.api:app --reload --port 8000

所有业务逻辑复用 src/zfundpilot 下的现有模块，
本文件只做 HTTP 入参/出参的序列化与路由编排。
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
from typing import Any

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response, StreamingResponse
from pydantic import BaseModel

from . import ai, analysis, config, data_io, db, fetch_fund, rebalance, risk
from .models import Fund, Transaction

app = FastAPI(title="ZFundPilot API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# 认证
# ---------------------------------------------------------------------------
def _create_token() -> str:
    """生成签名 token（HMAC + 过期时间）。"""
    payload = json.dumps({"exp": int(time.time()) + config.AUTH_TOKEN_MAX_AGE})
    payload_bytes = payload.encode()
    sig = hmac.new(config.AUTH_SECRET.encode(), payload_bytes, hashlib.sha256).digest()
    return base64.urlsafe_b64encode(payload_bytes + b"." + sig).decode()


def _verify_token(token: str) -> bool:
    """校验 token 签名与有效期。"""
    try:
        decoded = base64.urlsafe_b64decode(token.encode())
        payload_bytes, sig = decoded.rsplit(b".", 1)
        expected = hmac.new(config.AUTH_SECRET.encode(), payload_bytes, hashlib.sha256).digest()
        if not hmac.compare_digest(sig, expected):
            return False
        payload = json.loads(payload_bytes)
        return payload["exp"] > time.time()
    except Exception:
        return False


class LoginRequest(BaseModel):
    password: str


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str


@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    """所有 /api/* 请求需要认证（/api/auth/login 和 /api/auth/status 除外）。未设置密码时跳过。"""
    if not config.AUTH_ENABLED:
        return await call_next(request)

    path = request.url.path
    # 静态文件（非 /api）和公开认证端点不需要 token
    if not path.startswith("/api") or path in ("/api/auth/login", "/api/auth/status"):
        return await call_next(request)

    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        token = auth_header[7:]
        if _verify_token(token):
            return await call_next(request)

    return JSONResponse(status_code=401, content={"detail": "未登录或 token 已过期"})


@app.on_event("startup")
def _startup() -> None:
    db.init_db()


# ---------------------------------------------------------------------------
# 认证端点（无需 token）
# ---------------------------------------------------------------------------
@app.get("/api/auth/status")
def auth_status() -> dict[str, Any]:
    """返回是否需要登录。前端据此决定是否展示登录页。"""
    return {"required": config.AUTH_ENABLED}


@app.post("/api/auth/login")
def auth_login(body: LoginRequest) -> dict[str, Any]:
    """验证密码，返回 token。"""
    if not config.AUTH_ENABLED:
        return {"ok": True, "token": "", "message": "未设置密码，无需登录"}
    if not config.verify_password(body.password, config.AUTH_PASSWORD_HASH):
        raise HTTPException(401, "密码错误")
    return {"ok": True, "token": _create_token(), "message": "登录成功"}


@app.post("/api/auth/change-password")
def change_password(body: ChangePasswordRequest) -> dict[str, Any]:
    """修改密码（需已登录 + 当前密码验证）。"""
    if not config.AUTH_ENABLED:
        raise HTTPException(400, "未启用密码认证")
    if not config.verify_password(body.current_password, config.AUTH_PASSWORD_HASH):
        raise HTTPException(401, "当前密码错误")
    if len(body.new_password) < 6:
        raise HTTPException(400, "新密码至少 6 位")
    config.update_password(body.new_password)
    return {"ok": True, "message": "密码已修改，所有设备需要重新登录"}


# ---------------------------------------------------------------------------
# AI 投顾配置 & 对话
# ---------------------------------------------------------------------------
class AIConfigUpdate(BaseModel):
    base_url: str
    api_key: str = ""
    model: str
    web_search: bool = True


class ChatRequest(BaseModel):
    messages: list[dict[str, str]]


@app.get("/api/settings/ai")
def get_ai_config() -> dict[str, Any]:
    """返回 AI 配置（不返回明文 API Key）。"""
    return {
        "base_url": config.AI_BASE_URL,
        "model": config.AI_MODEL,
        "has_key": bool(config.AI_API_KEY),
        "web_search": config.AI_WEB_SEARCH,
    }


@app.put("/api/settings/ai")
def update_ai_config(body: AIConfigUpdate) -> dict[str, Any]:
    """保存 AI 配置。api_key 为空时保留原值。"""
    api_key = body.api_key if body.api_key else config.AI_API_KEY
    config.update_ai_config(body.base_url, api_key, body.model, body.web_search)
    return {"ok": True}


@app.get("/api/ai/usage")
def get_ai_usage() -> dict[str, Any]:
    """返回 AI token 用量统计（今日、累计、最近 20 条明细）。"""
    return db.get_ai_usage_stats()


@app.get("/api/ai/system-prompt")
def get_system_prompt(include_context: bool = True) -> dict[str, Any]:
    """构建并返回系统提示。前端在新对话首条消息时取一次，整个对话复用。"""
    return {"system_prompt": ai.build_system_prompt(include_context=include_context)}


@app.post("/api/ai/test")
def test_ai_connection() -> dict[str, Any]:
    """测试当前 AI 配置是否可用。"""
    return ai.test_connection()


@app.get("/api/ai/usage/daily")
def get_ai_usage_daily(days: int = 7) -> list[dict[str, Any]]:
    """返回最近 N 天每日 token 用量。"""
    return db.get_ai_usage_daily(days)


@app.post("/api/ai/chat")
async def ai_chat(body: ChatRequest):
    """AI 投顾对话（SSE 流式）。前端已携带 system 消息时跳过重建持仓上下文。"""
    has_system = any(m.get("role") == "system" for m in body.messages)
    context = ai.build_portfolio_context() if not has_system else ""

    async def generate():
        try:
            async for chunk in ai.chat_stream(body.messages, context):
                yield f"data: {chunk}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'error': str(e)})}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")


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
def get_transactions(fund_code: str | None = None) -> list[dict[str, Any]]:
    if fund_code:
        return [t.to_dict() for t in db.get_transactions(fund_code)]
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
        raise HTTPException(400, "交易信息不完整")
    tx_id = db.add_transaction(tx)
    if not db.get_latest_nav(body.fund_code):
        fetch_fund.update_fund_nav(body.fund_code)
    analysis.clear_analysis_cache()
    return {"id": tx_id, **tx.to_dict()}


@app.put("/api/transactions/{tx_id}")
def update_transaction(tx_id: int, body: TransactionCreate) -> dict[str, Any]:
    _ensure_fund_exists(body.fund_code)
    tx = Transaction(
        id=tx_id,
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
        raise HTTPException(400, "交易信息不完整")
    db.update_transaction(tx)
    if not db.get_latest_nav(body.fund_code):
        fetch_fund.update_fund_nav(body.fund_code)
    analysis.clear_analysis_cache()
    return {"ok": True, **tx.to_dict()}


@app.delete("/api/transactions/{tx_id}")
def delete_transaction(tx_id: int) -> dict[str, bool]:
    db.delete_transaction(tx_id)
    analysis.clear_analysis_cache()
    return {"ok": True}


@app.delete("/api/transactions")
def delete_all_transactions() -> dict[str, bool]:
    db.delete_all_transactions()
    analysis.clear_analysis_cache()
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
    analysis.clear_analysis_cache()
    return {"ok": True}


@app.post("/api/sectors/reset")
def reset_sectors() -> dict[str, int]:
    funds = db.get_funds()
    count = 0
    for f in funds:
        if not f.fund_name:
            continue
        new_sector = fetch_fund._guess_sector(f.fund_name)
        if new_sector != f.sector:
            db.update_fund_sector(f.fund_code, new_sector)
            fetch_fund.save_sector_mapping(f.fund_code, new_sector)
            count += 1
    analysis.clear_analysis_cache()
    return {"reset": count}


# ---------------------------------------------------------------------------
# 费率查询
# ---------------------------------------------------------------------------
@app.get("/api/funds/{code}/fee-rates")
def get_fund_fee_rates(code: str) -> dict[str, Any]:
    """返回基金的申购/赎回费率表。"""
    rates = fetch_fund.fetch_fund_fee_rates(code)
    return {
        "ok": rates.ok,
        "fund_code": rates.fund_code,
        "message": rates.message,
        "purchase": [
            {"min_amount": t.min_amount, "max_amount": t.max_amount,
             "rate": t.rate, "is_fixed": t.is_fixed,
             "fixed_fee": t.fixed_fee, "label": t.label}
            for t in (rates.purchase or [])
        ],
        "redemption": [
            {"min_days": t.min_days, "max_days": t.max_days, "rate": t.rate}
            for t in (rates.redemption or [])
        ],
        "management_fee": rates.management_fee,
        "custodian_fee": rates.custodian_fee,
        "sales_fee": rates.sales_fee,
    }


class CalcFeeQuery(BaseModel):
    action: str = "buy"
    amount: float | None = None
    shares: float | None = None
    date: str = ""


@app.get("/api/funds/{code}/calc-fee")
def calc_fund_fee(code: str, action: str = "buy",
                  amount: float | None = None,
                  shares: float | None = None,
                  date: str = "") -> dict[str, Any]:
    """根据交易参数计算手续费。

    - 买入：根据买入金额匹配申购费率
    - 卖出：FIFO 匹配买入批次计算赎回费率
    """
    code = code.strip()
    if not code:
        raise HTTPException(400, "基金代码不能为空")

    if action == "buy":
        amt = amount or 0
        if amt <= 0:
            return {"fee": 0, "rate": 0, "label": "金额为空", "lots": None}
        result = fetch_fund.calc_purchase_fee(code, amt)
    elif action == "sell":
        sh = shares or 0
        if sh <= 0:
            return {"fee": 0, "rate": 0, "label": "份额为空", "lots": None}
        if not date:
            return {"fee": 0, "rate": 0, "label": "日期为空", "lots": None}
        result = fetch_fund.calc_redemption_fee(code, date, sh)
    else:
        return {"fee": 0, "rate": 0, "label": "不支持的操作", "lots": None}

    return {
        "fee": result.fee,
        "rate": result.rate,
        "label": result.label,
        "lots": result.lots,
    }


# ---------------------------------------------------------------------------
# 净值
# ---------------------------------------------------------------------------
@app.post("/api/nav/update")
def update_nav() -> list[dict[str, Any]]:
    positions = analysis.calculate_positions()
    codes = [p.fund_code for p in positions if p.is_open]
    results = fetch_fund.update_all_holdings_nav(codes=codes)
    _backfill_transaction_navs()
    analysis.clear_analysis_cache()
    return [r.__dict__ for r in results]


def _backfill_transaction_navs() -> int:
    """回填缺失净值的交易记录。净值更新后自动调用。

    查找 nav IS NULL 的交易，按日期查净值，补全 nav 并计算缺失的份额/金额。
    现金分红的 nav 是每份分红金额（非基金净值），不自动回填。
    """
    txs = db.get_transactions_without_nav()
    count = 0
    for tx in txs:
        if tx.action == "dividend":
            continue  # 分红的 nav 含义不同，不自动回填
        nav_point = db.get_nav_on_or_after(tx.fund_code, tx.date)
        if not nav_point:
            continue
        tx.nav = float(nav_point["nav"])
        tx.normalize()
        db.update_transaction(tx)
        count += 1
    return count


@app.get("/api/nav/{code}")
def get_nav_history(code: str, date: str | None = None) -> list[dict[str, Any]]:
    if date:
        row = db.get_nav_on_or_after(code, date)
        if row:
            return [dict(row)]
        if not db.get_latest_nav(code):
            fetch_fund.update_fund_nav(code)
            row = db.get_nav_on_or_after(code, date)
            if row:
                return [dict(row)]
        return []
    rows = db.get_nav_history(code)
    if not rows and not db.get_latest_nav(code):
        fetch_fund.update_fund_nav(code)
        rows = db.get_nav_history(code)
    return [dict(r) for r in rows]


@app.get("/api/nav/latest")
def get_latest_navs() -> list[dict[str, Any]]:
    """返回所有基金的基础信息 + 最新净值（单次查询，前端无需合并）。"""
    funds = db.get_funds()
    result = []
    for f in funds:
        latest = db.get_latest_nav(f.fund_code)
        result.append({
            "fund_code": f.fund_code,
            "fund_name": f.fund_name,
            "fund_type": f.fund_type,
            "sector": f.sector,
            "date": latest["date"] if latest else None,
            "nav": float(latest["nav"]) if latest else None,
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


@app.get("/api/portfolio/channel-pnl")
def get_channel_pnl() -> list[dict[str, Any]]:
    return analysis.build_channel_daily_pnl()


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
    new_codes = {t.fund_code for t in body.transactions}
    for code in new_codes:
        if not db.get_latest_nav(code):
            fetch_fund.update_fund_nav(code)
    analysis.clear_analysis_cache()
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


# ---------------------------------------------------------------------------
# 偏好设置（多设备同步）
# ---------------------------------------------------------------------------

class PreferencesBody(BaseModel):
    channels: str = ""
    channel_colors: str = ""
    color_theme: str = ""


class KeywordMapsBody(BaseModel):
    type_custom: str = "[]"
    sector_custom: str = "[]"


@app.get("/api/keyword-maps")
def get_keyword_maps() -> dict:
    """返回默认 + 自定义关键词映射（类型/板块）。"""
    return fetch_fund.get_keyword_maps()


@app.put("/api/keyword-maps")
def save_keyword_maps(body: KeywordMapsBody) -> dict[str, bool]:
    """保存自定义关键词映射。"""
    db.upsert_preference("type_keywords_custom", body.type_custom)
    db.upsert_preference("sector_keywords_custom", body.sector_custom)
    return {"ok": True}


@app.get("/api/preferences")
def get_preferences() -> dict[str, str]:
    """返回所有偏好设置。前端负责 JSON 序列化/反序列化。"""
    return db.get_all_preferences()


@app.put("/api/preferences")
def save_preferences(body: PreferencesBody) -> dict[str, bool]:
    """保存偏好设置（购买渠道 + 渠道颜色）。空值不覆盖。"""
    if body.channels:
        db.upsert_preference("channels", body.channels)
    if body.channel_colors:
        db.upsert_preference("channel_colors", body.channel_colors)
    if body.color_theme:
        db.upsert_preference("color_theme", body.color_theme)
    analysis.clear_analysis_cache()
    return {"ok": True}


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
