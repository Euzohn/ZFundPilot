"""审计日志筛选与分页测试：action / username / 时间范围 / offset。

直插 ``audit_log`` 以获得确定的 ``ts``，覆盖纯日期与完整 ISO 时间串两种边界。
"""
from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest
from fastapi.testclient import TestClient

from zfundpilot import api, config, db


@pytest.fixture
def temp_db(monkeypatch):
    with TemporaryDirectory() as d:
        monkeypatch.setattr(config, "DB_PATH", str(Path(d) / "test.db"))
        db.init_db()
        yield


@pytest.fixture
def client(temp_db, monkeypatch):
    monkeypatch.setattr(api, "_REQ_LOGS", {})
    monkeypatch.setattr(api, "_AGENT_REQ_LOGS", {})
    return TestClient(api.app)


def _insert(ts: str, action: str, username: str | None = None,
            detail: dict | None = None) -> int:
    with db.get_connection() as conn:
        cursor = conn.execute(
            "INSERT INTO audit_log(ts, ip, username, action, detail) "
            "VALUES(?,?,?,?,?)",
            (ts, "127.0.0.1", username, action,
             None if detail is None else json.dumps(detail, ensure_ascii=False)),
        )
        return int(cursor.lastrowid)


def _seed() -> None:
    _insert("2026-11-01T09:00:00+08:00", "login_success", "admin")
    _insert("2026-11-02T10:00:00+08:00", "proposal_created", "admin")
    _insert("2026-11-02T23:59:59+08:00", "proposal_approved", "admin")
    _insert("2026-11-03T08:00:00+08:00", "login_failed", "guest")


class TestFetchAuditLogs:
    def test_default_newest_first(self, temp_db):
        _seed()
        rows = db.fetch_audit_logs()
        assert [r["action"] for r in rows] == [
            "login_failed", "proposal_approved", "proposal_created",
            "login_success",
        ]

    def test_limit_keeps_positional_semantics(self, temp_db):
        _seed()
        rows = db.fetch_audit_logs(2)
        assert len(rows) == 2
        assert rows[0]["action"] == "login_failed"

    def test_action_filter(self, temp_db):
        _seed()
        rows = db.fetch_audit_logs(action="proposal_created")
        assert [r["action"] for r in rows] == ["proposal_created"]

    def test_username_filter(self, temp_db):
        _seed()
        rows = db.fetch_audit_logs(username="guest")
        assert [r["action"] for r in rows] == ["login_failed"]

    def test_date_only_range_is_inclusive(self, temp_db):
        _seed()
        rows = db.fetch_audit_logs(ts_from="2026-11-02", ts_to="2026-11-02")
        assert [r["action"] for r in rows] == [
            "proposal_approved", "proposal_created",
        ]

    def test_full_iso_range(self, temp_db):
        _seed()
        rows = db.fetch_audit_logs(
            ts_from="2026-11-02T10:00:00+08:00",
            ts_to="2026-11-02T10:00:00+08:00",
        )
        assert [r["action"] for r in rows] == ["proposal_created"]

    def test_offset_pagination(self, temp_db):
        _seed()
        first = db.fetch_audit_logs(2)
        second = db.fetch_audit_logs(2, offset=2)
        assert [r["action"] for r in first] == [
            "login_failed", "proposal_approved",
        ]
        assert [r["action"] for r in second] == [
            "proposal_created", "login_success",
        ]

    def test_filters_combine(self, temp_db):
        _seed()
        rows = db.fetch_audit_logs(
            action="proposal_approved", username="admin",
            ts_from="2026-11-02", ts_to="2026-11-02",
        )
        assert len(rows) == 1
        assert rows[0]["action"] == "proposal_approved"


class TestAuditEndpoint:
    def test_filters_and_pagination(self, client):
        _seed()
        resp = client.get(
            "/api/audit",
            params={"username": "admin",
                    "from": "2026-11-02", "to": "2026-11-02",
                    "limit": 1, "offset": 1},
        )
        assert resp.status_code == 200, resp.text
        rows = resp.json()
        # 当天 admin 两条，倒序第二条是较早的 proposal_created
        assert [r["action"] for r in rows] == ["proposal_created"]

    def test_default_shape_unchanged(self, client):
        _seed()
        resp = client.get("/api/audit")
        assert resp.status_code == 200
        rows = resp.json()
        assert isinstance(rows, list)
        assert set(rows[0]) == {"id", "ts", "ip", "username", "action", "detail"}

    def test_invalid_from_format(self, client):
        resp = client.get("/api/audit?from=2026/11/02")
        assert resp.status_code == 422

    def test_from_later_than_to(self, client):
        resp = client.get("/api/audit?from=2026-11-03&to=2026-11-02")
        assert resp.status_code == 422
        body = resp.json()
        assert body["error"]["code"] == "validation_error"
        assert body["detail"]["field"] == "from"

    def test_empty_string_filter_rejected(self, client):
        assert client.get("/api/audit?action=").status_code == 422
