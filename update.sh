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

# 3. 拉取最新代码
echo "📥 拉取最新代码..."
git pull
echo ""

# 4. 显示更新后的版本
echo "📌 更新后版本：$(git log --oneline -1)"
echo ""

# 5. 构建并重启
echo "🔨 构建并启动容器..."
docker compose build --no-cache
docker compose up -d
docker image prune -f
echo ""

# 6. 检查状态
if [ "$(docker compose ps --status running -q | wc -l)" -gt 0 ]; then
  echo "✅ 更新完成！容器运行中"
  echo ""
  docker compose ps
else
  echo "❌ 容器未正常运行，查看日志："
  docker compose logs --tail 20
fi

echo ""
echo "=============================="