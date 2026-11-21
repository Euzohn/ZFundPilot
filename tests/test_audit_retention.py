"""审计日志保留期设置页可配回归。

覆盖：config 解析器（缺失/非法/越界退回默认）、GET/PUT HTTP 契约
（低于下限/超上限/非整数 422、边界值合法、持久化 + 审计）、调度器
清理实时读取配置值（修改后下次清理即生效）。

下限 30 天保护补记防重契约：proposal_service._executed_plan_trade_exists
依赖审计中的 auto_invest_execute 覆盖 7 天补记窗口，保留期过小会放行
同一交易日的重复买入。
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from zfundpilot import api, config, db, scheduler


@pytest.fixture
def temp_db(monkeypatch):
    with TemporaryDirectory() as d:
        monkeypatch.setattr(config, "DB_PATH", str(Path(d) / "test.db"))
        monkeypatch.setattr(config, "AUTH_DATA_PATH", str(Path(d) / "auth.json"))
        db.init_db()
        yield


@pytest.fixture
def client(temp_db, monkeypatch):
    monkeypatch.setattr(config, "AUTH_ENABLED", False)
    monkeypatch.setattr(api, "_REQ_LOGS", {})
    monkeypatch.setattr(api, "_AGENT_REQ_LOGS", {})
    return TestClient(api.app)


class TestResolveAuditRetention:
    def test_default_when_unset(self):
        assert config.resolve_audit_retention_days(None) == 90

    @pytest.mark.parametrize("stored", ["", "abc", "12.5", "0", "29", "3651", "-5"])
    def test_invalid_or_out_of_range_falls_back(self, stored):
        assert (config.resolve_audit_retention_days(stored)
                == config.AUDIT_RETENTION_DEFAULT_DAYS)

    @pytest.mark.parametrize("stored,expected", [("30", 30), (" 45 ", 45), ("3650", 3650)])
    def test_valid_values(self, stored, expected):
        assert config.resolve_audit_retention_days(stored) == expected

    def test_min_covers_backfill_window(self):
        """下限必须覆盖 7 天补记窗口（防重契约的硬约束）。"""
        assert config.AUDIT_RETENTION_MIN_DAYS >= 7


class TestAuditRetentionHttp:
    def test_get_default_view(self, client):
        resp = client.get("/api/settings/audit-retention")
        assert resp.status_code == 200
        assert resp.json() == {
            "retention_days": 90, "min_days": 30,
            "max_days": 3650, "default_days": 90,
        }

    def test_put_valid_persists_and_audits(self, client):
        resp = client.put("/api/settings/audit-retention",
                          json={"retention_days": 45})
        assert resp.status_code == 200, resp.text
        assert resp.json()["retention_days"] == 45
        assert db.get_preference(config.AUDIT_RETENTION_PREF_KEY) == "45"
        row = db.fetch_audit_logs(1)[0]
        assert row["action"] == "audit_retention_update"
        assert json.loads(row["detail"]) == {"from": 90, "to": 45}
        # GET 反映新值
        assert client.get("/api/settings/audit-retention").json()["retention_days"] == 45

    @pytest.mark.parametrize("days", [0, 7, 29, -1, 3651, 100000])
    def test_put_out_of_range_422(self, client, days):
        resp = client.put("/api/settings/audit-retention",
                          json={"retention_days": days})
        assert resp.status_code == 422
        assert db.get_preference(config.AUDIT_RETENTION_PREF_KEY) is None

    @pytest.mark.parametrize("bad", ["abc", 45.5, None, True])
    def test_put_non_integer_422(self, client, bad):
        resp = client.put("/api/settings/audit-retention",
                          json={"retention_days": bad})
        assert resp.status_code == 422
        assert db.get_preference(config.AUDIT_RETENTION_PREF_KEY) is None

    def test_put_missing_field_422(self, client):
        resp = client.put("/api/settings/audit-retention", json={})
        assert resp.status_code == 422

    def test_boundary_values_accepted(self, client):
        for days in (config.AUDIT_RETENTION_MIN_DAYS, config.AUDIT_RETENTION_MAX_DAYS):
            resp = client.put("/api/settings/audit-retention",
                              json={"retention_days": days})
            assert resp.status_code == 200, resp.text
            assert resp.json()["retention_days"] == days


class TestSchedulerUsesConfiguredRetention:
    def test_purge_uses_configured_value(self, temp_db, monkeypatch):
        db.upsert_preference(config.AUDIT_RETENTION_PREF_KEY, "45")
        mock_purge = MagicMock(return_value=0)
        monkeypatch.setattr(db, "purge_audit_logs", mock_purge)
        scheduler.purge_agent_operations_daily()
        mock_purge.assert_called_once_with(45)

    def test_purge_invalid_stored_falls_back_default(self, temp_db, monkeypatch):
        """手工改库写入越界值（如 7）不得破坏防重契约，退回默认 90。"""
        db.upsert_preference(config.AUDIT_RETENTION_PREF_KEY, "7")
        mock_purge = MagicMock(return_value=0)
        monkeypatch.setattr(db, "purge_audit_logs", mock_purge)
        scheduler.purge_agent_operations_daily()
        mock_purge.assert_called_once_with(90)

    def test_purge_integration_deletes_by_configured_window(self, temp_db):
        """配置 30 天：40 天前的审计行被删、20 天前保留（默认 90 则两者都留）。"""
        db.upsert_preference(config.AUDIT_RETENTION_PREF_KEY, "30")
        now = datetime.now(config.TIMEZONE)
        with db.get_connection(write=True) as conn:
            conn.execute("INSERT INTO audit_log(ts, action) VALUES(?, ?)",
                         ((now - timedelta(days=40)).isoformat(), "old"))
            conn.execute("INSERT INTO audit_log(ts, action) VALUES(?, ?)",
                         ((now - timedelta(days=20)).isoformat(), "recent"))
        scheduler.purge_agent_operations_daily()
        with db.get_connection() as conn:
            actions = [r["action"] for r in
                       conn.execute("SELECT action FROM audit_log")]
        assert actions == ["recent"]
