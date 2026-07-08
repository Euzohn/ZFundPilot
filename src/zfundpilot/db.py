"""SQLite 数据库操作层（交易流水驱动）。

表结构：
- funds               基金基础信息（代码/名称/类型/板块）
- transactions        买入/卖出流水
- nav_history         基金净值历史
- portfolio_snapshots 组合每日快照

设计：持仓不再单独存表，而是由 transactions 流水汇总计算（见 analysis.py）。
兼容旧版：若检测到旧 holdings 表，自动迁移为一条买入流水。
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable, Iterator
from contextlib import contextmanager

from . import config
from .models import Fund, NavPoint, Transaction


# ---------------------------------------------------------------------------
# 连接管理
# ---------------------------------------------------------------------------
@contextmanager
def get_connection() -> Iterator[sqlite3.Connection]:
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 初始化 & 迁移
# ---------------------------------------------------------------------------
def init_db() -> None:
    """创建所有表（若不存在），并迁移旧数据。幂等。"""
    with get_connection() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS funds (
                fund_code  TEXT PRIMARY KEY,
                fund_name  TEXT DEFAULT '',
                fund_type  TEXT DEFAULT '其它',
                sector     TEXT DEFAULT '',
                created_at TEXT DEFAULT (datetime('now','localtime')),
                updated_at TEXT DEFAULT (datetime('now','localtime'))
            );

            CREATE TABLE IF NOT EXISTS transactions (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                fund_code  TEXT NOT NULL,
                action     TEXT NOT NULL,
                date       TEXT NOT NULL,
                amount     REAL,
                shares     REAL,
                nav        REAL,
                fee        REAL DEFAULT 0,
                channel    TEXT DEFAULT '',
                note       TEXT DEFAULT '',
                created_at TEXT DEFAULT (datetime('now','localtime'))
            );

            CREATE TABLE IF NOT EXISTS nav_history (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                fund_code       TEXT NOT NULL,
                date            TEXT NOT NULL,
                nav             REAL NOT NULL,
                accumulated_nav REAL,
                source          TEXT DEFAULT 'akshare',
                created_at      TEXT DEFAULT (datetime('now','localtime')),
                UNIQUE(fund_code, date)
            );

            CREATE TABLE IF NOT EXISTS portfolio_snapshots (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                date         TEXT NOT NULL UNIQUE,
                total_cost   REAL NOT NULL,
                total_value  REAL NOT NULL,
                total_profit REAL NOT NULL,
                total_return REAL NOT NULL,
                created_at   TEXT DEFAULT (datetime('now','localtime'))
            );

            CREATE TABLE IF NOT EXISTS ai_usage (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at       TEXT NOT NULL DEFAULT (datetime('now','localtime')),
                model            TEXT DEFAULT '',
                prompt_tokens    INTEGER DEFAULT 0,
                completion_tokens INTEGER DEFAULT 0,
                total_tokens     INTEGER DEFAULT 0,
                turns            INTEGER DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS preferences (
                key   TEXT PRIMARY KEY,
                value TEXT NOT NULL DEFAULT ''
            );

            CREATE INDEX IF NOT EXISTS idx_tx_code ON transactions(fund_code);
            CREATE INDEX IF NOT EXISTS idx_tx_date ON transactions(date);
            CREATE INDEX IF NOT EXISTS idx_nav_code_date
                ON nav_history(fund_code, date);
            """
        )
    _migrate_add_columns()
    _migrate_relax_transactions_schema()
    _migrate_legacy_holdings()


def _migrate_add_columns() -> None:
    """为已存在的旧表补充新增列（如 channel）。幂等。"""
    with get_connection() as conn:
        cols = {r["name"] for r in
                conn.execute("PRAGMA table_info(transactions)").fetchall()}
        if "channel" not in cols:
            conn.execute(
                "ALTER TABLE transactions ADD COLUMN channel TEXT DEFAULT ''"
            )


def _migrate_relax_transactions_schema() -> None:
    """放宽 transactions 表约束：移除 CHECK(action) 和 amount/shares 的 NOT NULL。

    旧表有 CHECK(action IN ('buy','sell')) 和 amount/shares NOT NULL，
    阻止插入 dividend/reinvest 操作和待确认交易（NULL 字段）。
    SQLite 无法直接 ALTER 约束，需重建表。
    """
    with get_connection() as conn:
        row = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='transactions'"
        ).fetchone()
        if not row:
            return
        sql_text = row["sql"]
        if "CHECK" not in sql_text and "NOT NULL" not in sql_text:
            return  # 已是新schema，无需迁移

        conn.executescript(
            """
            CREATE TABLE transactions_new (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                fund_code  TEXT NOT NULL,
                action     TEXT NOT NULL,
                date       TEXT NOT NULL,
                amount     REAL,
                shares     REAL,
                nav        REAL,
                fee        REAL DEFAULT 0,
                channel    TEXT DEFAULT '',
                note       TEXT DEFAULT '',
                created_at TEXT DEFAULT (datetime('now','localtime'))
            );
            INSERT INTO transactions_new
                (id, fund_code, action, date, amount, shares, nav, fee, channel, note, created_at)
            SELECT id, fund_code, action, date, amount, shares, nav, fee, channel, note, created_at
            FROM transactions;
            DROP TABLE transactions;
            ALTER TABLE transactions_new RENAME TO transactions;
            CREATE INDEX IF NOT EXISTS idx_tx_code ON transactions(fund_code);
            CREATE INDEX IF NOT EXISTS idx_tx_date ON transactions(date);
            """
        )


def _migrate_legacy_holdings() -> None:
    """把旧版 holdings 表迁移为 funds + 一条买入流水。仅执行一次。"""
    with get_connection() as conn:
        has_old = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='holdings'"
        ).fetchone()
        if not has_old:
            return
        # 已迁移标记：若已有交易流水，跳过
        tx_count = conn.execute("SELECT COUNT(*) c FROM transactions").fetchone()["c"]
        rows = conn.execute("SELECT * FROM holdings").fetchall()
        if tx_count > 0 or not rows:
            conn.execute("ALTER TABLE holdings RENAME TO holdings_legacy_backup")
            return

        for r in rows:
            d = dict(r)
            code = d.get("fund_code", "").strip()
            if not code:
                continue
            amount = d.get("buy_amount") or 0.0
            cost_nav = d.get("cost_nav")
            shares = d.get("shares")
            if not shares:
                shares = amount / cost_nav if cost_nav else amount  # 无净值时份额=金额兜底
            conn.execute(
                "INSERT OR IGNORE INTO funds(fund_code,fund_name,fund_type,sector) "
                "VALUES(?,?,?,?)",
                (code, d.get("fund_name") or code, d.get("fund_type") or "其它",
                 d.get("sector") or ""),
            )
            conn.execute(
                "INSERT INTO transactions(fund_code,action,date,amount,shares,nav,note) "
                "VALUES(?,?,?,?,?,?,?)",
                (code, "buy", d.get("buy_date") or "2024-01-01",
                 amount, shares, cost_nav, "自旧版持仓迁移"),
            )
        conn.execute("ALTER TABLE holdings RENAME TO holdings_legacy_backup")


# ---------------------------------------------------------------------------
# funds 基础信息
# ---------------------------------------------------------------------------
def upsert_fund(fund: Fund) -> None:
    """新增或更新基金基础信息。"""
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO funds(fund_code, fund_name, fund_type, sector)
            VALUES(?,?,?,?)
            ON CONFLICT(fund_code) DO UPDATE SET
                fund_name=excluded.fund_name,
                fund_type=excluded.fund_type,
                sector=excluded.sector,
                updated_at=datetime('now','localtime')
            """,
            (fund.fund_code.strip(), fund.fund_name.strip(),
             fund.fund_type, fund.sector),
        )


def get_fund(fund_code: str) -> Fund | None:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM funds WHERE fund_code=?", (fund_code,)
        ).fetchone()
    return Fund.from_row(row) if row else None


def get_funds() -> list[Fund]:
    with get_connection() as conn:
        rows = conn.execute("SELECT * FROM funds ORDER BY fund_code").fetchall()
    return [Fund.from_row(r) for r in rows]


def update_fund_sector(fund_code: str, sector: str) -> None:
    with get_connection() as conn:
        conn.execute(
            "UPDATE funds SET sector=?, updated_at=datetime('now','localtime') "
            "WHERE fund_code=?",
            (sector, fund_code),
        )


# ---------------------------------------------------------------------------
# transactions 流水 CRUD
# ---------------------------------------------------------------------------
def add_transaction(tx: Transaction) -> int:
    """新增一笔流水，返回 id。会自动 normalize 补全字段。"""
    tx.normalize()
    with get_connection() as conn:
        cur = conn.execute(
            """
            INSERT INTO transactions(fund_code,action,date,amount,shares,nav,fee,channel,note)
            VALUES(?,?,?,?,?,?,?,?,?)
            """,
            (tx.fund_code.strip(), tx.action, tx.date, tx.amount, tx.shares,
             tx.nav, tx.fee, tx.channel, tx.note),
        )
        return int(cur.lastrowid)


def update_transaction(tx: Transaction) -> None:
    if tx.id is None:
        raise ValueError("update_transaction 需要 tx.id")
    tx.normalize()
    with get_connection() as conn:
        conn.execute(
            """
            UPDATE transactions SET
                fund_code=?, action=?, date=?, amount=?, shares=?, nav=?,
                fee=?, channel=?, note=?
            WHERE id=?
            """,
            (tx.fund_code.strip(), tx.action, tx.date, tx.amount, tx.shares,
             tx.nav, tx.fee, tx.channel, tx.note, tx.id),
        )


def delete_transaction(tx_id: int) -> None:
    with get_connection() as conn:
        conn.execute("DELETE FROM transactions WHERE id=?", (tx_id,))


def delete_all_transactions() -> None:
    with get_connection() as conn:
        conn.execute("DELETE FROM transactions")


def get_transactions(fund_code: str | None = None) -> list[Transaction]:
    """返回流水，按日期升序（同日按 id）。可按基金过滤。"""
    with get_connection() as conn:
        if fund_code:
            rows = conn.execute(
                "SELECT * FROM transactions WHERE fund_code=? ORDER BY date ASC, id ASC",
                (fund_code,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM transactions ORDER BY date ASC, id ASC"
            ).fetchall()
    return [Transaction.from_row(r) for r in rows]


def get_transactions_desc() -> list[Transaction]:
    """返回流水，按日期降序（最新在前），用于展示。"""
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM transactions ORDER BY date DESC, id DESC"
        ).fetchall()
    return [Transaction.from_row(r) for r in rows]


def get_transactions_without_nav() -> list[Transaction]:
    """返回净值缺失的交易记录（nav IS NULL），待净值更新后回填。"""
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM transactions WHERE nav IS NULL ORDER BY date ASC, id ASC"
        ).fetchall()
    return [Transaction.from_row(r) for r in rows]


def get_distinct_fund_codes() -> list[str]:
    """返回有流水记录的所有基金代码。"""
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT DISTINCT fund_code FROM transactions WHERE fund_code != ''"
        ).fetchall()
    return [r["fund_code"] for r in rows]


# ---------------------------------------------------------------------------
# 净值写入 / 查询
# ---------------------------------------------------------------------------
def upsert_nav(point: NavPoint) -> None:
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO nav_history(fund_code,date,nav,accumulated_nav,source)
            VALUES(?,?,?,?,?)
            ON CONFLICT(fund_code,date) DO UPDATE SET
                nav=excluded.nav, accumulated_nav=excluded.accumulated_nav,
                source=excluded.source
            """,
            (point.fund_code, point.date, point.nav, point.accumulated_nav,
             point.source),
        )


def upsert_nav_batch(points: Iterable[NavPoint]) -> int:
    rows = [(p.fund_code, p.date, p.nav, p.accumulated_nav, p.source)
            for p in points]
    if not rows:
        return 0
    with get_connection() as conn:
        conn.executemany(
            """
            INSERT INTO nav_history(fund_code,date,nav,accumulated_nav,source)
            VALUES(?,?,?,?,?)
            ON CONFLICT(fund_code,date) DO UPDATE SET
                nav=excluded.nav, accumulated_nav=excluded.accumulated_nav,
                source=excluded.source
            """,
            rows,
        )
    return len(rows)


def get_latest_nav(fund_code: str) -> sqlite3.Row | None:
    with get_connection() as conn:
        return conn.execute(
            "SELECT * FROM nav_history WHERE fund_code=? ORDER BY date DESC LIMIT 1",
            (fund_code,),
        ).fetchone()


def get_prev_nav(fund_code: str) -> sqlite3.Row | None:
    """返回倒数第二条 NAV 记录（用于计算今日收益）。"""
    with get_connection() as conn:
        return conn.execute(
            "SELECT * FROM nav_history WHERE fund_code=? ORDER BY date DESC LIMIT 1 OFFSET 1",
            (fund_code,),
        ).fetchone()


def get_nav_history(fund_code: str) -> list[sqlite3.Row]:
    with get_connection() as conn:
        return conn.execute(
            "SELECT * FROM nav_history WHERE fund_code=? ORDER BY date ASC",
            (fund_code,),
        ).fetchall()


def get_nav_on_or_after(fund_code: str, date_str: str) -> sqlite3.Row | None:
    """返回某日期当天或之后最近的一条净值。"""
    with get_connection() as conn:
        return conn.execute(
            "SELECT * FROM nav_history WHERE fund_code=? AND date>=? "
            "ORDER BY date ASC LIMIT 1",
            (fund_code, date_str),
        ).fetchone()


def get_nav_last_update() -> str | None:
    with get_connection() as conn:
        row = conn.execute("SELECT MAX(date) AS d FROM nav_history").fetchone()
    return row["d"] if row and row["d"] else None


# ---------------------------------------------------------------------------
# 组合快照
# ---------------------------------------------------------------------------
def save_snapshot(date_str: str, total_cost: float, total_value: float,
                  total_profit: float, total_return: float) -> None:
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO portfolio_snapshots(date,total_cost,total_value,
                total_profit,total_return)
            VALUES(?,?,?,?,?)
            ON CONFLICT(date) DO UPDATE SET
                total_cost=excluded.total_cost, total_value=excluded.total_value,
                total_profit=excluded.total_profit, total_return=excluded.total_return
            """,
            (date_str, total_cost, total_value, total_profit, total_return),
        )


def get_snapshots() -> list[sqlite3.Row]:
    with get_connection() as conn:
        return conn.execute(
            "SELECT * FROM portfolio_snapshots ORDER BY date ASC"
        ).fetchall()


# ---------------------------------------------------------------------------
# AI 用量记录
# ---------------------------------------------------------------------------
def add_ai_usage(model: str, prompt_tokens: int, completion_tokens: int,
                 total_tokens: int, turns: int) -> None:
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO ai_usage(created_at,model,prompt_tokens,completion_tokens,total_tokens,turns)"
            " VALUES(datetime('now'),?,?,?,?,?)",
            (model, prompt_tokens, completion_tokens, total_tokens, turns),
        )


def get_ai_usage_stats() -> dict:
    """返回今日总计、历史累计、最近 20 条明细"""
    with get_connection() as conn:
        today = conn.execute(
            "SELECT COALESCE(SUM(total_tokens),0) AS t FROM ai_usage"
            " WHERE created_at >= date('now')"
        ).fetchone()["t"]

        total = conn.execute(
            "SELECT COALESCE(SUM(total_tokens),0) AS t FROM ai_usage"
        ).fetchone()["t"]

        recent_rows = conn.execute(
            "SELECT * FROM ai_usage ORDER BY id DESC LIMIT 20"
        ).fetchall()

    recent = [{
        "id": r["id"],
        "created_at": r["created_at"],
        "model": r["model"],
        "prompt_tokens": r["prompt_tokens"],
        "completion_tokens": r["completion_tokens"],
        "total_tokens": r["total_tokens"],
        "turns": r["turns"],
    } for r in recent_rows]

    return {"today": today, "total": total, "recent": recent}


def get_ai_usage_daily(days: int = 7) -> list[dict]:
    """返回最近 N 天每日 token 用量（无记录的天补 0）。"""
    import datetime as dt
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT date(created_at) AS d, COALESCE(SUM(total_tokens),0) AS t"
            " FROM ai_usage"
            " WHERE created_at >= date('now', ?)"
            " GROUP BY date(created_at) ORDER BY d ASC",
            (f"-{days} days",),
        ).fetchall()
    usage_map = {r["d"]: r["t"] for r in rows}
    today = dt.datetime.now(dt.timezone.utc).date()
    dates = [(today - dt.timedelta(days=days - 1 - i)).isoformat() for i in range(days)]
    return [{"date": d, "tokens": usage_map.get(d, 0)} for d in dates]


# ---------------------------------------------------------------------------
# 偏好设置（key-value 存储）
# ---------------------------------------------------------------------------
def upsert_preference(key: str, value: str) -> None:
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO preferences(key,value) VALUES(?,?)"
            " ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value),
        )


def get_preference(key: str) -> str | None:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT value FROM preferences WHERE key=?", (key,)
        ).fetchone()
    return row["value"] if row else None


def get_all_preferences() -> dict[str, str]:
    with get_connection() as conn:
        rows = conn.execute("SELECT key, value FROM preferences").fetchall()
    return {r["key"]: r["value"] for r in rows}


if __name__ == "__main__":
    init_db()
    print(f"数据库已初始化：{config.DB_PATH}")
