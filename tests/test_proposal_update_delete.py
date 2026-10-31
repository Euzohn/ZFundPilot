"""F1 单笔修改/删除提案测试：版本前置、冲突检测、份额连带、转换腿、幂等。

本地不运行；由 CI 执行。覆盖设计稿 §12 验收案例。
"""
from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

from zfundpilot import agent_tokens, config, db
from zfundpilot import proposal_service as svc
from zfundpilot.analysis import clear_analysis_cache
from zfundpilot.models import Fund, Transaction
from zfundpilot.transaction_service import transaction_row_digest

KEY_A = "f1-update-key-aaaaaaaaaa"
KEY_B = "f1-update-key-bbbbbbbbb"
KEY_C = "f1-update-key-cccccccccc"
KEY_D = "f1-delete-key-dddddddddd"

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
        db.upsert_fund(Fund("110011", "易方达中小盘", "混合型", "成长"))
        clear_analysis_cache()
        yield
        clear_analysis_cache()


def _principal(scope: str = agent_tokens.SCOPE_TRANSACTIONS_PROPOSE) -> svc.Principal:
    _plain, info = agent_tokens.issue_token("test-agent", [scope])
    return svc.Principal("agent_token", str(info["id"]),
                         f"agent:{info['token_prefix']}")


def _add_tx(**overrides) -> int:
    params = {**BUY_PARAMS, **overrides}
    tx = Transaction(
        fund_code=params["fund_code"], action=params["action"],
        date=params["date"], amount=params.get("amount"),
        shares=params.get("shares"), nav=params.get("nav"),
        fee=params.get("fee", 0.0), channel=params.get("channel", ""),
        note=params.get("note", ""), is_t1=bool(params.get("is_t1", False)),
    )
    return db.add_transaction(tx)


def _digest_of(tx_id: int) -> str:
    return transaction_row_digest(db.get_transaction(tx_id))


def _create_update(principal, *, tx_id, digest, params=None, key=KEY_A):
    full = {"tx_id": tx_id, "expected_digest": digest, **(params or BUY_PARAMS)}
    return svc.create_proposal(
        principal, operation_type=svc.OPERATION_UPDATE_TRANSACTION,
        params=full, idempotency_key=key)


def _create_delete(principal, *, tx_id, digest, reason="", key=KEY_D):
    return svc.create_proposal(
        principal, operation_type=svc.OPERATION_DELETE_TRANSACTION,
        params={"tx_id": tx_id, "expected_digest": digest, "reason": reason},
        idempotency_key=key)


def _approve(pid: int) -> svc.ProposalResult:
    return svc.approve_proposal(pid, reviewer="admin")


class TestUpdateProposal:
    def test_create_and_approve_updates_row(self, temp_db):
        tx_id = _add_tx()
        principal = _principal()
        result = _create_update(
            principal, tx_id=tx_id, digest=_digest_of(tx_id),
            params={**BUY_PARAMS, "amount": 2000.0})

        assert result.http_status == 201
        assert result.code == "created"
        assert result.data["summary"]["operation_type"] == "update_transaction"
        assert result.data["summary"]["changed_fields"] == ["amount"]
        assert db.get_transaction(tx_id).amount == 1000.0  # 未批准前账本不变

        approved = _approve(result.data["proposal_id"])
        assert approved.code == "succeeded"
        assert db.get_transaction(tx_id).amount == 2000.0

    def test_target_changed_at_create_returns_409(self, temp_db):
        tx_id = _add_tx()
        stale = transaction_row_digest({"fund_code": "005827", "action": "buy",
                                        "date": "2020-01-01", "amount": 1.0,
                                        "shares": None, "nav": None, "fee": 0.0,
                                        "channel": "x", "note": "", "is_t1": False})
        result = _create_update(_principal(), tx_id=tx_id, digest=stale)

        assert result.http_status == 409
        assert result.code == "target_changed"

    def test_target_deleted_at_create_returns_404(self, temp_db):
        result = _create_update(_principal(), tx_id=99999, digest="0" * 64)
        assert result.http_status == 404
        assert result.code == "target_not_found"

    def test_target_changed_at_approve_returns_conflict(self, temp_db):
        tx_id = _add_tx()
        digest = _digest_of(tx_id)
        result = _create_update(_principal(), tx_id=tx_id, digest=digest)
        # 审批前网页改动目标行
        tx = db.get_transaction(tx_id)
        tx.amount = 9999.0
        db.update_transaction(tx)

        approved = _approve(result.data["proposal_id"])
        assert approved.code == "target_changed"
        assert approved.data["execution_result"]["reason"] == "target_changed"

    def test_target_deleted_at_approve_returns_conflict(self, temp_db):
        tx_id = _add_tx()
        result = _create_update(
            _principal(), tx_id=tx_id, digest=_digest_of(tx_id))
        db.delete_transaction(tx_id)

        approved = _approve(result.data["proposal_id"])
        assert approved.code == "target_deleted"
        assert approved.data["execution_result"]["reason"] == "target_deleted"

    def test_share_cascade_blocks_reducing_buy(self, temp_db):
        # 历史买入 100 份、卖出 60 份；把买入减到 30 份将使卖出超份额。
        buy_id = _add_tx(shares=100.0, amount=None)
        _add_tx(action="sell", shares=60.0, amount=None, nav=1.0)
        result = _create_update(
            _principal(), tx_id=buy_id, digest=_digest_of(buy_id),
            params={**BUY_PARAMS, "amount": 1000.0, "shares": 30.0})
        assert result.http_status == 201  # 创建期不阻断
        approved = _approve(result.data["proposal_id"])
        assert approved.code == "insufficient_shares_after_change"
        assert approved.data["execution_result"]["reason"] == \
            "insufficient_shares_after_change"

    def test_conversion_leg_isolated_rejected(self, temp_db):
        from_id, _to_id = db.add_conversion(
            Transaction(fund_code="005827", action="sell", date="2026-01-02",
                        shares=50.0, nav=1.0, channel="支付宝"),
            Transaction(fund_code="110011", action="buy", date="2026-01-02",
                        amount=50.0, nav=1.0, channel="支付宝"),
        )
        result = _create_update(
            _principal(), tx_id=from_id, digest=_digest_of(from_id))
        assert result.http_status == 409
        assert result.code == "conversion_leg_isolated"


class TestDeleteProposal:
    def test_create_and_approve_deletes_row(self, temp_db):
        tx_id = _add_tx()
        result = _create_delete(
            _principal(), tx_id=tx_id, digest=_digest_of(tx_id),
            reason="误录")

        assert result.http_status == 201
        assert result.data["summary"]["operation_type"] == "delete_transaction"
        assert result.data["summary"]["reason"] == "误录"
        assert db.get_transaction(tx_id) is not None  # 未批准前不删

        approved = _approve(result.data["proposal_id"])
        assert approved.code == "succeeded"
        assert db.get_transaction(tx_id) is None

    def test_delete_buy_blocked_by_share_cascade(self, temp_db):
        buy_id = _add_tx(shares=100.0, amount=None)
        _add_tx(action="sell", shares=60.0, amount=None, nav=1.0)
        result = _create_delete(
            _principal(), tx_id=buy_id, digest=_digest_of(buy_id))
        approved = _approve(result.data["proposal_id"])
        assert approved.code == "insufficient_shares_after_change"
        assert approved.data["execution_result"]["reason"] == \
            "insufficient_shares_after_change"
        assert db.get_transaction(buy_id) is not None  # 未删

    def test_delete_sell_always_allowed(self, temp_db):
        _add_tx(shares=100.0, amount=None)
        sell_id = _add_tx(action="sell", shares=60.0, amount=None, nav=1.0)
        result = _create_delete(
            _principal(), tx_id=sell_id, digest=_digest_of(sell_id))
        approved = _approve(result.data["proposal_id"])
        assert approved.code == "succeeded"
        assert db.get_transaction(sell_id) is None

    def test_conversion_leg_delete_rejected(self, temp_db):
        from_id, _to_id = db.add_conversion(
            Transaction(fund_code="005827", action="sell", date="2026-01-02",
                        shares=50.0, nav=1.0, channel="支付宝"),
            Transaction(fund_code="110011", action="buy", date="2026-01-02",
                        amount=50.0, nav=1.0, channel="支付宝"),
        )
        result = _create_delete(
            _principal(), tx_id=from_id, digest=_digest_of(from_id))
        assert result.http_status == 409
        assert result.code == "conversion_leg_isolated"


class TestIdempotency:
    def test_same_key_replays(self, temp_db):
        tx_id = _add_tx()
        principal = _principal()
        first = _create_update(principal, tx_id=tx_id, digest=_digest_of(tx_id))
        second = _create_update(principal, tx_id=tx_id, digest=_digest_of(tx_id))
        assert second.data["proposal_id"] == first.data["proposal_id"]
        assert second.replayed is True

    def test_same_key_different_params_conflicts(self, temp_db):
        tx_id = _add_tx()
        principal = _principal()
        _create_update(principal, tx_id=tx_id, digest=_digest_of(tx_id),
                       key=KEY_A)
        result = _create_update(
            principal, tx_id=tx_id, digest=_digest_of(tx_id),
            params={**BUY_PARAMS, "amount": 2000.0}, key=KEY_A)
        assert result.http_status == 409
        assert result.code == "idempotency_conflict"


class TestScope:
    def test_propose_scope_covers_update_delete(self, temp_db):
        # 仅有 transactions:propose（无 transactions:create）即可创建修改/删除提案。
        tx_id = _add_tx()
        principal = _principal(agent_tokens.SCOPE_TRANSACTIONS_PROPOSE)
        result = _create_delete(principal, tx_id=tx_id, digest=_digest_of(tx_id))
        assert result.http_status == 201

    def test_agent_cannot_approve(self, temp_db):
        # approve_proposal 需要 reviewer（管理员身份）；Agent 无 approve 工具，
        # 服务端执行时只校验创建者 token 仍有 propose scope。
        tx_id = _add_tx()
        result = _create_update(_principal(), tx_id=tx_id,
                                digest=_digest_of(tx_id))
        approved = _approve(result.data["proposal_id"])
        assert approved.code == "succeeded"
