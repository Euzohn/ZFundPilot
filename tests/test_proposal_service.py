"""账本提案服务测试：状态机、幂等、权限复核与事务执行。"""
from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

from zfundpilot import agent_tokens, config, db
from zfundpilot import proposal_service as svc
from zfundpilot.analysis import clear_analysis_cache
from zfundpilot.models import Fund

KEY_A = "proposal-key-aaaaaaaaaa"
KEY_B = "proposal-key-bbbbbbbbbbbb"

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
        db.init_db()
        db.upsert_fund(Fund("005827", "易方达蓝筹精选", "混合型", "消费"))
        clear_analysis_cache()
        yield
        clear_analysis_cache()


def _principal(scope: str = agent_tokens.SCOPE_TRANSACTIONS_PROPOSE,
               name: str = "test-agent") -> svc.Principal:
    _plain, info = agent_tokens.issue_token(name, [scope])
    return svc.Principal("agent_token", str(info["id"]),
                         f"agent:{info['token_prefix']}")


def _create(principal: svc.Principal, *, params: dict | None = None,
            key: str = KEY_A, operation: str = svc.OPERATION_ADD_TRANSACTION):
    return svc.create_proposal(
        principal, operation_type=operation,
        params=dict(params or BUY_PARAMS), idempotency_key=key)


def _audit_actions() -> list[str]:
    return [row["action"] for row in db.fetch_audit_logs(100)]


class TestCreate:
    def test_creates_pending_without_writing_ledger(self, temp_db):
        result = _create(_principal())

        assert result.http_status == 201
        assert result.code == "created"
        assert result.data["status"] == svc.STATUS_PENDING
        assert result.data["proposal_id"] > 0
        assert result.data["summary"]["fund_name"] == "易方达蓝筹精选"
        assert db.get_transactions_desc() == []
        assert "proposal_created" in _audit_actions()

    def test_replay_returns_same_proposal(self, temp_db):
        principal = _principal()
        first = _create(principal)
        second = _create(principal)

        assert second.replayed is True
        assert second.data["proposal_id"] == first.data["proposal_id"]

    def test_same_key_different_params_conflicts(self, temp_db):
        principal = _principal()
        _create(principal)
        result = _create(principal, params={**BUY_PARAMS, "amount": 2000.0})

        assert result.http_status == 409
        assert result.code == "idempotency_conflict"

    def test_rejects_unregistered_fund(self, temp_db):
        result = _create(_principal(), params={**BUY_PARAMS,
                                               "fund_code": "999999"})

        assert result.http_status == 409
        assert result.code == "fund_not_registered"
        assert db.get_transactions_desc() == []

    def test_rejects_unknown_operation(self, temp_db):
        with pytest.raises(svc.ProposalValidationError):
            _create(_principal(), operation="delete_transaction")

    @pytest.mark.parametrize("overrides", [
        {"fund_code": "abc"},
        {"date": "2026-13-01"},
        {"action": "transfer"},
        {"amount": -1},
        {"fee": -1},
        {"amount": None, "shares": None},
        {"unknown": 1},
    ])
    def test_rejects_invalid_params(self, temp_db, overrides):
        with pytest.raises(svc.ProposalValidationError):
            _create(_principal(), params={**BUY_PARAMS, **overrides})

    def test_limits_pending_per_owner(self, temp_db):
        principal = _principal()
        for i in range(svc.MAX_PENDING_PER_OWNER):
            _create(principal, key=f"proposal-key-{i:016d}")
        result = _create(principal, key="proposal-key-overflow")

        assert result.http_status == 409
        assert result.code == "too_many_pending"

    def test_owner_isolation_on_read(self, temp_db):
        owner = _principal()
        other = _principal(name="other")
        created = _create(owner)

        assert svc.get_proposal(owner,
                                created.data["proposal_id"]).http_status == 200
        hidden = svc.get_proposal(other, created.data["proposal_id"])
        assert hidden.http_status == 404


class TestApprove:
    def test_approve_writes_once_and_audits(self, temp_db):
        created = _create(_principal())
        pid = created.data["proposal_id"]

        result = svc.approve_proposal(pid, reviewer="admin")

        assert result.http_status == 200
        assert result.code == "succeeded"
        assert result.data["execution_result"]["tx_id"] > 0
        txs = db.get_transactions_desc()
        assert len(txs) == 1
        assert txs[0].fund_code == "005827"
        assert "proposal_approved" in _audit_actions()
        assert "add_transaction" in _audit_actions()

    def test_duplicate_approve_does_not_write_twice(self, temp_db):
        pid = _create(_principal()).data["proposal_id"]
        svc.approve_proposal(pid, reviewer="admin")
        result = svc.approve_proposal(pid, reviewer="admin")

        assert result.http_status == 409
        assert result.code == "not_pending"
        assert len(db.get_transactions_desc()) == 1

    def test_revoked_token_blocks_execution(self, temp_db):
        principal = _principal()
        pid = _create(principal).data["proposal_id"]
        db.revoke_agent_token(int(principal.id))

        result = svc.approve_proposal(pid, reviewer="admin")

        assert result.http_status == 409
        assert result.code == "token_revoked"
        assert db.get_transactions_desc() == []

    def test_write_switch_off_keeps_pending(self, temp_db, monkeypatch):
        pid = _create(_principal()).data["proposal_id"]
        monkeypatch.setattr(config, "AGENT_WRITE_ENABLED", False)

        result = svc.approve_proposal(pid, reviewer="admin")

        assert result.http_status == 403
        assert result.code == "write_disabled"
        assert svc.get_proposal_admin(pid).data["status"] == svc.STATUS_PENDING
        assert db.get_transactions_desc() == []

    def test_auth_disabled_blocks_execution(self, temp_db, monkeypatch):
        pid = _create(_principal()).data["proposal_id"]
        monkeypatch.setattr(config, "AUTH_ENABLED", False)

        result = svc.approve_proposal(pid, reviewer="admin")

        assert result.http_status == 403
        assert result.code == "auth_disabled"
        assert db.get_transactions_desc() == []

    def test_expired_proposal_cannot_approve(self, temp_db):
        pid = _create(_principal()).data["proposal_id"]
        with db.get_connection(write=True) as conn:
            conn.execute(
                "UPDATE operation_proposals SET expires_at='2000-01-01T00:00:00' "
                "WHERE id=?", (pid,))

        result = svc.approve_proposal(pid, reviewer="admin")

        assert result.http_status == 409
        assert result.code == "expired"
        assert db.get_transactions_desc() == []

    def test_sell_proposal_requires_shares(self, temp_db):
        params = {"fund_code": "005827", "action": "sell",
                  "date": "2026-01-02", "amount": 500.0}
        with pytest.raises(svc.ProposalValidationError):
            _create(_principal(), params=params)


class TestCancelReject:
    def test_cancel_own_pending(self, temp_db):
        principal = _principal()
        pid = _create(principal).data["proposal_id"]
        result = svc.cancel_proposal(principal, pid)

        assert result.http_status == 200
        assert result.data["status"] == svc.STATUS_CANCELLED
        assert db.get_transactions_desc() == []
        assert "proposal_cancelled" in _audit_actions()

    def test_cancel_other_token_is_404(self, temp_db):
        pid = _create(_principal()).data["proposal_id"]
        result = svc.cancel_proposal(_principal(name="other"), pid)

        assert result.http_status == 404

    def test_reject_records_reason(self, temp_db):
        pid = _create(_principal()).data["proposal_id"]
        result = svc.reject_proposal(pid, reviewer="admin", reason="金额不对")

        assert result.http_status == 200
        assert result.data["status"] == svc.STATUS_REJECTED
        assert result.data["rejection_reason"] == "金额不对"
        assert db.get_transactions_desc() == []

    def test_reject_twice_conflicts(self, temp_db):
        pid = _create(_principal()).data["proposal_id"]
        svc.reject_proposal(pid, reviewer="admin")
        result = svc.reject_proposal(pid, reviewer="admin")

        assert result.http_status == 409
        assert result.code == "not_pending"


class TestListAndCount:
    def test_pending_count(self, temp_db):
        _create(_principal())
        assert svc.count_pending() == 1

    def test_admin_list_filters(self, temp_db):
        pid = _create(_principal()).data["proposal_id"]
        svc.reject_proposal(pid, reviewer="admin")

        pending = svc.list_proposals(status=svc.STATUS_PENDING)
        rejected = svc.list_proposals(status=svc.STATUS_REJECTED)

        assert pending.data["total"] == 0
        assert rejected.data["total"] == 1
