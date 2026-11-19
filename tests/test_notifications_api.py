"""统一站内提醒中心 API 测试（P3 Phase 2）。

覆盖：列表分页/白名单 422、count、read/dismiss 批量上限与二选一校验、
不写审计（D8）、title_params 解析。
"""
from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory

import pytest
from fastapi.testclient import TestClient

from zfundpilot import api, config, db
from zfundpilot import notification_service as ns


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


def _seed(n: int = 3) -> list[int]:
    ids = []
    for i in range(n):
        ns.notify("dividend", str(i + 1), f"dividend:{i}", "dividend_detected",
                  {"fund_code": f"00{i}", "ex_date": "2026-11-11"})
        ids.append(db.list_notifications(limit=1)[0]["id"])
    return ids


def _audit_count() -> int:
    with db.get_connection() as conn:
        return int(conn.execute("SELECT COUNT(*) c FROM audit_log").fetchone()["c"])


class TestList:
    def test_default_pagination_shape(self, client):
        _seed(3)
        body = client.get("/api/notifications").json()
        assert body["pagination"] == {"limit": 50, "offset": 0, "total": 3,
                                      "has_more": False}
        assert len(body["items"]) == 3
        item = body["items"][0]
        assert item["title_code"] == "dividend_detected"
        assert isinstance(item["title_params"], dict)
        assert item["title_params"]["ex_date"] == "2026-11-11"
        assert item["status"] == "unread"

    def test_newest_first_and_offset(self, client):
        _seed(3)
        body = client.get("/api/notifications?limit=2&offset=2").json()
        assert len(body["items"]) == 1
        assert body["pagination"]["has_more"] is False
        assert body["pagination"]["total"] == 3

    def test_status_and_source_filters(self, client):
        _seed(2)
        ns.notify("job", "9", "job:failed:9", "job_failed", {"job_id": 9})
        first = db.list_notifications(limit=100)[-1]["id"]
        client.post("/api/notifications/read", json={"ids": [first]})
        assert len(client.get("/api/notifications?status=read").json()["items"]) == 1
        assert len(client.get("/api/notifications?status=unread").json()["items"]) == 2
        assert len(client.get(
            "/api/notifications?source_type=job").json()["items"]) == 1

    def test_invalid_status_422(self, client):
        resp = client.get("/api/notifications?status=bogus")
        assert resp.status_code == 422
        assert resp.json()["error"]["code"] == "validation_error"

    def test_invalid_source_type_422(self, client):
        resp = client.get("/api/notifications?source_type=bogus")
        assert resp.status_code == 422
        assert resp.json()["error"]["code"] == "validation_error"

    @pytest.mark.parametrize("query", ["limit=0", "limit=1001", "offset=-1"])
    def test_limit_offset_bounds_422(self, client, query):
        assert client.get(f"/api/notifications?{query}").status_code == 422


class TestCount:
    def test_default_unread(self, client):
        _seed(3)
        assert client.get("/api/notifications/count").json() == {"count": 3}

    def test_explicit_status(self, client):
        ids = _seed(2)
        client.post("/api/notifications/read", json={"ids": [ids[0]]})
        assert client.get("/api/notifications/count?status=read").json() == {"count": 1}

    def test_invalid_status_422(self, client):
        assert client.get("/api/notifications/count?status=bogus").status_code == 422


class TestReadDismiss:
    def test_read_by_ids(self, client):
        ids = _seed(3)
        body = client.post("/api/notifications/read",
                           json={"ids": ids[:2]}).json()
        assert body == {"ok": True, "updated": 2}
        assert client.get("/api/notifications/count").json() == {"count": 1}

    def test_read_all(self, client):
        _seed(3)
        body = client.post("/api/notifications/read", json={"all": True}).json()
        assert body["updated"] == 3
        assert client.get("/api/notifications/count").json() == {"count": 0}

    def test_dismiss_by_ids_and_all(self, client):
        ids = _seed(3)
        assert client.post("/api/notifications/dismiss",
                           json={"ids": [ids[0]]}).json()["updated"] == 1
        assert client.post("/api/notifications/dismiss",
                           json={"all": True}).json()["updated"] == 2
        assert client.get("/api/notifications/count?status=dismissed").json() == {"count": 3}

    def test_read_does_not_revive_dismissed(self, client):
        ids = _seed(1)
        client.post("/api/notifications/dismiss", json={"ids": ids})
        assert client.post("/api/notifications/read",
                           json={"all": True}).json()["updated"] == 0

    def test_no_audit_written(self, client):
        """D8：read/dismiss 是 UI 展示态，不写审计日志。"""
        ids = _seed(2)
        before = _audit_count()
        client.post("/api/notifications/read", json={"ids": ids})
        client.post("/api/notifications/dismiss", json={"all": True})
        assert _audit_count() == before

    @pytest.mark.parametrize("payload", [
        {},                          # 两者都缺
        {"ids": [1], "all": True},   # 两者都给
        {"ids": []},                 # 空列表
        {"ids": list(range(501))},   # 超 500 上限
    ])
    def test_invalid_body_422(self, client, payload):
        resp = client.post("/api/notifications/read", json=payload)
        assert resp.status_code == 422

    def test_dismiss_same_validation(self, client):
        assert client.post("/api/notifications/dismiss",
                           json={"ids": [1], "all": True}).status_code == 422
