"""回测任务化测试：幂等、进度、失败、归属与按任务类型的 scope 复核。"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest
from fastapi.testclient import TestClient

from zfundpilot import agent_tokens, api, config, db
from zfundpilot import refresh_service as svc

URL = "/api/agent/tools/backtest/dca"
KEY = "backtest-job-key-000001"


@pytest.fixture
def temp_db(monkeypatch):
    with TemporaryDirectory() as d:
        monkeypatch.setattr(config, "DB_PATH", str(Path(d) / "test.db"))
        db.init_db()
        yield


@pytest.fixture
def client(temp_db, monkeypatch):
    monkeypatch.setattr(config, "AUTH_ENABLED", True)
    monkeypatch.setattr(config, "AUTH_SECRET", "test-secret")
    monkeypatch.setattr(config, "AUTH_USERNAME", "admin")
    # 回测只读，不需要写开关；_spawn 同步执行便于断言任务终态。
    monkeypatch.setattr(config, "AGENT_WRITE_ENABLED", False)
    monkeypatch.setattr(svc, "_spawn", lambda fn: fn())
    # 限流桶是进程内全局状态，按 (token_id, endpoint) 计数；临时库的 token id
    # 会从 1 重新分配，必须清空以免命中其他测试留下的额度。
    monkeypatch.setattr(api, "_AGENT_REQ_LOGS", {})
    return TestClient(api.app)


def _issue(*scopes: str) -> tuple[dict[str, str], int]:
    plaintext, info = agent_tokens.issue_token("backtest-job", list(scopes))
    return {"Authorization": f"Bearer {plaintext}"}, int(info["id"])


def _body(**overrides) -> dict:
    payload = {
        "fund_codes": ["000001"],
        "start_date": "2024-01-01",
        "end_date": "2024-03-31",
        "amount_per_period": 1000,
    }
    payload.update(overrides)
    return payload


class _FakeResult:
    """最小 BacktestResult 替身：只提供 ``_backtest_result_data`` 用到的字段。"""

    def __init__(self, fund_code: str) -> None:
        self.fund_code = fund_code

    def to_dict(self) -> dict:
        return {
            "fund_code": self.fund_code,
            "fund_name": f"基金{self.fund_code}",
            "strategy": "dca",
            "status": "ok",
            "curve": [],
            "periods_detail": [],
        }


def _latest_job() -> dict:
    with db.get_connection() as conn:
        row = conn.execute(
            "SELECT status, done, total, current FROM refresh_jobs "
            "ORDER BY id DESC LIMIT 1").fetchone()
    return {key: row[key] for key in ("status", "done", "total", "current")}


def _install_stub(monkeypatch, snapshots=None, fail_codes=()):
    def fake(fund_codes, start_date, end_date, amount_per_period,
             cadence="month", include_lumpsum=True, nav_provider=None):
        if snapshots is not None:
            snapshots.append(_latest_job())
        code = fund_codes[0]
        if code in fail_codes:
            raise RuntimeError("模拟回测失败")
        return [_FakeResult(code)]

    monkeypatch.setattr(svc.backtest, "run_dca_backtest", fake)


def _insert_job(principal_id: str, job_type: str) -> int:
    now = datetime.now(config.TIMEZONE).isoformat()
    with db.get_connection(write=True) as conn:
        return db.insert_refresh_job(
            conn, principal_type="agent_token", principal_id=principal_id,
            job_type=job_type, params_digest="digest", status="queued",
            created_at=now, updated_at=now, expires_at=None)


class TestBacktestJobLifecycle:
    def test_start_progress_replay_and_conflict(self, client, monkeypatch):
        snapshots: list[dict] = []
        _install_stub(monkeypatch, snapshots)
        headers, _ = _issue(agent_tokens.SCOPE_FUNDS_READ)
        post_headers = {**headers, "Idempotency-Key": KEY}
        payload = _body(fund_codes=["000001", "000002"])

        resp = client.post(URL, json=payload, headers=post_headers)
        assert resp.status_code == 202, resp.text
        body = resp.json()
        assert body["tool"] == "run_dca_backtest"
        assert body["data"]["code"] == "queued"
        assert body["data"]["status"] == "queued"
        assert body["data"]["fund_count"] == 2
        job_id = body["data"]["job_id"]

        status = client.get(
            f"/api/agent/tools/refresh/{job_id}", headers=headers)
        assert status.status_code == 200, status.text
        data = status.json()["data"]
        assert data["job_type"] == "dca_backtest"
        assert data["status"] == "succeeded"
        assert data["progress"] == {
            "done": 2, "total": 2, "current": "", "phase": ""}
        assert data["result"]["ok"] is True
        assert data["result"]["fund_count"] == 2
        assert data["result"]["result_count"] == 2

        # 每个基金开始前读取任务行：done 从 0 递增到 1。
        assert [s["done"] for s in snapshots] == [0, 1]
        assert snapshots[0]["status"] == "running"
        assert snapshots[0]["total"] == 2
        assert snapshots[1]["current"] == "000001"

        replay = client.post(URL, json=payload, headers=post_headers)
        assert replay.status_code == 202
        replay_data = replay.json()["data"]
        assert replay_data["replayed"] is True
        assert replay_data["job_id"] == job_id
        assert replay_data["status"] == "queued"
        assert replay_data["fund_count"] == 2
        assert "expires_at" in replay_data
        assert len(snapshots) == 2  # 重放不重新执行

        conflict = client.post(
            URL, json=_body(fund_codes=["000001", "000002"],
                            amount_per_period=2000),
            headers=post_headers)
        assert conflict.status_code == 409
        assert conflict.json()["detail"]["code"] == "idempotency_conflict"

    def test_missing_idempotency_key_is_422(self, client):
        headers, _ = _issue(agent_tokens.SCOPE_FUNDS_READ)
        resp = client.post(URL, json=_body(), headers=headers)
        assert resp.status_code == 422
        assert resp.json()["detail"]["field"] == "idempotency_key"

    def test_failure_marks_job_failed_and_releases_gate(
            self, client, monkeypatch):
        _install_stub(monkeypatch, fail_codes={"000001"})
        headers, _ = _issue(agent_tokens.SCOPE_FUNDS_READ)

        resp = client.post(
            URL, json=_body(), headers={**headers, "Idempotency-Key": KEY})
        assert resp.status_code == 202
        job_id = resp.json()["data"]["job_id"]

        data = client.get(
            f"/api/agent/tools/refresh/{job_id}",
            headers=headers).json()["data"]
        assert data["status"] == "failed"
        assert "模拟回测失败" in data["error"]
        assert data["result"] == {"ok": False}
        # 后台执行无论成败都必须归还并发名额。
        assert svc._backtest_gate.acquire(blocking=False)
        svc._backtest_gate.release()

    def test_restart_marks_queued_backtest_interrupted(self, client):
        headers, token_id = _issue(agent_tokens.SCOPE_FUNDS_READ)
        job_id = _insert_job(str(token_id), svc.BACKTEST_JOB_TYPE)

        assert svc.mark_interrupted_on_startup() >= 1
        data = client.get(
            f"/api/agent/tools/refresh/{job_id}",
            headers=headers).json()["data"]
        assert data["job_type"] == "dca_backtest"
        assert data["status"] == "interrupted"


class TestJobTypeScope:
    def test_funds_read_cannot_read_refresh_job(self, client):
        headers, token_id = _issue(agent_tokens.SCOPE_FUNDS_READ)
        job_id = _insert_job(str(token_id), svc.JOB_TYPE)

        resp = client.get(
            f"/api/agent/tools/refresh/{job_id}", headers=headers)
        assert resp.status_code == 403
        assert resp.json()["error"]["code"] == "insufficient_scope"

    def test_data_refresh_cannot_read_backtest_job(self, client):
        headers, token_id = _issue(agent_tokens.SCOPE_DATA_REFRESH)
        job_id = _insert_job(str(token_id), svc.BACKTEST_JOB_TYPE)

        resp = client.get(
            f"/api/agent/tools/refresh/{job_id}", headers=headers)
        assert resp.status_code == 403
        assert resp.json()["error"]["code"] == "insufficient_scope"

    def test_unknown_job_type_is_refused(self, client):
        headers, token_id = _issue(
            agent_tokens.SCOPE_DATA_REFRESH, agent_tokens.SCOPE_FUNDS_READ)
        job_id = _insert_job(str(token_id), "mystery_job")

        resp = client.get(
            f"/api/agent/tools/refresh/{job_id}", headers=headers)
        assert resp.status_code == 403
        assert resp.json()["error"]["code"] == "insufficient_scope"

    def test_other_token_sees_404_not_403(self, client, monkeypatch):
        _install_stub(monkeypatch)
        creator, _ = _issue(agent_tokens.SCOPE_FUNDS_READ)
        other, _ = _issue(agent_tokens.SCOPE_FUNDS_READ)
        job_id = client.post(
            URL, json=_body(),
            headers={**creator, "Idempotency-Key": KEY},
        ).json()["data"]["job_id"]

        resp = client.get(
            f"/api/agent/tools/refresh/{job_id}", headers=other)
        assert resp.status_code == 404
        assert resp.json()["error"]["code"] == "not_found"


class TestBacktestParamValidation:
    def test_normalizes_and_dedupes(self):
        clean = svc.validate_backtest_params({
            "fund_codes": ["000001", " 000001 ", "110011"],
            "start_date": "2024-01-01",
            "end_date": "2024-03-31",
            "amount_per_period": 100,
        })
        assert clean["fund_codes"] == ["000001", "110011"]
        assert clean["amount_per_period"] == 100.0
        assert clean["cadence"] == "month"
        assert clean["include_lumpsum"] is True
        assert clean["include_curve"] is True
        assert clean["include_periods"] is False
        assert clean["max_points"] == 365

    def test_rejects_future_end_date(self):
        with pytest.raises(svc.RefreshValidationError) as exc:
            svc.validate_backtest_params({
                "fund_codes": ["000001"],
                "start_date": "2024-01-01",
                "end_date": "2999-01-01",
                "amount_per_period": 100,
            })
        assert exc.value.field == "end_date"

    def test_rejects_amount_over_limit(self):
        with pytest.raises(svc.RefreshValidationError) as exc:
            svc.validate_backtest_params({
                "fund_codes": ["000001"],
                "start_date": "2024-01-01",
                "end_date": "2024-03-31",
                "amount_per_period": 1_000_001,
            })
        assert exc.value.field == "amount_per_period"
