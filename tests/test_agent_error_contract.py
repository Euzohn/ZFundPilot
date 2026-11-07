"""统一错误契约：request_id、稳定错误码与旧 detail 兼容。"""
from __future__ import annotations

import re
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest
from fastapi.testclient import TestClient

from zfundpilot import agent_tokens, api, config, db
from zfundpilot.api_errors import build_error_payload

_REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9._:-]{8,64}$")


@pytest.fixture
def temp_db(monkeypatch):
    with TemporaryDirectory() as d:
        monkeypatch.setattr(config, "DB_PATH", str(Path(d) / "test.db"))
        db.init_db()
        yield


@pytest.fixture
def client(temp_db, monkeypatch):
    monkeypatch.setattr(config, "AUTH_ENABLED", True)
    monkeypatch.setattr(config, "AUTH_SECRET", "test-secret")
    monkeypatch.setattr(config, "AUTH_USERNAME", "admin")
    monkeypatch.setattr(config, "AGENT_WRITE_ENABLED", True)
    return TestClient(api.app)


def _headers(*scopes: str) -> dict[str, str]:
    plaintext, _ = agent_tokens.issue_token("error-contract", list(scopes))
    return {"Authorization": f"Bearer {plaintext}"}


class TestRequestId:
    def test_success_envelope_has_request_id(self, client):
        response = client.get(
            "/api/agent/tools/portfolio-summary",
            headers=_headers("portfolio:read"),
        )
        assert response.status_code == 200
        request_id = response.headers["X-Request-ID"]
        assert _REQUEST_ID_RE.fullmatch(request_id)
        body = response.json()
        assert body["request_id"] == request_id
        assert body["schema_version"] == 1
        assert body["tool"] == "get_portfolio_summary"

    def test_client_supplied_request_id_is_echoed(self, client):
        supplied = "req-0123456789abcdef"
        response = client.get(
            "/api/agent/tools/portfolio-summary",
            headers={**_headers("portfolio:read"), "X-Request-ID": supplied},
        )
        assert response.status_code == 200
        assert response.headers["X-Request-ID"] == supplied
        assert response.json()["request_id"] == supplied

    def test_invalid_request_id_is_replaced(self, client):
        supplied = "bad id with spaces"
        response = client.get(
            "/api/agent/tools/portfolio-summary",
            headers={**_headers("portfolio:read"), "X-Request-ID": supplied},
        )
        assert response.status_code == 200
        generated = response.headers["X-Request-ID"]
        assert generated != supplied
        assert _REQUEST_ID_RE.fullmatch(generated)


class TestErrorEnvelope:
    def test_missing_token_keeps_detail_and_adds_code(self, client):
        response = client.get("/api/agent/tools/portfolio-summary")
        assert response.status_code == 401
        body = response.json()
        assert isinstance(body["detail"], str)
        assert body["error"]["code"] == "invalid_token"
        assert body["error"]["retryable"] is False
        assert body["request_id"] == response.headers["X-Request-ID"]

    def test_insufficient_scope_code(self, client):
        response = client.get(
            "/api/agent/tools/portfolio-summary",
            headers=_headers("funds:read"),
        )
        assert response.status_code == 403
        body = response.json()
        assert "portfolio:read" in body["detail"]
        assert body["error"]["code"] == "insufficient_scope"

    def test_not_found_keeps_business_detail(self, client):
        response = client.get(
            "/api/agent/tools/proposals/999999",
            headers=_headers("transactions:propose"),
        )
        assert response.status_code == 404
        body = response.json()
        assert body["detail"]["code"] == "not_found"
        assert body["error"]["code"] == "not_found"

    def test_unknown_tool_with_token_is_404(self, client):
        response = client.get(
            "/api/agent/tools/does-not-exist",
            headers=_headers("portfolio:read"),
        )
        assert response.status_code == 404
        body = response.json()
        assert body["error"]["code"] == "not_found"
        assert body["request_id"] == response.headers["X-Request-ID"]

    def test_validation_error_lists_details(self, client):
        response = client.post(
            "/api/agent/tools/backtest/dca",
            headers=_headers("funds:read"),
            json={"fund_codes": [], "start_date": "bad", "end_date": "bad"},
        )
        assert response.status_code == 422
        body = response.json()
        assert isinstance(body["detail"], list)
        assert body["error"]["code"] == "validation_error"
        assert isinstance(body["error"]["details"], list)

    def test_rate_limit_is_retryable(self, client):
        headers = _headers("transactions:propose")
        url = "/api/agent/tools/precheck/backfill"
        response = None
        for _ in range(11):
            response = client.post(url, headers=headers, json={})
        assert response is not None
        assert response.status_code == 429
        body = response.json()
        assert body["error"]["code"] == "rate_limited"
        assert body["error"]["retryable"] is True
        assert body["error"]["retry_after"] >= 1
        assert response.headers["Retry-After"] == str(body["error"]["retry_after"])


class TestEnvelopeBuilder:
    def test_dict_detail_splits_code_message_and_details(self):
        payload = build_error_payload(
            request_id="req-0123456789",
            status_code=409,
            detail={"code": "target_changed", "message": "已变更",
                    "field": "amount"},
        )
        assert payload["detail"] == {
            "code": "target_changed", "message": "已变更", "field": "amount"}
        assert payload["error"]["code"] == "target_changed"
        assert payload["error"]["message"] == "已变更"
        assert payload["error"]["details"] == {"field": "amount"}
        assert payload["error"]["retryable"] is False

    def test_string_detail_uses_status_defaults(self):
        payload = build_error_payload(
            request_id="req-0123456789",
            status_code=403,
            detail="缺少权限",
        )
        assert payload["error"]["code"] == "forbidden"
        assert payload["error"]["message"] == "缺少权限"
        assert "details" not in payload["error"]

    def test_service_unavailable_is_retryable(self):
        payload = build_error_payload(
            request_id="req-0123456789",
            status_code=503,
            detail={"code": "database_busy", "message": "忙"},
            retry_after=5,
        )
        assert payload["error"]["retryable"] is True
        assert payload["error"]["retry_after"] == 5
