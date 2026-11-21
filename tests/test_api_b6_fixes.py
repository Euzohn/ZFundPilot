"""B6 数据路径回归测试。

覆盖：TpSl 止损契约 HTTP 保存、confirm_import 透传 is_t1/conversion_id +
整批预校验 + 清空原子性、不存在交易 404、update_nav 失败复位 running、
审计时间范围规范化、_mark_duplicates 数值规整、lifespan T+1 标记与
调度器降级启动。
"""
from __future__ import annotations

import sqlite3
import time
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from zfundpilot import api, config, db
from zfundpilot.models import Fund, Transaction

BUY = {
    "fund_code": "005827", "action": "buy", "date": "2026-01-02",
    "amount": 1000.0, "shares": 100.0, "nav": 10.0, "fee": 1.0,
    "channel": "支付宝",
}


@pytest.fixture
def temp_db(monkeypatch):
    with TemporaryDirectory() as d:
        monkeypatch.setattr(config, "DB_PATH", str(Path(d) / "test.db"))
        monkeypatch.setattr(config, "AUTH_DATA_PATH", str(Path(d) / "auth.json"))
        db.init_db()
        db.upsert_fund(Fund("005827", "易方达蓝筹精选", "混合型", "消费"))
        yield


@pytest.fixture
def client(temp_db, monkeypatch):
    monkeypatch.setattr(config, "AUTH_ENABLED", False)
    monkeypatch.setattr(api, "_REQ_LOGS", {})
    monkeypatch.setattr(api, "_AGENT_REQ_LOGS", {})
    # 导入/更新路径可能触发联网净值抓取，统一 mock
    monkeypatch.setattr(api.fetch_fund, "update_fund_nav", MagicMock())
    return TestClient(api.app)


def _seed_tx(**overrides) -> int:
    data = {**BUY, **overrides}
    return db.add_transaction(Transaction(**data))


def _audit_actions() -> list[str]:
    return [r["action"] for r in db.fetch_audit_logs(500)]


# ---------------------------------------------------------------------------
# TpSl 止损契约（负值合法、正值 422）——HTTP 保存路径
# ---------------------------------------------------------------------------

class TestTpSlHttp:
    def test_save_negative_stop_loss(self, client):
        resp = client.put("/api/alerts/config",
                          json={"stop_loss": -0.15, "take_profit": 0.2})
        assert resp.status_code == 200, resp.text
        cfg = db.get_tp_sl_config()
        assert float(cfg["stop_loss"]) == -0.15
        assert float(cfg["take_profit"]) == 0.2

    def test_save_positive_stop_loss_rejected(self, client):
        resp = client.put("/api/alerts/config", json={"stop_loss": 0.15})
        assert resp.status_code == 422
        assert float(db.get_tp_sl_config()["stop_loss"]) == -0.15  # 默认未被改写


# ---------------------------------------------------------------------------
# confirm_import：透传、整批预校验、清空+导入原子性
# ---------------------------------------------------------------------------

class TestConfirmImport:
    def test_passthrough_is_t1_and_conversion_id(self, client):
        resp = client.post("/api/csv/import", json={
            "transactions": [{**BUY, "is_t1": True, "conversion_id": "conv-123"}],
            "fetch_meta": False,
        })
        assert resp.status_code == 200, resp.text
        assert resp.json()["imported"] == 1
        txs = db.get_transactions()
        assert len(txs) == 1
        assert txs[0].is_t1 is True
        assert txs[0].conversion_id == "conv-123"

    def test_invalid_row_422_with_index_no_write(self, client):
        old_id = _seed_tx()
        invalid = {"fund_code": "005827", "action": "buy", "date": "2026-01-03"}
        resp = client.post("/api/csv/import", json={
            "transactions": [BUY, invalid],
            "clear_existing": True, "fetch_meta": False,
        })
        assert resp.status_code == 422
        detail = resp.json()["detail"]
        assert detail["code"] == "invalid_transactions"
        assert detail["rows"][0]["index"] == 1
        # 预校验在清空之前：旧账本完好，无新写入
        txs = db.get_transactions()
        assert [t.id for t in txs] == [old_id]
        assert "clear_then_import" not in _audit_actions()

    def test_invalid_sell_without_shares_422(self, client):
        invalid = {"fund_code": "005827", "action": "sell", "date": "2026-01-03"}
        resp = client.post("/api/csv/import", json={
            "transactions": [invalid], "fetch_meta": False,
        })
        assert resp.status_code == 422
        assert db.get_transactions() == []

    def test_clear_then_import_success(self, client):
        _seed_tx(date="2025-01-01")
        resp = client.post("/api/csv/import", json={
            "transactions": [BUY], "clear_existing": True, "fetch_meta": False,
        })
        assert resp.status_code == 200
        txs = db.get_transactions()
        assert len(txs) == 1
        assert txs[0].date == "2026-01-02"
        assert "clear_then_import" in _audit_actions()

    def test_clear_then_import_rolls_back_on_failure(self, client, monkeypatch):
        old_id = _seed_tx(date="2025-01-01")
        real_insert = db.insert_transaction
        calls = {"n": 0}

        def flaky_insert(conn, tx):
            calls["n"] += 1
            if calls["n"] == 2:
                raise sqlite3.OperationalError("disk I/O error")
            return real_insert(conn, tx)

        monkeypatch.setattr(db, "insert_transaction", flaky_insert)
        resp = client.post("/api/csv/import", json={
            "transactions": [BUY, {**BUY, "date": "2026-01-03"}],
            "clear_existing": True, "fetch_meta": False,
        })
        assert resp.status_code == 500
        # 清空与导入同事务：中途失败整体回滚，旧账本不丢
        txs = db.get_transactions()
        assert [t.id for t in txs] == [old_id]
        assert "clear_then_import" not in _audit_actions()

    def test_append_import_rolls_back_on_failure(self, client, monkeypatch):
        old_id = _seed_tx(date="2025-01-01")

        def bad_insert(conn, tx):
            raise sqlite3.OperationalError("disk I/O error")

        monkeypatch.setattr(db, "insert_transaction", bad_insert)
        resp = client.post("/api/csv/import", json={
            "transactions": [BUY], "fetch_meta": False,
        })
        assert resp.status_code == 500
        assert [t.id for t in db.get_transactions()] == [old_id]


# ---------------------------------------------------------------------------
# 更新/删除不存在的交易 → 404
# ---------------------------------------------------------------------------

class TestTransactionNotFound:
    def test_update_missing_404(self, client):
        resp = client.put("/api/transactions/999999", json=BUY)
        assert resp.status_code == 404

    def test_delete_missing_404(self, client):
        resp = client.delete("/api/transactions/999999")
        assert resp.status_code == 404

    def test_update_existing_ok(self, client):
        tx_id = _seed_tx()
        resp = client.put(f"/api/transactions/{tx_id}",
                          json={**BUY, "amount": 2000.0})
        assert resp.status_code == 200
        assert resp.json()["ok"] is True
        assert db.get_transaction(tx_id).amount == 2000.0

    def test_delete_existing_ok(self, client):
        tx_id = _seed_tx()
        resp = client.delete(f"/api/transactions/{tx_id}")
        assert resp.status_code == 200
        assert db.get_transaction(tx_id) is None


# ---------------------------------------------------------------------------
# update_nav：running=True 后失败必须复位
# ---------------------------------------------------------------------------

@pytest.fixture
def nav_state(monkeypatch):
    state = {"running": False, "total": 0, "done": 0, "current": "",
             "phase": "", "results": [], "error": ""}
    monkeypatch.setattr(api, "_nav_update_state", state)
    return state


def _mock_nav_worker(monkeypatch):
    monkeypatch.setattr(api.analysis, "calculate_positions",
                        lambda *a, **kw: [SimpleNamespace(fund_code="005827", is_open=True)])
    monkeypatch.setattr(api.fetch_fund, "update_all_holdings_nav",
                        lambda **kw: [])
    monkeypatch.setattr(api.analysis, "backfill_transaction_navs", lambda: [])
    monkeypatch.setattr(api.scheduler, "refresh_fund_metadata",
                        lambda **kw: None)


def _wait_nav_done(state, timeout: float = 5.0) -> None:
    deadline = time.time() + timeout
    while state["running"] and time.time() < deadline:
        time.sleep(0.02)
    assert not state["running"]


class TestUpdateNavRollback:
    def test_positions_failure_resets_running(self, temp_db, nav_state, monkeypatch):
        monkeypatch.setattr(config, "AUTH_ENABLED", False)
        monkeypatch.setattr(api.analysis, "calculate_positions",
                            MagicMock(side_effect=RuntimeError("boom")))
        c = TestClient(api.app, raise_server_exceptions=False)
        resp = c.post("/api/nav/update")
        assert resp.status_code == 500
        assert nav_state["running"] is False
        # 复位后可再次启动（不被 409 卡死）
        _mock_nav_worker(monkeypatch)
        resp = c.post("/api/nav/update")
        assert resp.status_code == 200
        _wait_nav_done(nav_state)

    def test_thread_start_failure_resets_running(self, temp_db, nav_state, monkeypatch):
        monkeypatch.setattr(config, "AUTH_ENABLED", False)
        _mock_nav_worker(monkeypatch)

        class BrokenThread:
            def __init__(self, *a, **kw):
                pass

            def start(self):
                raise RuntimeError("can't start new thread")

        monkeypatch.setattr(api.threading, "Thread", BrokenThread)
        c = TestClient(api.app, raise_server_exceptions=False)
        resp = c.post("/api/nav/update")
        assert resp.status_code == 500
        assert nav_state["running"] is False

    def test_concurrent_still_409(self, temp_db, nav_state, monkeypatch):
        monkeypatch.setattr(config, "AUTH_ENABLED", False)
        nav_state["running"] = True
        c = TestClient(api.app)
        assert c.post("/api/nav/update").status_code == 409


# ---------------------------------------------------------------------------
# _mark_duplicates：不可信模型输出的防御性类型规整
# ---------------------------------------------------------------------------

class TestMarkDuplicates:
    @pytest.fixture(autouse=True)
    def _existing(self, monkeypatch):
        tx = Transaction(fund_code="005827", action="buy", date="2026-01-02",
                         amount=1000.0, shares=100.0)
        monkeypatch.setattr(db, "get_transactions", lambda **kw: [tx])

    def test_string_amount_matched(self):
        items = [{"fund_code": "005827", "action": "buy",
                  "date": "2026-01-02", "amount": "1000.00"}]
        api._mark_duplicates(items)
        assert items[0]["is_duplicate"] is True

    def test_string_shares_matched(self):
        items = [{"fund_code": "005827", "action": "buy",
                  "date": "2026-01-02", "shares": "100.0"}]
        api._mark_duplicates(items)
        assert items[0]["is_duplicate"] is True

    def test_non_numeric_amount_skipped(self):
        items = [{"fund_code": "005827", "action": "buy",
                  "date": "2026-01-02", "amount": "abc"}]
        api._mark_duplicates(items)
        assert items[0]["is_duplicate"] is False

    def test_nan_inf_amount_skipped(self):
        for value in ("NaN", "inf", float("nan"), float("inf")):
            items = [{"fund_code": "005827", "action": "buy",
                      "date": "2026-01-02", "amount": value}]
            api._mark_duplicates(items)
            assert items[0]["is_duplicate"] is False

    def test_unhashable_date_no_crash(self):
        items = [{"fund_code": "005827", "action": "buy",
                  "date": {"x": 1}, "amount": 1000}]
        api._mark_duplicates(items)
        assert items[0]["is_duplicate"] is False

    def test_non_string_action_no_crash(self):
        items = [{"fund_code": "005827", "action": None,
                  "date": "2026-01-02", "amount": 1000}]
        api._mark_duplicates(items)
        assert items[0]["is_duplicate"] is False


# ---------------------------------------------------------------------------
# lifespan：T+1 修复仅成功标记；调度器初始化失败降级不崩溃
# ---------------------------------------------------------------------------

@pytest.fixture
def lifespan_env(temp_db, monkeypatch):
    monkeypatch.setattr(config, "AUTH_ENABLED", False)
    # 隔离 lifespan 中的全局副作用与后台任务
    monkeypatch.setattr(config, "apply_agent_write_preference", lambda v: None)
    monkeypatch.setattr(api.refresh_service, "mark_interrupted_on_startup", lambda: 0)
    monkeypatch.setattr(api.proposal_service, "mark_stale_on_startup", lambda: 0)
    monkeypatch.setattr(api.scheduler, "purge_agent_operations_daily", lambda: 0)
    monkeypatch.setattr(api.scheduler, "shutdown_scheduler", MagicMock())
    return monkeypatch


class TestLifespanT1Fix:
    def test_exception_not_marked_done(self, lifespan_env):
        lifespan_env.setattr(api.analysis, "recalculate_t1_transactions",
                             MagicMock(side_effect=RuntimeError("network down")))
        lifespan_env.setattr(api.scheduler, "init_scheduler", MagicMock())
        with TestClient(api.app):
            pass
        # 异常路径不标记，下次启动可重试
        assert db.get_preference("t1_nav_fix_done") is None

    def test_success_empty_marked_done(self, lifespan_env):
        lifespan_env.setattr(api.analysis, "recalculate_t1_transactions",
                             MagicMock(return_value=[]))
        lifespan_env.setattr(api.scheduler, "init_scheduler", MagicMock())
        with TestClient(api.app):
            pass
        assert db.get_preference("t1_nav_fix_done") == "1"

    def test_success_with_items_marked_done(self, lifespan_env):
        fixed = [{"tx_id": 1, "fund_code": "005827", "date": "2026-01-02",
                  "old_nav": 1.0, "new_nav": 1.1,
                  "old_shares": 100.0, "new_shares": 90.9}]
        lifespan_env.setattr(api.analysis, "recalculate_t1_transactions",
                             MagicMock(return_value=fixed))
        lifespan_env.setattr(api.scheduler, "init_scheduler", MagicMock())
        with TestClient(api.app):
            pass
        assert db.get_preference("t1_nav_fix_done") == "1"
        assert "t1_nav_fix" in _audit_actions()


class TestLifespanSchedulerFallback:
    def test_cron_failure_falls_back_to_default(self, lifespan_env):
        init = MagicMock(side_effect=[ValueError("无效的 cron 表达式"), None])
        set_cron = MagicMock()
        lifespan_env.setattr(api.scheduler, "init_scheduler", init)
        lifespan_env.setattr(api.scheduler, "set_cron", set_cron)
        lifespan_env.setattr(api.analysis, "recalculate_t1_transactions",
                             MagicMock(return_value=[]))
        with TestClient(api.app):
            pass
        set_cron.assert_called_once_with(config.NAV_CRON)
        assert init.call_count == 2

    def test_fallback_also_fails_still_starts(self, lifespan_env):
        init = MagicMock(side_effect=[ValueError("bad cron"), RuntimeError("still bad")])
        lifespan_env.setattr(api.scheduler, "init_scheduler", init)
        lifespan_env.setattr(api.scheduler, "set_cron", MagicMock())
        lifespan_env.setattr(api.analysis, "recalculate_t1_transactions",
                             MagicMock(return_value=[]))
        with TestClient(api.app) as c:
            assert c.get("/api/auth/status").status_code == 200

    def test_other_error_does_not_override_cron(self, lifespan_env):
        set_cron = MagicMock()
        lifespan_env.setattr(api.scheduler, "init_scheduler",
                             MagicMock(side_effect=RuntimeError("boom")))
        lifespan_env.setattr(api.scheduler, "set_cron", set_cron)
        lifespan_env.setattr(api.analysis, "recalculate_t1_transactions",
                             MagicMock(return_value=[]))
        with TestClient(api.app) as c:
            assert c.get("/api/auth/status").status_code == 200
        set_cron.assert_not_called()
