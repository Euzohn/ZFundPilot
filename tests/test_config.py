"""config 密码哈希与验证测试：bcrypt / SHA-256 回退 / 迁移升级 / auth fail-closed。"""
import importlib
import ipaddress
from unittest.mock import patch

import pytest

from zfundpilot import config


class TestHashPasswordSha256:
    def test_hex_format(self):
        h = config._hash_password_sha256("test123")
        assert len(h) == 64
        assert all(c in "0123456789abcdef" for c in h)

    def test_deterministic(self):
        assert config._hash_password_sha256("pw") == config._hash_password_sha256("pw")

    def test_different_inputs(self):
        assert config._hash_password_sha256("a") != config._hash_password_sha256("b")


class TestHashPasswordBcrypt:
    def test_bcrypt_prefix(self):
        h = config._hash_password("secret")
        assert h.startswith("$2b$")

    def test_different_salts(self):
        h1 = config._hash_password("pw")
        h2 = config._hash_password("pw")
        assert h1 != h2


class TestVerifyPassword:
    def test_bcrypt_correct(self):
        h = config._hash_password("hello")
        assert config.verify_password("hello", h) is True

    def test_bcrypt_wrong(self):
        h = config._hash_password("hello")
        assert config.verify_password("wrong", h) is False

    def test_sha256_fallback(self):
        h = config._hash_password_sha256("legacy")
        assert config.verify_password("legacy", h) is True

    def test_sha256_wrong(self):
        h = config._hash_password_sha256("legacy")
        assert config.verify_password("wrong", h) is False

    def test_corrupted_bcrypt_returns_false(self):
        assert config.verify_password("pw", "$2b$00$corrupted") is False


class TestMigratePasswordHash:
    def test_upgrades_to_bcrypt(self):
        sha_hash = config._hash_password_sha256("oldpw")
        with patch.object(config, "AUTH_PASSWORD_HASH", sha_hash):
            with patch.object(config, "_persist_auth"):
                config.migrate_password_hash("newpw")
                new_hash = config.AUTH_PASSWORD_HASH
                assert new_hash.startswith("$2b$")
                assert config.verify_password("newpw", new_hash)

    def test_does_not_change_auth_secret(self):
        original_secret = config.AUTH_SECRET
        with patch.object(config, "AUTH_PASSWORD_HASH", "old"):
            with patch.object(config, "_persist_auth"):
                config.migrate_password_hash("pw")
                assert config.AUTH_SECRET == original_secret

    def test_persist_called(self):
        with patch.object(config, "AUTH_PASSWORD_HASH", "old"):
            with patch.object(config, "_persist_auth") as mock_persist:
                config.migrate_password_hash("pw")
                mock_persist.assert_called_once()


class TestLoadAuthDataFailClosed:
    """auth.json 损坏/不可读必须拒绝启动（fail-closed）。

    旧实现静默返回 None → AUTH_ENABLED=False，一次读取失败就把已启用
    密码认证的系统降级为完全开放访问。文件不存在仍返回 None（首次运行）。
    """

    def test_missing_file_returns_none(self, tmp_path, monkeypatch):
        monkeypatch.setattr(config, "AUTH_DATA_PATH", str(tmp_path / "auth.json"))
        assert config._load_auth_data() is None

    def test_valid_file_returns_data(self, tmp_path, monkeypatch):
        p = tmp_path / "auth.json"
        p.write_text('{"username": "admin", "password_hash": "x", "secret": "s"}',
                     encoding="utf-8")
        monkeypatch.setattr(config, "AUTH_DATA_PATH", str(p))
        data = config._load_auth_data()
        assert data["username"] == "admin"
        assert data["password_hash"] == "x"

    def test_corrupted_json_raises(self, tmp_path, monkeypatch):
        p = tmp_path / "auth.json"
        p.write_text('{"username": ', encoding="utf-8")
        monkeypatch.setattr(config, "AUTH_DATA_PATH", str(p))
        with pytest.raises(RuntimeError, match="损坏或不可读"):
            config._load_auth_data()

    def test_unreadable_file_raises(self, tmp_path, monkeypatch):
        p = tmp_path / "auth.json"
        p.write_text("{}", encoding="utf-8")
        monkeypatch.setattr(config, "AUTH_DATA_PATH", str(p))
        with patch("builtins.open", side_effect=PermissionError("denied")):
            with pytest.raises(RuntimeError, match="损坏或不可读"):
                config._load_auth_data()

    def test_non_object_json_raises(self, tmp_path, monkeypatch):
        """合法 JSON 但非对象（如 []）同样 fail-closed，不得降级为开放访问。"""
        p = tmp_path / "auth.json"
        p.write_text("[]", encoding="utf-8")
        monkeypatch.setattr(config, "AUTH_DATA_PATH", str(p))
        with pytest.raises(RuntimeError):
            config._load_auth_data()

    def test_startup_refuses_corrupted_auth(self, tmp_path, monkeypatch):
        """模块初始化（启动路径）读取损坏 auth.json 时直接抛错拒绝启动。"""
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        (data_dir / "auth.json").write_text("{corrupted", encoding="utf-8")
        monkeypatch.setenv("ZFUNDPILOT_HOME", str(tmp_path))
        try:
            with pytest.raises(RuntimeError):
                importlib.reload(config)
        finally:
            # 恢复环境变量并重载，避免污染后续测试
            monkeypatch.undo()
            importlib.reload(config)


class TestTrustedProxies:
    """TRUSTED_PROXIES 支持 IPv6 CIDR（配套 api._get_client_ip 的 IPv6 识别），
    且向后兼容既有 IPv4 CIDR 配置。"""

    def test_ipv4_cidr_backward_compat(self):
        nets = config._parse_trusted_proxies("127.0.0.0/8, 10.0.0.0/8")
        assert nets == [ipaddress.ip_network("127.0.0.0/8"),
                        ipaddress.ip_network("10.0.0.0/8")]
        assert all(isinstance(n, ipaddress.IPv4Network) for n in nets)

    def test_ipv6_cidr(self):
        nets = config._parse_trusted_proxies("::1/128,2001:db8::/32")
        assert isinstance(nets[0], ipaddress.IPv6Network)
        assert ipaddress.ip_address("::1") in nets[0]
        assert ipaddress.ip_address("2001:db8::1") in nets[1]
        assert ipaddress.ip_address("2001:db9::1") not in nets[1]

    def test_mixed_and_bare_ips(self):
        nets = config._parse_trusted_proxies("192.168.1.1, ::1, 10.0.0.0/8")
        assert ipaddress.ip_address("192.168.1.1") in nets[0]
        assert ipaddress.ip_address("::1") in nets[1]
        assert ipaddress.ip_address("10.1.2.3") in nets[2]

    def test_empty_returns_empty(self):
        assert config._parse_trusted_proxies("") == []
        assert config._parse_trusted_proxies(" , ") == []

    def test_invalid_cidr_raises(self):
        with pytest.raises(ValueError):
            config._parse_trusted_proxies("not-a-cidr")

    def test_env_parsed_at_import(self, tmp_path, monkeypatch):
        """模块初始化（启动路径）从环境变量解析 IPv6+IPv4 混合网段。"""
        monkeypatch.setenv("ZFUNDPILOT_HOME", str(tmp_path))
        monkeypatch.setenv("ZFUNDPILOT_TRUSTED_PROXIES", "::1/128,127.0.0.0/8")
        try:
            importlib.reload(config)
            assert ipaddress.ip_address("::1") in config.TRUSTED_PROXIES[0]
            assert ipaddress.ip_address("127.0.0.1") in config.TRUSTED_PROXIES[1]
        finally:
            # 恢复环境变量并重载，避免污染后续测试
            monkeypatch.undo()
            importlib.reload(config)
