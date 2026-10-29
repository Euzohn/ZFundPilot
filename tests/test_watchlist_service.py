"""自选受控写入服务测试：幂等、版本冲突、墓碑恢复与审计原子性。"""
from __future__ import annotations

import json
import threading
from datetime import datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

from zfundpilot import config, db
from zfundpilot import watchlist_service as svc
from zfundpilot.analysis import clear_analysis_cache
from zfundpilot.models import Fund

KEY_A = "test-key-aaaaaaaaaaaa"
KEY_B = "test-key-bbbbbbbbbbbb"


@pytest.fixture
def temp_db(monkeypatch):
    with TemporaryDirectory() as d:
        monkeypatch.setattr(config, "DB_PATH", str(Path(d) / "test.db"))
        db.init_db()
        db.upsert_fund(Fund("005827", "易方达蓝筹精选", "混合型", "消费"))
        clear_analysis_cache()
        yield


def _agent(principal_id: str = "1") -> svc.Principal:
    return svc.Principal("agent_token", principal_id, f"agent:test{principal_id}")


def _web() -> svc.Principal:
    return svc.Principal("web", "admin", "admin")


def _add(code: str = "005827", *, note: str = "", group: str = "",
         key: str = KEY_A, principal: svc.Principal | None = None) -> svc.WatchlistResult:
    return svc.add_item(
        principal or _agent(), fund_code=code, note=note, group_name=group,
        idempotency_key=key)


def _audit_actions() -> list[str]:
    return [row["action"] for row in db.fetch_audit_logs(100)]


class TestAdd:
    def test_creates_with_revision_audit_and_operation(self, temp_db):
        result = _add(note="观察", group="核心")

        assert result.http_status == 200
        assert result.code == "created"
        assert result.replayed is False
        assert result.data["revision"] == 1
        assert result.data["after"]["note"] == "观察"
        assert result.data["operation_id"] > 0
        assert result.data["audit_id"] > 0

        rows = db.get_watchlist()
        assert len(rows) == 1
        assert rows[0]["group_name"] == "核心"
        assert rows[0]["revision"] == 1
        assert "watchlist_add" in _audit_actions()

    def test_rejects_unregistered_fund(self, temp_db):
        result = _add("999999")

        assert result.http_status == 409
        assert result.code == "fund_not_registered"
        assert db.get_watchlist() == []
        assert "watchlist_add" in _audit_actions()

    def test_existing_item_is_not_overwritten(self, temp_db):
        _add(note="原备注", group="原分组")
        result = _add(note="新备注", group="新分组", key=KEY_B)

        assert result.http_status == 409
        assert result.code == "already_exists"
        rows = db.get_watchlist()
        assert len(rows) == 1
        assert rows[0]["note"] == "原备注"
        assert rows[0]["group_name"] == "原分组"

    def test_same_key_same_params_replays_once(self, temp_db):
        first = _add(note="观察")
        second = _add(note="观察")

        assert first.replayed is False
        assert second.replayed is True
        assert second.http_status == 200
        assert second.data["operation_id"] == first.data["operation_id"]
        assert len(db.get_watchlist()) == 1

    def test_same_key_different_params_conflicts(self, temp_db):
        _add(note="观察")
        result = _add(note="别的备注")

        assert result.http_status == 409
        assert result.code == "idempotency_conflict"
        assert len(db.get_watchlist()) == 1

    def test_same_key_across_operations_conflicts(self, temp_db):
        _add()
        result = svc.remove_item(
            _agent(), fund_code="005827", expected_revision=1,
            idempotency_key=KEY_A)

        assert result.http_status == 409
        assert result.code == "idempotency_conflict"
        assert len(db.get_watchlist()) == 1

    def test_expired_key_is_not_reused(self, temp_db):
        first = _add()
        past = (datetime.now(config.TIMEZONE) - timedelta(days=1)).isoformat()
        with db.get_connection() as conn:
            conn.execute(
                "UPDATE agent_operations SET expires_at=? WHERE id=?",
                (past, first.data["operation_id"]))

        result = _add()
        assert result.http_status == 409
        assert result.code == "idempotency_expired"

    def test_concurrent_same_key_writes_once(self, temp_db):
        results: list[svc.WatchlistResult] = []
        errors: list[BaseException] = []
        barrier = threading.Barrier(6)

        def worker() -> None:
            try:
                barrier.wait(timeout=5)
                results.append(_add(note="并发"))
            except BaseException as exc:  # pragma: no cover - 失败时便于定位
                errors.append(exc)

        threads = [threading.Thread(target=worker) for _ in range(6)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=10)

        assert not errors
        assert len(results) == 6
        assert all(r.http_status == 200 for r in results)
        assert sum(1 for r in results if not r.replayed) == 1
        assert len({r.data["operation_id"] for r in results}) == 1
        assert len(db.get_watchlist()) == 1

    def test_validation_errors_do_not_write(self, temp_db):
        with pytest.raises(svc.WatchlistValidationError):
            _add("12345")
        with pytest.raises(svc.WatchlistValidationError):
            _add(note="x" * 501)
        with pytest.raises(svc.WatchlistValidationError):
            _add(key="short")

        assert db.get_watchlist() == []
        assert not _audit_actions()


class TestUpdate:
    def test_updates_and_bumps_revision(self, temp_db):
        _add(note="旧", group="旧组")
        result = svc.update_item(
            _agent(), fund_code="005827", expected_revision=1,
            note="新", group_name="新组", idempotency_key=KEY_B)

        assert result.http_status == 200
        assert result.code == "updated"
        assert result.data["changed"] is True
        assert result.data["revision"] == 2
        assert result.data["before"]["note"] == "旧"
        assert result.data["after"]["note"] == "新"
        assert db.get_watchlist()[0]["revision"] == 2

    def test_unchanged_patch_keeps_revision(self, temp_db):
        _add(note="同")
        result = svc.update_item(
            _agent(), fund_code="005827", expected_revision=1,
            note="同", idempotency_key=KEY_B)

        assert result.http_status == 200
        assert result.code == "unchanged"
        assert result.data["changed"] is False
        assert result.data["revision"] == 1

    def test_stale_revision_does_not_overwrite(self, temp_db):
        _add(note="原")
        svc.update_item(_agent(), fund_code="005827", expected_revision=1,
                        note="第一次", idempotency_key=KEY_B)
        result = svc.update_item(
            _agent(), fund_code="005827", expected_revision=1,
            note="第二次", idempotency_key="test-key-cccccccccccc")

        assert result.http_status == 409
        assert result.code == "revision_conflict"
        assert result.data["current_revision"] == 2
        assert db.get_watchlist()[0]["note"] == "第一次"

    def test_missing_item_returns_404(self, temp_db):
        result = svc.update_item(
            _agent(), fund_code="005827", expected_revision=1,
            note="x", idempotency_key=KEY_A)
        assert result.http_status == 404
        assert result.code == "not_found"

    def test_empty_patch_is_rejected(self, temp_db):
        _add()
        with pytest.raises(svc.WatchlistValidationError):
            svc.update_item(_agent(), fund_code="005827", expected_revision=1,
                            idempotency_key=KEY_B)


class TestRemoveAndRestore:
    def test_remove_keeps_tombstone(self, temp_db):
        _add(note="前值", group="观察组")
        result = svc.remove_item(
            _agent(), fund_code="005827", expected_revision=1,
            idempotency_key=KEY_B)

        assert result.http_status == 200
        assert result.code == "removed"
        assert result.data["revision"] == 2
        assert result.data["before"]["note"] == "前值"
        assert result.data["after"] is None
        assert db.get_watchlist() == []
        deleted = svc.list_deleted()
        assert len(deleted) == 1
        assert deleted[0]["revision"] == 2
        assert deleted[0]["group_name"] == "观察组"

    def test_stale_remove_is_rejected(self, temp_db):
        _add()
        svc.update_item(_agent(), fund_code="005827", expected_revision=1,
                        note="改", idempotency_key=KEY_B)
        result = svc.remove_item(
            _agent(), fund_code="005827", expected_revision=1,
            idempotency_key="test-key-cccccccccccc")

        assert result.http_status == 409
        assert result.code == "revision_conflict"
        assert len(db.get_watchlist()) == 1

    def test_readd_after_delete_uses_new_revision(self, temp_db):
        _add()
        svc.remove_item(_agent(), fund_code="005827", expected_revision=1,
                        idempotency_key=KEY_B)
        result = _add(key="test-key-cccccccccccc")

        assert result.http_status == 200
        assert result.data["revision"] == 3
        # 旧的删除版本不能用来恢复已重建对象
        stale = svc.restore_item(
            _web(), fund_code="005827", expected_revision=2,
            idempotency_key="test-key-dddddddddddd")
        assert stale.http_status == 404
        assert stale.code == "not_found"


class TestRestore:
    def _deleted(self) -> None:
        _add(note="前值", group="观察组")
        svc.remove_item(_agent(), fund_code="005827", expected_revision=1,
                        idempotency_key=KEY_B)

    def test_web_restore_brings_back_values(self, temp_db):
        self._deleted()
        result = svc.restore_item(
            _web(), fund_code="005827", expected_revision=2,
            idempotency_key="test-key-cccccccccccc")

        assert result.http_status == 200
        assert result.code == "restored"
        assert result.data["revision"] == 3
        assert result.data["after"]["note"] == "前值"
        assert result.data["after"]["group_name"] == "观察组"
        rows = db.get_watchlist()
        assert len(rows) == 1
        assert rows[0]["revision"] == 3
        assert svc.list_deleted() == []

    def test_stale_restore_is_rejected(self, temp_db):
        self._deleted()
        result = svc.restore_item(
            _web(), fund_code="005827", expected_revision=1,
            idempotency_key="test-key-cccccccccccc")

        assert result.http_status == 409
        assert result.code == "revision_conflict"
        assert db.get_watchlist() == []

    def test_agent_cannot_restore(self, temp_db):
        self._deleted()
        with pytest.raises(svc.WatchlistValidationError):
            svc.restore_item(
                _agent(), fund_code="005827", expected_revision=2,
                idempotency_key="test-key-cccccccccccc")

    def test_restore_requires_existing_fund(self, temp_db):
        self._deleted()
        with db.get_connection() as conn:
            conn.execute("DELETE FROM funds WHERE fund_code='005827'")
        result = svc.restore_item(
            _web(), fund_code="005827", expected_revision=2,
            idempotency_key="test-key-cccccccccccc")

        assert result.http_status == 409
        assert result.code == "fund_not_registered"

    def test_restore_does_not_duplicate_live_item(self, temp_db):
        self._deleted()
        # 模拟异常状态：墓碑仍在，但对象已被其他路径重建
        with db.get_connection(write=True) as conn:
            db.insert_watchlist_item(conn, "005827", "", "", 5)
        result = svc.restore_item(
            _web(), fund_code="005827", expected_revision=2,
            idempotency_key="test-key-cccccccccccc")

        assert result.http_status == 409
        assert result.code == "already_exists"
        rows = db.get_watchlist()
        assert len(rows) == 1
        assert rows[0]["revision"] == 5


class TestAuditAtomicity:
    def test_success_audit_links_operation(self, temp_db):
        result = _add(note="观察")
        op_id = result.data["operation_id"]

        with db.get_connection() as conn:
            op = conn.execute(
                "SELECT * FROM agent_operations WHERE id=?", (op_id,)
            ).fetchone()
            audit = conn.execute(
                "SELECT * FROM audit_log WHERE id=?", (op["audit_id"],)
            ).fetchone()

        assert op["status"] == "created"
        assert op["operation"] == "add"
        assert op["principal_type"] == "agent_token"
        assert audit["action"] == "watchlist_add"
        detail = json.loads(audit["detail"])
        assert detail["result"] == "created"
        assert detail["replayed"] is False
        assert "note" not in detail  # 不记录备注原文

    def test_failure_is_recorded_and_replayable(self, temp_db):
        first = _add("999999")
        second = _add("999999")

        assert first.code == "fund_not_registered"
        assert second.replayed is True
        assert second.code == "fund_not_registered"

    def test_operation_key_is_not_stored_plaintext(self, temp_db):
        result = _add()
        with db.get_connection() as conn:
            op = conn.execute(
                "SELECT key_hash FROM agent_operations WHERE id=?",
                (result.data["operation_id"],)).fetchone()
        assert op["key_hash"] != KEY_A
        assert len(op["key_hash"]) == 64
