"""任务化数据刷新服务测试：任务创建、幂等、互斥、归属与重启中断。"""
from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

from zfundpilot import config, db
from zfundpilot import refresh_service as svc
from zfundpilot.analysis import clear_analysis_cache
from zfundpilot.models import Fund

KEY_A = "refresh-key-aaaaaaaaaaaa"
KEY_B = "refresh-key-bbbbbbbbbbbb"


@pytest.fixture
def temp_db(monkeypatch):
    with TemporaryDirectory() as d:
        monkeypatch.setattr(config, "DB_PATH", str(Path(d) / "test.db"))
        db.init_db()
        db.upsert_fund(Fund("005827", "易方达蓝筹精选", "混合型", "消费"))
        clear_analysis_cache()
        yield
        clear_analysis_cache()


@pytest.fixture
def sync_refresh(monkeypatch):
    """后台线程改为同步执行，且抓取/元数据不访问网络。"""
    monkeypatch.setattr(svc, "_spawn", lambda fn: fn())

    class _Result:
        def __init__(self, code, ok=True, message=""):
            self.fund_code = code
            self.ok = ok
            self.message = message
            self.code = "ok" if ok else "fetch_error"

    def fake_update(codes, progress=None):
        if progress:
            for i, c in enumerate(codes, start=1):
                progress(i, len(codes), c)
        return [_Result(c) for c in codes]

    monkeypatch.setattr(svc.fetch_fund, "update_all_holdings_nav", fake_update)
    monkeypatch.setattr(svc.scheduler, "refresh_fund_metadata",
                        lambda on_phase=None: None)


def _agent(principal_id: str = "1") -> svc.Principal:
    return svc.Principal("agent_token", principal_id, f"agent:test{principal_id}")


def _start(codes, key=KEY_A, principal=None, **kw):
    return svc.start_refresh(
        principal or _agent(), fund_codes=codes, idempotency_key=key, **kw)


class TestStartRefresh:
    def test_creates_and_succeeds(self, temp_db, sync_refresh):
        result = _start(["005827"])
        assert result.http_status == 202
        assert result.code == "queued"
        assert result.replayed is False
        job_id = result.data["job_id"]
        assert job_id > 0

        status = svc.get_job_status(_agent(), job_id)
        assert status.http_status == 200
        data = status.data
        assert data["status"] == "succeeded"
        assert data["progress"]["total"] == 1
        assert data["result"]["updated"] == 1
        assert data["result"]["failed"] == 0
        assert data["can_cancel"] is False

    def test_same_key_same_params_replays_same_job(self, temp_db, sync_refresh):
        first = _start(["005827"])
        second = _start(["005827"])
        assert second.replayed is True
        assert second.http_status == 202
        assert second.data["job_id"] == first.data["job_id"]

    def test_same_key_different_params_conflicts(self, temp_db, sync_refresh):
        _start(["005827"])
        result = _start(["000001"], key=KEY_A)
        assert result.http_status == 409
        assert result.code == "idempotency_conflict"

    def test_busy_returns_current_job_and_no_operation(self, temp_db, monkeypatch):
        monkeypatch.setattr(svc, "_spawn", lambda fn: None)  # 不执行
        monkeypatch.setitem(svc.nav_update_state, "running", True)
        result = _start(["005827"])
        assert result.http_status == 409
        assert result.code == "refresh_busy"

    def test_open_holdings_default(self, temp_db, sync_refresh, monkeypatch):
        """缺省基金代码使用当前开仓持仓。"""
        monkeypatch.setattr(
            svc.analysis, "calculate_positions",
            lambda: [type("P", (), {"is_open": True, "fund_code": "005827"})()],
        )
        result = _start(None)
        assert result.http_status == 202
        assert result.data["fund_count"] == 1

    def test_validation_errors_do_not_create(self, temp_db, sync_refresh):
        with pytest.raises(svc.RefreshValidationError):
            _start(["12345"])
        with pytest.raises(svc.RefreshValidationError):
            _start(["005827"] * 51)
        with pytest.raises(svc.RefreshValidationError):
            _start([])
        with pytest.raises(svc.RefreshValidationError):
            _start(["005827"], key="short")

        with db.get_connection() as conn:
            count = conn.execute("SELECT COUNT(*) FROM refresh_jobs").fetchone()[0]
        assert count == 0


class TestOwnershipAndInterrupt:
    def test_other_token_cannot_read(self, temp_db, sync_refresh):
        job_id = _start(["005827"]).data["job_id"]
        other = svc.get_job_status(_agent("2"), job_id)
        assert other.http_status == 404
        assert other.code == "not_found"

    def test_startup_marks_leftover_interrupted(self, temp_db):
        now = svc._now().isoformat()
        with db.get_connection(write=True) as conn:
            job_id = db.insert_refresh_job(
                conn, principal_type="agent_token", principal_id="1",
                job_type="data_refresh", params_digest="x", status="running",
                created_at=now, updated_at=now, expires_at=None)
        marked = svc.mark_interrupted_on_startup()
        assert marked == 1
        with db.get_connection() as conn:
            row = db.get_refresh_job(conn, job_id, "agent_token", "1")
        assert row["status"] == "interrupted"

    def test_job_row_result_is_stored(self, temp_db, sync_refresh):
        job_id = _start(["005827"]).data["job_id"]
        with db.get_connection() as conn:
            row = db.get_refresh_job(conn, job_id, "agent_token", "1")
        assert row["status"] == "succeeded"
        result = json.loads(row["result_json"])
        assert result["ok"] is True
        assert result["updated"] == 1
