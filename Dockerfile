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

# 安装后端依赖（使用阿里云 PyPI 镜像加速）
COPY pyproject.toml ./
COPY src/ src/
RUN pip install --no-cache-dir -e . \
    -i https://mirrors.aliyun.com/pypi/simple \
    --trusted-host mirrors.aliyun.com

# 复制前端构建产物
COPY --from=frontend-build /app/frontend/dist frontend/dist/

# 复制数据目录（首次启动自动建表）
RUN mkdir -p data

EXPOSE 8000

CMD ["uvicorn", "zfundpilot.api:app", "--host", "0.0.0.0", "--port", "8000"]
