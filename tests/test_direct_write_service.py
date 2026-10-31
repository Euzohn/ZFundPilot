"""可信单笔直记服务测试：权限、预检、降级、幂等与额度。"""
from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

from zfundpilot import agent_tokens, config, db
from zfundpilot import proposal_service as proposals
from zfundpilot import transaction_service as svc
from zfundpilot.analysis import clear_analysis_cache
from zfundpilot.models import Fund, Transaction

KEY_A = "direct-key-aaaaaaaaaa"
KEY_B = "direct-key-bbbbbbbbbbbb"
KEY_C = "direct-key-cccccccccccc"

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
        monkeypatch.setattr(config, "AUTH_ENABLED", True)
        monkeypatch.setattr(config, "AUTH_USERNAME", "admin")
        monkeypatch.setattr(config, "AGENT_WRITE_ENABLED", True)
        monkeypatch.setattr(config, "AGENT_TX_MAX_AMOUNT", 500_000.0)
        monkeypatch.setattr(config, "AGENT_TX_DAILY_COUNT", 10)
        monkeypatch.setattr(config, "AGENT_TX_DAILY_AMOUNT", 1_000_000.0)
        db.init_db()
        db.upsert_fund(Fund("005827", "易方达蓝筹精选", "混合型", "消费"))
        clear_analysis_cache()
        yield
        clear_analysis_cache()


def _principal(*scopes: str, name: str = "test-agent") -> proposals.Principal:
    _plain, info = agent_tokens.issue_token(name, list(scopes))
    return proposals.Principal(
        "agent_token", str(info["id"]), f"agent:{info['token_prefix']}")


def _record(principal: proposals.Principal, *, params: dict | None = None,
            key: str = KEY_A) -> svc.DirectWriteResult:
    return svc.record_transaction_direct(
        principal, params=dict(params or BUY_PARAMS), idempotency_key=key)


def _actions() -> list[str]:
    return [row["action"] for row in db.fetch_audit_logs(200)]


def _operation_count() -> int:
    with db.get_connection() as conn:
        return int(conn.execute(
            "SELECT COUNT(*) FROM agent_operations "
            "WHERE operation='record_transaction'").fetchone()[0])


class TestDirectBasics:
    def test_records_once_with_source_and_audits(self, temp_db):
        result = _record(_principal(agent_tokens.SCOPE_TRANSACTIONS_CREATE))

        assert result.http_status == 201
        assert result.code == "recorded"
        assert result.data["execution_mode"] == "direct"
        assert result.data["transaction_id"] > 0
        assert result.data["operation_id"] > 0
        assert result.data["proposal_id"] is None
        assert result.data["verify_path"] == "/transactions"
        assert result.data["receipt"]["fund_name"] == "易方达蓝筹精选"
        assert result.data["receipt"]["unconfirmed_fields"] == ["nav", "shares"]
        tx = db.get_transaction(result.data["transaction_id"])
        assert tx is not None and tx.source == "agent"
        assert tx.amount == 1000.0
        assert len(db.get_transactions_desc()) == 1
        assert _operation_count() == 1
        actions = _actions()
        assert "add_transaction" in actions
        assert "agent_direct_add" in actions

    def test_requires_create_scope(self, temp_db):
        result = _record(_principal(agent_tokens.SCOPE_TRANSACTIONS_PROPOSE))

        assert result.http_status == 403
        assert result.code == "scope_revoked"
        assert db.get_transactions_desc() == []

    def test_db_write_switch_off_blocks_even_if_runtime_on(self, temp_db):
        db.upsert_preference(config.AGENT_WRITE_PREF_KEY, "false")

        result = _record(_principal(agent_tokens.SCOPE_TRANSACTIONS_CREATE))

        assert result.http_status == 403
        assert result.code == "write_disabled"
        assert db.get_transactions_desc() == []

    def test_rejects_unregistered_fund(self, temp_db):
        result = _record(
            _principal(agent_tokens.SCOPE_TRANSACTIONS_CREATE),
            params={**BUY_PARAMS, "fund_code": "999999"})

        assert result.http_status == 409
        assert result.code == "fund_not_registered"
        assert "agent_direct_rejected" in _actions()
        assert db.get_transactions_desc() == []

    def test_rejects_future_date(self, temp_db):
        with pytest.raises(svc.FutureDateError):
            _record(
                _principal(agent_tokens.SCOPE_TRANSACTIONS_CREATE),
                params={**BUY_PARAMS, "date": "2999-01-01"})
        assert db.get_transactions_desc() == []
        assert _operation_count() == 0

    def test_rejects_non_direct_action(self, temp_db):
        with pytest.raises(svc.TransactionValidationError):
            _record(
                _principal(agent_tokens.SCOPE_TRANSACTIONS_CREATE),
                params={**BUY_PARAMS, "action": "dividend",
                        "shares": None, "amount": 10.0})
        assert db.get_transactions_desc() == []


class TestIdempotency:
    def test_same_key_replays_without_second_write(self, temp_db):
        principal = _principal(agent_tokens.SCOPE_TRANSACTIONS_CREATE)
        first = _record(principal)
        second = _record(principal)

        assert second.http_status == 200
        assert second.code == "replayed"
        assert second.replayed is True
        assert second.data["transaction_id"] == first.data["transaction_id"]
        assert second.data["operation_id"] == first.data["operation_id"]
        assert len(db.get_transactions_desc()) == 1
        assert _operation_count() == 1

    def test_same_key_different_params_conflicts(self, temp_db):
        principal = _principal(agent_tokens.SCOPE_TRANSACTIONS_CREATE)
        _record(principal)
        result = _record(principal, params={**BUY_PARAMS, "amount": 2000.0})

        assert result.http_status == 409
        assert result.code == "idempotency_conflict"

    def test_rejection_does_not_consume_key(self, temp_db):
        principal = _principal(agent_tokens.SCOPE_TRANSACTIONS_CREATE)
        with pytest.raises(svc.FutureDateError):
            _record(principal, params={**BUY_PARAMS, "date": "2999-01-01"})

        result = _record(principal)

        assert result.http_status == 201
        assert len(db.get_transactions_desc()) == 1

    def test_downgrade_replay_returns_live_proposal_and_never_upgrades(
            self, temp_db, monkeypatch):
        principal = _principal(
            agent_tokens.SCOPE_TRANSACTIONS_CREATE,
            agent_tokens.SCOPE_TRANSACTIONS_PROPOSE)
        monkeypatch.setattr(config, "AGENT_TX_MAX_AMOUNT", 500.0)

        first = _record(principal)
        assert first.code == "downgraded"
        assert first.http_status == 201
        assert first.data["execution_mode"] == "proposal"
        assert db.get_transactions_desc() == []

        # 诱因消除后重放同一键仍返回提案，不得升级为直写。
        monkeypatch.setattr(config, "AGENT_TX_MAX_AMOUNT", 500_000.0)
        second = _record(principal)
        assert second.http_status == 200
        assert second.replayed is True
        assert second.data["execution_mode"] == "proposal"
        assert second.data["proposal_id"] == first.data["proposal_id"]
        assert db.get_transactions_desc() == []

        approved = proposals.approve_proposal(
            first.data["proposal_id"], reviewer="admin")
        assert approved.code == "succeeded"
        third = _record(principal)
        assert third.data["execution_mode"] == "proposal"
        assert third.data["receipt"]["status"] == "succeeded"
        assert third.data["receipt"]["execution_result"]["tx_id"]
        assert len(db.get_transactions_desc()) == 1


class TestPrechecks:
    def test_duplicate_without_propose_is_409(self, temp_db):
        principal = _principal(agent_tokens.SCOPE_TRANSACTIONS_CREATE)
        first = _record(principal)
        result = _record(principal, key=KEY_B)

        assert result.http_status == 409
        assert result.code == "duplicate_candidate"
        assert result.data["tx_id"] == first.data["transaction_id"]
        assert len(db.get_transactions_desc()) == 1

    def test_duplicate_with_propose_downgrades(self, temp_db):
        principal = _principal(
            agent_tokens.SCOPE_TRANSACTIONS_CREATE,
            agent_tokens.SCOPE_TRANSACTIONS_PROPOSE)
        _record(principal)
        result = _record(principal, key=KEY_B)

        assert result.http_status == 201
        assert result.code == "downgraded"
        assert result.data["execution_mode"] == "proposal"
        assert any("疑似" in w for w in
                   result.data["receipt"]["summary"]["warnings"])
        assert len(db.get_transactions_desc()) == 1
        assert "agent_direct_downgraded" in _actions()

    def test_same_day_different_amount_is_allowed(self, temp_db):
        principal = _principal(agent_tokens.SCOPE_TRANSACTIONS_CREATE)
        _record(principal)
        result = _record(
            principal, key=KEY_B, params={**BUY_PARAMS, "amount": 2000.0})

        assert result.http_status == 201
        assert len(db.get_transactions_desc()) == 2

    def test_duplicate_matches_pending_proposal(self, temp_db):
        proposer = _principal(
            agent_tokens.SCOPE_TRANSACTIONS_PROPOSE, name="proposer")
        proposals.create_proposal(
            proposer, operation_type="add_transaction",
            params=dict(BUY_PARAMS), idempotency_key=KEY_C)
        direct = _principal(agent_tokens.SCOPE_TRANSACTIONS_CREATE)

        result = _record(direct)

        assert result.http_status == 409
        assert result.code == "duplicate_candidate"
        assert result.data["proposal_id"] > 0

    def test_insufficient_shares_without_propose_is_409(self, temp_db):
        db.add_transaction(Transaction(
            fund_code="005827", action="buy", date="2026-01-01",
            shares=100.0, nav=1.0, channel="支付宝"))
        principal = _principal(agent_tokens.SCOPE_TRANSACTIONS_CREATE)
        result = _record(principal, params={
            **BUY_PARAMS, "action": "sell", "amount": None,
            "shares": 150.0, "nav": None})

        assert result.http_status == 409
        assert result.code == "insufficient_shares"
        assert result.data["available"] == 100.0
        assert len(db.get_transactions_desc()) == 1

    def test_insufficient_shares_with_propose_downgrades(self, temp_db):
        db.add_transaction(Transaction(
            fund_code="005827", action="buy", date="2026-01-01",
            shares=100.0, nav=1.0, channel="支付宝"))
        principal = _principal(
            agent_tokens.SCOPE_TRANSACTIONS_CREATE,
            agent_tokens.SCOPE_TRANSACTIONS_PROPOSE)
        result = _record(principal, params={
            **BUY_PARAMS, "action": "sell", "amount": None,
            "shares": 150.0, "nav": None})

        assert result.http_status == 201
        assert result.code == "downgraded"
        assert result.data["execution_mode"] == "proposal"

    def test_available_subtracts_reinvest_and_other_pending_sells(
            self, temp_db):
        db.add_transaction(Transaction(
            fund_code="005827", action="buy", date="2026-01-01",
            shares=100.0, nav=1.0, channel="支付宝"))
        db.add_transaction(Transaction(
            fund_code="005827", action="reinvest", date="2026-01-02",
            shares=50.0, nav=1.0, channel="支付宝"))
        other = _principal(
            agent_tokens.SCOPE_TRANSACTIONS_PROPOSE, name="other")
        proposals.create_proposal(
            other, operation_type="add_transaction",
            params={"fund_code": "005827", "action": "sell",
                    "date": "2026-01-03", "shares": 30.0,
                    "channel": "支付宝"},
            idempotency_key=KEY_C)
        principal = _principal(agent_tokens.SCOPE_TRANSACTIONS_CREATE)

        result = _record(principal, params={
            **BUY_PARAMS, "action": "sell", "amount": None,
            "shares": 130.0, "nav": None})

        assert result.http_status == 409
        assert result.code == "insufficient_shares"
        assert result.data["available"] == 120.0

    def test_amount_cap_without_propose_is_409(self, temp_db, monkeypatch):
        monkeypatch.setattr(config, "AGENT_TX_MAX_AMOUNT", 500.0)
        principal = _principal(agent_tokens.SCOPE_TRANSACTIONS_CREATE)
        result = _record(principal)

        assert result.http_status == 409
        assert result.code == "amount_exceeds_cap"
        assert result.data["cap"] == 500.0
        assert db.get_transactions_desc() == []

    def test_daily_count_quota_includes_downgrades(self, temp_db, monkeypatch):
        monkeypatch.setattr(config, "AGENT_TX_DAILY_COUNT", 1)
        monkeypatch.setattr(config, "AGENT_TX_MAX_AMOUNT", 500.0)
        principal = _principal(
            agent_tokens.SCOPE_TRANSACTIONS_CREATE,
            agent_tokens.SCOPE_TRANSACTIONS_PROPOSE)
        first = _record(principal)
        assert first.code == "downgraded"
        second = _record(principal, key=KEY_B)

        assert second.http_status == 429
        assert second.code == "daily_quota_exceeded"
        assert second.data["used"] == 1
        assert second.data["limit"] == 1

    def test_daily_amount_quota_only_counts_direct_writes(
            self, temp_db, monkeypatch):
        monkeypatch.setattr(config, "AGENT_TX_DAILY_AMOUNT", 1500.0)
        principal = _principal(agent_tokens.SCOPE_TRANSACTIONS_CREATE)
        first = _record(principal)
        assert first.data["daily_quota"]["amount_used"] == 1000.0
        second = _record(
            principal, key=KEY_B, params={**BUY_PARAMS, "amount": 600.0})

        assert second.http_status == 429
        assert second.code == "daily_quota_exceeded"
        assert second.data["used"] == 1000.0
        assert second.data["limit"] == 1500.0

    def test_downgrade_reuses_existing_pending_with_new_key(self, temp_db):
        principal = _principal(
            agent_tokens.SCOPE_TRANSACTIONS_CREATE,
            agent_tokens.SCOPE_TRANSACTIONS_PROPOSE)
        created = proposals.create_proposal(
            principal, operation_type="add_transaction",
            params=dict(BUY_PARAMS), idempotency_key=KEY_C)
        # 同主体已有同参 pending 提案；直记命中重复候选时应复用而非新建。
        db.add_transaction(Transaction(
            fund_code="005827", action="buy", date="2026-01-02",
            amount=1000.0, fee=1.0, channel="支付宝"))
        result = _record(principal, key=KEY_B)

        assert result.code == "downgraded"
        assert result.data["execution_mode"] == "proposal"
        assert result.data["proposal_id"] == created.data["proposal_id"]
        assert result.replayed is True
        assert result.http_status == 200

    def test_t1_receipt_lists_unconfirmed_fields(self, temp_db):
        result = _record(
            _principal(agent_tokens.SCOPE_TRANSACTIONS_CREATE),
            params={**BUY_PARAMS, "is_t1": True})

        assert result.data["receipt"]["unconfirmed_fields"] == ["nav", "shares"]
        assert any("T+1" in w for w in result.data["receipt"]["warnings"])

    def test_proposal_approval_does_not_set_agent_source(self, temp_db):
        principal = _principal(agent_tokens.SCOPE_TRANSACTIONS_PROPOSE)
        created = proposals.create_proposal(
            principal, operation_type="add_transaction",
            params=dict(BUY_PARAMS), idempotency_key=KEY_C)
        proposals.approve_proposal(created.data["proposal_id"], reviewer="admin")

        tx = db.get_transactions_desc()[0]
        assert tx.source == ""
