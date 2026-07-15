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
| `ZFUNDPILOT_USERNAME` | `admin` | **仅首次启动**时用于初始化登录用户名。首次启动后用户名存储在 `data/auth.json`，之后可通过设置页在线修改 |
| `ZFUNDPILOT_PASSWORD` | 空 | **仅首次启动**时用于初始化密码哈希。首次启动后密码以 SHA-256 哈希存储在 `data/auth.json`，之后可通过设置页在线修改密码 |
| `ZFUNDPILOT_SECRET` | 自动生成 | **仅首次启动**时用于初始化 token 签名密钥。首次启动后自动生成随机密钥并存储在 `data/auth.json` |
| `ZFUNDPILOT_NAV_CRON` | `0 21 * * 1-5` | 净值定时更新 cron 表达式（工作日 21:00）。可在设置页面暂停/启用 |

```bash
# 示例：设置用户名 + 访问密码 + 自定义数据目录
export ZFUNDPILOT_USERNAME="admin"
export ZFUNDPILOT_PASSWORD="your_secret_password"
export ZFUNDPILOT_HOME=/var/lib/zfundpilot
uvicorn zfundpilot.api:app --port 8000
```

> ⚠️ 如果通过 `--host 0.0.0.0` 对外暴露，**务必设置 `ZFUNDPILOT_PASSWORD`**，
> 否则任何人都能查看你的持仓数据。

---

## 3. Docker 部署（服务器推荐）

### 3.1 配置 Docker 镜像加速（国内服务器必做）

国内服务器直连 Docker Hub 会超时，需先配镜像加速器：

```bash
mkdir -p /etc/docker
cat > /etc/docker/daemon.json << 'EOF'
{
  "registry-mirrors": [
    "https://mirror.ccs.tencentyun.com",
    "https://docker.m.daocloud.io",
    "https://hub-mirror.c.163.com"
  ]
}
EOF
sudo systemctl daemon-reload && sudo systemctl restart docker
```

> 阿里云 ECS 也可用专属加速器：登录 [容器镜像服务控制台](https://cr.console.aliyun.com/cn-hangzhou/instances/mirrors) 获取个人加速器地址。

### 3.2 克隆 + 配置密码

```bash
git clone https://github.com/Euzohn/ZFundPilot.git
cd ZFundPilot
cp .env.example .env
vi .env                      # 填入你的密码和密钥
```

### 3.3 配置端口

`docker-compose.yml` 不设默认端口，端口由 `docker-compose.override.yml` 指定（该文件已被 .gitignore，不会被 git 追踪）：

```bash
cat > docker-compose.override.yml << 'EOF'
services:
  zfundpilot:
    ports:
      - "8080:8000"
EOF
```

把 `8080` 换成你想要的端口。

### 3.4 构建并启动

```bash
docker compose up -d --build
```

浏览器打开 `http://服务器IP:你的端口` → 输入密码 → 进入系统。

容器会自动重启（`restart: always`），服务器重启后无需手动干预。

> Dockerfile 已内置 npm（npmmirror）和 pip（阿里云）国内镜像，构建速度有保障。

### 3.5 防火墙

```bash
# Ubuntu / Debian — 端口跟你 override 里设的一致
sudo ufw allow 8080

# CentOS / RHEL
sudo firewall-cmd --permanent --add-port=8080/tcp && sudo firewall-cmd --reload
```

> 阿里云 ECS 还需在安全组规则中放行对应端口（TCP）。

### 3.6 日常运维

| 操作 | 命令 |
|------|------|
| 查看日志 | `docker compose logs -f` |
| 停止 | `docker compose down` |
| 更新代码 | `git pull && docker compose up -d --build` |
| 备份数据 | `cp data/fund.db data/fund.db.bak` |

### 3.7 环境变量

| 变量 | 必填 | 说明 |
|------|------|------|
| `ZFUNDPILOT_USERNAME` | 可选，默认 `admin` | **仅首次启动**时用于初始化登录用户名。首次启动后存储在 `data/auth.json`，之后可通过设置页修改 |
| `ZFUNDPILOT_PASSWORD` | 服务器部署必填 | **仅首次启动**时用于初始化密码哈希。首次启动后密码存储在 `data/auth.json`，之后可通过设置页修改 |
| `ZFUNDPILOT_SECRET` | 建议 | **仅首次启动**时用于初始化 token 签名密钥，首次启动后自动生成并存储在 `data/auth.json` |
| `ZFUNDPILOT_NAV_CRON` | 可选，默认 `0 21 * * 1-5` | 净值定时更新 cron 表达式（工作日 21:00）。可在设置页面暂停/启用 |
| `ZFUNDPILOT_HOME` | 可选 | 数据目录位置，默认 `/app/data` |

> ⚠️ 服务器对外暴露时**务必设置 `ZFUNDPILOT_PASSWORD`**，否则任何人都能查看你的持仓。

---

## 数据备份

数据库为单文件 `data/fund.db`，备份只需复制该文件：

```bash
cp data/fund.db data/fund.db.bak
```

也可通过前端「交易管理 → CSV 导入/导出」导出交易流水为 CSV。
