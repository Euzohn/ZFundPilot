"""SQLite 数据库操作层（交易流水驱动）。

表结构：
- funds               基金基础信息（代码/名称/类型/板块）
- transactions        买入/卖出流水
- nav_history         基金净值历史
- index_history        指数历史收盘价（基准对比，持久化缓存）

设计：持仓不再单独存表，而是由 transactions 流水汇总计算（见 analysis.py）。
兼容旧版：若检测到旧 holdings 表，自动迁移为一条买入流水。
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from datetime import datetime

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
    conn.execute("PRAGMA busy_timeout = 5000")
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
        conn.execute("PRAGMA journal_mode = WAL")
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS funds (
                fund_code       TEXT PRIMARY KEY,
                fund_name       TEXT DEFAULT '',
                fund_type       TEXT DEFAULT '其它',
                sector          TEXT DEFAULT '',
                tracking_index  TEXT DEFAULT '',
                created_at      TEXT DEFAULT (datetime('now','localtime')),
                updated_at      TEXT DEFAULT (datetime('now','localtime'))
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

            CREATE TABLE IF NOT EXISTS audit_log (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                ts         TEXT NOT NULL,
                ip         TEXT,
                username   TEXT,
                action     TEXT NOT NULL,
                detail     TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_audit_ts ON audit_log(ts DESC);

            CREATE TABLE IF NOT EXISTS auto_invest_plans (
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

            CREATE TABLE IF NOT EXISTS watchlist (
                fund_code  TEXT PRIMARY KEY,
                note      TEXT DEFAULT '',
                group_name TEXT DEFAULT '',
                added_at  TEXT DEFAULT (datetime('now','localtime'))
            );

            CREATE TABLE IF NOT EXISTS dividend_alerts (
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
                tx_id            INTEGER
            );
            CREATE INDEX IF NOT EXISTS idx_alert_status ON dividend_alerts(status);
            CREATE INDEX IF NOT EXISTS idx_alert_code_ex ON dividend_alerts(fund_code, ex_date);

            CREATE TABLE IF NOT EXISTS index_history (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                code       TEXT NOT NULL,
                date       TEXT NOT NULL,
                close      REAL NOT NULL,
                source     TEXT DEFAULT 'sina',
                created_at TEXT DEFAULT (datetime('now','localtime')),
                UNIQUE(code, date)
            );
            CREATE INDEX IF NOT EXISTS idx_index_code_date ON index_history(code, date);
            """
        )
    _migrate_add_columns()
    _migrate_relax_transactions_schema()
    _migrate_legacy_holdings()
    _migrate_tp_sl()
    _migrate_dividend_alerts_unique()
    _migrate_auto_invest_plans_check()
    _migrate_nav_history_check()
    _migrate_add_indexes()
    _migrate_add_conversion_id()


def _migrate_add_columns() -> None:
    """为已存在的旧表补充新增列。幂等。"""
    with get_connection() as conn:
        cols = {r["name"] for r in
                conn.execute("PRAGMA table_info(transactions)").fetchall()}
        if "channel" not in cols:
            conn.execute(
                "ALTER TABLE transactions ADD COLUMN channel TEXT DEFAULT ''"
            )
        if "is_t1" not in cols:
            conn.execute(
                "ALTER TABLE transactions ADD COLUMN is_t1 INTEGER DEFAULT 0"
            )
            # 回填：note 含 "T+1确认" 的旧交易标记为 is_t1
            conn.execute(
                "UPDATE transactions SET is_t1=1 WHERE note LIKE '%T+1确认%'"
            )


def _migrate_tp_sl() -> None:
    """止盈止损提醒相关迁移。幂等。"""
    with get_connection() as conn:
        da_cols = {r["name"] for r in
                   conn.execute("PRAGMA table_info(dividend_alerts)").fetchall()}
        if "alert_type" not in da_cols:
            conn.execute(
                "ALTER TABLE dividend_alerts ADD COLUMN alert_type TEXT DEFAULT 'dividend'"
            )
        if "triggered_return" not in da_cols:
            conn.execute(
                "ALTER TABLE dividend_alerts ADD COLUMN triggered_return REAL"
            )
        if "threshold" not in da_cols:
            conn.execute(
                "ALTER TABLE dividend_alerts ADD COLUMN threshold REAL"
            )

        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS tp_sl_alert_states (
                fund_code           TEXT NOT NULL,
                alert_type          TEXT NOT NULL,
                last_alert_id       INTEGER,
                last_triggered_return REAL,
                handled_at          TEXT,
                armed               INTEGER DEFAULT 1,
                updated_at          TEXT DEFAULT (datetime('now','localtime')),
                PRIMARY KEY (fund_code, alert_type)
            );
            """
        )
        # 兼容旧 dividend_alerts 已有数据：alert_type 默认为 'dividend' 无需回填

        # watchlist 表补充 group_name 列
        wl_cols = {r["name"] for r in
                   conn.execute("PRAGMA table_info(watchlist)").fetchall()}
        if wl_cols and "group_name" not in wl_cols:
            conn.execute(
                "ALTER TABLE watchlist ADD COLUMN group_name TEXT DEFAULT ''"
            )

        # funds 表补充 tracking_index 列
        fund_cols = {r["name"] for r in
                     conn.execute("PRAGMA table_info(funds)").fetchall()}
        if fund_cols and "tracking_index" not in fund_cols:
            conn.execute(
                "ALTER TABLE funds ADD COLUMN tracking_index TEXT DEFAULT ''"
            )

        # funds 表补充 dividend_method 列
        if fund_cols and "dividend_method" not in fund_cols:
            conn.execute(
                "ALTER TABLE funds ADD COLUMN dividend_method TEXT DEFAULT 'cash'"
            )


def _migrate_relax_transactions_schema() -> None:
    """统一管理 transactions 表的最终 schema 迁移。

    合并两步操作（避免两次重建）：
    1. 移除旧约束：旧表有 CHECK(action IN ('buy','sell')) 和 amount/shares NOT NULL，
       阻止插入 dividend/reinvest 操作和待确认交易（NULL 字段）。
    2. 添加新约束：CHECK(action IN 4种action) + CHECK(amount >= 0 OR amount IS NULL)，
       确保数据完整性。

    SQLite 无法直接 ALTER 约束，需重建表。幂等：目标 CHECK 已存在时跳过。
    """
    with get_connection() as conn:
        row = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='transactions'"
        ).fetchone()
        if not row:
            return
        sql_text = row["sql"]

        # 幂等判断：检查旧 schema 特征（CHECK(action IN ('buy','sell'))）或
        # 缺少新 CHECK 约束 → 需要迁移
        has_old_check = "action IN ('buy', 'sell')" in sql_text
        has_new_check = (
            "action IN ('buy', 'sell', 'dividend', 'reinvest')" in sql_text
            and "amount >= 0" in sql_text
        )
        if not has_old_check and has_new_check:
            return  # 已是最终 schema，无需迁移

        # Step 1: 清理脏数据（违反新 CHECK 约束的行）
        if has_old_check or not has_new_check:
            # 移除无效 action 值 + 负金额（否则重建时 CHECK 会失败）
            valid_actions = ("buy", "sell", "dividend", "reinvest")
            placeholders = ",".join("?" * len(valid_actions))
            conn.execute(
                f"DELETE FROM transactions WHERE action NOT IN ({placeholders}) "
                "OR amount < 0",
                valid_actions,
            )

        conn.executescript(
            """
            CREATE TABLE transactions_new (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                fund_code  TEXT NOT NULL,
                action     TEXT NOT NULL,
                date       TEXT NOT NULL,
                amount     REAL CHECK(amount >= 0 OR amount IS NULL),
                shares     REAL,
                nav        REAL,
                fee        REAL DEFAULT 0,
                channel    TEXT DEFAULT '',
                note       TEXT DEFAULT '',
                is_t1      INTEGER DEFAULT 0,
                created_at TEXT DEFAULT (datetime('now','localtime')),
                CHECK(action IN ('buy', 'sell', 'dividend', 'reinvest'))
            );
            INSERT INTO transactions_new
                (id, fund_code, action, date, amount, shares, nav, fee, channel, note, is_t1, created_at)
            SELECT id, fund_code, action, date, amount, shares, nav, fee, channel, note,
                   is_t1, created_at
            FROM transactions;
            DROP TABLE transactions;
            ALTER TABLE transactions_new RENAME TO transactions;
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
                "INSERT OR IGNORE INTO funds(fund_code,fund_name,fund_type,sector,tracking_index) "
                "VALUES(?,?,?,?,?)",
                (code, d.get("fund_name") or code, d.get("fund_type") or "其它",
                 d.get("sector") or "", ""),
            )
            conn.execute(
                "INSERT INTO transactions(fund_code,action,date,amount,shares,nav,note) "
                "VALUES(?,?,?,?,?,?,?)",
                (code, "buy", d.get("buy_date") or "2024-01-01",
                 amount, shares, cost_nav, "自旧版持仓迁移"),
            )
        conn.execute("ALTER TABLE holdings RENAME TO holdings_legacy_backup")


def _migrate_add_indexes() -> None:
    """补充缺失索引、删除冗余索引。幂等。"""
    with get_connection() as conn:
        existing = {
            r["name"]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='index'"
            ).fetchall()
        }

        # 补缺失索引
        if "idx_ai_usage_created" not in existing:
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_ai_usage_created "
                "ON ai_usage(created_at)"
            )
        if "idx_tx_code_date" not in existing:
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_tx_code_date "
                "ON transactions(fund_code, date)"
            )
        if "idx_auto_invest_enabled_next" not in existing:
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_auto_invest_enabled_next "
                "ON auto_invest_plans(enabled, next_run)"
            )
        if "idx_alert_type_status" not in existing:
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_alert_type_status "
                "ON dividend_alerts(alert_type, status)"
            )

        # 删冗余索引
        for idx in ("idx_nav_code_date", "idx_index_code_date", "idx_tx_code"):
            if idx in existing:
                conn.execute(f"DROP INDEX IF EXISTS {idx}")


def _migrate_add_conversion_id() -> None:
    """给 transactions 加 conversion_id 列（基金转换链接 ID）。幂等。"""
    with get_connection() as conn:
        cols = {r["name"] for r in
                conn.execute("PRAGMA table_info(transactions)").fetchall()}
        if "conversion_id" not in cols:
            conn.execute(
                "ALTER TABLE transactions ADD COLUMN conversion_id TEXT DEFAULT ''"
            )


def _migrate_dividend_alerts_unique() -> None:
    """给 dividend_alerts 加 UNIQUE(fund_code, ex_date, alert_type) 约束。

    幂等：目标 UNIQUE 已存在时跳过。重建前先清理重复数据（保留最早 id）。
    """
    with get_connection() as conn:
        sql_text = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='dividend_alerts'"
        ).fetchone()
        if not sql_text or "UNIQUE(fund_code, ex_date, alert_type)" in sql_text["sql"]:
            return

        # 清理重复数据：仅对 ex_date 非空的 dividend 行去重（保留每组最早 id）。
        # tp_sl 行 ex_date 为 NULL，SQLite UNIQUE 视 NULL 互异，不受约束，不能去重。
        conn.execute(
            """DELETE FROM dividend_alerts WHERE ex_date IS NOT NULL AND id NOT IN (
                   SELECT MIN(id) FROM dividend_alerts WHERE ex_date IS NOT NULL
                   GROUP BY fund_code, ex_date, COALESCE(alert_type, 'dividend')
               )"""
        )

        conn.executescript(
            """
            CREATE TABLE dividend_alerts_new (
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
            INSERT INTO dividend_alerts_new
                (id, fund_code, fund_name, record_date, ex_date, per_share,
                 pay_date, held_shares, estimated_amount, dividend_method,
                 status, created_at, resolved_at, tx_id,
                 alert_type, triggered_return, threshold)
            SELECT id, fund_code, fund_name, record_date, ex_date, per_share,
                   pay_date, held_shares, estimated_amount, dividend_method,
                   status, created_at, resolved_at, tx_id,
                   COALESCE(alert_type, 'dividend'), triggered_return, threshold
            FROM dividend_alerts;
            DROP TABLE dividend_alerts;
            ALTER TABLE dividend_alerts_new RENAME TO dividend_alerts;
            CREATE INDEX IF NOT EXISTS idx_alert_status ON dividend_alerts(status);
            CREATE INDEX IF NOT EXISTS idx_alert_code_ex ON dividend_alerts(fund_code, ex_date);
            CREATE INDEX IF NOT EXISTS idx_alert_type_status ON dividend_alerts(alert_type, status);
            """
        )


def _migrate_auto_invest_plans_check() -> None:
    """给 auto_invest_plans 加 CHECK(amount > 0) 约束。幂等。"""
    with get_connection() as conn:
        sql_text = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='auto_invest_plans'"
        ).fetchone()
        if not sql_text or "amount > 0" in sql_text["sql"]:
            return

        # 清理无效数据
        conn.execute("DELETE FROM auto_invest_plans WHERE amount <= 0")

        conn.executescript(
            """
            CREATE TABLE auto_invest_plans_new (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                fund_code    TEXT NOT NULL,
                amount       REAL NOT NULL CHECK(amount > 0),
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
            INSERT INTO auto_invest_plans_new
                SELECT * FROM auto_invest_plans;
            DROP TABLE auto_invest_plans;
            ALTER TABLE auto_invest_plans_new RENAME TO auto_invest_plans;
            """
        )


def _migrate_nav_history_check() -> None:
    """给 nav_history 加 CHECK(nav > 0) 约束。幂等。"""
    with get_connection() as conn:
        sql_text = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='nav_history'"
        ).fetchone()
        if not sql_text or "nav > 0" in sql_text["sql"]:
            return

        # 清理无效数据
        conn.execute("DELETE FROM nav_history WHERE nav <= 0")

        conn.executescript(
            """
            CREATE TABLE nav_history_new (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                fund_code       TEXT NOT NULL,
                date            TEXT NOT NULL,
                nav             REAL NOT NULL CHECK(nav > 0),
                accumulated_nav REAL,
                source          TEXT DEFAULT 'akshare',
                created_at      TEXT DEFAULT (datetime('now','localtime')),
                UNIQUE(fund_code, date)
            );
            INSERT INTO nav_history_new
                SELECT id, fund_code, date, nav, accumulated_nav, source, created_at
                FROM nav_history;
            DROP TABLE nav_history;
            ALTER TABLE nav_history_new RENAME TO nav_history;
            """
        )


# ---------------------------------------------------------------------------
# funds 基础信息
# ---------------------------------------------------------------------------
def upsert_fund(fund: Fund) -> None:
    """新增或更新基金基础信息。

    dividend_method 只在 INSERT 时写入默认值('cash')，
    ON CONFLICT 时不覆盖——避免元数据刷新重置用户设置。
    """
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO funds(fund_code, fund_name, fund_type, sector, tracking_index, dividend_method)
            VALUES(?,?,?,?,?,?)
            ON CONFLICT(fund_code) DO UPDATE SET
                fund_name=excluded.fund_name,
                fund_type=excluded.fund_type,
                sector=excluded.sector,
                tracking_index=excluded.tracking_index,
                updated_at=datetime('now','localtime')
            """,
            (fund.fund_code.strip(), fund.fund_name.strip(),
             fund.fund_type, fund.sector, fund.tracking_index, fund.dividend_method),
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


def update_fund_tracking_index(fund_code: str, tracking_index: str) -> None:
    with get_connection() as conn:
        conn.execute(
            "UPDATE funds SET tracking_index=?, updated_at=datetime('now','localtime') "
            "WHERE fund_code=?",
            (tracking_index, fund_code),
        )


def update_fund_dividend_method(fund_code: str, method: str) -> None:
    with get_connection() as conn:
        conn.execute(
            "UPDATE funds SET dividend_method=?, updated_at=datetime('now','localtime') "
            "WHERE fund_code=?",
            (method, fund_code),
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
            INSERT INTO transactions(fund_code,action,date,amount,shares,nav,fee,channel,note,is_t1,conversion_id)
            VALUES(?,?,?,?,?,?,?,?,?,?,?)
            """,
            (tx.fund_code.strip(), tx.action, tx.date, tx.amount, tx.shares,
             tx.nav, tx.fee, tx.channel, tx.note, int(tx.is_t1), tx.conversion_id),
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
                fee=?, channel=?, note=?, is_t1=?, conversion_id=?
            WHERE id=?
            """,
            (tx.fund_code.strip(), tx.action, tx.date, tx.amount, tx.shares,
             tx.nav, tx.fee, tx.channel, tx.note, int(tx.is_t1), tx.conversion_id, tx.id),
        )


def add_conversion(from_tx: Transaction, to_tx: Transaction) -> tuple[int, int]:
    """原子插入两条关联交易（卖出腿 + 买入腿），共享同一 conversion_id。

    返回 (from_tx_id, to_tx_id)。
    """
    conversion_id = str(uuid.uuid4())
    from_tx.conversion_id = conversion_id
    to_tx.conversion_id = conversion_id
    from_tx.normalize()
    to_tx.normalize()
    with get_connection() as conn:
        cur_from = conn.execute(
            """
            INSERT INTO transactions(fund_code,action,date,amount,shares,nav,fee,channel,note,is_t1,conversion_id)
            VALUES(?,?,?,?,?,?,?,?,?,?,?)
            """,
            (from_tx.fund_code.strip(), from_tx.action, from_tx.date, from_tx.amount,
             from_tx.shares, from_tx.nav, from_tx.fee, from_tx.channel, from_tx.note,
             int(from_tx.is_t1), conversion_id),
        )
        cur_to = conn.execute(
            """
            INSERT INTO transactions(fund_code,action,date,amount,shares,nav,fee,channel,note,is_t1,conversion_id)
            VALUES(?,?,?,?,?,?,?,?,?,?,?)
            """,
            (to_tx.fund_code.strip(), to_tx.action, to_tx.date, to_tx.amount,
             to_tx.shares, to_tx.nav, to_tx.fee, to_tx.channel, to_tx.note,
             int(to_tx.is_t1), conversion_id),
        )
        return int(cur_from.lastrowid), int(cur_to.lastrowid)


def delete_transaction(tx_id: int) -> None:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT conversion_id FROM transactions WHERE id=?", (tx_id,)
        ).fetchone()
        if row and row[0]:
            conn.execute(
                "UPDATE transactions SET conversion_id='' WHERE conversion_id=? AND id!=?",
                (row[0], tx_id),
            )
        conn.execute("DELETE FROM transactions WHERE id=?", (tx_id,))


def delete_all_transactions() -> None:
    with get_connection() as conn:
        conn.execute("DELETE FROM transactions")


def get_transactions(
    fund_code: str | None = None,
    *,
    fund_codes: list[str] | None = None,
    actions: list[str] | None = None,
    dates: list[str] | None = None,
) -> list[Transaction]:
    """返回流水，按日期升序（同日按 id）。支持多种过滤。

    fund_code: 单只基金过滤（兼容旧调用）
    fund_codes: 多基金过滤（IN 子句）
    actions: 按操作类型过滤（IN 子句）
    dates: 按日期过滤（IN 子句，精确匹配）
    """
    clauses: list[str] = []
    params: list[str | int] = []

    if fund_code:
        clauses.append("fund_code=?")
        params.append(fund_code)
    if fund_codes:
        ph = ",".join("?" for _ in fund_codes)
        clauses.append(f"fund_code IN ({ph})")
        params.extend(fund_codes)
    if actions:
        ph = ",".join("?" for _ in actions)
        clauses.append(f"action IN ({ph})")
        params.extend(actions)
    if dates:
        ph = ",".join("?" for _ in dates)
        clauses.append(f"date IN ({ph})")
        params.extend(dates)

    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    sql = f"SELECT * FROM transactions{where} ORDER BY date ASC, id ASC"

    with get_connection() as conn:
        rows = conn.execute(sql, params).fetchall()
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




# ---------------------------------------------------------------------------
# 净值写入 / 查询
# ---------------------------------------------------------------------------
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


def get_latest_navs_batch(fund_codes: list[str]) -> dict[str, sqlite3.Row]:
    """批量获取每只基金的最新净值（单次查询）。

    Returns:
        {fund_code: nav_row}
    """
    if not fund_codes:
        return {}
    with get_connection() as conn:
        ph = ",".join("?" for _ in fund_codes)
        rows = conn.execute(
            f"SELECT nh.* FROM nav_history nh "
            f"INNER JOIN ("
            f"  SELECT fund_code, MAX(date) AS max_date "
            f"  FROM nav_history WHERE fund_code IN ({ph}) "
            f"  GROUP BY fund_code"
            f") latest ON nh.fund_code = latest.fund_code AND nh.date = latest.max_date",
            fund_codes,
        ).fetchall()
    return {r["fund_code"]: r for r in rows}


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


def get_nav_history_by_period(
    fund_code: str, start_date: str, end_date: str
) -> list[sqlite3.Row]:
    """按 fund_code + 日期区间查询净值（date ASC，含端点）。"""
    with get_connection() as conn:
        return conn.execute(
            "SELECT * FROM nav_history WHERE fund_code=? AND date>=? AND date<=? "
            "ORDER BY date ASC",
            (fund_code, start_date, end_date),
        ).fetchall()


def get_nav_on_or_after(fund_code: str, date_str: str) -> sqlite3.Row | None:
    """返回某日期当天或之后最近的一条净值。"""
    with get_connection() as conn:
        return conn.execute(
            "SELECT * FROM nav_history WHERE fund_code=? AND date>=? "
            "ORDER BY date ASC LIMIT 1",
            (fund_code, date_str),
        ).fetchone()


def get_navs_on_or_after_batch(
    items: list[tuple[str, str]],
) -> dict[tuple[str, str], sqlite3.Row]:
    """批量获取每只基金指定日期当天或之后最近的一条净值（单连接+去重）。

    Args:
        items: [(fund_code, nav_date), ...]

    Returns:
        {(fund_code, nav_date): nav_row} — 仅包含有结果的对
    """
    if not items:
        return {}
    seen: set[tuple[str, str]] = set()
    result: dict[tuple[str, str], sqlite3.Row] = {}
    with get_connection() as conn:
        for code, date_str in items:
            key = (code, date_str)
            if key in seen:
                continue
            seen.add(key)
            row = conn.execute(
                "SELECT * FROM nav_history WHERE fund_code=? AND date>=? "
                "ORDER BY date ASC LIMIT 1",
                (code, date_str),
            ).fetchone()
            if row:
                result[key] = row
    return result


def get_nav_on_date(fund_code: str, date_str: str) -> sqlite3.Row | None:
    """返回某日期当天的净值（精确匹配，不含前后日期）。"""
    with get_connection() as conn:
        return conn.execute(
            "SELECT * FROM nav_history WHERE fund_code=? AND date=?",
            (fund_code, date_str),
        ).fetchone()




# ---------------------------------------------------------------------------
# 指数历史（基准对比）
# ---------------------------------------------------------------------------
def upsert_index_history(code: str,
                         points: Iterable[tuple[str, float]]) -> int:
    """批量写入指数历史收盘价。

    Args:
        code: 指数代码，如 "000300"
        points: [(date, close), ...]

    Returns:
        写入行数。
    """
    rows = [(code, d, c, "sina") for d, c in points]
    if not rows:
        return 0
    with get_connection() as conn:
        conn.executemany(
            """
            INSERT INTO index_history(code, date, close, source)
            VALUES(?, ?, ?, ?)
            ON CONFLICT(code, date) DO UPDATE SET
                close=excluded.close, source=excluded.source
            """,
            rows,
        )
    return len(rows)


def get_index_history(code: str,
                      start_date: str | None = None,
                      end_date: str | None = None) -> list[sqlite3.Row]:
    """查询指数历史收盘价（date ASC，含端点）。

    start_date / end_date 为 None 时不限该端。
    """
    clauses = ["code=?"]
    params: list[str] = [code]
    if start_date:
        clauses.append("date>=?")
        params.append(start_date)
    if end_date:
        clauses.append("date<=?")
        params.append(end_date)
    sql = ("SELECT * FROM index_history WHERE "
           + " AND ".join(clauses) + " ORDER BY date ASC")
    with get_connection() as conn:
        return conn.execute(sql, params).fetchall()


def get_index_latest_date(code: str) -> str | None:
    """返回某指数在 DB 中的最新日期。"""
    with get_connection() as conn:
        row = conn.execute(
            "SELECT MAX(date) AS d FROM index_history WHERE code=?",
            (code,),
        ).fetchone()
    return row["d"] if row and row["d"] else None


# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# AI 用量记录
# ---------------------------------------------------------------------------
def add_ai_usage(model: str, prompt_tokens: int, completion_tokens: int,
                 total_tokens: int, turns: int) -> None:
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO ai_usage(created_at,model,prompt_tokens,completion_tokens,total_tokens,turns)"
            " VALUES(datetime('now','localtime'),?,?,?,?,?)",
            (model, prompt_tokens, completion_tokens, total_tokens, turns),
        )


def get_ai_usage_stats() -> dict:
    """返回今日总计、历史累计、最近 20 条明细"""
    with get_connection() as conn:
        today = conn.execute(
            "SELECT COALESCE(SUM(total_tokens),0) AS t FROM ai_usage"
            " WHERE created_at >= date('now','localtime')"
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
            " WHERE created_at >= date('now','localtime', ?)"
            " GROUP BY date(created_at) ORDER BY d ASC",
            (f"-{days} days",),
        ).fetchall()
    usage_map = {r["d"]: r["t"] for r in rows}
    today = datetime.now(config.TIMEZONE).date()
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


# ---------------------------------------------------------------------------
# 审计日志
# ---------------------------------------------------------------------------
def log_audit(action: str, ip: str | None = None,
              username: str | None = None,
              detail: dict | None = None) -> None:
    """写入审计日志。"""
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO audit_log(ts, ip, username, action, detail) VALUES(?,?,?,?,?)",
            (datetime.now(config.TIMEZONE).isoformat(), ip, username, action,
             json.dumps(detail, ensure_ascii=False) if detail else None),
        )


def fetch_audit_logs(limit: int = 100) -> list[dict]:
    """返回最近 N 条审计日志。"""
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM audit_log ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# 定投计划 CRUD
# ---------------------------------------------------------------------------
def add_auto_invest_plan(fund_code: str, amount: float, cadence: str,
                          day_of_week: int | None = None,
                          day_of_month: int | None = None,
                          channel: str = "", note: str = "定投",
                          next_run: str | None = None) -> int:
    with get_connection() as conn:
        cur = conn.execute(
            """INSERT INTO auto_invest_plans
               (fund_code,amount,cadence,day_of_week,day_of_month,channel,note,next_run)
               VALUES(?,?,?,?,?,?,?,?)""",
            (fund_code.strip(), amount, cadence, day_of_week, day_of_month,
             channel, note, next_run),
        )
        return int(cur.lastrowid)


def update_auto_invest_plan(plan_id: int, **kwargs) -> None:
    """更新定投计划字段。仅允许白名单内的 key，防止 SQL 注入。"""
    if not kwargs:
        with get_connection() as conn:
            conn.execute(
                "UPDATE auto_invest_plans SET updated_at=datetime('now','localtime') "
                "WHERE id=?",
                (plan_id,),
            )
        return
    allowed = {
        "fund_code", "amount", "cadence", "day_of_week", "day_of_month",
        "channel", "note", "enabled", "next_run", "last_run", "last_tx_id",
    }
    updates = {k: v for k, v in kwargs.items() if k in allowed}
    if not updates:
        with get_connection() as conn:
            conn.execute(
                "UPDATE auto_invest_plans SET updated_at=datetime('now','localtime') "
                "WHERE id=?",
                (plan_id,),
            )
        return
    fields = ", ".join(f"{k}=?" for k in updates)
    vals = list(updates.values()) + [plan_id]
    with get_connection() as conn:
        conn.execute(
            f"UPDATE auto_invest_plans SET {fields}, "
            "updated_at=datetime('now','localtime') WHERE id=?",
            vals,
        )


def delete_auto_invest_plan(plan_id: int) -> None:
    with get_connection() as conn:
        conn.execute("DELETE FROM auto_invest_plans WHERE id=?", (plan_id,))


def get_auto_invest_plans() -> list[dict]:
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM auto_invest_plans ORDER BY id DESC"
        ).fetchall()
    return [dict(r) for r in rows]


def get_auto_invest_plan(plan_id: int) -> dict | None:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM auto_invest_plans WHERE id=?", (plan_id,)
        ).fetchone()
    return dict(row) if row else None


def get_due_auto_invest_plans(today: str) -> list[dict]:
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM auto_invest_plans WHERE enabled=1 "
            "AND next_run IS NOT NULL AND next_run<=? "
            "ORDER BY next_run ASC, id ASC",
            (today,),
        ).fetchall()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# 自选关注列表
# ---------------------------------------------------------------------------
def add_to_watchlist(fund_code: str, note: str = "", group_name: str = "") -> None:
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO watchlist(fund_code, note, group_name) VALUES(?,?,?) "
            "ON CONFLICT(fund_code) DO UPDATE SET note=excluded.note, group_name=excluded.group_name",
            (fund_code.strip(), note, group_name),
        )


def remove_from_watchlist(fund_code: str) -> None:
    with get_connection() as conn:
        conn.execute("DELETE FROM watchlist WHERE fund_code=?", (fund_code,))


def update_watchlist_group(fund_code: str, group_name: str) -> None:
    with get_connection() as conn:
        conn.execute(
            "UPDATE watchlist SET group_name=? WHERE fund_code=?",
            (group_name, fund_code),
        )


def get_watchlist() -> list[dict]:
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT w.fund_code, w.note, w.group_name, w.added_at, "
            "f.fund_name, f.fund_type, f.sector, f.tracking_index "
            "FROM watchlist w LEFT JOIN funds f ON w.fund_code=f.fund_code "
            "ORDER BY w.group_name, w.added_at DESC"
        ).fetchall()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# 分红提醒 (dividend_alerts) CRUD
# ---------------------------------------------------------------------------
def add_dividend_alert(alert: dict) -> int:
    """新增一条分红提醒（INSERT OR IGNORE 防 UNIQUE 竞态），返回 id。"""
    with get_connection() as conn:
        cur = conn.execute(
            """INSERT OR IGNORE INTO dividend_alerts
               (fund_code, fund_name, record_date, ex_date, per_share,
                pay_date, held_shares, estimated_amount, dividend_method)
               VALUES(?,?,?,?,?,?,?,?,?)""",
            (alert["fund_code"], alert.get("fund_name", ""),
             alert.get("record_date"), alert.get("ex_date"),
             alert.get("per_share"), alert.get("pay_date"),
             alert.get("held_shares"), alert.get("estimated_amount"),
             alert.get("dividend_method", "cash")),
        )
        return int(cur.lastrowid)


def get_dividend_alerts(status: str | None = None) -> list[dict]:
    """获取分红提醒列表（仅 dividend 类型）。status=None 返回全部。"""
    with get_connection() as conn:
        if status is None:
            rows = conn.execute(
                "SELECT * FROM dividend_alerts WHERE alert_type='dividend' OR alert_type IS NULL ORDER BY id DESC"
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM dividend_alerts WHERE (alert_type='dividend' OR alert_type IS NULL) AND status=? ORDER BY id DESC",
                (status,),
            ).fetchall()
    return [dict(r) for r in rows]


def get_pending_alert_count(alert_type: str | None = None) -> int:
    """返回 pending 状态的提醒数量。alert_type=None 返回全部。"""
    with get_connection() as conn:
        if alert_type:
            row = conn.execute(
                "SELECT COUNT(*) c FROM dividend_alerts WHERE status='pending' AND alert_type=?",
                (alert_type,),
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT COUNT(*) c FROM dividend_alerts WHERE status='pending'"
            ).fetchone()
    return row["c"] if row else 0


def update_dividend_alert(alert_id: int, **fields) -> None:
    """更新分红提醒字段（status / resolved_at / tx_id 等）。"""
    if not fields:
        return
    allowed = {"status", "resolved_at", "tx_id"}
    updates = {k: v for k, v in fields.items() if k in allowed}
    if not updates:
        return
    set_clause = ", ".join(f"{k}=?" for k in updates)
    vals = list(updates.values()) + [alert_id]
    with get_connection() as conn:
        conn.execute(
            f"UPDATE dividend_alerts SET {set_clause} WHERE id=?", vals
        )


def delete_dividend_alert(alert_id: int) -> bool:
    """删除一条分红提醒（仅 dividend 类型）。返回是否删除成功。"""
    with get_connection() as conn:
        cur = conn.execute(
            "DELETE FROM dividend_alerts WHERE id=? AND (alert_type='dividend' OR alert_type IS NULL)",
            (alert_id,),
        )
        return cur.rowcount > 0


# ---------------------------------------------------------------------------
# 止盈止损提醒 (tp_sl) CRUD
# ---------------------------------------------------------------------------
_PREF_TP_SL_PREFIX = "tp_sl_"


def get_tp_sl_config() -> dict:
    keys = {
        "enabled": "false",
        "take_profit_enabled": "true",
        "stop_loss_enabled": "true",
        "take_profit": "0.20",
        "stop_loss": "-0.15",
        "reset_ratio": "0.80",
    }
    for k, default in keys.items():
        val = get_preference(_PREF_TP_SL_PREFIX + k)
        if val is not None:
            keys[k] = val
    return keys


def update_tp_sl_config(**kwargs) -> None:
    allowed = {"enabled", "take_profit_enabled", "stop_loss_enabled",
               "take_profit", "stop_loss", "reset_ratio"}
    for k, v in kwargs.items():
        if k in allowed:
            if isinstance(v, bool):
                v = "true" if v else "false"
            upsert_preference(_PREF_TP_SL_PREFIX + k, str(v))


def add_tp_sl_alert(alert: dict) -> int:
    with get_connection() as conn:
        cur = conn.execute(
            """INSERT INTO dividend_alerts
               (fund_code, fund_name, alert_type, triggered_return, threshold,
                status, created_at)
               VALUES(?,?,?,?,?,?,datetime('now','localtime'))""",
            (alert["fund_code"], alert.get("fund_name", ""),
             alert["alert_type"], alert.get("triggered_return"),
             alert.get("threshold"), "pending"),
        )
        return int(cur.lastrowid)


def tp_sl_alert_exists(fund_code: str, alert_type: str, trigger_date: str) -> bool:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT 1 FROM dividend_alerts WHERE fund_code=? AND alert_type=? AND date(created_at)=? LIMIT 1",
            (fund_code, alert_type, trigger_date),
        ).fetchone()
    return row is not None


def get_tp_sl_alerts(status: str | None = None) -> list[dict]:
    with get_connection() as conn:
        if status is None:
            rows = conn.execute(
                "SELECT * FROM dividend_alerts WHERE alert_type IN ('take_profit','stop_loss') ORDER BY id DESC"
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM dividend_alerts WHERE alert_type IN ('take_profit','stop_loss') AND status=? ORDER BY id DESC",
                (status,),
            ).fetchall()
    return [dict(r) for r in rows]


def get_tp_sl_alert_state(fund_code: str, alert_type: str) -> dict | None:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM tp_sl_alert_states WHERE fund_code=? AND alert_type=?",
            (fund_code, alert_type),
        ).fetchone()
    return dict(row) if row else None


def get_tp_sl_alert_states_batch(
    fund_codes: list[str],
) -> dict[tuple[str, str], dict]:
    """批量获取止盈止损状态（单次查询）。

    Returns:
        {(fund_code, alert_type): state_dict}
    """
    if not fund_codes:
        return {}
    with get_connection() as conn:
        ph = ",".join("?" for _ in fund_codes)
        rows = conn.execute(
            f"SELECT * FROM tp_sl_alert_states WHERE fund_code IN ({ph})",
            fund_codes,
        ).fetchall()
    return {(r["fund_code"], r["alert_type"]): dict(r) for r in rows}


def upsert_tp_sl_alert_state(fund_code: str, alert_type: str, **fields) -> None:
    allowed = {"last_alert_id", "last_triggered_return", "handled_at", "armed"}
    updates = {k: v for k, v in fields.items() if k in allowed}
    if not updates:
        return
    insert_cols = ["fund_code", "alert_type"] + sorted(updates.keys())
    insert_vals = [fund_code, alert_type] + [updates[k] for k in sorted(updates.keys())]
    placeholders = ", ".join("?" for _ in insert_cols)
    cols_str = ", ".join(insert_cols)
    update_parts = [f"{k}=?" for k in sorted(updates.keys())]
    update_parts.append("updated_at=datetime('now','localtime')")
    set_clause = ", ".join(update_parts)
    update_vals = [updates[k] for k in sorted(updates.keys())]
    with get_connection() as conn:
        conn.execute(
            f"""INSERT INTO tp_sl_alert_states ({cols_str})
                VALUES ({placeholders})
                ON CONFLICT(fund_code, alert_type) DO UPDATE SET {set_clause}""",
            insert_vals + update_vals,
        )


def get_pending_tp_sl_alert_count() -> int:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT COUNT(*) c FROM dividend_alerts WHERE alert_type IN ('take_profit','stop_loss') AND status='pending'"
        ).fetchone()
    return row["c"] if row else 0


def dividend_alert_exists(fund_code: str, ex_date: str) -> bool:
    """检查某基金某除息日的分红提醒是否已存在（仅 dividend 类型）。

    查所有状态：ignored 后不再重复提醒；用户改主意可手动调 GET /check（不查本表）。
    """
    with get_connection() as conn:
        row = conn.execute(
            "SELECT 1 FROM dividend_alerts WHERE fund_code=? AND ex_date=? "
            "AND COALESCE(alert_type, 'dividend')='dividend' LIMIT 1",
            (fund_code, ex_date),
        ).fetchone()
    return row is not None


if __name__ == "__main__":
    init_db()
    print(f"数据库已初始化：{config.DB_PATH}")
