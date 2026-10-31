"""F3 预检测试：CSV/截图预检与对账预检（只读，不写账本）。

覆盖 scope/写开关门控、items 与 csv 两条解析路径、基金识别、字段校验、
重复检测、对账差额与 shares 校验。
"""
from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory

import pytest
from fastapi.testclient import TestClient

from zfundpilot import agent_tokens, api, config, db
from zfundpilot.analysis import clear_analysis_cache
from zfundpilot.models import Fund

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
    return TestClient(api.app)


def _agent_headers(scopes: list[str]) -> dict[str, str]:
    plaintext, _ = agent_tokens.issue_token("test-agent", scopes)
    return {"Authorization": f"Bearer {plaintext}"}


def _propose_headers() -> dict[str, str]:
    return _agent_headers([agent_tokens.SCOPE_TRANSACTIONS_PROPOSE])


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

    def test_csv_too_large(self, client):
        big = "fund_code,action,date\n" + "005827,buy,2026-01-02\n" * 200000
        r = _precheck_tx(client, {"format": "csv", "csv_text": big})
        assert r.status_code == 422
        assert r.json()["detail"]["code"] == "csv_too_large"

    def test_csv_not_string(self, client):
        r = _precheck_tx(client, {"format": "csv", "csv_text": 123})
        assert r.status_code == 422


# ---------------------------------------------------------------------------
# precheck_reconciliation
# ---------------------------------------------------------------------------

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

    def test_reconcile_item_not_object(self, client):
        r = _precheck_rec(client, {"holdings": ["str"]})
        data = r.json()["data"]
        assert len(data["fund_resolution_errors"]) == 1
