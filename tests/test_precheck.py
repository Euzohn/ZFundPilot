"""F3 预检测试：CSV/截图预检与对账预检（只读，不写账本）。

覆盖 scope/写开关门控、items 与 csv 两条解析路径、基金识别、字段校验、
重复检测、对账差额与 shares 校验。
"""
from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory

import pytest
from fastapi.testclient import TestClient

from zfundpilot import (
    agent_tokens,
    api,
    config,
    db,
    proposal_service,
    transaction_service,
)
from zfundpilot.analysis import clear_analysis_cache
from zfundpilot.models import Fund, Transaction

PRECHECK_TX = "/api/agent/tools/precheck/transactions"
PRECHECK_REC = "/api/agent/tools/precheck/reconciliation"

BUY_ITEM = {
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
        db.init_db()
        db.upsert_fund(Fund("005827", "易方达蓝筹精选", "混合型", "消费"))
        db.upsert_fund(Fund("161725", "招商中证白酒", "指数型", "消费"))
        clear_analysis_cache()
        yield
        clear_analysis_cache()


@pytest.fixture
def client(temp_db, monkeypatch):
    monkeypatch.setattr(config, "AUTH_ENABLED", True)
    monkeypatch.setattr(config, "AUTH_SECRET", "test-secret")
    monkeypatch.setattr(config, "AUTH_USERNAME", "admin")
    monkeypatch.setattr(config, "AGENT_WRITE_ENABLED", True)
    # 清空两套限流日志，避免同类用例密集调用 precheck 端点跨用例累积触发 429
    monkeypatch.setattr(api, "_REQ_LOGS", {})
    monkeypatch.setattr(api, "_AGENT_REQ_LOGS", {})
    return TestClient(api.app)


def _agent_headers(scopes: list[str]) -> dict[str, str]:
    plaintext, _ = agent_tokens.issue_token("test-agent", scopes)
    return {"Authorization": f"Bearer {plaintext}"}


def _propose_headers() -> dict[str, str]:
    return _agent_headers([agent_tokens.SCOPE_TRANSACTIONS_PROPOSE])


def _propose_token() -> tuple[dict[str, str], proposal_service.Principal]:
    """签发 token 并返回其请求头与服务层 principal（用于造 pending 提案）。"""
    plaintext, meta = agent_tokens.issue_token(
        "test-agent", [agent_tokens.SCOPE_TRANSACTIONS_PROPOSE])
    principal = proposal_service.Principal(
        "agent_token", str(meta["id"]), f"agent:{meta['token_prefix']}")
    return {"Authorization": f"Bearer {plaintext}"}, principal


def _create_pending_proposal(
        principal: proposal_service.Principal, params: dict) -> int:
    result = proposal_service.create_proposal(
        principal, operation_type="add_transaction", params=params,
        idempotency_key="pending-key-0123456789abcdef")
    assert result.ok, result.message
    return int(result.data["proposal_id"])


def _precheck_tx(client, payload, headers=None):
    return client.post(
        PRECHECK_TX, headers=headers or _propose_headers(),
        json={"input": payload})


def _precheck_rec(client, payload, headers=None):
    return client.post(
        PRECHECK_REC, headers=headers or _propose_headers(),
        json={"input": payload})


# ---------------------------------------------------------------------------
# 门控：scope / 写开关
# ---------------------------------------------------------------------------

class TestPrecheckGate:
    def test_precheck_tx_requires_propose_scope(self, client):
        headers = _agent_headers([agent_tokens.SCOPE_TRANSACTIONS_READ])
        r = _precheck_tx(client, {"format": "items", "items": [BUY_ITEM]},
                         headers=headers)
        assert r.status_code == 403

    def test_precheck_rec_requires_propose_scope(self, client):
        headers = _agent_headers([agent_tokens.SCOPE_TRANSACTIONS_READ])
        r = _precheck_rec(client, {"holdings": []}, headers=headers)
        assert r.status_code == 403

    def test_precheck_tx_blocked_when_write_disabled(self, client, monkeypatch):
        monkeypatch.setattr(config, "AGENT_WRITE_ENABLED", False)
        r = _precheck_tx(client, {"format": "items", "items": [BUY_ITEM]})
        assert r.status_code == 403
        assert r.json()["detail"]["code"] == "write_disabled"

    def test_precheck_rec_blocked_when_write_disabled(self, client, monkeypatch):
        monkeypatch.setattr(config, "AGENT_WRITE_ENABLED", False)
        r = _precheck_rec(client, {"holdings": []})
        assert r.status_code == 403


# ---------------------------------------------------------------------------
# precheck_transactions — items 路径
# ---------------------------------------------------------------------------

class TestPrecheckTransactionsItems:
    def test_valid_buy(self, client):
        r = _precheck_tx(client, {"format": "items", "items": [BUY_ITEM]})
        assert r.status_code == 200
        data = r.json()["data"]
        assert data["total"] == 1
        assert data["valid"] == 1
        item = data["items"][0]
        assert item["status"] == "valid"
        assert item["proposal_ready"] is True
        assert item["fund_resolution"]["status"] == "verified"
        assert item["fund_resolution"]["resolved_code"] == "005827"

    def test_fund_not_registered(self, client):
        item = {**BUY_ITEM, "fund_code": "999999"}
        r = _precheck_tx(client, {"format": "items", "items": [item]})
        data = r.json()["data"]
        assert data["invalid"] == 1
        assert data["items"][0]["status"] == "invalid"
        assert data["items"][0]["fund_resolution"]["status"] == "none"

    def test_missing_date(self, client):
        item = {k: v for k, v in BUY_ITEM.items() if k != "date"}
        r = _precheck_tx(client, {"format": "items", "items": [item]})
        data = r.json()["data"]
        assert data["items"][0]["status"] == "invalid"
        issues = data["items"][0]["issues"]
        assert any(i["field"] == "date" for i in issues)

    def test_buy_without_amount_invalid(self, client):
        item = {k: v for k, v in BUY_ITEM.items()
                if k not in ("amount", "shares", "nav")}
        r = _precheck_tx(client, {"format": "items", "items": [item]})
        data = r.json()["data"]
        assert data["items"][0]["status"] == "invalid"

    def test_duplicate_in_ledger(self, client):
        # 先直接记一笔，再预检同样的条目
        direct_headers = _agent_headers([
            agent_tokens.SCOPE_TRANSACTIONS_CREATE,
            agent_tokens.SCOPE_TRANSACTIONS_PROPOSE,
        ])
        created = client.post(
            "/api/agent/tools/transactions",
            headers={**direct_headers, "Idempotency-Key": "dup-key-0123456789abcdef"},
            json=BUY_ITEM)
        assert created.status_code in (200, 201), created.text
        r = _precheck_tx(client, {"format": "items", "items": [BUY_ITEM]})
        data = r.json()["data"]
        assert data["duplicate"] == 1
        dup = data["items"][0]
        assert dup["status"] == "duplicate"
        assert dup["duplicate"]["kind"] == "ledger"
        assert dup["proposal_ready"] is False

    def test_missing_channel_and_fee_warnings(self, client):
        item = {k: v for k, v in BUY_ITEM.items()
                if k not in ("channel", "fee")}
        r = _precheck_tx(client, {"format": "items", "items": [item]})
        data = r.json()["data"]
        item0 = data["items"][0]
        assert item0["status"] == "valid"
        codes = {i["code"] for i in item0["issues"]}
        assert "missing_channel" in codes
        assert "missing_fee" in codes

    def test_explicit_zero_fee_not_warned(self, client):
        item = {**BUY_ITEM, "fee": 0}
        r = _precheck_tx(client, {"format": "items", "items": [item]})
        codes = {i["code"] for i in r.json()["data"]["items"][0]["issues"]}
        assert "missing_fee" not in codes

    def test_fund_name_exact_from_ledger(self, client):
        item = {k: v for k, v in BUY_ITEM.items() if k != "fund_code"}
        item["fund_name"] = "易方达蓝筹精选"
        r = _precheck_tx(client, {"format": "items", "items": [item]})
        data = r.json()["data"]
        item0 = data["items"][0]
        assert item0["status"] == "valid"
        assert item0["fund_resolution"]["status"] == "exact"
        assert item0["fund_resolution"]["resolved_code"] == "005827"
        assert item0["transaction"]["fund_code"] == "005827"

    def test_fund_name_ambiguous_from_ledger(self, client):
        db.upsert_fund(Fund("005828", "易方达蓝筹精选C", "混合型", "消费"))
        item = {k: v for k, v in BUY_ITEM.items() if k != "fund_code"}
        item["fund_name"] = "易方达蓝筹"
        r = _precheck_tx(client, {"format": "items", "items": [item]})
        data = r.json()["data"]
        item0 = data["items"][0]
        assert item0["status"] == "invalid"
        assert item0["fund_resolution"]["status"] == "multiple"
        assert item0["proposal_ready"] is False
        assert len(item0["fund_resolution"]["candidates"]) == 2

    def test_fund_name_not_found(self, client):
        item = {k: v for k, v in BUY_ITEM.items() if k != "fund_code"}
        item["fund_name"] = "不存在的基金"
        r = _precheck_tx(client, {"format": "items", "items": [item]})
        data = r.json()["data"]
        item0 = data["items"][0]
        assert item0["status"] == "invalid"
        assert item0["fund_resolution"]["status"] == "none"
        assert any(i["code"] == "no_match" for i in item0["issues"])

    def test_duplicate_matches_own_pending_proposal(self, client):
        headers, principal = _propose_token()
        proposal_id = _create_pending_proposal(principal, BUY_ITEM)
        r = _precheck_tx(client, {"format": "items", "items": [BUY_ITEM]},
                         headers=headers)
        data = r.json()["data"]
        dup = data["items"][0]
        assert dup["status"] == "duplicate"
        assert dup["duplicate"]["kind"] == "pending_proposal"
        assert dup["duplicate"]["own"] is True
        assert dup["duplicate"]["proposal_id"] == proposal_id
        assert dup["proposal_ready"] is False

    def test_duplicate_other_pending_proposal_hides_id(self, client):
        other = proposal_service.Principal(
            "agent_token", "999999", "agent:other")
        _create_pending_proposal(other, BUY_ITEM)
        r = _precheck_tx(client, {"format": "items", "items": [BUY_ITEM]})
        diff = r.json()["data"]["items"][0]
        assert diff["status"] == "duplicate"
        assert diff["duplicate"]["kind"] == "pending_proposal"
        assert diff["duplicate"]["own"] is False
        assert diff["duplicate"]["proposal_id"] is None
        assert diff["proposal_ready"] is False

    def test_precheck_does_not_write_ledger(self, client):
        with db.get_connection() as conn:
            before_tx = conn.execute(
                "SELECT COUNT(*) FROM transactions").fetchone()[0]
            before_pp = conn.execute(
                "SELECT COUNT(*) FROM operation_proposals").fetchone()[0]
            before_audit = conn.execute(
                "SELECT COUNT(*) FROM audit_log WHERE action=?",
                ("agent_precheck_transactions",)).fetchone()[0]
        r = _precheck_tx(client, {"format": "items", "items": [BUY_ITEM]})
        assert r.status_code == 200
        with db.get_connection() as conn:
            assert conn.execute(
                "SELECT COUNT(*) FROM transactions").fetchone()[0] == before_tx
            assert conn.execute(
                "SELECT COUNT(*) FROM operation_proposals").fetchone()[0] == before_pp
            assert conn.execute(
                "SELECT COUNT(*) FROM audit_log WHERE action=?",
                ("agent_precheck_transactions",)).fetchone()[0] == before_audit + 1

    def test_channel_hint_applied(self, client):
        item = {k: v for k, v in BUY_ITEM.items() if k != "channel"}
        r = _precheck_tx(client, {"format": "items", "items": [item],
                                  "channel_hint": "理财通"})
        data = r.json()["data"]
        tx = data["items"][0]["transaction"]
        assert tx["channel"] == "理财通"

    def test_too_many_items(self, client):
        items = [BUY_ITEM] * 201
        r = _precheck_tx(client, {"format": "items", "items": items})
        assert r.status_code == 422
        assert r.json()["detail"]["code"] == "too_many_items"

    def test_invalid_format(self, client):
        r = _precheck_tx(client, {"format": "xml", "items": []})
        assert r.status_code == 422

    def test_items_not_array(self, client):
        r = _precheck_tx(client, {"format": "items", "items": "not-a-list"})
        assert r.status_code == 422

    def test_item_not_object(self, client):
        r = _precheck_tx(client, {"format": "items", "items": ["str"]})
        data = r.json()["data"]
        assert data["items"][0]["status"] == "invalid"


# ---------------------------------------------------------------------------
# precheck_transactions — csv 路径
# ---------------------------------------------------------------------------

class TestPrecheckTransactionsCsv:
    CSV_OK = (
        "fund_code,action,date,amount,fee,channel\n"
        "005827,buy,2026-01-02,1000,1,支付宝\n"
        "161725,buy,2026-01-03,2000,1,理财通\n"
    )

    def test_csv_valid(self, client):
        r = _precheck_tx(client, {"format": "csv", "csv_text": self.CSV_OK})
        assert r.status_code == 200
        data = r.json()["data"]
        assert data["valid"] == 2
        assert data["items"][0]["fund_resolution"]["resolved_code"] == "005827"

    def test_csv_missing_columns(self, client):
        r = _precheck_tx(client, {"format": "csv",
                                  "csv_text": "foo,bar\n1,2\n"})
        data = r.json()["data"]
        assert len(data["parse_errors"]) >= 1

    def test_csv_too_large(self, client, monkeypatch):
        # 缩小阈值避免构造 5 MB 文本拖慢测试
        monkeypatch.setattr(transaction_service, "_MAX_CSV_BYTES", 64)
        r = _precheck_tx(client, {"format": "csv",
                                  "csv_text": self.CSV_OK})
        assert r.status_code == 422
        assert r.json()["detail"]["code"] == "csv_too_large"

    def test_csv_too_many_rows(self, client):
        rows = "005827,buy,2026-01-02,1000\n" * 201
        r = _precheck_tx(client, {
            "format": "csv",
            "csv_text": "fund_code,action,date,amount\n" + rows})
        assert r.status_code == 422
        assert r.json()["detail"]["code"] == "too_many_items"

    def test_csv_channel_hint(self, client):
        csv_text = ("fund_code,action,date,amount,fee\n"
                    "005827,buy,2026-01-02,1000,1\n")
        r = _precheck_tx(client, {"format": "csv", "csv_text": csv_text,
                                  "channel_hint": "理财通"})
        data = r.json()["data"]
        item0 = data["items"][0]
        assert item0["transaction"]["channel"] == "理财通"
        codes = {i["code"] for i in item0["issues"]}
        assert "missing_channel" not in codes

    def test_csv_fee_column_detected(self, client):
        r = _precheck_tx(client, {"format": "csv", "csv_text": self.CSV_OK})
        for item in r.json()["data"]["items"]:
            codes = {i["code"] for i in item["issues"]}
            assert "missing_fee" not in codes

    def test_csv_without_fee_column_warns(self, client):
        csv_text = ("fund_code,action,date,amount\n"
                    "005827,buy,2026-01-02,1000\n")
        r = _precheck_tx(client, {"format": "csv", "csv_text": csv_text})
        codes = {i["code"] for i in r.json()["data"]["items"][0]["issues"]}
        assert "missing_fee" in codes

    def test_csv_parse_error_line(self, client):
        csv_text = ("fund_code,action,date,amount\n"
                    "005827,,2026-01-02,1000\n")
        r = _precheck_tx(client, {"format": "csv", "csv_text": csv_text})
        errs = r.json()["data"]["parse_errors"]
        assert errs
        assert errs[0]["line"] == 2

    def test_csv_not_string(self, client):
        r = _precheck_tx(client, {"format": "csv", "csv_text": 123})
        assert r.status_code == 422


# ---------------------------------------------------------------------------
# precheck_reconciliation
# ---------------------------------------------------------------------------

def _record_holding(shares: float = 100.0, channel: str = "支付宝") -> None:
    """写入一笔买入，构造账本已有持仓。"""
    db.add_transaction(Transaction(
        fund_code="005827", action="buy", date="2026-01-02",
        amount=shares * 10.0, shares=shares, nav=10.0, channel=channel))
    clear_analysis_cache()


class TestPrecheckReconciliation:
    def test_reconcile_valid(self, client):
        # 账本里没持仓，截图给了 005827 → status new（截图新增）
        r = _precheck_rec(client, {"holdings": [
            {"fund_code": "005827", "shares": 1000.0}]})
        assert r.status_code == 200
        data = r.json()["data"]
        assert data["ok"] is True
        assert len(data["items"]) >= 1
        item = data["items"][0]
        assert item["fund_code"] == "005827"
        assert item["status"] in ("new", "buy")

    def test_reconcile_fund_not_registered(self, client):
        r = _precheck_rec(client, {"holdings": [
            {"fund_code": "999999", "shares": 1000.0}]})
        data = r.json()["data"]
        assert len(data["fund_resolution_errors"]) == 1
        err = data["fund_resolution_errors"][0]
        assert err["status"] == "none"

    def test_reconcile_invalid_shares(self, client):
        r = _precheck_rec(client, {"holdings": [
            {"fund_code": "005827", "shares": "abc"}]})
        data = r.json()["data"]
        errs = data["fund_resolution_errors"]
        assert any(e.get("reason") == "invalid_shares" for e in errs)

    def test_reconcile_negative_shares(self, client):
        r = _precheck_rec(client, {"holdings": [
            {"fund_code": "005827", "shares": -100.0}]})
        data = r.json()["data"]
        errs = data["fund_resolution_errors"]
        assert any(e.get("reason") == "invalid_shares" for e in errs)

    def test_reconcile_missing_shares(self, client):
        r = _precheck_rec(client, {"holdings": [
            {"fund_code": "005827"}]})
        data = r.json()["data"]
        errs = data["fund_resolution_errors"]
        assert any(e.get("reason") == "invalid_shares" for e in errs)

    def test_reconcile_too_many(self, client):
        holdings = [{"fund_code": "005827", "shares": 1.0}] * 101
        r = _precheck_rec(client, {"holdings": holdings})
        assert r.status_code == 422

    def test_reconcile_holdings_not_array(self, client):
        r = _precheck_rec(client, {"holdings": "nope"})
        assert r.status_code == 422

    def test_reconcile_channel_too_long(self, client):
        r = _precheck_rec(client, {"channel": "x" * 51, "holdings": []})
        assert r.status_code == 422
        assert r.json()["detail"]["field"] == "channel"

    def test_reconcile_maybe_sold_not_proposal_ready(self, client):
        _record_holding()
        r = _precheck_rec(client, {"channel": "支付宝", "holdings": []})
        data = r.json()["data"]
        maybe = [i for i in data["items"] if i["status"] == "maybe_sold"]
        assert len(maybe) == 1
        item = maybe[0]
        assert item["fund_code"] == "005827"
        assert item["proposal_ready"] is False
        assert any(i["code"] == "absent_from_input"
                   for i in item["issues"])
        assert item["fund_resolution"]["status"] == "verified"
        assert item["fund_resolution"]["resolved_code"] == "005827"
        assert item["fund_resolution"]["input"] == "005827"

    def test_reconcile_invalid_shares_suppresses_maybe_sold(self, client):
        _record_holding()
        r = _precheck_rec(client, {"channel": "支付宝", "holdings": [
            {"fund_code": "005827", "shares": "abc"}]})
        data = r.json()["data"]
        assert data["fund_resolution_errors"]
        assert not [i for i in data["items"]
                    if i["fund_code"] == "005827"
                    and i["status"] == "maybe_sold"]

    def test_reconcile_market_value_estimates_nav(self, client):
        r = _precheck_rec(client, {"holdings": [
            {"fund_code": "005827", "shares": 10.0,
             "market_value": 12.0}]})
        item = r.json()["data"]["items"][0]
        assert item["status"] == "new"
        assert item["proposal_ready"] is True
        assert item["suggested_tx"]["nav"] == pytest.approx(1.2)
        assert item["suggested_tx"]["amount"] == pytest.approx(12.0)
        assert item["fund_resolution"]["fund_name"] == "易方达蓝筹精选"
        assert item["issues"] == []

    def test_reconcile_audit_recorded(self, client):
        with db.get_connection() as conn:
            before = conn.execute(
                "SELECT COUNT(*) FROM audit_log WHERE action=?",
                ("agent_precheck_reconciliation",)).fetchone()[0]
        r = _precheck_rec(client, {"holdings": []})
        assert r.status_code == 200
        with db.get_connection() as conn:
            after = conn.execute(
                "SELECT COUNT(*) FROM audit_log WHERE action=?",
                ("agent_precheck_reconciliation",)).fetchone()[0]
        assert after == before + 1

    def test_reconcile_item_not_object(self, client):
        r = _precheck_rec(client, {"holdings": ["str"]})
        data = r.json()["data"]
        assert len(data["fund_resolution_errors"]) == 1
