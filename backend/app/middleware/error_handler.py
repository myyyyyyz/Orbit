"""
全局异常处理中间件。

所有异常在此统一为同一种 JSON 结构，保证前端只需处理一种错误格式：

    {
        "error": "错误描述",
        "detail": "详细信息（仅开发环境返回）",
        "request_id": "abc-123"
    }

分工（Starlette 的异常处理是分层的，必须两条路径都注册才会生效）：
- HTTPException / RequestValidationError → 注册进 ExceptionMiddleware（内层），
  由 FastAPI 的异常中间件在业务代码抛出处捕获。
- Exception（兜底）→ Starlette 会把 `Exception` 键**提升**为最外层
  ServerErrorMiddleware 的 handler，捕获所有未被内层处理的异常。

历史缺陷：只注册了 `Exception`，导致 HTTPException 走 FastAPI 默认处理器
返回 `{"detail": ...}` 且**丢失 request_id**，而这里针对 HTTPException 的
分支永远不会被执行（死代码）。此处通过 `register_exception_handlers`
同时注册三类 handler 修复。
"""

import traceback

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from ..logging_config import get_logger
from .request_id import get_request_id

logger = get_logger(__name__)


def _is_dev() -> bool:
    """判断是否为开发环境。"""
    import os
    return os.getenv("ENV", "development").lower() in ("dev", "development", "local")


def _error_body(error: str, request_id: str, detail=None) -> dict:
    body = {"error": error, "request_id": request_id}
    if detail is not None:
        body["detail"] = detail
    return body


def _request_id_headers(request_id: str, extra=None) -> dict:
    """把 request_id 也放进响应头。

    必须在这里显式设置：`Exception` 兜底 handler 会被 Starlette 提升到最外层
    ServerErrorMiddleware（在 RequestIDMiddleware **之外**）执行，
    因此请求 ID 中间件没有机会往 500 响应上补 X-Request-ID 头——
    实测表现为 500 的 body 里有 request_id、日志里有，唯独响应头缺失，
    前端/网关就无法用它串联日志。
    """
    headers = dict(extra or {})
    headers["X-Request-ID"] = request_id
    return headers


# ── 已知异常 ①：HTTPException ─────────────────────────────

async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    """业务显式抛出的 HTTPException：保留状态码，补齐统一结构与 request_id。"""
    request_id = get_request_id(request)

    if exc.status_code >= 500:
        logger.error(
            "http_exception",
            status_code=exc.status_code,
            detail=str(exc.detail)[:200],
            request_id=request_id,
            path=request.url.path,
        )
    else:
        logger.warning(
            "http_exception",
            status_code=exc.status_code,
            detail=str(exc.detail)[:200],
            request_id=request_id,
            path=request.url.path,
        )

    headers = getattr(exc, "headers", None)
    return JSONResponse(
        status_code=exc.status_code,
        # 同时保留 `detail`（FastAPI 既有契约，存量客户端在读）与新增的
        # `error` / `request_id`，避免统一错误结构变成破坏性变更
        content=_error_body(str(exc.detail), request_id, detail=str(exc.detail)),
        headers=_request_id_headers(request_id, headers),
    )


# ── 已知异常 ②：请求参数校验失败（422）─────────────────────

async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    """Pydantic 请求校验失败：保持 422，同时补齐 request_id 供前端串联日志。"""
    request_id = get_request_id(request)
    logger.warning(
        "request_validation_failed",
        request_id=request_id,
        path=request.url.path,
        errors=len(exc.errors()),
    )
    return JSONResponse(
        status_code=422,
        content=_error_body("请求参数校验失败", request_id, detail=exc.errors()),
        headers=_request_id_headers(request_id),
    )


# ── 未知异常：兜底 ───────────────────────────────────────

async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """未预期异常：记录完整堆栈，对外只暴露通用信息（开发环境保留详情）。"""
    request_id = get_request_id(request)

    logger.error(
        "unhandled_exception",
        request_id=request_id,
        path=request.url.path,
        method=request.method,
        error_type=type(exc).__name__,
        error=str(exc)[:300],
        exc_info=True,
    )

    return JSONResponse(
        status_code=500,
        content=_error_body(
            "Internal Server Error",
            request_id,
            detail=(str(exc) if _is_dev() else None),
        ),
        headers=_request_id_headers(request_id),
    )


def register_exception_handlers(app: FastAPI) -> None:
    """一次性注册全部异常处理器（顺序无关，键决定归属层）。"""
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    # 注意：Exception 键会被 Starlette 提升为最外层 ServerErrorMiddleware 的兜底 handler
    app.add_exception_handler(Exception, global_exception_handler)
