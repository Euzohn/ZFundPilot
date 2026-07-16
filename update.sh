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
  echo "按 Enter 继续（git pull 会尝试合并，docker-compose.override.yml 不受影响）"
  echo "按 Ctrl+C 取消"
  read -r
fi

# 2. 记录当前版本
echo "📌 当前版本：$(git log --oneline -1)"
echo ""

# 3. 记录拉取前的 HEAD
BEFORE=$(git rev-parse HEAD)

# 4. 拉取最新代码
echo "📥 拉取最新代码..."
git pull
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
  docker image prune -f
  docker builder prune -f
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
echo "  ./update.sh              # 拉取代码 + 构建重启"
echo "  docker compose ps        # 查看容器状态"
echo "  docker compose logs -f   # 实时查看日志"
echo "  docker compose logs -50  # 查看最近50行日志"
echo "  docker compose restart   # 重启容器"
echo "  docker compose down       # 停止并移除容器"
echo "  docker compose up -d     # 后台启动（不重新构建）"
