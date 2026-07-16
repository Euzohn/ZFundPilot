# ─── 前端构建 ───
FROM node:22-slim AS frontend-build
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm config set registry https://registry.npmmirror.com && \
    npm ci
COPY frontend/ ./
RUN npm run build

# ─── 后端运行 ───
FROM python:3.11-slim AS backend
WORKDIR /app

# 设置时区为 Asia/Shanghai（修复 datetime.now() 返回 UTC 的问题）
ENV TZ=Asia/Shanghai
RUN apt-get update && apt-get install -y --no-install-recommends tzdata && \
    ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && \
    rm -rf /var/lib/apt/lists/*

# 安装后端依赖（使用阿里云 PyPI 镜像加速）
# 先只拷 pyproject.toml + stub 包，使 pip install 缓存与源码变更解耦
COPY pyproject.toml ./
RUN mkdir -p src/zfundpilot && touch src/zfundpilot/__init__.py && \
    pip install --no-cache-dir -e . \
    -i https://mirrors.aliyun.com/pypi/simple \
    --trusted-host mirrors.aliyun.com

# 拷贝真实源码（覆盖 stub，pip install 层缓存不受影响）
COPY src/ src/

# 复制前端构建产物
COPY --from=frontend-build /app/frontend/dist frontend/dist/

# 复制数据目录（首次启动自动建表）
RUN mkdir -p data

EXPOSE 8000

CMD ["uvicorn", "zfundpilot.api:app", "--host", "0.0.0.0", "--port", "8000"]
