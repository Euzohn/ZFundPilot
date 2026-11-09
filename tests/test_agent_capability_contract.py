"""能力发现契约元数据测试：get_agent_capabilities 返回 side_effect/idempotent/limits/error_codes。"""
from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory

import pytest
from fastapi.testclient import TestClient

from zfundpilot import agent_tokens, api, config, db


@pytest.fixture
def client(monkeypatch):
    with TemporaryDirectory() as d:
        monkeypatch.setattr(config, "DB_PATH", str(Path(d) / "test.db"))
        monkeypatch.setattr(config, "AUTH_ENABLED", True)
        db.init_db()
        monkeypatch.setattr(api, "_REQ_LOGS", {})
        monkeypatch.setattr(api, "_AGENT_REQ_LOGS", {})
        yield TestClient(api.app)


def _all_scopes() -> list[str]:
    return [getattr(agent_tokens, s) for s in dir(agent_tokens)
            if s.startswith("SCOPE_")]


def _get_tools(client: TestClient) -> dict[str, dict]:
    plain, _ = agent_tokens.issue_token(
        "contract-agent", _all_scopes())
    r = client.get("/api/agent/tools/capabilities",
                   headers={"Authorization": f"Bearer {plain}"})
    assert r.status_code == 200, r.text
    return {t["name"]: t for t in r.json()["data"]["tools"]}


class TestCapabilityContract:
    def test_every_tool_carries_contract_fields(self, client):
        tools = _get_tools(client)
        assert len(tools) == 33
        for name, tool in tools.items():
            assert "side_effect" in tool, name
            assert "idempotent" in tool, name
            assert "limits" in tool, name
            assert "error_codes" in tool, name
            assert tool["side_effect"] in ("read", "additive", "mutating"), name
            assert isinstance(tool["idempotent"], bool), name
            assert isinstance(tool["limits"], dict), name
            assert isinstance(tool["error_codes"], list), name

    def test_side_effect_classification(self, client):
        tools = _get_tools(client)
        # 只读分析
        assert tools["get_portfolio_summary"]["side_effect"] == "read"
        assert tools["run_dca_backtest"]["side_effect"] == "read"
        # precheck 虽是 POST 但只读、不写账本不建提案
        assert tools["precheck_transactions"]["side_effect"] == "read"
        # additive 写：只追加不覆盖
        for name in ("add_watchlist_item", "start_data_refresh",
                     "create_operation_proposal", "record_transaction"):
            assert tools[name]["side_effect"] == "additive", name
        # mutating 写：可能覆盖/移除
        for name in ("update_watchlist_item", "remove_watchlist_item",
                     "cancel_operation_proposal"):
            assert tools[name]["side_effect"] == "mutating", name

    def test_idempotent_flag(self, client):
        tools = _get_tools(client)
        # 所有写类工具幂等（靠 Idempotency-Key 或天然幂等）
        for name, tool in tools.items():
            if tool["risk"] in ("write", "propose"):
                assert tool["idempotent"] is True, name

    def test_limits_surface_documented_caps(self, client):
        tools = _get_tools(client)
        assert tools["list_positions"]["limits"]["limit"] == "1-500 (default 200)"
        assert tools["compare_funds"]["limits"]["codes"] == "1-20"
        assert tools["run_dca_backtest"]["limits"]["fund_codes"] == "1-5"
        assert tools["create_operation_proposal"]["limits"][
            "batch_import.items"] == "1-50"
        # 无上限的只读工具 limits 为空 dict
        assert tools["get_portfolio_summary"]["limits"] == {}

    def test_error_codes_include_write_specific(self, client):
        tools = _get_tools(client)
        # 版本冲突码只在需要 row_digest/revision 的工具上出现
        assert "target_changed" in tools["update_watchlist_item"]["error_codes"]
        assert "target_changed" in tools["create_operation_proposal"]["error_codes"]
        assert "target_changed" not in tools["add_watchlist_item"]["error_codes"]
        # 回填/直记的费率未知码
        assert "fee_unknown" in tools["create_operation_proposal"]["error_codes"]
        assert "fee_unknown" in tools["record_transaction"]["error_codes"]
        # 只读工具不出现写总闸码
        assert "write_disabled" not in tools["get_portfolio_summary"]["error_codes"]
        assert "write_disabled" in tools["add_watchlist_item"]["error_codes"]
