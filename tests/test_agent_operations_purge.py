"""幂等操作记录定期清理测试：purge_agent_operations 只清过期超宽限的记录。"""
from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory

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
