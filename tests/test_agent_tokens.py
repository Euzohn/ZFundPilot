"""Agent token 安全边界测试：生成/存储/校验/撤销/scope/无密码模式/管理端点。"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from zfundpilot import agent_tokens, analysis, api, config, db
from zfundpilot.fetch_fund import FeeRates, PurchaseTier, RedemptionTier
from zfundpilot.models import DataStatus, Fund, NavPoint, Transaction


@pytest.fixture
def temp_db(monkeypatch):
    """用临时数据库替换 config.DB_PATH，并建表。"""
    with TemporaryDirectory() as d:
        monkeypatch.setattr(config, "DB_PATH", str(Path(d) / "test.db"))
        db.init_db()
        analysis.clear_analysis_cache()
        yield
        analysis.clear_analysis_cache()


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

    def test_default_scopes_stay_conservative(self):
        """新增数据类 scope 不应进入默认勾选，避免存量流程静默扩权。"""
        assert set(agent_tokens.DEFAULT_SCOPES) == {
            "portfolio:read", "funds:read", "health:read"}
        assert set(agent_tokens.DEFAULT_SCOPES) < agent_tokens.ALLOWED_SCOPES
        assert "transactions:read" not in agent_tokens.DEFAULT_SCOPES
        assert "watchlist:read" not in agent_tokens.DEFAULT_SCOPES
        assert "alerts:read" not in agent_tokens.DEFAULT_SCOPES
        assert "plans:read" not in agent_tokens.DEFAULT_SCOPES


# ---------------------------------------------------------------------------
# 网页登录 token 校验（回归：签名可能包含分隔符字节）
# ---------------------------------------------------------------------------
class TestWebTokenVerify:
    def test_accepts_signature_containing_dot_byte(self, monkeypatch):
        exp = int(time.time()) + 3600
        payload_bytes = json.dumps({"exp": exp}).encode()
        secret = ""
        sig = b""
        for i in range(10000):
            candidate = f"dot-secret-{i}"
            digest = hmac.new(
                candidate.encode(), payload_bytes, hashlib.sha256).digest()
            if b"." in digest:
                secret, sig = candidate, digest
                break
        assert secret, "未找到签名含点号的测试密钥"
        monkeypatch.setattr(config, "AUTH_SECRET", secret)

        token = base64.urlsafe_b64encode(payload_bytes + b"." + sig).decode()

        assert api._verify_token(token) is True

    def test_rejects_tampered_signature_and_expired_token(self, monkeypatch):
        monkeypatch.setattr(config, "AUTH_SECRET", "verify-secret")
        assert api._verify_token(api._create_token()) is True

        forged_payload = json.dumps({"exp": int(time.time()) + 3600}).encode()
        forged = base64.urlsafe_b64encode(forged_payload + b"\x00" * 32).decode()
        assert api._verify_token(forged) is False

        expired_payload = json.dumps({"exp": int(time.time()) - 10}).encode()
        expired_sig = hmac.new(
            b"verify-secret", expired_payload, hashlib.sha256).digest()
        expired = base64.urlsafe_b64encode(
            expired_payload + b"." + expired_sig).decode()
        assert api._verify_token(expired) is False


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


# ---------------------------------------------------------------------------
# Agent 只读工具端点
# ---------------------------------------------------------------------------
class TestAgentTools:
    def _headers(self, *scopes: str) -> dict[str, str]:
        plaintext, _ = agent_tokens.issue_token("agent", list(scopes))
        return {"Authorization": f"Bearer {plaintext}"}

    def test_portfolio_summary_scope(self, temp_db, monkeypatch):
        monkeypatch.setattr(config, "AUTH_ENABLED", True)
        client = TestClient(api.app)

        ok = client.get("/api/agent/tools/portfolio-summary",
                        headers=self._headers("portfolio:read"))
        assert ok.status_code == 200
        body = ok.json()
        assert body["tool"] == "get_portfolio_summary"
        assert "total_value" in body["data"]
        assert "data_status" in body["data"]

        denied = client.get("/api/agent/tools/portfolio-summary",
                            headers=self._headers("funds:read"))
        assert denied.status_code == 403

    def test_data_status_requires_health_scope(self, temp_db, monkeypatch):
        monkeypatch.setattr(config, "AUTH_ENABLED", True)
        client = TestClient(api.app)

        ok = client.get("/api/agent/tools/data-status",
                        headers=self._headers("health:read"))
        assert ok.status_code == 200
        data = ok.json()["data"]
        assert data["as_of_date_semantics"]
        assert data["missing_nav_fund_count"] == 0
        assert data["stale_nav_fund_count"] == 0
        assert data["pending_t1_transaction_count"] == 0

        denied = client.get("/api/agent/tools/data-status",
                            headers=self._headers("portfolio:read"))
        assert denied.status_code == 403

    def test_portfolio_health_scope_and_data_quality(self, temp_db, monkeypatch):
        monkeypatch.setattr(config, "AUTH_ENABLED", True)
        client = TestClient(api.app)

        ok = client.get("/api/agent/tools/portfolio-health",
                        headers=self._headers("health:read"))
        assert ok.status_code == 200
        body = ok.json()
        assert body["tool"] == "get_portfolio_health"
        data = body["data"]
        assert data["overall_score"] == 0
        assert data["overall_tier"] == "danger"
        assert len(data["dimensions"]) == 4
        assert data["valuation_basis"] == "latest_formal_nav"
        assert data["data_quality"]["as_of_date_semantics"]
        assert data["data_quality"]["caveats"] == []

        denied = client.get("/api/agent/tools/portfolio-health",
                            headers=self._headers("portfolio:read"))
        assert denied.status_code == 403

    def test_health_caveats_cover_all_data_gaps(self):
        caveats = api._agent_health_caveats(DataStatus(
            missing_nav_fund_count=2,
            stale_nav_fund_count=1,
            pending_t1_transaction_count=3,
        ))
        assert len(caveats) == 3
        assert "2" in caveats[0] and "正式净值" in caveats[0]
        assert "1" in caveats[1]
        assert "3" in caveats[2]

    def test_positions_and_limit_validation(self, temp_db, monkeypatch):
        monkeypatch.setattr(config, "AUTH_ENABLED", True)
        client = TestClient(api.app)
        headers = self._headers("portfolio:read")

        resp = client.get("/api/agent/tools/positions", headers=headers)
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["positions"] == []
        assert data["total"] == 0

        assert client.get(
            "/api/agent/tools/positions?limit=0", headers=headers
        ).status_code == 422
        assert client.get(
            "/api/agent/tools/positions?limit=501", headers=headers
        ).status_code == 422

    def test_fund_detail(self, temp_db, monkeypatch):
        monkeypatch.setattr(config, "AUTH_ENABLED", True)
        db.upsert_fund(Fund(
            fund_code="005827", fund_name="测试基金",
            fund_type="混合型", sector="科技"))
        db.upsert_nav_batch([
            NavPoint(fund_code="005827", date="2026-10-26", nav=1.2),
            NavPoint(fund_code="005827", date="2026-10-27", nav=1.25,
                     accumulated_nav=1.5),
        ])
        analysis.clear_analysis_cache()
        client = TestClient(api.app)
        headers = self._headers("funds:read")

        resp = client.get("/api/agent/tools/funds/005827", headers=headers)
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["fund"]["fund_code"] == "005827"
        assert data["latest_formal_nav"]["nav"] == 1.25
        assert len(data["recent_nav"]) == 2
        assert data["positions"] == []

        assert client.get(
            "/api/agent/tools/funds/abc", headers=headers).status_code == 400
        assert client.get(
            "/api/agent/tools/funds/000000", headers=headers).status_code == 404

    def test_returns_portfolio_and_fund(self, temp_db, monkeypatch):
        monkeypatch.setattr(config, "AUTH_ENABLED", True)
        client = TestClient(api.app)
        headers = self._headers("portfolio:read")

        portfolio = client.get("/api/agent/tools/returns", headers=headers)
        assert portfolio.status_code == 200
        body = portfolio.json()
        assert body["tool"] == "get_returns"
        data = body["data"]
        assert data["scope"] == "portfolio"
        assert data["valuation_basis"] == "latest_formal_nav"
        assert set(data["daily"]) == {"pnl", "return"}

        db.upsert_fund(Fund(
            fund_code="005827", fund_name="测试基金",
            fund_type="混合型", sector="科技"))
        db.add_transaction(Transaction(
            fund_code="005827", action="buy", date="2025-01-02",
            amount=1000, shares=1000, nav=1.0))
        db.add_transaction(Transaction(
            fund_code="005827", action="buy", date="2025-06-02",
            amount=1000, shares=800, nav=1.25))
        db.upsert_nav_batch([
            NavPoint(fund_code="005827", date="2026-10-27", nav=1.5),
        ])
        analysis.clear_analysis_cache()

        fund = client.get(
            "/api/agent/tools/returns?fund_code=005827", headers=headers)
        assert fund.status_code == 200
        fund_data = fund.json()["data"]
        assert fund_data["scope"] == "fund"
        assert fund_data["fund_code"] == "005827"
        assert fund_data["fund_name"] == "测试基金"
        assert fund_data["transaction_count"] == 2
        assert fund_data["buy_amount"] == 2000
        assert fund_data["market_value"] == 2700
        assert fund_data["annualized_return"] is not None
        assert len(fund_data["channels"]) == 1

        assert client.get(
            "/api/agent/tools/returns?fund_code=abc",
            headers=headers).status_code == 400
        assert client.get(
            "/api/agent/tools/returns?fund_code=000000",
            headers=headers).status_code == 404

        denied = client.get(
            "/api/agent/tools/returns",
            headers=self._headers("funds:read"))
        assert denied.status_code == 403

    def test_compare_funds_scope_and_validation(self, temp_db, monkeypatch):
        monkeypatch.setattr(config, "AUTH_ENABLED", True)

        from zfundpilot.compare import CompareResponse, FundCompareItem

        def fake_compare(codes):
            return CompareResponse(
                funds=[FundCompareItem(code=c, name=f"基金{c}") for c in codes],
                correlations=(
                    [[1.0, 0.5], [0.5, 1.0]] if len(codes) == 2 else None),
            )

        monkeypatch.setattr(api.compare, "compare_funds", fake_compare)
        client = TestClient(api.app)
        headers = self._headers("funds:read")

        resp = client.get(
            "/api/agent/tools/funds/compare?codes=005827&codes=000001",
            headers=headers)
        assert resp.status_code == 200
        body = resp.json()
        assert body["tool"] == "compare_funds"
        data = body["data"]
        assert data["count"] == 2
        assert [f["code"] for f in data["funds"]] == ["005827", "000001"]
        assert data["correlations"] == [[1.0, 0.5], [0.5, 1.0]]
        assert "nav_series" not in data
        assert data["valuation_basis"] == "latest_formal_nav"

        assert client.get(
            "/api/agent/tools/funds/compare?codes=abc",
            headers=headers).status_code == 400
        assert client.get(
            "/api/agent/tools/funds/compare?codes=",
            headers=headers).status_code == 400
        assert client.get(
            "/api/agent/tools/funds/compare", headers=headers).status_code == 422

        denied = client.get(
            "/api/agent/tools/funds/compare?codes=005827",
            headers=self._headers("portfolio:read"))
        assert denied.status_code == 403

    def test_list_transactions_scope_and_filters(self, temp_db, monkeypatch):
        monkeypatch.setattr(config, "AUTH_ENABLED", True)
        db.upsert_fund(Fund(fund_code="005827", fund_name="测试基金",
                            fund_type="混合型", sector="科技"))
        db.add_transaction(Transaction(
            fund_code="005827", action="buy", date="2025-01-02",
            amount=1000, shares=1000, nav=1.0, channel="支付宝"))
        db.add_transaction(Transaction(
            fund_code="005827", action="buy", date="2026-06-02",
            amount=500, is_t1=True))  # nav 待确认 → pending_t1
        db.add_transaction(Transaction(
            fund_code="005827", action="buy", date="2026-07-02",
            amount=300))  # nav 缺失 → missing
        client = TestClient(api.app)
        headers = self._headers("transactions:read")

        all_tx = client.get("/api/agent/tools/transactions", headers=headers)
        assert all_tx.status_code == 200
        data = all_tx.json()["data"]
        assert data["total"] == 3
        assert data["transactions"][0]["date"] == "2026-07-02"  # 降序
        assert data["pagination"]["has_more"] is False
        assert data["valuation_basis"] == "latest_formal_nav"

        # 派生字段
        statuses = {t["date"]: t["nav_status"] for t in data["transactions"]}
        assert statuses == {"2025-01-02": "confirmed",
                            "2026-06-02": "pending_t1",
                            "2026-07-02": "missing"}
        named = next(t for t in data["transactions"] if t["date"] == "2025-01-02")
        assert named["fund_name"] == "测试基金"
        assert named["amount_semantics"] == "gross_paid"

        # 过滤
        pend = client.get("/api/agent/tools/transactions?nav_status=pending_t1",
                          headers=headers)
        assert pend.json()["data"]["total"] == 1
        rng = client.get(
            "/api/agent/tools/transactions?date_from=2026-01-01",
            headers=headers)
        assert rng.json()["data"]["total"] == 2
        chan = client.get("/api/agent/tools/transactions?channel=支付宝",
                          headers=headers)
        assert chan.json()["data"]["total"] == 1

        # 分页
        page = client.get("/api/agent/tools/transactions?limit=1&offset=1",
                          headers=headers)
        pdata = page.json()["data"]
        assert pdata["count"] == 1
        assert pdata["pagination"]["has_more"] is True
        assert pdata["pagination"]["total"] == 3

        # 校验失败
        assert client.get(
            "/api/agent/tools/transactions?fund_code=abc",
            headers=headers).status_code == 400
        assert client.get(
            "/api/agent/tools/transactions?action=trade",
            headers=headers).status_code == 400
        assert client.get(
            "/api/agent/tools/transactions?date_from=2026/01/01",
            headers=headers).status_code == 400
        assert client.get(
            "/api/agent/tools/transactions?date_from=2026-1-01",
            headers=headers).status_code == 400
        assert client.get(
            "/api/agent/tools/transactions?date_from=2026-02-30",
            headers=headers).status_code == 400
        assert client.get(
            "/api/agent/tools/transactions?nav_status=ok",
            headers=headers).status_code == 400
        assert client.get(
            "/api/agent/tools/transactions?date_from=2026-12-01&date_to=2026-01-01",
            headers=headers).status_code == 400

        # scope
        assert client.get(
            "/api/agent/tools/transactions",
            headers=self._headers("funds:read")).status_code == 403

    def test_get_transaction_and_404(self, temp_db, monkeypatch):
        monkeypatch.setattr(config, "AUTH_ENABLED", True)
        db.upsert_fund(Fund(fund_code="005827", fund_name="测试基金",
                            fund_type="混合型", sector="科技"))
        tx_id = db.add_transaction(Transaction(
            fund_code="005827", action="sell", date="2026-06-02",
            amount=1200, shares=900, nav=1.34, fee=6.0, channel="支付宝"))
        client = TestClient(api.app)
        headers = self._headers("transactions:read")

        resp = client.get(f"/api/agent/tools/transactions/{tx_id}",
                          headers=headers)
        assert resp.status_code == 200
        body = resp.json()
        assert body["tool"] == "get_transaction"
        item = body["data"]
        assert item["id"] == tx_id
        assert item["fund_name"] == "测试基金"
        assert item["nav_status"] == "confirmed"
        assert item["amount_semantics"] == "net_received"
        assert item["valuation_basis"] == "latest_formal_nav"

        assert client.get(
            "/api/agent/tools/transactions/999",
            headers=headers).status_code == 404
        assert client.get(
            "/api/agent/tools/transactions/0",
            headers=headers).status_code == 404

    def test_list_watchlist_scope_and_group(self, temp_db, monkeypatch):
        monkeypatch.setattr(config, "AUTH_ENABLED", True)
        db.upsert_fund(Fund(fund_code="005827", fund_name="测试基金",
                            fund_type="混合型", sector="科技"))
        db.add_to_watchlist("005827", "观察", "核心")
        db.add_to_watchlist("000001", "", "其他")
        client = TestClient(api.app)
        headers = self._headers("watchlist:read")

        resp = client.get("/api/agent/tools/watchlist", headers=headers)
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["total"] == 2
        assert data["pagination"]["has_more"] is False

        grouped = client.get(
            "/api/agent/tools/watchlist?group_name=核心", headers=headers)
        gdata = grouped.json()["data"]
        assert gdata["total"] == 1
        assert gdata["watchlist"][0]["fund_code"] == "005827"
        assert gdata["watchlist"][0]["fund_name"] == "测试基金"

        assert client.get(
            "/api/agent/tools/watchlist",
            headers=self._headers("plans:read")).status_code == 403

    def test_list_alerts_types_and_validation(self, temp_db, monkeypatch):
        monkeypatch.setattr(config, "AUTH_ENABLED", True)
        db.upsert_fund(Fund(fund_code="005827", fund_name="测试基金",
                            fund_type="混合型", sector="科技"))
        db.add_dividend_alert({
            "fund_code": "005827", "fund_name": "测试基金",
            "record_date": "2026-09-20", "ex_date": "2026-09-21",
            "per_share": 0.05, "pay_date": "2026-09-25",
            "held_shares": 1000, "estimated_amount": 50,
            "dividend_method": "cash",
        })
        db.add_tp_sl_alert({
            "fund_code": "005827", "fund_name": "测试基金",
            "alert_type": "take_profit", "triggered_return": 0.18,
            "threshold": 0.18,
        })
        client = TestClient(api.app)
        headers = self._headers("alerts:read")

        resp = client.get("/api/agent/tools/alerts", headers=headers)
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["total"] == 2
        assert {a["alert_type"] for a in data["alerts"]} == {
            "dividend", "take_profit"}

        div = client.get("/api/agent/tools/alerts?type=dividend",
                         headers=headers)
        assert div.json()["data"]["total"] == 1
        tp = client.get("/api/agent/tools/alerts?type=tp_sl",
                        headers=headers)
        assert tp.json()["data"]["total"] == 1

        # 白名单字段：不含内部列
        item = data["alerts"][0]
        assert set(item) <= {
            "id", "alert_type", "fund_code", "fund_name", "status",
            "triggered_return", "threshold", "record_date", "ex_date",
            "pay_date", "per_share", "estimated_amount", "held_shares",
            "dividend_method", "created_at", "resolved_at", "tx_id"}

        assert client.get(
            "/api/agent/tools/alerts?type=xxx", headers=headers).status_code == 400
        assert client.get(
            "/api/agent/tools/alerts?status=done", headers=headers).status_code == 400
        assert client.get(
            "/api/agent/tools/alerts",
            headers=self._headers("plans:read")).status_code == 403

    def test_list_auto_invest_plans_status(self, temp_db, monkeypatch):
        monkeypatch.setattr(config, "AUTH_ENABLED", True)
        db.upsert_fund(Fund(fund_code="005827", fund_name="测试基金",
                            fund_type="混合型", sector="科技"))
        active_id = db.add_auto_invest_plan(
            fund_code="005827", amount=1000, cadence="month",
            day_of_month=1, channel="支付宝", note="定投",
            next_run="2099-12-31")
        due_id = db.add_auto_invest_plan(
            fund_code="005827", amount=500, cadence="week",
            day_of_week=0, note="周定投", next_run="2020-01-01")
        paused_id = db.add_auto_invest_plan(
            fund_code="005827", amount=300, cadence="month",
            day_of_month=15, note="暂停中", next_run="2099-12-31")
        db.update_auto_invest_plan(paused_id, enabled=0)
        client = TestClient(api.app)
        headers = self._headers("plans:read")

        resp = client.get("/api/agent/tools/auto-invest-plans", headers=headers)
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["total"] == 3
        by_id = {p["id"]: p for p in data["plans"]}
        assert by_id[active_id]["status"] == "active"
        assert by_id[active_id]["enabled"] is True
        assert by_id[active_id]["fund_name"] == "测试基金"
        assert by_id[due_id]["status"] == "due"
        assert by_id[paused_id]["status"] == "paused"

        only_enabled = client.get(
            "/api/agent/tools/auto-invest-plans?enabled=true", headers=headers)
        assert only_enabled.json()["data"]["total"] == 2

        assert client.get(
            "/api/agent/tools/auto-invest-plans",
            headers=self._headers("alerts:read")).status_code == 403

    def test_portfolio_curve_scope_dates_and_sampling(self, temp_db, monkeypatch):
        monkeypatch.setattr(config, "AUTH_ENABLED", True)
        db.upsert_fund(Fund(fund_code="005827", fund_name="测试基金",
                            fund_type="混合型", sector="科技"))
        db.add_transaction(Transaction(
            fund_code="005827", action="buy", date="2026-01-01",
            amount=1000, shares=1000, nav=1.0, channel="支付宝"))
        db.upsert_nav_batch([
            NavPoint(fund_code="005827", date=f"2026-01-{day:02d}", nav=1.0)
            for day in range(1, 13)
        ])
        analysis.clear_analysis_cache()
        client = TestClient(api.app)
        headers = self._headers("portfolio:read")

        resp = client.get("/api/agent/tools/portfolio-curve", headers=headers)
        assert resp.status_code == 200
        assert resp.json()["tool"] == "get_portfolio_curve"
        data = resp.json()["data"]
        assert data["valuation_basis"] == "latest_formal_nav"
        assert data["points_count"] == 12
        assert data["points"][0]["date"] == "2026-01-01"
        assert data["points"][-1]["date"] == "2026-01-12"
        assert {"date", "total_value", "invested_cost",
                "total_return"} <= set(data["points"][0])

        sampled = client.get(
            "/api/agent/tools/portfolio-curve?max_points=10", headers=headers)
        sampled_data = sampled.json()["data"]
        assert sampled_data["points_count"] == 10
        assert sampled_data["points"][0]["date"] == "2026-01-01"
        assert sampled_data["points"][-1]["date"] == "2026-01-12"

        ranged = client.get(
            "/api/agent/tools/portfolio-curve"
            "?start_date=2026-01-05&end_date=2026-01-07", headers=headers)
        assert [p["date"] for p in ranged.json()["data"]["points"]] == [
            "2026-01-05", "2026-01-06", "2026-01-07"]

        assert client.get(
            "/api/agent/tools/portfolio-curve?start_date=2026-1-01",
            headers=headers).status_code == 400
        assert client.get(
            "/api/agent/tools/portfolio-curve?start_date=2026-02-30",
            headers=headers).status_code == 400
        assert client.get(
            "/api/agent/tools/portfolio-curve"
            "?start_date=2026-02-01&end_date=2026-01-01",
            headers=headers).status_code == 400
        assert client.get(
            "/api/agent/tools/portfolio-curve?max_points=5",
            headers=headers).status_code == 422
        assert client.get(
            "/api/agent/tools/portfolio-curve",
            headers=self._headers("health:read")).status_code == 403

    def test_benchmark_comparison_scope_and_validation(self, temp_db, monkeypatch):
        monkeypatch.setattr(config, "AUTH_ENABLED", True)
        calls: dict[str, str] = {}

        def fake_benchmark(indices: str = "") -> list[dict]:
            calls["indices"] = indices
            return [
                {"date": "2026-01-01", "000300": 0.0, "CPI": 0.0},
                {"date": "2026-01-02", "000300": 0.01, "CPI": 0.0},
                {"date": "2026-01-03", "000300": 0.02, "CPI": 0.0},
            ]

        monkeypatch.setattr(api, "get_portfolio_benchmark", fake_benchmark)
        client = TestClient(api.app)
        headers = self._headers("portfolio:read")

        resp = client.get(
            "/api/agent/tools/benchmark?codes=000300&codes=CPI&codes=000300",
            headers=headers)
        assert resp.status_code == 200
        assert resp.json()["tool"] == "get_benchmark_comparison"
        data = resp.json()["data"]
        assert data["codes"] == ["000300", "CPI"]
        assert data["code_names"]["000300"] == "沪深300"
        assert data["points_count"] == 3
        assert calls["indices"] == "000300,CPI"

        ranged = client.get(
            "/api/agent/tools/benchmark?codes=000300"
            "&start_date=2026-01-02&end_date=2026-01-03", headers=headers)
        assert [p["date"] for p in ranged.json()["data"]["points"]] == [
            "2026-01-02", "2026-01-03"]

        assert client.get(
            "/api/agent/tools/benchmark?codes=BAD",
            headers=headers).status_code == 400
        assert client.get(
            "/api/agent/tools/benchmark?codes=",
            headers=headers).status_code == 400
        assert client.get(
            "/api/agent/tools/benchmark", headers=headers).status_code == 422
        assert client.get(
            "/api/agent/tools/benchmark?codes=000300"
            "&start_date=2026-02-01&end_date=2026-01-01",
            headers=headers).status_code == 400
        assert client.get(
            "/api/agent/tools/benchmark?codes=000300",
            headers=self._headers("health:read")).status_code == 403

    def test_risk_report_scope_and_quality(self, temp_db, monkeypatch):
        monkeypatch.setattr(config, "AUTH_ENABLED", True)
        client = TestClient(api.app)
        headers = self._headers("health:read")

        resp = client.get("/api/agent/tools/risk-report", headers=headers)
        assert resp.status_code == 200
        assert resp.json()["tool"] == "get_risk_report"
        data = resp.json()["data"]
        assert data["valuation_basis"] == "latest_formal_nav"
        assert data["max_drawdown"] is None
        assert data["volatility"] is None
        assert data["data_quality"]["caveats"] == []
        assert data["flags"]
        for flag in data["flags"]:
            assert set(flag) == {
                "level", "code", "params", "title", "detail"}

        assert client.get(
            "/api/agent/tools/risk-report",
            headers=self._headers("portfolio:read")).status_code == 403

    def test_industry_exposure_scope_and_empty_portfolio(
            self, temp_db, monkeypatch):
        monkeypatch.setattr(config, "AUTH_ENABLED", True)
        client = TestClient(api.app)
        headers = self._headers("portfolio:read")

        resp = client.get(
            "/api/agent/tools/industry-exposure", headers=headers)
        assert resp.status_code == 200
        assert resp.json()["tool"] == "get_industry_exposure"
        data = resp.json()["data"]
        assert data["ok"] is False
        assert data["message"] == "无持仓"
        assert data["items"] == []
        assert data["funds_missing"] == []
        assert data["valuation_basis"] == "latest_formal_nav"
        assert "data_quality" in data

        assert client.get(
            "/api/agent/tools/industry-exposure",
            headers=self._headers("health:read")).status_code == 403

    def test_capabilities_includes_batch2_tools(self, temp_db, monkeypatch):
        monkeypatch.setattr(config, "AUTH_ENABLED", True)
        client = TestClient(api.app)
        headers = self._headers("portfolio:read", "health:read")

        data = client.get(
            "/api/agent/tools/capabilities", headers=headers).json()["data"]
        names = {t["name"] for t in data["tools"]}
        assert {"get_portfolio_curve", "get_benchmark_comparison",
                "get_risk_report", "get_industry_exposure"} <= names
        scopes = {t["name"]: t["scope"] for t in data["tools"]}
        assert scopes["get_risk_report"] == "health:read"
        assert scopes["get_industry_exposure"] == "portfolio:read"

        funds_data = client.get(
            "/api/agent/tools/capabilities",
            headers=self._headers("funds:read")).json()["data"]
        funds_names = {t["name"] for t in funds_data["tools"]}
        assert {"search_funds", "screen_funds", "run_dca_backtest"} <= funds_names
        assert "get_risk_report" not in funds_names
        methods = {t["name"]: t["method"] for t in funds_data["tools"]}
        assert methods["run_dca_backtest"] == "POST"

    def test_search_funds_scope_pagination_and_validation(
            self, temp_db, monkeypatch):
        monkeypatch.setattr(config, "AUTH_ENABLED", True)
        universe = [
            {"code": "005827", "name": "易方达蓝筹精选混合",
             "type": "混合型", "sector": "消费"},
            {"code": "000001", "name": "华夏成长混合",
             "type": "混合型", "sector": "科技"},
            {"code": "110011", "name": "易方达中小盘混合",
             "type": "混合型", "sector": "科技"},
        ]
        monkeypatch.setattr(
            api.fund_filter, "load_fund_universe",
            lambda force_refresh=False: universe)
        client = TestClient(api.app)
        headers = self._headers("funds:read")

        resp = client.get(
            "/api/agent/tools/search?keyword=易方达&limit=1", headers=headers)
        assert resp.status_code == 200
        assert resp.json()["tool"] == "search_funds"
        data = resp.json()["data"]
        assert data["ok"] is True
        assert data["total"] == 2
        assert data["count"] == 1
        assert data["pagination"] == {
            "limit": 1, "offset": 0, "total": 2, "has_more": True}
        assert set(data["funds"][0]) == {"code", "name", "type", "sector"}
        assert data["funds"][0]["code"] == "005827"

        page2 = client.get(
            "/api/agent/tools/search?keyword=易方达&limit=1&offset=1",
            headers=headers)
        page2_data = page2.json()["data"]
        assert page2_data["funds"][0]["code"] == "110011"
        assert page2_data["pagination"]["has_more"] is False

        assert client.get(
            "/api/agent/tools/search?keyword=%20%20",
            headers=headers).status_code == 400
        assert client.get(
            "/api/agent/tools/search?keyword=" + "基" * 101,
            headers=headers).status_code == 400
        assert client.get(
            "/api/agent/tools/search?keyword=易方达&limit=0",
            headers=headers).status_code == 422
        assert client.get(
            "/api/agent/tools/search?keyword=易方达",
            headers=self._headers("portfolio:read")).status_code == 403

    def test_search_funds_universe_failure_keeps_200(self, temp_db, monkeypatch):
        monkeypatch.setattr(config, "AUTH_ENABLED", True)
        monkeypatch.setattr(
            api.fund_filter, "load_fund_universe",
            lambda force_refresh=False: [])
        client = TestClient(api.app)

        resp = client.get(
            "/api/agent/tools/search?keyword=易方达",
            headers=self._headers("funds:read"))
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["ok"] is False
        assert data["code"] == "universe_failed"
        assert data["funds"] == []
        assert data["total"] == 0

    def test_screen_funds_filters_and_base_metrics(
            self, temp_db, monkeypatch):
        monkeypatch.setattr(config, "AUTH_ENABLED", True)
        universe = [
            {"code": "005827", "name": "易方达蓝筹精选混合",
             "type": "混合型", "sector": "消费"},
            {"code": "000001", "name": "华夏成长混合",
             "type": "混合型", "sector": "科技"},
            {"code": "110011", "name": "易方达中小盘混合",
             "type": "混合型", "sector": "科技"},
        ]
        monkeypatch.setattr(
            api.fund_filter, "load_fund_universe",
            lambda force_refresh=False: universe)
        monkeypatch.setattr(
            api.fetch_fund, "get_available_types",
            lambda: ["混合型", "债券型"])
        monkeypatch.setattr(
            api.fetch_fund, "get_available_sectors",
            lambda: ["科技", "消费"])
        client = TestClient(api.app)
        headers = self._headers("funds:read")

        resp = client.get(
            "/api/agent/tools/screen?types=混合型&types=混合型&sectors=科技",
            headers=headers)
        assert resp.status_code == 200
        assert resp.json()["tool"] == "screen_funds"
        data = resp.json()["data"]
        assert [f["code"] for f in data["funds"]] == ["000001", "110011"]
        assert data["total"] == 2
        assert data["with_metrics"] is False
        assert data["metrics"] == {
            "requested": False, "limit": 30, "attempted": 0,
            "succeeded": 0, "failed": 0, "timed_out": 0, "complete": True}
        assert data["funds"][0]["metrics_status"] == "not_requested"
        assert data["funds"][0]["returns"] is None
        assert data["funds"][0]["risk"] is None

        assert client.get(
            "/api/agent/tools/screen?types=股票型",
            headers=headers).status_code == 400
        assert client.get(
            "/api/agent/tools/screen?sectors=未知板块",
            headers=headers).status_code == 400
        many = "&".join(f"types=类型{i}" for i in range(21))
        assert client.get(
            f"/api/agent/tools/screen?{many}",
            headers=headers).status_code == 400
        assert client.get(
            "/api/agent/tools/screen?keyword=" + "基" * 101,
            headers=headers).status_code == 400
        assert client.get(
            "/api/agent/tools/screen",
            headers=self._headers("health:read")).status_code == 403

    def test_screen_funds_metrics_partial_and_busy(self, temp_db, monkeypatch):
        monkeypatch.setattr(config, "AUTH_ENABLED", True)
        universe = [
            {"code": "000001", "name": "华夏成长混合",
             "type": "混合型", "sector": "科技"},
            {"code": "110011", "name": "易方达中小盘混合",
             "type": "混合型", "sector": "科技"},
        ]
        monkeypatch.setattr(
            api.fund_filter, "load_fund_universe",
            lambda force_refresh=False: universe)
        client = TestClient(api.app)
        headers = self._headers("funds:read")

        def fake_enrich(items, timeout=20.0):
            stats = api.fund_filter.MetricsEnrichment(attempted=len(items))
            snapshots = {
                items[0].code: {
                    "scale": 100.0, "manager": "经理",
                    "inception_date": "2018-01-01",
                    "returns": {"1y": 0.1}, "risk": {"volatility": 0.2},
                },
            }
            stats.succeeded = 1
            stats.failed = len(items) - 1
            stats.complete = True
            return snapshots, stats

        monkeypatch.setattr(
            api.fund_filter, "enrich_page_metrics", fake_enrich)
        resp = client.get(
            "/api/agent/tools/screen?with_metrics=true", headers=headers)
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["with_metrics"] is True
        assert data["metrics"]["succeeded"] == 1
        assert data["metrics"]["failed"] == 1
        assert data["funds"][0]["metrics_status"] == "ok"
        assert data["funds"][0]["returns"] == {"1y": 0.1}
        assert data["funds"][1]["metrics_status"] == "unavailable"
        assert data["funds"][1]["returns"] is None

        def busy(items, timeout=20.0):
            raise api.fund_filter.EnrichmentBusy("指标增强并发已满")

        monkeypatch.setattr(
            api.fund_filter, "enrich_page_metrics", busy)
        limited = client.get(
            "/api/agent/tools/screen?with_metrics=true", headers=headers)
        assert limited.status_code == 429
        assert limited.headers["Retry-After"] == "60"

    def _fee_rates(self, ok: bool = True) -> FeeRates:
        return FeeRates(
            fund_code="000001",
            ok=ok,
            purchase=[PurchaseTier(min_amount=0, rate=0.001)] if ok else [],
            redemption=([RedemptionTier(min_days=0, max_days=6, rate=0.015),
                         RedemptionTier(min_days=7, max_days=None, rate=0.005)]
                        if ok else []),
        )

    def test_backtest_requires_post_token_scope(self, temp_db, monkeypatch):
        monkeypatch.setattr(config, "AUTH_ENABLED", True)
        payload = {
            "fund_codes": ["000001"],
            "start_date": "2024-01-01",
            "end_date": "2024-03-31",
            "amount_per_period": 1000,
        }
        client = TestClient(api.app)

        assert client.post(
            "/api/agent/tools/backtest/dca", json=payload).status_code == 401
        assert client.post(
            "/api/agent/tools/backtest/dca", json=payload,
            headers=self._headers("portfolio:read")).status_code == 403
        assert client.get(
            "/api/agent/tools/backtest/dca",
            headers=self._headers("funds:read")).status_code == 405

    def test_backtest_validation_edges(self, temp_db, monkeypatch):
        monkeypatch.setattr(config, "AUTH_ENABLED", True)
        client = TestClient(api.app)
        headers = self._headers("funds:read")
        base = {
            "fund_codes": ["000001"],
            "start_date": "2024-01-01",
            "end_date": "2024-03-31",
            "amount_per_period": 1000,
        }

        def post(**overrides):
            body = {**base, **overrides}
            return client.post(
                "/api/agent/tools/backtest/dca", json=body, headers=headers)

        assert post(fund_codes=[]).status_code == 422
        assert post(fund_codes=["000001"] * 6).status_code == 422
        assert post(fund_codes=["12345"]).status_code == 422
        assert post(start_date="2024-03-31", end_date="2024-03-01").status_code == 422
        assert post(start_date="2024-02-30").status_code == 422
        assert post(end_date="2999-01-01").status_code == 422
        assert post(start_date="2014-01-01", end_date="2024-01-02").status_code == 422
        assert post(amount_per_period=0).status_code == 422
        assert post(amount_per_period=True).status_code == 422
        assert post(amount_per_period=1_000_001).status_code == 422
        assert post(cadence="daily").status_code == 422
        assert post(max_points=9).status_code == 422
        assert post(extra_field=True).status_code == 422

    def test_backtest_success_curve_sampling_and_periods(
            self, temp_db, monkeypatch):
        monkeypatch.setattr(config, "AUTH_ENABLED", True)
        rows = [
            {"date": "2024-01-02", "nav": 1.0},
            {"date": "2024-02-01", "nav": 1.1},
            {"date": "2024-03-01", "nav": 1.2},
        ]
        monkeypatch.setattr(
            api.backtest, "readonly_nav_rows",
            lambda code, start, end: (rows, "database"))
        monkeypatch.setattr(
            api.fetch_fund, "fetch_fund_fee_rates",
            lambda code: self._fee_rates())
        client = TestClient(api.app)

        resp = client.post(
            "/api/agent/tools/backtest/dca",
            json={
                "fund_codes": ["000001", "000001"],
                "start_date": "2024-01-01",
                "end_date": "2024-03-31",
                "amount_per_period": 1000,
                "include_curve": True,
                "include_periods": False,
                "max_points": 10,
            },
            headers=self._headers("funds:read"))
        assert resp.status_code == 200
        body = resp.json()
        assert body["tool"] == "run_dca_backtest"
        data = body["data"]
        assert data["ok"] is True
        assert data["fund_count"] == 1
        assert data["result_count"] == 2  # dca + lumpsum
        dca = data["results"][0]
        assert dca["strategy"] == "dca"
        assert dca["status"] == "ok"
        assert dca["data_source"] == "database"
        assert dca["data_start"] == "2024-01-02"
        assert dca["data_end"] == "2024-03-01"
        assert dca["valuation_date"] == "2024-03-01"
        assert dca["total_periods"] == 3
        assert dca["fee_ok"] is True
        assert dca["periods_detail"] == []
        assert dca["periods_detail_count"] == 3
        assert 0 < dca["curve_points"] <= 10
        assert dca["curve"]
        lump = data["results"][1]
        assert lump["strategy"] == "lumpsum"
        assert lump["invested_capital"] == dca["invested_capital"]

    def test_backtest_partial_and_failed_results(self, temp_db, monkeypatch):
        monkeypatch.setattr(config, "AUTH_ENABLED", True)
        gap_rows = [
            {"date": "2024-01-01", "nav": 1.0},
            {"date": "2024-02-01", "nav": 1.1},
        ]

        def provider(code, start, end):
            if code == "000001":
                return gap_rows, "database"
            return [], "none"

        monkeypatch.setattr(api.backtest, "readonly_nav_rows", provider)
        monkeypatch.setattr(
            api.fetch_fund, "fetch_fund_fee_rates",
            lambda code: self._fee_rates())
        client = TestClient(api.app)
        headers = self._headers("funds:read")

        resp = client.post(
            "/api/agent/tools/backtest/dca",
            json={
                "fund_codes": ["000001", "000002"],
                "start_date": "2024-01-01",
                "end_date": "2024-02-01",
                "amount_per_period": 100,
                "cadence": "week",
                "include_lumpsum": False,
            },
            headers=headers)
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["ok"] is True
        assert data["failed_count"] == 1
        assert "1 个回测失败" in data["message"]
        partial = data["results"][0]
        assert partial["status"] == "partial"
        assert partial["code"] == "partial_coverage"
        assert partial["skipped_periods"] > 0
        failed = data["results"][1]
        assert failed["status"] == "failed"
        assert failed["code"] == "insufficient_nav"
        assert failed["net_final_value"] == 0

        all_failed = client.post(
            "/api/agent/tools/backtest/dca",
            json={
                "fund_codes": ["000002"],
                "start_date": "2024-01-01",
                "end_date": "2024-02-01",
                "amount_per_period": 100,
            },
            headers=headers)
        body = all_failed.json()["data"]
        assert body["ok"] is False
        assert body["message"]

    def test_backtest_zero_fee_unknown_is_explicit(self, temp_db, monkeypatch):
        monkeypatch.setattr(config, "AUTH_ENABLED", True)
        rows = [{"date": "2024-01-02", "nav": 1.0},
                {"date": "2024-02-01", "nav": 1.1}]
        monkeypatch.setattr(
            api.backtest, "readonly_nav_rows",
            lambda code, start, end: (rows, "remote"))
        monkeypatch.setattr(
            api.fetch_fund, "fetch_fund_fee_rates",
            lambda code: self._fee_rates(ok=False))
        client = TestClient(api.app)

        resp = client.post(
            "/api/agent/tools/backtest/dca",
            json={
                "fund_codes": ["000001"],
                "start_date": "2024-01-01",
                "end_date": "2024-02-01",
                "amount_per_period": 100,
            },
            headers=self._headers("funds:read"))
        dca = resp.json()["data"]["results"][0]
        assert dca["fee_ok"] is False
        assert dca["total_fees"] == 0
        assert any("费率表获取失败" in item for item in dca["caveats"])

    def test_backtest_concurrency_busy_returns_429(
            self, temp_db, monkeypatch):
        monkeypatch.setattr(config, "AUTH_ENABLED", True)
        gate = threading.BoundedSemaphore(1)
        assert gate.acquire(blocking=False)
        monkeypatch.setattr(api, "_AGENT_BACKTEST_GATE", gate)
        client = TestClient(api.app)

        resp = client.post(
            "/api/agent/tools/backtest/dca",
            json={
                "fund_codes": ["000001"],
                "start_date": "2024-01-01",
                "end_date": "2024-03-31",
                "amount_per_period": 1000,
            },
            headers=self._headers("funds:read"))

        assert resp.status_code == 429
        assert resp.headers["Retry-After"] == "60"
        gate.release()

    def test_agent_capabilities_filters_by_scope(self, temp_db, monkeypatch):
        monkeypatch.setattr(config, "AUTH_ENABLED", True)
        client = TestClient(api.app)
        headers = self._headers("portfolio:read", "transactions:read")

        resp = client.get("/api/agent/tools/capabilities", headers=headers)
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["granted_scopes"] == ["portfolio:read", "transactions:read"]
        names = {t["name"] for t in data["tools"]}
        assert "get_portfolio_summary" in names
        assert "list_transactions" in names
        assert "get_transaction" in names
        assert "get_agent_capabilities" in names  # 无 scope 要求，始终可见
        assert "get_data_status" not in names  # health:read 未授予
        assert "list_alerts" not in names
        for tool in data["tools"]:
            assert tool["risk"] == "read"
            assert tool["requires_confirmation"] is False

        # 任意有效 token 均可调用，不需要特定 scope
        minimal = client.get(
            "/api/agent/tools/capabilities",
            headers=self._headers("funds:read"))
        assert minimal.status_code == 200
        minimal_names = {t["name"] for t in minimal.json()["data"]["tools"]}
        assert "compare_funds" in minimal_names
        assert "get_portfolio_summary" not in minimal_names

    def test_rate_limit_shared_across_fund_codes(self, temp_db, monkeypatch):
        """基金代码是路径参数，不同代码必须共用同一个限流桶。"""
        monkeypatch.setattr(config, "AUTH_ENABLED", True)
        monkeypatch.setattr(api, "_AGENT_RATE_MAX", 1)
        monkeypatch.setattr(api, "_AGENT_REQ_LOGS", {})
        client = TestClient(api.app)
        headers = self._headers("funds:read")

        first = client.get("/api/agent/tools/funds/000001", headers=headers)
        second = client.get("/api/agent/tools/funds/000002", headers=headers)
        assert first.status_code == 404
        assert second.status_code == 429

    def test_route_specific_rate_limit_override(self, temp_db, monkeypatch):
        monkeypatch.setattr(config, "AUTH_ENABLED", True)
        monkeypatch.setattr(api, "_AGENT_REQ_LOGS", {})
        monkeypatch.setitem(
            api._AGENT_ROUTE_RATE_MAX, "/api/agent/tools/screen", 1)
        monkeypatch.setattr(
            api.fund_filter, "load_fund_universe",
            lambda force_refresh=False: [
                {"code": "000001", "name": "华夏成长混合",
                 "type": "混合型", "sector": "科技"}])
        client = TestClient(api.app)
        headers = self._headers("funds:read")

        # 搜索与筛选使用不同限流桶，搜索的额度不影响筛选
        assert client.get(
            "/api/agent/tools/search?keyword=华夏",
            headers=headers).status_code == 200
        first = client.get("/api/agent/tools/screen", headers=headers)
        second = client.get("/api/agent/tools/screen", headers=headers)
        assert first.status_code == 200
        assert second.status_code == 429
        assert second.headers["Retry-After"]

    def test_web_token_cannot_call_tools(self, admin_client):
        client, headers = admin_client
        assert client.get(
            "/api/agent/tools/portfolio-summary", headers=headers
        ).status_code == 401

    def test_missing_token_is_401(self, temp_db, monkeypatch):
        monkeypatch.setattr(config, "AUTH_ENABLED", True)
        assert TestClient(api.app).get(
            "/api/agent/tools/portfolio-summary").status_code == 401

    def test_auth_disabled_rejects_tools(self, temp_db, monkeypatch):
        monkeypatch.setattr(config, "AUTH_ENABLED", False)
        resp = TestClient(api.app).get(
            "/api/agent/tools/portfolio-summary",
            headers={"Authorization": "Bearer zfag_whatever"})
        assert resp.status_code == 403

    def test_unknown_tool_still_requires_token(self, temp_db, monkeypatch):
        """结构性默认拒绝：即使路径不存在，没有有效 token 也先返回 401。"""
        monkeypatch.setattr(config, "AUTH_ENABLED", True)
        client = TestClient(api.app)
        assert client.get("/api/agent/tools/does-not-exist").status_code == 401
        assert client.get(
            "/api/agent/tools/does-not-exist",
            headers=self._headers("portfolio:read"),
        ).status_code == 404
