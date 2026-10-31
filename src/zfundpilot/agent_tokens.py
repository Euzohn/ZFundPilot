"""Agent 只读访问的独立 token 安全边界。

与网页登录 token 物理隔离：

- 网页登录 token：HMAC 签名、无状态、有效期较短。
- Agent token：高熵随机串，服务端只存 SHA-256 摘要，可单独列出、撤销、轮换；
  仅能调用显式声明 scope 的 Agent 端点，绝不凭网页认证中间件通行全站 API。

安全默认：

- 缺少所需 scope → 403；token 无效 / 过期 / 已撤销 → 401。
- 未启用管理员密码认证（``config.AUTH_ENABLED`` 为 False）时，Agent token
  既不可签发也不可使用，避免无密码模式被匿名调用。

本模块只负责 token 自身的生成、校验与 scope 判断；HTTP 鉴权依赖与审计在
``api.py`` 中完成，数据库读写统一走 ``db.py``。
"""

from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta

from . import config, db

TOKEN_PREFIX = "zfag_"
PREFIX_DISPLAY_LEN = 12
DEFAULT_TTL_DAYS = 90
MAX_TTL_DAYS = 3650
_MIN_ENTROPY_BYTES = 32  # 256-bit 随机熵

SCOPE_PORTFOLIO_READ = "portfolio:read"
SCOPE_FUNDS_READ = "funds:read"
SCOPE_HEALTH_READ = "health:read"
SCOPE_TRANSACTIONS_READ = "transactions:read"
SCOPE_WATCHLIST_READ = "watchlist:read"
SCOPE_ALERTS_READ = "alerts:read"
SCOPE_PLANS_READ = "plans:read"
SCOPE_WATCHLIST_WRITE = "watchlist:write"
SCOPE_DATA_REFRESH = "data:refresh"
# 提案 scope：只允许创建/查看/取消自己的待审批提案，不能直写账本。
SCOPE_TRANSACTIONS_PROPOSE = "transactions:propose"
# 可信直记 scope：仅授权新增单笔普通买入/卖出，直接写账本（F0）。
# 与提案 scope 相互独立，不自动附带；默认不勾选，旧 token 不扩权。
SCOPE_TRANSACTIONS_CREATE = "transactions:create"

# 写 scope 仅开放低风险自选维护、任务化数据刷新、账本提案与可信单笔直记；
# 均受 config.AGENT_WRITE_ENABLED 总开关约束。直记是管理员对特定 token 的
# 预授权，不是逐笔人类确认；高影响账本变更仍必须走网页审批。
ALLOWED_SCOPES = frozenset({
    SCOPE_PORTFOLIO_READ,
    SCOPE_FUNDS_READ,
    SCOPE_HEALTH_READ,
    SCOPE_TRANSACTIONS_READ,
    SCOPE_WATCHLIST_READ,
    SCOPE_ALERTS_READ,
    SCOPE_PLANS_READ,
    SCOPE_WATCHLIST_WRITE,
    SCOPE_DATA_REFRESH,
    SCOPE_TRANSACTIONS_PROPOSE,
    SCOPE_TRANSACTIONS_CREATE,
})

# 写 scope 集合：用于能力发现、审计与前端风险提示，避免把写权限当只读展示。
WRITE_SCOPES = frozenset({
    SCOPE_WATCHLIST_WRITE,
    SCOPE_DATA_REFRESH,
    SCOPE_TRANSACTIONS_PROPOSE,
    SCOPE_TRANSACTIONS_CREATE,
})

# 提案 scope 集合：仅可提交待审批提案，执行权限只属于网页管理员。
PROPOSE_SCOPES = frozenset({SCOPE_TRANSACTIONS_PROPOSE})

# 新 scope 默认不勾选：签发页面需显式选择，避免存量流程静默扩权。
DEFAULT_SCOPES: tuple[str, ...] = (
    SCOPE_PORTFOLIO_READ,
    SCOPE_FUNDS_READ,
    SCOPE_HEALTH_READ,
)


class AgentTokenError(Exception):
    """Agent token 校验失败基类；``status_code`` 供 API 层直接使用。"""

    status_code = 401
    reason = "invalid_token"

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class AgentAuthDisabled(AgentTokenError):
    """未启用管理员认证，Agent token 不可签发或使用。"""

    status_code = 403
    reason = "auth_disabled"


class AgentTokenInvalid(AgentTokenError):
    """token 不存在或格式无效。"""

    status_code = 401
    reason = "invalid_token"


class AgentTokenExpired(AgentTokenInvalid):
    """token 已过期。"""

    reason = "expired"


class AgentTokenRevoked(AgentTokenInvalid):
    """token 已撤销。"""

    reason = "revoked"


class AgentTokenScopeDenied(AgentTokenError):
    """token 有效但缺少所需 scope。"""

    status_code = 403
    reason = "insufficient_scope"


@dataclass(frozen=True)
class AgentTokenContext:
    """通过校验后的 Agent 身份信息（不含明文与摘要）。"""

    id: int
    name: str
    scopes: frozenset[str]
    prefix: str  # 可安全写入日志的短前缀


def hash_token(plaintext: str) -> str:
    """返回 token 的 SHA-256 摘要（十六进制）。

    Token 本身是 256-bit 高熵随机值，不存在可离线猜测的弱口令问题，
    因此使用快速哈希而非 bcrypt；摘要仍只存服务端。
    """
    return hashlib.sha256(plaintext.encode("utf-8")).hexdigest()


def generate_token() -> tuple[str, str, str]:
    """生成新 token，返回 ``(明文, 摘要, 可展示前缀)``。"""
    plaintext = TOKEN_PREFIX + secrets.token_urlsafe(_MIN_ENTROPY_BYTES)
    return plaintext, hash_token(plaintext), plaintext[:PREFIX_DISPLAY_LEN]


def normalize_scopes(scopes: list[str] | tuple[str, ...] | str) -> frozenset[str]:
    """校验并规范化 scope 集合；未知 scope 或空集合抛 ``ValueError``。"""
    if isinstance(scopes, str):
        scopes = scopes.split()
    normalized = frozenset(s.strip() for s in scopes if s and s.strip())
    if not normalized:
        raise ValueError("至少需要一个 scope")
    unknown = normalized - ALLOWED_SCOPES
    if unknown:
        raise ValueError(f"未知 scope：{', '.join(sorted(unknown))}")
    return normalized


def issue_token(
    name: str,
    scopes: list[str] | tuple[str, ...] | str,
    expires_in_days: int | None = DEFAULT_TTL_DAYS,
) -> tuple[str, dict]:
    """签发 token。

    明文只在此刻返回一次，服务端仅保存摘要与元数据。返回
    ``(明文, token_元数据)``。
    """
    if not config.AUTH_ENABLED:
        raise AgentAuthDisabled("未启用管理员密码认证，不能签发 Agent token")
    clean_name = (name or "").strip()
    if not clean_name:
        raise ValueError("名称不能为空")
    if expires_in_days is not None and not (1 <= expires_in_days <= MAX_TTL_DAYS):
        raise ValueError(f"有效期需在 1–{MAX_TTL_DAYS} 天之间")

    scope_set = normalize_scopes(scopes)
    now = datetime.now(config.TIMEZONE)
    expires_at = (
        (now + timedelta(days=expires_in_days)).isoformat()
        if expires_in_days
        else None
    )
    plaintext, digest, prefix = generate_token()
    row = db.create_agent_token(
        name=clean_name,
        token_hash=digest,
        token_prefix=prefix,
        scopes=" ".join(sorted(scope_set)),
        expires_at=expires_at,
    )
    return plaintext, row


def authenticate(
    plaintext: str,
    required_scope: str | None = None,
    *,
    touch: bool = True,
) -> AgentTokenContext:
    """校验明文 token 与所需 scope；失败抛 :class:`AgentTokenError` 子类。

    ``touch=True`` 时更新最近使用时间；调用方若只想探测有效性可显式关闭。
    """
    if not config.AUTH_ENABLED:
        raise AgentAuthDisabled("未启用管理员密码认证，Agent token 不可用")
    if required_scope is not None and required_scope not in ALLOWED_SCOPES:
        raise ValueError(f"未定义的 Agent scope：{required_scope}")
    if not plaintext:
        raise AgentTokenInvalid("缺少 Agent token")

    row = db.get_agent_token_by_hash(hash_token(plaintext))
    if row is None:
        raise AgentTokenInvalid("Agent token 无效")
    if row.get("revoked_at"):
        raise AgentTokenRevoked("Agent token 已撤销")

    expires_at = row.get("expires_at")
    if expires_at:
        try:
            if datetime.fromisoformat(expires_at) <= datetime.now(config.TIMEZONE):
                raise AgentTokenExpired("Agent token 已过期")
        except (ValueError, TypeError) as exc:
            raise AgentTokenInvalid("Agent token 过期时间无效") from exc

    scopes = frozenset((row.get("scopes") or "").split())
    if required_scope is not None and required_scope not in scopes:
        raise AgentTokenScopeDenied(f"Agent token 缺少权限：{required_scope}")

    if touch:
        db.touch_agent_token(row["id"])
    return AgentTokenContext(
        id=row["id"],
        name=row.get("name", ""),
        scopes=scopes,
        prefix=row.get("token_prefix", ""),
    )


def is_active(token: dict, now: datetime | None = None) -> bool:
    """判断 token 元数据是否仍可用（未撤销且未过期）。"""
    if token.get("revoked_at"):
        return False
    expires_at = token.get("expires_at")
    if not expires_at:
        return True
    now = now or datetime.now(config.TIMEZONE)
    try:
        return datetime.fromisoformat(expires_at) > now
    except (ValueError, TypeError):
        return False
