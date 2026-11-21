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
import threading
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

logger = logging.getLogger(__name__)

_PREFIX = "enc:"
_fernet: Fernet | None = None
# 主密钥生成锁：FastAPI 同步端点跑在线程池，首次并发保存时两个线程可能
# 各自生成密钥互相覆盖，被覆盖密钥加密的字段将永久无法解密
_key_lock = threading.Lock()


def _get_fernet() -> Fernet:
    """获取（必要时生成）Fernet 实例。主密钥存于 data/secret.key。

    生成路径多重防护：
    - threading.Lock 串行化进程内并发（双重检查，避免重复生成）；
    - 先写同目录临时文件并 fsync，再 ``os.link`` 原子落位：崩溃/掉电不会
      留下 0 字节或半截密钥（旧实现 O_EXCL 创建后再写，创建与写入之间崩溃
      会留下空密钥文件，此后每次启动都失败且密文永久不可解）；
    - ``os.link`` 目标已存在则失败（跨进程竞态失败方读已有密钥），等价 O_EXCL；
    - 临时文件创建即 0600 并显式 fchmod，消除全局可读窗口；
    - 读取/落位后校验密钥非空且合法，损坏时给出可操作的 RuntimeError。
    """
    global _fernet
    if _fernet is not None:
        return _fernet
    with _key_lock:
        if _fernet is not None:
            return _fernet
        # 延迟导入 config 以避免循环依赖
        from . import config
        key_path = Path(config.DATA_DIR) / "secret.key"
        key_path.parent.mkdir(parents=True, exist_ok=True)
        if key_path.exists():
            key = key_path.read_bytes()
        else:
            key = Fernet.generate_key()
            tmp_path = key_path.with_name(
                f".secret.key.tmp.{os.getpid()}.{threading.get_ident()}")
            try:
                fd = os.open(tmp_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
                try:
                    # umask 可能削减权限位，显式补足 0600（失败至少告警）
                    if os.name == "posix":
                        try:
                            os.fchmod(fd, 0o600)
                        except OSError:
                            logger.warning("主密钥文件权限设置 0600 失败: %s", tmp_path)
                    os.write(fd, key)
                    os.fsync(fd)
                finally:
                    os.close(fd)
                try:
                    # 原子落位：目标已存在（跨进程竞态）则失败，改读已有密钥
                    os.link(tmp_path, key_path)
                except FileExistsError:
                    key = key_path.read_bytes()
                else:
                    logger.info("已生成新的加密主密钥 %s", key_path)
                    # fsync 目录确保 link 目录项持久化（best-effort）
                    if os.name == "posix":
                        try:
                            dir_fd = os.open(key_path.parent, os.O_RDONLY)
                            try:
                                os.fsync(dir_fd)
                            finally:
                                os.close(dir_fd)
                        except OSError:
                            logger.warning("主密钥目录 fsync 失败: %s", key_path.parent)
            finally:
                tmp_path.unlink(missing_ok=True)
        if not key:
            raise RuntimeError(
                f"主密钥文件为空：{key_path}。请从备份恢复 data/secret.key；"
                "若确认无任何加密数据，可删除该文件后重启重新生成。")
        try:
            _fernet = Fernet(key)
        except (ValueError, TypeError) as exc:
            raise RuntimeError(
                f"主密钥文件损坏：{key_path}（{exc}）。请从备份恢复 data/secret.key；"
                "若确认无任何加密数据，可删除该文件后重启重新生成。") from exc
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
