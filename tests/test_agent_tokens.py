"""Agent token 安全边界测试：生成/存储/校验/撤销/scope/无密码模式/管理端点。"""
from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from zfundpilot import agent_tokens, api, config, db


@pytest.fixture
def temp_db(monkeypatch):
    """用临时数据库替换 config.DB_PATH，并建表。"""
    with TemporaryDirectory() as d:
        monkeypatch.setattr(config, "DB_PATH", str(Path(d) / "test.db"))
        db.init_db()
        yield


@pytest.fixture
def admin_client(temp_db, monkeypatch):
    """启用网页认证后的 TestClient + 合法网页 Bearer 头。"""
    monkeypatch.setattr(config, "AUTH_ENABLED", True)
    monkeypatch.setattr(config, "AUTH_SECRET", "test-secret")
    monkeypatch.setattr(config, "AUTH_USERNAME", "admin")
    client = TestClient(api.app)
    return client, {"Authorization": f"Bearer {api._create_token()}"}


# ---------------------------------------------------------------------------
# token 生成与 scope
# ---------------------------------------------------------------------------
class TestGenerateToken:
    def test_prefix_hash_and_uniqueness(self):
        a, ha, pa = agent_tokens.generate_token()
        b, hb, pb = agent_tokens.generate_token()
        assert a.startswith(agent_tokens.TOKEN_PREFIX)
        assert a != b
        assert ha == agent_tokens.hash_token(a)
        assert hb == agent_tokens.hash_token(b)
        assert len(ha) == 64
        assert pa == a[:agent_tokens.PREFIX_DISPLAY_LEN]
        assert pa != a  # 前缀不是完整 token

    def test_normalize_scopes(self):
        scopes = agent_tokens.normalize_scopes(["portfolio:read", " funds:read "])
        assert scopes == frozenset({"portfolio:read", "funds:read"})

    def test_normalize_scopes_rejects_empty_and_unknown(self):
        with pytest.raises(ValueError):
            agent_tokens.normalize_scopes([])
        with pytest.raises(ValueError):
            agent_tokens.normalize_scopes(["portfolio:read", "portfolio:write"])


# ---------------------------------------------------------------------------
# 数据库层：只存摘要、列表不泄露摘要、撤销幂等
# ---------------------------------------------------------------------------
class TestDb:
    def test_create_list_get_and_revoke(self, temp_db):
        plaintext, digest, prefix = agent_tokens.generate_token()
        row = db.create_agent_token(
            name="agent-1", token_hash=digest, token_prefix=prefix,
            scopes="portfolio:read", expires_at=None,
        )
        assert "token_hash" not in row
        assert row["name"] == "agent-1"
        assert row["token_prefix"] == prefix

        listed = db.list_agent_tokens()
        assert len(listed) == 1
        assert "token_hash" not in listed[0]

        internal = db.get_agent_token_by_hash(digest)
        assert internal is not None
        assert internal["token_hash"] == digest

        assert db.revoke_agent_token(row["id"]) is True
        assert db.revoke_agent_token(row["id"]) is False  # 幂等
        assert db.get_agent_token(row["id"])["revoked_at"] is not None

    def test_get_by_hash_missing(self, temp_db):
        assert db.get_agent_token_by_hash("0" * 64) is None


# ---------------------------------------------------------------------------
# 签发与校验
# ---------------------------------------------------------------------------
class TestIssueAndAuthenticate:
    def test_auth_disabled_cannot_issue_or_use(self, temp_db, monkeypatch):
        monkeypatch.setattr(config, "AUTH_ENABLED", False)
        with pytest.raises(agent_tokens.AgentAuthDisabled):
            agent_tokens.issue_token("agent", ["portfolio:read"])
        with pytest.raises(agent_tokens.AgentAuthDisabled):
            agent_tokens.authenticate("zfag_whatever", "portfolio:read")

    def test_issue_and_authenticate(self, temp_db, monkeypatch):
        monkeypatch.setattr(config, "AUTH_ENABLED", True)
        plaintext, info = agent_tokens.issue_token(
            "agent", ["portfolio:read"], expires_in_days=10)
        assert plaintext.startswith(agent_tokens.TOKEN_PREFIX)
        assert "token_hash" not in info

        ctx = agent_tokens.authenticate(plaintext, "portfolio:read")
        assert ctx.id == info["id"]
        assert ctx.name == "agent"
        assert ctx.scopes == frozenset({"portfolio:read"})
        assert db.get_agent_token(info["id"])["last_used_at"] is not None

    def test_wrong_token(self, temp_db, monkeypatch):
        monkeypatch.setattr(config, "AUTH_ENABLED", True)
        with pytest.raises(agent_tokens.AgentTokenInvalid):
            agent_tokens.authenticate("zfag_not_a_real_token")

    def test_missing_scope(self, temp_db, monkeypatch):
        monkeypatch.setattr(config, "AUTH_ENABLED", True)
        plaintext, _ = agent_tokens.issue_token("agent", ["portfolio:read"])
        with pytest.raises(agent_tokens.AgentTokenScopeDenied):
            agent_tokens.authenticate(plaintext, "funds:read")

    def test_expired(self, temp_db, monkeypatch):
        monkeypatch.setattr(config, "AUTH_ENABLED", True)
        plaintext, digest, prefix = agent_tokens.generate_token()
        past = (datetime.now(config.TIMEZONE) - timedelta(days=1)).isoformat()
        db.create_agent_token(
            name="old", token_hash=digest, token_prefix=prefix,
            scopes="portfolio:read", expires_at=past,
        )
        with pytest.raises(agent_tokens.AgentTokenExpired):
            agent_tokens.authenticate(plaintext, "portfolio:read")

    def test_revoked(self, temp_db, monkeypatch):
        monkeypatch.setattr(config, "AUTH_ENABLED", True)
        plaintext, info = agent_tokens.issue_token("agent", ["portfolio:read"])
        db.revoke_agent_token(info["id"])
        with pytest.raises(agent_tokens.AgentTokenRevoked):
            agent_tokens.authenticate(plaintext, "portfolio:read")

    def test_unknown_required_scope_is_programming_error(self, temp_db, monkeypatch):
        monkeypatch.setattr(config, "AUTH_ENABLED", True)
        plaintext, _ = agent_tokens.issue_token("agent", ["portfolio:read"])
        with pytest.raises(ValueError):
            agent_tokens.authenticate(plaintext, "portfolio:write")

    def test_is_active(self, temp_db, monkeypatch):
        monkeypatch.setattr(config, "AUTH_ENABLED", True)
        _, info = agent_tokens.issue_token("agent", ["portfolio:read"])
        assert agent_tokens.is_active(info) is True
        db.revoke_agent_token(info["id"])
        assert agent_tokens.is_active(db.get_agent_token(info["id"])) is False


# ---------------------------------------------------------------------------
# 管理端点：无密码模式拒绝、签发/列出/撤销、Agent token 不得管理
# ---------------------------------------------------------------------------
class TestAdminApi:
    def test_rejects_when_auth_disabled(self, temp_db, monkeypatch):
        monkeypatch.setattr(config, "AUTH_ENABLED", False)
        client = TestClient(api.app)
        assert client.get("/api/agent/tokens").status_code == 403
        assert client.post("/api/agent/tokens", json={"name": "x"}).status_code == 403

    def test_create_list_revoke(self, admin_client):
        client, headers = admin_client
        resp = client.post(
            "/api/agent/tokens",
            json={"name": "agent-1", "scopes": ["portfolio:read"],
                  "expires_in_days": 30},
            headers=headers,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["token"].startswith(agent_tokens.TOKEN_PREFIX)
        assert "token_hash" not in body["token_info"]
        token_id = body["token_info"]["id"]

        listed = client.get("/api/agent/tokens", headers=headers).json()
        assert len(listed["tokens"]) == 1
        assert listed["tokens"][0]["active"] is True
        assert "token_hash" not in listed["tokens"][0]

        revoked = client.delete(f"/api/agent/tokens/{token_id}", headers=headers)
        assert revoked.status_code == 200
        assert revoked.json()["token_info"]["revoked_at"] is not None

        # 已撤销后 authenticate 必须失败
        with pytest.raises(agent_tokens.AgentTokenRevoked):
            agent_tokens.authenticate(body["token"], "portfolio:read")

    def test_agent_token_cannot_manage_tokens(self, admin_client):
        client, _ = admin_client
        plaintext, _ = agent_tokens.issue_token("agent", ["portfolio:read"])
        resp = client.get(
            "/api/agent/tokens",
            headers={"Authorization": f"Bearer {plaintext}"},
        )
        assert resp.status_code == 401

    def test_revoke_missing_returns_404(self, admin_client):
        client, headers = admin_client
        assert client.delete(
            "/api/agent/tokens/999", headers=headers).status_code == 404

    def test_create_rejects_unknown_scope(self, admin_client):
        client, headers = admin_client
        resp = client.post(
            "/api/agent/tokens",
            json={"name": "bad", "scopes": ["portfolio:write"]},
            headers=headers,
        )
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# 鉴权依赖：默认拒绝 + scope 匹配
# ---------------------------------------------------------------------------
def _probe_app(scope: str) -> FastAPI:
    probe = FastAPI()

    @probe.get("/probe")
    def _probe(ctx=Depends(api.require_agent_scope(scope))):  # noqa: B008
        return {"token_id": ctx.id, "scopes": sorted(ctx.scopes)}

    return probe


class TestRequireAgentScope:
    def test_valid_token_with_scope(self, temp_db, monkeypatch):
        monkeypatch.setattr(config, "AUTH_ENABLED", True)
        plaintext, info = agent_tokens.issue_token("agent", ["portfolio:read"])
        resp = TestClient(_probe_app("portfolio:read")).get(
            "/probe", headers={"Authorization": f"Bearer {plaintext}"})
        assert resp.status_code == 200
        assert resp.json()["token_id"] == info["id"]

    def test_missing_or_bad_token_is_401(self, temp_db, monkeypatch):
        monkeypatch.setattr(config, "AUTH_ENABLED", True)
        client = TestClient(_probe_app("portfolio:read"))
        assert client.get("/probe").status_code == 401
        assert client.get(
            "/probe", headers={"Authorization": "Bearer zfag_bad"}
        ).status_code == 401

    def test_insufficient_scope_is_403(self, temp_db, monkeypatch):
        monkeypatch.setattr(config, "AUTH_ENABLED", True)
        plaintext, _ = agent_tokens.issue_token("agent", ["portfolio:read"])
        resp = TestClient(_probe_app("funds:read")).get(
            "/probe", headers={"Authorization": f"Bearer {plaintext}"})
        assert resp.status_code == 403

    def test_auth_disabled_is_403(self, temp_db, monkeypatch):
        monkeypatch.setattr(config, "AUTH_ENABLED", False)
        resp = TestClient(_probe_app("portfolio:read")).get(
            "/probe", headers={"Authorization": "Bearer zfag_whatever"})
        assert resp.status_code == 403
