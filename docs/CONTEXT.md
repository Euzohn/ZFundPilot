# ZFundPilot 项目上下文（供 AI Agent 使用）

> 每次新对话开始时，Agent 应先读取此文件了解项目全貌。

---

## 一、项目概述

**ZFundPilot** — 个人基金分析与风险管理系统。

Web 应用，支持本地开发和服务器部署（Docker）。核心功能：管理基金持仓 → 自动更新净值 → 计算收益与风险 → 提供结构优化建议。不是交易系统，不做自动买卖，不连接券商。

> ⚠️ Agent 在本地开发时不要正式运行或测试，仅做代码编写和类型检查。服务器端部署通过 Docker 完成。

- **仓库**: `git@github.com:Euzohn/ZFundPilot.git`，分支 `main`
- **版本**: `0.16.0`（git tag `v0.16.0`）
- **License**: MIT

---

## 二、技术栈

| 层 | 技术 |
|---|---|
| 前端 | React 18 + Vite + TypeScript + Tailwind CSS + shadcn/ui + Recharts |
| 后端 | FastAPI + SQLite + Pandas + AkShare |
| 定时任务 | APScheduler（BackgroundScheduler，进程内） |
| 部署 | Docker（多阶段构建：node 前端构建 → python 运行时）+ docker-compose |
| 服务器 | 单容器 `restart: always`，`data/` 卷挂载 |

---

## 三、项目结构

```
ZFundPilot/
├── src/zfundpilot/          # Python 后端
│   ├── __init__.py          # __version__ = "0.16.0"
│   ├── api.py               # FastAPI 路由（所有 /api/* 端点）
│   ├── config.py            # 全局配置、环境变量、认证管理
│   ├── db.py                # SQLite 操作层（连接管理 + CRUD + 迁移）
│   ├── models.py            # 数据结构（Fund/Transaction/Position/PortfolioSummary）
│   ├── fetch_fund.py        # 基金净值获取（AkShare 优先，天天基金 fallback）+ 重仓股/排名/档案
│   ├── fetch_estimate.py   # 基金实时估值（东财估值 + 指数/ETF 兜底）
│   ├── compare.py           # 基金对比（收益率/风险/相关性多维度计算）
│   ├── fund_filter.py       # 基金筛选器（全市场池加载 + 多条件筛选 + 指标增强 Top 30）
│   ├── analysis.py          # 收益计算（持仓汇总 + 收益曲线 + 缓存）
│   ├── risk.py              # 风险分析（回撤/波动率/集中度/HHI）
│   ├── rebalance.py         # 再平衡建议
│   ├── backtest.py          # 定投策略回测（DCA + 一次性投入对比 + XIRR）
│   ├── auto_invest.py       # 定投计划自动执行（4 种频率 + 交易日顺延）
│   ├── crypto.py            # 敏感字段加密（Fernet，AI API key 等落盘加密）
│   ├── scheduler.py         # APScheduler 定时净值更新
│   ├── ai.py                # AI 投顾（OpenAI 兼容 API + 联网搜索）
│   └── data_io.py           # CSV 导入/导出 + 全量备份 ZIP
├── frontend/src/            # React 前端
│   ├── App.tsx              # 路由（/ → Home 独立页，其余在 Layout 内）
│   ├── pages/               # 15 个页面
│   │   ├── Home.tsx         # 首页（brutalist 战术终端风格，中英双语切换）
│   │   ├── Overview.tsx     # 组合总览
│   │   ├── Transactions.tsx # 交易管理（录入/流水/CSV/定投计划）
│   │   ├── NavUpdate.tsx    # 净值更新
│   │   ├── Positions.tsx    # 持仓明细
│   │   ├── Returns.tsx      # 收益分析（曲线/排名/日历）
│   │   ├── Risk.tsx         # 风险评估
│   │   ├── FundCompare.tsx     # 基金对比（多维度同框对比 + 相关性矩阵）
│   │   ├── Screener.tsx       # 基金筛选（全市场筛选 + 指标排序 + 加自选/对比）
│   │   ├── Watchlist.tsx      # 自选关注列表（追踪未持有基金）
│   │   ├── Backtest.tsx       # 定投回测（DCA vs 一次性投入 + 累计曲线 + 每期明细）
│   │   ├── AIChat.tsx       # AI 投顾对话
│   │   ├── FundDetail.tsx   # 基金详情（净值走势 + 持仓卡片 + 排名 + 档案 + 交易标记）
│   │   ├── Settings.tsx     # 设置（账户/AI/偏好）
│   │   └── Login.tsx        # 登录
│   ├── components/          # Layout + Logo 系列 + PnLCalendar + 业务组件（MetricCard/SortHeader/PageHeader/ConfirmDialog/TransactionDetailDialog/EmptyState/LoadingState/ThemeToggle/LanguageToggle）+ UI 组件（shadcn dialog/tooltip/popover 等）
│   ├── i18n/                # LanguageContext（Provider + useLang hook + getCurrentLang）+ zh.ts + en.ts
│   ├── api/                 # client.ts + types.ts
│   ├── hooks/               # useCountUp（animejs 数字动画，formatter 用 ref 存储避免 effect 重跑）
│   └── lib/                 # auth/channels/channelColors/colorTheme/format（按 lang 切换 ¥/$）/actionLabels/rangeLabels/useApi/backendLabels/taxonomyLabels
├── data/                    # SQLite 数据库 + auth.json + ai_config.json（gitignore）
├── Dockerfile               # 多阶段构建
├── docker-compose.yml       # 单服务 + data 卷
├── update.sh                # 部署脚本（git pull + docker compose up -d --build）
├── pyproject.toml           # Python 依赖 + ruff/pytest 配置
├── CHANGELOG.md             # 版本变更记录
├── README.md / README_EN.md # 项目说明（中/英）
├── NOTICE.md                # 数据来源与合规声明（License MIT 补充）
├── DEPLOY.md                # 部署文档
├── .env.example             # 环境变量示例
├── .github/workflows/       # GitHub Actions CI/CD
│   └── ci.yml               #   ruff → pytest (3.10/3.11/3.12 并行) → tsc → build
├── tests/                   # Pytest 测试套件
│   ├── conftest.py          #   共享 fixtures（make_plan/make_tx_row/PatchAutoInvest）
│   └── test_*.py            #   134 个测试用例
└── docs/CONTEXT.md              # 本文件（不追踪）
```

---

## 四、数据模型

### 数据库表（SQLite）

| 表 | 说明 |
|---|---|---|
| `funds` | 基金基础信息（code/name/type/sector） |
| `transactions` | 交易流水（buy/sell/dividend/reinvest） |
| `nav_history` | 基金净值历史（fund_code + date + nav） |
| `portfolio_snapshots` | 组合每日快照 |
| `watchlist` | 自选关注列表（fund_code + note + added_at，关联 funds 表） |
| `ai_usage` | AI token 用量记录 |
| `preferences` | 偏好设置 key-value（channels/channel_colors/color_theme/nav_auto_update/type_keywords_custom/sector_keywords_custom） |
| `audit_log` | 审计日志（ts/ip/username/action/detail），记录敏感操作 |

### 核心模型（models.py）

- **Transaction**: `fund_code`/`action`/`date`/`amount`/`shares`/`nav`/`fee`/`channel`/`note`
  - `normalize()`: amount/shares/nav 给出任意两个补全第三个，按 action 处理手续费
  - **P&L 约定**: `amount` **含手续费**（买入 = 付的总额，卖出 = 收的净额）
  - 买入: `amount = shares × nav + fee`
  - 卖出: `amount = shares × nav - fee`
  - 分红/再投资: 无手续费
- **Position**: 由 transactions 汇总计算（移动加权平均成本法）
  - `pending_buy_cost`: 待确认买入金额（T+1 份额未知时，金额计入此字段而非 `total_cost`，不参与市值/盈亏/收益率计算，仅用于 `is_open` 判断）
  - `is_open`: `held_shares > 1e-6 or total_cost > 1e-6 or pending_buy_cost > 1e-6`（含 T+1 待确认）
- **PortfolioSummary**: 组合层面汇总（含 daily/week/month/year P&L）

### T+1 交易处理

- **买入 T+1**: amount 已知，shares 待净值确认（`shares = (amount - fee) / nav`）
- **卖出 T+1**: shares 已知，fee + amount 待净值确认（`amount = shares × nav - fee`）
- `effectiveNavDate`: 15:00 前用当日净值，15:00 后用次日净值
- `backfill_transaction_navs()`: 净值更新后自动回填缺失 nav 的交易（跳过分红）
  - T+1 交易（`is_t1=1`）用 `date+1` 查净值，普通交易用 `date`
  - `_is_t1_transaction()` 检测 `tx.is_t1` 字段，`_t1_nav_date()` 返回次日日期
- `recalculate_t1_transactions()`: 一次性修复历史 T+1 交易的错误净值回填
  - 启动时自动执行（通过 `preferences` 表 key=`t1_nav_fix_done` 标记完成）
  - 检测条件：`is_t1=1` + nav 来自交易当日（错误）→ 用次日净值重算
  - 返回修复详情列表（tx_id/fund_code/old_nav/new_nav/old_shares/new_shares）
  - 修复结果写入 `audit_log`（action=`t1_nav_fix`，detail 含修复列表）+ stdout 打印

---

## 五、后端关键模块

### api.py — FastAPI 路由

- 版本: `FastAPI(title="ZFundPilot API", version="0.16.0")`
- 认证: HMAC 签名 token 认证，`auth_middleware` 拦截 `/api/*`（`/api/auth/login` 和 `/api/auth/status` 除外）。登录速率限制（5 次失败/5 分钟 → 锁定 15 分钟），密码使用 bcrypt 哈希（兼容旧 SHA-256，登录后自动升级）
- 审计日志: `audit_log` 表记录敏感操作（登录/改密/增删改交易/CSV 导入/AI 配置/定时任务/T+1 修复），`GET /api/audit` 查看最近 100 条，前端 detail 可展开查看格式化 JSON
- 启动: `@app.on_event("startup")` → `db.init_db()` + T+1 历史修复（一次性）+ `scheduler.init_scheduler()`
- 关闭: `@app.on_event("shutdown")` → `scheduler.shutdown_scheduler()`
- 静态文件: 生产模式挂载 `frontend/dist/` 到 `/`
- i18n 序列化: `/api/risk` flags 和 `/api/rebalance` advice 输出 `code`+`params`，前端 `backendLabels.ts` 按 code 翻译
- 自选列表: `POST/GET/DELETE /api/watchlist`，加入时自动获取基金 meta 并 upsert 到 `funds` 表
- 数据备份: `GET /api/export/zip`，ZIP 含 5 个 CSV（交易/基金/自选/定投/偏好），净值历史不含

### config.py — 全局配置

- 路径: `ZFUNDPILOT_HOME` 环境变量 → 项目根 → `data/` 目录
- 认证: `auth.json` 存储 `{username, password_hash, secret}`；`ZFUNDPILOT_USERNAME`/`ZFUNDPILOT_PASSWORD` 仅首次迁移；密码哈希为 bcrypt（兼容旧 SHA-256）；`ZFUNDPILOT_TRUSTED_PROXIES` 控制代理信任网段
- AI: `ai_config.json` 存储 `{base_url, api_key, model, web_search}`，其中 `api_key` 加密存储（见 `crypto.py`）
- 定时: `ZFUNDPILOT_NAV_CRON` 环境变量（默认 `0 21 * * 1-5`）

### crypto.py — 敏感字段加密

- Fernet 对称加密（AES-128-CBC + HMAC-SHA256），用于配置文件中敏感字段（如 AI API key）的加密存储
- 主密钥独立存于 `data/secret.key`（首启自动生成，32 字节随机，文件权限 0o600），与 `auth.json` 的 `AUTH_SECRET` 解耦
- 加密格式: `enc:<base64-token>`，无前缀的旧版明文自动兼容（加载时原样返回，下次保存时自动加密）
- `config._load_ai_config()` / `_save_ai_config()` 自动调用 `crypto.decrypt()` / `crypto.encrypt()`，运行时内存中 `AI_API_KEY` 为明文

### backtest.py — 定投策略回测

- `run_dca_backtest(fund_codes, start, end, amount, cadence, include_lumpsum)`: 对每只基金模拟定投 + 一次性投入
- 定投频率：月（每月1号）/ 双周（每14天）/ 周（每7天），扣款日遇非交易日跳到下一个有净值的交易日
- 计入申购费（`fetch_fund.calc_purchase_fee`）和赎回费（FIFO 按持有期匹配费率档）
- 指标：XIRR 年化（二分法）、最大回撤（复用 `risk.calculate_max_drawdown`）、夏普比率（无风险利率 3%）
- 净值数据不足时自动调 `fetch_fund.update_fund_nav` 拉取
- `BacktestResult` dataclass 含曲线（`curve`）和每期明细（`periods_detail`）

### auto_invest.py — 定投计划自动执行

- 数据库 `auto_invest_plans` 表存储定投计划（基金/金额/频率/定投日/启用状态/下次执行日）
- 4 种频率：`daily`（每个交易日）/ `week`（每周）/ `biweek`（每双周）/ `month`（每月）
- `calculate_next_run(plan)`: 根据频率计算下次执行日，遇非交易日顺延到最近的交易日（有净值数据时用净值数据推断；将来日期无净值数据时至少跳过周末）。`from_date` 缺省时取 `max(next_run, today)`，跳过停机期间错过的期数
- `execute_plan(plan, manual)`: 创建一笔买入交易（`nav=NULL`，等回填），自动通过 `fetch_fund.calc_purchase_fee` 计算手续费，更新 `last_run`/`last_tx_id`。手动执行（`manual=True`）不更新 `next_run`。15:00 前不加 T+1 标记（用当天净值），15:00 后加 `T+1确认` 标记（用次日净值）
- `run_all_due()`: 被 `scheduler.py` 每天 09:00 调用，检查所有 `enabled=1` 且 `next_run <= today` 的计划，逐个执行
- API: 6 个端点 `POST/GET/PUT/DELETE /api/auto-invest/plans` + `/toggle` + `/execute`

### fetch_fund.py — 净值获取

- `fetch_nav_history(fund_code)`: AkShare 优先（`ak.fund_open_fund_info_em`），天天基金 `pingzhongdata` fallback
- `update_fund_nav(fund_code)`: 获取 + 写入 DB
- `update_all_holdings_nav(codes, progress)`: 批量更新，0.3s 间隔限流
- `fetch_fund_meta(fund_code)`: 获取基金名称/类型/板块
- `fetch_fund_holdings(fund_code)`: 重仓股 + 资产配置（AkShare `fund_portfolio_hold_em`，1h 缓存，取最新季度前 10）
- `fetch_fund_ranking(fund_code)`: 同类排名百分位走势（AkShare `fund_open_fund_info_em(indicator="同类排名百分比")`，1h 缓存）
- `fetch_fund_profile(fund_code)`: 基金档案（天天基金 `pingzhongdata` 的 `Data_currentFundManager` + `Data_fluctuationScale`，单请求，1h 缓存）
- 缓存均带 `clear_*_cache()` 清空函数；费率 `fetch_fund_fee_rates` 另有 HTML 解析（`fundf10.eastmoney.com/jjfl_<code>.html`）

### fund_filter.py — 基金筛选

- `load_fund_universe()`: 天天基金 `fundcode_search.js` 全市场基金池（24h 本地缓存），自动分类类型/板块
- `filter_funds(types, sectors, keyword, limit, offset, with_metrics)`: 按条件筛选
- `with_metrics=True` 时 `_enrich_with_metrics()` 用 `_EXECUTOR`（6 线程池）对 Top 30 并发补充：`_enrich_one()` 复用 `compare.py` 的 `_get_cached_nav()`/`_get_fund_archive()`/`_calculate_period_return()`/`_calculate_max_drawdown()`/`_calculate_volatility()`/`_calculate_sharpe()`
- `FundFilterItem`: `code`/`name`/`type`/`sector`（基础）+ `scale`/`manager`/`inception_date`（档案）+ `returns`/`risk`（指标）

### fetch_estimate.py — 实时估值

- 主数据源：AkShare `fund_value_estimation_em()`（覆盖全市场基金），天天基金 fundgz API 已废弃
- 指数估值兜底：东财估值不可用时，对指数型基金用跟踪指数/ETF 实时涨跌估算
  - `fetch_index_quotes(keywords)`: 批量获取指数/ETF 实时涨跌幅，两级匹配（指数实时 → ETF 实时，仅按需）
  - `estimate_from_index(fund_code, tracking_index, prev_nav, prev_date)`: 用指数涨跌构建 FundEstimate
  - 数据源：`stock_zh_index_spot_sina`（A 股 562）+ `index_global_spot_em`（全球 56）+ `stock_hk_index_spot_em`（港股 359）+ `fund_etf_spot_em`（ETF 1566，行业/主题代理）
  - 指数缓存 30s，ETF 缓存 60s（拉取较慢）
- `fetch_estimate(fund_code)`: 获取单只基金估值（`gsz`/`gszzl`/`gztime`），30s 内存缓存
- `fetch_estimates(fund_codes)`: 批量获取，30s 批量缓存
- `stale-if-error`: API 失败时优先返回过期缓存而非空列表，避免短暂网络波动导致前端显示断档
- `gztime` 从估值列名提取日期（如 `2024-07-30-估算数据-估算值` → `2024-07-30 15:00`），而非用 `datetime.now()`，避免跨日数据时间戳错误
- 估算失效检测：`jzrq == gztime[:10]` 时标记 `ok=False`（真实净值已公布）
- API: `GET /api/estimate`（批量 + 组合汇总，含指数兜底）+ `GET /api/funds/{code}/estimate`（单只，含指数兜底）

### analysis.py — 收益计算

- `calculate_positions()`: 从 transactions 汇总持仓（待确认买入金额计入 `pending_buy_cost`，不参与市值/盈亏/收益率计算）
- `calculate_summary()`: 组合层面汇总（`total_cost` 不含 `pending_buy_cost`）
- `build_portfolio_curve()`: 组合收益曲线（待确认买入用 `pending_value_delta` 占位市值，避免虚假亏损）
- `build_channel_daily_pnl()`: 按渠道拆分的每日收益（堆叠柱状图）
- 内存 TTL 缓存（60s），8 个写入端点自动清除缓存

### scheduler.py — 定时任务

- APScheduler `BackgroundScheduler`，时区来自 `config.TIMEZONE`（环境变量 `ZFUNDPILOT_TIMEZONE`，默认 `Asia/Shanghai`）
- 默认 cron: `0 21 * * 1-5`（工作日 21:00）
- `max_instances=1` + `coalesce=True` + `misfire_grace_time=3600`
- 开关状态存 `preferences` 表 key=`nav_auto_update`，默认启用
- `_bootstrap_check`: 启动时检测今日 cron 是否已过，若已过则立即补跑
- `auto_invest` 任务：每天 09:00 检查到期定投计划并执行（`auto_invest.run_all_due`），写审计日志
- `_run_auto_invest` 加 `threading.Lock` 防止 bootstrap/cron/API 三入口并发重复执行
- `_bootstrap_auto_invest`: 启动时若已过 09:00 且今日未执行过，立即补跑
- `_convert_dow()`: 标准 cron day_of_week 数值（0=周日, 1=周一）→ APScheduler 编号（0=周一, 6=周日），`re.sub(r'(?<!/)\d+', lambda m: str((int(m.group(0))-1)%7), dow)`。`(?<!/)` 跳过 `/` 后的步进值（如 `*/2` 中的 `2` 不被转换）。只在 day_of_week 为纯数字（无字母缩写）时执行转换
- `config.TIMEZONE`: 所有 `datetime.now()` 调用使用此时区，不依赖系统时区
- API: `GET /api/scheduler/status` + `PUT /api/scheduler/toggle` + `PUT /api/scheduler/cron`

---

## 六、前端关键约定

### 路由（App.tsx）

- `/` → `<Home />`（独立全屏页，不在 Layout 内，无侧边栏）
- `/overview`、`/transactions`、`/nav`、`/positions`、`/returns`、`/risk`、`/compare`、`/screener`、`/watchlist`、`/backtest`、`/ai`、`/settings` → 在 `<Layout />` 内（含侧边栏）

### 首页（Home.tsx）

- Brutalist 战术终端风格：深色 `#0A0A0A` 底 + `#EAEAEA` 文字 + `#FF2A2A` 红色强调
- CRT 扫描线 overlay、磷光 text-shadow、monospace 主导
- 战术瞄准镜 SVG logo（四角括号 + 十字准星 + 中心圆 + Z 路径）
- 中英双语切换（右上角按钮，localStorage 持久化 `zfund_lang`）
- 实时时钟（每秒更新）
- 系统状态条（市场开/闭、NAV 更新日期、仓位集中度）
- 无 header，品牌信息在底部 footer

### 涨跌颜色主题

- CSS 变量在 `index.css` 定义 11 级 gain/loss 色阶
- `.color-theme-cn` class 切换：国际（绿涨红跌）/ 国内 A 股（红涨绿跌）
- `tailwind.config.js` 中 gain/loss 用 `var(--gain-*)` / `var(--loss-*)`
- `lib/colorTheme.ts` 管理 localStorage + 服务端同步
- 在 `Layout.tsx` 和 `Home.tsx` 的 `<html>` class 上应用

### Recharts 约定

- 混合 Area + Line 时用 `ComposedChart`（不是 `AreaChart`，否则 Line 不显示在 legend 中）
- 图例可点击切换显示/隐藏

### API 调用

- `api/client.ts`: 所有 API 调用集中在此，自动带 `Authorization: Bearer <token>`
- `api/types.ts`: 所有 TypeScript 类型定义
- `lib/useApi.ts`: `useApi(fetcher, deps)` 返回 `{ data, loading, error, reload }`

---

## 七、环境变量

| 变量 | 默认值 | 说明 |
|---|---|---|---|
| `ZFUNDPILOT_HOME` | 项目根 | 数据目录位置 |
| `ZFUNDPILOT_USERNAME` | `admin` | 仅首次启动初始化用户名 |
| `ZFUNDPILOT_PASSWORD` | 空 | 仅首次启动初始化密码（留空则无认证），密码哈希用 bcrypt |
| `ZFUNDPILOT_SECRET` | 自动生成 | 仅首次启动初始化 token 签名密钥 |
| `ZFUNDPILOT_NAV_CRON` | `0 21 * * 1-5` | 净值定时更新 cron 表达式 |
| `ZFUNDPILOT_TIMEZONE` | `Asia/Shanghai` | 系统时区（IANA 名称），影响定时任务、交易日期、日志时间戳 |
| `ZFUNDPILOT_TRUSTED_PROXIES` | 空 | 信任代理网段（CIDR 逗号分隔），仅在反代后配置 |

---

## 八、开发与部署

### 本地开发

```bash
# 后端
PYTHONPATH=src uvicorn zfundpilot.api:app --reload --port 8000

# 前端
cd frontend && npm run dev   # Vite :5173，代理 /api/* 到 :8000
```

### Docker 部署

```bash
docker compose up -d --build   # 构建并启动
# 或使用部署脚本
./update.sh                    # git pull + 智能构建
```

- `Dockerfile`: 多阶段（node 22 构建前端 → python 3.11-slim 运行），内置 `TZ=Asia/Shanghai` + `tzdata`
- `docker-compose.yml`: 单服务 + `data/` 卷 + `restart: always`
- 端口映射通过 gitignored `docker-compose.override.yml` 设置

### 类型检查

```bash
cd frontend && npx tsc --noEmit   # 前端类型检查
```

---

## 九、Git 规范

### Commit 规范

- **Commit message 用中文**
- 前缀: `feat:` / `fix:` / `docs:` / `perf:` / `chore:`
- 格式: `feat: 简短描述`，空行后可选详细说明
- **禁止 amend 已推送的 commit**：发现遗漏时新建 fix commit，不要 `git commit --amend` 后 force push。amend 会改写历史，导致服务器 `git pull` 分叉失败
- 示例:
  ```
  feat: 添加净值定时自动更新功能

  - 新建 scheduler.py，使用 APScheduler BackgroundScheduler
  - 默认工作日 21:00 自动拉取所有持仓基金净值
  ```

### 文档更新规则

每次功能变更时，**同步更新**以下文档：

| 文档 | 更新时机 |
|---|---|
| `CHANGELOG.md` | 每次功能新增/修复/变更时，在当前版本段落添加条目 |
| `README.md` | 新功能、新环境变量、项目结构变化时 |
| `README_EN.md` | 与 README.md 同步更新英文版 |
| `DEPLOY.md` | 部署流程、环境变量、Docker 配置变化时 |
| `.env.example` | 新增环境变量时 |

### CHANGELOG 格式

参考 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)：

```markdown
## [版本号] - YYYY-MM-DD

### Added
- 新增功能描述

### Changed
- 变更内容

### Fixed
- 修复内容

### Performance
- 性能优化
```

### Release 流程

1. 确认所有改动已提交并推送
2. 更新版本号（共 5 处）:
   - `src/zfundpilot/__init__.py` → `__version__ = "x.y.z"`
   - `src/zfundpilot/api.py` → `FastAPI(version="x.y.z")`
   - `pyproject.toml` → `version = "x.y.z"`
   - `frontend/package.json` → `"version": "x.y.z"`（同步更新 `frontend/package-lock.json`）
   - `docs/CONTEXT.md` → 主标题版本 + 项目树注释 + api.py 描述 + 工作状态区
3. 更新 `CHANGELOG.md`（`[Unreleased]` → `[x.y.z] - 日期`）
4. 更新 `README.md` / `README_EN.md`（功能列表、项目结构等）
5. 运行完整测试套件 + TypeScript 检查 + Vite build
6. 提交版本 bump 并推送
7. `git tag vx.y.z && git push origin vx.y.z`
8. GitHub Release:
   - 标题: `vx.y.z` 或带描述性标题（如 `v0.5.0 — 首页改版 + 定时更新`）
   - 正文: 从 CHANGELOG.md 复制对应版本段落
   - 命令: `gh release create vx.y.z --title "vx.y.z — 简短描述" --notes "$(cat CHANGELOG.md 中对应段落)"`
9. 积累到一定阶段（多个功能/修复）再发布新 release，不必每次提交都发

> **重要**：未经用户明确允许，不要主动创建 GitHub Release 或打 git tag。版本号 bump 可以随功能提交一起做，但 `git tag` + `gh release create` 必须等用户指示。

---

## 十、关键设计原则

### 不做

- 自动交易 / AI 预测涨跌 / 短期买卖信号

### 只做

- 数据驱动分析 / 风险管理 / 组合优化建议 / 长期结构判断

---

## 十一、数据源

- **AkShare** (`ak.fund_open_fund_info_em`): 主数据源，基金净值历史
- **AkShare** (`ak.fund_value_estimation_em`): 实时估值（覆盖全市场基金，交易日实时估算涨跌幅，目前不可用）
- **AkShare** (`ak.stock_zh_index_spot_sina` / `ak.index_global_spot_em` / `ak.stock_hk_index_spot_em`): 指数实时行情（A 股/全球/港股），指数基金估值兜底
- **AkShare** (`ak.fund_etf_spot_em`): ETF 实时行情（1566 只），行业/主题指数基金估值代理
- **天天基金** (`fund.eastmoney.com/pingzhongdata`): fallback 数据源 + 基金档案（经理/规模）
- **天天基金** (`fund.eastmoney.com/{code}.html`): 风险等级抓取（HTML 解析）
- **天天基金** (`fundf10.eastmoney.com`): 费率抓取（HTML 解析）
- 均为东方财富旗下，无需额外 API key

---

## 十二、当前工作状态

### Unreleased

- feat: 分红自动检测功能（Phase 1）——按基金并行调 `ak.fund_open_fund_info_em(indicator="分红送配详情")`，检测持仓基金的未记录分红事件，弹窗预填确认入账
- feat: `funds` 表新增 `dividend_method` 字段（`cash`/`reinvest`，默认 `cash`），FundDetail 页加分红方式选择器
- feat: 新增 API `GET /api/dividends/check`（检测未记录分红）、`PUT /api/funds/{code}/dividend-method`（设置分红方式）
- feat: 分红操作审计日志（`dividend_check` / `update_dividend_method`）
- fix: AkShare 1.18.79 → 1.18.82（空响应不再抛异常）
- feat: 分红定时检测（Phase 2）——每天 09:30 自动扫描，新发现存入 `dividend_alerts` 表（pending/confirmed/ignored），启动时 bootstrap 补执行
- feat: `dividend_alerts` 表 + CRUD，去重查所有状态（ignored 后不再重复提醒）
- feat: 新增 API `GET /api/dividends/alerts`、`GET /api/dividends/alerts/count`、`PUT /api/dividends/alerts/{id}`、`POST /api/dividends/scan`、`PUT /api/dividends/auto-check`
- feat: 导航栏 Transactions 项红点提醒（60s 轮询 pending count）+ Settings 分红自动检测开关卡片
- feat: DividendCheckDialog 改为 alerts 模式（pending 列表 + 重新扫描 + 忽略 + 确认带 alert_id 跳转 + 保存后回调标记 confirmed）
- feat: 分红扫描/提醒处理审计日志（`dividend_scan` / `dividend_alert_update` / `dividend_auto_check_toggle`）
- 完整规划见 `tmp/dividend-auto-detect-plan.md`，Phase 1-2 已完成

### v0.15.1 - 2026-08-11

> 已部署至服务器（2026-08-11，`./update.sh` + Settings「重置板块」回填 tracking_index）

- fix: `_index_fallback` 移除 `est.dwjz > 0` 跳过条件，修复指数兜底不触发
- fix: `pyproject.toml` 补全 `python-multipart` 运行时依赖声明，修复 CI 测试收集失败
- ci: workflow 加固（3 版本并行 + fail-fast: false + concurrency + timeout + working-directory）
- docs: 新增 `NOTICE.md` 数据来源与合规声明（中英双语）
- docs: README 截图区新增交易管理页面（深/浅双主题合并图）
- fix: Settings 偏好设置 tab 布局优化（max-w-4xl + 渠道行/关键词行移动端响应式 + 触摸目标增大）
- fix: TransactionDetailDialog 移动端适配（详情网格移动端单列 + 操作栏 flex-wrap）

### v0.15.0 - 2026-08-06

- 指数基金跟踪指数估值：`funds` 表加 `tracking_index` 列，`fetch_fund.py` 按基金名称推断跟踪指数关键词
- `fetch_estimate.py` 新增 `fetch_index_quotes()` + `estimate_from_index()`：东财估值不可用时用指数/ETF 实时涨跌估算
- 数据源：`stock_zh_index_spot_sina` + `index_global_spot_em` + `stock_hk_index_spot_em` + `fund_etf_spot_em`（ETF 代理行业指数）
- 两级匹配：先查指数实时（~5s），未匹配再查 ETF（~17s，仅按需）
- 前端展示：FundDetail badge + Positions/Watchlist 板块列小字
- 回填：`reset_sectors` 端点同时重推 tracking_index，Settings 页面点「重置板块」一次性回填
- 自选关注列表分组功能：`watchlist` 表加 `group_name` 列，支持分组管理自选基金
- AI 助手流式回答跨页面持久化：`ChatContext` 方案，`ChatProvider` 挂在 `<Routes>` 外层，切换页面不丢失对话
- 修复审计日志 4 条操作缺失 i18n 标签、`get_fund_estimate` 未检查当日净值已入库、FundCompare 删除重复 FilterSection 等

### v0.14.0 - 2026-08-04

- 基金筛选器独立页面 `/screener`：全市场筛选 + Top 30 指标增强（1年收益/回撤/波动率/规模/经理），列头可排序，一键加入对比或自选
- `fund_filter.py` 激活死代码 `_EXECUTOR`/`_MAX_METRICS_FUNDS`，`_enrich_with_metrics()` 复用 `compare.py` 指标计算
- 自选关注列表 `/watchlist`：`watchlist` 表 + 3 个 API 端点，支持追踪未持有基金
- 全量数据备份导出 `GET /api/export/zip`：ZIP 含 5 个 CSV（交易/基金/自选/定投/偏好），Settings 页面加备份按钮
- 基金筛选器 UX 改进：筛选芯片自动搜索 + 代码搜索忽略类型/板块 + 两阶段加载指标（先基础后指标，非阻塞）
- 修复 /api/risk 和 /api/rebalance 序列化丢弃 `code`+`params`（v0.12.1 引入 i18n code 体系时 API 层漏传）
- Risk.tsx 再平衡建议因 loading 条件 bug 从未显示，改为四态分支

### v0.13.1 - 2026-08-03

- 基金详情顶栏新增风险等级色点 Badge，后端 `fund.eastmoney.com/{code}.html` 抓取风险等级（低风险~高风险）
- 前端 `RISK_LEVELS`/`RISK_LEVEL_DOT`/`FUND_TYPE_DOT`/`translateRiskLevel()` 工具函数
- 基金详情顶栏元数据行重构：基金代码 · 类型色点 Badge · 板块 Badge · 渠道色点 Badge · 风险色点 Badge
- 侧边栏交换「交易管理」与「持仓明细」顺序
- 移除未使用的 `profileRiskLevel` i18n key

### v0.13.0 - 2026-08-02

- 基金详情净值走势 tooltip 新增当期收益率（`pnlReturn`，`当日收益 +¥123.45 (+1.23%)`）
- 交易详情弹窗修复：头部栏去掉重复渠道、网格去掉重复操作类型、新增 `is_t1` 确认时间行（复用 `aiChat.afterClose`/`beforeClose`）
- 基金详情新增持仓卡片（Phase 1）：资产配置饼图 + 前十大重仓股表格（AkShare `fund_portfolio_hold_em`），重仓股市值 `持仓市值`（万元）前端 `/10000` 显示 `亿`
- 基金详情新增同类排名走势卡片（Phase 2）：AkShare `fund_open_fund_info_em(indicator="同类排名百分比")`，排名百分位（越低越好）折线图 Y 轴反转
- 基金详情新增基金档案信息栏（Phase 3）：天天基金 `pingzhongdata`（`Data_currentFundManager` 张坤/从业13年又310天/任期收益50.94% + `Data_fluctuationScale` 规模204.16亿），单请求比 AkShare `fund_manager_em` 全表扫描（~16s）更快更准
- 新增 API：`GET /api/funds/{code}/ranking`、`GET /api/funds/{code}/profile`
- 新增测试：`tests/test_fetch_fund.py`（11 个用例），总测试数 92 → 103

> 完整历史版本记录见 `CHANGELOG.md`。

### 待办

- 更多基金类型识别和板块分类
