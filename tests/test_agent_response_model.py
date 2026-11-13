"""Agent 四类响应模型契约：查询 / 写入 / 提案 / 作业。

锁定文档「四类响应模型」的关键字段与枚举，避免无意中改动响应形状。
"""
from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest
from fastapi.testclient import TestClient

from zfundpilot import agent_tokens, api, config, db
from zfundpilot import proposal_service as svc
from zfundpilot.models import Fund

BUY_PARAMS = {
    "fund_code": "005827",
    "action": "buy",
    "date": "2026-01-02",
    "amount": 1000.0,
    "fee": 1.0,
    "channel": "支付宝",
}

ENVELOPE_KEYS = {
    "schema_version", "tool", "request_id", "generated_at", "currency", "data",
}


@pytest.fixture
def temp_db(monkeypatch):
    with TemporaryDirectory() as d:
        monkeypatch.setattr(config, "DB_PATH", str(Path(d) / "test.db"))
        monkeypatch.setattr(config, "AUTH_ENABLED", True)
        monkeypatch.setattr(config, "AUTH_SECRET", "test-secret")
        monkeypatch.setattr(config, "AUTH_USERNAME", "admin")
        monkeypatch.setattr(config, "AGENT_WRITE_ENABLED", True)
        db.init_db()
        db.upsert_fund(Fund("005827", "易方达蓝筹精选", "混合型", "消费"))
        yield


@pytest.fixture
def client(temp_db, monkeypatch):
    monkeypatch.setattr(api, "_REQ_LOGS", {})
    monkeypatch.setattr(api, "_AGENT_REQ_LOGS", {})
    return TestClient(api.app)


def _issue(*scopes: str) -> tuple[dict[str, str], int]:
    plaintext, info = agent_tokens.issue_token("response-model", list(scopes))
    return {"Authorization": f"Bearer {plaintext}"}, int(info["id"])


class TestQueryClass:
    def test_envelope_and_query_fields(self, client):
        headers, _ = _issue(agent_tokens.SCOPE_PORTFOLIO_READ)
        resp = client.get("/api/agent/tools/positions?limit=5", headers=headers)
        assert resp.status_code == 200
        body = resp.json()
        assert set(body) == ENVELOPE_KEYS
        assert body["schema_version"] == 1
        assert body["currency"] == "CNY"
        data = body["data"]
        # 查询类没有 ok/code/replayed，金额类带估值口径。
        assert "ok" not in data and "replayed" not in data
        assert data["valuation_basis"] == "latest_formal_nav"
        for key in ("count", "total", "limit", "positions"):
            assert key in data
        assert "pagination" not in data

    def test_paginated_list_uses_pagination_block(self, client):
        headers, _ = _issue(agent_tokens.SCOPE_TRANSACTIONS_READ)
        resp = client.get(
            "/api/agent/tools/transactions?limit=10&offset=0", headers=headers)
        assert resp.status_code == 200
        pagination = resp.json()["data"]["pagination"]
        assert set(pagination) == {"limit", "offset", "total", "has_more"}


class TestWriteClass:
    def test_watchlist_add_shape_and_replay(self, client):
        headers, _ = _issue(agent_tokens.SCOPE_WATCHLIST_WRITE)
        payload = {"fund_code": "005827", "note": "观察", "group_name": "核心"}
        key = "response-model-watchlist-key"
        first = client.post(
            "/api/agent/tools/watchlist", headers={**headers,
                                                   "Idempotency-Key": key},
            json=payload)
        assert first.status_code == 200, first.text
        data = first.json()["data"]
        for field in ("ok", "code", "message", "replayed", "fund_code",
                      "revision", "changed"):
            assert field in data
        assert data["ok"] is True and data["replayed"] is False
        assert data["code"] == "created"

        second = client.post(
            "/api/agent/tools/watchlist", headers={**headers,
                                                   "Idempotency-Key": key},
            json=payload)
        assert second.status_code == 200
        replayed = second.json()["data"]
        assert replayed["replayed"] is True
        assert replayed["revision"] == data["revision"]


class TestProposalClass:
    def test_create_proposal_shape(self, client):
        headers, _ = _issue(agent_tokens.SCOPE_TRANSACTIONS_PROPOSE)
        resp = client.post(
            "/api/agent/tools/proposals",
            headers={**headers, "Idempotency-Key": "response-model-proposal-key"},
            json={"operation_type": "add_transaction", "params": BUY_PARAMS},
        )
        assert resp.status_code == 201, resp.text
        data = resp.json()["data"]
        for field in ("ok", "code", "replayed", "proposal_id", "status",
                      "expires_at", "summary", "can_approve", "can_cancel",
                      "execution_result"):
            assert field in data
        assert data["status"] == "pending"
        assert data["can_approve"] is True and data["can_cancel"] is True
        assert data["execution_result"] is None

    def test_documented_status_enum_matches_constants(self):
        documented = {
            "pending", "succeeded", "failed", "conflict",
            "rejected", "cancelled", "expired",
        }
        actual = {
            svc.STATUS_PENDING, svc.STATUS_SUCCEEDED, svc.STATUS_FAILED,
            svc.STATUS_CONFLICT, svc.STATUS_REJECTED, svc.STATUS_CANCELLED,
            svc.STATUS_EXPIRED,
        }
        assert actual == documented
        # 批准成功是 succeeded，不引入含糊的 approved。
        assert "approved" not in actual


class TestJobClass:
    def test_job_status_shape(self, client):
        headers, token_id = _issue(agent_tokens.SCOPE_DATA_REFRESH)
        now = datetime.now(config.TIMEZONE)
        with db.get_connection(write=True) as conn:
            job_id = db.insert_refresh_job(
                conn, principal_type="agent_token",
                principal_id=str(token_id), job_type="data_refresh",
                params_digest="digest", status="succeeded",
                created_at=now.isoformat(), updated_at=now.isoformat(),
                expires_at=(now + timedelta(days=7)).isoformat(),
            )
        resp = client.get(
            f"/api/agent/tools/refresh/{job_id}", headers=headers)
        assert resp.status_code == 200, resp.text
        data = resp.json()["data"]
        for field in ("job_id", "job_type", "status", "progress", "result",
                      "error", "created_at", "updated_at", "expires_at",
                      "can_cancel"):
            assert field in data
        assert data["job_type"] == "data_refresh"
        assert set(data["progress"]) == {"done", "total", "current", "phase"}
        assert data["can_cancel"] is False

    def test_other_token_cannot_read_job(self, client):
        _headers, owner_id = _issue(agent_tokens.SCOPE_DATA_REFRESH)
        now = datetime.now(config.TIMEZONE)
        with db.get_connection(write=True) as conn:
            job_id = db.insert_refresh_job(
                conn, principal_type="agent_token", principal_id=str(owner_id),
                job_type="data_refresh", params_digest="digest",
                status="queued", created_at=now.isoformat(),
                updated_at=now.isoformat(), expires_at=None,
            )
        other, _ = _issue(agent_tokens.SCOPE_DATA_REFRESH)
        resp = client.get(f"/api/agent/tools/refresh/{job_id}", headers=other)
        assert resp.status_code == 404


class TestDirectWriteRejection:
    def test_rejection_is_error_without_execution_mode(self, client):
        headers, _ = _issue(agent_tokens.SCOPE_TRANSACTIONS_CREATE)
        resp = client.post(
            "/api/agent/tools/transactions",
            headers={**headers, "Idempotency-Key": "response-model-direct-key"},
            json={**BUY_PARAMS, "fund_code": "999999"},
        )
        assert resp.status_code == 409
        body = resp.json()
        assert body["error"]["code"] == "fund_not_registered"
        # 拒绝不是「成功但被拒绝」：2xx 专属字段不得出现。
        assert "execution_mode" not in body
        assert "execution_mode" not in (body.get("data") or {})
