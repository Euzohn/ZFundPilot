"""账本提案 HTTP 测试：scope、写开关、幂等、Agent 与网页权限隔离。"""
from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory

import pytest
from fastapi.testclient import TestClient

from zfundpilot import agent_tokens, api, config, db
from zfundpilot.analysis import clear_analysis_cache
from zfundpilot.models import Fund

KEY_A = "http-proposal-key-aaaa"
KEY_B = "http-proposal-key-bbbb"
AGENT_PROPOSALS = "/api/agent/tools/proposals"
WEB_PROPOSALS = "/api/proposals"

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


def _web_headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {api._create_token()}"}


def _create(client: TestClient, headers: dict[str, str], *,
            key: str = KEY_A, params: dict | None = None):
    return client.post(
        AGENT_PROPOSALS,
        headers={**headers, "Idempotency-Key": key},
        json={"operation_type": "add_transaction",
              "params": dict(params or BUY_PARAMS)},
    )


class TestProposalAgentGate:
    def test_create_requires_propose_scope(self, client):
        headers = _agent_headers([agent_tokens.SCOPE_TRANSACTIONS_READ])
        response = _create(client, headers)

        assert response.status_code == 403
        assert db.get_transactions_desc() == []

    def test_write_switch_off_blocks_create(self, client, monkeypatch):
        headers = _agent_headers([agent_tokens.SCOPE_TRANSACTIONS_PROPOSE])
        monkeypatch.setattr(config, "AGENT_WRITE_ENABLED", False)

        response = _create(client, headers)

        assert response.status_code == 403
        assert response.json()["detail"]["code"] == "write_disabled"
        assert db.get_transactions_desc() == []

    def test_missing_idempotency_key_is_422(self, client):
        headers = _agent_headers([agent_tokens.SCOPE_TRANSACTIONS_PROPOSE])
        response = client.post(
            AGENT_PROPOSALS, headers=headers,
            json={"operation_type": "add_transaction", "params": BUY_PARAMS})

        assert response.status_code == 422
        assert response.json()["detail"]["field"] == "idempotency_key"

    def test_unknown_field_is_422(self, client):
        headers = _agent_headers([agent_tokens.SCOPE_TRANSACTIONS_PROPOSE])
        response = client.post(
            AGENT_PROPOSALS,
            headers={**headers, "Idempotency-Key": KEY_A},
            json={"operation_type": "add_transaction",
                  "params": BUY_PARAMS, "unexpected": True})

        assert response.status_code == 422

    def test_agent_cannot_call_web_approval(self, client):
        headers = _agent_headers([agent_tokens.SCOPE_TRANSACTIONS_PROPOSE])
        pid = _create(client, headers).json()["data"]["proposal_id"]

        response = client.post(
            f"{WEB_PROPOSALS}/{pid}/approve", headers=headers)

        assert response.status_code == 401
        assert db.get_transactions_desc() == []


class TestProposalCreateAndRead:
    def test_create_then_replay(self, client):
        headers = _agent_headers([agent_tokens.SCOPE_TRANSACTIONS_PROPOSE])
        first = _create(client, headers)
        second = _create(client, headers)

        assert first.status_code == 201
        body = first.json()
        assert body["tool"] == "create_operation_proposal"
        assert body["data"]["status"] == "pending"
        assert body["data"]["replayed"] is False
        assert second.status_code == 200
        assert second.json()["data"]["replayed"] is True
        assert (second.json()["data"]["proposal_id"]
                == body["data"]["proposal_id"])
        assert db.get_transactions_desc() == []

    def test_same_key_different_params_is_409(self, client):
        headers = _agent_headers([agent_tokens.SCOPE_TRANSACTIONS_PROPOSE])
        _create(client, headers)
        response = _create(
            client, headers,
            params={**BUY_PARAMS, "amount": 2000.0})

        assert response.status_code == 409
        assert response.json()["detail"]["code"] == "idempotency_conflict"

    def test_unknown_operation_is_422(self, client):
        headers = _agent_headers([agent_tokens.SCOPE_TRANSACTIONS_PROPOSE])
        response = client.post(
            AGENT_PROPOSALS,
            headers={**headers, "Idempotency-Key": KEY_A},
            json={"operation_type": "delete_transaction", "params": {}})

        assert response.status_code == 422
        assert response.json()["detail"]["field"] == "operation_type"

    def test_get_own_proposal(self, client):
        headers = _agent_headers([agent_tokens.SCOPE_TRANSACTIONS_PROPOSE])
        pid = _create(client, headers).json()["data"]["proposal_id"]

        response = client.get(f"{AGENT_PROPOSALS}/{pid}", headers=headers)

        assert response.status_code == 200
        assert response.json()["data"]["proposal_id"] == pid
        assert response.json()["data"]["summary"]["fund_name"] == "易方达蓝筹精选"

    def test_get_other_token_proposal_is_404(self, client):
        owner = _agent_headers([agent_tokens.SCOPE_TRANSACTIONS_PROPOSE])
        other = _agent_headers([agent_tokens.SCOPE_TRANSACTIONS_PROPOSE])
        pid = _create(client, owner).json()["data"]["proposal_id"]

        response = client.get(f"{AGENT_PROPOSALS}/{pid}", headers=other)

        assert response.status_code == 404

    def test_list_only_own_proposals(self, client):
        owner = _agent_headers([agent_tokens.SCOPE_TRANSACTIONS_PROPOSE])
        other = _agent_headers([agent_tokens.SCOPE_TRANSACTIONS_PROPOSE])
        _create(client, owner)
        _create(client, owner, key=KEY_B,
                params={**BUY_PARAMS, "amount": 2000.0})

        own = client.get(AGENT_PROPOSALS, headers=owner)
        foreign = client.get(AGENT_PROPOSALS, headers=other)

        assert own.status_code == 200
        assert own.json()["data"]["total"] == 2
        assert foreign.json()["data"]["total"] == 0

    def test_cancel_pending_proposal(self, client):
        headers = _agent_headers([agent_tokens.SCOPE_TRANSACTIONS_PROPOSE])
        pid = _create(client, headers).json()["data"]["proposal_id"]

        response = client.delete(f"{AGENT_PROPOSALS}/{pid}", headers=headers)

        assert response.status_code == 200
        assert response.json()["data"]["status"] == "cancelled"
        assert db.get_transactions_desc() == []


class TestProposalWebApproval:
    def test_count_and_list(self, client):
        agent = _agent_headers([agent_tokens.SCOPE_TRANSACTIONS_PROPOSE])
        _create(client, agent)
        web = _web_headers()

        count = client.get(f"{WEB_PROPOSALS}/count", headers=web)
        listing = client.get(WEB_PROPOSALS, headers=web)

        assert count.status_code == 200
        assert count.json()["pending"] == 1
        assert listing.status_code == 200
        assert listing.json()["total"] == 1
        assert listing.json()["pending_count"] == 1

    def test_web_requires_login(self, client):
        assert client.get(f"{WEB_PROPOSALS}/count").status_code == 401
        assert client.get(WEB_PROPOSALS).status_code == 401

    def test_approve_writes_ledger_once(self, client):
        agent = _agent_headers([agent_tokens.SCOPE_TRANSACTIONS_PROPOSE])
        pid = _create(client, agent).json()["data"]["proposal_id"]
        web = _web_headers()

        approved = client.post(f"{WEB_PROPOSALS}/{pid}/approve", headers=web)
        again = client.post(f"{WEB_PROPOSALS}/{pid}/approve", headers=web)

        assert approved.status_code == 200
        assert approved.json()["status"] == "succeeded"
        assert approved.json()["execution_result"]["tx_id"] > 0
        assert again.status_code == 409
        txs = db.get_transactions_desc()
        assert len(txs) == 1
        assert txs[0].fund_code == "005827"
        assert txs[0].amount == 1000.0
        assert txs[0].fee == 1.0

    def test_reject_keeps_ledger_untouched(self, client):
        agent = _agent_headers([agent_tokens.SCOPE_TRANSACTIONS_PROPOSE])
        pid = _create(client, agent).json()["data"]["proposal_id"]
        web = _web_headers()

        response = client.post(
            f"{WEB_PROPOSALS}/{pid}/reject", headers=web,
            json={"reason": "参数不对"})

        assert response.status_code == 200
        assert response.json()["status"] == "rejected"
        assert response.json()["rejection_reason"] == "参数不对"
        assert db.get_transactions_desc() == []

    def test_approve_missing_proposal_is_404(self, client):
        response = client.post(
            f"{WEB_PROPOSALS}/9999/approve", headers=_web_headers())

        assert response.status_code == 404

    def test_approve_with_write_switch_off_is_403(self, client, monkeypatch):
        agent = _agent_headers([agent_tokens.SCOPE_TRANSACTIONS_PROPOSE])
        pid = _create(client, agent).json()["data"]["proposal_id"]
        web = _web_headers()
        monkeypatch.setattr(config, "AGENT_WRITE_ENABLED", False)

        response = client.post(f"{WEB_PROPOSALS}/{pid}/approve", headers=web)

        assert response.status_code == 403
        assert response.json()["detail"]["code"] == "write_disabled"
        assert db.get_transactions_desc() == []
        detail = client.get(f"{WEB_PROPOSALS}/{pid}", headers=web)
        assert detail.json()["status"] == "pending"

    def test_capabilities_gate_propose_by_write_switch(self, client):
        agent = _agent_headers([agent_tokens.SCOPE_TRANSACTIONS_PROPOSE])
        enabled = client.get(
            "/api/agent/tools/capabilities", headers=agent).json()

        propose = [t for t in enabled["data"]["tools"]
                   if t["name"] == "create_operation_proposal"][0]
        assert propose["risk"] == "propose"
        assert propose["enabled"] is True
        assert propose["requires_confirmation"] is True
