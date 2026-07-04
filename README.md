# ZFundPilot

个人基金分析与风险管理系统。本地运行，自动更新净值、计算收益与风险、给出组合结构优化建议。

> ⚠️ 仅用于数据分析与风险管理，不做自动交易、不预测涨跌、不构成任何投资建议。

## 功能

- **交易流水管理**：记录每一笔买入/卖出（定投、加仓、减仓、赎回），表单录入 + CSV 批量导入/导出
- **多渠道支持**：支付宝、理财通、天天基金等，同一基金不同渠道分开计算成本
- **持仓自动汇总**：按「基金 + 渠道」用移动加权平均成本法汇总，卖出时结转已实现收益
- **净值更新**：AkShare 优先，天天基金兜底，输入代码自动获取名称/类型/板块
- **收益分析**：浮动盈亏、已实现盈亏、组合收益曲线、收益率排序
- **风险分析**：最大回撤、年化波动率、集中度（HHI）、结构占比、风险提示
- **结构建议**：基于组合结构给出再平衡建议（非交易指令）
- **AI 投顾对话**：配置 OpenAI 兼容 API 后，AI 自动联网搜索最新资讯 + 结合持仓数据给出调仓建议（支持智谱 / Kimi / 通义千问 / DeepSeek）
- **净值走势图标记**：在净值曲线上自动标记买入/卖出点位，悬停显示交易明细
- **移动端适配**：抽屉式侧边栏导航、响应式网格布局
- **密码认证**：HMAC 签名 token，支持设置页在线修改密码（SHA-256 哈希存储）

## 环境要求

- Python 3.10+

## 安装

```bash
pip install -e .
```

开发模式（含测试与代码检查）：

```bash
pip install -e ".[dev]"
```

若 akshare 安装失败，可用国内镜像：

```bash
pip install akshare -i http://mirrors.aliyun.com/pypi/simple/ --trusted-host=mirrors.aliyun.com --upgrade
```

> macOS 上如遇 `SSL: CERTIFICATE_VERIFY_FAILED`，运行一次
> `/Applications/Python\ 3.x/Install\ Certificates.command` 即可修复。

## 部署

> 详细部署方式（开发/生产/Docker）见 [DEPLOY.md](DEPLOY.md)

### 方式一：React 前端 + FastAPI 后端（推荐）

```bash
# 后端 API（终端 1）
uvicorn zfundpilot.api:app --reload --port 8000

# 前端开发服务器（终端 2）
cd frontend && npm install && npm run dev
```

浏览器打开 http://localhost:5173

### 方式二：生产模式（单进程，前端构建后由后端统一服务）

```bash
cd frontend && npm install && npm run build && cd ..
uvicorn zfundpilot.api:app --host 0.0.0.0 --port 8000
```

浏览器打开 http://localhost:8000

### 方式三：Streamlit（旧版界面，仍可用）

```bash
streamlit run app.py
```

浏览器打开 http://localhost:8501

## 环境变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `ZFUNDPILOT_PASSWORD` | 空 | **仅首次启动**时用于初始化密码哈希，之后密码存在 `data/auth.json`，可通过设置页修改 |
| `ZFUNDPILOT_SECRET` | 自动生成 | **仅首次启动**时用于初始化 token 签名密钥，之后存于 `data/auth.json` |
| `ZFUNDPILOT_HOME` | 项目根 | 数据目录（`data/`）所在位置 |

## 使用流程

1. **交易录入 → 单笔录入**：输入基金代码点「获取基金信息」自动补全，选择买入/卖出、渠道，
   填金额/份额/净值（任意两项即可，自动补全第三项）后保存
   - 或 **CSV 导入/导出**：下载模板，填好流水后上传，可自动补全基金信息
2. **净值更新**：点「更新全部基金净值」拉取历史净值
3. **持仓明细**：查看按「基金+渠道」拆分的持仓，以及跨渠道合并视图
4. **收益分析 / 风险与建议**：查看收益曲线、浮动/已实现盈亏、风险指标与结构建议

> 金额、份额、成交净值三者填任意两项即可，系统自动补全。

## CSV 列说明（交易流水）

| 列名 | 说明 | 必填 |
|------|------|------|
| fund_code | 基金代码 | ✅ |
| action | 操作：买入/卖出（也识别 buy/sell/申购/赎回/定投） | ✅ |
| date | 成交日期 YYYY-MM-DD | ✅ |
| amount | 成交金额 | 三选二 |
| shares | 成交份额 | 三选二 |
| nav | 成交净值 | 三选二 |
| fee | 手续费 | |
| channel | 渠道：支付宝/理财通/天天基金等 | |
| note | 备注 | |

`amount` / `shares` / `nav` 填任意两项即可，导入时自动补全。支持中文表头（如「基金代码」「操作」「渠道」）。

## 项目结构

```text
ZFundPilot/
├── app.py                # Streamlit 旧版启动入口（仍可用）
├── pyproject.toml        # 打包配置、依赖、Ruff/Pytest 配置
├── Dockerfile            # 多阶段构建 Docker 镜像
├── docker-compose.yml    # Docker 部署（端口由 override 指定）
├── src/zfundpilot/       # Python 包
│   ├── __init__.py
│   ├── config.py         # 全局配置、渠道、风险阈值、认证/AI 配置存储
│   ├── models.py         # 数据结构（Fund / Transaction / Position）
│   ├── db.py             # SQLite 数据库操作
│   ├── fetch_fund.py     # 净值获取 + 名称/类型/板块自动识别
│   ├── analysis.py       # 交易流水汇总、收益计算、组合曲线
│   ├── risk.py           # 风险分析（回撤/波动率/集中度/结构占比）
│   ├── rebalance.py      # 结构优化建议
│   ├── data_io.py        # 交易流水 CSV 导入/导出
│   ├── api.py            # FastAPI REST API（28 路由 + 认证中间件）
│   └── ai.py             # AI 投顾对话（持仓上下文 + 联网搜索 + LLM 流式调用）
├── tests/                # Pytest 测试套件（25 测试）
├── data/
│   ├── fund.db           # SQLite 数据库（自动生成）
│   ├── auth.json         # 密码哈希 / token 密钥（自动生成）
│   ├── ai_config.json    # AI 模型配置（自动生成）
│   └── sector_map.json   # 基金代码→板块映射（自动维护）
├── frontend/             # React + Vite + TypeScript + Tailwind + shadcn/ui
│   ├── src/
│   │   ├── pages/        # 9 个页面（Overview / Transactions / Positions / FundDetail / NavUpdate / Returns / Risk / Settings / Login）
│   │   ├── components/   # Layout + shadcn/ui 组件
│   │   ├── api/          # 类型化 API client + streamChat (SSE)
│   │   └── lib/          # 工具函数（format / auth / channels / useApi）
│   └── dist/             # 构建产物（生产模式）
└── .env.example           # 环境变量模板
```

## 数据模型

- **funds**：基金基础信息（代码/名称/类型/板块）
- **transactions**：交易流水（买入/卖出/金额/份额/净值/渠道）
- **nav_history**：基金净值历史
- 持仓不单独存表，由交易流水按「基金 + 渠道」实时汇总计算（移动加权平均成本法）
- 旧版 holdings 表会在首次启动时自动迁移为交易流水

## 风险阈值

默认阈值定义在 `config.py` 的 `RiskThresholds`，可按需调整：

| 指标 | 默认阈值 |
|------|---------|
| 单基金占比偏高 / 过高 | 20% / 40% |
| 债券最低占比 | 10% |
| QDII 海外暴露 | 30% |
| 权益类偏重 | 70% |
| 高风险回撤 | -15% |
| 高波动率 | 25% |
