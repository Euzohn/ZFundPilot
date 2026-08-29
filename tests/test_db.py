"""db 层测试：SQLite 并发 PRAGMA（WAL + busy_timeout）与 AI 用量时区。"""
from datetime import datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from zfundpilot import config, db


def _tmp_db_path(d: str) -> str:
    return str(Path(d) / "test.db")


def test_connection_sets_wal_and_busy_timeout():
    """init_db 后数据库处于 WAL 模式，且每次连接设置 busy_timeout=5000。"""
    with TemporaryDirectory() as d:
        with patch.object(config, "DB_PATH", _tmp_db_path(d)):
            db.init_db()
            with db.get_connection() as conn:
                journal = conn.execute("PRAGMA journal_mode").fetchone()[0]
                busy = conn.execute("PRAGMA busy_timeout").fetchone()[0]
            assert journal == "wal"
            assert busy == 5000


def test_get_connection_sets_busy_timeout_without_init_db():
    """busy_timeout 由 get_connection 本身设置（无需 init_db），避免写入互相阻塞。"""
    with TemporaryDirectory() as d:
        with patch.object(config, "DB_PATH", _tmp_db_path(d)):
            with db.get_connection() as conn:
                busy = conn.execute("PRAGMA busy_timeout").fetchone()[0]
            assert busy == 5000


def test_add_ai_usage_stores_localtime():
    """add_ai_usage 写入本地时区（非 UTC），与读取侧一致。"""
    with TemporaryDirectory() as d:
        with patch.object(config, "DB_PATH", _tmp_db_path(d)):
            db.init_db()
            db.add_ai_usage("gpt", 1, 2, 3, 1)
            local = datetime.now(config.TIMEZONE)
            with db.get_connection() as conn:
                row = conn.execute(
                    "SELECT created_at FROM ai_usage ORDER BY id DESC LIMIT 1"
                ).fetchone()
            stored = datetime.fromisoformat(row["created_at"])
            assert stored.date() == local.date()
            assert abs((local.replace(tzinfo=None) - stored).total_seconds()) < 120


def test_ai_usage_stats_today_uses_localtime():
    """get_ai_usage_stats 的今日过滤按本地日归并，不含昨天的用量。"""
    with TemporaryDirectory() as d:
        with patch.object(config, "DB_PATH", _tmp_db_path(d)):
            db.init_db()
            tz = config.TIMEZONE
            today = datetime.now(tz)
            yesterday = today - timedelta(days=1)
            with db.get_connection() as conn:
                conn.execute(
                    "INSERT INTO ai_usage(created_at,model,prompt_tokens,"
                    "completion_tokens,total_tokens,turns)"
                    " VALUES(?,?,?,?,?,?)",
                    (today.strftime("%Y-%m-%d 09:00:00"), "gpt", 10, 10, 20, 1),
                )
                conn.execute(
                    "INSERT INTO ai_usage(created_at,model,prompt_tokens,"
                    "completion_tokens,total_tokens,turns)"
                    " VALUES(?,?,?,?,?,?)",
                    (yesterday.strftime("%Y-%m-%d 09:00:00"), "gpt", 5, 5, 10, 1),
                )
            stats = db.get_ai_usage_stats()
            assert stats["today"] == 20
            assert stats["total"] == 30


def test_ai_usage_daily_axis_uses_localtime():
    """get_ai_usage_daily 日期轴末位为本地今日，按本地日正确归并。"""
    with TemporaryDirectory() as d:
        with patch.object(config, "DB_PATH", _tmp_db_path(d)):
            db.init_db()
            tz = config.TIMEZONE
            today = datetime.now(tz)
            yesterday = today - timedelta(days=1)
            with db.get_connection() as conn:
                conn.execute(
                    "INSERT INTO ai_usage(created_at,model,prompt_tokens,"
                    "completion_tokens,total_tokens,turns)"
                    " VALUES(?,?,?,?,?,?)",
                    (today.strftime("%Y-%m-%d 09:00:00"), "gpt", 10, 10, 20, 1),
                )
                conn.execute(
                    "INSERT INTO ai_usage(created_at,model,prompt_tokens,"
                    "completion_tokens,total_tokens,turns)"
                    " VALUES(?,?,?,?,?,?)",
                    (yesterday.strftime("%Y-%m-%d 09:00:00"), "gpt", 5, 5, 10, 1),
                )
            daily = db.get_ai_usage_daily(7)
            assert daily[-1]["date"] == today.strftime("%Y-%m-%d")
            assert daily[-1]["tokens"] == 20
            by_date = {e["date"]: e["tokens"] for e in daily}
            assert by_date.get(yesterday.strftime("%Y-%m-%d")) == 10
