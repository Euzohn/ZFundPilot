"""F6.2 交易回填提案测试：创建期写事务外预计算、整批拒绝语义与审批执行。

覆盖：单行/批量成功、dividend 行拒绝（422）、nav 已存在（409）、digest 失配、
nav_unavailable / fee_unknown（含 no_buy_record）拒绝、显式 fee、费率抓取不在
写事务内、预计算与写事务间并发修改整批拒绝、不触碰 date/action/channel/note、
审批整批写入与审计（nav_backfill 对齐网页）、部分已回填整批 conflict；
precheck_backfill 只读工具（纯离线 + 写总闸 + scope + 限流）。
"""
from __future__ import annotations

import sqlite3
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest
from fastapi.testclient import TestClient

from zfundpilot import agent_tokens, api, config, db, fetch_fund
from zfundpilot import proposal_service as svc
from zfundpilot.analysis import clear_analysis_cache
from zfundpilot.fetch_fund import CalcFeeResult
from zfundpilot.models import Fund, NavPoint, Transaction

PROPOSALS_PATH = "/api/agent/tools/proposals"
CAPABILITIES_PATH = "/api/agent/tools/capabilities"
PRECHECK_BACKFILL_PATH = "/api/agent/tools/precheck/backfill"
KEY_A = "backfill-key-aaaaaaaaaa"
KEY_B = "backfill-key-bbbbbbbbbb"

FUND_CODE = "005827"


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
        db.upsert_fund(Fund(FUND_CODE, "易方达蓝筹精选", "混合型", "消费"))
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


def _backfill_principal() -> svc.Principal:
    return _principal(agent_tokens.SCOPE_TRANSACTIONS_PROPOSE)


def _make_buy_tx(*, date: str = "2026-01-05", amount: float = 1000.0,
                 is_t1: bool = False, fee: float = 0.0,
                 fund_code: str = FUND_CODE) -> int:
    return db.add_transaction(Transaction(
        fund_code=fund_code, action="buy", date=date, amount=amount,
        is_t1=is_t1, fee=fee))


def _make_sell_tx(*, date: str = "2026-01-05", shares: float = 100.0,
                  fee: float = 0.0) -> int:
    return db.add_transaction(Transaction(
        fund_code=FUND_CODE, action="sell", date=date, shares=shares,
        fee=fee))


def _make_dividend_tx(*, date: str = "2026-01-05") -> int:
    return db.add_transaction(Transaction(
        fund_code=FUND_CODE, action="dividend", date=date, amount=50.0))


def _add_nav(*, code: str = FUND_CODE, date: str = "2026-01-05",
             nav: float = 1.5) -> None:
    db.upsert_nav_batch([NavPoint(fund_code=code, date=date, nav=nav)])


def _tx_row(tx_id: int) -> dict:
    with db.get_connection() as conn:
        row = db.get_transaction_conn(conn, tx_id)
    return dict(row)


def _digest(tx_id: int) -> str:
    return svc.transaction_row_digest(_tx_row(tx_id))


def _item(tx_id: int, *, fee: float | None = None) -> dict:
    item: dict = {"tx_id": tx_id, "expected_digest": _digest(tx_id)}
    if fee is not None:
        item["fee"] = fee
    return item


def _params(tx_id: int, **kw) -> dict:
    return {"items": [_item(tx_id, **kw)]}


def _create(principal, params, *, key: str = KEY_A):
    return svc.create_proposal(
        principal, operation_type=svc.OPERATION_BACKFILL_TRANSACTION_NAVS,
        params=params, idempotency_key=key)


def _audit_actions() -> list[str]:
    return [row["action"] for row in db.fetch_audit_logs(200)]


def _get_proposal(pid: int) -> dict:
    with db.get_connection() as conn:
        row = db.get_proposal(conn, pid)
    return svc.proposal_row_to_dict(row, svc._now())


def _approve(pid: int, reviewer: str = "admin"):
    return svc.approve_proposal(pid, reviewer=reviewer)


# ---------------------------------------------------------------------------
# 创建校验
# ---------------------------------------------------------------------------

class TestCreateBackfill:
    def test_single_buy_creates_pending_proposal(self, temp_db, monkeypatch):
        monkeypatch.setattr(fetch_fund, "calc_purchase_fee", lambda code, amt:
                            CalcFeeResult(fee=0.0, code="purchase_rate"))
        tx_id = _make_buy_tx()
        _add_nav(date="2026-01-05", nav=1.5)
        result = _create(_backfill_principal(), _params(tx_id))
        assert result.http_status == 201
        assert result.code == "created"
        summary = result.data["summary"]
        assert summary["operation_type"] == "backfill_transaction_navs"
        assert summary["count"] == 1
        item = summary["items"][0]
        assert item["tx_id"] == tx_id
        assert item["after"]["nav"] == 1.5
        # 买入：amount 已知 1000，fee=0 → shares = (1000-0)/1.5
        assert item["after"]["shares"] == round((1000.0 - 0.0) / 1.5, 2)
        assert item["nav_date"] == "2026-01-05"

    def test_t1_uses_next_day_nav(self, temp_db, monkeypatch):
        monkeypatch.setattr(fetch_fund, "calc_purchase_fee", lambda code, amt:
                            CalcFeeResult(fee=0.0, code="purchase_rate"))
        tx_id = _make_buy_tx(date="2026-01-05", is_t1=True)
        _add_nav(date="2026-01-06", nav=1.6)
        result = _create(_backfill_principal(), _params(tx_id))
        assert result.ok
        item = result.data["summary"]["items"][0]
        assert item["nav_date"] == "2026-01-06"
        assert item["after"]["nav"] == 1.6

    def test_batch_success(self, temp_db, monkeypatch):
        monkeypatch.setattr(fetch_fund, "calc_purchase_fee", lambda code, amt:
                            CalcFeeResult(fee=0.0, code="purchase_rate"))
        ids = [_make_buy_tx(date=f"2026-01-0{d}") for d in (5, 6)]
        _add_nav(date="2026-01-05", nav=1.5)
        _add_nav(date="2026-01-06", nav=1.55)
        params = {"items": [_item(i) for i in ids]}
        result = _create(_backfill_principal(), params)
        assert result.ok
        assert result.data["summary"]["count"] == 2

    def test_dividend_row_rejected(self, temp_db):
        tx_id = _make_dividend_tx()
        result = _create(_backfill_principal(), _params(tx_id))
        assert result.http_status == 422
        assert result.code == "dividend_not_backfillable"
        assert result.data["issues"][0]["index"] == 0

    def test_nav_present_rejected(self, temp_db):
        tx_id = _make_buy_tx()
        _add_nav(date="2026-01-05", nav=1.5)
        # 先手工把该行 nav 填上
        with db.get_connection(write=True) as conn:
            conn.execute("UPDATE transactions SET nav=1.5 WHERE id=?", (tx_id,))
        result = _create(_backfill_principal(), _params(tx_id))
        assert result.http_status == 409
        assert result.code == "nav_present"

    def test_target_not_found(self, temp_db):
        result = _create(_backfill_principal(), {"items": [
            {"tx_id": 9999, "expected_digest": "0" * 64}]})
        assert result.http_status == 409
        assert result.code == "target_not_found"

    def test_digest_mismatch_rejected(self, temp_db):
        tx_id = _make_buy_tx()
        _add_nav(date="2026-01-05", nav=1.5)
        params = {"items": [{"tx_id": tx_id,
                             "expected_digest": "0" * 64}]}
        result = _create(_backfill_principal(), params)
        assert result.http_status == 409
        assert result.code == "target_changed"

    def test_nav_unavailable_rejected(self, temp_db):
        tx_id = _make_buy_tx(date="2026-02-01")
        # 不写入任何净值
        result = _create(_backfill_principal(), _params(tx_id))
        assert result.http_status == 409
        assert result.code == "nav_unavailable"

    def test_fee_unknown_rejected_when_not_explicit(self, temp_db, monkeypatch):
        monkeypatch.setattr(fetch_fund, "calc_purchase_fee", lambda code, amt:
                            CalcFeeResult(fee=0.0, code="fee_unknown"))
        tx_id = _make_buy_tx()
        _add_nav(date="2026-01-05", nav=1.5)
        result = _create(_backfill_principal(), _params(tx_id))
        assert result.http_status == 409
        assert result.code == "fee_unknown"

    def test_explicit_fee_overrides_unknown(self, temp_db, monkeypatch):
        monkeypatch.setattr(fetch_fund, "calc_purchase_fee", lambda code, amt:
                            CalcFeeResult(fee=0.0, code="fee_unknown"))
        tx_id = _make_buy_tx()
        _add_nav(date="2026-01-05", nav=1.5)
        result = _create(_backfill_principal(), _params(tx_id, fee=9.9))
        assert result.ok
        item = result.data["summary"]["items"][0]
        assert item["after"]["fee"] == 9.9
        assert item["fee_source"] == "explicit"

    def test_existing_nonzero_fee_reused(self, temp_db, monkeypatch):
        def _boom(*a, **k):
            raise AssertionError("已有手续费不应再抓取费率")
        monkeypatch.setattr(fetch_fund, "calc_purchase_fee", _boom)
        tx_id = _make_buy_tx(fee=7.5)
        _add_nav(date="2026-01-05", nav=1.5)
        result = _create(_backfill_principal(), _params(tx_id))
        assert result.ok
        item = result.data["summary"]["items"][0]
        assert item["fee_source"] == "existing"
        assert item["after"]["fee"] == 7.5

    def test_validation_rejects_empty_and_dup(self, temp_db):
        principal = _backfill_principal()
        for bad in ([], "x", None):
            with pytest.raises(svc.ProposalValidationError):
                svc.create_proposal(
                    principal,
                    operation_type=svc.OPERATION_BACKFILL_TRANSACTION_NAVS,
                    params={"items": bad}, idempotency_key=KEY_A)
        tx_id = _make_buy_tx()
        _add_nav(date="2026-01-05", nav=1.5)
        dup = {"items": [_item(tx_id), _item(tx_id)]}
        with pytest.raises(svc.ProposalValidationError):
            _create(principal, dup, key=KEY_B)

    def test_validation_rejects_unknown_top_level(self, temp_db):
        tx_id = _make_buy_tx()
        with pytest.raises(svc.ProposalValidationError):
            _create(_backfill_principal(),
                    {"items": [_item(tx_id)], "note": "x"})

    def test_idempotent_replay(self, temp_db, monkeypatch):
        monkeypatch.setattr(fetch_fund, "calc_purchase_fee", lambda code, amt:
                            CalcFeeResult(fee=0.0, code="purchase_rate"))
        tx_id = _make_buy_tx()
        _add_nav(date="2026-01-05", nav=1.5)
        principal = _backfill_principal()
        first = _create(principal, _params(tx_id))
        second = _create(principal, _params(tx_id))
        assert first.data["proposal_id"] == second.data["proposal_id"]
        assert second.replayed is True
        assert second.code == "replayed"

    def test_fee_fetch_runs_outside_write_transaction(self, temp_db,
                                                       monkeypatch):
        """费率抓取不得在 BEGIN IMMEDIATE 写事务内（F6.2 复查 Bug 1）。

        预计算阶段若已持写锁，另一个连接立即尝试写会 ``database is locked``。
        """
        def _fee_with_lock_probe(code, amt):
            probe = sqlite3.connect(config.DB_PATH, timeout=0.05)
            try:
                probe.execute("BEGIN IMMEDIATE")
                probe.rollback()
            finally:
                probe.close()
            return CalcFeeResult(fee=0.0, code="purchase_rate")

        monkeypatch.setattr(fetch_fund, "calc_purchase_fee",
                            _fee_with_lock_probe)
        tx_id = _make_buy_tx()
        _add_nav(date="2026-01-05", nav=1.5)
        result = _create(_backfill_principal(), _params(tx_id))
        assert result.ok

    def test_sell_no_buy_record_rejected(self, temp_db, monkeypatch):
        """无买入记录时不能静默回填 fee=0（F6.2 复查 Bug 2）。"""
        monkeypatch.setattr(
            fetch_fund, "calc_redemption_fee",
            lambda code, date, shares: CalcFeeResult(
                fee=0.0, code="no_buy_record"))
        tx_id = _make_sell_tx()
        _add_nav(date="2026-01-05", nav=1.5)
        result = _create(_backfill_principal(), _params(tx_id))
        assert result.http_status == 409
        assert result.code == "fee_unknown"
        assert "无买入记录" in result.message

    def test_concurrent_change_before_write_rejected(self, temp_db,
                                                     monkeypatch):
        """预计算与写事务之间的并发修改必须整批拒绝，不能写入过期快照。"""
        monkeypatch.setattr(fetch_fund, "calc_purchase_fee", lambda code, amt:
                            CalcFeeResult(fee=0.0, code="purchase_rate"))
        tx_id = _make_buy_tx()
        _add_nav(date="2026-01-05", nav=1.5)
        original = svc._prepare_backfill_items

        def _race(conn, items):
            prepared, error = original(conn, items)
            with db.get_connection(write=True) as wconn:
                wconn.execute(
                    "UPDATE transactions SET note='raced' WHERE id=?", (tx_id,))
            return prepared, error

        monkeypatch.setattr(svc, "_prepare_backfill_items", _race)
        result = _create(_backfill_principal(), _params(tx_id))
        assert result.http_status == 409
        assert result.code == "target_changed"


# ---------------------------------------------------------------------------
# 审批执行
# ---------------------------------------------------------------------------

class TestApproveBackfill:
    def test_approve_writes_snapshot_and_audits(self, temp_db, monkeypatch):
        monkeypatch.setattr(fetch_fund, "calc_purchase_fee", lambda code, amt:
                            CalcFeeResult(fee=1.0, code="purchase_rate"))
        tx_id = _make_buy_tx(amount=1000.0)
        _add_nav(date="2026-01-05", nav=1.5)
        created = _create(_backfill_principal(), _params(tx_id))
        pid = created.data["proposal_id"]
        approved = _approve(pid)
        assert approved.ok
        assert approved.code == "succeeded"
        row = _tx_row(tx_id)
        assert row["nav"] == 1.5
        assert row["fee"] == 1.0
        assert row["shares"] == round((1000.0 - 1.0) / 1.5, 2)
        # 审计对齐网页/调度器事件名
        actions = _audit_actions()
        assert "nav_backfill" in actions
        assert "proposal_approved" in actions

    def test_approve_does_not_touch_other_fields(self, temp_db, monkeypatch):
        monkeypatch.setattr(fetch_fund, "calc_purchase_fee", lambda code, amt:
                            CalcFeeResult(fee=0.0, code="purchase_rate"))
        tx_id = _make_buy_tx(date="2026-01-05", amount=1000.0, fee=0.0)
        _add_nav(date="2026-01-05", nav=1.5)
        before = _tx_row(tx_id)
        created = _create(_backfill_principal(), _params(tx_id))
        _approve(created.data["proposal_id"])
        after = _tx_row(tx_id)
        assert after["date"] == before["date"]
        assert after["action"] == before["action"]
        assert after["channel"] == before["channel"]
        assert after["note"] == before["note"]
        assert after["is_t1"] == before["is_t1"]

    def test_batch_all_or_nothing_on_partial_filled(self, temp_db, monkeypatch):
        monkeypatch.setattr(fetch_fund, "calc_purchase_fee", lambda code, amt:
                            CalcFeeResult(fee=0.0, code="purchase_rate"))
        id_a = _make_buy_tx(date="2026-01-05")
        id_b = _make_buy_tx(date="2026-01-06")
        _add_nav(date="2026-01-05", nav=1.5)
        _add_nav(date="2026-01-06", nav=1.55)
        params = {"items": [_item(id_a), _item(id_b)]}
        created = _create(_backfill_principal(), params)
        pid = created.data["proposal_id"]
        # 在审批前用其他路径回填 b 行 → 整批 conflict
        with db.get_connection(write=True) as conn:
            conn.execute(
                "UPDATE transactions SET nav=9.9 WHERE id=?", (id_b,))
        approved = _approve(pid)
        assert approved.http_status == 409
        assert approved.code == "partially_updated"
        # a 行也未被写入（无部分写入）
        assert _tx_row(id_a)["nav"] is None
        assert _tx_row(id_b)["nav"] == 9.9

    def test_reapprove_is_conflict(self, temp_db, monkeypatch):
        monkeypatch.setattr(fetch_fund, "calc_purchase_fee", lambda code, amt:
                            CalcFeeResult(fee=0.0, code="purchase_rate"))
        tx_id = _make_buy_tx()
        _add_nav(date="2026-01-05", nav=1.5)
        created = _create(_backfill_principal(), _params(tx_id))
        pid = created.data["proposal_id"]
        assert _approve(pid).ok
        again = _approve(pid)
        assert again.http_status == 409
        assert again.code == "not_pending"


# ---------------------------------------------------------------------------
# HTTP 门控与 precheck 工具
# ---------------------------------------------------------------------------

class TestHttpGating:
    def test_backfill_proposal_endpoint_via_scope(self, client, temp_db,
                                                   monkeypatch):
        monkeypatch.setattr(fetch_fund, "calc_purchase_fee", lambda code, amt:
                            CalcFeeResult(fee=0.0, code="purchase_rate"))
        tx_id = _make_buy_tx()
        _add_nav(date="2026-01-05", nav=1.5)
        _plain, info = agent_tokens.issue_token(
            "agent", [agent_tokens.SCOPE_TRANSACTIONS_PROPOSE])
        headers = {"Authorization": f"Bearer {_plain}",
                   "Idempotency-Key": KEY_A}
        resp = client.post(PROPOSALS_PATH, headers=headers, json={
            "operation_type": "backfill_transaction_navs",
            "params": _params(tx_id)})
        assert resp.status_code == 201, resp.text
        assert resp.json()["data"]["summary"]["operation_type"] == \
            "backfill_transaction_navs"

    def test_alerts_scope_cannot_create_backfill(self, client, temp_db):
        _plain, _info = agent_tokens.issue_token(
            "agent", [agent_tokens.SCOPE_ALERTS_PROPOSE])
        headers = {"Authorization": f"Bearer {_plain}",
                   "Idempotency-Key": KEY_A}
        resp = client.post(PROPOSALS_PATH, headers=headers, json={
            "operation_type": "backfill_transaction_navs",
            "params": {"items": [{"tx_id": 1,
                                  "expected_digest": "0" * 64}]}})
        assert resp.status_code == 403

    def test_precheck_backfill_is_offline(self, client, temp_db, monkeypatch):
        """precheck 只读盘点不得联网抓费率（F6.2 复查问题 3）。"""
        def _boom(*args, **kwargs):
            raise AssertionError("precheck_backfill 不应抓取费率")

        monkeypatch.setattr(fetch_fund, "calc_purchase_fee", _boom)
        monkeypatch.setattr(fetch_fund, "calc_redemption_fee", _boom)
        _add_nav(date="2026-01-05", nav=1.5)
        buy_id = _make_buy_tx()
        sell_id = _make_sell_tx()
        _plain, _info = agent_tokens.issue_token(
            "agent", [agent_tokens.SCOPE_TRANSACTIONS_PROPOSE])
        headers = {"Authorization": f"Bearer {_plain}"}
        resp = client.post(PRECHECK_BACKFILL_PATH, headers=headers,
                           json={"tx_ids": [buy_id, sell_id]})
        assert resp.status_code == 200, resp.text
        for item in resp.json()["data"]["items"]:
            assert item["backfillable"] is True
            assert item["fee_source"] == "needs_fee"
            assert item["fee_pending"] is True
            assert item["after"]["nav"] == 1.5

    def test_precheck_backfill_lists_candidates(self, client, temp_db,
                                                 monkeypatch):
        monkeypatch.setattr(fetch_fund, "calc_purchase_fee", lambda code, amt:
                            CalcFeeResult(fee=0.0, code="purchase_rate"))
        _add_nav(date="2026-01-05", nav=1.5)
        buy_id = _make_buy_tx()
        div_id = _make_dividend_tx()
        _plain, _info = agent_tokens.issue_token(
            "agent", [agent_tokens.SCOPE_TRANSACTIONS_PROPOSE])
        headers = {"Authorization": f"Bearer {_plain}"}
        resp = client.post(PRECHECK_BACKFILL_PATH, headers=headers, json={})
        assert resp.status_code == 200, resp.text
        data = resp.json()["data"]
        tx_ids = {it["tx_id"] for it in data["items"]}
        assert buy_id in tx_ids
        # 分红行默认不在候选里（省略 tx_ids 时排除）
        assert div_id not in tx_ids
        buy_item = next(it for it in data["items"] if it["tx_id"] == buy_id)
        assert buy_item["backfillable"] is True
        assert len(buy_item["row_digest"]) == 64

    def test_precheck_backfill_reports_dividend_on_explicit(self, client,
                                                             temp_db):
        div_id = _make_dividend_tx()
        _plain, _info = agent_tokens.issue_token(
            "agent", [agent_tokens.SCOPE_TRANSACTIONS_PROPOSE])
        headers = {"Authorization": f"Bearer {_plain}"}
        resp = client.post(PRECHECK_BACKFILL_PATH, headers=headers,
                           json={"tx_ids": [div_id]})
        assert resp.status_code == 200
        item = resp.json()["data"]["items"][0]
        assert item["backfillable"] is False
        assert item["reason"] == "dividend_not_backfillable"

    def test_precheck_backfill_write_gate(self, client, temp_db,
                                           monkeypatch):
        monkeypatch.setattr(config, "AGENT_WRITE_ENABLED", False)
        _plain, _info = agent_tokens.issue_token(
            "agent", [agent_tokens.SCOPE_TRANSACTIONS_PROPOSE])
        headers = {"Authorization": f"Bearer {_plain}"}
        resp = client.post(PRECHECK_BACKFILL_PATH, headers=headers, json={})
        assert resp.status_code == 403

    def test_precheck_backfill_requires_scope(self, client, temp_db):
        _plain, _info = agent_tokens.issue_token(
            "agent", [agent_tokens.SCOPE_PORTFOLIO_READ])
        headers = {"Authorization": f"Bearer {_plain}"}
        resp = client.post(PRECHECK_BACKFILL_PATH, headers=headers, json={})
        assert resp.status_code == 403

    def test_capabilities_includes_precheck_backfill(self, client, temp_db):
        _plain, _info = agent_tokens.issue_token(
            "agent", [agent_tokens.SCOPE_TRANSACTIONS_PROPOSE])
        headers = {"Authorization": f"Bearer {_plain}"}
        resp = client.get(CAPABILITIES_PATH, headers=headers)
        assert resp.status_code == 200
        names = {t["name"] for t in resp.json()["data"]["tools"]}
        assert "precheck_backfill" in names

    def test_precheck_backfill_rate_limited(self, client, temp_db,
                                            monkeypatch):
        api._AGENT_REQ_LOGS.clear()
        _plain, _info = agent_tokens.issue_token(
            "agent", [agent_tokens.SCOPE_TRANSACTIONS_PROPOSE])
        headers = {"Authorization": f"Bearer {_plain}"}
        last = None
        for _ in range(12):
            last = client.post(PRECHECK_BACKFILL_PATH, headers=headers,
                               json={})
        assert last is not None and last.status_code == 429
