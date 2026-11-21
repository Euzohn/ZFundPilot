"""db 层测试：SQLite 并发 PRAGMA（WAL + busy_timeout）与 AI 用量时区。"""
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import pytest

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


def test_update_fund_purchase_status_roundtrip():
    """申购状态写入后可从 get_fund 读回。"""
    from zfundpilot.models import Fund

    with TemporaryDirectory() as d:
        with patch.object(config, "DB_PATH", _tmp_db_path(d)):
            db.init_db()
            db.upsert_fund(Fund("160213", "国泰纳斯达克100", "QDII"))
            db.update_fund_purchase_status("160213", "暂停申购", 100.0, 10.0)
            fund = db.get_fund("160213")
            assert fund is not None
            assert fund.purchase_status == "暂停申购"
            assert fund.daily_limit == 100.0
            assert fund.min_purchase == 10.0


def test_upsert_fund_preserves_purchase_status():
    """元数据刷新（upsert_fund）不覆盖已写入的申购状态。"""
    from zfundpilot.models import Fund

    with TemporaryDirectory() as d:
        with patch.object(config, "DB_PATH", _tmp_db_path(d)):
            db.init_db()
            db.upsert_fund(Fund("001", "测试基金", "混合型"))
            db.update_fund_purchase_status("001", "限大额", 5000.0, 10.0)
            db.upsert_fund(Fund("001", "测试基金改名", "混合型"))
            fund = db.get_fund("001")
            assert fund is not None
            assert fund.fund_name == "测试基金改名"
            assert fund.purchase_status == "限大额"
            assert fund.daily_limit == 5000.0


def test_init_db_purchase_status_idempotent():
    """重复 init_db 不报错（迁移幂等）。"""
    with TemporaryDirectory() as d:
        with patch.object(config, "DB_PATH", _tmp_db_path(d)):
            db.init_db()
            db.init_db()
            with db.get_connection() as conn:
                cols = {r["name"] for r in
                        conn.execute("PRAGMA table_info(funds)").fetchall()}
            assert {"purchase_status", "daily_limit", "min_purchase"} <= cols


def test_update_fund_risk_level_roundtrip():
    """风险等级写入后可从 get_fund 读回。"""
    from zfundpilot.models import Fund

    with TemporaryDirectory() as d:
        with patch.object(config, "DB_PATH", _tmp_db_path(d)):
            db.init_db()
            db.upsert_fund(Fund("005827", "易方达蓝筹精选", "混合型"))
            db.update_fund_risk_level("005827", "中高风险")
            fund = db.get_fund("005827")
            assert fund is not None
            assert fund.risk_level == "中高风险"


def test_upsert_fund_preserves_risk_level():
    """元数据刷新（upsert_fund）不覆盖已写入的风险等级。"""
    from zfundpilot.models import Fund

    with TemporaryDirectory() as d:
        with patch.object(config, "DB_PATH", _tmp_db_path(d)):
            db.init_db()
            db.upsert_fund(Fund("001", "测试基金", "混合型"))
            db.update_fund_risk_level("001", "高风险")
            db.upsert_fund(Fund("001", "测试基金改名", "混合型"))
            fund = db.get_fund("001")
            assert fund is not None
            assert fund.fund_name == "测试基金改名"
            assert fund.risk_level == "高风险"


def test_init_db_risk_level_idempotent():
    """重复 init_db 不报错（risk_level 迁移幂等）。"""
    with TemporaryDirectory() as d:
        with patch.object(config, "DB_PATH", _tmp_db_path(d)):
            db.init_db()
            db.init_db()
            with db.get_connection() as conn:
                cols = {r["name"] for r in
                        conn.execute("PRAGMA table_info(funds)").fetchall()}
            assert "risk_level" in cols


def test_trade_calendar_roundtrip():
    """交易日历 upsert + is_trading_day 三态（空表/范围内/超范围）。"""
    with TemporaryDirectory() as d:
        with patch.object(config, "DB_PATH", _tmp_db_path(d)):
            db.init_db()
            # 空表 → 退化周末判断（周六休、工作日放行）
            assert db.is_trading_day("2026-10-03") is False  # 周六
            assert db.is_trading_day("2026-10-01") is True   # 周四（退化工作日放行）
            # 写入日历
            n = db.upsert_trade_calendar(["2026-09-30", "2026-10-08", "2026-10-09"])
            assert n == 3
            assert db.is_trading_day("2026-10-08") is True
            assert db.is_trading_day("2026-09-30") is True
            assert db.is_trading_day("2026-10-01") is False  # 范围内非交易日（国庆）
            # 超出覆盖范围（max=2026-10-09）→ 退化周末判断
            assert db.is_trading_day("2027-01-02") is False  # 周六
            assert db.is_trading_day("2027-01-04") is True   # 周一


def test_trade_calendar_upsert_idempotent():
    """重复 upsert 不报错且不重复。"""
    with TemporaryDirectory() as d:
        with patch.object(config, "DB_PATH", _tmp_db_path(d)):
            db.init_db()
            db.upsert_trade_calendar(["2026-10-08"])
            db.upsert_trade_calendar(["2026-10-08"])
            with db.get_connection() as conn:
                cnt = conn.execute(
                    "SELECT COUNT(*) AS c FROM trade_calendar"
                ).fetchone()["c"]
            assert cnt == 1


# ---------------------------------------------------------------------------
# 表重建迁移：原子性 / 失败可重入
# ---------------------------------------------------------------------------
class _PartialFailConn:
    """连接代理：executescript 逐句执行并在指定语句处抛错。

    模拟「迁移中途失败」（磁盘满等）。脚本已含 BEGIN/COMMIT，抛错后由
    外层 get_connection 整体回滚，用于验证正式表不丢、无残留。
    """

    def __init__(self, conn: sqlite3.Connection, fail_on: str):
        self._conn = conn
        self._fail_on = fail_on

    def __getattr__(self, name):
        return getattr(self._conn, name)

    def executescript(self, script: str):
        self._conn.commit()  # 真实 executescript 会先隐式提交挂起事务
        for stmt in script.split(";"):
            sql = stmt.strip()
            if not sql:
                continue
            if self._fail_on in sql:
                raise sqlite3.OperationalError("模拟磁盘满：迁移中途失败")
            self._conn.execute(sql)


# 各重建迁移的「旧 schema」构造 + 种子数据（含应被清理/去重的脏行）
_REBUILD_SETUPS = {
    "transactions": """
        DROP TABLE transactions;
        CREATE TABLE transactions (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            fund_code  TEXT NOT NULL,
            action     TEXT NOT NULL CHECK(action IN ('buy', 'sell')),
            date       TEXT NOT NULL,
            amount     REAL NOT NULL,
            shares     REAL NOT NULL,
            nav        REAL,
            fee        REAL DEFAULT 0,
            channel    TEXT DEFAULT '',
            note       TEXT DEFAULT '',
            is_t1      INTEGER DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now','localtime'))
        );
        INSERT INTO transactions(fund_code, action, date, amount, shares)
            VALUES('001', 'buy', '2026-01-05', 1000, 500);
    """,
    "dividend_alerts_unique": """
        DROP TABLE dividend_alerts;
        CREATE TABLE dividend_alerts (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            fund_code        TEXT NOT NULL,
            fund_name        TEXT DEFAULT '',
            record_date      TEXT,
            ex_date          TEXT,
            per_share        REAL,
            pay_date         TEXT,
            held_shares      REAL,
            estimated_amount REAL,
            dividend_method  TEXT DEFAULT 'cash',
            status           TEXT DEFAULT 'pending',
            created_at       TEXT DEFAULT (datetime('now','localtime')),
            resolved_at      TEXT,
            tx_id            INTEGER,
            alert_type       TEXT DEFAULT 'dividend',
            triggered_return REAL,
            threshold        REAL
        );
        INSERT INTO dividend_alerts(fund_code, ex_date) VALUES('001', '2026-01-10');
        INSERT INTO dividend_alerts(fund_code, ex_date) VALUES('001', '2026-01-10');
    """,
    "dividend_alerts_channel": """
        DROP TABLE dividend_alerts;
        CREATE TABLE dividend_alerts (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            fund_code        TEXT NOT NULL,
            fund_name        TEXT DEFAULT '',
            record_date      TEXT,
            ex_date          TEXT,
            per_share        REAL,
            pay_date         TEXT,
            held_shares      REAL,
            estimated_amount REAL,
            dividend_method  TEXT DEFAULT 'cash',
            status           TEXT DEFAULT 'pending',
            created_at       TEXT DEFAULT (datetime('now','localtime')),
            resolved_at      TEXT,
            tx_id            INTEGER,
            alert_type       TEXT DEFAULT 'dividend',
            triggered_return REAL,
            threshold        REAL,
            UNIQUE(fund_code, ex_date, alert_type)
        );
        INSERT INTO dividend_alerts(fund_code, ex_date) VALUES('001', '2026-01-10');
        INSERT INTO dividend_alerts(fund_code, ex_date) VALUES('001', '2026-02-10');
    """,
    "auto_invest_plans": """
        DROP TABLE auto_invest_plans;
        CREATE TABLE auto_invest_plans (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            fund_code    TEXT NOT NULL,
            amount       REAL NOT NULL,
            cadence      TEXT NOT NULL,
            day_of_week  INTEGER,
            day_of_month INTEGER,
            channel      TEXT DEFAULT '',
            note         TEXT DEFAULT '定投',
            enabled      INTEGER DEFAULT 1,
            next_run     TEXT,
            last_run     TEXT,
            last_tx_id   INTEGER,
            created_at   TEXT DEFAULT (datetime('now','localtime')),
            updated_at   TEXT DEFAULT (datetime('now','localtime'))
        );
        INSERT INTO auto_invest_plans(fund_code, amount, cadence)
            VALUES('001', 100, 'week');
        INSERT INTO auto_invest_plans(fund_code, amount, cadence)
            VALUES('002', 0, 'week');
    """,
    "nav_history": """
        DROP TABLE nav_history;
        CREATE TABLE nav_history (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            fund_code       TEXT NOT NULL,
            date            TEXT NOT NULL,
            nav             REAL NOT NULL,
            accumulated_nav REAL,
            source          TEXT DEFAULT 'akshare',
            created_at      TEXT DEFAULT (datetime('now','localtime')),
            UNIQUE(fund_code, date)
        );
        INSERT INTO nav_history(fund_code, date, nav) VALUES('001', '2026-01-05', 1.5);
        INSERT INTO nav_history(fund_code, date, nav) VALUES('001', '2026-01-06', 0);
    """,
}

# (用例名, 正式表名, 迁移函数名, 种子行数, 迁移后行数, 迁移后 schema 特征)
_REBUILD_CASES = [
    ("transactions", "transactions", "_migrate_relax_transactions_schema",
     1, 1, "amount >= 0"),
    ("dividend_alerts_unique", "dividend_alerts", "_migrate_dividend_alerts_unique",
     2, 1, "UNIQUE(fund_code, ex_date, alert_type)"),
    ("dividend_alerts_channel", "dividend_alerts", "_migrate_dividend_alerts_channel",
     2, 2, "UNIQUE(fund_code, ex_date, alert_type, channel)"),
    ("auto_invest_plans", "auto_invest_plans", "_migrate_auto_invest_plans_check",
     2, 1, "amount > 0"),
    ("nav_history", "nav_history", "_migrate_nav_history_check",
     2, 1, "nav > 0"),
]


@pytest.mark.parametrize("fail_point", ["drop", "rename"])
@pytest.mark.parametrize(
    "case", _REBUILD_CASES, ids=[c[0] for c in _REBUILD_CASES]
)
def test_rebuild_migration_atomic_and_reentrant(case, fail_point):
    """迁移中途失败整体回滚（正式表不丢），重跑成功且清理残留 *_new。

    fail_point=drop：DROP 正式表前失败；rename：DROP 之后、RENAME 之前
    失败（旧实现最危险的崩溃窗口）。两种情况旧表数据都必须完好。
    """
    name, table, migrate_name, seed_count, final_count, schema_mark = case
    with TemporaryDirectory() as d:
        with patch.object(config, "DB_PATH", _tmp_db_path(d)):
            db.init_db()
            with db.get_connection() as conn:
                conn.executescript(_REBUILD_SETUPS[name])
                # 模拟历史失败残留的中间表（旧实现会在此死循环）
                conn.execute(f"CREATE TABLE {table}_new (leftover TEXT)")
            migrate = getattr(db, migrate_name)
            fail_on = (
                f"DROP TABLE {table}" if fail_point == "drop"
                else f"ALTER TABLE {table}_new RENAME"
            )
            real_gc = db.get_connection

            @contextmanager
            def failing_gc(write=False):
                with real_gc(write=write) as conn:
                    yield _PartialFailConn(conn, fail_on)

            with patch.object(db, "get_connection", failing_gc):
                with pytest.raises(sqlite3.OperationalError):
                    migrate()

            # 失败后：正式表仍在、种子数据未丢（含脏数据清理也被回滚）
            with db.get_connection() as conn:
                names = {r["name"] for r in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'")}
                assert table in names
                cnt = conn.execute(
                    f"SELECT COUNT(*) c FROM {table}").fetchone()["c"]
                assert cnt == seed_count

            # 重入：再次执行成功，残留中间表被清理，脏行按约束清理/去重
            migrate()
            with db.get_connection() as conn:
                names = {r["name"] for r in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'")}
                assert table in names
                assert f"{table}_new" not in names
                cnt = conn.execute(
                    f"SELECT COUNT(*) c FROM {table}").fetchone()["c"]
                assert cnt == final_count
                sql = conn.execute(
                    "SELECT sql FROM sqlite_master WHERE type='table' AND name=?",
                    (table,),
                ).fetchone()["sql"]
                assert schema_mark in sql


def test_init_db_skips_redundant_indexes():
    """被判冗余的三个索引不再于 init_db 创建（消除每次启动建了又删）。"""
    with TemporaryDirectory() as d:
        with patch.object(config, "DB_PATH", _tmp_db_path(d)):
            # 屏蔽删冗余索引的迁移，单独验证建表脚本不再创建它们
            with patch.object(db, "_migrate_add_indexes", lambda: None):
                db.init_db()
            with db.get_connection() as conn:
                names = {r["name"] for r in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='index'")}
            assert not (
                {"idx_tx_code", "idx_nav_code_date", "idx_index_code_date"} & names
            )
            assert "idx_tx_date" in names


def test_delete_transaction_uses_write_transaction():
    """delete_transaction 先读后写，必须走 BEGIN IMMEDIATE（write=True）。"""
    with TemporaryDirectory() as d:
        with patch.object(config, "DB_PATH", _tmp_db_path(d)):
            db.init_db()
            calls: list[bool] = []
            real_gc = db.get_connection

            @contextmanager
            def spy(write=False):
                calls.append(write)
                with real_gc(write=write) as conn:
                    yield conn

            with patch.object(db, "get_connection", spy):
                db.delete_transaction(999)
            assert calls == [True]


def test_delete_transaction_unlinks_conversion_pair():
    """删除转换腿后另一腿解关联（conversion_id 置空），行为不变。"""
    from zfundpilot.models import Transaction

    with TemporaryDirectory() as d:
        with patch.object(config, "DB_PATH", _tmp_db_path(d)):
            db.init_db()
            sell = Transaction(fund_code="001", action="sell",
                               date="2026-01-05", shares=100, nav=1.5)
            buy = Transaction(fund_code="002", action="buy",
                              date="2026-01-05", amount=150, nav=1.5)
            from_id, to_id = db.add_conversion(sell, buy)
            db.delete_transaction(from_id)
            remaining = db.get_transactions()
            assert len(remaining) == 1
            assert remaining[0].id == to_id
            assert remaining[0].conversion_id == ""


def test_add_dividend_alert_conflict_returns_existing_id():
    """UNIQUE 冲突（竞态败者）返回已有行 id，而非 0。"""
    with TemporaryDirectory() as d:
        with patch.object(config, "DB_PATH", _tmp_db_path(d)):
            db.init_db()
            alert = {
                "fund_code": "001", "fund_name": "测试基金",
                "ex_date": "2026-01-10", "per_share": 0.05,
                "held_shares": 1000, "estimated_amount": 50,
                "channel": "支付宝",
            }
            first = db.add_dividend_alert(alert)
            assert first > 0
            # 同唯一键重复插入：返回已有 id，不新增行
            second = db.add_dividend_alert(dict(alert))
            assert second == first
            assert len(db.get_dividend_alerts()) == 1
            # 不同渠道不冲突，正常新增
            other = db.add_dividend_alert({**alert, "channel": "理财通"})
            assert other > 0
            assert other != first
            assert len(db.get_dividend_alerts()) == 2


def test_purge_audit_logs_retention():
    """purge_audit_logs 删除早于保留期的审计日志并返回删除数。"""
    with TemporaryDirectory() as d:
        with patch.object(config, "DB_PATH", _tmp_db_path(d)):
            db.init_db()
            now = datetime.now(config.TIMEZONE)
            stamps = [
                (now - timedelta(days=120)).isoformat(),  # 超期 → 删
                (now - timedelta(days=10)).isoformat(),   # 保留
                now.isoformat(),                          # 保留
            ]
            with db.get_connection() as conn:
                for ts in stamps:
                    conn.execute(
                        "INSERT INTO audit_log(ts, action) VALUES(?, 'login')",
                        (ts,),
                    )
            assert db.purge_audit_logs(90) == 1
            assert len(db.fetch_audit_logs(limit=100)) == 2
            # 默认保留期 90 天；重复清理返回 0
            assert db.purge_audit_logs() == 0
            assert len(db.fetch_audit_logs(limit=100)) == 2
