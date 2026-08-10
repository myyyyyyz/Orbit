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
from .agents import init_loop_db

# API 路由
from .api.knowledge import router as knowledge_router
from .api.knowledge_plan import router as knowledge_plan_router
from .api.performance import router as performance_router
from .api.strategy import router as strategy_router
from .api.logos import router as logos_router
from .api.auth import router as auth_router
from .api.memory import router as memory_router
from .api.onboarding import router as onboarding_router
from .api.storage import router as storage_router
from .agents.api import router as agents_router

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期：启动时初始化 DB + 预热 Embedding 模型"""
    logger.info("Knowledge Base Service starting...")
    try:
        init_tenant_db()
        init_memory_db()
        init_loop_db()
    except Exception:
        logger.warning("Database init failed", exc_info=True)
    try:
        preload_model()
    except Exception:
        logger.warning("Embedding model preload failed, will load on first request", exc_info=True)

    # P5: 启动 schedule 调度器（每分钟检查一次到期 schedule）
    try:
        from .agents.api import trigger_schedule
        from .agents.schedule import start_scheduler
        start_scheduler(trigger_schedule)
    except Exception:
        logger.warning("Schedule scheduler 启动失败", exc_info=True)

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
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    # Bug #11 修复：补齐 P4 per-role 模型 headers（X-LLM-Model-Planner/Builder/Reviewer/User），
    # 否则浏览器预检（OPTIONS）失败 → 前端 "Failed to fetch"
    allow_headers=[
        "Content-Type", "Authorization", "X-API-Key", "X-LLM-Model", "X-Request-ID",
        "X-LLM-Model-Planner", "X-LLM-Model-Builder", "X-LLM-Model-Reviewer", "X-LLM-Model-User",
    ],
)

# 注册路由
app.include_router(knowledge_router)
app.include_router(knowledge_plan_router)
app.include_router(performance_router)
app.include_router(strategy_router)
app.include_router(logos_router)
app.include_router(auth_router)
app.include_router(memory_router)
app.include_router(onboarding_router)
app.include_router(storage_router)
app.include_router(agents_router)


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
    # Bug #10 修复：HEAD 请求对 chat/completions 端点必然失败（不支持 HEAD），
    # 且默认 base_url 是 OpenAI 而实际可能用 DeepSeek。
    # 改为仅校验 key 是否配置（不产生真实 API 调用开销；真实调用失败会在请求时体现）。
    try:
        api_key = os.getenv("LLM_API_KEY", "")
        if api_key:
            checks["llm_api"] = "ok"
        else:
            checks["llm_api"] = "skipped (no API key)"
    except Exception as e:  # noqa: BLE001
        checks["llm_api"] = f"unreachable: {str(e)[:100]}"

    all_healthy = all(
        v == "ok" or v.startswith("skipped")
        for v in [checks.get("chromadb", ""), checks.get("sqlite", ""), checks.get("llm_api", "")]
    )
    checks["status"] = "ok" if all_healthy else "degraded"
    return checks
