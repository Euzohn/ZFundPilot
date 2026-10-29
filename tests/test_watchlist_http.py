"""自选写入口 HTTP 测试：scope、写开关、幂等键、版本冲突与网页恢复。"""
from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory

import pytest
from fastapi.testclient import TestClient

from zfundpilot import agent_tokens, api, config, db
from zfundpilot.analysis import clear_analysis_cache
from zfundpilot.models import Fund

KEY_A = "http-key-aaaaaaaaaaaa"
KEY_B = "http-key-bbbbbbbbbbbb"
KEY_C = "http-key-cccccccccccc"
AGENT_ADD = "/api/agent/tools/watchlist"


@pytest.fixture
def temp_db(monkeypatch):
    with TemporaryDirectory() as d:
        monkeypatch.setattr(config, "DB_PATH", str(Path(d) / "test.db"))
        db.init_db()
        db.upsert_fund(Fund("005827", "易方达蓝筹精选", "混合型", "消费"))
        clear_analysis_cache()
        yield
        clear_analysis_cache()


@pytest.fixture
def client(temp_db, monkeypatch):
    monkeypatch.setattr(config, "AUTH_ENABLED", True)
    monkeypatch.setattr(config, "AUTH_SECRET", "test-secret")
    monkeypatch.setattr(config, "AUTH_USERNAME", "admin")
    monkeypatch.setattr(config, "AGENT_WRITE_ENABLED", True)
    return TestClient(api.app)


def _agent_headers(scopes: list[str]) -> dict[str, str]:
    plaintext, _ = agent_tokens.issue_token("test-agent", scopes)
    return {"Authorization": f"Bearer {plaintext}"}


def _web_headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {api._create_token()}"}


def _add(client: TestClient, headers: dict[str, str], *, key: str = KEY_A,
         code: str = "005827", note: str = "", group: str = ""):
    return client.post(
        AGENT_ADD,
        headers={**headers, "Idempotency-Key": key},
        json={"fund_code": code, "note": note, "group_name": group},
    )


class TestAgentWriteGate:
    def test_add_requires_write_scope(self, client):
        headers = _agent_headers([agent_tokens.SCOPE_WATCHLIST_READ])
        response = _add(client, headers)
        assert response.status_code == 403
        assert "watchlist:write" in response.json()["detail"]

    def test_write_switch_off_blocks_even_with_scope(self, client, monkeypatch):
        headers = _agent_headers([agent_tokens.SCOPE_WATCHLIST_WRITE])
        monkeypatch.setattr(config, "AGENT_WRITE_ENABLED", False)

        response = _add(client, headers)
        assert response.status_code == 403
        assert response.json()["detail"]["code"] == "write_disabled"
        assert db.get_watchlist() == []

    def test_missing_token_is_401(self, client):
        response = client.post(
            AGENT_ADD,
            headers={"Idempotency-Key": KEY_A},
            json={"fund_code": "005827"},
        )
        assert response.status_code == 401

    def test_missing_idempotency_key_is_422(self, client):
        headers = _agent_headers([agent_tokens.SCOPE_WATCHLIST_WRITE])
        response = client.post(
            AGENT_ADD, headers=headers, json={"fund_code": "005827"})

        assert response.status_code == 422
        assert response.json()["detail"]["field"] == "idempotency_key"
        assert db.get_watchlist() == []

    def test_unknown_field_is_422(self, client):
        headers = _agent_headers([agent_tokens.SCOPE_WATCHLIST_WRITE])
        response = client.post(
            AGENT_ADD,
            headers={**headers, "Idempotency-Key": KEY_A},
            json={"fund_code": "005827", "unexpected": True},
        )
        assert response.status_code == 422


class TestAgentWatchlistCrud:
    def test_add_then_replay(self, client):
        headers = _agent_headers([agent_tokens.SCOPE_WATCHLIST_WRITE])
        first = _add(client, headers, note="观察", group="核心")
        second = _add(client, headers, note="观察", group="核心")

        assert first.status_code == 200
        body = first.json()
        assert body["tool"] == "add_watchlist_item"
        assert body["data"]["revision"] == 1
        assert body["data"]["replayed"] is False
        assert second.json()["data"]["replayed"] is True
        assert second.json()["data"]["operation_id"] == body["data"]["operation_id"]
        assert len(db.get_watchlist()) == 1

    def test_update_uses_revision_and_reports_conflict(self, client):
        headers = _agent_headers([agent_tokens.SCOPE_WATCHLIST_WRITE])
        _add(client, headers)

        updated = client.patch(
            f"{AGENT_ADD}/005827",
            headers={**headers, "Idempotency-Key": KEY_B},
            json={"expected_revision": 1, "note": "新备注"},
        )
        stale = client.patch(
            f"{AGENT_ADD}/005827",
            headers={**headers, "Idempotency-Key": KEY_C},
            json={"expected_revision": 1, "note": "旧版本写入"},
        )

        assert updated.status_code == 200
        assert updated.json()["data"]["revision"] == 2
        assert stale.status_code == 409
        assert stale.json()["detail"]["code"] == "revision_conflict"
        assert db.get_watchlist()[0]["note"] == "新备注"

    def test_remove_requires_revision(self, client):
        headers = _agent_headers([agent_tokens.SCOPE_WATCHLIST_WRITE])
        _add(client, headers)

        missing = client.delete(f"{AGENT_ADD}/005827", headers=headers)
        removed = client.delete(
            f"{AGENT_ADD}/005827?expected_revision=1",
            headers={**headers, "Idempotency-Key": KEY_B},
        )

        assert missing.status_code == 422
        assert removed.status_code == 200
        assert removed.json()["data"]["revision"] == 2
        assert db.get_watchlist() == []

    def test_duplicate_add_returns_409(self, client):
        headers = _agent_headers([agent_tokens.SCOPE_WATCHLIST_WRITE])
        _add(client, headers, note="原")
        response = _add(client, headers, key=KEY_B, note="新")

        assert response.status_code == 409
        assert response.json()["detail"]["code"] == "already_exists"
        assert db.get_watchlist()[0]["note"] == "原"

    def test_unregistered_fund_is_rejected_without_writes(self, client):
        headers = _agent_headers([agent_tokens.SCOPE_WATCHLIST_WRITE])
        response = _add(client, headers, code="999999")

        assert response.status_code == 409
        assert response.json()["detail"]["code"] == "fund_not_registered"
        assert db.get_watchlist() == []


class TestWebWatchlist:
    def test_revision_flow_and_restore(self, client):
        headers = _web_headers()
        added = client.post(
            "/api/watchlist",
            headers={**headers, "Idempotency-Key": KEY_A},
            json={"code": "005827", "note": "\u524d\u503c", "group_name": "\u6838\u5fc3"},
        )
        assert added.status_code == 200
        assert added.json()["revision"] == 1

        listed = client.get("/api/watchlist", headers=headers)
        assert listed.status_code == 200
        assert listed.json()[0]["revision"] == 1

        grouped = client.put(
            "/api/watchlist/005827/group",
            headers={**headers, "Idempotency-Key": KEY_B},
            json={"group_name": "\u89c2\u5bdf", "expected_revision": 1},
        )
        assert grouped.status_code == 200
        assert grouped.json()["revision"] == 2

        removed = client.delete(
            "/api/watchlist/005827?expected_revision=2",
            headers={**headers, "Idempotency-Key": KEY_C},
        )
        assert removed.status_code == 200
        assert removed.json()["revision"] == 3
        assert client.get("/api/watchlist", headers=headers).json() == []

        deleted = client.get("/api/watchlist/deleted", headers=headers).json()
        assert deleted["items"][0]["revision"] == 3
        assert deleted["items"][0]["group_name"] == "\u89c2\u5bdf"

        restored = client.post(
            "/api/watchlist/005827/restore",
            headers={**headers, "Idempotency-Key": "http-key-dddddddddddd"},
            json={"expected_revision": 3},
        )
        assert restored.status_code == 200
        assert restored.json()["revision"] == 4
        assert client.get("/api/watchlist", headers=headers).json()[0]["note"] == "\u524d\u503c"

    def test_delete_without_revision_is_422(self, client):
        headers = _web_headers()
        client.post(
            "/api/watchlist",
            headers={**headers, "Idempotency-Key": KEY_A},
            json={"code": "005827"},
        )
        response = client.delete("/api/watchlist/005827", headers={
            **headers, "Idempotency-Key": KEY_B})
        assert response.status_code == 422

    def test_web_add_keeps_fund_lookup(self, client, monkeypatch):
        headers = _web_headers()
        called: list[str] = []

        class Meta:
            ok = True
            fund_name = "\u65b0\u57fa\u91d1"
            fund_type = "\u6df7\u5408\u578b"
            sector = "\u79d1\u6280"
            tracking_index = ""
            message = ""

        def fake_meta(code: str):
            called.append(code)
            return Meta()

        monkeypatch.setattr("zfundpilot.api.fetch_fund.fetch_fund_meta", fake_meta)
        monkeypatch.setattr(
            "zfundpilot.api.fetch_fund.save_sector_mapping",
            lambda code, sector: None,
        )

        response = client.post(
            "/api/watchlist",
            headers={**headers, "Idempotency-Key": KEY_A},
            json={"code": "000001"},
        )
        assert response.status_code == 200
        assert called == ["000001"]
        assert db.get_fund("000001") is not None


class TestCapabilities:
    def test_write_tools_are_flagged_and_follow_switch(self, client, monkeypatch):
        headers = _agent_headers([
            agent_tokens.SCOPE_WATCHLIST_READ,
            agent_tokens.SCOPE_WATCHLIST_WRITE,
        ])
        enabled = client.get("/api/agent/tools/capabilities", headers=headers).json()
        writes = {t["name"]: t for t in enabled["data"]["tools"]
                  if t["name"].endswith("_watchlist_item")}
        assert set(writes) == {
            "add_watchlist_item", "update_watchlist_item", "remove_watchlist_item"}
        assert all(t["risk"] == "write" for t in writes.values())
        assert all(t["enabled"] is True for t in writes.values())
        assert enabled["data"]["write_enabled"] is True

        monkeypatch.setattr(config, "AGENT_WRITE_ENABLED", False)
        disabled = client.get("/api/agent/tools/capabilities", headers=headers).json()
        writes = {t["name"]: t for t in disabled["data"]["tools"]
                  if t["name"].endswith("_watchlist_item")}
        assert all(t["enabled"] is False for t in writes.values())
        assert disabled["data"]["write_enabled"] is False
