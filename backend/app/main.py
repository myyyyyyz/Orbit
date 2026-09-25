"""Knowledge Base Service — FastAPI 应用入口

路由按域拆分在 api/ 目录下，此处只做应用初始化和注册。
"""

import asyncio
import os
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from .config import settings, ConfigError
from .logging_config import setup_logging, get_logger
from .middleware.request_id import RequestIDMiddleware
from .middleware.error_handler import register_exception_handlers
from .middleware.security_headers import SecurityHeadersMiddleware
from .rate_limit import limiter
from .embed import preload_model
from .multitenant import init_db as init_tenant_db
from .memory import init_memory_db
from .agents import init_loop_db
# P2-2: 可观测性（Prometheus + Sentry）
from .monitoring import setup_prometheus, setup_sentry

# API 路由
from .api.knowledge import router as knowledge_router
from .api.knowledge_plan import router as knowledge_plan_router
from .api.knowledge_imports import router as knowledge_imports_router
from .api.performance import router as performance_router
from .api.strategy import router as strategy_router
from .api.logos import router as logos_router
from .api.auth import router as auth_router
from .api.memory import router as memory_router
from .api.onboarding import router as onboarding_router
from .api.storage import router as storage_router
from .api.usage import router as usage_router
from .agents.api import router as agents_router

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期：启动时初始化 DB + 预热 Embedding 模型；退出时优雅停机。"""
    # P0-1: 初始化结构化日志（必须最先执行）
    setup_logging()

    # P1-3: 启动时配置验证（仅在非测试环境执行）
    # 生产环境配置错误直接抛 ConfigError 阻止启动，不留半配置状态对外服务
    if not os.getenv("PYTEST_RUNNING"):
        from .config import _validate_config_on_startup
        _validate_config_on_startup()

    logger.info("knowledge_base_starting", version="1.0.0")
    try:
        init_tenant_db()
        init_memory_db()
        init_loop_db()
        logger.info("databases_initialized")
    except Exception:
        logger.error("database_init_failed", exc_info=True)
        # 数据库不可用属于致命错误：带着坏掉的 DB 启动只会让所有请求 500
        if not os.getenv("PYTEST_RUNNING"):
            raise

    try:
        # 模型加载是同步阻塞且耗时的（首次可能数十秒），不能占住事件循环
        await asyncio.to_thread(preload_model)
        logger.info("embedding_model_preloaded")
    except Exception:
        logger.warning("embedding_preload_failed", exc_info=True)

    # P5: 启动 schedule 调度器（每分钟检查一次到期 schedule）
    started_scheduler = False
    try:
        from .agents.api import trigger_schedule
        from .agents.schedule import start_scheduler
        start_scheduler(trigger_schedule)
        started_scheduler = True
        logger.info("schedule_scheduler_started")
    except Exception:
        logger.warning("schedule_scheduler_startup_failed", exc_info=True)

    yield

    # ── 优雅停机 ──
    logger.info("knowledge_base_shutting_down")
    if started_scheduler:
        try:
            from .agents.schedule import stop_scheduler
            stop_scheduler()
            logger.info("schedule_scheduler_stopped")
        except Exception:
            logger.warning("schedule_scheduler_stop_failed", exc_info=True)


app = FastAPI(
    title="Knowledge Base Service",
    description="知识库服务 — 文档上传、向量化、语义检索",
    version="1.0.0",
    lifespan=lifespan,
)

# P2-2: Prometheus 指标仪表盘（/metrics）
setup_prometheus(app)

# P2-2: Sentry 错误追踪（自动，需要 SENTRY_DSN 环境变量）
setup_sentry()

# Rate Limiter —— 全进程唯一实例（详见 app/rate_limit.py）
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# X-Request-ID — 全链路请求追踪
app.add_middleware(RequestIDMiddleware)

# P0-2: 全局异常处理 —— 必须同时注册 HTTPException / RequestValidationError /
# Exception 三类 handler，否则业务错误会绕过统一结构、丢失 request_id。
register_exception_handlers(app)

# 安全响应头（纯 ASGI 实现，不影响 SSE）
app.add_middleware(SecurityHeadersMiddleware)

# CORS（最后添加 = 最外层，保证异常响应也带上 CORS 头）
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
    expose_headers=["X-Request-ID"],
)

# 注册路由
app.include_router(knowledge_router)
app.include_router(knowledge_plan_router)
app.include_router(knowledge_imports_router)
app.include_router(performance_router)
app.include_router(strategy_router)
app.include_router(logos_router)
app.include_router(auth_router)
app.include_router(memory_router)
app.include_router(onboarding_router)
app.include_router(storage_router)
app.include_router(usage_router)
app.include_router(agents_router)


# ── 健康检查 ──
#
# 三个端点职责不同，混用会导致"要么无意义地恒 200，要么把降级态误判为不可用"：
#   /health        存活探针（liveness）——进程能响应即 200，供容器 healthcheck 使用
#   /health/detail 依赖明细——永远 200，body 给出各依赖状态，供运维面板展示
#   /ready         就绪探针（readiness）——关键依赖不可用时返回 503，供负载均衡摘除节点

def _run_dependency_checks() -> dict:
    """探测各依赖的实时状态。"""
    checks: dict = {"service": "knowledge-base", "version": "1.0.0"}

    # 1. ChromaDB
    try:
        from .store import get_client
        get_client().heartbeat()
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
    api_key = os.getenv("LLM_API_KEY", "")
    checks["llm_api"] = "ok" if api_key else "skipped (no API key)"

    critical_ok = checks["chromadb"] == "ok" and checks["sqlite"] == "ok"
    # LLM 未配置（skipped）只记为中性：生产环境配置校验本就强制要求 LLM_API_KEY，
    # 这里的 skipped 只出现在开发/测试环境，不该把状态标成 degraded。
    llm_value = checks["llm_api"]
    llm_bad = not (llm_value == "ok" or llm_value.startswith("skipped"))
    degraded = not critical_ok or llm_bad

    checks["status"] = "ok" if not degraded else ("unavailable" if not critical_ok else "degraded")
    return checks


@app.get("/health")
def health(request: Request):
    """存活探针：只证明进程还能处理请求，不探测外部依赖。

    刻意保持极简——容器编排用它判断"要不要重启这个进程"，
    依赖抖动不该触发重启风暴（那属于 /ready 的职责）。
    """
    return {"status": "ok", "service": "knowledge-base", "version": "1.0.0"}


@app.get("/health/detail")
def health_detail(request: Request):
    """依赖明细：始终 200，由 body 表达健康度。"""
    log = get_logger(__name__).bind(request_id=getattr(request.state, "request_id", "unknown"))
    checks = _run_dependency_checks()
    if checks["status"] != "ok":
        log.warning(
            "health_check_degraded",
            status=checks["status"],
            chromadb=checks.get("chromadb"),
            sqlite=checks.get("sqlite"),
            llm_api=checks.get("llm_api"),
        )
    return checks


@app.get("/ready")
def ready(request: Request):
    """就绪探针：关键依赖（向量库 + 关系库）不可用时返回 503。

    LLM Key 缺失只标 degraded 但不摘除节点——检索/知识库功能仍然可用。
    """
    checks = _run_dependency_checks()
    critical_ok = checks["chromadb"] == "ok" and checks["sqlite"] == "ok"
    status_code = 200 if critical_ok else 503
    return JSONResponse(status_code=status_code, content=checks)
