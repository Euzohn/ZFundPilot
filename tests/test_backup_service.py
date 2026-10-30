"""备份格式 v2 测试：导出、预检、恢复、损坏/重复/回滚。"""
from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

from zfundpilot import backup_service as bs
from zfundpilot import config, db
from zfundpilot.analysis import clear_analysis_cache
from zfundpilot.models import Fund, Transaction


@pytest.fixture
def temp_env(monkeypatch):
    with TemporaryDirectory() as d:
        monkeypatch.setattr(config, "DB_PATH", str(Path(d) / "test.db"))
        monkeypatch.setattr(config, "DATA_DIR", d)
        db.init_db()
        db.upsert_fund(Fund("005827", "易方达蓝筹精选", "混合型", "消费"))
        db.add_transaction(Transaction(
            fund_code="005827", action="buy", date="2026-01-02",
            amount=1000.0, fee=1.0, channel="支付宝"))
        clear_analysis_cache()
        yield
        clear_analysis_cache()


def _zip_files(payload: bytes) -> dict[str, bytes]:
    with zipfile.ZipFile(io.BytesIO(payload)) as zf:
        return {name: zf.read(name) for name in zf.namelist()}


def _replace_member(payload: bytes, name: str, data: bytes) -> bytes:
    files = _zip_files(payload)
    files[name] = data
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for key, value in files.items():
            zf.writestr(key, value)
    return buf.getvalue()


def _mutate_manifest(payload: bytes, mutate) -> bytes:
    files = _zip_files(payload)
    manifest = json.loads(files["manifest.json"])
    mutate(manifest)
    files["manifest.json"] = json.dumps(manifest, ensure_ascii=False).encode()
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for key, value in files.items():
            zf.writestr(key, value)
    return buf.getvalue()


class TestExport:
    def test_manifest_and_tables(self, temp_env):
        payload = bs.export_backup_zip()
        files = _zip_files(payload)
        assert "manifest.json" in files
        manifest = json.loads(files["manifest.json"])
        assert manifest["format"] == bs.FORMAT_NAME
        assert manifest["format_version"] == bs.FORMAT_VERSION
        assert set(manifest["tables"]) == set(bs.TABLE_COLUMNS)
        for table in bs.TABLE_COLUMNS:
            assert manifest["tables"][table]["file"] == f"tables/{table}.jsonl"
        assert "tables/nav_history.jsonl" in files
        assert all("agent_tokens" not in name for name in files)
        assert all("audit_log" not in name for name in files)

    def test_nav_history_roundtrip(self, temp_env):
        db.upsert_nav_batch([type("P", (), {
            "fund_code": "005827", "date": "2026-01-02",
            "nav": 1.5, "accumulated_nav": 2.5, "source": "test",
        })()])
        payload = bs.export_backup_zip()
        preview = bs.preview_backup(payload)
        assert preview.counts["nav_history"] == 1
        assert preview.counts["transactions"] == 1


class TestPreviewErrors:
    def test_corrupt_checksum(self, temp_env):
        payload = bs.export_backup_zip()
        broken = _replace_member(
            payload, "tables/funds.jsonl", b'{"fund_code":"bad"}\n')
        with pytest.raises(bs.BackupValidationError) as exc:
            bs.preview_backup(broken)
        assert exc.value.code == "checksum_mismatch"

    def test_duplicate_key(self, temp_env):
        payload = bs.export_backup_zip()
        files = _zip_files(payload)
        row = json.loads(files["tables/funds.jsonl"].decode().splitlines()[0])
        duplicate = (json.dumps(row) + "\n" + json.dumps(row) + "\n").encode()
        files["tables/funds.jsonl"] = duplicate
        manifest = json.loads(files["manifest.json"])
        manifest["tables"]["funds"]["rows"] = 2
        manifest["tables"]["funds"]["sha256"] = bs._sha256(duplicate)
        files["manifest.json"] = json.dumps(manifest).encode()
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for key, value in files.items():
                zf.writestr(key, value)
        with pytest.raises(bs.BackupValidationError) as exc:
            bs.preview_backup(buf.getvalue())
        assert exc.value.code == "duplicate_key"

    def test_unknown_table(self, temp_env):
        payload = bs.export_backup_zip()
        broken = _mutate_manifest(
            payload, lambda m: m["tables"].update({"evil": {"file": "x"}}))
        with pytest.raises(bs.BackupValidationError) as exc:
            bs.preview_backup(broken)
        assert exc.value.code == "table_mismatch"

    def test_missing_manifest(self, temp_env):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("tables/funds.jsonl", b"")
        with pytest.raises(bs.BackupValidationError) as exc:
            bs.preview_backup(buf.getvalue())
        assert exc.value.code == "missing_manifest"

    def test_unsupported_version(self, temp_env):
        payload = bs.export_backup_zip()
        broken = _mutate_manifest(
            payload, lambda m: m.update({"format_version": 1}))
        with pytest.raises(bs.BackupValidationError) as exc:
            bs.preview_backup(broken)
        assert exc.value.code == "unsupported_version"


class TestRestore:
    def test_roundtrip_replaces_current_data(self, temp_env):
        payload = bs.export_backup_zip()
        db.add_transaction(Transaction(
            fund_code="005827", action="buy", date="2026-02-02",
            amount=500.0, channel="支付宝"))
        assert len(db.get_transactions_desc()) == 2

        result = bs.restore_backup(payload, username="tester")
        assert result.total_rows > 0
        assert len(db.get_transactions_desc()) == 1
        assert result.safety_backup.startswith("pre_restore_")
        safety = Path(config.DATA_DIR) / "backups" / result.safety_backup
        assert safety.is_file()

    def test_failure_rolls_back(self, temp_env, monkeypatch):
        payload = bs.export_backup_zip()
        db.add_transaction(Transaction(
            fund_code="005827", action="buy", date="2026-02-02",
            amount=500.0, channel="支付宝"))

        def boom(*args, **kwargs):
            raise RuntimeError("audit down")

        monkeypatch.setattr(bs.db, "log_audit", boom)
        with pytest.raises(RuntimeError):
            bs.restore_backup(payload)
        # 事务回滚：恢复前的两笔交易仍在。
        assert len(db.get_transactions_desc()) == 2

    def test_busy_guard(self, temp_env):
        payload = bs.export_backup_zip()
        assert bs._restore_guard.acquire(blocking=False)
        try:
            with pytest.raises(bs.BackupBusyError):
                bs.restore_backup(payload)
        finally:
            bs._restore_guard.release()
