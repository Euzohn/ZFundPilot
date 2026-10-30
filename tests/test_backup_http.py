"""备份 HTTP 测试：导出、预检、确认恢复与错误码。"""
from __future__ import annotations

import io
import zipfile
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest
from fastapi.testclient import TestClient

from zfundpilot import api, config, db
from zfundpilot import backup_service as bs
from zfundpilot.analysis import clear_analysis_cache
from zfundpilot.models import Fund, Transaction

PREFLIGHT = "/api/backup/preflight"
RESTORE = "/api/backup/restore"


@pytest.fixture
def temp_env(monkeypatch):
    with TemporaryDirectory() as d:
        monkeypatch.setattr(config, "DB_PATH", str(Path(d) / "test.db"))
        monkeypatch.setattr(config, "DATA_DIR", d)
        monkeypatch.setattr(config, "AUTH_ENABLED", False)
        db.init_db()
        db.upsert_fund(Fund("005827", "易方达蓝筹精选", "混合型", "消费"))
        db.add_transaction(Transaction(
            fund_code="005827", action="buy", date="2026-01-02",
            amount=1000.0, channel="支付宝"))
        clear_analysis_cache()
        yield
        clear_analysis_cache()


@pytest.fixture
def client(temp_env):
    return TestClient(api.app)


def _backup() -> bytes:
    return bs.export_backup_zip()


def _upload(payload: bytes):
    return {"file": ("backup.zip", payload, "application/zip")}


class TestBackupHttp:
    def test_export_is_v2_zip(self, client):
        response = client.get("/api/export/zip")
        assert response.status_code == 200
        with zipfile.ZipFile(io.BytesIO(response.content)) as zf:
            assert "manifest.json" in zf.namelist()
            assert "tables/nav_history.jsonl" in zf.namelist()

    def test_preflight_returns_counts(self, client):
        response = client.post(PREFLIGHT, files=_upload(_backup()))
        assert response.status_code == 200
        data = response.json()
        assert data["format_version"] == bs.FORMAT_VERSION
        assert data["tables"]["funds"]["rows"] == 1
        assert data["replace_all"] is True
        assert data["warnings"]

    def test_preflight_rejects_corrupt(self, client):
        response = client.post(
            PREFLIGHT, files=_upload(b"not a zip"))
        assert response.status_code == 422
        assert response.json()["detail"]["code"] == "invalid_zip"

    def test_restore_requires_confirmation(self, client):
        response = client.post(RESTORE, files=_upload(_backup()),
                               data={"confirmation": "nope"})
        assert response.status_code == 400
        assert response.json()["detail"]["code"] == "confirmation_required"

    def test_restore_replaces_data(self, client):
        payload = _backup()
        db.add_transaction(Transaction(
            fund_code="005827", action="buy", date="2026-02-02",
            amount=500.0, channel="支付宝"))
        assert len(db.get_transactions_desc()) == 2

        response = client.post(RESTORE, files=_upload(payload),
                               data={"confirmation": "RESTORE"})
        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is True
        assert data["total_rows"] > 0
        assert data["safety_backup"]
        assert len(db.get_transactions_desc()) == 1

    def test_restore_busy(self, client):
        assert bs._restore_guard.acquire(blocking=False)
        try:
            response = client.post(RESTORE, files=_upload(_backup()),
                                   data={"confirmation": "RESTORE"})
        finally:
            bs._restore_guard.release()
        assert response.status_code == 409
        assert response.json()["detail"]["code"] == "restore_busy"
