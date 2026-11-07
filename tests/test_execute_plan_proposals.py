"""F6.3 定投手动执行提案测试：创建期零副作用、费率/T+1 快照、审批写入。

覆盖：计划引用与 digest、交易日窗口、当日/历史幂等、可投性严格阻断、
费率未知需显式 fee、写事务外抓费、审批写一笔买入流水并推进
last_run/last_tx_id（不重算 next_run）、目标被改/被删/已执行/不可投冲突、
补记历史日期不倒退 last_run、成功提案级重复保护、scope 门控。
"""
from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest
from fastapi.testclient import TestClient

from zfundpilot import agent_tokens, api, auto_invest, config, db, fetch_fund
from zfundpilot import proposal_service as svc
from zfundpilot.analysis import clear_analysis_cache
from zfundpilot.fetch_fund import CalcFeeResult
from zfundpilot.models import Fund

PROPOSALS_PATH = "/api/agent/tools/proposals"
CAPABILITIES_PATH = "/api/agent/tools/capabilities"
KEY_A = "execute-plan-key-aaaaaaaa"
KEY_B = "execute-plan-key-bbbbbbbb"
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


def _tx_principal() -> svc.Principal:
    return _principal(agent_tokens.SCOPE_TRANSACTIONS_PROPOSE)


def _fixed_now(monkeypatch, *, year: int = 2026, month: int = 1,
               day: int = 5, hour: int = 10) -> datetime:
    now = datetime(year, month, day, hour, 0, tzinfo=config.TIMEZONE)
    monkeypatch.setattr(svc, "_now", lambda: now)
    return now


def _make_plan(*, amount: float = 500.0, channel: str = "支付宝",
               note: str = "工资定投", enabled: int = 1,
               last_run: str | None = None,
               next_run: str | None = "2026-01-12") -> int:
    plan_id = db.add_auto_invest_plan(
        fund_code=FUND_CODE, amount=amount, cadence="week", day_of_week=0,
        channel=channel, note=note, next_run=next_run)
    fields: dict = {}
    if enabled == 0:
        fields["enabled"] = 0
    if last_run is not None:
        fields["last_run"] = last_run
    if fields:
        db.update_auto_invest_plan(plan_id, **fields)
    return plan_id


def _plan(plan_id: int) -> dict:
    return db.get_auto_invest_plan(plan_id)


def _digest(plan_id: int) -> str:
    return auto_invest.plan_row_digest(_plan(plan_id))


def _params(plan_id: int, *, trade_date: str | None = None,
            fee: float | None = None) -> dict:
    params: dict = {
        "plan_id": plan_id, "expected_digest": _digest(plan_id)}
    if trade_date is not None:
        params["trade_date"] = trade_date
    if fee is not None:
        params["fee"] = fee
    return params


def _create(principal: svc.Principal, params: dict, *,
            key: str = KEY_A) -> svc.ProposalResult:
    return svc.create_proposal(
        principal, operation_type=svc.OPERATION_EXECUTE_PLAN,
        params=params, idempotency_key=key)


def _approve(pid: int, reviewer: str = "admin") -> svc.ProposalResult:
    return svc.approve_proposal(pid, reviewer=reviewer)


def _transactions() -> list[dict]:
    with db.get_connection() as conn:
        rows = conn.execute("SELECT * FROM transactions ORDER BY id").fetchall()
    return [dict(r) for r in rows]


def _audit_actions() -> list[str]:
    return [row["action"] for row in db.fetch_audit_logs(200)]


def _fee(fee: float = 1.5, code: str = "purchase_rate"):
    return lambda code_, amount: CalcFeeResult(fee=fee, code=code)


# ---------------------------------------------------------------------------
# 创建校验
# ---------------------------------------------------------------------------

class TestCreateExecutePlan:
    def test_creates_pending_without_side_effects(self, temp_db, monkeypatch):
        _fixed_now(monkeypatch)
        monkeypatch.setattr(fetch_fund, "calc_purchase_fee", _fee(1.5))
        plan_id = _make_plan()
        result = _create(_tx_principal(), _params(plan_id))
        assert result.http_status == 201
        assert result.code == "created"
        summary = result.data["summary"]
        assert summary["operation_type"] == "execute_plan"
        assert summary["plan_id"] == plan_id
        assert summary["amount"] == 500.0
        assert summary["trade_date"] == "2026-01-05"
        assert summary["is_t1"] is False
        assert summary["fee"] == 1.5
        assert summary["fee_source"] == "fetched"
        # 创建提案不写账本、不动计划簿记。
        assert _transactions() == []
        assert _plan(plan_id)["last_run"] is None

    def test_default_trade_date_is_today(self, temp_db, monkeypatch):
        _fixed_now(monkeypatch, day=5)
        monkeypatch.setattr(fetch_fund, "calc_purchase_fee", _fee(0.0))
        plan_id = _make_plan()
        result = _create(_tx_principal(), _params(plan_id))
        assert result.data["summary"]["trade_date"] == "2026-01-05"

    def test_is_t1_after_cutoff_when_created_today(self, temp_db, monkeypatch):
        _fixed_now(monkeypatch, hour=16)
        monkeypatch.setattr(fetch_fund, "calc_purchase_fee", _fee(0.0))
        plan_id = _make_plan()
        result = _create(_tx_principal(), _params(plan_id))
        assert result.data["summary"]["is_t1"] is True

    def test_historical_trade_date_snapshot(self, temp_db, monkeypatch):
        _fixed_now(monkeypatch, day=10)
        monkeypatch.setattr(fetch_fund, "calc_purchase_fee", _fee(0.0))
        plan_id = _make_plan()
        result = _create(
            _tx_principal(), _params(plan_id, trade_date="2026-01-08"))
        summary = result.data["summary"]
        assert summary["trade_date"] == "2026-01-08"
        assert summary["is_t1"] is False
        assert any("补记历史交易日" in w for w in summary["warnings"])

    @pytest.mark.parametrize("trade_date", [
        "2026-01-06",   # 未来
        "2025-12-28",   # 超过 7 天
        "2026/01/05",   # 格式错误
        "2026-02-30",   # 非法日期
    ])
    def test_invalid_trade_date_rejected(self, temp_db, monkeypatch,
                                         trade_date):
        _fixed_now(monkeypatch, day=5)
        plan_id = _make_plan()
        with pytest.raises(svc.ProposalValidationError):
            _create(
                _tx_principal(), _params(plan_id, trade_date=trade_date))

    @pytest.mark.parametrize("field,value", [
        ("amount", 1000.0), ("is_t1", True), ("channel", "天天基金"),
        ("note", "改备注"), ("last_run", "2026-01-04"),
        ("next_run", "2026-02-01"), ("enabled", False),
    ])
    def test_forbidden_overrides_rejected(self, temp_db, monkeypatch,
                                          field, value):
        _fixed_now(monkeypatch)
        plan_id = _make_plan()
        params = _params(plan_id)
        params[field] = value
        with pytest.raises(svc.ProposalValidationError):
            _create(_tx_principal(), params)

    def test_unknown_field_rejected(self, temp_db, monkeypatch):
        _fixed_now(monkeypatch)
        plan_id = _make_plan()
        params = _params(plan_id)
        params["foo"] = 1
        with pytest.raises(svc.ProposalValidationError):
            _create(_tx_principal(), params)

    def test_plan_not_found(self, temp_db, monkeypatch):
        _fixed_now(monkeypatch)
        result = _create(_tx_principal(), {
            "plan_id": 999, "expected_digest": "0" * 64})
        assert result.http_status == 404
        assert result.code == "target_not_found"

    def test_digest_mismatch(self, temp_db, monkeypatch):
        _fixed_now(monkeypatch)
        plan_id = _make_plan()
        params = _params(plan_id)
        params["expected_digest"] = "f" * 64
        result = _create(_tx_principal(), params)
        assert result.http_status == 409
        assert result.code == "target_changed"

    def test_last_run_same_date_rejected(self, temp_db, monkeypatch):
        _fixed_now(monkeypatch)
        plan_id = _make_plan(last_run="2026-01-05")
        result = _create(_tx_principal(), _params(plan_id))
        assert result.http_status == 409
        assert result.code == "already_executed"

    @pytest.mark.parametrize("status,limit,minimum,amount,reason", [
        ("暂停申购", 0, 0, 500.0, "suspended"),
        ("开放申购", 100.0, 0, 500.0, "limit_exceeded"),
        ("开放申购", 0, 1000.0, 500.0, "below_minimum"),
    ])
    def test_purchasable_strictly_blocked(self, temp_db, monkeypatch, status,
                                         limit, minimum, amount, reason):
        _fixed_now(monkeypatch)
        monkeypatch.setattr(fetch_fund, "calc_purchase_fee", _fee(0.0))
        db.update_fund_purchase_status(FUND_CODE, status, limit, minimum)
        plan_id = _make_plan(amount=amount)
        result = _create(_tx_principal(), _params(plan_id))
        assert result.http_status == 409
        assert result.code == reason

    def test_fee_unknown_requires_explicit_fee(self, temp_db, monkeypatch):
        _fixed_now(monkeypatch)
        monkeypatch.setattr(
            fetch_fund, "calc_purchase_fee", _fee(0.0, "fee_unknown"))
        plan_id = _make_plan()
        result = _create(_tx_principal(), _params(plan_id))
        assert result.http_status == 409
        assert result.code == "fee_unknown"

    def test_explicit_fee_skips_fee_fetch(self, temp_db, monkeypatch):
        _fixed_now(monkeypatch)

        def _boom(*args, **kwargs):
            raise AssertionError("显式 fee 不应抓取费率")

        monkeypatch.setattr(fetch_fund, "calc_purchase_fee", _boom)
        plan_id = _make_plan()
        result = _create(_tx_principal(), _params(plan_id, fee=2.5))
        assert result.ok
        summary = result.data["summary"]
        assert summary["fee"] == 2.5
        assert summary["fee_source"] == "explicit"

    def test_fee_fetch_runs_outside_write_transaction(self, temp_db,
                                                       monkeypatch):
        _fixed_now(monkeypatch)

        def _fee_with_lock_probe(code, amount):
            probe = sqlite3.connect(config.DB_PATH, timeout=0.05)
            try:
                probe.execute("BEGIN IMMEDIATE")
                probe.rollback()
            finally:
                probe.close()
            return CalcFeeResult(fee=0.0, code="purchase_rate")

        monkeypatch.setattr(fetch_fund, "calc_purchase_fee",
                            _fee_with_lock_probe)
        plan_id = _make_plan()
        assert _create(_tx_principal(), _params(plan_id)).ok


# ---------------------------------------------------------------------------
# 审批执行
# ---------------------------------------------------------------------------

class TestApproveExecutePlan:
    def test_approve_writes_one_buy_and_advances_bookkeeping(
            self, temp_db, monkeypatch):
        _fixed_now(monkeypatch)
        monkeypatch.setattr(fetch_fund, "calc_purchase_fee", _fee(1.5))
        plan_id = _make_plan()
        created = _create(_tx_principal(), _params(plan_id))
        approved = _approve(created.data["proposal_id"])
        assert approved.ok
        assert approved.code == "succeeded"

        rows = _transactions()
        assert len(rows) == 1
        tx = rows[0]
        assert tx["action"] == "buy"
        assert tx["fund_code"] == FUND_CODE
        assert tx["date"] == "2026-01-05"
        assert tx["amount"] == 500.0
        assert tx["shares"] is None
        assert tx["nav"] is None
        assert tx["fee"] == 1.5
        assert tx["channel"] == "支付宝"
        assert tx["note"] == "工资定投"
        assert bool(tx["is_t1"]) is False

        plan = _plan(plan_id)
        assert plan["last_run"] == "2026-01-05"
        assert plan["last_tx_id"] == tx["id"]
        assert plan["next_run"] == "2026-01-12"

        actions = _audit_actions()
        assert "auto_invest_execute" in actions
        assert "proposal_approved" in actions
        detail = approved.data["execution_result"]
        assert detail["tx_id"] == tx["id"]
        assert detail["plan_id"] == plan_id

    def test_t1_snapshot_written_on_approval(self, temp_db, monkeypatch):
        _fixed_now(monkeypatch, hour=16)
        monkeypatch.setattr(fetch_fund, "calc_purchase_fee", _fee(0.0))
        plan_id = _make_plan()
        created = _create(_tx_principal(), _params(plan_id))
        _approve(created.data["proposal_id"])
        assert bool(_transactions()[0]["is_t1"]) is True

    def test_plan_changed_before_approval_conflicts(self, temp_db, monkeypatch):
        _fixed_now(monkeypatch)
        monkeypatch.setattr(fetch_fund, "calc_purchase_fee", _fee(0.0))
        plan_id = _make_plan()
        created = _create(_tx_principal(), _params(plan_id))
        db.update_auto_invest_plan(plan_id, amount=800.0)
        result = _approve(created.data["proposal_id"])
        assert result.http_status == 409
        assert result.code == "target_changed"
        assert _transactions() == []

    def test_plan_deleted_before_approval_conflicts(self, temp_db, monkeypatch):
        _fixed_now(monkeypatch)
        monkeypatch.setattr(fetch_fund, "calc_purchase_fee", _fee(0.0))
        plan_id = _make_plan()
        created = _create(_tx_principal(), _params(plan_id))
        db.delete_auto_invest_plan(plan_id)
        result = _approve(created.data["proposal_id"])
        assert result.http_status == 409
        assert result.code == "target_deleted"
        assert _transactions() == []

    def test_scheduler_executed_today_blocks_approval(self, temp_db,
                                                      monkeypatch):
        _fixed_now(monkeypatch)
        monkeypatch.setattr(fetch_fund, "calc_purchase_fee", _fee(0.0))
        plan_id = _make_plan()
        created = _create(_tx_principal(), _params(plan_id))
        db.update_auto_invest_plan(plan_id, last_run="2026-01-05")
        result = _approve(created.data["proposal_id"])
        assert result.http_status == 409
        assert result.code == "already_executed"
        assert _transactions() == []

    def test_purchasable_changed_before_approval_conflicts(
            self, temp_db, monkeypatch):
        _fixed_now(monkeypatch)
        monkeypatch.setattr(fetch_fund, "calc_purchase_fee", _fee(0.0))
        plan_id = _make_plan()
        created = _create(_tx_principal(), _params(plan_id))
        db.update_fund_purchase_status(FUND_CODE, "暂停申购", 0, 0)
        result = _approve(created.data["proposal_id"])
        assert result.http_status == 409
        assert result.code == "purchasable_changed"
        assert result.data["purchasable_reason"] == "suspended"
        assert _transactions() == []

    def test_backdated_execution_does_not_rollback_last_run(
            self, temp_db, monkeypatch):
        _fixed_now(monkeypatch, day=10)
        monkeypatch.setattr(fetch_fund, "calc_purchase_fee", _fee(0.0))
        plan_id = _make_plan(last_run="2026-01-09")
        created = _create(
            _tx_principal(), _params(plan_id, trade_date="2026-01-08"))
        result = _approve(created.data["proposal_id"])
        assert result.ok
        plan = _plan(plan_id)
        assert plan["last_run"] == "2026-01-09"   # 取 max，不回退
        assert plan["next_run"] == "2026-01-12"   # 不重算
        assert _transactions()[0]["date"] == "2026-01-08"

    def test_duplicate_backdated_proposal_rejected(self, temp_db, monkeypatch):
        _fixed_now(monkeypatch, day=10)
        monkeypatch.setattr(fetch_fund, "calc_purchase_fee", _fee(0.0))
        plan_id = _make_plan(last_run="2026-01-09")
        first = _create(
            _tx_principal(),
            _params(plan_id, trade_date="2026-01-08"), key=KEY_A)
        assert _approve(first.data["proposal_id"]).ok
        # 第二个补记同一交易日：创建期即拒绝。
        second = _create(
            _tx_principal(),
            _params(plan_id, trade_date="2026-01-08"), key=KEY_B)
        assert second.http_status == 409
        assert second.code == "already_executed"
        assert len(_transactions()) == 1

    def test_second_pending_backdated_proposal_conflicts_on_approval(
            self, temp_db, monkeypatch):
        _fixed_now(monkeypatch, day=10)
        monkeypatch.setattr(fetch_fund, "calc_purchase_fee", _fee(0.0))
        plan_id = _make_plan(last_run="2026-01-09")
        first = _create(
            _tx_principal(),
            _params(plan_id, trade_date="2026-01-08"), key=KEY_A)
        second = _create(
            _tx_principal(),
            _params(plan_id, trade_date="2026-01-08"), key=KEY_B)
        assert first.ok and second.ok
        assert _approve(first.data["proposal_id"]).ok
        result = _approve(second.data["proposal_id"])
        assert result.http_status == 409
        assert result.code == "already_executed"
        assert len(_transactions()) == 1

    def test_disabled_plan_still_manually_executable(self, temp_db,
                                                      monkeypatch):
        _fixed_now(monkeypatch)
        monkeypatch.setattr(fetch_fund, "calc_purchase_fee", _fee(0.0))
        plan_id = _make_plan(enabled=0)
        created = _create(_tx_principal(), _params(plan_id))
        assert created.ok
        assert any("停用" in w for w in created.data["summary"]["warnings"])
        assert _approve(created.data["proposal_id"]).ok
        assert len(_transactions()) == 1

    def test_reapprove_is_not_pending(self, temp_db, monkeypatch):
        _fixed_now(monkeypatch)
        monkeypatch.setattr(fetch_fund, "calc_purchase_fee", _fee(0.0))
        plan_id = _make_plan()
        pid = _create(_tx_principal(), _params(plan_id)).data["proposal_id"]
        assert _approve(pid).ok
        again = _approve(pid)
        assert again.http_status == 409
        assert again.code == "not_pending"
        assert len(_transactions()) == 1


# ---------------------------------------------------------------------------
# HTTP 门控
# ---------------------------------------------------------------------------

class TestHttpGating:
    def test_transactions_propose_can_create(self, client, temp_db,
                                             monkeypatch):
        _fixed_now(monkeypatch)
        monkeypatch.setattr(fetch_fund, "calc_purchase_fee", _fee(0.0))
        plan_id = _make_plan()
        plain, _info = agent_tokens.issue_token(
            "agent", [agent_tokens.SCOPE_TRANSACTIONS_PROPOSE])
        headers = {"Authorization": f"Bearer {plain}",
                   "Idempotency-Key": KEY_A}
        resp = client.post(PROPOSALS_PATH, headers=headers, json={
            "operation_type": "execute_plan", "params": _params(plan_id)})
        assert resp.status_code == 201, resp.text
        assert resp.json()["data"]["summary"]["operation_type"] == \
            "execute_plan"

    def test_plans_propose_cannot_create_execute_plan(self, client, temp_db):
        plan_id = _make_plan()
        plain, _info = agent_tokens.issue_token(
            "agent", [agent_tokens.SCOPE_PLANS_PROPOSE])
        headers = {"Authorization": f"Bearer {plain}",
                   "Idempotency-Key": KEY_A}
        resp = client.post(PROPOSALS_PATH, headers=headers, json={
            "operation_type": "execute_plan",
            "params": {"plan_id": plan_id, "expected_digest": "0" * 64}})
        assert resp.status_code == 403

    def test_capabilities_lists_execute_plan(self, client, temp_db):
        plain, _info = agent_tokens.issue_token(
            "agent", [agent_tokens.SCOPE_TRANSACTIONS_PROPOSE])
        headers = {"Authorization": f"Bearer {plain}"}
        resp = client.get(CAPABILITIES_PATH, headers=headers)
        assert resp.status_code == 200, resp.text
        # 能力发现列出提案工具即说明该 scope 可见；具体 operation 由工具参数承载。
        names = {tool["name"] for tool in resp.json()["data"]["tools"]}
        assert "create_operation_proposal" in names
