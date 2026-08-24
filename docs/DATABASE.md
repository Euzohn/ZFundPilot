# ZFundPilot 数据库设计文档

数据库：SQLite，文件路径 `data/fund.db`（由 `config.DB_PATH` 指定）。

连接管理：`db.get_connection()` 上下文管理器，每次请求独立连接，`row_factory = sqlite3.Row`，自动 commit/rollback/close。

---

## 表结构总览

| 表 | 用途 | 主键 |
|---|---|---|---|
| `funds` | 基金基础信息 | `fund_code` |
| `transactions` | 交易流水（买入/卖出/分红/再投资） | `id` (自增) |
| `nav_history` | 基金净值历史 | `id` (自增)，`UNIQUE(fund_code, date)` |
| `portfolio_snapshots` | 组合每日快照 | `id` (自增)，`UNIQUE(date)` |
| `audit_log` | 审计日志（敏感操作记录） | `id` (自增) |
| `auto_invest_plans` | 定投计划 | `id` (自增) |
| `watchlist` | 自选关注列表 | `fund_code` |
| `ai_usage` | AI token 用量记录 | `id` (自增) |
| `preferences` | 偏好设置 key-value | `key` |
| `dividend_alerts` | 提醒列表（分红 + 止盈止损） | `id` (自增) |
| `tp_sl_alert_states` | 止盈止损状态机 | `(fund_code, alert_type)` |
| `index_history` | 指数历史收盘价（基准对比，持久化缓存） | `id` (自增)，`UNIQUE(code, date)` |

---

## 1. funds — 基金基础信息

一只基金一条记录。首次录入交易时自动创建，也可通过 `fetch_fund_meta()` 补全名称/类型/板块。

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| `fund_code` | TEXT | PRIMARY KEY | 基金代码（如 `005827`） |
| `fund_name` | TEXT | DEFAULT '' | 基金名称 |
| `fund_type` | TEXT | DEFAULT '其它' | 基金类型（混合型/指数型/QDII/债券型/股票型/其它） |
| `sector` | TEXT | DEFAULT '' | 板块（如 科技/消费/医药） |
| `tracking_index` | TEXT | DEFAULT '' | 跟踪指数关键词（指数型基金用于实时估值，如 沪深300/半导体材料设备） |
| `dividend_method` | TEXT | DEFAULT 'cash' | 分红方式：`cash` / `reinvest`（FundDetail 页可设置） |
| `created_at` | TEXT | DEFAULT datetime('now','localtime') | 创建时间 |
| `updated_at` | TEXT | DEFAULT datetime('now','localtime') | 更新时间 |

**基金类型**（`config.FUND_TYPES`）：混合型、指数型、QDII、债券型、股票型、其它

**权益类判定**（`config.EQUITY_LIKE_TYPES`）：混合型、指数型、股票型、QDII（债券型不算权益）

---

## 2. transactions — 交易流水

所有买入/卖出/分红/再投资记录。持仓不单独存表，由 `analysis.calculate_positions()` 从流水汇总计算。

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| `id` | INTEGER | PRIMARY KEY AUTOINCREMENT | 自增主键 |
| `fund_code` | TEXT | NOT NULL | 基金代码 |
| `action` | TEXT | NOT NULL | 交易方向：`buy` / `sell` / `dividend` / `reinvest` |
| `date` | TEXT | NOT NULL | 交易日期（YYYY-MM-DD） |
| `amount` | REAL | 可空 | 成交金额（正数）。**含手续费** |
| `shares` | REAL | 可空 | 成交份额（正数） |
| `nav` | REAL | 可空 | 成交净值 |
| `fee` | REAL | DEFAULT 0 | 手续费 |
| `channel` | TEXT | DEFAULT '' | 购买渠道（支付宝/理财通/天天基金等） |
| `note` | TEXT | DEFAULT '' | 备注 |
| `is_t1` | INTEGER | DEFAULT 0 | T+1 待确认标记（1=T+1，净值用 date+1 回填） |
| `created_at` | TEXT | DEFAULT datetime('now','localtime') | 创建时间 |

### 金额与手续费约定

> **`amount` 包含手续费**，这是全系统最核心的约定。

| 操作 | 公式 | 说明 |
|---|---|---|
| 买入 | `amount = shares × nav + fee` | 用户支付的总额（份额价值 + 手续费） |
| 卖出 | `amount = shares × nav - fee` | 用户收到的净额（份额价值 - 手续费） |
| 分红 | `amount = 到账金额` | 无手续费 |
| 再投资 | `amount = shares × nav` | 无手续费 |

`Transaction.normalize()` 方法根据已知两个字段补全第三个，精度：shares→2位小数，nav→4位小数，amount→2位小数。

### T+1 待确认交易

- `is_t1` 列标记 T+1 交易（1=T+1），`auto_invest.py` 在 15:00 后创建交易时自动设置
- **买入 T+1**：`amount` 已知，`shares` 和 `nav` 待净值确认（15:00 后净值公布）
- **卖出 T+1**：`shares` 已知，`fee` 和 `amount` 待净值确认（卖出手续费依赖卖出净值）
- `amount`/`shares`/`nav` 允许为 NULL，支持待确认状态
- 净值更新后 `_backfill_transaction_navs()` 自动回填缺失 nav 的交易（跳过分红）

### 索引

| 索引名 | 字段 | 用途 |
|---|---|---|
| `idx_tx_code` | `fund_code` | 按基金代码查询交易 |
| `idx_tx_date` | `date` | 按日期范围筛选 |

---

## 3. nav_history — 基金净值历史

每只基金每个交易日一条净值记录。由 `fetch_fund.update_fund_nav()` 从 AkShare/天天基金拉取。

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| `id` | INTEGER | PRIMARY KEY AUTOINCREMENT | 自增主键 |
| `fund_code` | TEXT | NOT NULL | 基金代码 |
| `date` | TEXT | NOT NULL | 净值日期（YYYY-MM-DD） |
| `nav` | REAL | NOT NULL | 单位净值 |
| `accumulated_nav` | REAL | 可空 | 累计净值 |
| `source` | TEXT | DEFAULT 'akshare' | 数据来源（akshare / eastmoney） |
| `created_at` | TEXT | DEFAULT datetime('now','localtime') | 创建时间 |

**唯一约束**：`UNIQUE(fund_code, date)` — 同一基金同一日期只有一条记录，重复拉取时 upsert 覆盖。

### 索引

| 索引名 | 字段 | 用途 |
|---|---|---|
| `idx_nav_code_date` | `(fund_code, date)` | 按基金+日期查询净值 |

---

## 4. portfolio_snapshots — 组合每日快照

组合层面的每日汇总数据。用于绘制历史收益曲线。

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| `id` | INTEGER | PRIMARY KEY AUTOINCREMENT | 自增主键 |
| `date` | TEXT | NOT NULL UNIQUE | 快照日期（YYYY-MM-DD），唯一 |
| `total_cost` | REAL | NOT NULL | 当日持仓总成本 |
| `total_value` | REAL | NOT NULL | 当日持仓总市值 |
| `total_profit` | REAL | NOT NULL | 当日总盈亏（市值 - 成本） |
| `total_return` | REAL | NOT NULL | 当日总收益率 |
| `created_at` | TEXT | DEFAULT datetime('now','localtime') | 创建时间 |

---

## 5. audit_log — 审计日志

敏感操作记录，用于安全审计和设置页面查看。

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| `id` | INTEGER | PRIMARY KEY AUTOINCREMENT | 自增主键 |
| `ts` | TEXT | NOT NULL | 操作时间（UTC ISO 8601） |
| `ip` | TEXT |  | 客户端 IP |
| `username` | TEXT |  | 操作用户名 |
| `action` | TEXT | NOT NULL | 操作类型（如 add_transaction / login_success / auto_invest_execute） |
| `detail` | TEXT |  | 操作详情（JSON 字符串） |

索引：`idx_audit_ts` on `ts DESC`。

---

## 6. auto_invest_plans — 定投计划

定投计划的配置和执行状态。调度器每天 09:00 检查到期计划并执行。

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| `id` | INTEGER | PRIMARY KEY AUTOINCREMENT | 自增主键 |
| `fund_code` | TEXT | NOT NULL | 基金代码 |
| `amount` | REAL | NOT NULL | 每次定投金额 |
| `cadence` | TEXT | NOT NULL | 频率：`daily` / `week` / `biweek` / `month` |
| `day_of_week` | INTEGER |  | 周定投日（0=周一 .. 6=周日） |
| `day_of_month` | INTEGER |  | 月定投日（1-31） |
| `channel` | TEXT | DEFAULT '' | 交易渠道 |
| `note` | TEXT | DEFAULT '定投' | 备注 |
| `enabled` | INTEGER | DEFAULT 1 | 是否启用（1=启用，0=停用） |
| `next_run` | TEXT |  | 下次执行日期（YYYY-MM-DD） |
| `last_run` | TEXT |  | 上次执行日期（YYYY-MM-DD） |
| `last_tx_id` | INTEGER |  | 上次执行生成的交易 ID（关联 transactions.id） |
| `created_at` | TEXT | DEFAULT datetime('now','localtime') | 创建时间 |
| `updated_at` | TEXT | DEFAULT datetime('now','localtime') | 更新时间 |

---

## 7. watchlist — 自选关注列表

追踪未持有的基金。通过 `POST /api/watchlist` 添加时自动获取基金 meta 并 upsert 到 `funds` 表。

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| `fund_code` | TEXT | PRIMARY KEY | 基金代码 |
| `note` | TEXT | DEFAULT '' | 用户备注 |
| `group_name` | TEXT | DEFAULT '' | 分组名称（v0.15.0 起支持分组管理） |
| `added_at` | TEXT | DEFAULT datetime('now','localtime') | 加入时间 |

查询时 LEFT JOIN `funds` 表获取基金名称/类型/板块。

---

## 8. ai_usage — AI token 用量记录

每次 AI 对话的 token 消耗记录。用于用量统计和趋势展示。

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| `id` | INTEGER | PRIMARY KEY AUTOINCREMENT | 自增主键 |
| `created_at` | TEXT | NOT NULL DEFAULT datetime('now','localtime') | 创建时间（本地时间） |
| `model` | TEXT | DEFAULT '' | 模型 ID（如 glm-4-plus） |
| `prompt_tokens` | INTEGER | DEFAULT 0 | 输入 token 数 |
| `completion_tokens` | INTEGER | DEFAULT 0 | 输出 token 数 |
| `total_tokens` | INTEGER | DEFAULT 0 | 总 token 数 |
| `turns` | INTEGER | DEFAULT 0 | 对话轮数 |

> 注：`created_at` 存的是本地时间（`datetime('now','localtime')`），前端展示时按 UTC 解析转本地时区。

---

## 9. preferences — 偏好设置

通用 key-value 存储，用于持久化用户偏好。各模块通过 `db.upsert_preference(key, value)` / `db.get_preference(key)` 读写。

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| `key` | TEXT | PRIMARY KEY | 偏好键名 |
| `value` | TEXT | NOT NULL DEFAULT '' | 偏好值（JSON 字符串或纯文本） |

### 已知 key 列表

| key | 值格式 | 说明 |
|---|---|---|
| `channels` | JSON 数组字符串 | 购买渠道顺序（如 `["支付宝","理财通",...]`） |
| `channel_colors` | JSON 对象字符串 | 渠道颜色映射（如 `{"支付宝":"#3b82f6",...}`） |
| `color_theme` | 纯文本 | 涨跌颜色主题：`international` / `china` |
| `nav_auto_update` | 纯文本 | 定时更新开关：`true` / `false` |
| `type_keywords_custom` | JSON 数组字符串 | 自定义类型关键词映射 |
| `sector_keywords_custom` | JSON 数组字符串 | 自定义板块关键词映射 |
| `dividend_auto_check` | 纯文本 | 分红自动检测开关：`true` / `false` |
| `t1_nav_fix_done` | 纯文本 | T+1 净值历史修复是否已完成：`1`/`0`（启动时一次性执行） |
| `tp_sl_enabled` | 纯文本 | 止盈止损总开关：`true` / `false`（默认 `false`） |
| `tp_sl_take_profit` | 纯文本 | 止盈阈值（数值字符串，如 `0.20` = 20%） |
| `tp_sl_stop_loss` | 纯文本 | 止损阈值（数值字符串，如 `-0.15` = -15%） |
| `tp_sl_take_profit_enabled` | 纯文本 | 止盈独立开关：`true` / `false`（默认 `true`） |
| `tp_sl_stop_loss_enabled` | 纯文本 | 止损独立开关：`true` / `false`（默认 `true`） |
| `tp_sl_reset_ratio` | 纯文本 | 止盈止损复位比例（默认 `0.80`，触发后收益率回落至 `threshold × ratio` 以下才重新 armed） |

---

## 10. dividend_alerts — 提醒列表

分红 + 止盈止损共用，通过 `alert_type` 区分。分红提醒由分红定时检测（每天 09:30）写入，止盈止损提醒由净值更新完成后的 `_run_tp_sl_check()` 写入。

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| `id` | INTEGER | PRIMARY KEY AUTOINCREMENT | 自增主键 |
| `fund_code` | TEXT | NOT NULL | 基金代码 |
| `fund_name` | TEXT | DEFAULT '' | 基金名称（tp_sl 写入时冗余） |
| `record_date` | TEXT | | 分红登记日（仅分红用） |
| `ex_date` | TEXT | | 除息日（仅分红用） |
| `per_share` | REAL | | 每份分红金额（仅分红用） |
| `pay_date` | TEXT | | 派息日（仅分红用） |
| `held_shares` | REAL | | 持有份额（仅分红用） |
| `estimated_amount` | REAL | | 预计分红金额（仅分红用） |
| `dividend_method` | TEXT | DEFAULT 'cash' | 分红方式：`cash` / `reinvest`（仅分红用） |
| `alert_type` | TEXT | DEFAULT 'dividend' | 提醒类型：`dividend` / `take_profit` / `stop_loss` |
| `triggered_return` | REAL | | 触发时的收益率（仅 tp_sl 用） |
| `threshold` | REAL | | 触发时的目标阈值（仅 tp_sl 用） |
| `status` | TEXT | DEFAULT 'pending' | 状态：`pending` / `confirmed` / `ignored` |
| `created_at` | TEXT | DEFAULT datetime('now','localtime') | 创建时间 |
| `resolved_at` | TEXT | | 处理时间（确认/忽略） |
| `tx_id` | INTEGER | | 关联交易 ID（分红确认入账时写入） |

索引：`idx_alert_status` on `status`，`idx_alert_code_ex` on `(fund_code, ex_date)`。

**兼容性**：`alert_type`/`triggered_return`/`threshold` 由 `_migrate_tp_sl()` 补充，旧数据 `alert_type` 默认为 `'dividend'` 无需回填。

---

## 11. tp_sl_alert_states — 止盈止损状态机

记录每只基金每个方向（止盈/止损）的 armed 状态，用于避免重复提醒。触发后 `armed=0`（disarmed），收益率回落到 `threshold × reset_ratio` 以下后恢复 `armed=1`。

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| `fund_code` | TEXT | NOT NULL | 基金代码 |
| `alert_type` | TEXT | NOT NULL | 方向：`take_profit` / `stop_loss` |
| `last_alert_id` | INTEGER | | 最近一次生成的提醒 ID（关联 dividend_alerts.id） |
| `last_triggered_return` | REAL | | 最近一次触发时的收益率 |
| `handled_at` | TEXT | | 最近一次触发时间 |
| `armed` | INTEGER | DEFAULT 1 | 是否可再次触发：1=armed / 0=disarmed |
| `updated_at` | TEXT | DEFAULT datetime('now','localtime') | 更新时间 |

**主键**：`PRIMARY KEY (fund_code, alert_type)` — 同一基金同一方向只有一条状态记录。

---

## 12. index_history — 指数历史收盘价

存储基准指数（沪深300/上证指数/创业板指）的历史日收盘价，作为 `fetch_index_history()` 的 L2 持久化缓存。在线拉取后自动写入，离线时从 DB 返回已有数据。

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| `id` | INTEGER | PK AUTOINCREMENT | 自增主键 |
| `code` | TEXT | NOT NULL | 指数代码（如 `000300` 沪深300） |
| `date` | TEXT | NOT NULL | 日期 `YYYY-MM-DD` |
| `close` | REAL | NOT NULL | 收盘价 |
| `source` | TEXT | DEFAULT 'sina' | 数据来源 |
| `created_at` | TEXT | DEFAULT datetime('now','localtime') | 创建时间 |

**唯一约束**：`UNIQUE(code, date)` — 同一指数同一日期只有一条记录，upsert 更新。

**索引**：`idx_index_code_date ON index_history(code, date)`

**相关函数**（db.py）：
- `upsert_index_history(code, points)`: 批量写入，`ON CONFLICT(code, date) DO UPDATE`
- `get_index_history(code, start_date?, end_date?)`: 按区间查询（date ASC）
- `get_index_latest_date(code)`: 返回某指数 DB 中最新日期

**三级缓存**（`fetch_estimate.fetch_index_history`）：
1. L1 内存缓存（`_index_hist_cache`，1h TTL）→ 命中即返回
2. L2 SQLite（`index_history` 表）→ DB 最新日期 < today 时触发 L3
3. L3 新浪在线（`ak.stock_zh_index_daily`）→ 成功后持久化到 L2，失败时从 L2 返回

**scheduler 集成**：`_update_benchmark_indices()` 在净值更新后调用，遍历 `config.BENCHMARK_INDICES` 逐只拉取并持久化。

---

## Python 数据模型（models.py）

数据库表通过 Python dataclass 映射，不使用 ORM。

### Fund

对应 `funds` 表。字段：`fund_code`、`fund_name`、`fund_type`、`sector`。

### Transaction

对应 `transactions` 表。核心方法：

- `normalize()`: 根据已知字段补全 amount/shares/nav，按 action 处理手续费
- `is_valid()`: 校验交易合法性（方向合法、必要字段非空）

### Position

**不对应数据库表**，由 `analysis.calculate_positions()` 从 transactions 流水汇总计算。

关键字段：
- `held_shares`: 当前持有份额
- `total_cost`: 当前持仓成本（移动加权平均，卖出时结转）
- `avg_cost_nav`: 持仓均价 = total_cost / held_shares
- `market_value`: 当前市值 = held_shares × latest_nav
- `unrealized_pnl`: 浮动盈亏 = market_value - total_cost
- `realized_pnl`: 已实现盈亏（历次卖出累计）
- `total_pnl`: 总盈亏 = 浮动 + 已实现（property）
- `weight`: 占组合比例
- `is_open`: 是否仍有持仓（含 T+1 待确认）（property）

### PortfolioSummary

**不对应数据库表**，由 `analysis.calculate_summary()` 从 positions 汇总。

关键字段：
- `total_cost` / `total_value` / `unrealized_pnl` / `realized_pnl` / `total_pnl` / `total_return`
- `total_buy` / `total_sell` / `total_dividend`: 累计买入/卖出/分红金额
- `holding_count`: 当前持仓基金数
- `max_single_weight` / `max_single_name`: 最大单基金占比及名称
- `as_of_date`: 最新净值日期
- `daily_pnl` / `daily_return`: 今日收益
- `week_pnl` / `week_return`: 本周收益
- `month_pnl` / `month_return`: 本月收益
- `year_pnl` / `year_return`: 今年收益

### 其他模型

| 模型 | 定义位置 | 说明 |
|---|---|---|
| `NavPoint` | models.py | 一条净值记录（fund_code/date/nav/accumulated_nav/source） |
| `FetchResult` | fetch_fund.py | 净值抓取结果（fund_code/ok/written/message/latest_date/latest_nav） |
| `FundMeta` | fetch_fund.py | 基金元信息（fund_code/fund_name/fund_type/sector/tracking_index） |
| `FeeLot` | fetch_fund.py | 赎回费 FIFO 明细（lot_date/shares/fee_rate/fee） |
| `CalcFeeResponse` | fetch_fund.py | 费率计算结果（fee/fee_rate/lots） |
| `RiskReport` | risk.py | 风险报告（max_drawdown/volatility/hhi/flags 等） |
| `RiskFlag` | risk.py | 风险提示条目（level/code/params/title/detail） |
| `Advice` | rebalance.py | 结构优化建议（code/params/category/text） |
| `BacktestResult` | backtest.py | 回测结果（含曲线 + 每期明细） |
| `AutoInvestPlan` | auto_invest.py | 定投计划（fund_code/amount/cadence/next_run 等） |

---

## 数据库迁移

`db.init_db()` 在应用启动时调用（幂等），包含以下迁移：

1. **建表**：所有 `CREATE TABLE IF NOT EXISTS`（含 `audit_log`、`auto_invest_plans`、`watchlist`、`dividend_alerts`、`index_history`）
2. **`_migrate_add_columns()`**: 为旧表补充新增列（`channel`、`is_t1`，回填 `note LIKE '%T+1确认%'` 的旧交易标记为 `is_t1=1`）
3. **`_migrate_relax_transactions_schema()`**: 重建 transactions 表，移除 `CHECK(action IN ('buy','sell'))` 约束和 `NOT NULL` 约束，支持 dividend/reinvest 和待确认交易
4. **`_migrate_legacy_holdings()`**: 旧版 `holdings` 表数据迁移为一条买入流水
5. **`_migrate_tp_sl()`**: 为 `dividend_alerts` 补充 `alert_type`/`triggered_return`/`threshold` 列，新建 `tp_sl_alert_states` 表

> `index_history` 表通过 `init_db()` 中的 `CREATE TABLE IF NOT EXISTS` 创建，无需单独迁移函数（新表，无历史数据兼容问题）。

---

## 数据流

```
用户录入交易 → transactions 表
                    ↓
        analysis.calculate_positions()
                    ↓
              Position 列表
                    ↓
        analysis.calculate_summary()
                    ↓
           PortfolioSummary

fetch_fund.update_fund_nav() → nav_history 表
                                    ↓
                          _backfill_transaction_navs()
                                    ↓
                          回填 transactions.nav
```
