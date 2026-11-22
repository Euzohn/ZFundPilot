"""统一站内提醒中心（P3 Phase 2）服务层测试。

覆盖：去重、best-effort 隔离（故障注入：通知写入失败不影响主业务）、
业务状态联动、五类事件源写入规则、生命周期清理、启动 interrupted 仅 running、
备份排除与恢复清空。
"""
from __future__ import annotations

import io
import json
import zipfile
from datetime import datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from zfundpilot import backup_service as bs
from zfundpilot import config, db, refresh_service, scheduler
from zfundpilot import notification_service as ns
from zfundpilot.fetch_dividend import DividendEvent


@pytest.fixture
def temp_db(monkeypatch):
    with TemporaryDirectory() as d:
        monkeypatch.setattr(config, "DB_PATH", str(Path(d) / "test.db"))
        db.init_db()
        yield


def _add(key: str, *, source_type: str = "dividend", source_id: str = "1",
         created_at: str | None = None) -> bool:
    return db.add_notification(
        source_type=source_type, source_id=source_id, dedupe_key=key,
        title_code="dividend_detected", title_params={"fund_code": "005827"},
        created_at=created_at)


def _rows() -> list[dict]:
    return db.list_notifications(limit=1000)


def _ev() -> DividendEvent:
    return DividendEvent(
        fund_code="005827", fund_name="易方达蓝筹精选",
        record_date="2026-11-10", ex_date="2026-11-11", per_share=0.05,
        pay_date="2026-11-12", held_shares=1000.0, estimated_amount=50.0,
        channel="支付宝")


class TestDedupe:
    def test_same_key_not_resent(self, temp_db):
        assert _add("dividend:005827:2026-11-11:支付宝") is True
        assert _add("dividend:005827:2026-11-11:支付宝") is False
        assert len(_rows()) == 1

    def test_different_channel_distinct(self, temp_db):
        assert _add("dividend:005827:2026-11-11:支付宝") is True
        assert _add("dividend:005827:2026-11-11:天天基金") is True
        assert len(_rows()) == 2

    def test_title_params_roundtrip(self, temp_db):
        ns.notify("data_health", "2026-11-19", "data:health:2026-11-19",
                  "data_health_abnormal", {"stale_nav_fund_count": 2})
        row = _rows()[0]
        assert json.loads(row["title_params"]) == {"stale_nav_fund_count": 2}
        assert row["status"] == "unread"


class TestBestEffort:
    def test_notify_swallows_db_error(self, temp_db, monkeypatch):
        monkeypatch.setattr(db, "add_notification",
                            MagicMock(side_effect=RuntimeError("db down")))
        assert ns.notify("dividend", "1", "k", "dividend_detected") is False

    def test_trade_calendar_degraded_swallows_db_error(self, temp_db, monkeypatch):
        """降级通知走 best-effort：db 失败不抛，不影响定投主流程。"""
        monkeypatch.setattr(db, "add_notification",
                            MagicMock(side_effect=RuntimeError("db down")))
        assert ns.notify_trade_calendar_degraded("2026-10-01") is False  # 不抛

    def test_sync_swallows_db_error(self, temp_db, monkeypatch):
        monkeypatch.setattr(db, "sync_notification_by_source",
                            MagicMock(side_effect=RuntimeError("db down")))
        ns.sync_alert_status(1, "confirmed")  # 不抛

    def test_invalidate_swallows_db_error(self, temp_db, monkeypatch):
        monkeypatch.setattr(db, "sync_notification_by_source",
                            MagicMock(side_effect=RuntimeError("db down")))
        ns.invalidate_alert(1)  # 不抛

    def test_evaluate_data_health_swallows_error(self, temp_db, monkeypatch):
        monkeypatch.setattr("zfundpilot.analysis.calculate_positions",
                            MagicMock(side_effect=RuntimeError("boom")))
        ns.evaluate_data_health()  # 不抛


class TestTradeCalendarDegraded:
    """P3-2：定投执行日日历未覆盖 → auto_invest 来源降级通知，按日去重。"""

    def test_creates_notification_row(self, temp_db):
        assert ns.notify_trade_calendar_degraded("2026-10-01") is True
        row = _rows()[0]
        assert row["source_type"] == "auto_invest"
        assert row["title_code"] == "trade_calendar_degraded"
        assert json.loads(row["title_params"]) == {"date": "2026-10-01"}
        assert row["status"] == "unread"

    def test_dedupe_by_date(self, temp_db):
        assert ns.notify_trade_calendar_degraded("2026-10-01") is True
        assert ns.notify_trade_calendar_degraded("2026-10-01") is False  # 同日不重发
        assert ns.notify_trade_calendar_degraded("2026-10-02") is True
        assert len(_rows()) == 2


class TestFaultInjection:
    """🔴 通知写入抛异常时，分红扫描/定投执行/净值聚合照常完成。"""

    def test_dividend_scan_unaffected(self, temp_db, monkeypatch):
        monkeypatch.setattr(db, "add_notification",
                            MagicMock(side_effect=RuntimeError("db down")))
        monkeypatch.setattr("zfundpilot.fetch_dividend.check_dividends",
                            MagicMock(return_value=[_ev()]))
        scheduler._run_dividend_check()
        alerts = db.get_dividend_alerts()
        assert len(alerts) == 1
        assert alerts[0]["fund_code"] == "005827"
        assert alerts[0]["channel"] == "支付宝"

    def test_auto_invest_unaffected(self, temp_db, monkeypatch):
        monkeypatch.setattr(db, "add_notification",
                            MagicMock(side_effect=RuntimeError("db down")))
        monkeypatch.setattr(scheduler, "fetch_fund", MagicMock())
        monkeypatch.setattr(scheduler.auto_invest, "run_all_due", MagicMock(
            return_value=[{"plan_id": 1, "fund_code": "001",
                           "status": "suspended", "date": "2026-11-19"}]))
        scheduler._run_auto_invest()  # 不抛
        with db.get_connection() as conn:
            rows = conn.execute(
                "SELECT action FROM audit_log WHERE action='auto_invest_execute'"
            ).fetchall()
        assert len(rows) == 1

    def test_nav_update_aggregation_unaffected(self, temp_db, monkeypatch):
        monkeypatch.setattr(db, "add_notification",
                            MagicMock(side_effect=RuntimeError("db down")))
        failed = SimpleNamespace(ok=False, fund_code="005827", message="超时")
        ns.notify_nav_update_failed([failed])  # 不抛

    def test_helpers_never_raise_on_malformed_input(self, temp_db):
        """参数构造阶段也在 best-effort 保护内：畸形输入不上抛、不落通知。"""
        ns.notify_nav_update_failed([object()])      # 缺 ok 属性
        ns.notify_dividend_alert(object(), 1)        # 缺事件字段
        ns.notify_auto_invest_results([None])        # 元素非 dict
        ns.notify_auto_invest_results("not-a-list")  # 整体非列表
        assert _rows() == []


class TestStatusSync:
    def test_confirmed_read_ignored_dismissed_pending_unread(self, temp_db):
        ns.notify("dividend", "7", "dividend:7", "dividend_detected")
        ns.sync_alert_status(7, "confirmed")
        assert _rows()[0]["status"] == "read"
        assert _rows()[0]["read_at"]
        ns.sync_alert_status(7, "ignored")
        assert _rows()[0]["status"] == "dismissed"
        ns.sync_alert_status(7, "pending")
        # dismissed 不回退（业务误处理走网页更正，通知保持已忽略）
        assert _rows()[0]["status"] == "dismissed"

    def test_pending_reverts_read_to_unread(self, temp_db):
        ns.notify("tpsl", "9", "tpsl:9", "tp_sl_triggered")
        ns.sync_alert_status(9, "confirmed")
        assert _rows()[0]["status"] == "read"
        ns.sync_alert_status(9, "pending")
        row = _rows()[0]
        assert row["status"] == "unread"
        assert row["read_at"] is None

    def test_invalidate_dismisses(self, temp_db):
        ns.notify("dividend", "7", "dividend:7", "dividend_detected")
        ns.invalidate_alert(7)
        assert _rows()[0]["status"] == "dismissed"

    def test_unknown_status_noop(self, temp_db):
        ns.notify("dividend", "7", "dividend:7", "dividend_detected")
        ns.sync_alert_status(7, "whatever")
        assert _rows()[0]["status"] == "unread"


class TestAutoInvestResults:
    def test_only_skip_codes_and_error_notified(self, temp_db):
        date = "2026-11-19"
        results = [
            {"plan_id": 1, "fund_code": "001", "status": "suspended", "date": date},
            {"plan_id": 2, "fund_code": "002", "status": "limit_exceeded", "date": date},
            {"plan_id": 3, "fund_code": "003", "status": "below_minimum", "date": date},
            {"plan_id": 4, "fund_code": "004", "status": "error", "date": date,
             "error": "净值缺失"},
            {"plan_id": 5, "fund_code": "005", "status": "holiday", "date": date},
            {"plan_id": 6, "fund_code": "006", "status": "skipped", "date": date},
            {"plan_id": 7, "fund_code": "007", "status": "success", "date": date},
        ]
        ns.notify_auto_invest_results(results)
        rows = _rows()
        assert len(rows) == 4
        keys = {r["dedupe_key"] for r in rows}
        assert keys == {
            f"auto_invest:1:{date}:suspended",
            f"auto_invest:2:{date}:limit_exceeded",
            f"auto_invest:3:{date}:below_minimum",
            f"auto_invest:4:{date}:error",
        }
        skipped = next(r for r in rows if r["source_id"] == "1")
        assert skipped["title_code"] == "auto_invest_skipped"
        assert json.loads(skipped["title_params"])["skip_code"] == "suspended"

    def test_same_day_rerun_deduped(self, temp_db):
        results = [{"plan_id": 1, "fund_code": "001",
                    "status": "suspended", "date": "2026-11-19"}]
        ns.notify_auto_invest_results(results)
        ns.notify_auto_invest_results(results)
        assert len(_rows()) == 1

    def test_task_error(self, temp_db):
        ns.notify_auto_invest_task_error("boom")
        row = _rows()[0]
        assert row["title_code"] == "auto_invest_task_error"
        assert row["dedupe_key"].startswith("auto_invest:task:")


class TestJobNotifications:
    def test_job_failed_both_types(self, temp_db):
        ns.notify_job_failed(11, "data_refresh", "网络超时")
        ns.notify_job_failed(12, "dca_backtest", "净值不足")
        rows = _rows()
        assert {r["dedupe_key"] for r in rows} == {"job:failed:11", "job:failed:12"}
        assert json.loads(rows[0]["title_params"])["error"]

    def test_interrupted_only_running(self, temp_db):
        now = datetime.now(config.TIMEZONE).isoformat()
        with db.get_connection(write=True) as conn:
            for status in ("queued", "running"):
                conn.execute(
                    "INSERT INTO refresh_jobs"
                    "(principal_type, principal_id, job_type, params_digest,"
                    " status, created_at, updated_at) VALUES(?,?,?,?,?,?,?)",
                    ("agent_token", "1", "data_refresh", "d", status, now, now))
        count = refresh_service.mark_interrupted_on_startup()
        assert count == 2
        rows = _rows()
        assert len(rows) == 1
        assert rows[0]["title_code"] == "job_interrupted"
        with db.get_connection() as conn:
            running_id = conn.execute(
                "SELECT id FROM refresh_jobs WHERE status='interrupted' "
                "ORDER BY id DESC LIMIT 1").fetchone()[0]
        assert rows[0]["dedupe_key"] == f"job:interrupted:{running_id}"


class TestNavUpdateAggregation:
    def test_no_failure_no_notification(self, temp_db):
        ok = SimpleNamespace(ok=True, fund_code="005827", message="成功")
        ns.notify_nav_update_failed([ok])
        assert _rows() == []

    def test_daily_aggregate_one(self, temp_db):
        failed = [SimpleNamespace(ok=False, fund_code=f"00{i}", message="超时")
                  for i in range(3)]
        ns.notify_nav_update_failed(failed)
        ns.notify_nav_update_failed(failed)  # 同日重复评估不重发
        rows = _rows()
        assert len(rows) == 1
        params = json.loads(rows[0]["title_params"])
        assert params["count"] == 3
        assert len(params["funds"]) == 3
        assert rows[0]["dedupe_key"].startswith("nav_update:failed:")


class TestDataHealth:
    def test_abnormal_daily_one(self, temp_db, monkeypatch):
        monkeypatch.setattr("zfundpilot.analysis.calculate_positions",
                            MagicMock(return_value=[]))
        monkeypatch.setattr(
            "zfundpilot.analysis._build_data_status",
            MagicMock(return_value=SimpleNamespace(
                stale_nav_fund_count=2, missing_nav_fund_count=0,
                pending_t1_transaction_count=1)))
        ns.evaluate_data_health()
        ns.evaluate_data_health()
        rows = _rows()
        assert len(rows) == 1
        assert rows[0]["title_code"] == "data_health_abnormal"
        assert rows[0]["dedupe_key"].startswith("data:health:")
        params = json.loads(rows[0]["title_params"])
        assert params["stale_nav_fund_count"] == 2
        assert params["pending_t1_transaction_count"] == 1

    def test_healthy_no_notification(self, temp_db, monkeypatch):
        monkeypatch.setattr("zfundpilot.analysis.calculate_positions",
                            MagicMock(return_value=[]))
        monkeypatch.setattr(
            "zfundpilot.analysis._build_data_status",
            MagicMock(return_value=SimpleNamespace(
                stale_nav_fund_count=0, missing_nav_fund_count=0,
                pending_t1_transaction_count=0)))
        ns.evaluate_data_health()
        assert _rows() == []


class TestLifecycle:
    def test_purge_only_old_dismissed(self, temp_db):
        now = datetime.now(config.TIMEZONE)
        old = (now - timedelta(days=31)).isoformat()
        recent = (now - timedelta(days=5)).isoformat()
        _add("old-dismissed", created_at=old)
        _add("old-read", created_at=old)
        _add("old-unread", created_at=old)
        _add("recent-dismissed", created_at=recent)
        rows = {r["dedupe_key"]: r["id"] for r in _rows()}
        db.dismiss_notifications([rows["old-dismissed"], rows["recent-dismissed"]])
        db.mark_notifications_read([rows["old-read"]])
        cutoff = (now - timedelta(days=30)).isoformat()
        assert db.purge_dismissed_notifications(cutoff) == 1
        assert {r["dedupe_key"] for r in _rows()} == {
            "old-read", "old-unread", "recent-dismissed"}

    def test_scheduler_daily_purge(self, temp_db):
        now = datetime.now(config.TIMEZONE)
        _add("just_over", created_at=(now - timedelta(days=31)).isoformat())
        _add("just_under", created_at=(now - timedelta(days=29)).isoformat())
        db.dismiss_notifications(all=True)
        assert scheduler.purge_notifications_daily() == 1
        assert [r["dedupe_key"] for r in _rows()] == ["just_under"]

    def test_read_all_skips_dismissed(self, temp_db):
        _add("a")
        _add("b")
        rows = {r["dedupe_key"]: r["id"] for r in _rows()}
        db.dismiss_notifications([rows["b"]])
        assert db.mark_notifications_read(all=True) == 1
        status = {r["dedupe_key"]: r["status"] for r in _rows()}
        assert status == {"a": "read", "b": "dismissed"}


class TestBackup:
    @pytest.fixture
    def temp_env(self, monkeypatch):
        with TemporaryDirectory() as d:
            monkeypatch.setattr(config, "DB_PATH", str(Path(d) / "test.db"))
            monkeypatch.setattr(config, "DATA_DIR", d)
            db.init_db()
            yield

    def test_excluded_from_backup_and_cleared_on_restore(self, temp_env):
        _add("dividend:005827:2026-11-11:支付宝")
        payload = bs.export_backup_zip()
        with zipfile.ZipFile(io.BytesIO(payload)) as zf:
            names = zf.namelist()
            manifest = json.loads(zf.read("manifest.json"))
        assert all("notifications" not in n for n in names)
        assert "notifications" in manifest["excluded"]
        # manifest 业务表清单不变（12 表）
        assert len(manifest["tables"]) == 12
        bs.restore_backup(payload, username="tester")
        assert db.count_notifications() == 0
