"""数据刷新 HTTP 测试：scope、写开关、幂等、互斥与归属。"""
from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory

import pytest
from fastapi.testclient import TestClient

from zfundpilot import agent_tokens, api, config, db
from zfundpilot import refresh_service as svc
from zfundpilot.analysis import clear_analysis_cache
from zfundpilot.models import Fund

KEY_A = "http-refresh-key-aaaaaaaa"
KEY_B = "http-refresh-key-bbbbbbbbbb"
REFRESH = "/api/agent/tools/refresh"


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
    monkeypatch.setattr(svc, "_spawn", lambda fn: fn())

    class _Result:
        def __init__(self, code):
            self.fund_code = code
            self.ok = True
            self.message = ""
            self.code = "ok"

    monkeypatch.setattr(
        svc.fetch_fund, "update_all_holdings_nav",
        lambda codes, progress=None: [_Result(c) for c in codes])
    monkeypatch.setattr(svc.scheduler, "refresh_fund_metadata",
                        lambda on_phase=None: None)
    return TestClient(api.app)


def _agent_headers(scopes):
    plaintext, _ = agent_tokens.issue_token("test-agent", scopes)
    return {"Authorization": f"Bearer {plaintext}"}


def _start(client, headers, *, key=KEY_A, body=None):
    return client.post(
        REFRESH,
        headers={**headers, "Idempotency-Key": key},
        json=body or {},
    )


class TestRefreshGate:
    def test_requires_scope(self, client):
        response = _start(client, _agent_headers([agent_tokens.SCOPE_FUNDS_READ]))
        assert response.status_code == 403

    def test_write_switch_off_blocks(self, client, monkeypatch):
        monkeypatch.setattr(config, "AGENT_WRITE_ENABLED", False)
        response = _start(client, _agent_headers([agent_tokens.SCOPE_DATA_REFRESH]))
        assert response.status_code == 403
        assert response.json()["detail"]["code"] == "write_disabled"

    def test_missing_idempotency_is_422(self, client):
        headers = _agent_headers([agent_tokens.SCOPE_DATA_REFRESH])
        response = client.post(REFRESH, headers=headers, json={})
        assert response.status_code == 422
        assert response.json()["detail"]["field"] == "idempotency_key"


class TestRefreshJob:
    def test_start_poll_replay(self, client):
        headers = _agent_headers([agent_tokens.SCOPE_DATA_REFRESH])
        first = _start(client, headers, body={"fund_codes": ["005827"]})
        assert first.status_code == 202
        body = first.json()
        assert body["tool"] == "start_data_refresh"
        assert body["data"]["status"] == "queued"
        job_id = body["data"]["job_id"]

        status = client.get(f"{REFRESH}/{job_id}", headers=headers)
        assert status.status_code == 200
        data = status.json()["data"]
        assert data["status"] == "succeeded"
        assert data["result"]["updated"] == 1
        assert data["can_cancel"] is False

        replay = _start(client, headers, body={"fund_codes": ["005827"]})
        assert replay.status_code == 202
        assert replay.json()["data"]["replayed"] is True
        assert replay.json()["data"]["job_id"] == job_id

    def test_other_token_cannot_read(self, client):
        creator = _agent_headers([agent_tokens.SCOPE_DATA_REFRESH])
        other = _agent_headers([agent_tokens.SCOPE_DATA_REFRESH])
        job_id = _start(client, creator, body={"fund_codes": ["005827"]}).json()["data"]["job_id"]

        response = client.get(f"{REFRESH}/{job_id}", headers=other)
        assert response.status_code == 404
        assert response.json()["detail"]["code"] == "not_found"

    def test_busy_returns_409(self, client, monkeypatch):
        headers = _agent_headers([agent_tokens.SCOPE_DATA_REFRESH])
        monkeypatch.setattr(svc, "_spawn", lambda fn: None)
        monkeypatch.setitem(svc.nav_update_state, "running", True)
        response = _start(client, headers, body={"fund_codes": ["005827"]})
        assert response.status_code == 409
        assert response.json()["detail"]["code"] == "refresh_busy"

    def test_invalid_codes_422(self, client):
        headers = _agent_headers([agent_tokens.SCOPE_DATA_REFRESH])
        response = _start(client, headers, body={"fund_codes": ["abc"]})
        assert response.status_code == 422
        assert response.json()["detail"]["field"] == "fund_codes"

    def test_unknown_job_404(self, client):
        headers = _agent_headers([agent_tokens.SCOPE_DATA_REFRESH])
        response = client.get(f"{REFRESH}/999999", headers=headers)
        assert response.status_code == 404


class TestCapabilities:
    def test_refresh_tools_flagged(self, client, monkeypatch):
        headers = _agent_headers([agent_tokens.SCOPE_DATA_REFRESH])
        data = client.get("/api/agent/tools/capabilities", headers=headers).json()["data"]
        tools = {t["name"]: t for t in data["tools"]}
        start = tools["start_data_refresh"]
        status = tools["get_job_status"]
        assert start["risk"] == "write"
        assert start["enabled"] is True
        assert status["risk"] == "read"

        monkeypatch.setattr(config, "AGENT_WRITE_ENABLED", False)
        data = client.get("/api/agent/tools/capabilities", headers=headers).json()["data"]
        tools = {t["name"]: t for t in data["tools"]}
        assert tools["start_data_refresh"]["enabled"] is False
