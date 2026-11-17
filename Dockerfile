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
RUN apt-get update && apt-get install -y --no-install-recommends tzdata libjpeg62-turbo && \
    ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && \
    rm -rf /var/lib/apt/lists/*

# 安装后端依赖（使用阿里云 PyPI 镜像加速）
# requirements.txt 与源码分离，依赖不变时 pip install 层缓存命中
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt \
    -i https://mirrors.aliyun.com/pypi/simple \
    --trusted-host mirrors.aliyun.com

# 拷贝源码
COPY src/ src/
ENV PYTHONPATH=/app/src

# 复制前端构建产物
COPY --from=frontend-build /app/frontend/dist frontend/dist/

# 复制数据目录（首次启动自动建表）
RUN mkdir -p data

# 非 root 运行：新建 zfundpilot 用户（UID 1000）并把数据目录属主交给他。
# bind mount（./data:/app/data）会遮蔽镜像内属主，宿主机目录需 chown 一致（见 DEPLOY.md）。
RUN useradd -m -u 1000 zfundpilot && \
    chown zfundpilot:zfundpilot /app/data
USER zfundpilot

EXPOSE 8000

CMD ["uvicorn", "zfundpilot.api:app", "--host", "0.0.0.0", "--port", "8000"]
