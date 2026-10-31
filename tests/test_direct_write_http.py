"""可信单笔直记 HTTP 测试：scope、写开关、限流、注册与回执信封。"""
from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory

import pytest
from fastapi.testclient import TestClient

from zfundpilot import agent_tokens, api, config, db
from zfundpilot.analysis import clear_analysis_cache
from zfundpilot.models import Fund

KEY_A = "http-direct-key-aaaa"
KEY_B = "http-direct-key-bbbb"
ENDPOINT = "/api/agent/tools/transactions"
PROPOSAL_ENDPOINT = "/api/agent/tools/proposals"

BUY_PARAMS = {
    "fund_code": "005827",
    "action": "buy",
    "date": "2026-01-02",
    "amount": 1000.0,
    "fee": 1.0,
    "channel": "支付宝",
}


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


def _post(client: TestClient, headers: dict[str, str], *,
          key: str = KEY_A, params: dict | None = None):
    return client.post(
        ENDPOINT,
        headers={**headers, "Idempotency-Key": key},
        json=dict(params or BUY_PARAMS),
    )


class TestDirectWriteGate:
    def test_requires_create_scope(self, client):
        headers = _agent_headers([agent_tokens.SCOPE_TRANSACTIONS_READ])
        response = _post(client, headers)

        assert response.status_code == 403
        assert db.get_transactions_desc() == []

    def test_write_switch_off_blocks(self, client, monkeypatch):
        headers = _agent_headers([agent_tokens.SCOPE_TRANSACTIONS_CREATE])
        monkeypatch.setattr(config, "AGENT_WRITE_ENABLED", False)

        response = _post(client, headers)

        assert response.status_code == 403
        assert response.json()["detail"]["code"] == "write_disabled"
        assert db.get_transactions_desc() == []

    def test_missing_idempotency_key_is_422(self, client):
        headers = _agent_headers([agent_tokens.SCOPE_TRANSACTIONS_CREATE])
        response = client.post(
            ENDPOINT, headers=headers, json=BUY_PARAMS)

        assert response.status_code == 422
        assert response.json()["detail"]["field"] == "idempotency_key"

    def test_future_date_is_422_future_date(self, client):
        headers = _agent_headers([agent_tokens.SCOPE_TRANSACTIONS_CREATE])
        response = _post(
            client, headers, params={**BUY_PARAMS, "date": "2999-01-01"})

        assert response.status_code == 422
        assert response.json()["detail"]["code"] == "future_date"

    def test_post_does_not_collide_with_get_list(self, client):
        headers = _agent_headers([agent_tokens.SCOPE_TRANSACTIONS_READ])

        response = client.get(ENDPOINT, headers=headers)

        assert response.status_code == 200
        assert response.json()["tool"] == "list_transactions"


class TestDirectWriteResults:
    def test_direct_success_envelope(self, client):
        headers = _agent_headers([agent_tokens.SCOPE_TRANSACTIONS_CREATE])
        response = _post(client, headers)

        assert response.status_code == 201
        body = response.json()
        assert body["tool"] == "record_transaction"
        assert body["data"]["execution_mode"] == "direct"
        assert body["data"]["transaction_id"] > 0
        assert body["data"]["daily_quota"]["used"] == 1

    def test_replay_returns_200_same_transaction(self, client):
        headers = _agent_headers([agent_tokens.SCOPE_TRANSACTIONS_CREATE])
        first = _post(client, headers)
        second = _post(client, headers)

        assert second.status_code == 200
        assert second.json()["data"]["replayed"] is True
        assert (second.json()["data"]["transaction_id"]
                == first.json()["data"]["transaction_id"])
        assert len(db.get_transactions_desc()) == 1

    def test_downgrade_envelope_when_no_propose(self, client):
        headers = _agent_headers([agent_tokens.SCOPE_TRANSACTIONS_CREATE])
        _post(client, headers)
        response = _post(client, headers, key=KEY_B)

        assert response.status_code == 409
        assert response.json()["detail"]["code"] == "duplicate_candidate"
        assert len(db.get_transactions_desc()) == 1

    def test_downgrade_envelope_when_propose(self, client):
        headers = _agent_headers(
            [agent_tokens.SCOPE_TRANSACTIONS_CREATE,
             agent_tokens.SCOPE_TRANSACTIONS_PROPOSE])
        _post(client, headers)
        response = _post(client, headers, key=KEY_B)

        assert response.status_code == 201
        body = response.json()
        assert body["data"]["execution_mode"] == "proposal"
        assert body["data"]["proposal_id"] > 0
        assert body["data"]["verify_path"] == "/proposals"
        assert len(db.get_transactions_desc()) == 1

    def test_capabilities_registers_record_transaction_with_fallback(
            self, client):
        headers = _agent_headers([agent_tokens.SCOPE_TRANSACTIONS_CREATE])

        response = client.get(
            "/api/agent/tools/capabilities", headers=headers)

        tools = response.json()["data"]["tools"]
        record = next(
            (t for t in tools if t["name"] == "record_transaction"), None)
        assert record is not None
        assert record["risk"] == "write"
        assert record["fallback_tool"] == "create_operation_proposal"

    def test_fallback_proposal_available_when_create_only(self, client):
        headers = _agent_headers(
            [agent_tokens.SCOPE_TRANSACTIONS_CREATE,
             agent_tokens.SCOPE_TRANSACTIONS_PROPOSE])

        response = client.get(
            "/api/agent/tools/capabilities", headers=headers)

        names = {t["name"] for t in response.json()["data"]["tools"]}
        assert "record_transaction" in names
        assert "create_operation_proposal" in names

    def test_quota_exceeded_is_429(self, client, monkeypatch):
        monkeypatch.setattr(config, "AGENT_TX_DAILY_COUNT", 1)
        headers = _agent_headers([agent_tokens.SCOPE_TRANSACTIONS_CREATE])
        _post(client, headers)
        response = _post(client, headers, key=KEY_B)

        assert response.status_code == 429
        assert response.json()["detail"]["code"] == "daily_quota_exceeded"
