"""B6 安全类回归测试。

覆盖：OPTIONS 预检放行、change-password/username/agent-write 升级认证
共享登录锁定桶、Agent 鉴权失败按 IP 限流、登录用户名枚举耗时均衡、
IPv6/IPv4-mapped 客户端 IP 识别。
"""
from __future__ import annotations

import asyncio
import ipaddress
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace

import pytest
from fastapi.middleware.cors import CORSMiddleware
from fastapi.testclient import TestClient
from starlette.requests import Request
from starlette.responses import Response

from zfundpilot import agent_tokens, api, config, db

PASSWORD = "correct-horse-battery"


@pytest.fixture
def temp_db(monkeypatch):
    with TemporaryDirectory() as d:
        monkeypatch.setattr(config, "DB_PATH", str(Path(d) / "test.db"))
        monkeypatch.setattr(config, "AUTH_DATA_PATH", str(Path(d) / "auth.json"))
        db.init_db()
        yield


@pytest.fixture
def client(temp_db, monkeypatch):
    monkeypatch.setattr(config, "AUTH_ENABLED", True)
    monkeypatch.setattr(config, "AUTH_SECRET", "test-secret")
    monkeypatch.setattr(config, "AUTH_USERNAME", "admin")
    monkeypatch.setattr(config, "AUTH_PASSWORD_HASH",
                        config._hash_password_sha256(PASSWORD))
    monkeypatch.setattr(config, "AGENT_WRITE_ENABLED", False)
    monkeypatch.setattr(config, "AGENT_WRITE_ENV_LOCKED", False)
    monkeypatch.setattr(config, "AGENT_WRITE_ENV_DEFAULT", False)
    # 隔离限流状态，避免跨测试/跨文件污染
    monkeypatch.setattr(api, "_LOGIN_ATTEMPTS", {})
    monkeypatch.setattr(api, "_LOGIN_LOCKED_UNTIL", {})
    monkeypatch.setattr(api, "_AGENT_AUTH_FAILS", {})
    monkeypatch.setattr(api, "_REQ_LOGS", {})
    monkeypatch.setattr(api, "_AGENT_REQ_LOGS", {})
    return TestClient(api.app)


def _web_headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {api._create_token()}"}


def _audits(action: str) -> list[dict]:
    return [r for r in db.fetch_audit_logs(500) if r["action"] == action]


def _detail(row: dict) -> dict:
    import json
    return json.loads(row["detail"]) if row["detail"] else {}


# ---------------------------------------------------------------------------
# OPTIONS 预检放行（auth 中间件先于 CORS 执行，不得 401 拦截预检）
# ---------------------------------------------------------------------------

class TestOptionsPreflight:
    def test_auth_middleware_passes_options(self, monkeypatch):
        monkeypatch.setattr(config, "AUTH_ENABLED", True)
        scope = {"type": "http", "method": "OPTIONS", "path": "/api/transactions",
                 "headers": [], "query_string": b""}
        request = Request(scope)
        called = []

        async def call_next(req):
            called.append(True)
            return Response(status_code=200)

        resp = asyncio.run(api.auth_middleware(request, call_next))
        assert called == [True]
        assert resp.status_code == 200

    def test_preflight_not_blocked_by_auth(self, client):
        # 默认未配置跨域源：CORS 拒绝（400），但绝不能是 auth 的 401
        resp = client.options("/api/transactions", headers={
            "Origin": "http://cross.example",
            "Access-Control-Request-Method": "GET",
        })
        assert resp.status_code != 401

    def test_preflight_succeeds_with_allowed_origin(self, client, monkeypatch):
        # 临时允许一个跨域源并重建中间件栈，验证预检能拿到 CORS 头
        for m in api.app.user_middleware:
            if m.cls is CORSMiddleware:
                monkeypatch.setitem(m.kwargs, "allow_origins",
                                    ["http://allowed.example"])
        monkeypatch.setattr(api.app, "middleware_stack", None)
        resp = client.options("/api/transactions", headers={
            "Origin": "http://allowed.example",
            "Access-Control-Request-Method": "GET",
        })
        assert resp.status_code == 200
        assert resp.headers["access-control-allow-origin"] == "http://allowed.example"

    def test_agent_preflight_not_blocked(self, client):
        resp = client.options("/api/agent/tools/funds", headers={
            "Origin": "http://cross.example",
            "Access-Control-Request-Method": "GET",
        })
        assert resp.status_code != 401


# ---------------------------------------------------------------------------
# 升级认证（change-password / change-username / agent-write）共享登录锁定桶
# ---------------------------------------------------------------------------

class TestStepupLockout:
    def test_change_password_wrong_counts_and_audits(self, client):
        resp = client.post("/api/auth/change-password", headers=_web_headers(),
                           json={"current_password": "wrong", "new_password": "newpass123"})
        assert resp.status_code == 401
        assert len(api._LOGIN_ATTEMPTS["testclient"]) == 1
        rows = _audits("login_failed")
        assert len(rows) == 1
        assert _detail(rows[0])["source"] == "change_password"
        assert _detail(rows[0])["reason"] == "wrong_password"

    def test_change_password_lockout_shared_with_login(self, client):
        for _ in range(config.LOGIN_MAX_FAILURES):
            resp = client.post("/api/auth/change-password", headers=_web_headers(),
                               json={"current_password": "wrong", "new_password": "newpass123"})
            assert resp.status_code == 401
        # 锁定后：change-password 与 login 共享同一桶，均 429
        resp = client.post("/api/auth/change-password", headers=_web_headers(),
                           json={"current_password": "wrong", "new_password": "newpass123"})
        assert resp.status_code == 429
        assert resp.json()["error"]["code"] == "login_rate_limited"
        resp = client.post("/api/auth/login",
                           json={"username": "admin", "password": PASSWORD})
        assert resp.status_code == 429

    def test_change_password_success_clears_bucket(self, client):
        for _ in range(config.LOGIN_MAX_FAILURES - 1):
            client.post("/api/auth/change-password", headers=_web_headers(),
                        json={"current_password": "wrong", "new_password": "newpass123"})
        resp = client.post("/api/auth/change-password", headers=_web_headers(),
                           json={"current_password": PASSWORD, "new_password": "newpass123"})
        assert resp.status_code == 200
        assert api._LOGIN_ATTEMPTS == {}
        assert api._LOGIN_LOCKED_UNTIL == {}

    def test_change_username_wrong_counts_and_audits(self, client):
        resp = client.post("/api/auth/change-username", headers=_web_headers(),
                           json={"current_password": "wrong", "new_username": "newadmin"})
        assert resp.status_code == 401
        assert len(api._LOGIN_ATTEMPTS["testclient"]) == 1
        rows = _audits("login_failed")
        assert _detail(rows[0])["source"] == "change_username"

    def test_change_username_lockout(self, client):
        for _ in range(config.LOGIN_MAX_FAILURES):
            client.post("/api/auth/change-username", headers=_web_headers(),
                        json={"current_password": "wrong", "new_username": "newadmin"})
        resp = client.post("/api/auth/change-username", headers=_web_headers(),
                           json={"current_password": "wrong", "new_username": "newadmin"})
        assert resp.status_code == 429

    def test_agent_write_wrong_password_counts_keeps_403(self, client):
        resp = client.put("/api/settings/agent-write", headers=_web_headers(),
                          json={"enabled": True, "password": "wrong"})
        # 保持既有 403 语义（前端据此不强制登出）
        assert resp.status_code == 403
        assert resp.json()["detail"]["code"] == "wrong_password"
        assert len(api._LOGIN_ATTEMPTS["testclient"]) == 1
        assert any(_detail(r)["source"] == "agent_write_enable"
                   for r in _audits("login_failed"))
        assert len(_audits("agent_write_toggle_denied")) == 1

    def test_agent_write_lockout_429(self, client):
        for _ in range(config.LOGIN_MAX_FAILURES):
            client.put("/api/settings/agent-write", headers=_web_headers(),
                       json={"enabled": True, "password": "wrong"})
        resp = client.put("/api/settings/agent-write", headers=_web_headers(),
                          json={"enabled": True, "password": "wrong"})
        assert resp.status_code == 429


# ---------------------------------------------------------------------------
# Agent 鉴权失败按 IP 限流（超限 429 且不再写审计）
# ---------------------------------------------------------------------------

class TestAgentAuthFailThrottle:
    def test_failures_throttled_and_audit_stops(self, client, monkeypatch):
        monkeypatch.setattr(api, "_AGENT_AUTH_FAIL_MAX", 3)
        for _ in range(3):
            resp = client.get("/api/agent/tools/funds")
            assert resp.status_code == 401
        assert len(_audits("agent_auth_failed")) == 3
        resp = client.get("/api/agent/tools/funds")
        assert resp.status_code == 429
        assert resp.headers.get("Retry-After")
        assert resp.json()["error"]["code"] == "rate_limited"
        # 超限后不再写审计（防审计表无界膨胀）
        assert len(_audits("agent_auth_failed")) == 3

    def test_success_does_not_reset_counter(self, client, monkeypatch):
        # 策略钉住：成功认证不清失败计数，窗口自然过期
        monkeypatch.setattr(api, "_AGENT_AUTH_FAIL_MAX", 3)
        for _ in range(2):
            assert client.get("/api/agent/tools/funds").status_code == 401
        plaintext, _info = agent_tokens.issue_token(
            "throttle-test", [agent_tokens.SCOPE_FUNDS_READ])
        ok = client.get("/api/agent/tools/capabilities",
                        headers={"Authorization": f"Bearer {plaintext}"})
        assert ok.status_code == 200
        assert client.get("/api/agent/tools/funds").status_code == 401
        # 第 4 次失败触发锁定：即使持有效 token 也 429
        resp = client.get("/api/agent/tools/capabilities",
                          headers={"Authorization": f"Bearer {plaintext}"})
        assert resp.status_code == 429


# ---------------------------------------------------------------------------
# 登录用户名枚举耗时均衡（错用户名也执行一次哑 bcrypt 校验）
# ---------------------------------------------------------------------------

class TestLoginTimingEqualization:
    def test_dummy_hash_is_bcrypt_cost12(self):
        assert api._DUMMY_PASSWORD_HASH.startswith("$2b$12$")

    def test_wrong_username_runs_dummy_verify(self, client, monkeypatch):
        calls = []
        real = config.verify_password

        def spy(password, password_hash):
            calls.append(password_hash)
            return real(password, password_hash)

        monkeypatch.setattr(config, "verify_password", spy)
        resp = client.post("/api/auth/login",
                           json={"username": "nobody", "password": "whatever"})
        assert resp.status_code == 401
        assert calls == [api._DUMMY_PASSWORD_HASH]

    def test_wrong_password_uses_real_hash(self, client, monkeypatch):
        calls = []
        real = config.verify_password

        def spy(password, password_hash):
            calls.append(password_hash)
            return real(password, password_hash)

        monkeypatch.setattr(config, "verify_password", spy)
        resp = client.post("/api/auth/login",
                           json={"username": "admin", "password": "wrong"})
        assert resp.status_code == 401
        assert calls == [config.AUTH_PASSWORD_HASH]


# ---------------------------------------------------------------------------
# IPv6 / IPv4-mapped 客户端 IP
# ---------------------------------------------------------------------------

def _fake_request(host: str | None, xff: str | None = None):
    headers = {} if xff is None else {"x-forwarded-for": xff}
    client = None if host is None else SimpleNamespace(host=host)
    return SimpleNamespace(client=client, headers=headers)


class TestClientIp:
    def test_ipv4_mapped_hits_trusted_proxy(self, monkeypatch):
        monkeypatch.setattr(config, "TRUSTED_PROXIES",
                            [ipaddress.ip_network("127.0.0.0/8")])
        req = _fake_request("::ffff:127.0.0.1", "203.0.113.9")
        assert api._get_client_ip(req) == "203.0.113.9"

    def test_ipv6_not_trusted_ignores_xff(self, monkeypatch):
        monkeypatch.setattr(config, "TRUSTED_PROXIES",
                            [ipaddress.ip_network("127.0.0.0/8")])
        req = _fake_request("::1", "203.0.113.9")
        assert api._get_client_ip(req) == "::1"

    def test_ipv6_trusted_network(self, monkeypatch):
        monkeypatch.setattr(config, "TRUSTED_PROXIES",
                            [ipaddress.ip_network("::1/128")])
        req = _fake_request("::1", "203.0.113.9")
        assert api._get_client_ip(req) == "203.0.113.9"

    def test_untrusted_ipv4_ignores_xff(self, monkeypatch):
        monkeypatch.setattr(config, "TRUSTED_PROXIES",
                            [ipaddress.ip_network("127.0.0.0/8")])
        req = _fake_request("198.51.100.7", "203.0.113.9")
        assert api._get_client_ip(req) == "198.51.100.7"

    def test_invalid_host_returned_as_is(self, monkeypatch):
        monkeypatch.setattr(config, "TRUSTED_PROXIES", [])
        assert api._get_client_ip(_fake_request("testclient")) == "testclient"

    def test_no_client_unknown(self):
        assert api._get_client_ip(_fake_request(None)) == "unknown"