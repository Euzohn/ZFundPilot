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
from dataclasses import asdict, replace
from datetime import datetime
from typing import Annotated, Any, Literal

from fastapi import (
    Depends,
    FastAPI,
    File,
    Form,
    HTTPException,
    Query,
    Request,
    Security,
    UploadFile,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response, StreamingResponse
from fastapi.security import HTTPBearer
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from . import __version__ as APP_VERSION
from . import (
    agent_tokens,
    ai,
    analysis,
    auto_invest,
    backtest,
    backup_service,
    compare,
    config,
    data_io,
    db,
    fetch_estimate,
    fetch_fund,
    fetch_macro,
    fund_filter,
    health,
    rebalance,
    refresh_service,
    risk,
    scheduler,
    watchlist_service,
)
from .models import (
    ACTION_BUY,
    ACTION_DIVIDEND,
    ACTION_REINVEST,
    ACTION_SELL,
    ACTIONS,
    DataStatus,
    Fund,
    PortfolioSummary,
    Transaction,
)
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
    # 启动时把遗留 queued/running 刷新任务标记 interrupted，避免永久 running。
    interrupted = refresh_service.mark_interrupted_on_startup()
    if interrupted:
        logger.warning("标记 %d 个中断的刷新任务为 interrupted", interrupted)
    yield
    scheduler.shutdown_scheduler()


app = FastAPI(
    title="ZFundPilot API",
    version="0.25.0",
    lifespan=_lifespan,
    openapi_tags=[
        {
            "name": "agent",
            "description": (
                "Agent 只读工具。需要 `Authorization: Bearer <Agent token>`，"
                "按 scope 默认拒绝，响应含 schema_version/tool/generated_at/currency。"
            ),
        },
        {
            "name": "agent-admin",
            "description": "Agent token 管理。需要网页登录 token，未启用密码认证时拒绝。",
        },
    ],
)

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
    "/api/agent/tokens":       (30, 60),
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
    """校验 token 签名与有效期。

    签名固定 32 字节（SHA-256），因此按长度切分，而不是按 "." 分割：
    签名内容可能恰好含 "." 字节，用 rsplit 会把签名截断成误判为无效。
    """
    try:
        decoded = base64.urlsafe_b64decode(token.encode())
        if len(decoded) <= 32:
            return False
        sig = decoded[-32:]
        payload_bytes = decoded[:-32]
        if payload_bytes.endswith(b"."):
            payload_bytes = payload_bytes[:-1]
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
    # Agent 工具端点使用独立 Agent token，由 require_agent_scope 依赖校验；
    # 不经过网页登录 token 中间件（仍默认拒绝：每个工具路由都挂 Agent 鉴权依赖）。
    if path == "/api/agent/tools" or path.startswith("/api/agent/tools/"):
        return await call_next(request)
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
# Agent 只读访问：独立 token 管理 + 默认拒绝的 scope 依赖
# ---------------------------------------------------------------------------
_AGENT_ERROR_RESPONSES = {
    401: {"description": "缺少、无效、已过期或已撤销的 Agent token"},
    403: {"description": "缺少所需 scope，或实例未启用管理员密码认证"},
    429: {"description": "超过按 token + 端点的限流阈值，参见 Retry-After"},
}
_ADMIN_ERROR_RESPONSES = {
    401: {"description": "需要有效的网页登录 token"},
    403: {"description": "未启用管理员密码认证，禁止管理 Agent token"},
}

# 仅用于 OpenAPI 的 securitySchemes / Swagger Authorize；实际校验由中间件与
# _require_admin_auth 完成，故 auto_error=False，避免重复拒绝。
_agent_bearer_scheme = HTTPBearer(
    auto_error=False,
    scheme_name="AgentBearer",
    description="Agent token（zfag_...），仅用于 /api/agent/tools/*",
)
_admin_bearer_scheme = HTTPBearer(
    auto_error=False,
    scheme_name="WebLoginBearer",
    description="网页登录 token，由 /api/auth/login 获取",
)


class AgentTokenCreate(BaseModel):
    """签发 Agent token 的请求体。"""
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=64)
    scopes: list[str] = Field(
        default_factory=lambda: list(agent_tokens.DEFAULT_SCOPES))
    expires_in_days: int | None = Field(
        default=agent_tokens.DEFAULT_TTL_DAYS,
        ge=1, le=agent_tokens.MAX_TTL_DAYS,
    )

    @field_validator("name")
    @classmethod
    def _strip_name(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("名称不能为空")
        return v

    @field_validator("scopes")
    @classmethod
    def _check_scopes(cls, v: list[str]) -> list[str]:
        try:
            return sorted(agent_tokens.normalize_scopes(v))
        except ValueError as exc:
            raise ValueError(str(exc)) from exc


def _require_admin_auth(request: Request) -> None:
    """Agent token 管理端点要求已启用并已通过网页登录认证。

    不依赖中间件顺序：即使将来为 Agent 路由放宽中间件，管理端点仍自行校验
    HMAC 网页 token。未启用密码认证时一律拒绝，避免无密码模式匿名管理 token。
    """
    if not config.AUTH_ENABLED:
        raise HTTPException(
            status_code=403,
            detail="需先启用管理员密码认证，Agent token 不支持无密码模式",
        )
    header = request.headers.get("Authorization", "")
    if not header.startswith("Bearer ") or not _verify_token(header[7:]):
        raise HTTPException(status_code=401, detail="需要管理员登录")


@app.get("/api/agent/tokens", tags=["agent-admin"],
         summary="列出 Agent token 元数据",
         responses=_ADMIN_ERROR_RESPONSES,
         dependencies=[Security(_admin_bearer_scheme)])
def list_agent_tokens(request: Request) -> dict[str, Any]:
    """列出 Agent token 元数据（不含明文与摘要）。"""
    _require_admin_auth(request)
    tokens = db.list_agent_tokens()
    for token in tokens:
        token["active"] = agent_tokens.is_active(token)
    return {"tokens": tokens, "scopes": sorted(agent_tokens.ALLOWED_SCOPES)}


@app.post("/api/agent/tokens", tags=["agent-admin"],
          summary="签发 Agent token（明文仅返回一次）",
          responses=_ADMIN_ERROR_RESPONSES,
          dependencies=[Security(_admin_bearer_scheme)])
def create_agent_token(body: AgentTokenCreate, request: Request) -> dict[str, Any]:
    """签发 Agent token；明文仅本次响应返回。"""
    _require_admin_auth(request)
    ip = _get_client_ip(request)
    try:
        plaintext, info = agent_tokens.issue_token(
            body.name, body.scopes, body.expires_in_days)
    except agent_tokens.AgentTokenError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    db.log_audit(
        "agent_token_created", ip=ip, username=config.AUTH_USERNAME,
        detail={"token_id": info["id"], "name": info["name"],
                "token_prefix": info["token_prefix"], "scopes": info["scopes"],
                "expires_at": info["expires_at"]},
    )
    return {
        "token": plaintext,
        "token_info": info,
        "message": "请立即保存该 token；服务端仅存摘要，之后无法再次查看明文",
    }


@app.delete("/api/agent/tokens/{token_id}", tags=["agent-admin"],
            summary="撤销 Agent token（幂等）",
            responses=_ADMIN_ERROR_RESPONSES,
            dependencies=[Security(_admin_bearer_scheme)])
def revoke_agent_token(token_id: int, request: Request) -> dict[str, Any]:
    """撤销 Agent token（幂等：重复撤销返回 already_revoked）。"""
    _require_admin_auth(request)
    ip = _get_client_ip(request)
    info = db.get_agent_token(token_id)
    if info is None:
        raise HTTPException(status_code=404, detail="Agent token 不存在")
    revoked = db.revoke_agent_token(token_id)
    if revoked:
        db.log_audit(
            "agent_token_revoked", ip=ip, username=config.AUTH_USERNAME,
            detail={"token_id": token_id, "name": info.get("name"),
                    "token_prefix": info.get("token_prefix")},
        )
    return {"ok": True, "already_revoked": not revoked,
            "token_info": db.get_agent_token(token_id)}


# --- Agent 请求鉴权依赖（供后续工具端点使用）-------------------------------
_AGENT_REQ_LOGS: dict[str, list[float]] = {}
_AGENT_SWEEP_COUNTER = 0
_AGENT_RATE_WINDOW = 60
_AGENT_RATE_MAX = 120  # 每 token 每端点每分钟（默认）
# 较重端点使用更低限额；键为路由模板，与 _agent_endpoint_key 一致。
_AGENT_ROUTE_RATE_MAX: dict[str, int] = {
    "/api/agent/tools/search": 60,
    "/api/agent/tools/screen": 20,
    "/api/agent/tools/backtest/dca": 20,
    "/api/agent/tools/benchmark": 20,
    "/api/agent/tools/industry-exposure": 20,
    # 写端点独立计数，避免与同路径的 GET 读取共用额度。
    "POST /api/agent/tools/watchlist": 30,
    "PATCH /api/agent/tools/watchlist/{code}": 30,
    "DELETE /api/agent/tools/watchlist/{code}": 30,
    # 刷新创建较重（联网抓取），任务状态查询轻量走默认额度。
    "POST /api/agent/tools/refresh": 10,
}


def _agent_rate_max_for(endpoint_key: str) -> int:
    """返回指定端点的每分钟限额；未单独配置时用默认值。

    键可以是 ``METHOD 路由模板``，也兼容旧的无方法路径。
    """
    if endpoint_key in _AGENT_ROUTE_RATE_MAX:
        return _AGENT_ROUTE_RATE_MAX[endpoint_key]
    path = endpoint_key.split(" ", 1)[-1]
    return _AGENT_ROUTE_RATE_MAX.get(path, _AGENT_RATE_MAX)


def _agent_endpoint_key(request: Request) -> str:
    """返回 ``方法 + 路由模板``，避免路径参数或读写方法分裂/混用限流桶。

    例如 ``/api/agent/tools/funds/005827`` 与 ``.../000001`` 必须共用
    ``/api/agent/tools/funds/{code}`` 这一个桶，否则枚举基金代码可绕过限流；
    同一路径的 GET 与写方法也各自计数，防止列表读取吃掉写入额度。
    """
    route = request.scope.get("route")
    path = getattr(route, "path", None) or request.url.path
    return f"{request.method} {path}"


def _check_agent_rate_limit(token_id: int, path: str) -> tuple[bool, int]:
    """按 token + 端点做轻量限流，防止单 token 拖垮服务。"""
    global _AGENT_SWEEP_COUNTER
    _AGENT_SWEEP_COUNTER += 1
    now = time.time()
    if _AGENT_SWEEP_COUNTER >= 200 or len(_AGENT_REQ_LOGS) > 10000:
        _AGENT_SWEEP_COUNTER = 0
        for key in [k for k, ts in _AGENT_REQ_LOGS.items()
                    if not ts or now - ts[-1] > 2 * _AGENT_RATE_WINDOW]:
            _AGENT_REQ_LOGS.pop(key, None)
    key = f"{token_id}:{path}"
    timestamps = _AGENT_REQ_LOGS.setdefault(key, [])
    timestamps[:] = [t for t in timestamps if now - t < _AGENT_RATE_WINDOW]
    if len(timestamps) >= _agent_rate_max_for(path):
        return False, int(timestamps[0] + _AGENT_RATE_WINDOW - now) + 1
    timestamps.append(now)
    return True, 0


def _extract_agent_bearer(request: Request) -> str:
    """从 Authorization: Bearer 中取明文 token；缺失时返回空串。"""
    header = request.headers.get("Authorization", "")
    return header[7:].strip() if header.startswith("Bearer ") else ""


def _authenticate_agent_token(request: Request) -> agent_tokens.AgentTokenContext:
    """校验 Agent Bearer token 本身（不含 scope）；失败写审计并抛 401/403。"""
    plaintext = _extract_agent_bearer(request)
    try:
        return agent_tokens.authenticate(plaintext)
    except agent_tokens.AgentTokenError as exc:
        db.log_audit(
            "agent_auth_failed", ip=_get_client_ip(request),
            detail={"path": request.url.path, "reason": exc.reason,
                    "token_prefix": plaintext[:agent_tokens.PREFIX_DISPLAY_LEN]},
        )
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc


def require_agent_scope(required_scope: str | None):
    """构造 FastAPI 依赖：校验 Agent token 是否具备所需 scope，默认拒绝。

    ``required_scope=None`` 表示只要求一个有效 Agent token（如能力发现），
    不额外校验 scope；有效性仍由 ``agent_auth_middleware`` 统一保证。
    若依赖被用在中间件未覆盖的路由上，这里会兜底重新校验 token。
    失败语义：无/错误/过期/撤销 token → 401；有效 token 但缺 scope → 403；
    超限 → 429。审计记录 token 前缀与端点，不记录明文或响应内容。
    """
    if required_scope is not None and required_scope not in agent_tokens.ALLOWED_SCOPES:
        raise ValueError(f"未定义的 Agent scope：{required_scope}")

    def _dependency(request: Request) -> agent_tokens.AgentTokenContext:
        ctx = getattr(request.state, "agent_ctx", None)
        if ctx is None:
            ctx = _authenticate_agent_token(request)
        if required_scope is not None and required_scope not in ctx.scopes:
            db.log_audit(
                "agent_auth_failed", ip=_get_client_ip(request),
                detail={"path": request.url.path, "scope": required_scope,
                        "reason": "insufficient_scope",
                        "token_id": ctx.id, "token_prefix": ctx.prefix},
            )
            raise HTTPException(
                status_code=403,
                detail=f"Agent token 缺少权限：{required_scope}",
            )

        allowed, retry_after = _check_agent_rate_limit(
            ctx.id, _agent_endpoint_key(request))
        if not allowed:
            db.log_audit(
                "agent_rate_limited", ip=_get_client_ip(request),
                detail={"path": request.url.path, "token_id": ctx.id,
                        "token_prefix": ctx.prefix, "retry_after": retry_after},
            )
            raise HTTPException(
                status_code=429,
                detail=f"请求过于频繁，请 {retry_after} 秒后再试",
                headers={"Retry-After": str(retry_after)},
            )

        db.log_audit(
            "agent_auth_ok", ip=_get_client_ip(request),
            detail={"path": request.url.path, "token_id": ctx.id,
                    "token_prefix": ctx.prefix,
                    "scope": required_scope or "any"},
        )
        return ctx

    return _dependency


@app.middleware("http")
async def agent_auth_middleware(request: Request, call_next):
    """Agent 工具路由的入口校验：没有有效 Agent token 一律拒绝。

    结构性默认拒绝：即使某条工具路由漏挂 scope 依赖，也无法匿名访问。
    """
    path = request.url.path
    if not (path == "/api/agent/tools" or path.startswith("/api/agent/tools/")):
        return await call_next(request)
    if request.method == "OPTIONS":  # 交由 CORS 中间件处理预检
        return await call_next(request)
    try:
        request.state.agent_ctx = _authenticate_agent_token(request)
    except HTTPException as exc:
        return JSONResponse(status_code=exc.status_code,
                            content={"detail": exc.detail},
                            headers=exc.headers)
    return await call_next(request)


# --- Agent 只读工具（首期 4 个）--------------------------------------------
def _agent_tool_response(tool: str, data: dict[str, Any]) -> dict[str, Any]:
    """统一工具响应包：版本、工具名、生成时间与币种，便于 Agent 稳定解析。"""
    return {
        "schema_version": 1,
        "tool": tool,
        "generated_at": datetime.now(config.TIMEZONE).isoformat(),
        "currency": "CNY",
        "data": data,
    }


@app.get("/api/agent/tools/portfolio-summary", tags=["agent"],
         summary="组合汇总（只读）", responses=_AGENT_ERROR_RESPONSES,
         dependencies=[Security(_agent_bearer_scheme)])
def agent_get_portfolio_summary(
    ctx: Annotated[
        agent_tokens.AgentTokenContext,
        Depends(require_agent_scope(agent_tokens.SCOPE_PORTFOLIO_READ)),
    ],
) -> dict[str, Any]:
    """组合市值、收益、年化与数据截至时间（只读）。

    ``data.as_of_date`` 是各持仓正式净值日期的最大值，不代表所有基金均已更新；
    数据完整性见 ``data.data_status``。
    """
    del ctx
    return _agent_tool_response(
        "get_portfolio_summary", analysis.calculate_summary().to_dict())


@app.get("/api/agent/tools/data-status", tags=["agent"],
         summary="数据状态（只读）", responses=_AGENT_ERROR_RESPONSES,
         dependencies=[Security(_agent_bearer_scheme)])
def agent_get_data_status(
    ctx: Annotated[
        agent_tokens.AgentTokenContext,
        Depends(require_agent_scope(agent_tokens.SCOPE_HEALTH_READ)),
    ],
) -> dict[str, Any]:
    """正式净值缺失/过期与 T+1 待确认交易摘要（只读）。"""
    del ctx
    summary = analysis.calculate_summary()
    status = summary.data_status
    return _agent_tool_response("get_data_status", {
        "as_of_date": summary.as_of_date,
        "as_of_date_semantics": (
            "as_of_date 为各持仓正式净值日期的最大值，不代表所有基金均已更新"
        ),
        "missing_nav_fund_count": status.missing_nav_fund_count,
        "stale_nav_fund_count": status.stale_nav_fund_count,
        "pending_t1_transaction_count": status.pending_t1_transaction_count,
    })


def _agent_health_caveats(status: DataStatus) -> list[str]:
    """把数据状态翻译成体检结论的降级说明，避免 Agent 忽略数据缺口。"""
    caveats: list[str] = []
    if status.missing_nav_fund_count:
        caveats.append(
            f"{status.missing_nav_fund_count} 只基金缺少正式净值，市值与收益评分可能偏低")
    if status.stale_nav_fund_count:
        caveats.append(
            f"{status.stale_nav_fund_count} 只基金的最新正式净值可能已过期")
    if status.pending_t1_transaction_count:
        caveats.append(
            f"{status.pending_t1_transaction_count} 笔 T+1 交易待确认，尚未计入市值")
    return caveats


@app.get("/api/agent/tools/portfolio-health", tags=["agent"],
         summary="组合体检（只读）", responses=_AGENT_ERROR_RESPONSES,
         dependencies=[Security(_agent_bearer_scheme)])
def agent_get_portfolio_health(
    ctx: Annotated[
        agent_tokens.AgentTokenContext,
        Depends(require_agent_scope(agent_tokens.SCOPE_HEALTH_READ)),
    ],
) -> dict[str, Any]:
    """组合四维体检评分、风险提示与结构建议（只读）。

    复用 ``health.build_health_report()``；数据缺口不隐藏，统一放在
    ``data.data_quality.caveats``，评分口径仍为最新正式净值。
    """
    del ctx
    report = health.build_health_report()
    status = report.summary.data_status
    data = report.to_dict()
    data["valuation_basis"] = "latest_formal_nav"
    data["data_quality"] = {
        "as_of_date": report.summary.as_of_date,
        "as_of_date_semantics": (
            "as_of_date 为各持仓正式净值日期的最大值，不代表所有基金均已更新"
        ),
        "missing_nav_fund_count": status.missing_nav_fund_count,
        "stale_nav_fund_count": status.stale_nav_fund_count,
        "pending_t1_transaction_count": status.pending_t1_transaction_count,
        "caveats": _agent_health_caveats(status),
    }
    return _agent_tool_response("get_portfolio_health", data)


@app.get("/api/agent/tools/positions", tags=["agent"],
         summary="持仓列表（只读）", responses=_AGENT_ERROR_RESPONSES,
         dependencies=[Security(_agent_bearer_scheme)])
def agent_list_positions(
    ctx: Annotated[
        agent_tokens.AgentTokenContext,
        Depends(require_agent_scope(agent_tokens.SCOPE_PORTFOLIO_READ)),
    ],
    include_closed: bool = False,
    limit: int = Query(200, ge=1, le=500),
) -> dict[str, Any]:
    """持仓列表（按市值降序，默认仅未清仓），按 (基金, 渠道) 区分。"""
    del ctx
    positions = analysis.calculate_positions(include_closed=include_closed)
    total = len(positions)
    items = [p.to_dict() for p in positions[:limit]]
    return _agent_tool_response("list_positions", {
        "count": len(items),
        "total": total,
        "limit": limit,
        "include_closed": include_closed,
        "valuation_basis": "latest_formal_nav",
        "positions": items,
    })


_RETURN_BASIS_NOTE = (
    "total_return/return_rate 与各周期 return 只基于当前开仓成本与最新正式净值，"
    "不是历史累计收益；已清仓基金的历史已实现盈亏只计入 realized_pnl 与 XIRR。"
)


def _position_counts(positions: list[Any]) -> tuple[int, int]:
    open_count = sum(1 for p in positions if p.is_open)
    return open_count, len(positions) - open_count


def _agent_returns_data(summary: PortfolioSummary) -> dict[str, Any]:
    """组合级收益视图：聚焦累计/年化与分周期收益，与 portfolio-summary 互补。"""
    positions = analysis.calculate_positions(include_closed=True)
    open_count, closed_count = _position_counts(positions)
    return {
        "scope": "portfolio",
        "as_of_date": summary.as_of_date,
        "as_of_date_semantics": (
            "as_of_date 为各持仓正式净值日期的最大值，不代表所有基金均已更新"
        ),
        "valuation_basis": "latest_formal_nav",
        "return_basis": "open_positions_floating",
        "return_basis_note": _RETURN_BASIS_NOTE,
        "realized_pnl_scope": "all_history_including_closed",
        "total_pnl_scope": "unrealized_open_plus_realized_all_history",
        "total_cost": summary.total_cost,
        "total_value": summary.total_value,
        # 完全清仓时没有开仓成本，浮动收益率无定义，返回 null 而不是 0。
        "total_return": (
            summary.total_return if summary.total_cost > 1e-9 else None),
        "annualized_return": summary.annualized_return,
        "total_pnl": summary.total_pnl,
        "unrealized_pnl": summary.unrealized_pnl,
        "realized_pnl": summary.realized_pnl,
        "daily": {"pnl": summary.daily_pnl, "return": summary.daily_return},
        "week": {"pnl": summary.week_pnl, "return": summary.week_return},
        "month": {"pnl": summary.month_pnl, "return": summary.month_return},
        "year": {"pnl": summary.year_pnl, "return": summary.year_return},
        "holding_count": summary.holding_count,
        "open_position_count": open_count,
        "closed_position_count": closed_count,
        "data_quality": _agent_data_quality(summary.data_status),
    }


def _agent_fund_returns_data(code: str) -> dict[str, Any]:
    """单基金收益视图：累计/年化、现金流汇总与各渠道持仓盈亏。

    已实现盈亏与 XIRR 覆盖该基金全部历史流水（含已清仓渠道）；
    ``return_rate`` 只基于当前开仓成本，不能读作历史累计收益。
    """
    fund = db.get_fund(code)
    positions = [
        p for p in analysis.calculate_positions(include_closed=True)
        if p.fund_code == code
    ]
    if not fund and not positions:
        raise HTTPException(status_code=404, detail=f"未找到基金 {code}")

    buy_amount = sell_amount = dividend_amount = 0.0
    pending_t1 = 0
    transactions = db.get_transactions(fund_code=code)
    for tx in transactions:
        tx.normalize()
        if tx.is_t1 and not tx.nav and tx.action != ACTION_DIVIDEND:
            pending_t1 += 1
        if not tx.amount:
            continue
        if tx.action == ACTION_BUY:
            buy_amount += tx.amount
        elif tx.action == ACTION_SELL:
            sell_amount += tx.amount
        elif tx.action in (ACTION_DIVIDEND, ACTION_REINVEST):
            dividend_amount += tx.amount

    open_positions = [p for p in positions if p.is_open]
    closed_positions = [p for p in positions if not p.is_open]
    total_value = sum(p.market_value for p in open_positions)
    total_cost = sum(p.total_cost for p in open_positions)
    unrealized = sum(p.unrealized_pnl for p in open_positions)
    # 已清仓渠道的已实现收益也要计入，否则完全清仓后 realized_pnl 会错误归零。
    realized = sum(p.realized_pnl for p in positions)
    closed_realized = sum(p.realized_pnl for p in closed_positions)
    latest_date = max(
        (p.latest_date for p in open_positions if p.latest_date), default=None)

    missing_nav_channels = [
        p for p in open_positions
        if p.held_shares > 1e-6 and p.latest_nav is None
    ]
    caveats: list[str] = []
    if missing_nav_channels:
        caveats.append(
            f"{len(missing_nav_channels)} 个持仓渠道缺少正式净值，"
            "市值、浮动收益率与 XIRR 暂不可用")
    if pending_t1:
        caveats.append(f"{pending_t1} 笔 T+1 交易待确认，尚未计入市值")

    return {
        "scope": "fund",
        "fund_code": code,
        "fund_name": fund.fund_name if fund else positions[0].fund_name,
        "valuation_basis": "latest_formal_nav",
        "return_basis": "open_positions_floating",
        "return_basis_note": _RETURN_BASIS_NOTE,
        "realized_pnl_scope": "all_history_including_closed",
        "total_pnl_scope": "unrealized_open_plus_realized_all_history",
        "as_of_date": latest_date,
        "as_of_date_semantics": "as_of_date 为该基金当前开仓的最新正式净值日期",
        "market_value": total_value,
        "total_cost": total_cost,
        "unrealized_pnl": unrealized,
        "realized_pnl": realized,
        "closed_realized_pnl": closed_realized,
        "total_pnl": unrealized + realized,
        # 缺净值时市值按 0 计，直接相除会得到 -100% 的假亏损，故返回 null。
        "return_rate": (
            (total_value / total_cost - 1)
            if total_cost > 1e-9 and not missing_nav_channels else None),
        "annualized_return": (
            None if missing_nav_channels
            else analysis.calculate_fund_xirr(code)),
        "transaction_count": len(transactions),
        "buy_amount": buy_amount,
        "sell_amount": sell_amount,
        "dividend_amount": dividend_amount,
        "open_position_count": len(open_positions),
        "closed_position_count": len(closed_positions),
        "data_quality": {
            "missing_nav_channel_count": len(missing_nav_channels),
            "pending_t1_transaction_count": pending_t1,
            "caveats": caveats,
        },
        "channels": [
            _agent_fund_channel_item(p) for p in positions
        ],
    }


def _agent_fund_channel_item(position: Any) -> dict[str, Any]:
    """单基金渠道明细；已清仓渠道保留，避免历史已实现收益静默消失。"""
    nav_missing = position.held_shares > 1e-6 and position.latest_nav is None
    return {
        "channel": position.channel,
        "is_open": position.is_open,
        "market_value": position.market_value,
        "total_cost": position.total_cost,
        "unrealized_pnl": position.unrealized_pnl,
        "realized_pnl": position.realized_pnl,
        "return_rate": (
            None if nav_missing or not position.is_open
            else position.return_rate),
        "annualized_return": position.annualized_return,
        "latest_date": position.latest_date,
        "nav_missing": nav_missing,
    }


@app.get("/api/agent/tools/returns", tags=["agent"],
         summary="收益视图（只读）",
         responses={**_AGENT_ERROR_RESPONSES,
                    400: {"description": "基金代码必须为 6 位数字"},
                    404: {"description": "基金不存在"}},
         dependencies=[Security(_agent_bearer_scheme)])
def agent_get_returns(
    ctx: Annotated[
        agent_tokens.AgentTokenContext,
        Depends(require_agent_scope(agent_tokens.SCOPE_PORTFOLIO_READ)),
    ],
    fund_code: str | None = Query(
        None, description="可选：单基金代码（6 位数字），省略返回组合级"),
) -> dict[str, Any]:
    """收益视图：默认组合级；传 ``fund_code`` 返回单基金级（只读）。

    组合级复用 ``analysis.calculate_summary()``；单基金级复用
    ``analysis.calculate_fund_xirr()`` 与交易流水汇总。金额口径均为最新正式净值。
    """
    del ctx
    if fund_code is None:
        data = _agent_returns_data(analysis.calculate_summary())
    else:
        if not re.fullmatch(r"\d{6}", fund_code):
            raise HTTPException(status_code=400, detail="基金代码必须为 6 位数字")
        data = _agent_fund_returns_data(fund_code)
    return _agent_tool_response("get_returns", data)


@app.get("/api/agent/tools/funds/compare", tags=["agent"],
         summary="基金对比（只读）",
         responses={**_AGENT_ERROR_RESPONSES,
                    400: {"description": "基金代码列表为空或格式非法（超过 20 只由参数校验返回 422）"}},
         dependencies=[Security(_agent_bearer_scheme)])
def agent_compare_funds(
    ctx: Annotated[
        agent_tokens.AgentTokenContext,
        Depends(require_agent_scope(agent_tokens.SCOPE_FUNDS_READ)),
    ],
    codes: Annotated[list[str], Query(min_length=1, max_length=20)],
    include_nav_series: bool = False,
) -> dict[str, Any]:
    """对比多只基金：收益、风险、费率与相关性（只读）。

    数据包含外部抓取结果，可能较慢或部分基金失败；每只基金以 ``ok``/``message``
    标记。默认不返回 ``nav_series``（体积较大），需要时显式开启。
    """
    del ctx
    cleaned = list(dict.fromkeys(
        c.strip() for c in codes if c and c.strip()))
    if not cleaned:
        raise HTTPException(status_code=400, detail="基金代码列表为空")
    if any(not re.fullmatch(r"\d{6}", c) for c in cleaned):
        raise HTTPException(status_code=400, detail="基金代码必须为 6 位数字")

    result = compare.compare_funds(cleaned)
    data: dict[str, Any] = {
        "ok": result.ok,
        "message": result.message,
        "msg_code": result.msg_code,
        "count": len(result.funds),
        "funds": [asdict(fund) for fund in result.funds],
        "correlations": result.correlations,
        "valuation_basis": "latest_formal_nav",
    }
    if include_nav_series:
        data["nav_series"] = result.nav_series
    return _agent_tool_response("compare_funds", data)


@app.get("/api/agent/tools/funds/{code}", tags=["agent"],
         summary="单基金详情（只读）",
         responses={**_AGENT_ERROR_RESPONSES,
                    400: {"description": "基金代码必须为 6 位数字"},
                    404: {"description": "基金不存在"}},
         dependencies=[Security(_agent_bearer_scheme)])
def agent_get_fund_detail(
    code: str,
    ctx: Annotated[
        agent_tokens.AgentTokenContext,
        Depends(require_agent_scope(agent_tokens.SCOPE_FUNDS_READ)),
    ],
    nav_limit: int = Query(30, ge=1, le=250),
) -> dict[str, Any]:
    """单基金详情：基础信息、最新正式净值、年化、各渠道持仓与近期净值。"""
    del ctx
    if not re.fullmatch(r"\d{6}", code):
        raise HTTPException(status_code=400, detail="基金代码必须为 6 位数字")
    fund = db.get_fund(code)
    if not fund:
        raise HTTPException(status_code=404, detail=f"未找到基金 {code}")

    latest = db.get_latest_nav(code)
    positions = [
        p for p in analysis.calculate_positions(include_closed=False)
        if p.fund_code == code
    ]
    recent = db.get_nav_history(code)[-nav_limit:]
    return _agent_tool_response("get_fund_detail", {
        "fund": fund.to_dict(),
        "valuation_basis": "latest_formal_nav",
        "latest_formal_nav": ({
            "date": latest["date"],
            "nav": latest["nav"],
            "accumulated_nav": latest["accumulated_nav"],
            "source": latest["source"],
        } if latest else None),
        "annualized_return": analysis.calculate_fund_xirr(code),
        "positions": [p.to_dict() for p in positions],
        "recent_nav": [
            {"date": row["date"], "nav": row["nav"],
             "accumulated_nav": row["accumulated_nav"]}
            for row in recent
        ],
    })


# ---------------------------------------------------------------------------
# Agent 只读查询工具（P1.5-A 第 1 批：流水/自选/提醒/计划/能力发现）
# ---------------------------------------------------------------------------
_AGENT_TX_ACTIONS = frozenset(ACTIONS)
_AGENT_NAV_STATUSES = frozenset({"confirmed", "pending_t1", "missing"})
_AGENT_ALERT_STATUSES = frozenset({"pending", "confirmed", "ignored"})
_AGENT_ALERT_TYPES = frozenset({"dividend", "take_profit", "stop_loss", "tp_sl"})
_AGENT_ALERT_FIELDS = (
    "id", "alert_type", "fund_code", "fund_name", "status",
    "triggered_return", "threshold",
    "record_date", "ex_date", "pay_date", "per_share",
    "estimated_amount", "held_shares", "dividend_method",
    "created_at", "resolved_at", "tx_id",
)


def _agent_pagination(limit: int, offset: int, total: int,
                      count: int) -> dict[str, Any]:
    """统一分页块：精确 total + 当前页是否还有更多。"""
    return {
        "limit": limit,
        "offset": offset,
        "total": total,
        "has_more": offset + count < total,
    }


def _agent_validate_date(value: str | None, field: str) -> str | None:
    if value is None:
        return None
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise HTTPException(
            status_code=400, detail=f"{field} 格式必须为 YYYY-MM-DD")
    try:
        datetime.strptime(value, "%Y-%m-%d")
    except ValueError:
        raise HTTPException(
            status_code=400, detail=f"{field} 不是有效日期") from None
    return value


def _agent_fund_name_map() -> dict[str, str]:
    return {f.fund_code: f.fund_name for f in db.get_funds()}


def _agent_tx_nav_status(tx: Transaction) -> str:
    if tx.nav is not None:
        return "confirmed"
    return "pending_t1" if tx.is_t1 else "missing"


def _agent_tx_amount_semantics(action: str) -> str:
    if action == ACTION_BUY:
        return "gross_paid"
    if action == ACTION_SELL:
        return "net_received"
    return "gross"


def _agent_tx_conversion_role(tx: Transaction) -> str:
    if not tx.conversion_id:
        return ""
    if tx.action == ACTION_SELL:
        return "out"
    if tx.action == ACTION_BUY:
        return "in"
    return ""


def _agent_transaction_item(tx: Transaction,
                            fund_name: str | None) -> dict[str, Any]:
    """把 Transaction 序列化为稳定单项，并补充派生字段。"""
    tx.normalize()
    item = tx.to_dict()
    item["fund_name"] = fund_name
    item["nav_status"] = _agent_tx_nav_status(tx)
    item["amount_semantics"] = _agent_tx_amount_semantics(tx.action)
    item["conversion_role"] = _agent_tx_conversion_role(tx)
    return item


def _agent_alert_item(row: dict) -> dict[str, Any]:
    """只返回白名单字段，避免把内部列意外透传给 Agent。"""
    item = {field: row.get(field) for field in _AGENT_ALERT_FIELDS}
    if item["alert_type"] is None:
        item["alert_type"] = "dividend"
    return item


@app.get("/api/agent/tools/transactions", tags=["agent"],
         summary="交易流水列表（只读）",
         responses={**_AGENT_ERROR_RESPONSES,
                    400: {"description": "基金代码、动作、日期或净值状态过滤非法"}},
         dependencies=[Security(_agent_bearer_scheme)])
def agent_list_transactions(
    ctx: Annotated[
        agent_tokens.AgentTokenContext,
        Depends(require_agent_scope(agent_tokens.SCOPE_TRANSACTIONS_READ)),
    ],
    fund_code: str | None = None,
    channel: str | None = None,
    action: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    conversion_id: str | None = None,
    nav_status: str | None = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> dict[str, Any]:
    """交易流水列表（按日期与 id 降序），支持多条件过滤与分页。

    ``amount`` 口径：买入含手续费（``gross_paid``）、卖出扣手续费
    （``net_received``）、分红/再投资为 ``gross``；``nav_status`` 区分
    已确认、T+1 待确认与缺失净值。
    """
    del ctx
    if fund_code is not None and not re.fullmatch(r"\d{6}", fund_code):
        raise HTTPException(status_code=400, detail="基金代码必须为 6 位数字")
    if action is not None and action not in _AGENT_TX_ACTIONS:
        raise HTTPException(
            status_code=400, detail=f"action 仅支持 {' / '.join(ACTIONS)}")
    _agent_validate_date(date_from, "date_from")
    _agent_validate_date(date_to, "date_to")
    if nav_status is not None and nav_status not in _AGENT_NAV_STATUSES:
        raise HTTPException(
            status_code=400,
            detail="nav_status 仅支持 confirmed / pending_t1 / missing")
    if date_from and date_to and date_from > date_to:
        raise HTTPException(status_code=400, detail="date_from 不能晚于 date_to")

    transactions = db.get_transactions(fund_code=fund_code)
    matched: list[Transaction] = []
    for tx in transactions:
        tx.normalize()
        if channel is not None and (tx.channel or "") != channel:
            continue
        if action is not None and tx.action != action:
            continue
        if date_from and tx.date < date_from:
            continue
        if date_to and tx.date > date_to:
            continue
        if conversion_id and tx.conversion_id != conversion_id:
            continue
        if nav_status is not None and _agent_tx_nav_status(tx) != nav_status:
            continue
        matched.append(tx)

    matched.sort(key=lambda t: (t.date or "", t.id or 0), reverse=True)
    total = len(matched)
    page = matched[offset:offset + limit]
    names = _agent_fund_name_map()
    items = [_agent_transaction_item(tx, names.get(tx.fund_code))
             for tx in page]
    return _agent_tool_response("list_transactions", {
        "count": len(items),
        "total": total,
        "pagination": _agent_pagination(limit, offset, total, len(items)),
        "valuation_basis": "latest_formal_nav",
        "transactions": items,
    })


@app.get("/api/agent/tools/transactions/{tx_id}", tags=["agent"],
         summary="单笔交易详情（只读）",
         responses={**_AGENT_ERROR_RESPONSES,
                    404: {"description": "交易不存在"}},
         dependencies=[Security(_agent_bearer_scheme)])
def agent_get_transaction(
    tx_id: int,
    ctx: Annotated[
        agent_tokens.AgentTokenContext,
        Depends(require_agent_scope(agent_tokens.SCOPE_TRANSACTIONS_READ)),
    ],
) -> dict[str, Any]:
    """单笔交易明细，字段与流水列表单项一致。"""
    del ctx
    tx = db.get_transaction(tx_id)
    if tx is None:
        raise HTTPException(status_code=404, detail=f"未找到交易 {tx_id}")
    fund = db.get_fund(tx.fund_code)
    data = _agent_transaction_item(tx, fund.fund_name if fund else None)
    data["valuation_basis"] = "latest_formal_nav"
    return _agent_tool_response("get_transaction", data)


class AgentWatchlistAddRequest(BaseModel):
    """Agent 新增自选请求；不接受名称代替代码，也不接受未知字段。"""

    model_config = ConfigDict(extra="forbid")

    fund_code: str
    note: str = ""
    group_name: str = ""


class AgentWatchlistUpdateRequest(BaseModel):
    """Agent 更新自选请求；只修改显式提供的字段。"""

    model_config = ConfigDict(extra="forbid")

    expected_revision: int
    note: str = ""
    group_name: str = ""


_AGENT_WRITE_ERROR_RESPONSES = {
    **_AGENT_ERROR_RESPONSES,
    409: {"description": "版本冲突、对象不存在/已存在或幂等键冲突"},
    422: {"description": "参数非法或缺少 Idempotency-Key"},
}


def _agent_write_principal(
    ctx: agent_tokens.AgentTokenContext,
) -> watchlist_service.Principal:
    return watchlist_service.Principal(
        "agent_token", str(ctx.id), f"agent:{ctx.prefix}")


def _idempotency_key_header(request: Request) -> str:
    return request.headers.get("Idempotency-Key", "")


def _watchlist_validation_error(
    exc: watchlist_service.WatchlistValidationError,
) -> HTTPException:
    return HTTPException(
        status_code=422,
        detail={"code": "validation_error", "field": exc.field,
                "message": exc.message},
    )


def _watchlist_result_data(result: watchlist_service.WatchlistResult) -> dict:
    """成功结果展开；失败结果映射为 HTTPException。"""
    if not result.ok:
        raise HTTPException(
            status_code=result.http_status,
            detail={"code": result.code, "message": result.message},
        )
    return {
        "ok": True,
        "code": result.code,
        "message": result.message,
        "replayed": result.replayed,
        **result.data,
    }


def _require_agent_write_enabled(
    request: Request, ctx: agent_tokens.AgentTokenContext) -> None:
    """写能力总开关；关闭时连具备 scope 的 token 也不能写入。"""
    if config.AGENT_WRITE_ENABLED:
        return
    db.log_audit(
        "watchlist_write_rejected", ip=_get_client_ip(request),
        detail={"reason": "write_disabled", "token_id": ctx.id,
                "token_prefix": ctx.prefix, "path": request.url.path},
    )
    raise HTTPException(
        status_code=403,
        detail={"code": "write_disabled",
                "message": "Agent 写能力未启用，请联系管理员开启"},
    )


@app.get("/api/agent/tools/watchlist", tags=["agent"],
         summary="自选列表（只读）", responses=_AGENT_ERROR_RESPONSES,
         dependencies=[Security(_agent_bearer_scheme)])
def agent_list_watchlist(
    ctx: Annotated[
        agent_tokens.AgentTokenContext,
        Depends(require_agent_scope(agent_tokens.SCOPE_WATCHLIST_READ)),
    ],
    group_name: str | None = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> dict[str, Any]:
    """自选关注列表（含基金元数据），可按分组过滤。"""
    del ctx
    rows = db.get_watchlist()
    if group_name is not None:
        rows = [r for r in rows if (r.get("group_name") or "") == group_name]
    total = len(rows)
    page = rows[offset:offset + limit]
    return _agent_tool_response("list_watchlist", {
        "count": len(page),
        "total": total,
        "pagination": _agent_pagination(limit, offset, total, len(page)),
        "watchlist": page,
    })


@app.post("/api/agent/tools/watchlist", tags=["agent"],
          summary="新增自选（受控写入）",
          responses=_AGENT_WRITE_ERROR_RESPONSES,
          dependencies=[Security(_agent_bearer_scheme)])
def agent_add_watchlist_item(
    request: Request,
    body: AgentWatchlistAddRequest,
    ctx: Annotated[
        agent_tokens.AgentTokenContext,
        Depends(require_agent_scope(agent_tokens.SCOPE_WATCHLIST_WRITE)),
    ],
) -> dict[str, Any]:
    """新增自选关系；已存在时返回冲突，不覆盖备注与分组。"""
    _require_agent_write_enabled(request, ctx)
    try:
        result = watchlist_service.add_item(
            _agent_write_principal(ctx),
            fund_code=body.fund_code,
            note=body.note,
            group_name=body.group_name,
            idempotency_key=_idempotency_key_header(request),
            ip=_get_client_ip(request),
        )
    except watchlist_service.WatchlistValidationError as exc:
        raise _watchlist_validation_error(exc) from exc
    return _agent_tool_response(
        "add_watchlist_item", _watchlist_result_data(result))


@app.patch("/api/agent/tools/watchlist/{code}", tags=["agent"],
           summary="更新自选（受控写入）",
           responses=_AGENT_WRITE_ERROR_RESPONSES,
           dependencies=[Security(_agent_bearer_scheme)])
def agent_update_watchlist_item(
    request: Request,
    code: str,
    body: AgentWatchlistUpdateRequest,
    ctx: Annotated[
        agent_tokens.AgentTokenContext,
        Depends(require_agent_scope(agent_tokens.SCOPE_WATCHLIST_WRITE)),
    ],
) -> dict[str, Any]:
    """按 revision 更新备注/分组；只修改请求中显式出现的字段。"""
    _require_agent_write_enabled(request, ctx)
    provided = body.model_fields_set
    try:
        result = watchlist_service.update_item(
            _agent_write_principal(ctx),
            fund_code=code,
            expected_revision=body.expected_revision,
            note=body.note if "note" in provided else watchlist_service.UNSET,
            group_name=(
                body.group_name if "group_name" in provided
                else watchlist_service.UNSET
            ),
            idempotency_key=_idempotency_key_header(request),
            ip=_get_client_ip(request),
        )
    except watchlist_service.WatchlistValidationError as exc:
        raise _watchlist_validation_error(exc) from exc
    return _agent_tool_response(
        "update_watchlist_item", _watchlist_result_data(result))


@app.delete("/api/agent/tools/watchlist/{code}", tags=["agent"],
            summary="移除自选（受控写入）",
            responses=_AGENT_WRITE_ERROR_RESPONSES,
            dependencies=[Security(_agent_bearer_scheme)])
def agent_remove_watchlist_item(
    request: Request,
    code: str,
    ctx: Annotated[
        agent_tokens.AgentTokenContext,
        Depends(require_agent_scope(agent_tokens.SCOPE_WATCHLIST_WRITE)),
    ],
    expected_revision: int = Query(..., ge=1),
) -> dict[str, Any]:
    """按 revision 删除自选；删除保留可恢复前值。"""
    _require_agent_write_enabled(request, ctx)
    try:
        result = watchlist_service.remove_item(
            _agent_write_principal(ctx),
            fund_code=code,
            expected_revision=expected_revision,
            idempotency_key=_idempotency_key_header(request),
            ip=_get_client_ip(request),
        )
    except watchlist_service.WatchlistValidationError as exc:
        raise _watchlist_validation_error(exc) from exc
    return _agent_tool_response(
        "remove_watchlist_item", _watchlist_result_data(result))


# ---------------------------------------------------------------------------
# Agent 任务化数据刷新（D：仅净值/元数据，不触碰交易与计划）
# ---------------------------------------------------------------------------
class AgentRefreshRequest(BaseModel):
    """Agent 刷新请求；缺省基金代码时使用当前开仓持仓。"""

    model_config = ConfigDict(extra="forbid")

    fund_codes: list[str] | None = None


def _refresh_validation_error(
    exc: refresh_service.RefreshValidationError,
) -> HTTPException:
    return HTTPException(
        status_code=422,
        detail={"code": "validation_error", "field": exc.field,
                "message": exc.message},
    )


def _agent_refresh_principal(
    ctx: agent_tokens.AgentTokenContext,
) -> refresh_service.Principal:
    return refresh_service.Principal(
        "agent_token", str(ctx.id), f"agent:{ctx.prefix}")


def _refresh_result_data(result: refresh_service.RefreshResult) -> dict:
    if not result.ok:
        detail: dict[str, Any] = {
            "code": result.code, "message": result.message}
        # 保留 busy 时的 current_job_id 等可操作信息，便于客户端轮询。
        detail.update(result.data)
        raise HTTPException(status_code=result.http_status, detail=detail)
    return {
        "ok": True,
        "code": result.code,
        "message": result.message,
        "replayed": result.replayed,
        **result.data,
    }


@app.post("/api/agent/tools/refresh", tags=["agent"],
          summary="启动数据刷新任务（受控写入）",
          responses={**_AGENT_WRITE_ERROR_RESPONSES,
                     202: {"description": "任务已创建，返回 job_id"}},
          status_code=202,
          dependencies=[Security(_agent_bearer_scheme)])
def agent_start_data_refresh(
    request: Request,
    body: AgentRefreshRequest,
    ctx: Annotated[
        agent_tokens.AgentTokenContext,
        Depends(require_agent_scope(agent_tokens.SCOPE_DATA_REFRESH)),
    ],
) -> dict[str, Any]:
    """启动仅净值/元数据刷新；不回填交易净值，不执行定投。"""
    _require_agent_write_enabled(request, ctx)
    try:
        result = refresh_service.start_refresh(
            _agent_refresh_principal(ctx),
            fund_codes=body.fund_codes,
            idempotency_key=_idempotency_key_header(request),
            ip=_get_client_ip(request),
        )
    except refresh_service.RefreshValidationError as exc:
        raise _refresh_validation_error(exc) from exc
    return _agent_tool_response("start_data_refresh", _refresh_result_data(result))


@app.get("/api/agent/tools/refresh/{job_id}", tags=["agent"],
         summary="查询数据刷新任务状态（只读）",
         responses={**_AGENT_ERROR_RESPONSES,
                    404: {"description": "任务不存在或不属于当前 token"}},
         dependencies=[Security(_agent_bearer_scheme)])
def agent_get_refresh_job(
    job_id: int,
    ctx: Annotated[
        agent_tokens.AgentTokenContext,
        Depends(require_agent_scope(agent_tokens.SCOPE_DATA_REFRESH)),
    ],
) -> dict[str, Any]:
    """返回任务进度与结果；仅创建者 token 可读。"""
    try:
        result = refresh_service.get_job_status(
            _agent_refresh_principal(ctx), job_id)
    except refresh_service.RefreshValidationError as exc:
        raise _refresh_validation_error(exc) from exc
    return _agent_tool_response("get_job_status", _refresh_result_data(result))


def _agent_alert_rows(alert_type: str | None,
                      status: str | None) -> list[dict]:
    """按类型合并分红与止盈止损提醒，统一按 id 降序。"""
    if alert_type == "dividend":
        rows = db.get_dividend_alerts(status)
    elif alert_type in ("take_profit", "stop_loss"):
        rows = [r for r in db.get_tp_sl_alerts(status)
                if r.get("alert_type") == alert_type]
    elif alert_type == "tp_sl":
        rows = db.get_tp_sl_alerts(status)
    else:
        rows = db.get_dividend_alerts(status) + db.get_tp_sl_alerts(status)
    rows.sort(key=lambda r: r.get("id") or 0, reverse=True)
    return rows


@app.get("/api/agent/tools/alerts", tags=["agent"],
         summary="提醒列表（只读）",
         responses={**_AGENT_ERROR_RESPONSES,
                    400: {"description": "提醒类型或状态非法"}},
         dependencies=[Security(_agent_bearer_scheme)])
def agent_list_alerts(
    ctx: Annotated[
        agent_tokens.AgentTokenContext,
        Depends(require_agent_scope(agent_tokens.SCOPE_ALERTS_READ)),
    ],
    type: str | None = None,
    status: str | None = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> dict[str, Any]:
    """分红与止盈止损提醒列表。

    ``status`` 是业务处理状态（pending/confirmed/ignored），不是已读标记；
    提醒「已读」尚未实现，不在此接口伪装。
    """
    del ctx
    if type is not None and type not in _AGENT_ALERT_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"type 仅支持 {' / '.join(sorted(_AGENT_ALERT_TYPES))}")
    if status is not None and status not in _AGENT_ALERT_STATUSES:
        raise HTTPException(
            status_code=400,
            detail="status 仅支持 pending / confirmed / ignored")
    rows = _agent_alert_rows(type, status)
    total = len(rows)
    page = [_agent_alert_item(r) for r in rows[offset:offset + limit]]
    return _agent_tool_response("list_alerts", {
        "count": len(page),
        "total": total,
        "pagination": _agent_pagination(limit, offset, total, len(page)),
        "alerts": page,
    })


@app.get("/api/agent/tools/auto-invest-plans", tags=["agent"],
         summary="定投计划列表（只读）", responses=_AGENT_ERROR_RESPONSES,
         dependencies=[Security(_agent_bearer_scheme)])
def agent_list_auto_invest_plans(
    ctx: Annotated[
        agent_tokens.AgentTokenContext,
        Depends(require_agent_scope(agent_tokens.SCOPE_PLANS_READ)),
    ],
    enabled: bool | None = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> dict[str, Any]:
    """定投计划列表，含派生状态；不虚构未持久化的跳过原因。"""
    del ctx
    rows = db.get_auto_invest_plans()
    if enabled is not None:
        rows = [r for r in rows if bool(r.get("enabled")) == enabled]
    names = _agent_fund_name_map()
    today = datetime.now(config.TIMEZONE).date().isoformat()
    items: list[dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        item["enabled"] = bool(item.get("enabled"))
        item["fund_name"] = names.get(item.get("fund_code", ""))
        next_run = item.get("next_run")
        if not item["enabled"]:
            item["status"] = "paused"
        elif next_run and next_run <= today:
            item["status"] = "due"
        else:
            item["status"] = "active"
        items.append(item)
    total = len(items)
    page = items[offset:offset + limit]
    return _agent_tool_response("list_auto_invest_plans", {
        "count": len(page),
        "total": total,
        "pagination": _agent_pagination(limit, offset, total, len(page)),
        "plans": page,
    })


# ---------------------------------------------------------------------------
# Agent 只读查询工具（P1.5-A 第 2 批：组合曲线/基准/风险/行业敞口）
# ---------------------------------------------------------------------------
_AGENT_AS_OF_SEMANTICS = (
    "as_of_date 为各持仓正式净值日期的最大值，不代表所有基金均已更新"
)


def _agent_data_quality(status: DataStatus) -> dict[str, Any]:
    """统一数据质量块：缺口计数 + 降级说明，避免新工具隐藏数据问题。"""
    return {
        "missing_nav_fund_count": status.missing_nav_fund_count,
        "stale_nav_fund_count": status.stale_nav_fund_count,
        "pending_t1_transaction_count": status.pending_t1_transaction_count,
        "caveats": _agent_health_caveats(status),
    }


def _agent_sample_points(points: list[dict[str, Any]],
                         max_points: int) -> list[dict[str, Any]]:
    """等距抽样并保留首尾，控制大响应；点数未超限时原样返回。"""
    total = len(points)
    if total <= max_points:
        return points
    step = (total - 1) / (max_points - 1)
    indices = sorted({int(round(i * step)) for i in range(max_points)})
    return [points[i] for i in indices]


@app.get("/api/agent/tools/portfolio-curve", tags=["agent"],
         summary="组合收益曲线（只读）",
         responses={**_AGENT_ERROR_RESPONSES,
                    400: {"description": "日期格式非法或起止顺序颠倒"}},
         dependencies=[Security(_agent_bearer_scheme)])
def agent_get_portfolio_curve(
    ctx: Annotated[
        agent_tokens.AgentTokenContext,
        Depends(require_agent_scope(agent_tokens.SCOPE_PORTFOLIO_READ)),
    ],
    start_date: str | None = None,
    end_date: str | None = None,
    max_points: int = Query(365, ge=10, le=2000),
) -> dict[str, Any]:
    """组合每日市值/投入/累计收益率曲线（只读）。

    复用 ``analysis.build_portfolio_curve()``；``max_points`` 超限时按等距
    抽样保留首尾。曲线为可视化口径，不用于精确对账。
    """
    del ctx
    _agent_validate_date(start_date, "start_date")
    _agent_validate_date(end_date, "end_date")
    if start_date and end_date and start_date > end_date:
        raise HTTPException(
            status_code=400, detail="start_date 不能晚于 end_date")

    curve = analysis.build_portfolio_curve()
    points: list[dict[str, Any]] = []
    if not curve.empty:
        if start_date:
            curve = curve[curve["date"] >= start_date]
        if end_date:
            curve = curve[curve["date"] <= end_date]
        points = _agent_sample_points(
            curve.to_dict(orient="records"), max_points)

    summary = analysis.calculate_summary()
    return _agent_tool_response("get_portfolio_curve", {
        "as_of_date": summary.as_of_date,
        "as_of_date_semantics": _AGENT_AS_OF_SEMANTICS,
        "valuation_basis": "latest_formal_nav",
        "max_points": max_points,
        "points_count": len(points),
        "points": points,
    })


@app.get("/api/agent/tools/benchmark", tags=["agent"],
         summary="基准对比（只读）",
         responses={**_AGENT_ERROR_RESPONSES,
                    400: {"description": "日期格式非法、起止顺序颠倒或基准代码不受支持"}},
         dependencies=[Security(_agent_bearer_scheme)])
def agent_get_benchmark_comparison(
    ctx: Annotated[
        agent_tokens.AgentTokenContext,
        Depends(require_agent_scope(agent_tokens.SCOPE_PORTFOLIO_READ)),
    ],
    codes: Annotated[list[str], Query(min_length=1, max_length=20)],
    start_date: str | None = None,
    end_date: str | None = None,
) -> dict[str, Any]:
    """基准指数/宏观水位与组合曲线对齐的累计收益率（只读）。

    仅支持 ``COMPARABLE_CODES`` 白名单；累计收益率基期为组合曲线起点，
    ``start_date``/``end_date`` 只截取返回区间。失败代码不出现在 ``points``。
    """
    del ctx
    _agent_validate_date(start_date, "start_date")
    _agent_validate_date(end_date, "end_date")
    if start_date and end_date and start_date > end_date:
        raise HTTPException(
            status_code=400, detail="start_date 不能晚于 end_date")

    cleaned = list(dict.fromkeys(
        c.strip() for c in codes if c and c.strip()))
    if not cleaned:
        raise HTTPException(status_code=400, detail="基准代码列表为空")
    invalid = [c for c in cleaned if c not in COMPARABLE_CODES]
    if invalid:
        raise HTTPException(
            status_code=400,
            detail=f"不支持的基准代码：{', '.join(invalid)}")

    rows = get_portfolio_benchmark(indices=",".join(cleaned))
    if start_date:
        rows = [row for row in rows if row.get("date", "") >= start_date]
    if end_date:
        rows = [row for row in rows if row.get("date", "") <= end_date]

    summary = analysis.calculate_summary()
    return _agent_tool_response("get_benchmark_comparison", {
        "as_of_date": summary.as_of_date,
        "as_of_date_semantics": _AGENT_AS_OF_SEMANTICS,
        "valuation_basis": "latest_formal_nav",
        "codes": cleaned,
        "code_names": {c: COMPARABLE_CODES[c] for c in cleaned},
        "points_count": len(rows),
        "points": rows,
    })


@app.get("/api/agent/tools/risk-report", tags=["agent"],
         summary="风险报告（只读）", responses=_AGENT_ERROR_RESPONSES,
         dependencies=[Security(_agent_bearer_scheme)])
def agent_get_risk_report(
    ctx: Annotated[
        agent_tokens.AgentTokenContext,
        Depends(require_agent_scope(agent_tokens.SCOPE_HEALTH_READ)),
    ],
) -> dict[str, Any]:
    """组合风险指标、结构占比与风险提示（只读）。

    复用 ``risk.build_risk_report()``；``flags`` 同时返回稳定
    ``code``+``params``（供客户端 i18n）与中文 ``title``/``detail``。
    数据缺口统一放在 ``data_quality.caveats``，不隐藏。
    """
    del ctx
    report = risk.build_risk_report()
    summary = analysis.calculate_summary()
    return _agent_tool_response("get_risk_report", {
        "as_of_date": summary.as_of_date,
        "as_of_date_semantics": _AGENT_AS_OF_SEMANTICS,
        "valuation_basis": "latest_formal_nav",
        "max_drawdown": report.max_drawdown,
        "volatility": report.volatility,
        "max_single_weight": report.max_single_weight,
        "max_single_name": report.max_single_name,
        "hhi": report.hhi,
        "equity_weight": report.equity_weight,
        "bond_weight": report.bond_weight,
        "qdii_weight": report.qdii_weight,
        "flags": [asdict(flag) for flag in report.flags],
        "data_quality": _agent_data_quality(summary.data_status),
    })


@app.get("/api/agent/tools/industry-exposure", tags=["agent"],
         summary="行业敞口（只读）", responses=_AGENT_ERROR_RESPONSES,
         dependencies=[Security(_agent_bearer_scheme)])
def agent_get_industry_exposure(
    ctx: Annotated[
        agent_tokens.AgentTokenContext,
        Depends(require_agent_scope(agent_tokens.SCOPE_PORTFOLIO_READ)),
    ],
) -> dict[str, Any]:
    """组合行业穿透敞口（只读）。

    复用 ``analysis.aggregate_industry_exposure()``；行业配置来自外部抓取，
    可能较慢。失败基金进入 ``funds_missing`` 并说明原因，不影响其他基金。
    """
    del ctx
    result = analysis.aggregate_industry_exposure()
    summary = analysis.calculate_summary()
    data = result.to_dict()
    data["as_of_date"] = summary.as_of_date
    data["as_of_date_semantics"] = _AGENT_AS_OF_SEMANTICS
    data["valuation_basis"] = "latest_formal_nav"
    data["data_quality"] = _agent_data_quality(summary.data_status)
    return _agent_tool_response("get_industry_exposure", data)


# ---------------------------------------------------------------------------
# Agent 只读查询工具（P1.5-A 第 3 批：基金检索与筛选）
# ---------------------------------------------------------------------------
_AGENT_FUND_KEYWORD_MAX = 100
_AGENT_FUND_FILTER_MAX = 20


def _agent_fund_keyword(value: str | None, *, required: bool) -> str:
    """清洗检索关键词：去首尾空白、限长；必填时拒绝空值。"""
    keyword = (value or "").strip()
    if not keyword:
        if required:
            raise HTTPException(status_code=400, detail="keyword 不能为空")
        return ""
    if len(keyword) > _AGENT_FUND_KEYWORD_MAX:
        raise HTTPException(
            status_code=400,
            detail=f"keyword 不能超过 {_AGENT_FUND_KEYWORD_MAX} 个字符")
    return keyword


def _agent_fund_filters(values: list[str] | None, allowed: list[str],
                        field: str) -> list[str] | None:
    """去重并校验类型/板块过滤值，拒绝未知值和空值。"""
    if not values:
        return None
    cleaned = list(dict.fromkeys(v.strip() for v in values if v and v.strip()))
    if not cleaned:
        return None
    if len(cleaned) > _AGENT_FUND_FILTER_MAX:
        raise HTTPException(
            status_code=400,
            detail=f"{field} 最多 {_AGENT_FUND_FILTER_MAX} 个")
    invalid = [v for v in cleaned if v not in allowed]
    if invalid:
        raise HTTPException(
            status_code=400,
            detail=f"不支持的 {field}：{', '.join(invalid)}")
    return cleaned


def _agent_fund_brief(item: fund_filter.FundFilterItem) -> dict[str, Any]:
    """检索结果的最小字段集，不触发任何外部指标抓取。"""
    return {"code": item.code, "name": item.name,
            "type": item.type, "sector": item.sector}


def _agent_fund_full(item: fund_filter.FundFilterItem,
                     snapshot: dict | None, status: str) -> dict[str, Any]:
    """筛选结果：基础字段 + 可选指标快照；缺失不补零。"""
    data = _agent_fund_brief(item)
    if snapshot is None:
        data.update({
            "scale": None, "manager": "", "inception_date": "",
            "returns": None, "risk": None, "metrics_status": status,
        })
        return data
    data.update({
        "scale": snapshot.get("scale"),
        "manager": snapshot.get("manager", ""),
        "inception_date": snapshot.get("inception_date", ""),
        "returns": snapshot.get("returns") or {},
        "risk": snapshot.get("risk") or {},
        "metrics_status": status,
    })
    return data


@app.get("/api/agent/tools/search", tags=["agent"],
         summary="基金检索（只读）",
         responses={**_AGENT_ERROR_RESPONSES,
                    400: {"description": "keyword 为空或超长"}},
         dependencies=[Security(_agent_bearer_scheme)])
def agent_search_funds(
    ctx: Annotated[
        agent_tokens.AgentTokenContext,
        Depends(require_agent_scope(agent_tokens.SCOPE_FUNDS_READ)),
    ],
    keyword: Annotated[str, Query(min_length=1)],
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> dict[str, Any]:
    """按名称或代码子串检索基金池（只读，不补指标）。"""
    del ctx
    value = _agent_fund_keyword(keyword, required=True)
    result = fund_filter.filter_funds(
        keyword=value, limit=limit, offset=offset, with_metrics=False)
    funds = [_agent_fund_brief(f) for f in result.funds]
    return _agent_tool_response("search_funds", {
        "ok": result.ok,
        "code": result.code,
        "message": result.message,
        "count": len(funds),
        "total": result.total,
        "pagination": _agent_pagination(limit, offset, result.total, len(funds)),
        "funds": funds,
    })


@app.get("/api/agent/tools/screen", tags=["agent"],
         summary="基金筛选（只读）",
         responses={**_AGENT_ERROR_RESPONSES,
                    400: {"description": "类型/板块/关键词非法或超限"}},
         dependencies=[Security(_agent_bearer_scheme)])
def agent_screen_funds(
    ctx: Annotated[
        agent_tokens.AgentTokenContext,
        Depends(require_agent_scope(agent_tokens.SCOPE_FUNDS_READ)),
    ],
    types: Annotated[list[str] | None, Query()] = None,
    sectors: Annotated[list[str] | None, Query()] = None,
    keyword: str | None = None,
    with_metrics: bool = False,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> dict[str, Any]:
    """按类型/板块/关键词筛选基金池（只读）。

    ``with_metrics=true`` 只对当前页按代码升序的前 30 项补指标，且受进程内
    并发额度限制；超限返回 429，不排队。
    """
    del ctx
    cleaned_types = _agent_fund_filters(
        types, fetch_fund.get_available_types(), "types")
    cleaned_sectors = _agent_fund_filters(
        sectors, fetch_fund.get_available_sectors(), "sectors")
    value = _agent_fund_keyword(keyword, required=False)

    result = fund_filter.filter_funds(
        types=cleaned_types, sectors=cleaned_sectors, keyword=value,
        limit=limit, offset=offset, with_metrics=False)

    snapshots: dict[str, dict] = {}
    metrics = fund_filter.MetricsEnrichment(requested=with_metrics)
    if with_metrics and result.ok and result.funds:
        try:
            snapshots, metrics = fund_filter.enrich_page_metrics(result.funds)
        except fund_filter.EnrichmentBusy as exc:
            raise HTTPException(
                status_code=429, detail=str(exc),
                headers={"Retry-After": str(_AGENT_RATE_WINDOW)}) from exc
    elif not result.funds or not with_metrics:
        metrics.complete = True

    fund_rows: list[dict[str, Any]] = []
    for index, item in enumerate(result.funds):
        if not with_metrics:
            status = "not_requested"
        elif index >= metrics.limit:
            status = "over_limit"
        elif item.code in snapshots:
            status = "ok"
        else:
            status = "unavailable"
        fund_rows.append(_agent_fund_full(item, snapshots.get(item.code), status))

    return _agent_tool_response("screen_funds", {
        "ok": result.ok,
        "code": result.code,
        "message": result.message,
        "count": len(fund_rows),
        "total": result.total,
        "pagination": _agent_pagination(
            limit, offset, result.total, len(fund_rows)),
        "with_metrics": with_metrics,
        "metrics": metrics.to_dict(),
        "funds": fund_rows,
    })


# ---------------------------------------------------------------------------
# Agent 只读查询工具（P1.5-A 第 3 批：只读定投回测）
# ---------------------------------------------------------------------------
_AGENT_BACKTEST_MAX_AMOUNT = 1_000_000.0
_AGENT_BACKTEST_MAX_YEARS = 10
# 回测会抓取净值与费率，按进程限制同时执行数；满额快速拒绝而不是排队。
_AGENT_BACKTEST_MAX_CONCURRENCY = 2
_AGENT_BACKTEST_GATE = threading.BoundedSemaphore(_AGENT_BACKTEST_MAX_CONCURRENCY)


class AgentDcaBacktestRequest(BaseModel):
    """Agent 只读定投回测入参；未知字段拒绝，数值拒绝 NaN/Infinity。"""

    model_config = ConfigDict(allow_inf_nan=False, extra="forbid")

    fund_codes: list[str] = Field(min_length=1, max_length=5)
    start_date: str
    end_date: str
    amount_per_period: float = Field(gt=0, le=_AGENT_BACKTEST_MAX_AMOUNT)
    cadence: Literal["month", "week", "biweek"] = "month"
    include_lumpsum: bool = True
    include_curve: bool = True
    include_periods: bool = False
    max_points: int = Field(default=365, ge=10, le=2000)

    @field_validator("fund_codes")
    @classmethod
    def validate_fund_codes(cls, v: list[str]) -> list[str]:
        cleaned: list[str] = []
        for raw in v:
            code = (raw or "").strip()
            if not re.fullmatch(r"\d{6}", code):
                raise ValueError(f"fund_code 必须为 6 位数字: {raw}")
            if code not in cleaned:
                cleaned.append(code)
        if not cleaned:
            raise ValueError("请至少选择一只基金")
        return cleaned

    @field_validator("amount_per_period", mode="before")
    @classmethod
    def reject_bool_amount(cls, v: object) -> object:
        if isinstance(v, bool):
            raise ValueError("amount_per_period 必须为数字")
        return v

    @field_validator("start_date", "end_date")
    @classmethod
    def validate_date(cls, v: str) -> str:
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", v):
            raise ValueError("日期格式必须为 YYYY-MM-DD")
        try:
            datetime.strptime(v, "%Y-%m-%d")
        except ValueError:
            raise ValueError("不是有效日期") from None
        return v

    @model_validator(mode="after")
    def validate_range(self) -> AgentDcaBacktestRequest:
        start = datetime.strptime(self.start_date, "%Y-%m-%d").date()
        end = datetime.strptime(self.end_date, "%Y-%m-%d").date()
        if start >= end:
            raise ValueError("起始日期必须早于结束日期")
        today = datetime.now(config.TIMEZONE).date()
        if end > today:
            raise ValueError("结束日期不能晚于今天")
        months = (end.year - start.year) * 12 + (end.month - start.month)
        if months > _AGENT_BACKTEST_MAX_YEARS * 12 or (
            months == _AGENT_BACKTEST_MAX_YEARS * 12 and end.day > start.day
        ):
            raise ValueError(
                f"回测区间不能超过 {_AGENT_BACKTEST_MAX_YEARS} 年")
        return self


@app.post("/api/agent/tools/backtest/dca", tags=["agent"],
          summary="定投回测（只读）",
          responses={**_AGENT_ERROR_RESPONSES,
                     422: {"description": "请求体字段缺失、类型错误或含未知字段"}},
          dependencies=[Security(_agent_bearer_scheme)])
def agent_run_dca_backtest(
    req: AgentDcaBacktestRequest,
    ctx: Annotated[
        agent_tokens.AgentTokenContext,
        Depends(require_agent_scope(agent_tokens.SCOPE_FUNDS_READ)),
    ],
) -> dict[str, Any]:
    """在历史净值上模拟定投，可选附带一次性投入对照（只读）。

    复用 ``backtest.run_dca_backtest()`` 的计算逻辑，但通过
    ``readonly_nav_rows`` 只读获取净值：不调用 ``update_fund_nav()``，
    不会写入正式净值表、交易、计划或基金元数据。数据不足或费率缺失时
    在结果中显式标注，不把未知费用或失败项伪装成有效收益。
    """
    del ctx
    if not _AGENT_BACKTEST_GATE.acquire(blocking=False):
        raise HTTPException(
            status_code=429,
            detail="回测并发已满，请稍后再试",
            headers={"Retry-After": str(_AGENT_RATE_WINDOW)},
        )
    try:
        results = backtest.run_dca_backtest(
            fund_codes=req.fund_codes,
            start_date=req.start_date,
            end_date=req.end_date,
            amount_per_period=req.amount_per_period,
            cadence=req.cadence,
            include_lumpsum=req.include_lumpsum,
            nav_provider=backtest.readonly_nav_rows,
        )
    finally:
        _AGENT_BACKTEST_GATE.release()

    payload: list[dict[str, Any]] = []
    for result in results:
        row = result.to_dict()
        curve = row.get("curve") or []
        periods = row.get("periods_detail") or []
        row["curve"] = (
            _agent_sample_points(curve, req.max_points)
            if req.include_curve else []
        )
        row["periods_detail"] = periods if req.include_periods else []
        row["curve_points"] = len(row["curve"])
        row["periods_detail_count"] = len(periods)
        payload.append(row)

    failed = sum(1 for row in payload if row["status"] == "failed")
    ok = failed < len(payload) and bool(payload)
    message = ""
    if not ok:
        message = "所有基金回测失败，详见各结果的 status/code/message"
    elif failed:
        message = f"{failed} 个回测失败，详见各结果的 status/code/message"

    return _agent_tool_response("run_dca_backtest", {
        "ok": ok,
        "message": message,
        "simulation_note": (
            "定投与一次性投入为历史模拟，不是组合配置建议，也不代表未来收益；"
            "未模拟分红、拆分与红利再投资。"
        ),
        "requested": {
            "start_date": req.start_date,
            "end_date": req.end_date,
            "cadence": req.cadence,
            "amount_per_period": req.amount_per_period,
            "include_lumpsum": req.include_lumpsum,
        },
        "fund_count": len(req.fund_codes),
        "result_count": len(payload),
        "failed_count": failed,
        "results": payload,
    })


# 只读工具登记表：供能力发现；新增工具时同步维护。
_AGENT_TOOL_REGISTRY: tuple[dict[str, Any], ...] = (
    {"name": "get_portfolio_summary", "method": "GET",
     "path": "/api/agent/tools/portfolio-summary",
     "scope": agent_tokens.SCOPE_PORTFOLIO_READ},
    {"name": "get_data_status", "method": "GET",
     "path": "/api/agent/tools/data-status",
     "scope": agent_tokens.SCOPE_HEALTH_READ},
    {"name": "get_portfolio_health", "method": "GET",
     "path": "/api/agent/tools/portfolio-health",
     "scope": agent_tokens.SCOPE_HEALTH_READ},
    {"name": "list_positions", "method": "GET",
     "path": "/api/agent/tools/positions",
     "scope": agent_tokens.SCOPE_PORTFOLIO_READ},
    {"name": "get_returns", "method": "GET",
     "path": "/api/agent/tools/returns",
     "scope": agent_tokens.SCOPE_PORTFOLIO_READ},
    {"name": "compare_funds", "method": "GET",
     "path": "/api/agent/tools/funds/compare",
     "scope": agent_tokens.SCOPE_FUNDS_READ},
    {"name": "get_fund_detail", "method": "GET",
     "path": "/api/agent/tools/funds/{code}",
     "scope": agent_tokens.SCOPE_FUNDS_READ},
    {"name": "list_transactions", "method": "GET",
     "path": "/api/agent/tools/transactions",
     "scope": agent_tokens.SCOPE_TRANSACTIONS_READ},
    {"name": "get_transaction", "method": "GET",
     "path": "/api/agent/tools/transactions/{tx_id}",
     "scope": agent_tokens.SCOPE_TRANSACTIONS_READ},
    {"name": "list_watchlist", "method": "GET",
     "path": "/api/agent/tools/watchlist",
     "scope": agent_tokens.SCOPE_WATCHLIST_READ},
    {"name": "list_alerts", "method": "GET",
     "path": "/api/agent/tools/alerts",
     "scope": agent_tokens.SCOPE_ALERTS_READ},
    {"name": "list_auto_invest_plans", "method": "GET",
     "path": "/api/agent/tools/auto-invest-plans",
     "scope": agent_tokens.SCOPE_PLANS_READ},
    {"name": "get_portfolio_curve", "method": "GET",
     "path": "/api/agent/tools/portfolio-curve",
     "scope": agent_tokens.SCOPE_PORTFOLIO_READ},
    {"name": "get_benchmark_comparison", "method": "GET",
     "path": "/api/agent/tools/benchmark",
     "scope": agent_tokens.SCOPE_PORTFOLIO_READ},
    {"name": "get_risk_report", "method": "GET",
     "path": "/api/agent/tools/risk-report",
     "scope": agent_tokens.SCOPE_HEALTH_READ},
    {"name": "get_industry_exposure", "method": "GET",
     "path": "/api/agent/tools/industry-exposure",
     "scope": agent_tokens.SCOPE_PORTFOLIO_READ},
    {"name": "search_funds", "method": "GET",
     "path": "/api/agent/tools/search",
     "scope": agent_tokens.SCOPE_FUNDS_READ},
    {"name": "screen_funds", "method": "GET",
     "path": "/api/agent/tools/screen",
     "scope": agent_tokens.SCOPE_FUNDS_READ},
    {"name": "run_dca_backtest", "method": "POST",
     "path": "/api/agent/tools/backtest/dca",
     "scope": agent_tokens.SCOPE_FUNDS_READ},
    {"name": "get_agent_capabilities", "method": "GET",
     "path": "/api/agent/tools/capabilities",
     "scope": None},
    {"name": "add_watchlist_item", "method": "POST",
     "path": "/api/agent/tools/watchlist",
     "scope": agent_tokens.SCOPE_WATCHLIST_WRITE,
     "risk": "write", "requires_confirmation": False},
    {"name": "update_watchlist_item", "method": "PATCH",
     "path": "/api/agent/tools/watchlist/{code}",
     "scope": agent_tokens.SCOPE_WATCHLIST_WRITE,
     "risk": "write", "requires_confirmation": False},
    {"name": "remove_watchlist_item", "method": "DELETE",
     "path": "/api/agent/tools/watchlist/{code}",
     "scope": agent_tokens.SCOPE_WATCHLIST_WRITE,
     "risk": "write", "requires_confirmation": False},
    {"name": "start_data_refresh", "method": "POST",
     "path": "/api/agent/tools/refresh",
     "scope": agent_tokens.SCOPE_DATA_REFRESH,
     "risk": "write", "requires_confirmation": False},
    {"name": "get_job_status", "method": "GET",
     "path": "/api/agent/tools/refresh/{job_id}",
     "scope": agent_tokens.SCOPE_DATA_REFRESH},
)


@app.get("/api/agent/tools/capabilities", tags=["agent"],
         summary="能力发现（只读）", responses=_AGENT_ERROR_RESPONSES,
         dependencies=[Security(_agent_bearer_scheme)])
def agent_get_capabilities(
    ctx: Annotated[
        agent_tokens.AgentTokenContext,
        Depends(require_agent_scope(None)),
    ],
) -> dict[str, Any]:
    """返回当前 token 已获授权的工具与元数据。"""
    tools = [
        {
            **tool,
            "risk": tool.get("risk", "read"),
            "requires_confirmation": tool.get("requires_confirmation", False),
            "enabled": (
                config.AGENT_WRITE_ENABLED
                if tool.get("risk") == "write" else True
            ),
        }
        for tool in _AGENT_TOOL_REGISTRY
        if tool["scope"] is None or tool["scope"] in ctx.scopes
    ]
    return _agent_tool_response("get_agent_capabilities", {
        "server_version": APP_VERSION,
        "schema_version": 1,
        "granted_scopes": sorted(ctx.scopes),
        "write_enabled": config.AGENT_WRITE_ENABLED,
        "currency": "CNY",
        "tools": tools,
    })


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
    if field not in ("fund_type", "sector", "channel", "risk_level"):
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
    if not body.is_t1 and body.to_amount is not None and not to_tx.is_valid():
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
    model_config = ConfigDict(extra="forbid")

    code: str
    note: str = ""
    group_name: str = ""


class WatchlistGroupRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    group_name: str = ""
    expected_revision: int


class WatchlistUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_revision: int
    note: str = ""
    group_name: str = ""


class WatchlistRestoreRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_revision: int


def _web_write_principal() -> watchlist_service.Principal:
    name = config.AUTH_USERNAME or "admin"
    return watchlist_service.Principal("web", name, name)


def _ensure_fund_registered(code: str) -> None:
    """网页新增自选时保留原有“按代码收录基金”的能力。

    Agent 写入口不调用此函数：Agent 只能操作已收录基金，避免写路径隐式
    联网抓取与覆盖分类映射。
    """
    if db.get_fund(code) is not None:
        return
    meta = fetch_fund.fetch_fund_meta(code)
    if not meta.ok:
        raise HTTPException(400, meta.message or f"基金 {code} 不存在")
    db.upsert_fund(Fund(code, meta.fund_name, meta.fund_type,
                        meta.sector, meta.tracking_index))
    fetch_fund.save_sector_mapping(code, meta.sector)


@app.post("/api/watchlist")
def add_to_watchlist(request: Request, body: WatchlistRequest) -> dict[str, Any]:
    try:
        code = watchlist_service.validate_fund_code(body.code)
    except watchlist_service.WatchlistValidationError as exc:
        raise _watchlist_validation_error(exc) from exc
    _ensure_fund_registered(code)
    try:
        result = watchlist_service.add_item(
            _web_write_principal(),
            fund_code=code,
            note=body.note,
            group_name=body.group_name,
            idempotency_key=_idempotency_key_header(request),
            ip=_get_client_ip(request),
        )
    except watchlist_service.WatchlistValidationError as exc:
        raise _watchlist_validation_error(exc) from exc
    return _watchlist_result_data(result)


@app.get("/api/watchlist")
def get_watchlist() -> list[dict]:
    return db.get_watchlist()


@app.get("/api/watchlist/deleted")
def get_deleted_watchlist() -> dict[str, Any]:
    """列出可恢复的删除记录（含前值与删除版本）。"""
    return {"items": watchlist_service.list_deleted()}


@app.patch("/api/watchlist/{code}")
def update_watchlist_item(request: Request, code: str,
                          body: WatchlistUpdateRequest) -> dict[str, Any]:
    provided = body.model_fields_set
    try:
        result = watchlist_service.update_item(
            _web_write_principal(),
            fund_code=code,
            expected_revision=body.expected_revision,
            note=body.note if "note" in provided else watchlist_service.UNSET,
            group_name=(
                body.group_name if "group_name" in provided
                else watchlist_service.UNSET
            ),
            idempotency_key=_idempotency_key_header(request),
            ip=_get_client_ip(request),
        )
    except watchlist_service.WatchlistValidationError as exc:
        raise _watchlist_validation_error(exc) from exc
    return _watchlist_result_data(result)


@app.put("/api/watchlist/{code}/group")
def update_watchlist_group(request: Request, code: str,
                           body: WatchlistGroupRequest) -> dict[str, Any]:
    try:
        result = watchlist_service.update_item(
            _web_write_principal(),
            fund_code=code,
            expected_revision=body.expected_revision,
            group_name=body.group_name,
            idempotency_key=_idempotency_key_header(request),
            ip=_get_client_ip(request),
        )
    except watchlist_service.WatchlistValidationError as exc:
        raise _watchlist_validation_error(exc) from exc
    return _watchlist_result_data(result)


@app.delete("/api/watchlist/{code}")
def remove_from_watchlist(
    request: Request,
    code: str,
    expected_revision: int = Query(..., ge=1),
) -> dict[str, Any]:
    try:
        result = watchlist_service.remove_item(
            _web_write_principal(),
            fund_code=code,
            expected_revision=expected_revision,
            idempotency_key=_idempotency_key_header(request),
            ip=_get_client_ip(request),
        )
    except watchlist_service.WatchlistValidationError as exc:
        raise _watchlist_validation_error(exc) from exc
    return _watchlist_result_data(result)


@app.post("/api/watchlist/{code}/restore")
def restore_watchlist_item(request: Request, code: str,
                           body: WatchlistRestoreRequest) -> dict[str, Any]:
    """恢复已删除自选；仅网页管理员可用，且不得覆盖后续修改。"""
    try:
        result = watchlist_service.restore_item(
            _web_write_principal(),
            fund_code=code,
            expected_revision=body.expected_revision,
            idempotency_key=_idempotency_key_header(request),
            ip=_get_client_ip(request),
        )
    except watchlist_service.WatchlistValidationError as exc:
        raise _watchlist_validation_error(exc) from exc
    return _watchlist_result_data(result)


@app.get("/api/funds/{code}")
def get_fund(code: str) -> dict[str, Any]:
    fund = db.get_fund(code)
    if not fund:
        raise HTTPException(404, f"未找到基金 {code}")
    return fund.to_dict()


@app.get("/api/funds/{code}/xirr")
def get_fund_xirr(code: str) -> dict[str, Any]:
    return {"annualized_return": analysis.calculate_fund_xirr(code)}


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
        _nav_update_state["phase"] = ""
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
            _nav_update_state["phase"] = "backfill"
            updated = analysis.backfill_transaction_navs()
            analysis.clear_analysis_cache()
            if updated:
                db.log_audit("nav_backfill", ip=client_ip,
                              detail={"count": len(updated), "items": updated})
            # 同步刷新基金元数据（申购状态/交易日历/风险等级），与定时任务行为一致
            _nav_update_state["results"] = [r.__dict__ for r in results]

            def _set_phase(phase: str) -> None:
                _nav_update_state["phase"] = phase

            scheduler.refresh_fund_metadata(on_phase=_set_phase)
            # 元数据写入后失效持仓缓存，确保接口立即返回新值
            analysis.clear_analysis_cache()
        except Exception as exc:  # noqa: BLE001
            _nav_update_state["error"] = str(exc)
        finally:
            with _nav_update_lock:
                _nav_update_state["running"] = False
                _nav_update_state["current"] = ""
                _nav_update_state["phase"] = ""

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
# 宏观财富水位代码 → 名称（CPI/M2，与指数基准同构，scheduler 共用）
MACRO_INDICES = config.MACRO_INDICES
# 全部可用的对比代码（基准指数 + 宏观水位）
COMPARABLE_CODES = {**BENCHMARK_INDICES, **MACRO_INDICES}


@app.get("/api/portfolio/benchmark")
def get_portfolio_benchmark(indices: str = "") -> list[dict[str, Any]]:
    """获取基准指数累计收益率序列，与组合曲线日期对齐。

    Args:
        indices: 逗号分隔的代码，如 "000300,000001,399006,CPI,M2"
                 基准指数代码（000300 等）+ 宏观财富水位代码（CPI/M2）

    Returns:
        [{date: "2025-01-01", "000300": 0.05, "000001": 0.03, ...}, ...]
        每个代码的值为累计收益率（close / close_at_start - 1）。
        失败的代码不包含在结果中。
    """
    if not indices:
        return []
    codes = [c.strip() for c in indices.split(",") if c.strip()]
    codes = [c for c in codes if c in COMPARABLE_CODES]
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
        if code in MACRO_INDICES:
            # 宏观水位（月度数据）：基期 = 建仓前最后一个月末水平，
            # 使水位线在建仓日精确为 0，随后随通胀/货币扩张累积。
            baseline_res = fetch_macro.fetch_macro_baseline(code, start_date, end_date)
            if baseline_res:
                hist, first_close = baseline_res
            else:
                hist, first_close = [], 0
        else:
            hist = fetch_estimate.fetch_index_history(code, start_date, end_date)
            first_close = hist[0]["close"] if hist else 0
        if not hist:
            continue
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
        logger.warning("get_portfolio_benchmark: 所有基准数据均为空 %s", codes)
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


@app.get("/api/portfolio/health")
def get_health_report() -> dict[str, Any]:
    report = health.build_health_report()
    return report.to_dict()


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
    """全量备份导出（格式 v2：manifest + 12 张表 JSONL，含净值历史）。"""
    content = backup_service.export_backup_zip()
    db.log_audit("export_backup", ip=_get_client_ip(request), detail={})
    date_str = datetime.now(config.TIMEZONE).strftime("%Y%m%d")
    return Response(
        content=content,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="zfundpilot_backup_{date_str}.zip"'},
    )


_MAX_BACKUP_SIZE = backup_service.MAX_ZIP_BYTES


async def _read_backup_upload(file: UploadFile) -> bytes:
    """读取上传备份并限制大小；超限返回 413。"""
    if file.size is not None and file.size > _MAX_BACKUP_SIZE:
        raise HTTPException(413, "备份文件超过大小限制")
    data = await file.read()
    if len(data) > _MAX_BACKUP_SIZE:
        raise HTTPException(413, "备份文件超过大小限制")
    return data


def _backup_validation_error(
    exc: backup_service.BackupValidationError,
) -> HTTPException:
    return HTTPException(
        status_code=422,
        detail={"code": exc.code, "field": exc.field, "message": exc.message},
    )


@app.post("/api/backup/preflight")
async def backup_preflight(
    request: Request, file: UploadFile = File(...),
) -> dict[str, Any]:
    """备份导入预检：只读校验结构、版本、校验和与行数，不修改数据。"""
    data = await _read_backup_upload(file)
    try:
        preview = backup_service.preview_backup(data)
    except backup_service.BackupValidationError as exc:
        db.log_audit("backup_preflight_rejected", ip=_get_client_ip(request),
                     detail={"code": exc.code})
        raise _backup_validation_error(exc) from exc
    db.log_audit("backup_preflight", ip=_get_client_ip(request),
                 detail={"total_rows": preview.total_rows,
                         "format_version": preview.format_version})
    return preview.to_dict()


@app.post("/api/backup/restore")
async def backup_restore(
    request: Request,
    file: UploadFile = File(...),
    confirmation: str = Form(...),
) -> dict[str, Any]:
    """从备份整体恢复用户数据；需输入 RESTORE 确认，自动先备份当前数据。"""
    if confirmation.strip().upper() != "RESTORE":
        raise HTTPException(
            400, detail={"code": "confirmation_required",
                         "message": "请输入 RESTORE 确认整体恢复"})
    data = await _read_backup_upload(file)
    try:
        result = backup_service.restore_backup(
            data,
            ip=_get_client_ip(request),
            username=config.AUTH_USERNAME if config.AUTH_ENABLED else "local",
        )
    except backup_service.BackupBusyError as exc:
        raise HTTPException(
            409, detail={"code": "restore_busy", "message": str(exc)}) from exc
    except backup_service.BackupValidationError as exc:
        db.log_audit("restore_backup_rejected", ip=_get_client_ip(request),
                     detail={"code": exc.code})
        raise _backup_validation_error(exc) from exc
    except Exception as exc:  # noqa: BLE001
        logger.exception("备份恢复失败")
        raise HTTPException(
            500, detail={"code": "restore_failed",
                         "message": "恢复失败，当前数据已回滚"}) from exc
    return result.to_dict()


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
    funds = {f.fund_code: f for f in db.get_funds()}
    for p in plans:
        f = funds.get(p["fund_code"])
        p["fund_name"] = f.fund_name if f else ""
        p["purchase_status"] = f.purchase_status if f else ""
        p["daily_limit"] = f.daily_limit if f else 0.0
        p["min_purchase"] = f.min_purchase if f else 0.0
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
