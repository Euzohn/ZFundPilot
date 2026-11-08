"""crypto 加解密测试：Fernet 加密、解密、旧版明文兼容、主密钥隔离。"""
import json
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

    def test_invalid_token_warns(self, tmp_path, monkeypatch, caplog):
        """解密失败必须记录告警，避免静默丢数据。"""
        self._setup_key(tmp_path, monkeypatch)
        bad = "enc:ZmFrZS1ub3QtcmVhbC10b2tlbi0xMjM0NTY3ODkw="
        with caplog.at_level("WARNING", logger="zfundpilot.crypto"):
            assert crypto.decrypt(bad) == ""
        assert any("解密失败" in r.message for r in caplog.records)

    def test_is_encrypted(self):
        assert crypto.is_encrypted("enc:abc") is True
        assert crypto.is_encrypted("sk-plaintext") is False
        assert crypto.is_encrypted("") is False

    def test_save_preserves_existing_ciphertext_on_empty(self, tmp_path, monkeypatch):
        """传入空 Key 时保留磁盘上的旧密文，避免解密失败后被空值覆盖。"""
        self._setup_key(tmp_path, monkeypatch)
        cfg_path = tmp_path / "ai_config.json"
        monkeypatch.setattr(config, "AI_CONFIG_PATH", str(cfg_path))

        config._save_ai_config({
            "base_url": "https://api.test/v1",
            "api_key": "sk-original",
            "model": "m",
            "vision_api_key": "sk-vision",
        })
        raw = json.loads(cfg_path.read_text(encoding="utf-8"))
        assert raw["api_key"].startswith("enc:")
        saved_cipher = raw["api_key"]

        # 模拟“未改动/解密失败”：空 Key 不应覆盖旧密文
        config._save_ai_config({
            "base_url": "https://api.test/v1",
            "api_key": "",
            "model": "m2",
            "vision_api_key": "",
        })
        raw2 = json.loads(cfg_path.read_text(encoding="utf-8"))
        assert raw2["api_key"] == saved_cipher
        assert raw2["vision_api_key"].startswith("enc:")
        assert crypto.decrypt(raw2["api_key"]) == "sk-original"
        assert crypto.decrypt(raw2["vision_api_key"]) == "sk-vision"

        # 重新填写新 Key 时应覆盖
        config._save_ai_config({
            "base_url": "https://api.test/v1",
            "api_key": "sk-new",
            "model": "m2",
            "vision_api_key": "sk-vision",
        })
        raw3 = json.loads(cfg_path.read_text(encoding="utf-8"))
        assert crypto.decrypt(raw3["api_key"]) == "sk-new"

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
