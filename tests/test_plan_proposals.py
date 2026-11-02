"""F5 定投计划维护提案测试：创建/修改/启停/删除校验、审批执行与 HTTP 门控。

覆盖：
- create_plan：完整配置校验、禁用字段硬拒、基金收录、重复 warning、幂等。
- update_plan：patch 合并、版本前置、目标缺失/失配、交叉规则。
- toggle_plan：enable 布尔、版本前置、同状态拒绝、启用逾期补投提示。
- delete_plan：版本前置、目标缺失/失配。
- HTTP 门控：plans:propose 授权、跨域精确复核、双 scope 只读端点、写总闸、
  能力发现。
- 审批执行：create_plan 写入（默认停用）、toggle 冲突回滚。
"""
from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory

import pytest
from fastapi.testclient import TestClient

from zfundpilot import agent_tokens, api, auto_invest, config, db
from zfundpilot import proposal_service as svc
from zfundpilot.analysis import clear_analysis_cache
from zfundpilot.models import Fund

PROPOSALS_PATH = "/api/agent/tools/proposals"
CAPABILITIES_PATH = "/api/agent/tools/capabilities"
KEY_A = "plan-key-aaaaaaaaaaaa"
KEY_B = "plan-key-bbbbbbbbbbbb"


@pytest.fixture
def temp_db(monkeypatch):
    with TemporaryDirectory() as d:
        monkeypatch.setattr(config, "DB_PATH", str(Path(d) / "test.db"))
        monkeypatch.setattr(config, "AUTH_ENABLED", True)
        monkeypatch.setattr(config, "AUTH_SECRET", "test-secret")
        monkeypatch.setattr(config, "AUTH_USERNAME", "admin")
        monkeypatch.setattr(config, "AGENT_WRITE_ENABLED", True)
        # 交易日历缓存跨测试残留会让空库误判；每个 temp_db 重置。
        db._trade_cal_cache = None
        db._trade_cal_max = None
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


def _plans_principal() -> svc.Principal:
    return _principal(agent_tokens.SCOPE_PLANS_PROPOSE)


def _create_plan(principal: svc.Principal, params: dict, *,
                 key: str = KEY_A) -> svc.ProposalResult:
    return svc.create_proposal(
        principal, operation_type=svc.OPERATION_CREATE_PLAN,
        params=params, idempotency_key=key)


def _make_existing_plan(*, fund_code: str = "005827", amount: float = 500.0,
                        cadence: str = "week", day_of_week: int = 0,
                        day_of_month: int | None = None,
                        channel: str = "支付宝", note: str = "定投",
                        enabled: int = 1) -> int:
    pid = db.add_auto_invest_plan(
        fund_code=fund_code, amount=amount, cadence=cadence,
        day_of_week=day_of_week, day_of_month=day_of_month,
        channel=channel, note=note, next_run="2026-01-05")
    if enabled == 0:
        db.update_auto_invest_plan(pid, enabled=0)
    return pid


def _digest(plan_id: int) -> str:
    return auto_invest.plan_row_digest(db.get_auto_invest_plan(plan_id))


def _audit_actions() -> list[str]:
    return [row["action"] for row in db.fetch_audit_logs(200)]


WEEKLY = {
    "fund_code": "005827", "amount": 500.0, "cadence": "week",
    "day_of_week": 0, "channel": "支付宝", "note": "工资定投",
}
MONTHLY = {
    "fund_code": "161725", "amount": 1000.0, "cadence": "month",
    "day_of_month": 15, "channel": "天天基金", "note": "月定投",
}
DAILY = {
    "fund_code": "005827", "amount": 100.0, "cadence": "daily",
    "channel": "", "note": "定投",
}


# ---------------------------------------------------------------------------
# create_plan
# ---------------------------------------------------------------------------

class TestCreatePlan:
    def test_creates_pending_disabled_without_writing_plans(self, temp_db):
        result = _create_plan(_plans_principal(), WEEKLY)
        assert result.http_status == 201
        assert result.code == "created"
        summary = result.data["summary"]
        assert summary["operation_type"] == "create_plan"
        assert summary["fund_code"] == "005827"
        assert summary["amount"] == 500.0
        assert summary["cadence"] == "week"
        assert summary["schedule"]  # 排期标签
        assert summary["enabled"] is False
        assert summary["next_run"]  # 预览下次执行
        assert "scheduler_hint" in summary
        # 不写 plans / transactions 表
        assert db.get_auto_invest_plans() == []
        assert db.get_transactions_desc() == []
        assert "proposal_created" in _audit_actions()

    def test_summary_schedule_label_weekly(self, temp_db):
        result = _create_plan(_plans_principal(), WEEKLY)
        assert result.data["summary"]["schedule"] == "每周一"

    def test_summary_schedule_label_monthly(self, temp_db):
        result = _create_plan(_plans_principal(), MONTHLY)
        assert result.data["summary"]["schedule"] == "每月15日"

    @pytest.mark.parametrize("field", ["enabled", "next_run", "last_run",
                                       "last_tx_id"])
    def test_rejects_forbidden_field(self, temp_db, field):
        with pytest.raises(svc.ProposalValidationError) as exc_info:
            _create_plan(_plans_principal(), {**WEEKLY, field: "x"})
        assert exc_info.value.field == field

    def test_rejects_unregistered_fund(self, temp_db):
        result = _create_plan(
            _plans_principal(), {**WEEKLY, "fund_code": "999999"})
        assert result.http_status == 409
        assert result.code == "fund_not_registered"
        assert result.data["fund_code"] == "999999"

    def test_rejects_invalid_cadence(self, temp_db):
        with pytest.raises(svc.ProposalValidationError) as exc_info:
            _create_plan(_plans_principal(), {**WEEKLY, "cadence": "hourly"})
        assert exc_info.value.field == "cadence"

    def test_rejects_week_without_day_of_week(self, temp_db):
        bad = {**WEEKLY, "day_of_week": None}
        with pytest.raises(svc.ProposalValidationError) as exc_info:
            _create_plan(_plans_principal(), bad)
        assert exc_info.value.field == "day_of_week"

    def test_rejects_week_with_day_of_month(self, temp_db):
        bad = {**WEEKLY, "day_of_month": 15}
        with pytest.raises(svc.ProposalValidationError) as exc_info:
            _create_plan(_plans_principal(), bad)
        assert exc_info.value.field == "day_of_month"

    def test_rejects_daily_with_day_of_week(self, temp_db):
        bad = {**DAILY, "day_of_week": 2}
        with pytest.raises(svc.ProposalValidationError) as exc_info:
            _create_plan(_plans_principal(), bad)
        assert exc_info.value.field == "day_of_week"

    def test_rejects_unknown_field(self, temp_db):
        with pytest.raises(svc.ProposalValidationError):
            _create_plan(_plans_principal(), {**WEEKLY, "extra": 1})

    def test_warns_on_duplicate_existing_plan(self, temp_db):
        _make_existing_plan(fund_code="005827", amount=500.0,
                            cadence="week", day_of_week=0,
                            channel="支付宝")
        result = _create_plan(_plans_principal(), WEEKLY)
        assert result.http_status == 201
        warnings = result.data["summary"]["warnings"]
        assert any("相同配置" in w for w in warnings)

    def test_idempotent_replay(self, temp_db):
        principal = _plans_principal()
        first = _create_plan(principal, WEEKLY)
        second = _create_plan(principal, WEEKLY)
        assert second.replayed is True
        assert second.data["proposal_id"] == first.data["proposal_id"]


# ---------------------------------------------------------------------------
# update_plan
# ---------------------------------------------------------------------------

class TestUpdatePlan:
    def test_update_partial_patch_validates(self, temp_db):
        pid = _make_existing_plan()
        result = svc.create_proposal(
            _plans_principal(), operation_type=svc.OPERATION_UPDATE_PLAN,
            params={"plan_id": pid, "expected_digest": _digest(pid),
                    "amount": 800.0},
            idempotency_key=KEY_A)
        assert result.http_status == 201
        summary = result.data["summary"]
        assert summary["plan_id"] == pid
        assert "amount" in summary["changed_fields"]
        assert summary["after"]["amount"] == 800.0

    def test_update_requires_plan_id_and_digest(self, temp_db):
        with pytest.raises(svc.ProposalValidationError) as exc_info:
            svc.create_proposal(
                _plans_principal(), operation_type=svc.OPERATION_UPDATE_PLAN,
                params={"amount": 800.0}, idempotency_key=KEY_A)
        assert exc_info.value.field == "plan_id"

    def test_update_rejects_unknown_field(self, temp_db):
        pid = _make_existing_plan()
        with pytest.raises(svc.ProposalValidationError):
            svc.create_proposal(
                _plans_principal(), operation_type=svc.OPERATION_UPDATE_PLAN,
                params={"plan_id": pid, "expected_digest": _digest(pid),
                        "bogus": 1},
                idempotency_key=KEY_A)

    def test_update_rejects_when_target_missing(self, temp_db):
        result = svc.create_proposal(
            _plans_principal(), operation_type=svc.OPERATION_UPDATE_PLAN,
            params={"plan_id": 999999, "expected_digest": "a" * 64,
                    "amount": 800.0},
            idempotency_key=KEY_A)
        assert result.http_status == 404
        assert result.code == "target_not_found"
        assert result.data["plan_id"] == 999999

    def test_update_rejects_when_digest_mismatch(self, temp_db):
        pid = _make_existing_plan()
        result = svc.create_proposal(
            _plans_principal(), operation_type=svc.OPERATION_UPDATE_PLAN,
            params={"plan_id": pid, "expected_digest": "0" * 64,
                    "amount": 800.0},
            idempotency_key=KEY_A)
        assert result.http_status == 409
        assert result.code == "target_changed"
        assert result.data["plan_id"] == pid

    def test_update_merge_validates_cross_rules(self, temp_db):
        # 原为 week+day_of_week=0；patch 改 cadence=month、补 day_of_month，
        # 但未清 day_of_week → 合并后 month 频率仍带 day_of_week，应拒绝。
        pid = _make_existing_plan()
        with pytest.raises(svc.ProposalValidationError) as exc_info:
            svc.create_proposal(
                _plans_principal(), operation_type=svc.OPERATION_UPDATE_PLAN,
                params={"plan_id": pid, "expected_digest": _digest(pid),
                        "cadence": "month", "day_of_month": 15},
                idempotency_key=KEY_A)
        assert exc_info.value.field == "day_of_week"

    def test_update_can_clear_day_field_with_null(self, temp_db):
        pid = _make_existing_plan()
        result = svc.create_proposal(
            _plans_principal(), operation_type=svc.OPERATION_UPDATE_PLAN,
            params={"plan_id": pid, "expected_digest": _digest(pid),
                    "cadence": "month", "day_of_week": None,
                    "day_of_month": 15},
            idempotency_key=KEY_A)
        assert result.http_status == 201
        after = result.data["summary"]["after"]
        assert after["day_of_week"] is None
        assert after["day_of_month"] == 15

    def test_update_no_patch_fields_rejected(self, temp_db):
        pid = _make_existing_plan()
        with pytest.raises(svc.ProposalValidationError) as exc_info:
            svc.create_proposal(
                _plans_principal(), operation_type=svc.OPERATION_UPDATE_PLAN,
                params={"plan_id": pid, "expected_digest": _digest(pid)},
                idempotency_key=KEY_A)
        assert exc_info.value.field == "params"


# ---------------------------------------------------------------------------
# toggle_plan
# ---------------------------------------------------------------------------

class TestTogglePlan:
    def test_toggle_requires_enable_bool(self, temp_db):
        pid = _make_existing_plan()
        with pytest.raises(svc.ProposalValidationError) as exc_info:
            svc.create_proposal(
                _plans_principal(), operation_type=svc.OPERATION_TOGGLE_PLAN,
                params={"plan_id": pid, "expected_digest": _digest(pid)},
                idempotency_key=KEY_A)
        assert exc_info.value.field == "enable"

    def test_toggle_rejects_non_bool_enable(self, temp_db):
        pid = _make_existing_plan()
        with pytest.raises(svc.ProposalValidationError) as exc_info:
            svc.create_proposal(
                _plans_principal(), operation_type=svc.OPERATION_TOGGLE_PLAN,
                params={"plan_id": pid, "expected_digest": _digest(pid),
                        "enable": "yes"},
                idempotency_key=KEY_A)
        assert exc_info.value.field == "enable"

    def test_toggle_rejects_when_target_missing(self, temp_db):
        result = svc.create_proposal(
            _plans_principal(), operation_type=svc.OPERATION_TOGGLE_PLAN,
            params={"plan_id": 999999, "expected_digest": "a" * 64,
                    "enable": False},
            idempotency_key=KEY_A)
        assert result.http_status == 404
        assert result.code == "target_not_found"

    def test_toggle_rejects_when_digest_mismatch(self, temp_db):
        pid = _make_existing_plan()
        result = svc.create_proposal(
            _plans_principal(), operation_type=svc.OPERATION_TOGGLE_PLAN,
            params={"plan_id": pid, "expected_digest": "0" * 64,
                    "enable": False},
            idempotency_key=KEY_A)
        assert result.http_status == 409
        assert result.code == "target_changed"

    def test_toggle_rejects_same_state(self, temp_db):
        # 默认创建的 plan 已 enabled=1；再提案 enable=True 应拒绝。
        pid = _make_existing_plan()
        with pytest.raises(svc.ProposalValidationError) as exc_info:
            svc.create_proposal(
                _plans_principal(), operation_type=svc.OPERATION_TOGGLE_PLAN,
                params={"plan_id": pid, "expected_digest": _digest(pid),
                        "enable": True},
                idempotency_key=KEY_A)
        assert exc_info.value.field == "enable"

    def test_toggle_enable_warns_backfill_when_overdue(self, temp_db):
        pid = _make_existing_plan(enabled=0)
        # next_run 留在创建时的 2026-01-05；置为更早以稳定触发补投提示。
        db.update_auto_invest_plan(pid, next_run="2000-01-03")
        result = svc.create_proposal(
            _plans_principal(), operation_type=svc.OPERATION_TOGGLE_PLAN,
            params={"plan_id": pid, "expected_digest": _digest(pid),
                    "enable": True},
            idempotency_key=KEY_A)
        assert result.http_status == 201
        hint = result.data["summary"]["scheduler_hint"]
        assert "补投" in hint


# ---------------------------------------------------------------------------
# delete_plan
# ---------------------------------------------------------------------------

class TestDeletePlan:
    def test_delete_requires_plan_id_and_digest(self, temp_db):
        with pytest.raises(svc.ProposalValidationError) as exc_info:
            svc.create_proposal(
                _plans_principal(), operation_type=svc.OPERATION_DELETE_PLAN,
                params={}, idempotency_key=KEY_A)
        assert exc_info.value.field == "plan_id"

    def test_delete_rejects_when_target_missing(self, temp_db):
        result = svc.create_proposal(
            _plans_principal(), operation_type=svc.OPERATION_DELETE_PLAN,
            params={"plan_id": 999999, "expected_digest": "a" * 64},
            idempotency_key=KEY_A)
        assert result.http_status == 404
        assert result.code == "target_not_found"

    def test_delete_rejects_when_digest_mismatch(self, temp_db):
        pid = _make_existing_plan()
        result = svc.create_proposal(
            _plans_principal(), operation_type=svc.OPERATION_DELETE_PLAN,
            params={"plan_id": pid, "expected_digest": "0" * 64},
            idempotency_key=KEY_A)
        assert result.http_status == 409
        assert result.code == "target_changed"


# ---------------------------------------------------------------------------
# HTTP 门控与错误形状
# ---------------------------------------------------------------------------

def _headers(scopes: list[str], *, key: str = "http-plan-key-0123456789"
             ) -> dict[str, str]:
    plaintext, _ = agent_tokens.issue_token("http-agent", scopes)
    return {"Authorization": f"Bearer {plaintext}",
            "Idempotency-Key": key}


class TestHttp:
    def test_requires_plans_propose_scope(self, client):
        headers = _headers([agent_tokens.SCOPE_PLANS_READ])
        r = client.post(PROPOSALS_PATH, headers=headers, json={
            "operation_type": "create_plan", "params": WEEKLY})
        assert r.status_code == 403

    def test_transactions_propose_rejected_for_plan_op(self, client):
        # 双 scope 依赖放行进入，但按 operation_type 精确复核仍 403。
        headers = _headers([agent_tokens.SCOPE_TRANSACTIONS_PROPOSE])
        r = client.post(PROPOSALS_PATH, headers=headers, json={
            "operation_type": "create_plan", "params": WEEKLY})
        assert r.status_code == 403

    def test_plans_propose_rejected_for_ledger_op(self, client):
        headers = _headers([agent_tokens.SCOPE_PLANS_PROPOSE])
        r = client.post(PROPOSALS_PATH, headers=headers, json={
            "operation_type": "add_transaction",
            "params": {"fund_code": "005827", "action": "buy",
                       "date": "2026-01-02", "amount": 1000.0,
                       "channel": "支付宝"}})
        assert r.status_code == 403

    def test_list_get_cancel_work_with_either_scope(self, client):
        # list/get/cancel 是双域工具：任一 scope 均可操作**自己**创建的提案。
        # 提案按 principal 隔离，故必须用同一 token 创建后再读取。
        cases = [
            ([agent_tokens.SCOPE_TRANSACTIONS_PROPOSE], "add_transaction",
             {"fund_code": "005827", "action": "buy", "date": "2026-01-02",
              "amount": 1000.0, "shares": 100.0, "nav": 10.0, "fee": 1.0,
              "channel": "支付宝"},
             "list-key-ledger-0123456789"),
            ([agent_tokens.SCOPE_PLANS_PROPOSE], "create_plan", WEEKLY,
             "list-key-plan-0123456789"),
        ]
        for scopes, op_type, params, key in cases:
            headers = _headers(list(scopes), key=key)
            r = client.post(PROPOSALS_PATH, headers=headers, json={
                "operation_type": op_type, "params": params})
            assert r.status_code == 201, r.text
            pid = r.json()["data"]["proposal_id"]
            r = client.get("/api/agent/tools/proposals", headers=headers)
            assert r.status_code == 200
            assert [p["proposal_id"] for p in r.json()["data"]["items"]] == [pid]
            r = client.get(f"{PROPOSALS_PATH}/{pid}", headers=headers)
            assert r.status_code == 200
            assert r.json()["data"]["proposal_id"] == pid
            r = client.delete(f"{PROPOSALS_PATH}/{pid}", headers=headers)
            assert r.status_code == 200
            assert r.json()["data"]["status"] == svc.STATUS_CANCELLED

    def test_write_disabled_blocks(self, client, monkeypatch):
        monkeypatch.setattr(config, "AGENT_WRITE_ENABLED", False)
        headers = _headers([agent_tokens.SCOPE_PLANS_PROPOSE])
        r = client.post(PROPOSALS_PATH, headers=headers, json={
            "operation_type": "create_plan", "params": WEEKLY})
        assert r.status_code == 403
        assert r.json()["detail"]["code"] == "write_disabled"

    def test_capabilities_lists_plan_tools_with_plans_propose(self, client):
        headers = _headers([agent_tokens.SCOPE_PLANS_PROPOSE])
        r = client.get(CAPABILITIES_PATH, headers=headers)
        assert r.status_code == 200
        tools = {t["name"] for t in r.json()["data"]["tools"]}
        assert "create_operation_proposal" in tools
        assert "list_auto_invest_plans" not in tools  # 需 plans:read

    def test_list_plans_includes_row_digest(self, client):
        _make_existing_plan()
        headers = _headers([agent_tokens.SCOPE_PLANS_READ])
        r = client.get("/api/agent/tools/auto-invest-plans", headers=headers)
        assert r.status_code == 200
        plans = r.json()["data"]["plans"]
        assert len(plans) == 1
        assert len(plans[0]["row_digest"]) == 64


# ---------------------------------------------------------------------------
# 审批执行
# ---------------------------------------------------------------------------

class TestApprove:
    def test_approve_create_writes_plan_disabled(self, temp_db):
        pid = _create_plan(_plans_principal(), WEEKLY).data["proposal_id"]
        result = svc.approve_proposal(pid, reviewer="admin")
        assert result.http_status == 200
        assert result.code == "succeeded"
        execution = result.data["execution_result"]
        assert execution["ok"] is True
        assert execution["enabled"] is False
        assert execution["plan_id"] > 0
        plans = db.get_auto_invest_plans()
        assert len(plans) == 1
        assert plans[0]["enabled"] == 0
        # 计划操作永不写 transactions
        assert db.get_transactions_desc() == []
        assert "auto_invest_plan_create" in _audit_actions()
        assert "proposal_approved" in _audit_actions()

    def test_approve_toggle_conflict_when_plan_changed(self, temp_db):
        pid = _make_existing_plan()  # enabled=1
        digest = _digest(pid)
        # 提案：停用
        proposal = svc.create_proposal(
            _plans_principal(), operation_type=svc.OPERATION_TOGGLE_PLAN,
            params={"plan_id": pid, "expected_digest": digest,
                    "enable": False},
            idempotency_key=KEY_A)
        assert proposal.ok
        # 审批前人为改动计划（改金额 → 配置摘要变化）
        db.update_auto_invest_plan(pid, amount=999.0)
        result = svc.approve_proposal(
            proposal.data["proposal_id"], reviewer="admin")
        assert result.http_status == 409
        assert result.code == "target_changed"
        # 计划未被翻转
        assert db.get_auto_invest_plan(pid)["enabled"] == 1
        assert svc.get_proposal_admin(
            proposal.data["proposal_id"]).data["status"] == svc.STATUS_CONFLICT

    def test_approve_delete_removes_plan(self, temp_db):
        pid = _make_existing_plan()
        proposal = svc.create_proposal(
            _plans_principal(), operation_type=svc.OPERATION_DELETE_PLAN,
            params={"plan_id": pid, "expected_digest": _digest(pid)},
            idempotency_key=KEY_A)
        result = svc.approve_proposal(
            proposal.data["proposal_id"], reviewer="admin")
        assert result.http_status == 200
        assert db.get_auto_invest_plan(pid) is None
        assert "auto_invest_plan_delete" in _audit_actions()
