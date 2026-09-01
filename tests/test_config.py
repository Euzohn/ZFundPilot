"""config 密码哈希与验证测试：bcrypt / SHA-256 回退 / 迁移升级。"""
from unittest.mock import patch

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
