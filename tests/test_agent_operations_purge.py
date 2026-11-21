"""幂等操作记录定期清理测试：purge_agent_operations 只清过期超宽限的记录。"""
from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import MagicMock

import pytest

from zfundpilot import config, db, scheduler


@pytest.fixture
def temp_db(monkeypatch):
    with TemporaryDirectory() as d:
        monkeypatch.setattr(config, "DB_PATH", str(Path(d) / "test.db"))
        db.init_db()
        yield


def _insert(key_hash: str, *, expires_at: str | None, created_at: str) -> None:
    with db.get_connection(write=True) as conn:
        db.insert_operation(
            conn, principal_type="agent_token", principal_id="1",
            key_hash=key_hash, operation="record_transaction",
            params_digest="digest", status="succeeded", result_json="{}",
            audit_id=None, created_at=created_at, expires_at=expires_at)


def _keys() -> list[str]:
    with db.get_connection() as conn:
        return sorted(r["key_hash"] for r in
                      conn.execute("SELECT key_hash FROM agent_operations"))


class TestPurgeAgentOperations:
    def test_purges_only_expired_beyond_grace(self, temp_db):
        now = datetime.now(config.TIMEZONE)
        # 过期 60 天前 → 超出 30 天宽限，应清理
        _insert("old", expires_at=(now - timedelta(days=60)).isoformat(),
                created_at=(now - timedelta(days=150)).isoformat())
        # 过期 10 天前 → 宽限内，保留
        _insert("grace", expires_at=(now - timedelta(days=10)).isoformat(),
                created_at=(now - timedelta(days=100)).isoformat())
        # 未过期（TTL 内）→ 保留
        _insert("fresh", expires_at=(now + timedelta(days=90)).isoformat(),
                created_at=now.isoformat())
        # 无 expires_at → 保留
        _insert("null", expires_at=None, created_at=now.isoformat())

        cutoff = (now - timedelta(days=30)).isoformat()
        removed = db.purge_agent_operations(cutoff)
        assert removed == 1
        assert _keys() == ["fresh", "grace", "null"]

    def test_never_touches_unexpired(self, temp_db):
        now = datetime.now(config.TIMEZONE)
        for i in range(3):
            _insert(f"k{i}", expires_at=(now + timedelta(days=i)).isoformat(),
                    created_at=now.isoformat())
        cutoff = now.isoformat()
        assert db.purge_agent_operations(cutoff) == 0
        assert len(_keys()) == 3

    def test_scheduler_helper_uses_grace_window(self, temp_db, monkeypatch):
        """purge_agent_operations_daily 以 now − 30 天为 cutoff 清理。"""
        now = datetime.now(config.TIMEZONE)
        # 过期 31 天前（created_at 121 天前 + 90 天 TTL）→ 被清理
        _insert("just_over", expires_at=(now - timedelta(days=31)).isoformat(),
                created_at=(now - timedelta(days=121)).isoformat())
        # 过期 29 天前 → 宽限内，保留
        _insert("just_under", expires_at=(now - timedelta(days=29)).isoformat(),
                created_at=(now - timedelta(days=119)).isoformat())

        removed = scheduler.purge_agent_operations_daily()
        assert removed == 1
        assert _keys() == ["just_under"]


class TestAuditLogPurge:
    """每日清理同时调用 db.purge_audit_logs(90)（B4 契约）。

    B4 与本修复并行开发：db.purge_audit_logs 缺席时用 mock 钉住调用契约
    （raising=False），合入后集成用例自动生效。
    """

    def test_daily_purge_calls_audit_logs_90(self, temp_db, monkeypatch):
        mock_purge = MagicMock(return_value=3)
        monkeypatch.setattr(db, "purge_audit_logs", mock_purge, raising=False)
        scheduler.purge_agent_operations_daily()
        mock_purge.assert_called_once_with(90)

    def test_audit_purge_failure_does_not_break_ops_purge(self, temp_db, monkeypatch):
        """审计清理失败（含 B4 未合入时的 AttributeError）不影响幂等记录清理。"""
        now = datetime.now(config.TIMEZONE)
        _insert("old", expires_at=(now - timedelta(days=60)).isoformat(),
                created_at=(now - timedelta(days=150)).isoformat())
        monkeypatch.setattr(
            db, "purge_audit_logs",
            MagicMock(side_effect=RuntimeError("boom")), raising=False)
        removed = scheduler.purge_agent_operations_daily()
        assert removed == 1
        assert _keys() == []

    def test_audit_purge_integration_when_available(self, temp_db):
        """B4 合入后：真实 purge_audit_logs 只删 90 天前的审计行。"""
        if not hasattr(db, "purge_audit_logs"):
            pytest.skip("db.purge_audit_logs 尚未由 B4 提供")
        now = datetime.now(config.TIMEZONE)
        with db.get_connection(write=True) as conn:
            conn.execute(
                "INSERT INTO audit_log(ts, action) VALUES(?, ?)",
                ((now - timedelta(days=120)).isoformat(), "old_action"))
            conn.execute(
                "INSERT INTO audit_log(ts, action) VALUES(?, ?)",
                ((now - timedelta(days=10)).isoformat(), "recent_action"))
        scheduler.purge_agent_operations_daily()
        with db.get_connection() as conn:
            actions = [r["action"] for r in
                       conn.execute("SELECT action FROM audit_log")]
        assert actions == ["recent_action"]
