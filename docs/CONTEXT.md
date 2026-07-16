# ZFundPilot 项目上下文（供 AI Agent 使用）

> 每次新对话开始时，Agent 应先读取此文件了解项目全貌。

---

## 一、项目概述

**ZFundPilot** — 个人基金分析与风险管理系统。

Web 应用，支持本地开发和服务器部署（Docker）。核心功能：管理基金持仓 → 自动更新净值 → 计算收益与风险 → 提供结构优化建议。不是交易系统，不做自动买卖，不连接券商。

> ⚠️ Agent 在本地开发时不要正式运行或测试，仅做代码编写和类型检查。服务器端部署通过 Docker 完成。

- **仓库**: `git@github.com:Euzohn/ZFundPilot.git`，分支 `main`
- **版本**: `0.5.1`（git tag `v0.5.1`）
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
│   ├── __init__.py          # __version__ = "0.5.1"
│   ├── api.py               # FastAPI 路由（所有 /api/* 端点）
│   ├── config.py            # 全局配置、环境变量、认证管理
│   ├── db.py                # SQLite 操作层（连接管理 + CRUD + 迁移）
│   ├── models.py            # 数据结构（Fund/Transaction/Position/PortfolioSummary）
│   ├── fetch_fund.py        # 基金净值获取（AkShare 优先，天天基金 fallback）
│   ├── analysis.py          # 收益计算（持仓汇总 + 收益曲线 + 缓存）
│   ├── risk.py              # 风险分析（回撤/波动率/集中度/HHI）
│   ├── rebalance.py         # 再平衡建议
│   ├── scheduler.py         # APScheduler 定时净值更新
│   ├── ai.py                # AI 投顾（OpenAI 兼容 API + 联网搜索）
│   └── data_io.py           # CSV 导入/导出
├── frontend/src/            # React 前端
│   ├── App.tsx              # 路由（/ → Home 独立页，其余在 Layout 内）
│   ├── pages/               # 10 个页面
│   │   ├── Home.tsx         # 首页（brutalist 战术终端风格，中英双语切换）
│   │   ├── Overview.tsx     # 组合总览
│   │   ├── Transactions.tsx # 交易管理（录入/流水/CSV）
│   │   ├── NavUpdate.tsx    # 净值更新
│   │   ├── Positions.tsx    # 持仓明细
│   │   ├── Returns.tsx      # 收益分析（曲线/排名/日历）
│   │   ├── Risk.tsx         # 风险评估
│   │   ├── AIChat.tsx       # AI 投顾对话
│   │   ├── FundDetail.tsx   # 基金详情（净值走势 + 交易标记）
│   │   ├── Settings.tsx     # 设置（账户/AI/偏好）
│   │   └── Login.tsx        # 登录
│   ├── components/          # Layout + Logo 系列 + PnLCalendar + UI 组件
│   ├── api/                 # client.ts + types.ts
│   └── lib/                 # auth/channels/channelColors/colorTheme/format/useApi
├── data/                    # SQLite 数据库 + auth.json + ai_config.json（gitignore）
├── Dockerfile               # 多阶段构建
├── docker-compose.yml       # 单服务 + data 卷
├── update.sh                # 部署脚本（git pull + docker compose up -d --build）
├── pyproject.toml           # Python 依赖 + ruff/pytest 配置
├── CHANGELOG.md             # 版本变更记录
├── README.md / README_EN.md # 项目说明（中/英）
├── DEPLOY.md                # 部署文档
├── .env.example             # 环境变量示例
└── CONTEXT.md              # 本文件（不追踪）
```

---

## 四、数据模型

### 数据库表（SQLite）

| 表 | 说明 |
|---|---|
| `funds` | 基金基础信息（code/name/type/sector） |
| `transactions` | 交易流水（buy/sell/dividend/reinvest） |
| `nav_history` | 基金净值历史（fund_code + date + nav） |
| `portfolio_snapshots` | 组合每日快照 |
| `ai_usage` | AI token 用量记录 |
| `preferences` | 偏好设置 key-value（channels/channel_colors/color_theme/nav_auto_update/type_keywords_custom/sector_keywords_custom） |

### 核心模型（models.py）

- **Transaction**: `fund_code`/`action`/`date`/`amount`/`shares`/`nav`/`fee`/`channel`/`note`
  - `normalize()`: amount/shares/nav 给出任意两个补全第三个，按 action 处理手续费
  - **P&L 约定**: `amount` **含手续费**（买入 = 付的总额，卖出 = 收的净额）
  - 买入: `amount = shares × nav + fee`
  - 卖出: `amount = shares × nav - fee`
  - 分红/再投资: 无手续费
- **Position**: 由 transactions 汇总计算（移动加权平均成本法）
  - `is_open`: `held_shares > 1e-6 or total_cost > 1e-6`（含 T+1 待确认）
- **PortfolioSummary**: 组合层面汇总（含 daily/week/month/year P&L）

### T+1 交易处理

- **买入 T+1**: amount 已知，shares 待净值确认（`shares = (amount - fee) / nav`）
- **卖出 T+1**: shares 已知，fee + amount 待净值确认（`amount = shares × nav - fee`）
- `effectiveNavDate`: 15:00 前用当日净值，15:00 后用次日净值
- `_backfill_transaction_navs()`: 净值更新后自动回填缺失 nav 的交易（跳过分红）

---

## 五、后端关键模块

### api.py — FastAPI 路由

- 版本: `FastAPI(title="ZFundPilot API", version="0.5.1")`
- 认证: HMAC 签名 token，`auth_middleware` 拦截 `/api/*`（`/api/auth/login` 和 `/api/auth/status` 除外）
- 启动: `@app.on_event("startup")` → `db.init_db()` + `scheduler.init_scheduler()`
- 关闭: `@app.on_event("shutdown")` → `scheduler.shutdown_scheduler()`
- 静态文件: 生产模式挂载 `frontend/dist/` 到 `/`

### config.py — 全局配置

- 路径: `ZFUNDPILOT_HOME` 环境变量 → 项目根 → `data/` 目录
- 认证: `auth.json` 存储 `{username, password_hash, secret}`；`ZFUNDPILOT_USERNAME`/`ZFUNDPILOT_PASSWORD` 仅首次迁移
- AI: `ai_config.json` 存储 `{base_url, api_key, model, web_search}`
- 定时: `ZFUNDPILOT_NAV_CRON` 环境变量（默认 `0 21 * * 1-5`）

### fetch_fund.py — 净值获取

- `fetch_nav_history(fund_code)`: AkShare 优先（`ak.fund_open_fund_info_em`），天天基金 `pingzhongdata` fallback
- `update_fund_nav(fund_code)`: 获取 + 写入 DB
- `update_all_holdings_nav(codes, progress)`: 批量更新，0.3s 间隔限流
- `fetch_fund_meta(fund_code)`: 获取基金名称/类型/板块

### analysis.py — 收益计算

- `calculate_positions()`: 从 transactions 汇总持仓
- `calculate_summary()`: 组合层面汇总
- `calculate_curve()`: 组合收益曲线
- 内存 TTL 缓存（60s），8 个写入端点自动清除缓存

### scheduler.py — 定时任务

- APScheduler `BackgroundScheduler`，时区 `Asia/Shanghai`
- 默认 cron: `0 21 * * 1-5`（工作日 21:00）
- `max_instances=1` + `coalesce=True` + `misfire_grace_time=3600`
- 开关状态存 `preferences` 表 key=`nav_auto_update`，默认启用
- `_bootstrap_check`: 启动时检测今日 cron 是否已过，若已过则立即补跑
- `_TZ = ZoneInfo("Asia/Shanghai")`: 所有 `datetime.now(_TZ)` 时区感知，不依赖系统时区
- API: `GET /api/scheduler/status` + `PUT /api/scheduler/toggle` + `PUT /api/scheduler/cron`

---

## 六、前端关键约定

### 路由（App.tsx）

- `/` → `<Home />`（独立全屏页，不在 Layout 内，无侧边栏）
- `/overview`、`/transactions`、`/nav`、`/positions`、`/returns`、`/risk`、`/ai`、`/settings` → 在 `<Layout />` 内（含侧边栏）

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
|---|---|---|
| `ZFUNDPILOT_HOME` | 项目根 | 数据目录位置 |
| `ZFUNDPILOT_USERNAME` | `admin` | 仅首次启动初始化用户名 |
| `ZFUNDPILOT_PASSWORD` | 空 | 仅首次启动初始化密码（留空则无认证） |
| `ZFUNDPILOT_SECRET` | 自动生成 | 仅首次启动初始化 token 签名密钥 |
| `ZFUNDPILOT_NAV_CRON` | `0 21 * * 1-5` | 净值定时更新 cron 表达式 |

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
2. 更新版本号:
   - `src/zfundpilot/__init__.py` → `__version__ = "x.y.z"`
   - `src/zfundpilot/api.py` → `FastAPI(version="x.y.z")`
3. 更新 `CHANGELOG.md`（新版本段落）
4. 更新 `README.md` / `README_EN.md`（功能列表、项目结构等）
5. Git tag: `git tag vx.y.z && git push origin vx.y.z`
6. GitHub Release:
   - 标题: `vx.y.z` 或带描述性标题（如 `v0.5.0 — 首页改版 + 定时更新`）
   - 正文: 从 CHANGELOG.md 复制对应版本段落
   - 命令: `gh release create vx.y.z --title "vx.y.z — 简短描述" --notes "$(cat CHANGELOG.md 中对应段落)"`
7. 积累到一定阶段（多个功能/修复）再发布新 release，不必每次提交都发

---

## 十、关键设计原则

### 不做

- 自动交易 / AI 预测涨跌 / 短期买卖信号

### 只做

- 数据驱动分析 / 风险管理 / 组合优化建议 / 长期结构判断

---

## 十一、数据源

- **AkShare** (`ak.fund_open_fund_info_em`): 主数据源，基金净值历史
- **天天基金** (`fund.eastmoney.com/pingzhongdata`): fallback 数据源
- **天天基金** (`fundf10.eastmoney.com`): 费率抓取（HTML 解析）
- 两者都是东方财富旗下，无需额外 API key

---

## 十二、当前工作状态

### 已完成（v0.5.1）

- 首页 brutalist 战术终端风格改版（中英双语、实时时钟、系统状态条、战术瞄准镜 logo）
- 用户名 + 密码登录系统
- 涨跌颜色主题切换（国际/国内 A 股）
- 净值定时自动更新（APScheduler，工作日 21:00，Docker 时区修复 + 时区感知 datetime）
- AI 投顾对话（多会话、token 用量、联网搜索、持仓上下文、界面重设计）
- 交易录入（手动 + AI 自然语言 + CSV 导入）
- 收益分析（曲线/排名/日历/按渠道堆叠）
- 风险评估（回撤/波动率/集中度/HHI）
- 基金详情（净值走势 + 交易标记 + 回本涨幅）
- 持仓明细（跨渠道合并 + 回本涨幅子文字）
- 渠道颜色/关键词映射/偏好设置同步
- 基础设计层升级（Card 去边框、圆角加大、hover 增强、噪点叠加）
- 侧边栏导航分组 + Overview 布局重构

### 待办

- GitHub Release for v0.5.1（需 `gh auth login`）
- 更多基金类型识别和板块分类
