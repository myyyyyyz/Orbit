# Orbit Backend — FastAPI 生产镜像

FROM python:3.11-slim

# Python 运行时行为
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    # 数据根目录（与 docker-compose 的 volume 挂载点保持一致）
    DATA_DIR=/app/data \
    # sentence-transformers 模型缓存落在数据卷，避免每次重建镜像重新下载
    HF_HOME=/app/data/.cache/huggingface \
    SENTENCE_TRANSFORMERS_HOME=/app/data/.cache/sentence-transformers

WORKDIR /app

# 构建依赖单独一层，装完即清理，避免残留在镜像中
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/*

# 依赖层缓存：仅 requirements 变化时才重装
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# 数据目录 + 非 root 用户（容器逃逸后无 root 权限）
RUN mkdir -p /app/data/chroma_db /app/data/uploads /app/data/memory /app/knowledge \
    && useradd -m -u 1000 orbit \
    && chown -R orbit:orbit /app

USER orbit

EXPOSE 8001

HEALTHCHECK --interval=30s --timeout=10s --retries=3 --start-period=90s \
    CMD python -c "import urllib.request,sys; r=urllib.request.urlopen('http://127.0.0.1:8001/health',timeout=5); sys.exit(0 if r.status==200 else 1)"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8001", "--workers", "1"]
