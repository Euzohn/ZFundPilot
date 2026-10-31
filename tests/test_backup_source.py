"""备份 source 列兼容性测试：旧 v2 列变体（无 source）恢复成功并补空串。"""
from __future__ import annotations

import hashlib
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
        clear_analysis_cache()
        yield
        clear_analysis_cache()


def _zip_files(payload: bytes) -> dict[str, bytes]:
    with zipfile.ZipFile(io.BytesIO(payload)) as zf:
        return {name: zf.read(name) for name in zf.namelist()}


def _rebuild(files: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, data in files.items():
            zf.writestr(name, data)
    return buf.getvalue()


def _strip_source_from_export(payload: bytes) -> bytes:
    """把新备份降级为不含 source 的旧 v2 列变体。"""
    files = _zip_files(payload)
    manifest = json.loads(files["manifest.json"])

    legacy_cols = list(bs.LEGACY_COLUMN_VARIANTS["transactions"][0])
    meta = dict(manifest["tables"]["transactions"])
    meta["columns"] = legacy_cols
    manifest["tables"]["transactions"] = meta

    rows = [json.loads(line) for line in files["tables/transactions.jsonl"]
            .decode("utf-8").splitlines() if line.strip()]
    legacy_rows = [{k: v for k, v in row.items() if k != "source"}
                   for row in rows]
    body = "\n".join(
        json.dumps(r, ensure_ascii=False) for r in legacy_rows) + "\n"

    meta["rows"] = len(legacy_rows)
    meta["sha256"] = hashlib.sha256(body.encode("utf-8")).hexdigest()
    manifest["tables"]["transactions"] = meta
    files["manifest.json"] = json.dumps(manifest, ensure_ascii=False).encode()
    files["tables/transactions.jsonl"] = body.encode("utf-8")
    return _rebuild(files)


class TestSourceColumnCompat:
    def test_export_includes_source(self, temp_env):
        db.add_transaction(Transaction(
            fund_code="005827", action="buy", date="2026-01-02",
            amount=1000.0, fee=1.0, channel="支付宝", source="agent"))
        payload = bs.export_backup_zip()
        files = _zip_files(payload)
        manifest = json.loads(files["manifest.json"])
        assert "source" in manifest["tables"]["transactions"]["columns"]
        rows = [json.loads(line) for line in
                files["tables/transactions.jsonl"].decode().splitlines()]
        assert rows[0]["source"] == "agent"

    def test_legacy_backup_without_source_restores_as_empty(self, temp_env):
        db.add_transaction(Transaction(
            fund_code="005827", action="buy", date="2026-01-02",
            amount=1000.0, fee=1.0, channel="支付宝", source="agent"))
        legacy = _strip_source_from_export(bs.export_backup_zip())

        preview = bs.preview_backup(legacy)
        assert preview.counts["transactions"] == 1

        result = bs.restore_backup(legacy)
        assert result.counts["transactions"] == 1
        tx = db.get_transactions_desc()[0]
        assert tx.source == ""
        # agent 直记来源在旧备份中不存在，恢复后保持空串（手动）语义。
        assert tx.amount == 1000.0

    def test_restore_clears_proposals_and_idempotency(self, temp_env):
        # 恢复应清空旧提案与幂等记录，避免指向已替换数据。
        with db.get_connection(write=True) as conn:
            conn.execute(
                "INSERT INTO operation_proposals("
                "principal_type, principal_id, token_prefix, "
                "operation_type, status, params_json, params_digest, "
                "summary_json, risk_level, created_at, expires_at) "
                "VALUES('agent_token','1','','add_transaction','pending',"
                "'{}','d','{}','medium','2026-01-01T00:00:00',"
                "'2026-01-08T00:00:00')")
            conn.execute(
                "INSERT INTO agent_operations("
                "principal_type, principal_id, key_hash, operation, "
                "params_digest, status, result_json, created_at) "
                "VALUES('agent_token','1','k','record_transaction','d',"
                "'succeeded','{}','2026-01-01T00:00:00')")

        legacy = _strip_source_from_export(bs.export_backup_zip())
        bs.restore_backup(legacy)

        with db.get_connection() as conn:
            assert int(conn.execute(
                "SELECT COUNT(*) FROM operation_proposals").fetchone()[0]) == 0
            assert int(conn.execute(
                "SELECT COUNT(*) FROM agent_operations").fetchone()[0]) == 0

    def test_new_backup_with_source_roundtrips(self, temp_env):
        db.add_transaction(Transaction(
            fund_code="005827", action="buy", date="2026-01-02",
            amount=1000.0, fee=1.0, channel="支付宝", source="agent"))

        payload = bs.export_backup_zip()
        bs.restore_backup(payload)
        tx = db.get_transactions_desc()[0]
        assert tx.source == "agent"
