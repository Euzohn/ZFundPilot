"""敏感字段加密存储（Fernet: AES-128-CBC + HMAC-SHA256）。

用途：在 data/ai_config.json 等配置文件中加密存储 API key 等敏感字段，
避免服务器文件被读取时直接暴露密钥。

主密钥（master key）管理：
- 首次使用时自动生成 32 字节随机密钥，存入 data/secret.key
- 文件权限 0o600（仅所有者可读写，Unix 平台）
- 与 auth.json 的 AUTH_SECRET 解耦，避免改密码导致密钥失效

向后兼容：
- 加密后字段格式为 `enc:<base64-token>`
- 未加密的旧字段（无 `enc:` 前缀）按明文返回，下次保存时自动加密
"""
from __future__ import annotations

import logging
import os
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

logger = logging.getLogger(__name__)

_PREFIX = "enc:"
_fernet: Fernet | None = None


def _get_fernet() -> Fernet:
    """获取（必要时生成）Fernet 实例。主密钥存于 data/secret.key。"""
    global _fernet
    if _fernet is not None:
        return _fernet
    # 延迟导入 config 以避免循环依赖
    from . import config
    key_path = Path(config.DATA_DIR) / "secret.key"
    if key_path.exists():
        key = key_path.read_bytes()
    else:
        key_path.parent.mkdir(parents=True, exist_ok=True)
        key = Fernet.generate_key()
        key_path.write_bytes(key)
        try:
            os.chmod(key_path, 0o600)
        except OSError:
            # Windows/非 POSIX 平台无 chmod，忽略
            pass
        logger.info("已生成新的加密主密钥 %s", key_path)
    _fernet = Fernet(key)
    return _fernet


def is_encrypted(value: str) -> bool:
    """判断字段是否为 `enc:` 前缀的密文。"""
    return bool(value) and value.startswith(_PREFIX)


def encrypt(plaintext: str) -> str:
    """加密明文，返回 `enc:<base64-token>` 格式密文。空串原样返回。"""
    if not plaintext:
        return ""
    token = _get_fernet().encrypt(plaintext.encode("utf-8"))
    return _PREFIX + token.decode("ascii")


def decrypt(ciphertext: str) -> str:
    """解密 `enc:` 前缀的密文，返回明文。

    - 无 `enc:` 前缀视为旧版明文，原样返回（向后兼容）
    - 空串原样返回
    - 解密失败（密钥变更/数据损坏）返回空串，并记录告警避免静默丢数据
    """
    if not ciphertext:
        return ""
    if not ciphertext.startswith(_PREFIX):
        # 旧版明文，原样返回，下次保存时自动加密
        return ciphertext
    try:
        token = ciphertext[len(_PREFIX):].encode("ascii")
        return _get_fernet().decrypt(token).decode("utf-8")
    except (InvalidToken, UnicodeDecodeError, UnicodeEncodeError):
        logger.warning(
            "敏感字段解密失败（主密钥可能已变更或丢失）：ciphertext 长度 %d，"
            "该字段暂按空值处理；请重新填写并保存，避免旧值被覆盖",
            len(ciphertext),
        )
        return ""


def reset() -> None:
    """重置缓存的 Fernet 实例（测试用）。"""
    global _fernet
    _fernet = None
