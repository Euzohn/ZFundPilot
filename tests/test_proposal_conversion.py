"""F2 基金转换/整对删除/分红提醒关联提案测试。

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

KEY_ADD = "f2-add-conversion-key-aaaa"
KEY_DEL = "f2-del-conversion-key-bbbb"
KEY_DIV = "f2-dividend-alert-key-cccc"

CONVERSION_PARAMS = {
    "from_code": "005827",
    "to_code": "110011",
    "date": "2026-01-02",
    "from_shares": 50.0,
    "from_nav": 1.2,
    "from_fee": 0.5,
    "to_nav": 1.0,
    "channel": "支付宝",
}

DIVIDEND_PARAMS = {
    "fund_code": "005827",
    "action": "dividend",
    "date": "2026-01-10",
    "amount": 100.0,
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
    params = {
        "fund_code": "005827", "action": "buy", "date": "2026-01-02",
        "amount": 1000.0, "fee": 1.0, "channel": "支付宝",
        **overrides,
    }
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


def _make_pair() -> tuple[int, int, str]:
    """直接写入一对标准转换腿，返回 (from_id, to_id, conversion_id)。"""
    from_id, to_id = db.add_conversion(
        Transaction(fund_code="005827", action="sell", date="2026-01-02",
                    shares=50.0, nav=1.0, channel="支付宝"),
        Transaction(fund_code="110011", action="buy", date="2026-01-02",
                    amount=50.0, nav=1.0, channel="支付宝"),
    )
    return from_id, to_id, db.get_transaction(from_id).conversion_id


def _create_conversion(principal, *, params=None, key=KEY_ADD):
    return svc.create_proposal(
        principal, operation_type=svc.OPERATION_ADD_CONVERSION,
        params=params or dict(CONVERSION_PARAMS),
        idempotency_key=key)


def _delete_params(from_id: int, to_id: int, cid: str) -> dict:
    return {
        "conversion_id": cid,
        "expected_from_digest": _digest_of(from_id),
        "expected_to_digest": _digest_of(to_id),
        "reason": "误录",
    }


def _create_delete_conversion(principal, *, params, key=KEY_DEL):
    return svc.create_proposal(
        principal, operation_type=svc.OPERATION_DELETE_CONVERSION,
        params=params, idempotency_key=key)


def _create_dividend(principal, *, alert_id, key=KEY_DIV):
    return svc.create_proposal(
        principal, operation_type=svc.OPERATION_ADD_TRANSACTION,
        params={**DIVIDEND_PARAMS, "dividend_alert_id": alert_id},
        idempotency_key=key)


def _approve(pid: int) -> svc.ProposalResult:
    return svc.approve_proposal(pid, reviewer="admin")


def _alert_of(alert_id: int) -> dict:
    return next(a for a in db.get_dividend_alerts() if a["id"] == alert_id)


class TestAddConversion:
    def test_create_and_approve_writes_linked_legs(self, temp_db):
        principal = _principal()
        result = _create_conversion(principal)

        assert result.http_status == 201
        summary = result.data["summary"]
        assert summary["operation_type"] == "add_conversion"
        assert summary["conversion"]["from"]["fund_code"] == "005827"
        assert summary["conversion"]["to"]["fund_code"] == "110011"
        # 非 T+1 未填 to_amount：摘要应展示由卖出腿推导出的转入金额/份额。
        assert summary["conversion"]["to"]["amount"] == pytest.approx(59.5)
        assert summary["conversion"]["to"]["shares"] == pytest.approx(59.5)
        assert db.get_transactions() == []  # 未批准前不写账本

        approved = _approve(result.data["proposal_id"])
        assert approved.code == "succeeded"
        execution = approved.data["execution_result"]
        assert execution["ok"] is True

        from_tx = db.get_transaction(execution["from_id"])
        to_tx = db.get_transaction(execution["to_id"])
        assert from_tx.action == "sell"
        assert to_tx.action == "buy"
        assert from_tx.fund_code == "005827"
        assert to_tx.fund_code == "110011"
        assert from_tx.shares == pytest.approx(50.0)
        assert to_tx.conversion_id == from_tx.conversion_id
        assert from_tx.conversion_id  # 双腿共享同一非空 conversion_id

    def test_same_fund_rejected(self, temp_db):
        params = {**CONVERSION_PARAMS, "to_code": "005827"}
        with pytest.raises(svc.ProposalValidationError) as exc:
            _create_conversion(_principal(), params=params)
        assert exc.value.field == "from_code"

    @pytest.mark.parametrize("field,code", [
        ("from_code", "999998"),
        ("to_code", "999999"),
    ])
    def test_unregistered_fund_rejected(self, temp_db, field, code):
        params = {**CONVERSION_PARAMS, field: code}
        result = _create_conversion(_principal(), params=params)

        assert result.http_status == 409
        assert result.code == "fund_not_registered"
        assert result.data["fund_code"] == code
        assert db.get_transactions() == []

    def test_non_t1_requires_to_leg(self, temp_db):
        # from_nav 与 to_amount/to_nav 均空：非 T+1 无法推导转入腿。
        params = {**CONVERSION_PARAMS, "from_nav": None,
                  "to_amount": None, "to_nav": None}
        with pytest.raises(svc.ProposalValidationError) as exc:
            _create_conversion(_principal(), params=params)
        assert exc.value.field == "to_amount"

    def test_t1_allows_deferred_to_leg(self, temp_db):
        params = {**CONVERSION_PARAMS, "is_t1": True}
        result = _create_conversion(_principal(), params=params)
        assert result.http_status == 201

        approved = _approve(result.data["proposal_id"])
        assert approved.code == "succeeded"
        execution = approved.data["execution_result"]
        to_tx = db.get_transaction(execution["to_id"])
        assert to_tx.action == "buy"
        assert to_tx.amount is None
        assert to_tx.shares is None

    def test_share_shortfall_is_warning_not_block(self, temp_db):
        # 该渠道仅持有 10 份，却转出 50 份：创建成功（warning），审批不阻断。
        _add_tx(fund_code="005827", shares=10.0, amount=None, nav=1.0)
        result = _create_conversion(_principal())

        assert result.http_status == 201
        assert any("可用份额" in w for w in result.data["summary"]["warnings"])

        approved = _approve(result.data["proposal_id"])
        assert approved.code == "succeeded"
        execution = approved.data["execution_result"]
        assert execution["ok"] is True
        assert any("可用份额" in w for w in execution["warnings"])
        assert db.get_transaction(execution["from_id"]) is not None


class TestDeleteConversion:
    def test_create_and_approve_deletes_pair(self, temp_db):
        from_id, to_id, cid = _make_pair()
        result = _create_delete_conversion(
            _principal(), params=_delete_params(from_id, to_id, cid))

        assert result.http_status == 201
        summary = result.data["summary"]
        assert summary["operation_type"] == "delete_conversion"
        assert summary["conversion_id"] == cid
        assert summary["conversion"]["from"]["fund_code"] == "005827"
        assert summary["conversion"]["to"]["fund_code"] == "110011"
        assert summary["reason"] == "误录"
        assert db.get_transaction(from_id) is not None  # 未批准前不删

        approved = _approve(result.data["proposal_id"])
        assert approved.code == "succeeded"
        assert db.get_transaction(from_id) is None
        assert db.get_transaction(to_id) is None

    def test_from_digest_mismatch(self, temp_db):
        from_id, to_id, cid = _make_pair()
        params = _delete_params(from_id, to_id, cid)
        params["expected_from_digest"] = "0" * 64
        result = _create_delete_conversion(_principal(), params=params)

        assert result.http_status == 409
        assert result.code == "target_changed"
        assert result.data["leg"] == "from"

    def test_to_digest_mismatch(self, temp_db):
        from_id, to_id, cid = _make_pair()
        params = _delete_params(from_id, to_id, cid)
        params["expected_to_digest"] = "0" * 64
        result = _create_delete_conversion(_principal(), params=params)

        assert result.http_status == 409
        assert result.code == "target_changed"
        assert result.data["leg"] == "to"

    def test_conversion_not_found(self, temp_db):
        params = {
            "conversion_id": "00000000-0000-0000-0000-000000000000",
            "expected_from_digest": "0" * 64,
            "expected_to_digest": "0" * 64,
        }
        result = _create_delete_conversion(_principal(), params=params)
        assert result.http_status == 404
        assert result.code == "conversion_not_found"

    def test_non_standard_pair_rejected(self, temp_db):
        # 两条流水共享 conversion_id，但都不是卖出腿：非标准转换对。
        from_id, to_id = db.add_conversion(
            Transaction(fund_code="005827", action="buy", date="2026-01-02",
                        amount=50.0, nav=1.0, channel="支付宝"),
            Transaction(fund_code="110011", action="buy", date="2026-01-02",
                        amount=50.0, nav=1.0, channel="支付宝"),
        )
        cid = db.get_transaction(from_id).conversion_id
        params = _delete_params(from_id, to_id, cid)
        result = _create_delete_conversion(_principal(), params=params)

        assert result.http_status == 409
        assert result.code == "conversion_leg_mismatch"

    def test_buy_leg_oversell_blocks(self, temp_db):
        from_id, to_id, cid = _make_pair()  # 转入基金 110011 买入 50 份
        _add_tx(fund_code="110011", action="sell", shares=30.0,
                amount=None, nav=1.0)
        result = _create_delete_conversion(
            _principal(), params=_delete_params(from_id, to_id, cid))
        assert result.http_status == 201

        approved = _approve(result.data["proposal_id"])
        assert approved.code == "insufficient_shares_after_change"
        assert approved.data["execution_result"]["reason"] == \
            "insufficient_shares_after_change"
        assert db.get_transaction(from_id) is not None
        assert db.get_transaction(to_id) is not None

    def test_sell_leg_removal_always_allowed(self, temp_db):
        # 转出基金另有超卖卖出流水；删除转换对只释放卖出腿，不应被份额连带阻断。
        from_id, to_id, cid = _make_pair()
        _add_tx(fund_code="005827", action="sell", shares=100.0,
                amount=None, nav=1.0)
        result = _create_delete_conversion(
            _principal(), params=_delete_params(from_id, to_id, cid))

        approved = _approve(result.data["proposal_id"])
        assert approved.code == "succeeded"
        assert db.get_transaction(from_id) is None
        assert db.get_transaction(to_id) is None


class TestDividendAlertLink:
    def _alert(self, *, ex_date: str = "2026-01-10",
               fund_code: str = "005827") -> int:
        return db.add_dividend_alert({
            "fund_code": fund_code,
            "fund_name": "易方达蓝筹精选",
            "ex_date": ex_date,
            "per_share": 0.1,
        })

    def test_link_success(self, temp_db):
        alert_id = self._alert()
        result = _create_dividend(_principal(), alert_id=alert_id)
        assert result.http_status == 201
        assert _alert_of(alert_id)["status"] == "pending"  # 未批准前不处理

        approved = _approve(result.data["proposal_id"])
        assert approved.code == "succeeded"
        execution = approved.data["execution_result"]
        tx_id = execution["tx_id"]
        assert db.get_transaction(tx_id).action == "dividend"

        alert = _alert_of(alert_id)
        assert alert["status"] == "confirmed"
        assert alert["tx_id"] == tx_id
        assert alert["resolved_at"]

    def test_resolved_alert_blocks(self, temp_db):
        alert_id = self._alert()
        db.update_dividend_alert(alert_id, status="confirmed")
        result = _create_dividend(_principal(), alert_id=alert_id)
        assert result.http_status == 201

        approved = _approve(result.data["proposal_id"])
        assert approved.code == "dividend_alert_resolved"
        assert approved.data["execution_result"]["reason"] == \
            "dividend_alert_resolved"
        # 失败时不得留下流水（提醒校验先于写入）。
        assert db.get_transactions() == []

    def test_fund_mismatch_blocks(self, temp_db):
        alert_id = self._alert(fund_code="110011")
        result = _create_dividend(_principal(), alert_id=alert_id)
        assert result.http_status == 201

        approved = _approve(result.data["proposal_id"])
        assert approved.code == "dividend_alert_fund_mismatch"
        assert db.get_transactions() == []
        assert _alert_of(alert_id)["status"] == "pending"

    def test_non_dividend_action_rejected(self, temp_db):
        alert_id = self._alert()
        with pytest.raises(svc.ProposalValidationError) as exc:
            svc.create_proposal(
                _principal(), operation_type=svc.OPERATION_ADD_TRANSACTION,
                params={"fund_code": "005827", "action": "buy",
                        "date": "2026-01-02", "amount": 100.0,
                        "dividend_alert_id": alert_id},
                idempotency_key=KEY_DIV)
        assert exc.value.field == "dividend_alert_id"


class TestConversionIdempotency:
    def test_same_key_replays(self, temp_db):
        principal = _principal()
        first = _create_conversion(principal)
        second = _create_conversion(principal)

        assert second.replayed is True
        assert second.data["proposal_id"] == first.data["proposal_id"]
        assert second.data["summary"]["operation_type"] == "add_conversion"

    def test_same_key_different_params_conflicts(self, temp_db):
        principal = _principal()
        _create_conversion(principal)
        result = _create_conversion(
            principal, params={**CONVERSION_PARAMS, "from_shares": 60.0})

        assert result.http_status == 409
        assert result.code == "idempotency_conflict"


class TestConversionScope:
    def test_propose_scope_suffices_for_conversions(self, temp_db):
        principal = _principal(agent_tokens.SCOPE_TRANSACTIONS_PROPOSE)
        result = _create_conversion(principal)
        assert result.http_status == 201

        # 审批期复核创建者 token 仍具 transactions:propose（OPERATION_SCOPE）。
        approved = _approve(result.data["proposal_id"])
        assert approved.code == "succeeded"
