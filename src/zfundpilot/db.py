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
from typing import Any

from . import config
from .models import Fund, NavPoint, Transaction


# ---------------------------------------------------------------------------
# 连接管理
# ---------------------------------------------------------------------------
@contextmanager
def get_connection(write: bool = False) -> Iterator[sqlite3.Connection]:
    """打开数据库连接；``write=True`` 时立即取得写锁。

    写事务需要先读后写（幂等检查、版本校验），若使用默认的延迟事务，
    并发时可能读到旧快照后在升级写锁阶段直接失败。``BEGIN IMMEDIATE``
    让写操作按 SQLite 写锁串行化，配合 ``busy_timeout`` 等待而非报错。
    """
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 5000")
    if write:
        conn.execute("BEGIN IMMEDIATE")
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
                purchase_status TEXT DEFAULT '',
                daily_limit     REAL DEFAULT 0,
                min_purchase    REAL DEFAULT 0,
                risk_level      TEXT DEFAULT '',
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
                added_at  TEXT DEFAULT (datetime('now','localtime')),
                revision  INTEGER NOT NULL DEFAULT 1
            );

            -- 自选墓碑：删除后保留前值与单调版本，防止旧请求或重建对象复用版本。
            CREATE TABLE IF NOT EXISTS watchlist_tombstones (
                fund_code   TEXT PRIMARY KEY,
                revision    INTEGER NOT NULL,
                note        TEXT DEFAULT '',
                group_name  TEXT DEFAULT '',
                added_at    TEXT,
                deleted_at  TEXT NOT NULL
            );

            -- 写操作幂等记录：同主体同键只执行一次，结果可重放以便重试。
            CREATE TABLE IF NOT EXISTS agent_operations (
                id             INTEGER PRIMARY KEY AUTOINCREMENT,
                principal_type TEXT NOT NULL,
                principal_id   TEXT NOT NULL,
                key_hash       TEXT NOT NULL,
                operation      TEXT NOT NULL,
                params_digest  TEXT NOT NULL,
                status         TEXT NOT NULL,
                result_json    TEXT,
                audit_id       INTEGER,
                created_at     TEXT NOT NULL,
                expires_at     TEXT,
                UNIQUE(principal_type, principal_id, key_hash)
            );
            CREATE INDEX IF NOT EXISTS idx_agent_ops_created
                ON agent_operations(created_at);

            -- 持久化刷新任务：服务重启把遗留 queued/running 标记 interrupted。
            CREATE TABLE IF NOT EXISTS refresh_jobs (
                id             INTEGER PRIMARY KEY AUTOINCREMENT,
                principal_type TEXT NOT NULL,
                principal_id   TEXT NOT NULL,
                job_type       TEXT NOT NULL DEFAULT 'data_refresh',
                params_digest  TEXT NOT NULL,
                status         TEXT NOT NULL,
                total          INTEGER NOT NULL DEFAULT 0,
                done           INTEGER NOT NULL DEFAULT 0,
                current        TEXT DEFAULT '',
                phase          TEXT DEFAULT '',
                result_json    TEXT,
                error          TEXT,
                created_at     TEXT NOT NULL,
                updated_at     TEXT NOT NULL,
                expires_at     TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_refresh_jobs_owner
                ON refresh_jobs(principal_type, principal_id);
            CREATE INDEX IF NOT EXISTS idx_refresh_jobs_status
                ON refresh_jobs(status);

            -- 账本操作提案：Agent 只提交待审批提案，网页管理员确认后由服务端执行。
            -- 提案内容可能含账本隐私，访问按创建者隔离；执行结果与业务写入同事务。
            CREATE TABLE IF NOT EXISTS operation_proposals (
                id                    INTEGER PRIMARY KEY AUTOINCREMENT,
                principal_type        TEXT NOT NULL,
                principal_id          TEXT NOT NULL,
                token_prefix          TEXT DEFAULT '',
                operation_type        TEXT NOT NULL,
                status                TEXT NOT NULL,
                params_json           TEXT NOT NULL,
                params_digest         TEXT NOT NULL,
                summary_json          TEXT,
                risk_level            TEXT DEFAULT 'medium',
                created_at            TEXT NOT NULL,
                expires_at            TEXT NOT NULL,
                reviewed_by           TEXT,
                reviewed_at           TEXT,
                rejection_reason      TEXT,
                execution_result_json TEXT,
                audit_id              INTEGER,
                completed_at          TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_proposals_status
                ON operation_proposals(status);
            CREATE INDEX IF NOT EXISTS idx_proposals_owner
                ON operation_proposals(principal_type, principal_id);
            CREATE INDEX IF NOT EXISTS idx_proposals_created
                ON operation_proposals(created_at);

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

            CREATE TABLE IF NOT EXISTS trade_calendar (
                date       TEXT PRIMARY KEY,
                created_at TEXT DEFAULT (datetime('now','localtime'))
            );

            CREATE TABLE IF NOT EXISTS agent_tokens (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                name         TEXT NOT NULL,
                token_hash   TEXT NOT NULL UNIQUE,
                token_prefix TEXT NOT NULL DEFAULT '',
                scopes       TEXT NOT NULL DEFAULT '',
                created_at   TEXT NOT NULL,
                expires_at   TEXT,
                last_used_at TEXT,
                revoked_at   TEXT
            );
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
    _migrate_add_purchase_status()
    _migrate_add_risk_level()
    _migrate_watchlist_revision()


def _migrate_add_risk_level() -> None:
    """为 funds 表补充 risk_level 字段（旧库升级）。幂等。"""
    with get_connection() as conn:
        cols = {r["name"] for r in
                conn.execute("PRAGMA table_info(funds)").fetchall()}
        if "risk_level" not in cols:
            conn.execute(
                "ALTER TABLE funds ADD COLUMN risk_level TEXT DEFAULT ''"
            )


def _migrate_watchlist_revision() -> None:
    """为 watchlist 补充 revision 列并回填版本 1。幂等。

    旧库没有版本概念，全部按 1 处理；此后任何写入都会递增，删除后版本
    留在墓碑表，避免重建对象复用旧版本触发 ABA 覆盖。
    """
    with get_connection() as conn:
        cols = {r["name"] for r in
                conn.execute("PRAGMA table_info(watchlist)").fetchall()}
        if not cols or "revision" in cols:
            return
        conn.execute(
            "ALTER TABLE watchlist ADD COLUMN revision INTEGER NOT NULL DEFAULT 1"
        )
        conn.execute("UPDATE watchlist SET revision=1")


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


def _migrate_add_purchase_status() -> None:
    """为 funds 表补充申购状态字段（旧库升级）。幂等。"""
    with get_connection() as conn:
        cols = {r["name"] for r in
                conn.execute("PRAGMA table_info(funds)").fetchall()}
        if "purchase_status" not in cols:
            conn.execute(
                "ALTER TABLE funds ADD COLUMN purchase_status TEXT DEFAULT ''"
            )
        if "daily_limit" not in cols:
            conn.execute(
                "ALTER TABLE funds ADD COLUMN daily_limit REAL DEFAULT 0"
            )
        if "min_purchase" not in cols:
            conn.execute(
                "ALTER TABLE funds ADD COLUMN min_purchase REAL DEFAULT 0"
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


def update_fund_purchase_status(
    fund_code: str, status: str, daily_limit: float, min_purchase: float
) -> None:
    """更新基金申购状态（定投执行前的可投性校验依据）。"""
    with get_connection() as conn:
        conn.execute(
            "UPDATE funds SET purchase_status=?, daily_limit=?, min_purchase=?, "
            "updated_at=datetime('now','localtime') WHERE fund_code=?",
            (status, daily_limit, min_purchase, fund_code),
        )


def update_fund_risk_level(fund_code: str, risk_level: str) -> None:
    """更新基金风险等级。"""
    with get_connection() as conn:
        conn.execute(
            "UPDATE funds SET risk_level=?, "
            "updated_at=datetime('now','localtime') WHERE fund_code=?",
            (risk_level, fund_code),
        )


# ---------------------------------------------------------------------------
# transactions 流水 CRUD
# ---------------------------------------------------------------------------
def insert_transaction(conn: sqlite3.Connection, tx: Transaction) -> int:
    """在调用方事务内插入一笔流水，返回 id；调用方负责 normalize 与提交。"""
    cur = conn.execute(
        """
        INSERT INTO transactions(fund_code,action,date,amount,shares,nav,fee,channel,note,is_t1,conversion_id)
        VALUES(?,?,?,?,?,?,?,?,?,?,?)
        """,
        (tx.fund_code.strip(), tx.action, tx.date, tx.amount, tx.shares,
         tx.nav, tx.fee, tx.channel, tx.note, int(tx.is_t1), tx.conversion_id),
    )
    return int(cur.lastrowid)


def add_transaction(tx: Transaction) -> int:
    """新增一笔流水，返回 id。会自动 normalize 补全字段。"""
    tx.normalize()
    with get_connection() as conn:
        return insert_transaction(conn, tx)


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


def get_transaction(tx_id: int) -> Transaction | None:
    """按 id 返回单笔流水；不存在返回 None。"""
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM transactions WHERE id=?", (tx_id,)
        ).fetchone()
    return Transaction.from_row(row) if row else None


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
                         points: Iterable[tuple[str, float]],
                         source: str = "sina") -> int:
    """批量写入指数历史收盘价。

    Args:
        code: 指数代码，如 "000300"（宏观代码 "CPI"/"M2" 也存此表）
        points: [(date, close), ...]
        source: 数据源标识，默认 "sina"；宏观数据传 "macro"

    Returns:
        写入行数。
    """
    rows = [(code, d, c, source) for d, c in points]
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
# A 股交易日历（定投可投性校验，fetch_fund.refresh_trade_calendar 写入）
# ---------------------------------------------------------------------------
_trade_cal_cache: frozenset[str] | None = None
_trade_cal_max: str | None = None


def upsert_trade_calendar(dates: list[str]) -> int:
    """批量写入交易日历（幂等）。失效内存缓存，返回写入行数。"""
    global _trade_cal_cache, _trade_cal_max
    rows = [(d,) for d in dates]
    if not rows:
        return 0
    with get_connection() as conn:
        conn.executemany(
            "INSERT INTO trade_calendar(date) VALUES(?) "
            "ON CONFLICT(date) DO NOTHING",
            rows,
        )
    _trade_cal_cache = None
    _trade_cal_max = None
    return len(rows)


def is_trading_day(date_str: str) -> bool:
    """判断某日是否为 A 股交易日（trade_calendar 表为准）。

    - 覆盖范围内不在日历 → 法定节假日/调休休市 → False
    - 表为空（首启未刷新/网络失败）→ 退化周末判断（fail-open）
    - 日期超出日历覆盖范围（如跨年日历未更新）→ 退化周末判断
    """
    global _trade_cal_cache, _trade_cal_max
    # 快照到局部变量，避免 upsert 并发清空缓存导致读到不一致的 (cal, max) 组合
    cal = _trade_cal_cache
    cal_max = _trade_cal_max
    if cal is None:
        with get_connection() as conn:
            rows = conn.execute("SELECT date FROM trade_calendar").fetchall()
        cal = frozenset(r["date"] for r in rows)
        cal_max = max(cal) if cal else None
        _trade_cal_cache, _trade_cal_max = cal, cal_max
    if not cal:
        d = datetime.strptime(date_str, "%Y-%m-%d").date()
        return d.weekday() < 5
    if date_str in cal:
        return True
    if cal_max and date_str > cal_max:
        d = datetime.strptime(date_str, "%Y-%m-%d").date()
        return d.weekday() < 5
    return False


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


def agent_write_enabled_conn(conn: sqlite3.Connection) -> bool:
    """在调用方事务内解析 Agent 写能力总开关的权威值。

    多 worker 部署时各进程的运行时 ``config.AGENT_WRITE_ENABLED`` 可能陈旧，
    因此执行写操作前必须回到 ``preferences`` 表复核。数据库无记录（从未在
    设置页切换过）时退回运行时值，与启动解析和测试替身保持一致。
    """
    row = conn.execute(
        "SELECT value FROM preferences WHERE key=?",
        (config.AGENT_WRITE_PREF_KEY,),
    ).fetchone()
    if row is None:
        return bool(config.AGENT_WRITE_ENABLED) and not config.AGENT_WRITE_ENV_LOCKED
    return config.resolve_agent_write_enabled(
        row["value"],
        env_locked=config.AGENT_WRITE_ENV_LOCKED,
        env_default=config.AGENT_WRITE_ENV_DEFAULT,
    )


def get_all_preferences() -> dict[str, str]:
    with get_connection() as conn:
        rows = conn.execute("SELECT key, value FROM preferences").fetchall()
    return {r["key"]: r["value"] for r in rows}


# ---------------------------------------------------------------------------
# 审计日志
# ---------------------------------------------------------------------------
def log_audit(action: str, ip: str | None = None,
              username: str | None = None,
              detail: dict | None = None,
              *,
              conn: sqlite3.Connection | None = None) -> int | None:
    """写入审计日志。

    传入 ``conn`` 时复用调用方事务（业务写入与审计同提交/同回滚），并返回
    审计行 id；不传时使用独立连接，行为与旧版一致。
    """
    sql = "INSERT INTO audit_log(ts, ip, username, action, detail) VALUES(?,?,?,?,?)"
    params = (
        datetime.now(config.TIMEZONE).isoformat(), ip, username, action,
        json.dumps(detail, ensure_ascii=False) if detail else None,
    )
    if conn is not None:
        return conn.execute(sql, params).lastrowid
    with get_connection() as own_conn:
        return own_conn.execute(sql, params).lastrowid


def fetch_audit_logs(limit: int = 100) -> list[dict]:
    """返回最近 N 条审计日志。"""
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM audit_log ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Agent token（服务端只存摘要，明文仅签发时返回一次）
# ---------------------------------------------------------------------------
_AGENT_TOKEN_PUBLIC_FIELDS = (
    "id", "name", "token_prefix", "scopes", "created_at",
    "expires_at", "last_used_at", "revoked_at",
)


def _agent_token_public(row: sqlite3.Row) -> dict:
    """将行转为可对外返回的元数据，剔除 token_hash。"""
    data = dict(row)
    return {k: data.get(k) for k in _AGENT_TOKEN_PUBLIC_FIELDS}


def create_agent_token(*, name: str, token_hash: str, token_prefix: str,
                       scopes: str, expires_at: str | None = None) -> dict:
    """插入一条 Agent token 摘要，返回不含摘要的元数据。"""
    now = datetime.now(config.TIMEZONE).isoformat()
    with get_connection() as conn:
        cur = conn.execute(
            "INSERT INTO agent_tokens(name, token_hash, token_prefix, scopes, "
            "created_at, expires_at) VALUES(?,?,?,?,?,?)",
            (name, token_hash, token_prefix, scopes, now, expires_at),
        )
        token_id = cur.lastrowid
        row = conn.execute(
            "SELECT * FROM agent_tokens WHERE id = ?", (token_id,)
        ).fetchone()
    return _agent_token_public(row)


def list_agent_tokens() -> list[dict]:
    """列出全部 Agent token 元数据（不含摘要）。"""
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM agent_tokens ORDER BY id DESC"
        ).fetchall()
    return [_agent_token_public(r) for r in rows]


def get_agent_token(token_id: int) -> dict | None:
    """按 id 返回元数据（不含摘要）。"""
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM agent_tokens WHERE id = ?", (token_id,)
        ).fetchone()
    return _agent_token_public(row) if row else None


def get_agent_token_conn(conn: sqlite3.Connection,
                         token_id: int) -> sqlite3.Row | None:
    """在调用方事务内按 id 读取 token 原始行（审批执行时复核权限用）。"""
    return conn.execute(
        "SELECT * FROM agent_tokens WHERE id = ?", (token_id,)
    ).fetchone()


def get_agent_token_by_hash(token_hash: str) -> dict | None:
    """按摘要查找 token（含内部字段，仅供鉴权使用，不得直接返回给客户端）。"""
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM agent_tokens WHERE token_hash = ?", (token_hash,)
        ).fetchone()
    return dict(row) if row else None


def revoke_agent_token(token_id: int) -> bool:
    """撤销 token；已撤销或不存在时返回 False。"""
    now = datetime.now(config.TIMEZONE).isoformat()
    with get_connection() as conn:
        cur = conn.execute(
            "UPDATE agent_tokens SET revoked_at = ? "
            "WHERE id = ? AND revoked_at IS NULL",
            (now, token_id),
        )
        return cur.rowcount > 0


def touch_agent_token(token_id: int) -> None:
    """更新 token 最近使用时间。"""
    now = datetime.now(config.TIMEZONE).isoformat()
    with get_connection() as conn:
        conn.execute(
            "UPDATE agent_tokens SET last_used_at = ? WHERE id = ?",
            (now, token_id),
        )


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
    """旧版直接写入（不做幂等/版本校验）；新增代码应走 watchlist_service。"""
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO watchlist(fund_code, note, group_name) VALUES(?,?,?) "
            "ON CONFLICT(fund_code) DO UPDATE SET note=excluded.note, "
            "group_name=excluded.group_name, revision=watchlist.revision+1",
            (fund_code.strip(), note, group_name),
        )


def remove_from_watchlist(fund_code: str) -> None:
    with get_connection() as conn:
        conn.execute("DELETE FROM watchlist WHERE fund_code=?", (fund_code,))


def update_watchlist_group(fund_code: str, group_name: str) -> None:
    with get_connection() as conn:
        conn.execute(
            "UPDATE watchlist SET group_name=?, revision=revision+1 "
            "WHERE fund_code=?",
            (group_name, fund_code),
        )


def get_watchlist() -> list[dict]:
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT w.fund_code, w.note, w.group_name, w.added_at, w.revision, "
            "f.fund_name, f.fund_type, f.sector, f.tracking_index "
            "FROM watchlist w LEFT JOIN funds f ON w.fund_code=f.fund_code "
            "ORDER BY w.group_name, w.added_at DESC"
        ).fetchall()
    return [dict(r) for r in rows]


# --- 自选受控写入（由 watchlist_service 在单一事务内调用）------------------
def fund_exists(conn: sqlite3.Connection, fund_code: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM funds WHERE fund_code=?", (fund_code,)
    ).fetchone()
    return row is not None


def get_watchlist_item(conn: sqlite3.Connection,
                       fund_code: str) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT fund_code, note, group_name, added_at, revision "
        "FROM watchlist WHERE fund_code=?",
        (fund_code,),
    ).fetchone()


def insert_watchlist_item(conn: sqlite3.Connection, fund_code: str, note: str,
                          group_name: str, revision: int) -> None:
    conn.execute(
        "INSERT INTO watchlist(fund_code, note, group_name, revision) "
        "VALUES(?,?,?,?)",
        (fund_code, note, group_name, revision),
    )


def update_watchlist_item(conn: sqlite3.Connection, fund_code: str, note: str,
                          group_name: str, revision: int) -> None:
    conn.execute(
        "UPDATE watchlist SET note=?, group_name=?, revision=? "
        "WHERE fund_code=?",
        (note, group_name, revision, fund_code),
    )


def delete_watchlist_item(conn: sqlite3.Connection, fund_code: str) -> None:
    conn.execute("DELETE FROM watchlist WHERE fund_code=?", (fund_code,))


def get_watchlist_tombstone(conn: sqlite3.Connection,
                            fund_code: str) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT fund_code, revision, note, group_name, added_at, deleted_at "
        "FROM watchlist_tombstones WHERE fund_code=?",
        (fund_code,),
    ).fetchone()


def upsert_watchlist_tombstone(conn: sqlite3.Connection, fund_code: str,
                               revision: int, note: str, group_name: str,
                               added_at: str | None, deleted_at: str) -> None:
    conn.execute(
        "INSERT INTO watchlist_tombstones"
        "(fund_code, revision, note, group_name, added_at, deleted_at) "
        "VALUES(?,?,?,?,?,?) "
        "ON CONFLICT(fund_code) DO UPDATE SET revision=excluded.revision, "
        "note=excluded.note, group_name=excluded.group_name, "
        "added_at=excluded.added_at, deleted_at=excluded.deleted_at",
        (fund_code, revision, note, group_name, added_at, deleted_at),
    )


def delete_watchlist_tombstone(conn: sqlite3.Connection, fund_code: str) -> None:
    conn.execute(
        "DELETE FROM watchlist_tombstones WHERE fund_code=?", (fund_code,)
    )


def get_watchlist_tombstones() -> list[dict]:
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT t.fund_code, t.revision, t.note, t.group_name, "
            "t.added_at, t.deleted_at, f.fund_name "
            "FROM watchlist_tombstones t "
            "LEFT JOIN funds f ON t.fund_code=f.fund_code "
            "ORDER BY t.deleted_at DESC"
        ).fetchall()
    return [dict(r) for r in rows]


# --- 写操作幂等记录 --------------------------------------------------------
def get_operation(conn: sqlite3.Connection, principal_type: str,
                  principal_id: str, key_hash: str) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM agent_operations "
        "WHERE principal_type=? AND principal_id=? AND key_hash=?",
        (principal_type, principal_id, key_hash),
    ).fetchone()


def insert_operation(conn: sqlite3.Connection, *, principal_type: str,
                     principal_id: str, key_hash: str, operation: str,
                     params_digest: str, status: str, result_json: str,
                     audit_id: int | None, created_at: str,
                     expires_at: str | None) -> int:
    cur = conn.execute(
        "INSERT INTO agent_operations"
        "(principal_type, principal_id, key_hash, operation, params_digest, "
        "status, result_json, audit_id, created_at, expires_at) "
        "VALUES(?,?,?,?,?,?,?,?,?,?)",
        (principal_type, principal_id, key_hash, operation, params_digest,
         status, result_json, audit_id, created_at, expires_at),
    )
    return int(cur.lastrowid)


# ---------------------------------------------------------------------------
# 刷新任务 (refresh_jobs)
# ---------------------------------------------------------------------------
def insert_refresh_job(conn: sqlite3.Connection, *, principal_type: str,
                       principal_id: str, job_type: str, params_digest: str,
                       status: str, created_at: str, updated_at: str,
                       expires_at: str | None) -> int:
    cur = conn.execute(
        "INSERT INTO refresh_jobs"
        "(principal_type, principal_id, job_type, params_digest, status, "
        "created_at, updated_at, expires_at) VALUES(?,?,?,?,?,?,?,?)",
        (principal_type, principal_id, job_type, params_digest, status,
         created_at, updated_at, expires_at),
    )
    return int(cur.lastrowid)


def get_refresh_job(conn: sqlite3.Connection, job_id: int,
                    principal_type: str, principal_id: str) -> sqlite3.Row | None:
    """按归属读取任务；他人任务返回 None（查询层据此 404，不泄漏存在性）。"""
    return conn.execute(
        "SELECT * FROM refresh_jobs WHERE id=? AND principal_type=? "
        "AND principal_id=?",
        (job_id, principal_type, principal_id),
    ).fetchone()


def update_refresh_job(conn: sqlite3.Connection, job_id: int, *,
                       status: str | None = None, total: int | None = None,
                       done: int | None = None, current: str | None = None,
                       phase: str | None = None, result_json: str | None = None,
                       error: str | None = None, updated_at: str) -> None:
    sets: list[str] = ["updated_at=?"]
    params: list[Any] = [updated_at]
    if status is not None:
        sets.append("status=?")
        params.append(status)
    if total is not None:
        sets.append("total=?")
        params.append(total)
    if done is not None:
        sets.append("done=?")
        params.append(done)
    if current is not None:
        sets.append("current=?")
        params.append(current)
    if phase is not None:
        sets.append("phase=?")
        params.append(phase)
    if result_json is not None:
        sets.append("result_json=?")
        params.append(result_json)
    if error is not None:
        sets.append("error=?")
        params.append(error)
    params.append(job_id)
    conn.execute(f"UPDATE refresh_jobs SET {', '.join(sets)} WHERE id=?", params)


def mark_interrupted_refresh_jobs(now: str) -> int:
    """启动时把遗留 queued/running 标记为 interrupted，避免永久 running。"""
    with get_connection() as conn:
        cur = conn.execute(
            "UPDATE refresh_jobs SET status='interrupted', updated_at=? "
            "WHERE status IN ('queued','running')",
            (now,),
        )
        return int(cur.rowcount)


def purge_refresh_jobs(cutoff: str) -> int:
    """清理过期较久的任务记录，避免表无限增长。"""
    with get_connection() as conn:
        cur = conn.execute(
            "DELETE FROM refresh_jobs WHERE expires_at IS NOT NULL "
            "AND expires_at < ?",
            (cutoff,),
        )
        return int(cur.rowcount)


# ---------------------------------------------------------------------------
# 账本操作提案 (operation_proposals)
# ---------------------------------------------------------------------------
def insert_proposal(conn: sqlite3.Connection, *, principal_type: str,
                    principal_id: str, token_prefix: str, operation_type: str,
                    status: str, params_json: str, params_digest: str,
                    summary_json: str, risk_level: str, created_at: str,
                    expires_at: str) -> int:
    cur = conn.execute(
        "INSERT INTO operation_proposals"
        "(principal_type, principal_id, token_prefix, operation_type, status, "
        "params_json, params_digest, summary_json, risk_level, created_at, "
        "expires_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
        (principal_type, principal_id, token_prefix, operation_type, status,
         params_json, params_digest, summary_json, risk_level, created_at,
         expires_at),
    )
    return int(cur.lastrowid)


def get_proposal(conn: sqlite3.Connection, proposal_id: int) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM operation_proposals WHERE id=?", (proposal_id,)
    ).fetchone()


def get_proposal_for_owner(conn: sqlite3.Connection, proposal_id: int,
                           principal_type: str,
                           principal_id: str) -> sqlite3.Row | None:
    """按归属读取提案；他人提案返回 None（查询层据此 404，不泄漏存在性）。"""
    return conn.execute(
        "SELECT * FROM operation_proposals WHERE id=? AND principal_type=? "
        "AND principal_id=?",
        (proposal_id, principal_type, principal_id),
    ).fetchone()


def list_proposals(conn: sqlite3.Connection, *, status: str | None = None,
                   limit: int = 50, offset: int = 0) -> list[sqlite3.Row]:
    sql = "SELECT * FROM operation_proposals"
    params: list[Any] = []
    if status:
        sql += " WHERE status=?"
        params.append(status)
    sql += " ORDER BY id DESC LIMIT ? OFFSET ?"
    params.extend([limit, offset])
    return conn.execute(sql, params).fetchall()


def count_proposals(conn: sqlite3.Connection, status: str | None = None) -> int:
    sql = "SELECT COUNT(*) FROM operation_proposals"
    params: list[Any] = []
    if status:
        sql += " WHERE status=?"
        params.append(status)
    return int(conn.execute(sql, params).fetchone()[0])


def update_proposal(conn: sqlite3.Connection, proposal_id: int, *,
                    status: str | None = None, reviewed_by: str | None = None,
                    reviewed_at: str | None = None,
                    rejection_reason: str | None = None,
                    execution_result_json: str | None = None,
                    audit_id: int | None = None,
                    completed_at: str | None = None) -> None:
    sets: list[str] = []
    params: list[Any] = []
    for column, value in (
        ("status", status),
        ("reviewed_by", reviewed_by),
        ("reviewed_at", reviewed_at),
        ("rejection_reason", rejection_reason),
        ("execution_result_json", execution_result_json),
        ("audit_id", audit_id),
        ("completed_at", completed_at),
    ):
        if value is not None:
            sets.append(f"{column}=?")
            params.append(value)
    if not sets:
        return
    params.append(proposal_id)
    conn.execute(
        f"UPDATE operation_proposals SET {', '.join(sets)} WHERE id=?", params)


def expire_pending_proposals(now: str) -> int:
    """把已过期但仍 pending 的提案标记 expired；只影响未审批提案。"""
    with get_connection(write=True) as conn:
        cur = conn.execute(
            "UPDATE operation_proposals SET status='expired', completed_at=? "
            "WHERE status='pending' AND expires_at <= ?",
            (now, now),
        )
        return int(cur.rowcount)


def purge_proposals(cutoff: str) -> int:
    """清理过期较久的已结束提案记录，避免表无限增长。"""
    with get_connection(write=True) as conn:
        cur = conn.execute(
            "DELETE FROM operation_proposals WHERE status IN "
            "('succeeded','failed','conflict','rejected','cancelled','expired') "
            "AND completed_at IS NOT NULL AND completed_at < ?",
            (cutoff,),
        )
        return int(cur.rowcount)


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
