#!/bin/bash
set -e

cd "$(dirname "$0")"

echo "=============================="
echo " ZFundPilot 更新脚本"
echo "=============================="
echo ""

# 1. 检查未提交的改动
if [ -n "$(git status --porcelain 2>/dev/null)" ]; then
  echo "⚠️  检测到本地未提交的改动："
  git status --short
  echo ""
  echo "⚠️  update.sh 会执行 git reset --hard origin/main，以上改动将被丢弃！"
  echo "💡  docker-compose.override.yml 和 .env 在 .gitignore 中不受影响"
  echo "按 Enter 继续，按 Ctrl+C 取消"
  read -r
fi

# 2. 记录当前版本
echo "📌 当前版本：$(git log --oneline -1)"
echo ""

# 3. 记录拉取前的 HEAD
BEFORE=$(git rev-parse HEAD)

# 4. 拉取最新代码（fetch + reset，避免分叉问题）
echo "📥 拉取最新代码..."
git fetch origin
git reset --hard origin/main
echo ""

# 5. 判断 HEAD 是否变化
AFTER=$(git rev-parse HEAD)

if [ "$BEFORE" = "$AFTER" ]; then
  echo "✅ 已是最新，无需构建，仅确保容器运行"
  docker compose up -d
else
  echo "📌 更新后版本：$(git log --oneline -1)"
  echo ""
  echo "🔨 检测到更新，构建并启动容器..."
  docker compose up -d --build
  # 清理悬空镜像（不清理 builder 缓存，保留层缓存加速增量构建）
  docker image prune -f
fi
echo ""

# 6. 检查状态
if [ "$(docker compose ps --status running -q | wc -l)" -gt 0 ]; then
  echo "✅ 容器运行中"
  echo ""
  docker compose ps
else
  echo "❌ 容器未正常运行，查看日志："
  docker compose logs --tail 20
fi

echo ""
echo "=============================="
echo ""
echo "常用命令："
echo ""
echo "  --- 部署 ---"
echo "  ./update.sh              # 拉取代码 + 构建重启"
echo "  docker compose up -d     # 后台启动（不重新构建）"
echo "  docker compose restart   # 重启容器"
echo "  docker compose down      # 停止并移除容器"
echo "  docker compose ps        # 查看容器状态"
echo ""
echo "  --- 日志 ---"
echo "  docker compose logs -f                         # 实时查看日志"
echo "  docker compose logs -50                       # 查看最近50行日志"
echo "  docker compose logs --tail 200 | grep sched   # 查看定时任务日志"
echo "  docker compose logs --tail 200 | grep T+1     # 查看 T+1 修复日志"
echo ""
echo "  --- 数据库 ---"
echo "  docker compose exec zfundpilot sqlite3 data/fund.db \\"
echo "    'SELECT * FROM transactions ORDER BY date DESC LIMIT 10'  # 查看最近10笔交易"
echo "  docker compose exec zfundpilot sqlite3 data/fund.db \\"
echo "    'SELECT * FROM audit_log ORDER BY ts DESC LIMIT 10'       # 查看审计日志"
echo "  docker compose exec zfundpilot sqlite3 data/fund.db \\"
echo "    'SELECT key,value FROM preferences'                       # 查看偏好设置"
echo ""
echo "  --- 定时任务 ---"
echo "  docker compose exec zfundpilot python -c \\"
echo "    'from zfundpilot.scheduler import get_status; print(get_status())'  # 查看定时任务状态"
echo ""
echo "  --- 运维 ---"
echo "  docker compose exec zfundpilot bash           # 进入容器终端"
echo "  docker stats zfundpilot --no-stream           # 查看资源占用"
echo "  docker system df                              # 查看磁盘占用"
echo "  cp -r data data.bak.\$(date +%Y%m%d)           # 备份数据目录"
