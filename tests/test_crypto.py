"""crypto 加解密测试：Fernet 加密、解密、旧版明文兼容、主密钥隔离。"""
import os

from zfundpilot import config, crypto


class TestCrypto:
    def _setup_key(self, tmp_path, monkeypatch):
        """每个测试用独立的临时 data 目录，避免污染真实 secret.key。"""
        monkeypatch.setattr(config, "DATA_DIR", str(tmp_path))
        crypto.reset()

    def test_roundtrip(self, tmp_path, monkeypatch):
        self._setup_key(tmp_path, monkeypatch)
        plain = "sk-abc123-xyz"
        cipher = crypto.encrypt(plain)
        assert cipher.startswith("enc:")
        assert cipher != plain
        assert crypto.decrypt(cipher) == plain

    def test_empty_string(self, tmp_path, monkeypatch):
        self._setup_key(tmp_path, monkeypatch)
        assert crypto.encrypt("") == ""
        assert crypto.decrypt("") == ""

    def test_legacy_plaintext_compat(self, tmp_path, monkeypatch):
        """旧版明文 api_key（无 enc: 前缀）应原样返回。"""
        self._setup_key(tmp_path, monkeypatch)
        assert crypto.decrypt("sk-old-plaintext-key") == "sk-old-plaintext-key"

    def test_persistence_across_fernet_instances(self, tmp_path, monkeypatch):
        """同一 data 目录下，重启后（重置 Fernet 缓存）仍可解密。"""
        self._setup_key(tmp_path, monkeypatch)
        cipher = crypto.encrypt("persist-me")
        crypto.reset()  # 模拟重启
        assert crypto.decrypt(cipher) == "persist-me"

    def test_invalid_token_returns_empty(self, tmp_path, monkeypatch):
        """密钥变更/数据损坏时返回空串而非抛异常。"""
        self._setup_key(tmp_path, monkeypatch)
        bad = "enc:ZmFrZS1ub3QtcmVhbC10b2tlbi0xMjM0NTY3ODkw="
        assert crypto.decrypt(bad) == ""

    def test_key_file_permissions(self, tmp_path, monkeypatch):
        """Unix 平台上 secret.key 文件权限应为 0o600。"""
        self._setup_key(tmp_path, monkeypatch)
        crypto.encrypt("trigger-key-generation")
        key_path = tmp_path / "secret.key"
        assert key_path.exists()
        if os.name == "posix":
            mode = key_path.stat().st_mode & 0o777
            assert mode == 0o600

    def test_different_data_dirs_isolated(self, tmp_path, monkeypatch):
        """不同 data 目录的主密钥应不同，互相无法解密。"""
        # 目录 A 加密
        dir_a = tmp_path / "a"
        dir_a.mkdir()
        self._setup_key(dir_a, monkeypatch)
        cipher_a = crypto.encrypt("isolation-test")

        # 切换到目录 B
        dir_b = tmp_path / "b"
        dir_b.mkdir()
        self._setup_key(dir_b, monkeypatch)
        # B 的密钥解不开 A 的密文
        assert crypto.decrypt(cipher_a) == ""
