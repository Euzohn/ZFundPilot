"""备份格式 v2 测试：导出、预检、恢复、损坏/重复/回滚。"""
from __future__ import annotations

import io
import json
import struct
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


def _understate_sizes(payload: bytes, declared: int) -> bytes:
    """把各条目中央目录与本地头声明的解压大小低报为 declared（模拟恶意构造）。"""
    data = bytearray(payload)
    eocd = data.rfind(b"PK\x05\x06")
    assert eocd >= 0
    count = struct.unpack_from("<H", data, eocd + 10)[0]
    pos = struct.unpack_from("<I", data, eocd + 16)[0]
    for _ in range(count):
        assert data[pos:pos + 4] == b"PK\x01\x02"
        fname_len, extra_len, comment_len = struct.unpack_from(
            "<HHH", data, pos + 28)
        local = struct.unpack_from("<I", data, pos + 42)[0]
        struct.pack_into("<I", data, pos + 24, declared)
        assert data[local:local + 4] == b"PK\x03\x04"
        struct.pack_into("<I", data, local + 22, declared)
        pos += 46 + fname_len + extra_len + comment_len
    return bytes(data)


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
        assert set(manifest["excluded"]) == set(bs.EXCLUDED_TABLES)
        # 待审批提案不进备份，恢复时也会被清空（避免指向已替换的数据）。
        assert "operation_proposals" in manifest["excluded"]

    def test_all_db_tables_registered(self, temp_env):
        """每张表必须进备份白名单或显式排除（带理由），防止新表「隐形」。"""
        with db.get_connection() as conn:
            tables = {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master "
                    "WHERE type='table' AND name NOT LIKE 'sqlite_%'"
                )
            }
        covered = set(bs.TABLE_COLUMNS) | set(bs.EXCLUDED_TABLES)
        assert tables <= covered, f"未登记的表：{sorted(tables - covered)}"
        assert all(reason for reason in bs.EXCLUDED_TABLES.values())

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

    def test_restore_clears_stale_proposals(self, temp_env):
        """恢复后旧提案必须清空，避免指向已被替换的账本数据。"""
        payload = bs.export_backup_zip()
        with db.get_connection(write=True) as conn:
            db.insert_proposal(
                conn, principal_type="agent_token", principal_id="1",
                token_prefix="zfag_test", operation_type="add_transaction",
                status="pending", params_json="{}",
                params_digest="x" * 64, summary_json="{}",
                risk_level="medium", created_at="2026-01-01T00:00:00+08:00",
                expires_at="2099-01-01T00:00:00+08:00")
        with db.get_connection() as conn:
            assert db.count_proposals(conn) == 1

        bs.restore_backup(payload, username="tester")

        with db.get_connection() as conn:
            assert db.count_proposals(conn) == 0

    def test_restore_keeps_valuation_cache(self, temp_env):
        """估值缓存不进备份，恢复也不清空（可重建缓存，保留现状）。"""
        db.upsert_index_valuation(
            index_code="000300", index_name="沪深300", pe=12.5,
            pe_percentile=45.0, pb=1.4, pb_percentile=40.0, window="10y",
            window_months=120, temperature="fair", history_months=260,
            data_date="2026-10-31", source="legulegu", payload="[]",
            updated_at="2026-11-15T00:00:00")
        payload = bs.export_backup_zip()
        assert "index_valuation" in bs.EXCLUDED_TABLES

        bs.restore_backup(payload, username="tester")

        row = db.get_index_valuation("000300")
        assert row is not None and row["pe"] == 12.5

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


class TestZipUncompressedLimits:
    def test_header_total_precheck(self, temp_env, monkeypatch):
        """头声明合计超限：预检即拒绝。"""
        monkeypatch.setattr(bs, "MAX_UNCOMPRESSED_BYTES", 100)
        payload = bs.export_backup_zip()
        with pytest.raises(bs.BackupValidationError) as exc:
            bs.preview_backup(payload)
        assert exc.value.code == "file_too_large"

    def test_underreported_sizes_cannot_bypass(self, temp_env, monkeypatch):
        """低报 ZIP 头 file_size 不能绕过总量防线：必须被结构化拒绝。

        头合计（14×1 字节）远低于预算，预检放行；真实解压字节远超预算。
        不同 zipfile 实现下表现为预算超限或压缩流校验失败，均不得放行。
        """
        monkeypatch.setattr(bs, "MAX_UNCOMPRESSED_BYTES", 1024)
        payload = _understate_sizes(bs.export_backup_zip(), 1)
        with pytest.raises(bs.BackupValidationError) as exc:
            bs.preview_backup(payload)
        assert exc.value.code in ("file_too_large", "invalid_zip")

    def test_read_limited_budget_counts_actual_bytes(self):
        """总量预算按实际解压字节累计，头声明低报不影响强制上限。"""
        actual = b"x" * 3000
        info = zipfile.ZipInfo("tables/funds.jsonl")
        info.file_size = 10  # 恶意低报，单条目预检放行

        class _FakeZip:
            def open(self, _info):
                return io.BytesIO(actual)

        budget = bs._UncompressedBudget(1024)
        with pytest.raises(bs.BackupValidationError) as exc:
            bs._read_limited(
                _FakeZip(), info, bs.MAX_SINGLE_FILE_BYTES, budget)
        assert exc.value.code == "file_too_large"
        assert "总大小" in exc.value.message

    def test_budget_accumulates_across_entries(self):
        """预算跨条目累计：单条目不超限但合计超限仍拒绝。"""
        info = zipfile.ZipInfo("tables/funds.jsonl")
        info.file_size = 600

        class _FakeZip:
            def open(self, _info):
                return io.BytesIO(b"x" * 600)

        budget = bs._UncompressedBudget(1024)
        bs._read_limited(_FakeZip(), info, bs.MAX_SINGLE_FILE_BYTES, budget)
        assert budget.remaining == 424
        with pytest.raises(bs.BackupValidationError) as exc:
            bs._read_limited(
                _FakeZip(), info, bs.MAX_SINGLE_FILE_BYTES, budget)
        assert exc.value.code == "file_too_large"

    def test_corrupt_entry_stream_is_structured_error(self, temp_env):
        """条目压缩流损坏（如低报大小触发 CRC 失败）返回结构化校验错误。"""
        payload = _understate_sizes(bs.export_backup_zip(), 1)
        with pytest.raises(bs.BackupValidationError) as exc:
            bs.preview_backup(payload)
        assert exc.value.code in ("invalid_zip", "file_too_large")
