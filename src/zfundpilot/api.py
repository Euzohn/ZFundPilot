"""FastAPI REST API 层。

启动：
    uvicorn zfundpilot.api:app --reload --port 8000

所有业务逻辑复用 src/zfundpilot 下的现有模块，
本文件只做 HTTP 入参/出参的序列化与路由编排。
"""
from __future__ import annotations

import base64
import contextlib
import hashlib
import hmac
import ipaddress
import json
import logging
import os
import re
import threading
import time
import urllib.parse
from dataclasses import replace
from datetime import datetime
from typing import Annotated, Any, Literal

from fastapi import FastAPI, File, HTTPException, Query, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from . import __version__ as APP_VERSION
from . import (
    ai,
    analysis,
    auto_invest,
    backtest,
    compare,
    config,
    data_io,
    db,
    fetch_estimate,
    fetch_fund,
    fund_filter,
    rebalance,
    risk,
    scheduler,
)
from .models import ACTIONS, Fund, Transaction
from .nav_update_state import nav_update_lock as _nav_update_lock
from .nav_update_state import nav_update_state as _nav_update_state

logger = logging.getLogger(__name__)


@contextlib.asynccontextmanager
async def _lifespan(app: FastAPI):
    """应用生命周期：startup 初始化 DB + 调度器，shutdown 清理。"""
    db.init_db()
    # 一次性修复历史 T+1 交易的错误净值回填
    if db.get_preference("t1_nav_fix_done") is None:
        try:
            fixed = analysis.recalculate_t1_transactions()
        except Exception:
            logger.exception("T+1 净值回填修复异常，跳过")
            fixed = None
        if fixed:
            print(f"[T+1 NAV FIX] 修复 {len(fixed)} 笔交易:")
            for f in fixed:
                print(f"  tx#{f['tx_id']} {f['fund_code']} {f['date']}  "
                      f"nav {f['old_nav']:.4f}→{f['new_nav']:.4f}  "
                      f"shares {f['old_shares']:.2f}→{f['new_shares']:.2f}")
            db.log_audit("t1_nav_fix", detail={"fixed": fixed, "count": len(fixed)})
            logger.info("修复了 %d 笔 T+1 交易的净值回填", len(fixed))
        db.upsert_preference("t1_nav_fix_done", "1")
    scheduler.init_scheduler()
    yield
    scheduler.shutdown_scheduler()


app = FastAPI(title="ZFundPilot API", version="0.21.0", lifespan=_lifespan)

# ---------------------------------------------------------------------------
# 登录速率限制（in-memory，单 uvicorn worker）
# ---------------------------------------------------------------------------
_LOGIN_ATTEMPTS: dict[str, list[float]] = {}
_LOGIN_LOCKED_UNTIL: dict[str, float] = {}
_LOGIN_WINDOW = config.LOGIN_WINDOW
_LOGIN_MAX_FAILURES = config.LOGIN_MAX_FAILURES
_LOGIN_LOCKOUT = config.LOGIN_LOCKOUT
_LOGIN_SWEEP_COUNTER = 0  # 用于控制 sweep 频率


def _get_client_ip(request: Request) -> str:
    """安全获取客户端 IP。

    仅在 request.client.host 命中 TRUSTED_PROXIES 时读取 X-Forwarded-For 头，
    否则直接用 request.client.host（防止客户端伪造 IP 绕过限流）。
    """
    client_host = request.client.host if request.client else "unknown"
    try:
        addr = ipaddress.IPv4Address(client_host)
    except ipaddress.AddressValueError:
        return client_host
    if any(addr in net for net in config.TRUSTED_PROXIES):
        xff = request.headers.get("x-forwarded-for", "")
        if xff:
            return xff.split(",")[0].strip()
    return client_host


def _check_rate_limit(ip: str) -> tuple[bool, int]:
    """检查 IP 是否超出登录失败限制。

    返回 (允许尝试, 剩余锁定秒数)。
    """
    now = time.time()
    lock_expiry = _LOGIN_LOCKED_UNTIL.get(ip, 0)
    if now < lock_expiry:
        return False, int(lock_expiry - now)
    if lock_expiry:
        _LOGIN_LOCKED_UNTIL.pop(ip, None)
        _LOGIN_ATTEMPTS.pop(ip, None)
    return True, 0


def _record_failed_login(ip: str) -> None:
    global _LOGIN_SWEEP_COUNTER
    now = time.time()
    _LOGIN_ATTEMPTS.setdefault(ip, []).append(now)
    _LOGIN_ATTEMPTS[ip] = [t for t in _LOGIN_ATTEMPTS[ip] if now - t < _LOGIN_WINDOW]
    if len(_LOGIN_ATTEMPTS[ip]) >= _LOGIN_MAX_FAILURES:
        _LOGIN_LOCKED_UNTIL[ip] = now + _LOGIN_LOCKOUT
    # 定期 sweep 防止字典无界增长
    _LOGIN_SWEEP_COUNTER += 1
    if _LOGIN_SWEEP_COUNTER >= 100 or len(_LOGIN_ATTEMPTS) > 10000:
        _LOGIN_SWEEP_COUNTER = 0
        _sweep_login_attempts()


def _clear_login_attempts(ip: str) -> None:
    _LOGIN_ATTEMPTS.pop(ip, None)
    _LOGIN_LOCKED_UNTIL.pop(ip, None)


def _sweep_login_attempts() -> None:
    """清理过期的登录记录，防止字典无界增长。"""
    now = time.time()
    expired_ips = [
        ip for ip, lock in list(_LOGIN_LOCKED_UNTIL.items())
        if now >= lock
    ]
    for ip in expired_ips:
        _LOGIN_LOCKED_UNTIL.pop(ip, None)
        _LOGIN_ATTEMPTS.pop(ip, None)
    # 同时清理已过期的尝试记录（即使未被锁定过，窗口过期也清理）
    for ip in list(_LOGIN_ATTEMPTS):
        _LOGIN_ATTEMPTS[ip] = [
            t for t in _LOGIN_ATTEMPTS[ip] if now - t < _LOGIN_WINDOW
        ]
        if not _LOGIN_ATTEMPTS[ip]:
            _LOGIN_ATTEMPTS.pop(ip, None)

# ---------------------------------------------------------------------------
# 端点速率限制（in-memory，单 uvicorn worker）
# ---------------------------------------------------------------------------
_REQ_LOGS: dict[str, list[float]] = {}
_REQ_SWEEP_COUNTER = 0
_REQ_SWEEP_EVERY = 100
_REQ_MAX_SIZE = 10000

_ENDPOINT_LIMITS: dict[str, tuple[int, int]] = {
    "/api/ai/chat":            (20, 60),
    "/api/ai/parse-screenshot": (20, 60),
    "/api/funds/compare":      (60, 60),
    "/api/backtest/dca":       (60, 60),
    "/api/csv/import":         (30, 60),
    "/api/portfolio/industry-exposure": (60, 60),
}

_DOMAIN_LIMITS: dict[str, tuple[int, int]] = {
    "ai":  (20, 60),
    "csv": (30, 60),
}


def _sweep_req_logs() -> None:
    now = time.time()
    expired = [k for k, ts in _REQ_LOGS.items()
               if not ts or now - ts[-1] > 600]
    for k in expired:
        _REQ_LOGS.pop(k, None)


def _check_endpoint_rate_limit(request: Request, path: str) -> tuple[bool, int]:
    global _REQ_SWEEP_COUNTER
    _REQ_SWEEP_COUNTER += 1
    if _REQ_SWEEP_COUNTER >= _REQ_SWEEP_EVERY or len(_REQ_LOGS) > _REQ_MAX_SIZE:
        _REQ_SWEEP_COUNTER = 0
        _sweep_req_logs()

    limits = _ENDPOINT_LIMITS.get(path)
    if not limits:
        for prefix, lim in _DOMAIN_LIMITS.items():
            if path.startswith(f"/api/{prefix}/"):
                limits = lim
                break
    if not limits:
        return True, 0

    ip = _get_client_ip(request)
    now = time.time()
    key = f"{ip}:{path}"
    timestamps = _REQ_LOGS.setdefault(key, [])
    window = limits[1]
    timestamps[:] = [t for t in timestamps if now - t < window]
    if len(timestamps) >= limits[0]:
        retry_after = int(timestamps[0] + window - now) + 1
        return False, retry_after
    timestamps.append(now)
    return True, 0


@app.middleware("http")
async def endpoint_rate_limit_middleware(request: Request, call_next):
    path = request.url.path
    if not path.startswith("/api") or path in ("/api/auth/login", "/api/auth/status"):
        return await call_next(request)
    allowed, retry_after = _check_endpoint_rate_limit(request, path)
    if not allowed:
        return JSONResponse(
            status_code=429,
            content={"detail": f"请求过于频繁，请 {retry_after} 秒后再试",
                     "retry_after": retry_after},
            headers={"Retry-After": str(retry_after)},
        )
    return await call_next(request)

app.add_middleware(
    CORSMiddleware,
    allow_origins=config.CORS_ORIGINS,
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
        logger.debug("token 校验失败", exc_info=True)
        return False


class LoginRequest(BaseModel):
    username: str
    password: str


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str


class ChangeUsernameRequest(BaseModel):
    current_password: str
    new_username: str


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


# ---------------------------------------------------------------------------
# 认证端点（无需 token）
# ---------------------------------------------------------------------------
@app.get("/api/auth/status")
def auth_status() -> dict[str, Any]:
    """返回是否需要登录。前端据此决定是否展示登录页。"""
    return {"required": config.AUTH_ENABLED, "version": APP_VERSION}


@app.get("/api/auth/me")
def auth_me(request: Request) -> dict[str, Any]:
    """返回当前登录用户信息（需 token 认证）。"""
    return {"username": config.AUTH_USERNAME}


@app.post("/api/auth/login")
def auth_login(request: Request, body: LoginRequest) -> dict[str, Any]:
    """验证用户名 + 密码，返回 token。"""
    if not config.AUTH_ENABLED:
        return {"ok": True, "token": "", "message": "未设置密码，无需登录"}

    ip = _get_client_ip(request)
    allowed, retry_after = _check_rate_limit(ip)
    if not allowed:
        db.log_audit("login_failed", ip=ip, username=body.username,
                      detail={"reason": "rate_limited", "retry_after": retry_after})
        return JSONResponse(
            status_code=429,
            content={"detail": f"尝试次数过多，请 {retry_after} 秒后再试",
                     "retry_after": retry_after},
        )

    if body.username != config.AUTH_USERNAME:
        _record_failed_login(ip)
        db.log_audit("login_failed", ip=ip, username=body.username,
                      detail={"reason": "wrong_username"})
        raise HTTPException(401, "用户名或密码错误")

    if not config.verify_password(body.password, config.AUTH_PASSWORD_HASH):
        _record_failed_login(ip)
        db.log_audit("login_failed", ip=ip, username=body.username,
                      detail={"reason": "wrong_password"})
        raise HTTPException(401, "用户名或密码错误")

    _clear_login_attempts(ip)
    try:
        db.log_audit("login_success", ip=ip, username=body.username)
    except Exception:
        logger.exception("记录登录成功审计日志失败")

    # 检测旧 SHA-256 hash，无感升级为 bcrypt
    if not config.AUTH_PASSWORD_HASH.startswith("$2b$"):
        config.migrate_password_hash(body.password)
        logger.info("用户 %s 密码哈希自动升级为 bcrypt", body.username)

    return {"ok": True, "token": _create_token(), "message": "登录成功"}


@app.post("/api/auth/change-password")
def change_password(request: Request, body: ChangePasswordRequest) -> dict[str, Any]:
    """修改密码（需已登录 + 当前密码验证）。"""
    if not config.AUTH_ENABLED:
        raise HTTPException(400, "未启用密码认证")
    if not config.verify_password(body.current_password, config.AUTH_PASSWORD_HASH):
        raise HTTPException(401, "当前密码错误")
    if len(body.new_password) < 6:
        raise HTTPException(400, "新密码至少 6 位")
    config.update_password(body.new_password)
    db.log_audit("change_password", ip=_get_client_ip(request), username=config.AUTH_USERNAME)
    return {"ok": True, "message": "密码已修改，所有设备需要重新登录"}


@app.post("/api/auth/change-username")
def change_username(request: Request, body: ChangeUsernameRequest) -> dict[str, Any]:
    """修改用户名（需已登录 + 当前密码验证）。"""
    if not config.AUTH_ENABLED:
        raise HTTPException(400, "未启用密码认证")
    if not config.verify_password(body.current_password, config.AUTH_PASSWORD_HASH):
        raise HTTPException(401, "当前密码错误")
    new_username = body.new_username.strip()
    if len(new_username) < 2:
        raise HTTPException(400, "用户名至少 2 位")
    old_username = config.AUTH_USERNAME
    config.update_username(new_username)
    db.log_audit("change_username", ip=_get_client_ip(request),
                  username=old_username,
                  detail={"old_username": old_username, "new_username": new_username})
    return {"ok": True, "message": "用户名已修改，所有设备需要重新登录"}


# ---------------------------------------------------------------------------
# AI 投顾配置 & 对话
# ---------------------------------------------------------------------------
_BLOCKED_TLDS = {".internal", ".localhost"}


def _validate_base_url(v: str) -> str:
    """校验 AI base_url：要求 http/https 协议，拒绝 link-local 地址和危险 TLD。"""
    parsed = urllib.parse.urlparse(v)
    if parsed.scheme not in ("http", "https"):
        raise ValueError("base_url 必须使用 http 或 https 协议")
    hostname = parsed.hostname or ""
    # 拒绝 link-local 地址（云元数据端点 169.254.x.x / fe80::/10）
    try:
        addr = ipaddress.ip_address(hostname)
    except ValueError:
        pass  # hostname 不是 IP，走 TLD 检查
    else:
        if isinstance(addr, ipaddress.IPv4Address) and addr.is_link_local:
            raise ValueError("不允许使用 link-local 地址（169.254.x.x）")
        if isinstance(addr, ipaddress.IPv6Address) and addr.is_link_local:
            raise ValueError("不允许使用 link-local 地址（fe80::/10）")
    # 拒绝危险 TLD
    for tld in _BLOCKED_TLDS:
        if hostname.endswith(tld):
            raise ValueError(f"不允许使用 {tld} 域名")
    return v


class AIConfigUpdate(BaseModel):
    base_url: str
    api_key: str = ""
    model: str
    web_search: bool = True
    custom_prompt: str = ""

    @field_validator("base_url")
    @classmethod
    def validate_base_url(cls, v: str) -> str:
        return _validate_base_url(v)


class VisionConfigUpdate(BaseModel):
    base_url: str
    api_key: str = ""
    model: str

    @field_validator("base_url")
    @classmethod
    def validate_base_url(cls, v: str) -> str:
        return _validate_base_url(v)


class ReconcileItem(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False)

    fund_code: str
    shares: float | None = None
    market_value: float | None = None

    @field_validator("fund_code")
    @classmethod
    def validate_fund_code(cls, v: str) -> str:
        if not re.fullmatch(r"\d{6}", v):
            raise ValueError("fund_code 必须为 6 位数字")
        return v

    @field_validator("shares", "market_value")
    @classmethod
    def validate_non_negative(cls, v: float | None) -> float | None:
        if v is not None and v < 0:
            raise ValueError("不能为负数")
        return v


class ReconcileRequest(BaseModel):
    items: list[ReconcileItem]
    channel: str = ""


class ChatMessage(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False)

    role: Literal["system", "user", "assistant", "tool"]
    content: str

    @field_validator("content")
    @classmethod
    def validate_content(cls, v: str) -> str:
        if len(v) > 20000:
            raise ValueError("单条消息内容不能超过 20000 字符")
        return v


class ChatRequest(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False)

    messages: list[ChatMessage]

    @field_validator("messages")
    @classmethod
    def validate_messages(cls, v: list[ChatMessage]) -> list[ChatMessage]:
        if len(v) > 50:
            raise ValueError("消息数量不能超过 50 条")
        total = sum(len(m.content) for m in v)
        if total > 100000:
            raise ValueError("消息总长度不能超过 100000 字符")
        return v


@app.get("/api/settings/ai")
def get_ai_config() -> dict[str, Any]:
    """返回 AI 配置（不返回明文 API Key）。"""
    return {
        "base_url": config.AI_BASE_URL,
        "model": config.AI_MODEL,
        "has_key": bool(config.AI_API_KEY),
        "web_search": config.AI_WEB_SEARCH,
        "custom_prompt": config.AI_CUSTOM_PROMPT,
    }


@app.put("/api/settings/ai")
def update_ai_config(request: Request, body: AIConfigUpdate) -> dict[str, Any]:
    """保存 AI 配置。api_key 为空时保留原值。"""
    api_key = body.api_key if body.api_key else config.AI_API_KEY
    config.update_ai_config(body.base_url, api_key, body.model, body.web_search, body.custom_prompt)
    db.log_audit("update_ai_config", ip=_get_client_ip(request),
                  username=config.AUTH_USERNAME if config.AUTH_ENABLED else None,
                  detail={"base_url": body.base_url, "model": body.model,
                          "web_search": body.web_search, "has_key": bool(body.api_key)})
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


@app.get("/api/settings/vision")
def get_vision_config() -> dict[str, Any]:
    """返回视觉模型配置（不返回明文 API Key）。"""
    return {
        "base_url": config.AI_VISION_BASE_URL,
        "model": config.AI_VISION_MODEL,
        "has_key": bool(config.AI_VISION_API_KEY),
    }


@app.put("/api/settings/vision")
def update_vision_config(request: Request, body: VisionConfigUpdate) -> dict[str, Any]:
    """保存视觉模型配置。api_key 为空时保留原值。"""
    api_key = body.api_key if body.api_key else config.AI_VISION_API_KEY
    config.update_vision_config(body.base_url, api_key, body.model)
    db.log_audit("update_vision_config", ip=_get_client_ip(request),
                 username=config.AUTH_USERNAME if config.AUTH_ENABLED else None,
                 detail={"base_url": body.base_url, "model": body.model, "has_key": bool(body.api_key)})
    return {"ok": True}


@app.post("/api/ai/vision-test")
def test_vision_connection() -> dict[str, Any]:
    """测试视觉模型是否可用（发 1×1 测试图）。"""
    return ai.test_vision_connection()


_MAX_SCREENSHOT_SIZE = 10 * 1024 * 1024  # 10 MB


@app.post("/api/ai/parse-screenshot")
async def parse_screenshot(file: UploadFile = File(...), mode: str = "transactions", channel_hint: str = "", user_hint: str = "") -> dict[str, Any]:
    """上传截图，视觉模型解析为结构化数据（不落库）。

    mode: "transactions"（交易流水）| "holdings"（持仓对账）
    user_hint: 用户补充说明，追加到视觉模型提示词
    交易模式自动标记已存在的重复交易（is_duplicate=True）。
    """
    size = file.size
    if size is not None and size > _MAX_SCREENSHOT_SIZE:
        raise HTTPException(413, "图片大小不能超过 10MB")
    image = await file.read()
    if len(image) > _MAX_SCREENSHOT_SIZE:
        raise HTTPException(413, "图片大小不能超过 10MB")
    if not image:
        return {"ok": False, "items": [], "error": "图片为空"}
    result = ai.parse_screenshot(image, mode, channel_hint, file.content_type or "", user_hint)
    if result["ok"] and mode == "transactions":
        _mark_duplicates(result["items"])
    return result


def _mark_duplicates(items: list[dict]) -> None:
    """标记重复交易：与已有交易对比 fund_code+action+date+amount/shares。

    判定为重复的条件（全部满足）：
    - fund_code 相同
    - action 相同
    - date 相同（parsed tx 的 date 非空）
    - amount 相近（abs < 0.01）或 shares 相近
    """
    # 收集 items 中需要查询的 (fund_code, action, date) 三元组
    query_triples: set[tuple[str, str, str]] = set()
    for item in items:
        code = str(item.get("fund_code") or "").strip()
        date = item.get("date")
        if not code or not date:
            continue
        action = item.get("action", "")
        query_triples.add((code, action, date))

    if not query_triples:
        for item in items:
            item["is_duplicate"] = False
        return

    # 按 fund_codes / actions / dates 分组，批量查库
    fund_codes = list({triple[0] for triple in query_triples})
    actions = list({triple[1] for triple in query_triples})
    dates = list({triple[2] for triple in query_triples})
    existing = db.get_transactions(fund_codes=fund_codes, actions=actions, dates=dates)

    # 构建查找表：(fund_code, action, date) → [tx]
    lookup: dict[tuple[str, str, str], list] = {}
    for tx in existing:
        lookup.setdefault((tx.fund_code, tx.action, tx.date), []).append(tx)

    for item in items:
        item["is_duplicate"] = False
        code = str(item.get("fund_code") or "").strip()
        date = item.get("date")
        if not code or not date:
            continue
        action = item.get("action", "")
        amount = item.get("amount")
        shares = item.get("shares")
        for tx in lookup.get((code, action, date), []):
            if amount is not None and tx.amount is not None and abs(tx.amount - amount) < 0.01:
                item["is_duplicate"] = True
                break
            if shares is not None and tx.shares is not None and abs(tx.shares - shares) < 0.01:
                item["is_duplicate"] = True
                break


@app.post("/api/ai/reconcile")
def reconcile(body: ReconcileRequest) -> dict[str, Any]:
    """持仓对账：截图持仓 vs 已记录持仓（按渠道），生成差额调整交易建议。"""
    items = [{"fund_code": it.fund_code, "shares": it.shares, "market_value": it.market_value} for it in body.items]
    return analysis.reconcile_holdings(items, body.channel)


@app.get("/api/ai/usage/daily")
def get_ai_usage_daily(days: Annotated[int, Query(ge=1, le=365)] = 7) -> list[dict[str, Any]]:
    """返回最近 N 天每日 token 用量。"""
    return db.get_ai_usage_daily(days)


@app.post("/api/ai/chat")
async def ai_chat(body: ChatRequest):
    """AI 投顾对话（SSE 流式）。前端已携带 system 消息时跳过重建持仓上下文。"""
    has_system = any(m.role == "system" for m in body.messages)
    context = ai.build_portfolio_context() if not has_system else ""
    messages_dicts = [{"role": m.role, "content": m.content} for m in body.messages]

    async def generate():
        try:
            async for chunk in ai.chat_stream(messages_dicts, context):
                yield f"data: {chunk}\n\n"
        except Exception:
            logger.exception("AI 流式对话异常")
            yield f"data: {json.dumps({'error': 'AI 服务暂时不可用'})}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")


# ---------------------------------------------------------------------------
# 请求模型
# ---------------------------------------------------------------------------
class TransactionCreate(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False)

    fund_code: str
    action: str
    date: str
    amount: float | None = None
    shares: float | None = None
    nav: float | None = None
    fee: float = 0.0
    channel: str = ""
    note: str = ""
    is_t1: bool = False
    conversion_id: str = ""

    @field_validator("fund_code")
    @classmethod
    def validate_fund_code(cls, v: str) -> str:
        if not re.fullmatch(r"\d{6}", v):
            raise ValueError("fund_code 必须为 6 位数字")
        return v

    @field_validator("action")
    @classmethod
    def validate_action(cls, v: str) -> str:
        if v not in ACTIONS:
            raise ValueError(f"action 仅支持 {' / '.join(ACTIONS)}")
        return v

    @field_validator("date")
    @classmethod
    def validate_date(cls, v: str) -> str:
        try:
            datetime.strptime(v, "%Y-%m-%d")
        except ValueError:
            raise ValueError("date 格式必须为 YYYY-MM-DD")
        return v

    @field_validator("amount", "shares", "nav", "fee")
    @classmethod
    def validate_non_negative(cls, v: float | None) -> float | None:
        if v is not None and v < 0:
            raise ValueError("不能为负数")
        return v


class ConversionCreate(BaseModel):
    """基金转换请求（卖出转出基金 + 买入转入基金）。"""
    model_config = ConfigDict(allow_inf_nan=False)

    from_code: str
    to_code: str
    date: str
    from_shares: float            # 转出份额
    from_nav: float | None = None # 转出净值（可选，自动补全）
    from_fee: float = 0.0         # 转出赎回费
    to_amount: float | None = None  # 转入金额（T+1 时可为空，从卖出腿自动推导）
    to_nav: float | None = None   # 转入净值（可选，自动补全）
    to_fee: float = 0.0           # 转入申购费
    channel: str = ""
    note: str = ""
    is_t1: bool = False

    @field_validator("from_code", "to_code")
    @classmethod
    def validate_fund_code(cls, v: str) -> str:
        if not re.fullmatch(r"\d{6}", v):
            raise ValueError("fund_code 必须为 6 位数字")
        return v

    @field_validator("date")
    @classmethod
    def validate_date(cls, v: str) -> str:
        try:
            datetime.strptime(v, "%Y-%m-%d")
        except ValueError:
            raise ValueError("date 格式必须为 YYYY-MM-DD")
        return v

    @field_validator("from_shares", "from_nav", "from_fee", "to_amount", "to_nav", "to_fee")
    @classmethod
    def validate_non_negative(cls, v: float | None) -> float | None:
        if v is not None and v < 0:
            raise ValueError("不能为负数")
        return v


class SectorUpdate(BaseModel):
    sector: str


class DividendMethodUpdate(BaseModel):
    method: str  # 'cash' or 'reinvest'


class DividendAlertUpdate(BaseModel):
    status: str  # 'confirmed' or 'ignored'
    tx_id: int | None = None


class DividendAutoCheckBody(BaseModel):
    enabled: bool


class TpSlConfigUpdate(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False)

    enabled: bool | None = None
    take_profit_enabled: bool | None = None
    stop_loss_enabled: bool | None = None
    take_profit: float | None = None
    stop_loss: float | None = None
    reset_ratio: float | None = None

    @field_validator("take_profit", "stop_loss", "reset_ratio")
    @classmethod
    def validate_non_negative(cls, v: float | None) -> float | None:
        if v is not None and v < 0:
            raise ValueError("不能为负数")
        return v


class AlertUpdateBody(BaseModel):
    status: str  # 'confirmed' or 'ignored'


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


@app.get("/api/portfolio/industry-exposure")
def get_industry_exposure() -> dict[str, Any]:
    """跨基金聚合真实行业敞口（基金穿透）。"""
    return analysis.aggregate_industry_exposure().to_dict()


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
def get_transactions(
    fund_code: Annotated[str | None, Query(pattern=r"^\d{6}$")] = None,
) -> list[dict[str, Any]]:
    if fund_code:
        return [t.to_dict() for t in db.get_transactions(fund_code)]
    return [t.to_dict() for t in db.get_transactions_desc()]


@app.post("/api/transactions")
def add_transaction(request: Request, body: TransactionCreate) -> dict[str, Any]:
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
        is_t1=body.is_t1,
        conversion_id=body.conversion_id,
    )
    tx.normalize()
    if not tx.is_valid():
        raise HTTPException(400, "交易信息不完整")
    tx_id = db.add_transaction(tx)
    if not db.get_latest_nav(body.fund_code):
        fetch_fund.update_fund_nav(body.fund_code)
    analysis.clear_analysis_cache()
    db.log_audit("add_transaction", ip=_get_client_ip(request),
                  username=config.AUTH_USERNAME if config.AUTH_ENABLED else None,
                  detail={"tx_id": tx_id, "fund_code": tx.fund_code,
                          "action": tx.action, "date": tx.date,
                          "amount": tx.amount, "shares": tx.shares})
    return {"id": tx_id, **tx.to_dict()}


@app.put("/api/transactions/{tx_id}")
def update_transaction(request: Request, tx_id: int, body: TransactionCreate) -> dict[str, Any]:
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
        is_t1=body.is_t1,
        conversion_id=body.conversion_id,
    )
    tx.normalize()
    if not tx.is_valid():
        raise HTTPException(400, "交易信息不完整")
    db.update_transaction(tx)
    if not db.get_latest_nav(body.fund_code):
        fetch_fund.update_fund_nav(body.fund_code)
    analysis.clear_analysis_cache()
    db.log_audit("update_transaction", ip=_get_client_ip(request),
                  username=config.AUTH_USERNAME if config.AUTH_ENABLED else None,
                  detail={"tx_id": tx_id, "fund_code": tx.fund_code,
                          "action": tx.action, "date": tx.date,
                          "amount": tx.amount, "shares": tx.shares})
    return {"ok": True, **tx.to_dict()}


@app.delete("/api/transactions/{tx_id}")
def delete_transaction(request: Request, tx_id: int) -> dict[str, bool]:
    db.delete_transaction(tx_id)
    analysis.clear_analysis_cache()
    db.log_audit("delete_transaction", ip=_get_client_ip(request),
                  username=config.AUTH_USERNAME if config.AUTH_ENABLED else None,
                  detail={"tx_id": tx_id})
    return {"ok": True}


@app.delete("/api/transactions")
def delete_all_transactions(request: Request) -> dict[str, bool]:
    db.delete_all_transactions()
    analysis.clear_analysis_cache()
    db.log_audit("delete_all_transactions", ip=_get_client_ip(request),
                  username=config.AUTH_USERNAME if config.AUTH_ENABLED else None)
    return {"ok": True}


# ---------------------------------------------------------------------------
# 基金转换
# ---------------------------------------------------------------------------
@app.post("/api/conversions")
def add_conversion(request: Request, body: ConversionCreate) -> dict[str, Any]:
    """基金转换：原子创建卖出（转出基金）+ 买入（转入基金）两条关联交易。"""
    if body.from_code == body.to_code:
        raise HTTPException(400, "转出基金和转入基金不能相同")
    _ensure_fund_exists(body.from_code)
    _ensure_fund_exists(body.to_code)
    from_tx = Transaction(
        fund_code=body.from_code,
        action="sell",
        date=body.date,
        shares=body.from_shares,
        nav=body.from_nav,
        fee=body.from_fee,
        channel=body.channel,
        note=body.note,
        is_t1=body.is_t1,
    )
    to_tx = Transaction(
        fund_code=body.to_code,
        action="buy",
        date=body.date,
        amount=body.to_amount,
        nav=body.to_nav,
        fee=body.to_fee,
        channel=body.channel,
        note=body.note,
        is_t1=body.is_t1,
    )
    from_tx.normalize()
    # 非 T+1 且未填转入金额：从卖出腿推导（卖出净到账 = 转出份额×净值−赎回费）
    if not body.is_t1 and body.to_amount is None and from_tx.amount is not None:
        to_tx.amount = from_tx.amount
    to_tx.normalize()
    if not from_tx.is_valid():
        raise HTTPException(400, "转出信息不完整（需要份额）")
    if not body.is_t1 and not to_tx.is_valid():
        raise HTTPException(400, "转入信息不完整（需要金额或份额）")
    from_id, to_id = db.add_conversion(from_tx, to_tx)
    # 两个基金都可能缺净值，分别补拉
    for code in (body.from_code, body.to_code):
        if not db.get_latest_nav(code):
            fetch_fund.update_fund_nav(code)
    analysis.clear_analysis_cache()
    db.log_audit("add_conversion", ip=_get_client_ip(request),
                  username=config.AUTH_USERNAME if config.AUTH_ENABLED else None,
                  detail={"from_id": from_id, "to_id": to_id,
                          "from_code": body.from_code, "to_code": body.to_code,
                          "date": body.date})
    return {"from_id": from_id, "to_id": to_id,
            "from": {"id": from_id, **from_tx.to_dict()},
            "to": {"id": to_id, **to_tx.to_dict()}}


# ---------------------------------------------------------------------------
# 基金信息
# ---------------------------------------------------------------------------
@app.get("/api/funds")
def get_funds() -> list[dict[str, Any]]:
    return [f.to_dict() for f in db.get_funds()]


class CompareRequest(BaseModel):
    codes: list[str]


class FilterRequest(BaseModel):
    types: list[str] = []
    sectors: list[str] = []
    keyword: str = ""
    limit: int = Field(50, ge=1, le=500)
    offset: int = Field(0, ge=0)
    with_metrics: bool = False


@app.post("/api/funds/filter")
def filter_funds(body: FilterRequest) -> dict[str, Any]:
    """按条件筛选基金候选池。"""
    result = fund_filter.filter_funds(
        types=body.types if body.types else None,
        sectors=body.sectors if body.sectors else None,
        keyword=body.keyword,
        limit=body.limit,
        offset=body.offset,
        with_metrics=body.with_metrics,
    )
    return result.__dict__


@app.post("/api/funds/compare")
def compare_funds(body: CompareRequest) -> dict[str, Any]:
    """对比多只基金。"""
    result = compare.compare_funds(body.codes)
    return result.__dict__


class WatchlistRequest(BaseModel):
    code: str
    note: str = ""
    group_name: str = ""


class WatchlistGroupRequest(BaseModel):
    group_name: str = ""


@app.post("/api/watchlist")
def add_to_watchlist(request: Request, body: WatchlistRequest) -> dict[str, Any]:
    code = body.code.strip()
    if not code:
        raise HTTPException(400, "基金代码不能为空")
    meta = fetch_fund.fetch_fund_meta(code)
    if not meta.ok:
        raise HTTPException(400, meta.message or f"基金 {code} 不存在")
    db.upsert_fund(Fund(code, meta.fund_name, meta.fund_type, meta.sector, meta.tracking_index))
    fetch_fund.save_sector_mapping(code, meta.sector)
    db.add_to_watchlist(code, body.note, body.group_name)
    db.log_audit("watchlist_add", ip=_get_client_ip(request), detail={"code": code, "group_name": body.group_name})
    return {"ok": True, "code": code}


@app.get("/api/watchlist")
def get_watchlist() -> list[dict]:
    return db.get_watchlist()


@app.put("/api/watchlist/{code}/group")
def update_watchlist_group(request: Request, code: str, body: WatchlistGroupRequest) -> dict[str, Any]:
    db.update_watchlist_group(code, body.group_name)
    db.log_audit("watchlist_group", ip=_get_client_ip(request), detail={"code": code, "group_name": body.group_name})
    return {"ok": True, "code": code}


@app.delete("/api/watchlist/{code}")
def remove_from_watchlist(request: Request, code: str) -> dict[str, Any]:
    db.remove_from_watchlist(code)
    db.log_audit("watchlist_remove", ip=_get_client_ip(request), detail={"code": code})
    return {"ok": True, "code": code}


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
        db.upsert_fund(Fund(code, meta.fund_name, meta.fund_type, meta.sector, meta.tracking_index))
        fetch_fund.save_sector_mapping(code, meta.sector)
    return meta.__dict__


@app.put("/api/funds/{code}/sector")
def update_sector(code: str, body: SectorUpdate) -> dict[str, bool]:
    db.update_fund_sector(code, body.sector)
    fetch_fund.save_sector_mapping(code, body.sector)
    analysis.clear_analysis_cache()
    return {"ok": True}


@app.put("/api/funds/{code}/dividend-method")
def update_dividend_method(code: str, body: DividendMethodUpdate, request: Request) -> dict[str, bool]:
    if body.method not in ("cash", "reinvest"):
        raise HTTPException(400, "method must be 'cash' or 'reinvest'")
    db.update_fund_dividend_method(code, body.method)
    db.log_audit("update_dividend_method", ip=_get_client_ip(request), detail={"code": code, "method": body.method})
    return {"ok": True}


@app.get("/api/dividends/check")
def check_dividends(request: Request) -> list[dict]:
    """检查持仓基金的未记录分红事件。

    用 def 而非 async def：内部用 ThreadPoolExecutor + AkShare 同步阻塞，
    async def 会卡住事件循环。FastAPI 对 def 端点自动放到线程池执行。
    """
    from . import fetch_dividend
    events = fetch_dividend.check_dividends()
    db.log_audit("dividend_check", ip=_get_client_ip(request), detail={"found": len(events)})
    return [
        {
            "fund_code": ev.fund_code,
            "fund_name": ev.fund_name,
            "record_date": ev.record_date,
            "ex_date": ev.ex_date,
            "per_share": ev.per_share,
            "pay_date": ev.pay_date,
            "held_shares": ev.held_shares,
            "estimated_amount": ev.estimated_amount,
            "dividend_method": ev.dividend_method,
        }
        for ev in events
    ]


@app.get("/api/dividends/alerts")
def get_dividend_alerts(status: str | None = None) -> list[dict]:
    """获取分红提醒列表。status=pending/confirmed/ignored，默认全部。"""
    return db.get_dividend_alerts(status)


@app.get("/api/dividends/alerts/count")
def get_pending_alert_count() -> dict[str, int]:
    """返回 pending 分红提醒数量（仅 dividend 类型，向后兼容）。"""
    return {"count": db.get_pending_alert_count("dividend")}


@app.put("/api/dividends/alerts/{alert_id}")
def update_dividend_alert(alert_id: int, body: DividendAlertUpdate,
                          request: Request) -> dict[str, bool]:
    """更新分红提醒状态（confirmed / ignored）。"""
    if body.status not in ("confirmed", "ignored"):
        raise HTTPException(400, "status must be 'confirmed' or 'ignored'")
    fields: dict = {"status": body.status,
                    "resolved_at": datetime.now(config.TIMEZONE).isoformat()}
    if body.tx_id is not None:
        fields["tx_id"] = body.tx_id
    db.update_dividend_alert(alert_id, **fields)
    db.log_audit("dividend_alert_update", ip=_get_client_ip(request),
                 detail={"id": alert_id, "status": body.status,
                         "tx_id": body.tx_id})
    return {"ok": True}


@app.delete("/api/dividends/alerts/{alert_id}")
def delete_dividend_alert_route(alert_id: int, request: Request) -> dict[str, bool]:
    """删除一条分红提醒（误报等场景）。"""
    if not db.delete_dividend_alert(alert_id):
        raise HTTPException(404, "Alert not found")
    db.log_audit("dividend_alert_delete", ip=_get_client_ip(request),
                 detail={"id": alert_id})
    return {"ok": True}


@app.post("/api/dividends/scan")
def scan_dividends(request: Request) -> dict[str, Any]:
    """手动触发分红扫描，新发现的存入 dividend_alerts 表。

    与 GET /check 区分：scan 持久化到 alerts 表，check 只返回不存储。
    """
    from . import fetch_dividend
    events = fetch_dividend.check_dividends()
    new_count = 0
    for ev in events:
        if not db.dividend_alert_exists(ev.fund_code, ev.ex_date):
            db.add_dividend_alert({
                "fund_code": ev.fund_code,
                "fund_name": ev.fund_name,
                "record_date": ev.record_date,
                "ex_date": ev.ex_date,
                "per_share": ev.per_share,
                "pay_date": ev.pay_date,
                "held_shares": ev.held_shares,
                "estimated_amount": ev.estimated_amount,
                "dividend_method": ev.dividend_method,
            })
            new_count += 1
    db.log_audit("dividend_scan", ip=_get_client_ip(request),
                 detail={"found": len(events), "new": new_count,
                         "cleaned": fetch_dividend._last_cleanup_count})
    return {"found": len(events), "new": new_count,
            "cleaned": fetch_dividend._last_cleanup_count}


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
        new_idx = fetch_fund._guess_tracking_index(f.fund_name, f.fund_type)
        if new_idx != f.tracking_index:
            db.update_fund_tracking_index(f.fund_code, new_idx)
            count += 1
    analysis.clear_analysis_cache()
    return {"reset": count}


# ---------------------------------------------------------------------------
# 实时估值（AkShare fund_value_estimation_em）
# ---------------------------------------------------------------------------

def _index_fallback(estimates: list, merged: dict[str, dict]) -> None:
    """对 AkShare 无数据且无 DB override 的指数型基金，用跟踪指数/ETF 实时涨跌估算。

    直接修改 estimates 列表中的 FundEstimate 对象。
    """
    today_str = datetime.now(config.TIMEZONE).strftime("%Y-%m-%d")
    pending: list[tuple[int, str, str]] = []  # (index in estimates, fund_code, tracking_index)
    keywords: set[str] = set()

    for i, est in enumerate(estimates):
        if est.ok:
            continue
        info = merged.get(est.fund_code, {})
        # 当日净值已入库的由 DB override 处理，跳过
        if info.get("latest_date") == today_str:
            continue
        idx_kw = info.get("tracking_index", "")
        if not idx_kw:
            continue
        pending.append((i, est.fund_code, idx_kw))
        keywords.add(idx_kw)

    if not pending:
        return

    quotes = fetch_estimate.fetch_index_quotes(list(keywords))
    now_str = datetime.now(config.TIMEZONE).strftime("%Y-%m-%d %H:%M")

    for i, code, idx_kw in pending:
        change_pct = quotes.get(idx_kw)
        if change_pct is None:
            continue
        latest_nav = db.get_latest_nav(code)
        if not latest_nav:
            continue
        prev_nav = float(latest_nav["nav"])
        prev_date = str(latest_nav["date"])
        est = estimates[i]
        estimates[i] = replace(
            est,
            dwjz=prev_nav,
            jzrq=prev_date,
            gsz=round(prev_nav * (1 + change_pct / 100), 4),
            gszzl=round(change_pct, 2),
            gztime=now_str,
            ok=True,
            code="index_estimate",
            message="指数估值",
        )


@app.get("/api/estimate")
def get_estimates() -> dict[str, Any]:
    """批量获取所有持仓基金的实时估值 + 组合汇总。"""
    positions = analysis.calculate_positions()
    merged: dict[str, dict] = {}
    for p in positions:
        if not p.is_open:
            continue
        m = merged.setdefault(p.fund_code, {
            "code": p.fund_code, "name": p.fund_name,
            "shares": 0.0, "latest_date": None,
            "tracking_index": p.tracking_index,
        })
        m["shares"] += p.held_shares
        if p.latest_date and (not m["latest_date"] or p.latest_date > m["latest_date"]):
            m["latest_date"] = p.latest_date

    estimates = fetch_estimate.fetch_estimates(list(merged.keys()))

    # 指数估值兜底：对 AkShare 无数据且无 DB override 的指数型基金，
    # 用跟踪指数/ETF 实时涨跌估算
    _index_fallback(estimates, merged)

    funds: list[dict[str, Any]] = []
    total_est_pnl = 0.0
    total_prev_value = 0.0
    latest_gztime = ""
    today_str = datetime.now(config.TIMEZONE).strftime("%Y-%m-%d")
    for idx, est in enumerate(estimates):
        info = merged.get(est.fund_code, {})
        shares = info.get("shares", 0)

        # DB 数据优先：当日净值已入库则覆盖 AkShare 数据，与基金详情页一致
        db_override = False
        if info.get("latest_date") == today_str:
            latest_nav = db.get_latest_nav(est.fund_code)
            prev_nav = db.get_prev_nav(est.fund_code)
            if latest_nav and prev_nav:
                # 用 replace 生成新对象写回，避免污染缓存中的共享引用
                new_dwjz = float(prev_nav["nav"])
                new_gsz = float(latest_nav["nav"])
                new_gszzl = round((new_gsz - new_dwjz) / new_dwjz * 100, 2) if new_dwjz else 0
                est = replace(est, dwjz=new_dwjz, gsz=new_gsz, gszzl=new_gszzl, ok=False)
                estimates[idx] = est
                db_override = True

        if est.ok:
            # 盘中估算：用 gszzl 百分比计算 pnl，确保与前端显示符号一致
            est_pnl = round(shares * est.dwjz * est.gszzl / 100, 2) if est.dwjz else 0
            prev_value = round(shares * est.dwjz, 2)
            total_est_pnl += est_pnl
            total_prev_value += prev_value
            if est.gztime > latest_gztime:
                latest_gztime = est.gztime
        else:
            # 已公布净值（DB 或 AkShare 数据）
            if est.gsz and est.dwjz:
                if db_override:
                    # DB 数据：直接用精确净值差计算，避免 gszzl 四舍五入误差
                    est_pnl = round(shares * (est.gsz - est.dwjz), 2)
                else:
                    # AkShare 数据：用 gszzl 百分比计算，避免 FOF/QDII 符号不一致
                    est_pnl = round(shares * est.dwjz * est.gszzl / 100, 2) if est.dwjz else 0
                prev_value = round(shares * est.dwjz, 2)
                total_est_pnl += est_pnl
                total_prev_value += prev_value
            else:
                est = replace(est, gszzl=0)
                est_pnl = 0
                prev_value = 0
        funds.append({
            "fund_code": est.fund_code,
            "fund_name": est.fund_name or info.get("name", est.fund_code),
            "held_shares": shares,
            "dwjz": est.dwjz,
            "gsz": est.gsz,
            "gszzl": est.gszzl,
            "gztime": est.gztime,
            "estimated_pnl": est_pnl,
            "prev_value": prev_value,
            "ok": est.ok,
            "message": est.message,
        })

    return {
        "funds": funds,
        "total_estimated_pnl": round(total_est_pnl, 2),
        "estimated_return": (total_est_pnl / total_prev_value) if total_prev_value > 0 else 0,
        "gztime": latest_gztime,
    }


@app.get("/api/funds/{code}/estimate")
def get_fund_estimate(code: str) -> dict[str, Any]:
    """获取单只基金的实时估值。"""
    est = fetch_estimate.fetch_estimate(code)
    # 指数估值兜底
    if not est.ok:
        fund = db.get_fund(code)
        if fund and fund.tracking_index:
            today_str = datetime.now(config.TIMEZONE).strftime("%Y-%m-%d")
            latest_nav = db.get_latest_nav(code)
            if latest_nav and str(latest_nav["date"]) != today_str:
                est = fetch_estimate.estimate_from_index(
                    code, fund.fund_name, fund.tracking_index,
                    float(latest_nav["nav"]), str(latest_nav["date"]),
                )
    return {
        "fund_code": est.fund_code,
        "fund_name": est.fund_name,
        "jzrq": est.jzrq,
        "dwjz": est.dwjz,
        "gsz": est.gsz,
        "gszzl": est.gszzl,
        "gztime": est.gztime,
        "ok": est.ok,
        "message": est.message,
    }


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


@app.get("/api/funds/{code}/holdings")
def get_fund_holdings(code: str) -> dict[str, Any]:
    """返回基金重仓股 + 资产配置。"""
    result = fetch_fund.fetch_fund_holdings(code)
    return {
        "ok": result.ok,
        "fund_code": result.fund_code,
        "message": result.message,
        "code": result.code,
        "holdings": [
            {"stock_code": h.stock_code, "stock_name": h.stock_name,
             "weight": h.weight, "shares": h.shares,
             "market_value": h.market_value, "quarter": h.quarter}
            for h in (result.holdings or [])
        ],
        "stock_ratio": result.stock_ratio,
        "bond_ratio": result.bond_ratio,
        "cash_ratio": result.cash_ratio,
        "other_ratio": result.other_ratio,
        "quarter": result.quarter,
    }


@app.get("/api/funds/{code}/industry-allocation")
def get_fund_industry_allocation(code: str) -> dict[str, Any]:
    """返回单基金行业配置（证监会分类）。"""
    result = fetch_fund.fetch_fund_industry_allocation(code)
    return {
        "ok": result.ok,
        "fund_code": result.fund_code,
        "message": result.message,
        "code": result.code,
        "allocations": [
            {"industry": a.industry, "weight": a.weight,
             "market_value": a.market_value, "quarter": a.quarter}
            for a in result.allocations
        ],
        "quarter": result.quarter,
        "stock_ratio": result.stock_ratio,
    }


@app.get("/api/funds/{code}/ranking")
def get_fund_ranking(code: str) -> dict[str, Any]:
    """返回基金同类排名百分位走势。"""
    result = fetch_fund.fetch_fund_ranking(code)
    return {
        "ok": result.ok,
        "fund_code": result.fund_code,
        "message": result.message,
        "code": result.code,
        "points": [
            {"date": p.date, "percentile": p.percentile}
            for p in (result.points or [])
        ],
    }


@app.get("/api/funds/{code}/profile")
def get_fund_profile(code: str) -> dict[str, Any]:
    """返回基金档案（经理 / 规模 / 费率）。"""
    profile = fetch_fund.fetch_fund_profile(code)
    return {
        "ok": profile.ok,
        "fund_code": profile.fund_code,
        "message": profile.message,
        "code": profile.code,
        "manager": profile.manager,
        "manager_career_days": profile.manager_career_days,
        "scale": profile.scale,
        "tenure_return": profile.tenure_return,
        "management_fee": profile.management_fee,
        "custodian_fee": profile.custodian_fee,
        "sales_fee": profile.sales_fee,
        "risk_level": profile.risk_level,
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
            return {"fee": 0, "rate": 0, "label": "金额为空",
                    "code": "amount_empty", "amount": 0, "nav": None, "lots": None}
        result = fetch_fund.calc_purchase_fee(code, amt)
    elif action == "sell":
        sh = shares or 0
        if sh <= 0:
            return {"fee": 0, "rate": 0, "label": "份额为空",
                    "code": "shares_empty", "amount": 0, "nav": None, "lots": None}
        if not date:
            return {"fee": 0, "rate": 0, "label": "日期为空",
                    "code": "date_empty", "amount": 0, "nav": None, "lots": None}
        try:
            result = fetch_fund.calc_redemption_fee(code, date, sh)
        except (ValueError, IndexError) as e:
            raise HTTPException(400, f"日期格式错误: {e}")
    else:
        return {"fee": 0, "rate": 0, "label": "不支持的操作",
                "code": "unsupported_action", "amount": 0, "nav": None, "lots": None}

    return {
        "fee": result.fee,
        "rate": result.rate,
        "label": result.label,
        "code": result.code,
        "amount": result.amount,
        "nav": result.nav,
        "lots": result.lots,
    }


# ---------------------------------------------------------------------------
# 净值
# ---------------------------------------------------------------------------
@app.post("/api/nav/update")
def update_nav(request: Request) -> dict[str, Any]:
    with _nav_update_lock:
        if _nav_update_state["running"]:
            raise HTTPException(409, "净值更新正在进行中")
        _nav_update_state["running"] = True
        _nav_update_state["total"] = 0
        _nav_update_state["done"] = 0
        _nav_update_state["current"] = ""
        _nav_update_state["results"] = []
        _nav_update_state["error"] = ""

    positions = analysis.calculate_positions()
    codes = [p.fund_code for p in positions if p.is_open]
    client_ip = _get_client_ip(request)

    def _run() -> None:
        _nav_update_state["total"] = len(codes)
        try:
            def _progress(i: int, total: int, code: str) -> None:
                _nav_update_state["done"] = i
                _nav_update_state["total"] = total
                _nav_update_state["current"] = code

            results = fetch_fund.update_all_holdings_nav(codes=codes, progress=_progress)
            updated = analysis.backfill_transaction_navs()
            analysis.clear_analysis_cache()
            if updated:
                db.log_audit("nav_backfill", ip=client_ip,
                              detail={"count": len(updated), "items": updated})
            _nav_update_state["results"] = [r.__dict__ for r in results]
        except Exception as exc:  # noqa: BLE001
            _nav_update_state["error"] = str(exc)
        finally:
            with _nav_update_lock:
                _nav_update_state["running"] = False
                _nav_update_state["current"] = ""

    threading.Thread(target=_run, daemon=True).start()
    return {"ok": True, "message": "净值更新已启动", "total": len(codes)}


@app.get("/api/nav/update/status")
def nav_update_status() -> dict[str, Any]:
    return dict(_nav_update_state)


# ---------------------------------------------------------------------------
# 净值
# ---------------------------------------------------------------------------
@app.get("/api/nav/latest")
def get_latest_navs() -> list[dict[str, Any]]:
    """返回所有基金的基础信息 + 最新净值（批量查询，避免 N+1）。"""
    funds = db.get_funds()
    codes = [f.fund_code for f in funds]
    latest_map = db.get_latest_navs_batch(codes)
    return [{
        "fund_code": f.fund_code,
        "fund_name": f.fund_name,
        "fund_type": f.fund_type,
        "sector": f.sector,
        "date": latest_map[f.fund_code]["date"] if f.fund_code in latest_map else None,
        "nav": float(latest_map[f.fund_code]["nav"]) if f.fund_code in latest_map else None,
    } for f in funds]


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


# ---------------------------------------------------------------------------
# 组合曲线 & 风险 & 建议
# ---------------------------------------------------------------------------
@app.get("/api/portfolio/curve")
def get_portfolio_curve() -> list[dict[str, Any]]:
    curve = analysis.build_portfolio_curve()
    if curve.empty:
        return []
    return curve.to_dict(orient="records")


# 基准指数代码 → 名称（从 config 导入，scheduler 共用）
BENCHMARK_INDICES = config.BENCHMARK_INDICES


@app.get("/api/portfolio/benchmark")
def get_portfolio_benchmark(indices: str = "") -> list[dict[str, Any]]:
    """获取基准指数累计收益率序列，与组合曲线日期对齐。

    Args:
        indices: 逗号分隔的指数代码，如 "000300,000001,399006"

    Returns:
        [{date: "2025-01-01", "000300": 0.05, "000001": 0.03, ...}, ...]
        每个指数的值为累计收益率（close / close_at_start - 1）。
        失败的指数不包含在结果中。
    """
    if not indices:
        return []
    codes = [c.strip() for c in indices.split(",") if c.strip()]
    codes = [c for c in codes if c in BENCHMARK_INDICES]
    if not codes:
        return []

    curve = analysis.build_portfolio_curve()
    if curve.empty:
        logger.warning("get_portfolio_benchmark: 组合曲线为空，跳过基准数据")
        return []

    dates = curve["date"].tolist()
    start_date = dates[0]
    end_date = dates[-1]

    series: dict[str, dict[str, float]] = {}
    for code in codes:
        hist = fetch_estimate.fetch_index_history(code, start_date, end_date)
        if not hist:
            continue
        first_close = hist[0]["close"]
        if first_close == 0:
            continue
        # 按日期建 Map，计算累计收益率
        close_map: dict[str, float] = {}
        for pt in hist:
            close_map[pt["date"]] = (pt["close"] / first_close) - 1
        # ffill 到组合曲线的日期轴
        last_val = 0.0
        filled: dict[str, float] = {}
        for d in dates:
            if d in close_map:
                last_val = close_map[d]
            filled[d] = last_val
        series[code] = filled

    if not series:
        logger.warning("get_portfolio_benchmark: 所有指数数据均为空 %s", codes)
        return []

    result = []
    for d in dates:
        row: dict[str, Any] = {"date": d}
        for code in series:
            row[code] = round(series[code][d], 6)
        result.append(row)
    return result


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
            {"level": f.level, "code": f.code, "params": f.params, "title": f.title, "detail": f.detail}
            for f in report.flags
        ],
    }


@app.get("/api/rebalance")
def get_rebalance_advice() -> list[dict[str, Any]]:
    advice = rebalance.generate_advice()
    return [{"code": a.code, "params": a.params, "category": a.category, "text": a.text} for a in advice]


# ---------------------------------------------------------------------------
# 定投回测
# ---------------------------------------------------------------------------
class DcaBacktestRequest(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False)

    fund_codes: list[str]
    start_date: str          # YYYY-MM-DD
    end_date: str            # YYYY-MM-DD
    amount_per_period: float
    cadence: str = "month"   # month / biweek / week
    include_lumpsum: bool = True

    @field_validator("fund_codes")
    @classmethod
    def validate_fund_codes(cls, v: list[str]) -> list[str]:
        if not v:
            raise ValueError("请至少选择一只基金")
        if len(v) > 20:
            raise ValueError("最多选择 20 只基金")
        for code in v:
            if not re.fullmatch(r"\d{6}", code):
                raise ValueError(f"fund_code 必须为 6 位数字: {code}")
        return v

    @field_validator("amount_per_period")
    @classmethod
    def validate_amount(cls, v: float) -> float:
        if v <= 0:
            raise ValueError("每期金额必须大于 0")
        return v

    @field_validator("cadence")
    @classmethod
    def validate_cadence(cls, v: str) -> str:
        if v not in ("month", "biweek", "week"):
            raise ValueError("频率仅支持 month / biweek / week")
        return v

    @field_validator("start_date", "end_date")
    @classmethod
    def validate_date(cls, v: str) -> str:
        try:
            datetime.strptime(v, "%Y-%m-%d")
        except ValueError:
            raise ValueError("日期格式必须为 YYYY-MM-DD")
        return v

    @model_validator(mode="after")
    def validate_date_order(self) -> DcaBacktestRequest:
        if self.start_date >= self.end_date:
            raise ValueError("起始日期必须早于结束日期")
        return self


@app.post("/api/backtest/dca")
def run_dca_backtest(req: DcaBacktestRequest) -> dict[str, Any]:
    results = backtest.run_dca_backtest(
        fund_codes=req.fund_codes,
        start_date=req.start_date,
        end_date=req.end_date,
        amount_per_period=req.amount_per_period,
        cadence=req.cadence,
        include_lumpsum=req.include_lumpsum,
    )
    return {"results": [r.to_dict() for r in results], "ok": True, "message": ""}


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


@app.get("/api/export/zip")
def export_backup(request: Request) -> Response:
    """全量备份导出（ZIP 含 5 个 CSV：交易/基金/自选/定投/偏好）。"""
    content = data_io.export_backup_zip()
    db.log_audit("export_backup", ip=_get_client_ip(request), detail={})
    date_str = datetime.now(config.TIMEZONE).strftime("%Y%m%d")
    return Response(
        content=content,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="zfundpilot_backup_{date_str}.zip"'},
    )


_MAX_CSV_SIZE = 5 * 1024 * 1024  # 5 MB


@app.post("/api/csv/parse")
async def parse_csv(file: UploadFile = File(...)) -> dict[str, Any]:
    size = file.size
    if size is not None and size > _MAX_CSV_SIZE:
        raise HTTPException(413, "CSV 文件大小不能超过 5MB")
    content = await file.read()
    if len(content) > _MAX_CSV_SIZE:
        raise HTTPException(413, "CSV 文件大小不能超过 5MB")
    txs, errors = data_io.parse_transactions_csv(content)
    return {
        "transactions": [t.to_dict() for t in txs],
        "errors": errors,
    }


@app.post("/api/csv/import")
def confirm_import(request: Request, body: CSVImportConfirm) -> dict[str, Any]:
    if body.clear_existing:
        db.delete_all_transactions()
        db.log_audit("clear_then_import", ip=_get_client_ip(request),
                      username=config.AUTH_USERNAME if config.AUTH_ENABLED else None,
                      detail={"import_count": len(body.transactions)})
    else:
        db.log_audit("csv_import", ip=_get_client_ip(request),
                      username=config.AUTH_USERNAME if config.AUTH_ENABLED else None,
                      detail={"import_count": len(body.transactions)})
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
                        sector: str = "", tracking_index: str = "") -> None:
    fund = db.get_fund(code)
    if fund and fund.fund_name and fund.fund_name != code:
        return
    if not name:
        meta = fetch_fund.fetch_fund_meta(code)
        if meta.ok:
            name, ftype, sector, tracking_index = (
                meta.fund_name, meta.fund_type, meta.sector, meta.tracking_index)
    db.upsert_fund(Fund(code, name or code, ftype, sector, tracking_index))


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


# ---------------------------------------------------------------------------
# 定投计划
# ---------------------------------------------------------------------------
class AutoInvestPlanCreate(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False)

    fund_code: str
    amount: float
    cadence: str
    day_of_week: int | None = None
    day_of_month: int | None = None
    channel: str = ""
    note: str = "定投"

    @field_validator("fund_code")
    @classmethod
    def validate_fund_code(cls, v: str) -> str:
        if not re.fullmatch(r"\d{6}", v):
            raise ValueError("fund_code 必须为 6 位数字")
        return v

    @field_validator("amount")
    @classmethod
    def validate_amount(cls, v: float) -> float:
        if v <= 0:
            raise ValueError("定投金额必须大于 0")
        return v

    @field_validator("cadence")
    @classmethod
    def validate_cadence(cls, v: str) -> str:
        if v not in auto_invest.CADENCES:
            raise ValueError(f"频率仅支持 {' / '.join(auto_invest.CADENCES)}")
        return v

    @model_validator(mode="after")
    def validate_day_fields(self) -> AutoInvestPlanCreate:
        if self.cadence in ("week", "biweek"):
            if self.day_of_week is None:
                raise ValueError("week/biweek 频率需指定 day_of_week")
            if not 0 <= self.day_of_week <= 6:
                raise ValueError("day_of_week 范围 0-6（0=周一）")
        if self.cadence == "month":
            if self.day_of_month is None:
                raise ValueError("month 频率需指定 day_of_month")
            if not 1 <= self.day_of_month <= 31:
                raise ValueError("day_of_month 范围 1-31")
        return self


class AutoInvestPlanToggle(BaseModel):
    enabled: bool


@app.post("/api/auto-invest/plans")
def create_auto_invest_plan(request: Request, body: AutoInvestPlanCreate) -> dict[str, Any]:
    _ensure_fund_exists(body.fund_code)
    plan = {
        "fund_code": body.fund_code,
        "amount": body.amount,
        "cadence": body.cadence,
        "day_of_week": body.day_of_week,
        "day_of_month": body.day_of_month,
        "channel": body.channel,
        "note": body.note,
    }
    plan["next_run"] = auto_invest.calculate_next_run(plan)
    plan_id = db.add_auto_invest_plan(**plan)
    db.log_audit("auto_invest_plan_create", ip=_get_client_ip(request),
                  username=config.AUTH_USERNAME if config.AUTH_ENABLED else None,
                  detail={"plan_id": plan_id, "fund_code": body.fund_code,
                          "cadence": body.cadence, "amount": body.amount})
    return {"id": plan_id, **plan, "next_run": plan["next_run"]}


@app.get("/api/auto-invest/plans")
def list_auto_invest_plans() -> list[dict[str, Any]]:
    plans = db.get_auto_invest_plans()
    funds = {f.fund_code: f.fund_name for f in db.get_funds()}
    for p in plans:
        p["fund_name"] = funds.get(p["fund_code"], "")
    return plans


@app.put("/api/auto-invest/plans/{plan_id}")
def update_auto_invest_plan(request: Request, plan_id: int, body: AutoInvestPlanCreate) -> dict[str, bool]:
    old = db.get_auto_invest_plan(plan_id)
    if not old:
        raise HTTPException(404, "定投计划不存在")
    _ensure_fund_exists(body.fund_code)
    plan = {
        "fund_code": body.fund_code,
        "amount": body.amount,
        "cadence": body.cadence,
        "day_of_week": body.day_of_week,
        "day_of_month": body.day_of_month,
        "channel": body.channel,
        "note": body.note,
    }
    plan["next_run"] = auto_invest.calculate_next_run(plan)
    db.update_auto_invest_plan(plan_id, **plan)
    db.log_audit("auto_invest_plan_update", ip=_get_client_ip(request),
                  username=config.AUTH_USERNAME if config.AUTH_ENABLED else None,
                  detail={"plan_id": plan_id, "fund_code": body.fund_code,
                          "cadence": body.cadence, "amount": body.amount})
    return {"ok": True}


@app.delete("/api/auto-invest/plans/{plan_id}")
def delete_auto_invest_plan(request: Request, plan_id: int) -> dict[str, bool]:
    db.delete_auto_invest_plan(plan_id)
    db.log_audit("auto_invest_plan_delete", ip=_get_client_ip(request),
                  username=config.AUTH_USERNAME if config.AUTH_ENABLED else None,
                  detail={"plan_id": plan_id})
    return {"ok": True}


@app.put("/api/auto-invest/plans/{plan_id}/toggle")
def toggle_auto_invest_plan(request: Request, plan_id: int, body: AutoInvestPlanToggle) -> dict[str, bool]:
    db.update_auto_invest_plan(plan_id, enabled=1 if body.enabled else 0)
    db.log_audit("auto_invest_plan_toggle", ip=_get_client_ip(request),
                  username=config.AUTH_USERNAME if config.AUTH_ENABLED else None,
                  detail={"plan_id": plan_id, "enabled": body.enabled})
    return {"ok": True}


@app.post("/api/auto-invest/plans/{plan_id}/execute")
def execute_auto_invest_plan(request: Request, plan_id: int) -> dict[str, Any]:
    plan = db.get_auto_invest_plan(plan_id)
    if not plan:
        raise HTTPException(404, "定投计划不存在")
    result = auto_invest.execute_plan(plan, manual=True)
    if result.get("skipped"):
        raise HTTPException(409, "该定投计划今日已执行")
    analysis.clear_analysis_cache()
    db.log_audit("auto_invest_execute", ip=_get_client_ip(request),
                  username=config.AUTH_USERNAME if config.AUTH_ENABLED else None,
                  detail={"plan_id": plan_id, "fund_code": plan["fund_code"],
                          "amount": plan["amount"], "tx_id": result.get("tx_id")})
    return {"ok": True, **result}


# ---------------------------------------------------------------------------
# 审计日志
# ---------------------------------------------------------------------------
@app.get("/api/audit")
def get_audit_logs(limit: Annotated[int, Query(ge=1, le=1000)] = 100) -> list[dict]:
    """返回最近 N 条审计日志（需认证）。"""
    return db.fetch_audit_logs(limit)


# ---------------------------------------------------------------------------
# 定时任务
# ---------------------------------------------------------------------------
@app.get("/api/scheduler/status")
def get_scheduler_status() -> dict[str, Any]:
    """返回定时任务状态。"""
    return scheduler.get_status()


class SchedulerToggleBody(BaseModel):
    enabled: bool


@app.put("/api/scheduler/toggle")
def toggle_scheduler(request: Request, body: SchedulerToggleBody) -> dict[str, Any]:
    """启用/暂停定时净值更新。"""
    scheduler.set_enabled(body.enabled)
    db.log_audit("scheduler_toggle", ip=_get_client_ip(request),
                  username=config.AUTH_USERNAME if config.AUTH_ENABLED else None,
                  detail={"enabled": body.enabled})
    return scheduler.get_status()


class SchedulerCronBody(BaseModel):
    cron: str


@app.put("/api/scheduler/cron")
def update_scheduler_cron(request: Request, body: SchedulerCronBody) -> dict[str, Any]:
    """更新定时净值更新的 cron 表达式。"""
    try:
        scheduler.set_cron(body.cron)
    except ValueError as e:
        raise HTTPException(400, f"无效 cron 表达式: {e}")
    db.log_audit("scheduler_cron_change", ip=_get_client_ip(request),
                  username=config.AUTH_USERNAME if config.AUTH_ENABLED else None,
                  detail={"cron": body.cron})
    return scheduler.get_status()


@app.put("/api/dividends/auto-check")
def toggle_dividend_auto_check(request: Request, body: DividendAutoCheckBody) -> dict[str, Any]:
    """启用/暂停分红自动检测。"""
    scheduler.set_dividend_enabled(body.enabled)
    db.log_audit("dividend_auto_check_toggle", ip=_get_client_ip(request),
                 detail={"enabled": body.enabled})
    return scheduler.get_status()


@app.get("/api/alerts/config")
def get_alerts_config() -> dict[str, Any]:
    """获取止盈止损提醒配置。"""
    return db.get_tp_sl_config()


@app.put("/api/alerts/config")
def update_alerts_config(request: Request, body: TpSlConfigUpdate) -> dict[str, Any]:
    """更新止盈止损提醒配置。"""
    updates = {k: v for k, v in body.model_dump().items() if v is not None}
    db.update_tp_sl_config(**updates)
    db.log_audit("tp_sl_config_update", ip=_get_client_ip(request),
                 detail=updates)
    return db.get_tp_sl_config()


@app.get("/api/alerts/count")
def get_alerts_count(type: str | None = None) -> dict[str, int]:
    """返回 pending 提醒数量。type='tp_sl' 只返回止盈止损，默认全部。"""
    if type == "tp_sl":
        return {"count": db.get_pending_tp_sl_alert_count()}
    return {"count": db.get_pending_alert_count()}


@app.get("/api/alerts")
def get_alerts(type: str | None = None, status: str | None = None) -> list[dict]:
    """获取提醒列表。type='tp_sl' 只返回止盈止损，默认全部。"""
    if type == "tp_sl":
        return db.get_tp_sl_alerts(status)
    if status is None:
        return db.get_dividend_alerts()
    return db.get_dividend_alerts(status)


@app.put("/api/alerts/{alert_id}")
def update_alert(alert_id: int, request: Request, body: AlertUpdateBody) -> dict[str, bool]:
    """更新提醒状态（confirmed / ignored / pending）。"""
    if body.status not in ("confirmed", "ignored", "pending"):
        raise HTTPException(400, "status must be 'confirmed', 'ignored' or 'pending'")
    fields: dict = {"status": body.status,
                    "resolved_at": None if body.status == "pending" else datetime.now(config.TIMEZONE).isoformat()}
    db.update_dividend_alert(alert_id, **fields)
    db.log_audit("tp_sl_alert_update", ip=_get_client_ip(request),
                 detail={"id": alert_id, "status": body.status})
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
