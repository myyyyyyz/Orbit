"""Knowledge Base Service — FastAPI 应用入口

路由按域拆分在 api/ 目录下，此处只做应用初始化和注册。
"""

import os
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

from .config import settings
from .middleware.request_id import RequestIDMiddleware
from .embed import preload_model
from .multitenant import init_db as init_tenant_db
from .memory import init_memory_db

# API 路由
from .api.knowledge import router as knowledge_router
from .api.performance import router as performance_router
from .api.strategy import router as strategy_router
from .api.logos import router as logos_router
from .api.auth import router as auth_router
from .api.memory import router as memory_router
from .api.onboarding import router as onboarding_router
from .api.storage import router as storage_router

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期：启动时初始化 DB + 预热 Embedding 模型"""
    logger.info("Knowledge Base Service starting...")
    try:
        init_tenant_db()
        init_memory_db()
    except Exception:
        logger.warning("Database init failed", exc_info=True)
    try:
        preload_model()
    except Exception:
        logger.warning("Embedding model preload failed, will load on first request", exc_info=True)
    yield
    logger.info("Knowledge Base Service shutting down...")


app = FastAPI(
    title="Knowledge Base Service",
    description="知识库服务 — 文档上传、向量化、语义检索",
    version="1.0.0",
    lifespan=lifespan,
)

# Rate Limiter
limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# X-Request-ID — 全链路请求追踪
app.add_middleware(RequestIDMiddleware)

# CORS
_CORS_ORIGINS = os.getenv("CORS_ORIGINS", "http://localhost:3000,http://localhost:8000")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in _CORS_ORIGINS.split(",") if o.strip()],
    allow_methods=["GET", "POST", "PATCH", "DELETE"],
    allow_headers=["Content-Type", "Authorization", "X-API-Key", "X-LLM-Model"],
)

# 注册路由
app.include_router(knowledge_router)
app.include_router(performance_router)
app.include_router(strategy_router)
app.include_router(logos_router)
app.include_router(auth_router)
app.include_router(memory_router)
app.include_router(onboarding_router)
app.include_router(storage_router)


# ── 健康检查 ──

@app.get("/health")
def health():
    """深度健康检查：验证 ChromaDB、SQLite、LLM API 连通性"""
    checks = {"service": "knowledge-base"}

    # 1. ChromaDB
    try:
        from .store import get_client
        client = get_client()
        client.heartbeat()
        checks["chromadb"] = "ok"
    except Exception as e:
        checks["chromadb"] = f"unhealthy: {str(e)[:100]}"

    # 2. SQLite
    try:
        from .multitenant import _get_db
        conn = _get_db()
        conn.execute("SELECT 1")
        conn.close()
        checks["sqlite"] = "ok"
    except Exception as e:
        checks["sqlite"] = f"unhealthy: {str(e)[:100]}"

    # 3. LLM API 可达性（可选）
    try:
        api_key = os.getenv("LLM_API_KEY", "")
        if api_key:
            import urllib.request
            base_url = os.getenv("LLM_BASE_URL", "https://api.openai.com/v1/chat/completions")
            head_req = urllib.request.Request(base_url, method="HEAD")
            urllib.request.urlopen(head_req, timeout=5)
            checks["llm_api"] = "ok"
        else:
            checks["llm_api"] = "skipped (no API key)"
    except Exception as e:
        checks["llm_api"] = f"unreachable: {str(e)[:100]}"

    all_healthy = all(
        v == "ok" or v.startswith("skipped")
        for v in [checks.get("chromadb", ""), checks.get("sqlite", ""), checks.get("llm_api", "")]
    )
    checks["status"] = "ok" if all_healthy else "degraded"
    return checks
