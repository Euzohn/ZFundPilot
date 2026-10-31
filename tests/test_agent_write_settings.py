"""Agent 写能力设置端点测试：默认关闭、密码确认、env 紧急刹车、能力联动、审计。"""
from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest
from fastapi.testclient import TestClient

from zfundpilot import agent_tokens, api, config, db
from zfundpilot.analysis import clear_analysis_cache
from zfundpilot.models import Fund

SETTINGS = "/api/settings/agent-write"
AGENT_PROPOSALS = "/api/agent/tools/proposals"
PASSWORD = "correct-horse-battery"

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
    monkeypatch.setattr(config, "AUTH_PASSWORD_HASH",
                        config._hash_password_sha256(PASSWORD))
    monkeypatch.setattr(config, "AGENT_WRITE_ENABLED", False)
    # 固定 env 语义，避免宿主机环境变量影响断言
    monkeypatch.setattr(config, "AGENT_WRITE_ENV_LOCKED", False)
    monkeypatch.setattr(config, "AGENT_WRITE_ENV_DEFAULT", False)
    return TestClient(api.app)


def _web_headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {api._create_token()}"}


def _agent_headers(scopes: list[str]) -> dict[str, str]:
    plaintext, _ = agent_tokens.issue_token("test-agent", scopes)
    return {"Authorization": f"Bearer {plaintext}"}


def _audits(action: str) -> list[dict]:
    return [row for row in db.fetch_audit_logs(100) if row["action"] == action]


def _detail(row: dict) -> dict:
    return json.loads(row["detail"]) if row["detail"] else {}


def _enable(client: TestClient, password: str = PASSWORD, headers: dict | None = None):
    return client.put(
        SETTINGS, headers=headers or _web_headers(),
        json={"enabled": True, "password": password},
    )


class TestAgentWriteSettingsEndpoint:
    def test_default_disabled(self, client):
        response = client.get(SETTINGS, headers=_web_headers())

        assert response.status_code == 200
        assert response.json() == {
            "enabled": False,
            "locked": False,
            "can_enable": True,
            "source": "default",
        }
        assert config.AGENT_WRITE_ENABLED is False
        # 读取状态不应写入偏好记录
        assert db.get_preference(config.AGENT_WRITE_PREF_KEY) is None

    def test_enable_requires_correct_password(self, client):
        response = _enable(client, password="wrong-password")

        assert response.status_code == 403
        assert response.json()["detail"]["code"] == "wrong_password"
        assert db.get_preference(config.AGENT_WRITE_PREF_KEY) is None
        assert config.AGENT_WRITE_ENABLED is False
        denied = _audits("agent_write_toggle_denied")
        assert denied
        assert _detail(denied[0])["reason"] == "wrong_password"

    def test_enable_with_correct_password(self, client):
        response = _enable(client)

        assert response.status_code == 200
        body = response.json()
        assert body["ok"] is True
        assert body["enabled"] is True
        assert body["source"] == "settings"
        assert config.AGENT_WRITE_ENABLED is True
        assert db.get_preference(config.AGENT_WRITE_PREF_KEY) == "true"
        toggles = _audits("agent_write_toggle")
        assert toggles
        detail = _detail(toggles[0])
        assert detail["enabled"] is True
        assert detail["previous"] is False

    def test_disable_without_password(self, client):
        db.upsert_preference(config.AGENT_WRITE_PREF_KEY, "true")
        config.apply_agent_write_preference("true")
        assert config.AGENT_WRITE_ENABLED is True

        response = client.put(SETTINGS, headers=_web_headers(),
                              json={"enabled": False})

        assert response.status_code == 200
        assert response.json()["enabled"] is False
        assert config.AGENT_WRITE_ENABLED is False
        assert db.get_preference(config.AGENT_WRITE_PREF_KEY) == "false"
        toggles = _audits("agent_write_toggle")
        assert toggles
        assert _detail(toggles[0])["previous"] is True

    def test_enable_forbidden_without_web_auth(self, client, monkeypatch):
        monkeypatch.setattr(config, "AUTH_ENABLED", False)

        response = _enable(client)

        assert response.status_code == 403
        assert response.json()["detail"]["code"] == "auth_required"
        assert db.get_preference(config.AGENT_WRITE_PREF_KEY) is None
        denied = _audits("agent_write_toggle_denied")
        assert denied
        assert _detail(denied[0])["reason"] == "auth_required"

    def test_env_lock_forces_off(self, client, monkeypatch):
        monkeypatch.setattr(config, "AGENT_WRITE_ENV_LOCKED", True)
        # 即使数据库里曾开启，环境锁定也强制关闭
        db.upsert_preference(config.AGENT_WRITE_PREF_KEY, "true")

        status = client.get(SETTINGS, headers=_web_headers()).json()
        assert status == {
            "enabled": False,
            "locked": True,
            "can_enable": False,
            "source": "env_locked",
        }

        response = _enable(client)
        assert response.status_code == 403
        assert response.json()["detail"]["code"] == "env_forced_off"
        assert db.get_preference(config.AGENT_WRITE_PREF_KEY) == "true"
        assert config.AGENT_WRITE_ENABLED is False
        denied = _audits("agent_write_toggle_denied")
        assert denied
        assert _detail(denied[0])["reason"] == "env_forced_off"

    def test_unknown_field_rejected(self, client):
        response = client.put(
            SETTINGS, headers=_web_headers(),
            json={"enabled": True, "password": PASSWORD, "unexpected": 1},
        )
        assert response.status_code == 422


class TestCapabilitiesFollowSwitch:
    def test_capabilities_write_enabled_and_locked(self, client, monkeypatch):
        headers = _agent_headers([agent_tokens.SCOPE_WATCHLIST_WRITE])

        before = client.get("/api/agent/tools/capabilities", headers=headers).json()["data"]
        assert before["write_enabled"] is False
        assert before["write_locked"] is False
        tool = next(t for t in before["tools"] if t["name"] == "add_watchlist_item")
        assert tool["enabled"] is False

        assert _enable(client).status_code == 200

        after = client.get("/api/agent/tools/capabilities", headers=headers).json()["data"]
        assert after["write_enabled"] is True
        tool = next(t for t in after["tools"] if t["name"] == "add_watchlist_item")
        assert tool["enabled"] is True

        monkeypatch.setattr(config, "AGENT_WRITE_ENV_LOCKED", True)
        locked = client.get("/api/agent/tools/capabilities", headers=headers).json()["data"]
        assert locked["write_locked"] is True

    def test_proposal_creation_follows_switch(self, client):
        headers = {**_agent_headers([agent_tokens.SCOPE_TRANSACTIONS_PROPOSE])}
        payload = {"operation_type": "add_transaction", "params": BUY_PARAMS}

        blocked = client.post(
            AGENT_PROPOSALS, headers={**headers, "Idempotency-Key": "agent-write-off-key-01"},
            json=payload)
        assert blocked.status_code == 403
        assert blocked.json()["detail"]["code"] == "write_disabled"
        assert db.get_transactions_desc() == []

        assert _enable(client).status_code == 200

        created = client.post(
            AGENT_PROPOSALS, headers={**headers, "Idempotency-Key": "agent-write-on-key-01"},
            json=payload)
        assert created.status_code == 201
        assert created.json()["data"]["status"] == "pending"
        # 提案不直接写账本
        assert db.get_transactions_desc() == []

        assert client.put(SETTINGS, headers=_web_headers(),
                          json={"enabled": False}).status_code == 200
        blocked_again = client.post(
            AGENT_PROPOSALS, headers={**headers, "Idempotency-Key": "agent-write-off-key-02"},
            json=payload)
        assert blocked_again.status_code == 403
        assert blocked_again.json()["detail"]["code"] == "write_disabled"


class TestTransactionSwitchRecheck:
    """多 worker 场景：设置页写入 DB 后，其他进程事务内立即看到权威值。"""

    def _create_proposal(self, client: TestClient, key: str) -> int:
        headers = _agent_headers([agent_tokens.SCOPE_TRANSACTIONS_PROPOSE])
        response = client.post(
            AGENT_PROPOSALS, headers={**headers, "Idempotency-Key": key},
            json={"operation_type": "add_transaction", "params": BUY_PARAMS})
        assert response.status_code == 201
        return response.json()["data"]["proposal_id"]

    def _proposal_status(self, proposal_id: int) -> str:
        with db.get_connection() as conn:
            return db.get_proposal(conn, proposal_id)["status"]

    def test_db_off_blocks_approval_even_if_runtime_says_on(
            self, client, monkeypatch):
        monkeypatch.setattr(config, "AGENT_WRITE_ENABLED", True)
        proposal_id = self._create_proposal(client, "multi-worker-off-key-01")
        # 模拟另一 worker 在设置页关闭总闸：本进程运行时值仍旧为 True。
        db.upsert_preference(config.AGENT_WRITE_PREF_KEY, "false")
        assert config.AGENT_WRITE_ENABLED is True

        response = client.post(
            f"/api/proposals/{proposal_id}/approve", headers=_web_headers())

        assert response.status_code == 403
        assert response.json()["detail"]["code"] == "write_disabled"
        assert self._proposal_status(proposal_id) == "pending"
        assert db.get_transactions_desc() == []

    def test_db_on_allows_approval_even_if_runtime_says_off(
            self, client, monkeypatch):
        monkeypatch.setattr(config, "AGENT_WRITE_ENABLED", True)
        proposal_id = self._create_proposal(client, "multi-worker-on-key-01")
        # 模拟另一 worker 在设置页开启总闸：本进程运行时值仍旧为 False。
        db.upsert_preference(config.AGENT_WRITE_PREF_KEY, "true")
        monkeypatch.setattr(config, "AGENT_WRITE_ENABLED", False)

        response = client.post(
            f"/api/proposals/{proposal_id}/approve", headers=_web_headers())

        assert response.status_code == 200
        assert response.json()["status"] == "succeeded"
        assert self._proposal_status(proposal_id) == "succeeded"
        assert len(db.get_transactions_desc()) == 1


class TestResolveAgentWriteEnabled:
    def test_env_lock_wins_over_everything(self):
        assert config.resolve_agent_write_enabled(
            "true", env_locked=True, env_default=True) is False
        assert config.resolve_agent_write_enabled(
            None, env_locked=True, env_default=True) is False

    def test_stored_value_beats_env_default(self):
        assert config.resolve_agent_write_enabled(
            "false", env_locked=False, env_default=True) is False
        assert config.resolve_agent_write_enabled(
            "true", env_locked=False, env_default=False) is True

    def test_env_default_used_without_record(self):
        assert config.resolve_agent_write_enabled(
            None, env_locked=False, env_default=True) is True
        assert config.resolve_agent_write_enabled(
            None, env_locked=False, env_default=False) is False

    def test_apply_updates_runtime_flag(self, monkeypatch):
        monkeypatch.setattr(config, "AGENT_WRITE_ENV_LOCKED", False)
        monkeypatch.setattr(config, "AGENT_WRITE_ENV_DEFAULT", False)
        monkeypatch.setattr(config, "AGENT_WRITE_ENABLED", False)

        assert config.apply_agent_write_preference("true") is True
        assert config.AGENT_WRITE_ENABLED is True
        assert config.apply_agent_write_preference("false") is False
        assert config.AGENT_WRITE_ENABLED is False
        assert config.apply_agent_write_preference(None) is False

    def test_apply_respects_env_lock(self, monkeypatch):
        monkeypatch.setattr(config, "AGENT_WRITE_ENV_LOCKED", True)
        monkeypatch.setattr(config, "AGENT_WRITE_ENV_DEFAULT", False)
        monkeypatch.setattr(config, "AGENT_WRITE_ENABLED", True)

        assert config.apply_agent_write_preference("true") is False
        assert config.AGENT_WRITE_ENABLED is False

    def test_apply_respects_env_default_without_record(self, monkeypatch):
        monkeypatch.setattr(config, "AGENT_WRITE_ENV_LOCKED", False)
        monkeypatch.setattr(config, "AGENT_WRITE_ENV_DEFAULT", True)
        monkeypatch.setattr(config, "AGENT_WRITE_ENABLED", False)

        assert config.apply_agent_write_preference(None) is True
        assert config.AGENT_WRITE_ENABLED is True
