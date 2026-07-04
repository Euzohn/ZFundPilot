"""全局配置与常量定义。

集中管理数据库路径、基金类型、风险阈值等，避免在各模块散落魔法值。
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets as _secrets

# ---------------------------------------------------------------------------
# 路径配置
# ---------------------------------------------------------------------------
# 开发模式（src-layout）：从包目录上溯三级找到项目根（含 pyproject.toml）
# 安装模式：找不到 pyproject.toml 时退回 cwd，保证数据可写
_PACKAGE_DIR = os.path.dirname(os.path.abspath(__file__))
_SRC_DIR = os.path.dirname(_PACKAGE_DIR)
_PROJECT_ROOT = os.path.dirname(_SRC_DIR)
if not os.path.exists(os.path.join(_PROJECT_ROOT, "pyproject.toml")):
    _PROJECT_ROOT = os.getcwd()

BASE_DIR = os.environ.get("ZFUNDPILOT_HOME") or _PROJECT_ROOT
DATA_DIR = os.path.join(BASE_DIR, "data")
DB_PATH = os.path.join(DATA_DIR, "fund.db")

# 确保数据目录存在
os.makedirs(DATA_DIR, exist_ok=True)


# ---------------------------------------------------------------------------
# 基金分类
# ---------------------------------------------------------------------------
# 资产类型（对应 fund.md 的“资产持仓分布”）
FUND_TYPES = [
    "混合型",
    "指数型",
    "QDII",
    "债券型",
    "股票型",
    "其它",
]

# 权益类资产类型（用于风险判断，债券/货币不算权益）
EQUITY_LIKE_TYPES = {"混合型", "指数型", "股票型", "QDII"}


# ---------------------------------------------------------------------------
# 购买渠道
# ---------------------------------------------------------------------------
# 常用渠道，UI 下拉用；用户也可自行输入其它渠道名
CHANNELS = [
    "支付宝",
    "理财通",
    "天天基金",
    "基金公司直销",
    "银行",
    "券商",
    "其它",
]
DEFAULT_CHANNEL = "支付宝"


# ---------------------------------------------------------------------------
# 风险阈值（可按需调整）
# ---------------------------------------------------------------------------
class RiskThresholds:
    # 单只基金占比
    SINGLE_FUND_WARN = 0.20   # 超过 20% 提示集中度偏高
    SINGLE_FUND_HIGH = 0.40   # 超过 40% 提示集中度过高

    # 债券等防守型资产占比
    BOND_MIN = 0.10           # 低于 10% 提示防守不足

    # QDII 海外暴露
    QDII_WARN = 0.30          # 超过 30% 提示海外/汇率风险

    # 权益类总占比
    EQUITY_WARN = 0.70        # 超过 70% 提示风格偏成长

    # 最大回撤
    DRAWDOWN_HIGH = -0.15     # 低于 -15% 高风险

    # 年化波动率
    VOLATILITY_HIGH = 0.25    # 超过 25% 波动偏高


# ---------------------------------------------------------------------------
# 数据源配置
# ---------------------------------------------------------------------------
# 一年约 244 个交易日，用于年化换算
TRADING_DAYS_PER_YEAR = 244

# 净值获取失败时的最大重试次数
FETCH_MAX_RETRIES = 2


# ---------------------------------------------------------------------------
# 认证配置
# ---------------------------------------------------------------------------
# 密码以 SHA-256 哈希存储在 data/auth.json 中，不以明文保存。
# 首次启动时，若设置了 ZFUNDPILOT_PASSWORD 环境变量，则自动迁移到 auth.json。
# 之后密码管理通过 API /api/auth/change-password 进行，无需修改环境变量。
# 不设置密码时（默认），应用为开放访问（适合纯本地使用）。

AUTH_DATA_PATH = os.path.join(DATA_DIR, "auth.json")


def _hash_password(password: str) -> str:
    """SHA-256 哈希密码。"""
    return hashlib.sha256(password.encode()).hexdigest()


def verify_password(password: str, password_hash: str) -> bool:
    """验证密码与哈希是否匹配（常量时间比较）。"""
    return hmac.compare_digest(_hash_password(password), password_hash)


def _load_auth_data() -> dict | None:
    """从 auth.json 读取认证数据。"""
    if not os.path.exists(AUTH_DATA_PATH):
        return None
    try:
        with open(AUTH_DATA_PATH, encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None


def _save_auth_data(data: dict) -> None:
    """写入 auth.json。"""
    with open(AUTH_DATA_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def update_password(new_password: str) -> None:
    """更新密码哈希（内存 + 持久化）。"""
    global AUTH_PASSWORD_HASH
    AUTH_PASSWORD_HASH = _hash_password(new_password)
    auth_data = _load_auth_data() or {}
    auth_data["password_hash"] = AUTH_PASSWORD_HASH
    _save_auth_data(auth_data)


# 初始化：优先从 auth.json 读取，回退到环境变量（首次迁移）
_auth_data = _load_auth_data()
_env_password = os.environ.get("ZFUNDPILOT_PASSWORD", "")
_env_secret = os.environ.get("ZFUNDPILOT_SECRET", "")

if _auth_data and _auth_data.get("password_hash"):
    AUTH_PASSWORD_HASH: str = _auth_data["password_hash"]
    AUTH_SECRET: str = _auth_data.get("secret", "") or _env_secret or _env_password
elif _env_password:
    AUTH_PASSWORD_HASH = _hash_password(_env_password)
    AUTH_SECRET = _env_secret or _secrets.token_hex(32)
    _save_auth_data({"password_hash": AUTH_PASSWORD_HASH, "secret": AUTH_SECRET})
else:
    AUTH_PASSWORD_HASH = ""
    AUTH_SECRET = ""

# 是否启用认证
AUTH_ENABLED = bool(AUTH_PASSWORD_HASH)

# token 有效期（秒），默认 7 天
AUTH_TOKEN_MAX_AGE = 7 * 24 * 3600


# ---------------------------------------------------------------------------
# AI 投顾配置
# ---------------------------------------------------------------------------
# AI 配置存储在 data/ai_config.json 中。
# 支持 OpenAI 兼容 API（OpenAI / 智谱 / Kimi / 通义千问 / DeepSeek 等）。
# 联网搜索根据 base_url 自动识别提供商格式。

AI_CONFIG_PATH = os.path.join(DATA_DIR, "ai_config.json")


def _load_ai_config() -> dict:
    if not os.path.exists(AI_CONFIG_PATH):
        return {}
    try:
        with open(AI_CONFIG_PATH, encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def _save_ai_config(data: dict) -> None:
    with open(AI_CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def update_ai_config(base_url: str, api_key: str, model: str, web_search: bool) -> None:
    """更新 AI 配置（内存 + 持久化）。"""
    global AI_BASE_URL, AI_API_KEY, AI_MODEL, AI_WEB_SEARCH
    AI_BASE_URL = base_url
    AI_API_KEY = api_key
    AI_MODEL = model
    AI_WEB_SEARCH = web_search
    _save_ai_config({
        "base_url": base_url,
        "api_key": api_key,
        "model": model,
        "web_search": web_search,
    })


_ai_config = _load_ai_config()
AI_BASE_URL: str = _ai_config.get("base_url", "")
AI_API_KEY: str = _ai_config.get("api_key", "")
AI_MODEL: str = _ai_config.get("model", "")
AI_WEB_SEARCH: bool = _ai_config.get("web_search", True)
