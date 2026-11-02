"""F4 批量追加导入测试：创建校验、原子执行、回滚与 HTTP 门控。

覆盖批内/批外重复、基金收录、逐条字段、上限、幂等、审批原子性与失败回滚。
"""
from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory

import pytest
from fastapi.testclient import TestClient

from zfundpilot import agent_tokens, api, config, db
from zfundpilot import proposal_service as svc
from zfundpilot.analysis import clear_analysis_cache
from zfundpilot.models import Fund

PROPOSALS_PATH = "/api/agent/tools/proposals"
KEY_A = "batch-key-aaaaaaaaaa"
KEY_B = "batch-key-bbbbbbbbbbbb"

BUY = {
    "fund_code": "005827", "action": "buy", "date": "2026-01-02",
    "amount": 1000.0, "shares": 100.0, "nav": 10.0, "fee": 1.0,
    "channel": "支付宝",
}
SELL = {
    "fund_code": "005827", "action": "sell", "date": "2026-01-03",
    "shares": 100.0, "nav": 10.0, "fee": 1.0, "channel": "支付宝",
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
        db.upsert_fund(Fund("161725", "招商中证白酒", "指数型", "消费"))
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


def _propose_principal() -> svc.Principal:
    return _principal(agent_tokens.SCOPE_TRANSACTIONS_PROPOSE)


def _create_batch(principal: svc.Principal, transactions: list[dict],
                  *, key: str = KEY_A, note: str = "",
                  extra: dict | None = None) -> svc.ProposalResult:
    params: dict = {"transactions": transactions, "note": note}
    if extra:
        params.update(extra)
    return svc.create_proposal(
        principal, operation_type=svc.OPERATION_BATCH_IMPORT,
        params=params, idempotency_key=key)


def _audit_actions() -> list[str]:
    return [row["action"] for row in db.fetch_audit_logs(200)]


def _delete_fund(code: str) -> None:
    with db.get_connection(write=True) as conn:
        conn.execute("DELETE FROM funds WHERE fund_code=?", (code,))


# ---------------------------------------------------------------------------
# 创建
# ---------------------------------------------------------------------------

class TestCreate:
    def test_creates_pending_without_writing_ledger(self, temp_db):
        result = _create_batch(_propose_principal(), [BUY, {**BUY, "date": "2026-01-03"}])

        assert result.http_status == 201
        assert result.code == "created"
        summary = result.data["summary"]
        assert summary["count"] == 2
        assert summary["actions"] == {"buy": 2}
        assert summary["date_range"] == {"from": "2026-01-02", "to": "2026-01-03"}
        assert summary["amount_total"] == 2000.0
        assert len(summary["items"]) == 2
        assert db.get_transactions_desc() == []
        assert "proposal_created" in _audit_actions()

    @pytest.mark.parametrize("transactions", [[], "not-a-list", [BUY] * 51])
    def test_rejects_invalid_structure(self, temp_db, transactions):
        with pytest.raises(svc.ProposalValidationError):
            svc.create_proposal(
                _propose_principal(),
                operation_type=svc.OPERATION_BATCH_IMPORT,
                params={"transactions": transactions}, idempotency_key=KEY_A)

    def test_rejects_invalid_item_with_index(self, temp_db):
        bad = {**BUY, "date": "2026-13-40"}
        with pytest.raises(svc.BatchValidationError) as exc_info:
            _create_batch(_propose_principal(), [BUY, bad])
        assert exc_info.value.index == 1
        assert exc_info.value.item_issues[0]["field"] == "date"
        assert db.get_transactions_desc() == []

    def test_rejects_unregistered_fund_with_index(self, temp_db):
        result = _create_batch(
            _propose_principal(),
            [BUY, {**BUY, "fund_code": "999999", "date": "2026-01-04"}])

        assert result.http_status == 409
        assert result.code == "fund_not_registered"
        assert result.data["index"] == 1
        assert result.data["fund_code"] == "999999"
        assert db.get_transactions_desc() == []

    def test_rejects_internal_duplicate(self, temp_db):
        result = _create_batch(
            _propose_principal(),
            [BUY, {**BUY, "date": "2026-01-03"}, {**BUY, "date": "2026-01-03"}])

        assert result.http_status == 409
        assert result.code == "batch_internal_duplicate"
        assert result.data["index"] == 1
        assert result.data["other_index"] == 2

    def test_duplicate_with_ledger_only_warns(self, temp_db):
        db.add_transaction(svc.Transaction(**BUY))
        result = _create_batch(_propose_principal(), [BUY])

        assert result.http_status == 201
        assert any("账本" in w for w in result.data["summary"]["warnings"])

    def test_duplicate_with_pending_only_warns(self, temp_db):
        principal = _propose_principal()
        pending = svc.create_proposal(
            principal, operation_type=svc.OPERATION_ADD_TRANSACTION,
            params=dict(BUY), idempotency_key="pending-key-0123456789")
        assert pending.ok

        result = _create_batch(principal, [BUY])

        assert result.http_status == 201
        assert any("待审提案" in w for w in result.data["summary"]["warnings"])

    def test_rejects_dividend_alert_in_batch(self, temp_db):
        dividend = {
            "fund_code": "005827", "action": "dividend", "date": "2026-01-02",
            "amount": 10.0, "channel": "支付宝", "dividend_alert_id": 7,
        }
        with pytest.raises(svc.BatchValidationError) as exc_info:
            _create_batch(_propose_principal(), [dividend])
        assert exc_info.value.item_issues[0]["code"] == "unsupported_in_batch"

    def test_rejects_fund_name_instead_of_code(self, temp_db):
        named = {"fund_name": "易方达蓝筹精选", "action": "buy",
                 "date": "2026-01-02", "amount": 1000.0, "channel": "支付宝"}
        with pytest.raises(svc.BatchValidationError) as exc_info:
            _create_batch(_propose_principal(), [named])
        assert exc_info.value.index == 0

    def test_ignores_clear_existing_with_warning(self, temp_db):
        result = _create_batch(
            _propose_principal(), [BUY], extra={"clear_existing": True})

        assert result.http_status == 201
        assert result.data["summary"]["count"] == 1
        assert any("已忽略" in w for w in result.data["summary"]["warnings"])
        assert result.data["params"]["ignored_fields"] == ["clear_existing"]
        assert db.get_transactions_desc() == []

    def test_rejects_unknown_top_level_field(self, temp_db):
        with pytest.raises(svc.ProposalValidationError):
            _create_batch(
                _propose_principal(), [BUY], extra={"clear_existng": True})

    @pytest.mark.parametrize("malformed", [
        [{"x": 1}],      # 不可哈希元素：曾触发未捕获 TypeError → 500
        "clear_existing",  # 非数组
        123,
    ])
    def test_rejects_malformed_ignored_fields(self, temp_db, malformed):
        with pytest.raises(svc.ProposalValidationError) as exc_info:
            _create_batch(
                _propose_principal(), [BUY],
                extra={"ignored_fields": malformed})
        assert exc_info.value.field == "ignored_fields"

    def test_idempotent_replay(self, temp_db):
        principal = _propose_principal()
        first = _create_batch(principal, [BUY])
        second = _create_batch(principal, [BUY])

        assert second.replayed is True
        assert second.data["proposal_id"] == first.data["proposal_id"]

    def test_same_key_different_params_conflicts(self, temp_db):
        principal = _propose_principal()
        _create_batch(principal, [BUY])
        result = _create_batch(principal, [SELL])

        assert result.http_status == 409
        assert result.code == "idempotency_conflict"

    def test_limits_pending_per_owner(self, temp_db):
        principal = _propose_principal()
        for i in range(svc.MAX_PENDING_PER_OWNER):
            result = _create_batch(
                principal, [BUY], key=f"batch-key-{i:016d}")
            assert result.ok
        overflow = _create_batch(principal, [BUY], key="batch-key-overflow")

        assert overflow.http_status == 409
        assert overflow.code == "too_many_pending"


# ---------------------------------------------------------------------------
# 审批执行
# ---------------------------------------------------------------------------

class TestApprove:
    def test_approve_writes_all_atomically(self, temp_db):
        pid = _create_batch(
            _propose_principal(), [BUY, {**SELL, "date": "2026-01-03"}]
        ).data["proposal_id"]

        result = svc.approve_proposal(pid, reviewer="admin")

        assert result.http_status == 200
        assert result.code == "succeeded"
        execution = result.data["execution_result"]
        assert execution["ok"] is True
        assert execution["count"] == 2
        assert len(execution["tx_ids"]) == 2
        txs = db.get_transactions_desc()
        assert len(txs) == 2
        assert {t.action for t in txs} == {"buy", "sell"}
        assert "proposal_approved" in _audit_actions()
        assert _audit_actions().count("add_transaction") >= 2

    def test_approve_fund_missing_rolls_back(self, temp_db):
        pid = _create_batch(_propose_principal(), [BUY]).data["proposal_id"]
        _delete_fund("005827")

        result = svc.approve_proposal(pid, reviewer="admin")

        assert result.http_status == 409
        assert result.code == "fund_missing"
        assert result.data["index"] == 0
        assert db.get_transactions_desc() == []
        assert svc.get_proposal_admin(pid).data["status"] == svc.STATUS_CONFLICT

    def test_approve_insufficient_shares_rolls_back(self, temp_db):
        sell = {**SELL, "shares": 50.0}
        pid = _create_batch(_propose_principal(), [sell]).data["proposal_id"]

        result = svc.approve_proposal(pid, reviewer="admin")

        assert result.http_status == 409
        assert result.code == "insufficient_shares_after_change"
        assert result.data["index"] == 0
        assert db.get_transactions_desc() == []

    def test_approve_buy_then_sell_within_batch(self, temp_db):
        # 账本原余额 0：批内先买 100 再卖 100，最终余额 0，应整批成功。
        pid = _create_batch(
            _propose_principal(),
            [{**BUY, "shares": 100.0}, {**SELL, "shares": 100.0}],
        ).data["proposal_id"]

        result = svc.approve_proposal(pid, reviewer="admin")

        assert result.http_status == 200
        assert len(db.get_transactions_desc()) == 2

    def test_approve_cleared_ignored_fields_still_succeeds(self, temp_db):
        # 创建时 ignored_fields 会写入 params；审批期重新校验必须放行。
        pid = _create_batch(
            _propose_principal(), [BUY], extra={"clear_existing": True},
        ).data["proposal_id"]

        result = svc.approve_proposal(pid, reviewer="admin")

        assert result.http_status == 200
        assert len(db.get_transactions_desc()) == 1

    def test_approve_twice_does_not_write_twice(self, temp_db):
        pid = _create_batch(_propose_principal(), [BUY]).data["proposal_id"]
        svc.approve_proposal(pid, reviewer="admin")
        result = svc.approve_proposal(pid, reviewer="admin")

        assert result.http_status == 409
        assert result.code == "not_pending"
        assert len(db.get_transactions_desc()) == 1

    def test_approve_expired(self, temp_db):
        pid = _create_batch(_propose_principal(), [BUY]).data["proposal_id"]
        with db.get_connection(write=True) as conn:
            conn.execute(
                "UPDATE operation_proposals SET expires_at=? WHERE id=?",
                ("2000-01-01T00:00:00", pid))

        result = svc.approve_proposal(pid, reviewer="admin")

        assert result.http_status == 409
        assert result.code == "expired"
        assert db.get_transactions_desc() == []


# ---------------------------------------------------------------------------
# HTTP 门控与错误形状
# ---------------------------------------------------------------------------

def _headers(scopes: list[str]) -> dict[str, str]:
    plaintext, _ = agent_tokens.issue_token("http-agent", scopes)
    return {"Authorization": f"Bearer {plaintext}",
            "Idempotency-Key": "http-batch-key-0123456789"}


class TestHttp:
    def test_requires_propose_scope(self, client):
        headers = _headers([agent_tokens.SCOPE_TRANSACTIONS_READ])
        r = client.post(PROPOSALS_PATH, headers=headers, json={
            "operation_type": "batch_import",
            "params": {"transactions": [BUY]}})
        assert r.status_code == 403

    def test_write_disabled_blocks(self, client, monkeypatch):
        monkeypatch.setattr(config, "AGENT_WRITE_ENABLED", False)
        headers = _headers([agent_tokens.SCOPE_TRANSACTIONS_PROPOSE])
        r = client.post(PROPOSALS_PATH, headers=headers, json={
            "operation_type": "batch_import",
            "params": {"transactions": [BUY]}})
        assert r.status_code == 403
        assert r.json()["detail"]["code"] == "write_disabled"

    def test_batch_invalid_item_shape(self, client):
        headers = _headers([agent_tokens.SCOPE_TRANSACTIONS_PROPOSE])
        r = client.post(PROPOSALS_PATH, headers=headers, json={
            "operation_type": "batch_import",
            "params": {"transactions": [BUY, {**BUY, "date": "bad"}]}})
        assert r.status_code == 422
        detail = r.json()["detail"]
        assert detail["code"] == "batch_invalid_item"
        assert detail["index"] == 1
        assert detail["issues"][0]["field"] == "date"

    def test_fund_not_registered_shape(self, client):
        headers = _headers([agent_tokens.SCOPE_TRANSACTIONS_PROPOSE])
        r = client.post(PROPOSALS_PATH, headers=headers, json={
            "operation_type": "batch_import",
            "params": {"transactions": [{**BUY, "fund_code": "999999"}]}})
        assert r.status_code == 409
        detail = r.json()["detail"]
        assert detail["code"] == "fund_not_registered"
        assert detail["index"] == 0
        assert detail["fund_code"] == "999999"
