# 贡献指南

感谢你对 ZFundPilot 的兴趣！欢迎提交 Issue 或 Pull Request。

## 开发环境

### 后端（FastAPI + SQLite）

```bash
git clone https://github.com/Euzohn/ZFundPilot.git
cd ZFundPilot
pip install -e ".[dev]"
```

### 前端（React + Vite + TypeScript）

```bash
cd frontend
npm install
```

### 本地启动

```bash
# 后端（端口 8000）
PYTHONPATH=src uvicorn zfundpilot.api:app --reload --port 8000

# 前端（端口 5173，代理 /api/* 到 :8000）
cd frontend && npm run dev
```

### Docker 部署

```bash
docker compose up -d --build
# 或使用部署脚本
./update.sh
```

## 代码规范

### 后端

- 使用 **Ruff** 进行代码检查与格式化：`ruff check --fix . && ruff format .`
- 测试：`pytest`
- 提交前请确保 `ruff check .` 和 `pytest` 均通过

### 前端

- 使用 **TypeScript** 严格模式，提交前执行类型检查：`cd frontend && npx tsc --noEmit`
- 组件风格：shadcn/ui + Tailwind CSS，遵循现有组件命名与目录结构
- 图表：Recharts（混合 Area + Line 时用 `ComposedChart`）

## 项目结构

```text
src/zfundpilot/          # Python 后端
├── api.py               # FastAPI 路由
├── config.py            # 全局配置
├── db.py                # SQLite 操作层
├── models.py            # 数据结构
├── fetch_fund.py        # 基金净值获取
├── analysis.py          # 收益计算
├── risk.py              # 风险分析
├── rebalance.py         # 再平衡建议
├── scheduler.py         # APScheduler 定时任务
├── ai.py                # AI 投顾
└── data_io.py           # CSV 导入/导出
frontend/src/             # React 前端
├── pages/               # 页面组件
├── components/          # Layout + UI 组件
├── api/                 # API client + types
└── lib/                 # 工具函数
tests/                   # 测试
Dockerfile               # 多阶段构建
docker-compose.yml       # 单服务 + data 卷
```

## 提交规范

- Commit message **使用中文**
- 前缀：`feat:` / `fix:` / `docs:` / `perf:` / `chore:`
- 格式：`feat: 简短描述`，空行后可选详细说明
- PR 请描述清楚改动内容与动机

## 设计原则

ZFundPilot 只做数据分析与风险管理，**不做**自动交易、不预测涨跌、不构成投资建议。
贡献内容应与这一原则一致。
