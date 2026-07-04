# 部署指南

本指南覆盖三种部署方式，按复杂度递增：

| 方式 | 适用场景 | 需要启动的进程 |
|------|---------|--------------|
| [开发模式](#1-开发模式) | 本地开发调试 | 后端 + 前端各一个终端 |
| [生产模式](#2-生产模式单进程) | 个人日常使用 | 仅后端一个进程 |
| [Docker](#3-docker-部署) | 环境隔离 / 服务器部署 | 一个容器 |

---

## 前置条件

- Python 3.10+
- Node.js 18+ / npm 9+
- 网络可访问 `fund.eastmoney.com`（获取基金净值）

> macOS 如遇 `SSL: CERTIFICATE_VERIFY_FAILED`，运行一次
> `/Applications/Python\ 3.x/Install\ Certificates.command`

---

## 1. 开发模式

前后端分离运行，前端支持热更新。

```bash
# 安装后端依赖
pip install -e .

# 安装前端依赖
cd frontend && npm install && cd ..
```

```bash
# 终端 1：后端 API（自动重载）
uvicorn zfundpilot.api:app --reload --port 8000

# 终端 2：前端开发服务器（热更新）
cd frontend && npm run dev
```

浏览器打开 http://localhost:5173 ，Vite 会自动将 `/api/*` 代理到 `localhost:8000`。

---

## 2. 生产模式（单进程）

构建前端静态文件，由 FastAPI 统一服务，只需一个进程。

### 2.1 构建前端

```bash
cd frontend
npm install
npm run build          # 产物输出到 frontend/dist/
cd ..
```

### 2.2 启动

```bash
pip install -e .
uvicorn zfundpilot.api:app --host 0.0.0.0 --port 8000
```

浏览器打开 http://localhost:8000 ，FastAPI 同时提供 API 和前端页面。

> 启动时如果检测到 `frontend/dist/` 存在，会自动挂载为静态文件服务。

### 2.3 后台运行（macOS / Linux）

```bash
nohup uvicorn zfundpilot.api:app --host 0.0.0.0 --port 8000 > zfundpilot.log 2>&1 &
```

### 2.4 环境变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `ZFUNDPILOT_HOME` | 项目根目录 | 数据目录（`data/` 所在位置） |

```bash
# 示例：将数据放在 /var/lib/zfundpilot
export ZFUNDPILOT_HOME=/var/lib/zfundpilot
uvicorn zfundpilot.api:app --port 8000
```

---

## 3. Docker 部署

### 3.1 构建镜像

```bash
docker build -t zfundpilot .
```

### 3.2 运行容器

```bash
# 数据持久化到宿主机 ./data 目录
docker run -d \
  --name zfundpilot \
  -p 8000:8000 \
  -v $(pwd)/data:/app/data \
  zfundpilot

# 自定义数据目录
docker run -d \
  --name zfundpilot \
  -p 8000:8000 \
  -e ZFUNDPILOT_HOME=/data \
  -v /path/to/data:/data \
  zfundpilot
```

浏览器打开 http://localhost:8000

### 3.3 停止 / 更新

```bash
docker stop zfundpilot && docker rm zfundpilot
docker build -t zfundpilot . && docker run -d ...  # 重新运行
```

---

## 数据备份

数据库为单文件 `data/fund.db`，备份只需复制该文件：

```bash
cp data/fund.db data/fund.db.bak
```

也可通过前端「交易管理 → CSV 导入/导出」导出交易流水为 CSV。
