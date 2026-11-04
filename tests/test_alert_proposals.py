"""F6.1 提醒处理提案测试：创建校验、审批执行与 HTTP 门控。

覆盖：摘要失配、非 pending、类型不符、tx 关联校验、幂等；审批状态推进、
审计与网页事件名对齐、并发修改冲突、不写账本；HTTP 门控（alerts:propose
可进提案端点、跨域 403、写总闸、list_alerts 返回 row_digest）。
"""
from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest
from fastapi.testclient import TestClient

from zfundpilot import agent_tokens, api, config, db
from zfundpilot import proposal_service as svc
from zfundpilot.analysis import clear_analysis_cache
from zfundpilot.models import Fund, Transaction

PROPOSALS_PATH = "/api/agent/tools/proposals"
CAPABILITIES_PATH = "/api/agent/tools/capabilities"
KEY_A = "alert-key-aaaaaaaaaaaa"
KEY_B = "alert-key-bbbbbbbbbbbb"


@pytest.fixture
def temp_db(monkeypatch):
    with TemporaryDirectory() as d:
        monkeypatch.setattr(config, "DB_PATH", str(Path(d) / "test.db"))
        monkeypatch.setattr(config, "AUTH_ENABLED", True)
        monkeypatch.setattr(config, "AUTH_SECRET", "test-secret")
        monkeypatch.setattr(config, "AUTH_USERNAME", "admin")
        monkeypatch.setattr(config, "AGENT_WRITE_ENABLED", True)
        db._trade_cal_cache = None
        db._trade_cal_max = None
        db.init_db()
        db.upsert_fund(Fund("005827", "易方达蓝筹精选", "混合型", "消费"))
        clear_analysis_cache()
        yield
        clear_analysis_cache()


@pytest.fixture
def client(temp_db, monkeypatch):
    monkeypatch.setattr(api, "_REQ_LOGS", {})
    monkeypatch.setattr(api, "_AGENT_REQ_LOGS", {})
    return TestClient(api.app)


def _principal(*scopes: str, name: str = "test-agent") -> svc.Principal:
    _plain, info = agent_tokens.issue_token(name, list(scopes))
    return svc.Principal(
        "agent_token", str(info["id"]), f"agent:{info['token_prefix']}")


def _alert_principal() -> svc.Principal:
    return _principal(agent_tokens.SCOPE_ALERTS_PROPOSE)


def _make_dividend_alert(*, ex_date: str = "2026-01-10",
                         fund_code: str = "005827") -> int:
    return db.add_dividend_alert({
        "fund_code": fund_code, "fund_name": "易方达蓝筹精选",
        "record_date": "2026-01-08", "ex_date": ex_date,
        "per_share": 0.05, "pay_date": "2026-01-12",
        "held_shares": 1000.0, "estimated_amount": 50.0,
        "dividend_method": "cash",
    })


def _make_tp_sl_alert(*, alert_type: str = "take_profit") -> int:
    return db.add_tp_sl_alert({
        "fund_code": "005827", "fund_name": "易方达蓝筹精选",
        "alert_type": alert_type, "triggered_return": 0.25,
        "threshold": 0.2,
    })


def _alert_row(alert_id: int) -> dict:
    with db.get_connection() as conn:
        row = db.get_dividend_alert_conn(conn, alert_id)
    return dict(row)


def _digest(alert_id: int) -> str:
    return svc.alert_row_digest(_alert_row(alert_id))


def _params(alert_id: int, *, status: str = "confirmed",
            alert_type: str = "dividend",
            tx_id: int | None = None) -> dict:
    params = {
        "alert_type": alert_type, "alert_id": alert_id,
        "expected_digest": _digest(alert_id), "status": status,
    }
    if tx_id is not None:
        params["tx_id"] = tx_id
    return params


def _create(principal, params, *, key: str = KEY_A):
    return svc.create_proposal(
        principal, operation_type=svc.OPERATION_RESOLVE_ALERT,
        params=params, idempotency_key=key)


def _audit_actions() -> list[str]:
    return [row["action"] for row in db.fetch_audit_logs(200)]


def _dividend_tx(*, fund_code: str = "005827", action: str = "dividend") -> int:
    return db.add_transaction(Transaction(
        fund_code=fund_code, action=action, date="2026-01-12", amount=50.0))


def _set_alert(alert_id: int, **fields) -> None:
    db.update_dividend_alert(alert_id, **fields)


# ---------------------------------------------------------------------------
# 创建校验
# ---------------------------------------------------------------------------

class TestCreateResolveAlert:
    def test_confirm_dividend_creates_pending_proposal(self, temp_db):
        alert_id = _make_dividend_alert()
        result = _create(_alert_principal(), _params(alert_id))
        assert result.http_status == 201
        assert result.code == "created"
        summary = result.data["summary"]
        assert summary["operation_type"] == "resolve_alert"
        assert summary["alert_id"] == alert_id
        assert summary["alert_type"] == "dividend"
        assert summary["before_status"] == "pending"
        assert summary["after_status"] == "confirmed"
        assert summary["fund_code"] == "005827"
        assert summary["linked_tx_id"] is None
        assert any("未关联分红流水" in w for w in summary["warnings"])
        # 只创建提案，不改提醒状态、不写账本
        assert _alert_row(alert_id)["status"] == "pending"
        assert db.get_transactions_desc() == []
        assert "proposal_created" in _audit_actions()

    def test_ignore_tp_sl_alert(self, temp_db):
        alert_id = _make_tp_sl_alert(alert_type="stop_loss")
        result = _create(_alert_principal(), _params(
            alert_id, status="ignored", alert_type="stop_loss"))
        assert result.http_status == 201
        summary = result.data["summary"]
        assert summary["alert_type"] == "stop_loss"
        assert summary["after_status"] == "ignored"
        assert summary["linked_tx_id"] is None
        assert _alert_row(alert_id)["status"] == "pending"

    def test_alert_type_mismatch_rejected(self, temp_db):
        alert_id = _make_dividend_alert()
        with pytest.raises(svc.ProposalValidationError) as exc_info:
            _create(_alert_principal(), _params(
                alert_id, alert_type="take_profit"))
        assert exc_info.value.field == "alert_type"

    def test_target_not_found(self, temp_db):
        result = _create(_alert_principal(), {
            "alert_type": "dividend", "alert_id": 9999,
            "expected_digest": "a" * 64, "status": "confirmed"})
        assert result.http_status == 404
        assert result.code == "target_not_found"

    def test_not_pending_rejected(self, temp_db):
        alert_id = _make_dividend_alert()
        _set_alert(alert_id, status="confirmed",
                   resolved_at="2026-01-11T00:00:00")
        result = _create(_alert_principal(), _params(alert_id))
        assert result.http_status == 409
        assert result.code == "not_pending"

    def test_target_changed_when_digest_stale(self, temp_db):
        alert_id = _make_dividend_alert()
        params = _params(alert_id)
        # 提案前人为改动提醒字段（模拟网页侧修正分红金额）
        with db.get_connection(write=True) as conn:
            conn.execute(
                "UPDATE dividend_alerts SET per_share=0.06 WHERE id=?",
                (alert_id,))
        result = _create(_alert_principal(), params, key=KEY_B)
        assert result.http_status == 409
        assert result.code == "target_changed"

    @pytest.mark.parametrize("status", ["pending", "done", ""])
    def test_rejects_invalid_target_status(self, temp_db, status):
        alert_id = _make_dividend_alert()
        with pytest.raises(svc.ProposalValidationError) as exc_info:
            _create(_alert_principal(), _params(alert_id, status=status))
        assert exc_info.value.field == "status"

    @pytest.mark.parametrize("alert_type", ["dividend ", "tp_sl", "unknown"])
    def test_rejects_invalid_alert_type(self, temp_db, alert_type):
        alert_id = _make_dividend_alert()
        with pytest.raises(svc.ProposalValidationError) as exc_info:
            _create(_alert_principal(), _params(
                alert_id, alert_type=alert_type))
        assert exc_info.value.field == "alert_type"

    @pytest.mark.parametrize("bad_id", [0, -1, True, "1", 1.5])
    def test_rejects_invalid_alert_id(self, temp_db, bad_id):
        with pytest.raises(svc.ProposalValidationError) as exc_info:
            _create(_alert_principal(), {
                "alert_type": "dividend", "alert_id": bad_id,
                "expected_digest": "a" * 64, "status": "confirmed"})
        assert exc_info.value.field == "alert_id"

    def test_rejects_unknown_param(self, temp_db):
        alert_id = _make_dividend_alert()
        params = _params(alert_id)
        params["force"] = True
        with pytest.raises(svc.ProposalValidationError) as exc_info:
            _create(_alert_principal(), params)
        assert exc_info.value.field == "params"

    def test_links_existing_dividend_tx(self, temp_db):
        alert_id = _make_dividend_alert()
        tx_id = _dividend_tx()
        result = _create(_alert_principal(), _params(alert_id, tx_id=tx_id))
        assert result.http_status == 201
        summary = result.data["summary"]
        assert summary["linked_tx_id"] == tx_id
        assert not any("未关联分红流水" in w for w in summary["warnings"])
        assert _alert_row(alert_id)["tx_id"] is None

    def test_tx_not_found(self, temp_db):
        alert_id = _make_dividend_alert()
        result = _create(_alert_principal(), _params(alert_id, tx_id=9999))
        assert result.http_status == 409
        assert result.code == "tx_not_found"

    def test_tx_action_mismatch(self, temp_db):
        alert_id = _make_dividend_alert()
        tx_id = _dividend_tx(action="buy")
        result = _create(_alert_principal(), _params(alert_id, tx_id=tx_id))
        assert result.http_status == 409
        assert result.code == "tx_mismatch"

    def test_tx_fund_mismatch(self, temp_db):
        alert_id = _make_dividend_alert()
        tx_id = _dividend_tx(fund_code="000001")
        result = _create(_alert_principal(), _params(alert_id, tx_id=tx_id))
        assert result.http_status == 409
        assert result.code == "tx_mismatch"

    def test_tx_already_linked(self, temp_db):
        other = _make_dividend_alert(ex_date="2025-12-10")
        tx_id = _dividend_tx()
        _set_alert(other, tx_id=tx_id)
        alert_id = _make_dividend_alert()
        result = _create(_alert_principal(), _params(alert_id, tx_id=tx_id))
        assert result.http_status == 409
        assert result.code == "tx_already_linked"
        assert result.data["linked_alert_id"] == other

    @pytest.mark.parametrize("status,alert_type", [
        ("ignored", "dividend"), ("confirmed", "take_profit")])
    def test_tx_only_allowed_for_confirmed_dividend(
            self, temp_db, status, alert_type):
        alert_id = (_make_dividend_alert() if alert_type == "dividend"
                    else _make_tp_sl_alert())
        tx_id = _dividend_tx()
        with pytest.raises(svc.ProposalValidationError) as exc_info:
            _create(_alert_principal(), _params(
                alert_id, status=status, alert_type=alert_type, tx_id=tx_id))
        assert exc_info.value.field == "tx_id"

    def test_idempotent_replay(self, temp_db):
        alert_id = _make_dividend_alert()
        first = _create(_alert_principal(), _params(alert_id))
        second = _create(_alert_principal(), _params(alert_id))
        assert first.data["proposal_id"] == second.data["proposal_id"]
        assert second.replayed is True
        assert second.http_status == 200
        assert second.code == "replayed"

    def test_idempotency_conflict_on_param_change(self, temp_db):
        alert_id = _make_dividend_alert()
        _create(_alert_principal(), _params(alert_id))
        result = _create(_alert_principal(), _params(
            alert_id, status="ignored"))
        assert result.http_status == 409
        assert result.code == "idempotency_conflict"

    def test_unregistered_fund_still_creatable(self, temp_db):
        alert_id = _make_dividend_alert()
        with db.get_connection(write=True) as conn:
            conn.execute("DELETE FROM funds WHERE fund_code='005827'")
        result = _create(_alert_principal(), _params(alert_id))
        assert result.http_status == 201
        assert result.data["summary"]["fund_name"] == "005827"


def _audit_detail(action: str) -> dict:
    for row in db.fetch_audit_logs(100):
        if row["action"] == action:
            return json.loads(row["detail"] or "{}")
    raise AssertionError(f"未找到审计事件：{action}")


# ---------------------------------------------------------------------------
# 审批执行
# ---------------------------------------------------------------------------

class TestApprove:
    def test_approve_confirm_advances_alert_state(self, temp_db):
        alert_id = _make_dividend_alert()
        pid = _create(_alert_principal(), _params(alert_id)).data["proposal_id"]
        result = svc.approve_proposal(pid, reviewer="admin")
        assert result.http_status == 200
        assert result.code == "succeeded"
        assert result.data["status"] == "succeeded"
        row = _alert_row(alert_id)
        assert row["status"] == "confirmed"
        assert row["resolved_at"]
        assert row["tx_id"] is None
        # 不写账本
        assert db.get_transactions_desc() == []
        actions = _audit_actions()
        assert "dividend_alert_update" in actions
        assert "proposal_approved" in actions
        detail = _audit_detail("dividend_alert_update")
        assert detail["proposal_id"] == pid
        assert detail["status"] == "confirmed"

    def test_approve_ignore_without_resolution_tx(self, temp_db):
        alert_id = _make_dividend_alert()
        pid = _create(_alert_principal(), _params(
            alert_id, status="ignored")).data["proposal_id"]
        result = svc.approve_proposal(pid, reviewer="admin")
        assert result.http_status == 200
        assert _alert_row(alert_id)["status"] == "ignored"
        assert _alert_row(alert_id)["tx_id"] is None

    def test_approve_links_tx_without_creating_one(self, temp_db):
        alert_id = _make_dividend_alert()
        tx_id = _dividend_tx()
        pid = _create(_alert_principal(), _params(
            alert_id, tx_id=tx_id)).data["proposal_id"]
        result = svc.approve_proposal(pid, reviewer="admin")
        assert result.http_status == 200
        assert _alert_row(alert_id)["tx_id"] == tx_id
        assert len(db.get_transactions_desc()) == 1

    def test_approve_tp_sl_uses_web_audit_event(self, temp_db):
        alert_id = _make_tp_sl_alert(alert_type="take_profit")
        pid = _create(_alert_principal(), _params(
            alert_id, alert_type="take_profit")).data["proposal_id"]
        result = svc.approve_proposal(pid, reviewer="admin")
        assert result.http_status == 200
        assert _alert_row(alert_id)["status"] == "confirmed"
        actions = _audit_actions()
        assert "tp_sl_alert_update" in actions
        assert "dividend_alert_update" not in actions

    def test_approve_conflict_when_alert_changed(self, temp_db):
        alert_id = _make_dividend_alert()
        pid = _create(_alert_principal(), _params(alert_id)).data["proposal_id"]
        with db.get_connection(write=True) as conn:
            conn.execute(
                "UPDATE dividend_alerts SET per_share=0.06 WHERE id=?",
                (alert_id,))
        result = svc.approve_proposal(pid, reviewer="admin")
        assert result.http_status == 409
        assert result.code == "target_changed"
        assert result.data["status"] == "conflict"
        assert _alert_row(alert_id)["status"] == "pending"
        assert "proposal_conflict" in _audit_actions()

    def test_approve_conflict_when_already_processed(self, temp_db):
        alert_id = _make_dividend_alert()
        pid = _create(_alert_principal(), _params(alert_id)).data["proposal_id"]
        _set_alert(alert_id, status="ignored",
                   resolved_at="2026-01-11T00:00:00")
        result = svc.approve_proposal(pid, reviewer="admin")
        assert result.http_status == 409
        assert result.code == "not_pending"
        assert _audit_actions().count("dividend_alert_update") == 0

    def test_approve_conflict_when_alert_deleted(self, temp_db):
        alert_id = _make_dividend_alert()
        pid = _create(_alert_principal(), _params(alert_id)).data["proposal_id"]
        db.delete_dividend_alert(alert_id)
        result = svc.approve_proposal(pid, reviewer="admin")
        assert result.http_status == 409
        assert result.code == "target_deleted"

    def test_approve_conflict_when_type_changed(self, temp_db):
        alert_id = _make_dividend_alert()
        pid = _create(_alert_principal(), _params(alert_id)).data["proposal_id"]
        with db.get_connection(write=True) as conn:
            conn.execute(
                "UPDATE dividend_alerts SET alert_type='take_profit' "
                "WHERE id=?", (alert_id,))
        result = svc.approve_proposal(pid, reviewer="admin")
        assert result.http_status == 409
        assert result.code == "alert_type_changed"

    def test_approve_conflict_when_tx_taken_meanwhile(self, temp_db):
        alert_id = _make_dividend_alert()
        other = _make_dividend_alert(ex_date="2025-12-10")
        tx_id = _dividend_tx()
        pid = _create(_alert_principal(), _params(
            alert_id, tx_id=tx_id)).data["proposal_id"]
        _set_alert(other, tx_id=tx_id)
        result = svc.approve_proposal(pid, reviewer="admin")
        assert result.http_status == 409
        assert result.code == "tx_already_linked"
        assert _alert_row(alert_id)["tx_id"] is None

    def test_second_approve_rejected(self, temp_db):
        alert_id = _make_dividend_alert()
        pid = _create(_alert_principal(), _params(alert_id)).data["proposal_id"]
        assert svc.approve_proposal(pid, reviewer="admin").http_status == 200
        again = svc.approve_proposal(pid, reviewer="admin")
        assert again.http_status == 409
        assert again.code == "not_pending"


# ---------------------------------------------------------------------------
# HTTP 门控与错误形状
# ---------------------------------------------------------------------------

def _headers(scopes: list[str], *, key: str = "http-alert-key-0123456789"
             ) -> dict[str, str]:
    plaintext, _ = agent_tokens.issue_token("http-agent", scopes)
    return {"Authorization": f"Bearer {plaintext}",
            "Idempotency-Key": key}


class TestHttp:
    def test_create_requires_alerts_propose_scope(self, client):
        alert_id = _make_dividend_alert()
        headers = _headers([agent_tokens.SCOPE_ALERTS_READ])
        r = client.post(PROPOSALS_PATH, headers=headers, json={
            "operation_type": "resolve_alert", "params": _params(alert_id)})
        assert r.status_code == 403

    def test_transactions_propose_rejected_for_alert_op(self, client):
        # 端点接受任一提案 scope 进入，但按 operation_type 精确复核仍 403。
        alert_id = _make_dividend_alert()
        headers = _headers([agent_tokens.SCOPE_TRANSACTIONS_PROPOSE])
        r = client.post(PROPOSALS_PATH, headers=headers, json={
            "operation_type": "resolve_alert", "params": _params(alert_id)})
        assert r.status_code == 403

    def test_alerts_propose_rejected_for_ledger_op(self, client):
        headers = _headers([agent_tokens.SCOPE_ALERTS_PROPOSE])
        r = client.post(PROPOSALS_PATH, headers=headers, json={
            "operation_type": "add_transaction", "params": {
                "fund_code": "005827", "action": "buy",
                "date": "2025-01-02", "amount": 100.0}})
        assert r.status_code == 403

    def test_create_succeeds_and_returns_alert_summary(self, client):
        alert_id = _make_dividend_alert()
        headers = _headers([agent_tokens.SCOPE_ALERTS_PROPOSE])
        r = client.post(PROPOSALS_PATH, headers=headers, json={
            "operation_type": "resolve_alert", "params": _params(alert_id)})
        assert r.status_code == 201
        body = r.json()["data"]
        assert body["summary"]["operation_type"] == "resolve_alert"
        assert body["summary"]["alert_id"] == alert_id

    def test_write_gate_blocks_alert_proposal(self, client, monkeypatch):
        alert_id = _make_dividend_alert()
        monkeypatch.setattr(config, "AGENT_WRITE_ENABLED", False)
        headers = _headers([agent_tokens.SCOPE_ALERTS_PROPOSE])
        r = client.post(PROPOSALS_PATH, headers=headers, json={
            "operation_type": "resolve_alert", "params": _params(alert_id)})
        assert r.status_code == 403
        assert r.json()["detail"]["code"] == "write_disabled"

    def test_validation_error_shape(self, client):
        headers = _headers([agent_tokens.SCOPE_ALERTS_PROPOSE])
        r = client.post(PROPOSALS_PATH, headers=headers, json={
            "operation_type": "resolve_alert", "params": {
                "alert_type": "dividend", "alert_id": 0,
                "expected_digest": "a" * 64, "status": "confirmed"}})
        assert r.status_code == 422
        assert r.json()["detail"]["field"] == "alert_id"

    def test_capabilities_lists_proposal_tool(self, client):
        headers = _headers([agent_tokens.SCOPE_ALERTS_PROPOSE])
        r = client.get(CAPABILITIES_PATH, headers=headers)
        assert r.status_code == 200
        tools = {tool["name"]: tool for tool in r.json()["data"]["tools"]}
        assert tools["create_operation_proposal"]["risk"] == "propose"
        assert "list_operation_proposals" in tools
        # alerts:propose 不隐含只读提醒列表
        assert "list_alerts" not in tools

    def test_list_alerts_returns_row_digest(self, client):
        alert_id = _make_dividend_alert()
        headers = _headers([agent_tokens.SCOPE_ALERTS_READ])
        r = client.get("/api/agent/tools/alerts", headers=headers)
        assert r.status_code == 200
        item = r.json()["data"]["alerts"][0]
        assert item["id"] == alert_id
        assert item["row_digest"] == _digest(alert_id)

    def test_alerts_propose_can_list_own_proposals(self, client):
        alert_id = _make_dividend_alert()
        headers = _headers([agent_tokens.SCOPE_ALERTS_PROPOSE])
        created = client.post(PROPOSALS_PATH, headers=headers, json={
            "operation_type": "resolve_alert", "params": _params(alert_id)})
        assert created.status_code == 201
        pid = created.json()["data"]["proposal_id"]
        r = client.get(PROPOSALS_PATH, headers=headers)
        assert r.status_code == 200
        assert [item["proposal_id"] for item in r.json()["data"]["items"]] == [pid]
        detail = client.get(f"{PROPOSALS_PATH}/{pid}", headers=headers)
        assert detail.status_code == 200
        assert detail.json()["data"]["summary"]["alert_id"] == alert_id
