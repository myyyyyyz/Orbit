"""知识库核心路由: /api/knowledge/*

多租户口径（本轮改造）
----------------------
读写分离，两者用**不同**的隔离语义：

- **读取**（stats/search/context/ask/ask-stream）
  已登录 → 同时检索「组织共享库 ∪ 本人私有库」，两路结果按相似度合并；
  匿名   → 只读匿名沙箱（`settings.ANON_COLLECTION`），看不到任何真实租户数据。

- **写入**（upload/upload-text/delete）
  由参数 ``scope`` 决定落到哪个空间：``shared``（组织内共享，默认）
  或 ``personal``（仅本人可见）。写类端点一律要求登录——写入是持久化副作用，
  不能以"体验"为名开放给匿名；历史实现在这里写的是**全局共享** Collection，
  导致任意未登录访客都能写入、并删除他人上传的内容。

`scope` 只是"写到哪"的选择器，**不是**身份来源：租户/用户一律来自验签后的
Token claim（见 `middleware/auth.py::bind_scope`），客户端无法通过参数越权。
"""
import asyncio
import os
import uuid
from typing import Optional

import aiofiles
from fastapi import APIRouter, Body, Depends, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import StreamingResponse

from ..cache import get as cache_get, put as cache_put, purge_prefix
from ..chunk import chunk_text
from ..config import settings
from ..generate import generate_answer
from ..ingest import SUPPORTED_TYPES, get_file_type, parse_file
from ..logging_config import get_logger
from ..middleware.auth import bind_scope, get_current_user, get_optional_user
from ..multitenant import TenantScope, normalize_scope, read_scopes, uploads_dir
from ..rate_limit import limiter
from ..router import route_model
from ..search import resolve_active_version, search, search_formatted
from ..store import add_documents, delete_by_source, get_stats
from ..stream import stream_ask

logger = get_logger(__name__)

router = APIRouter(prefix="/api/v1/knowledge", tags=["knowledge"])


def _bind(user: Optional[dict], scope: Optional[str]) -> TenantScope:
    """把「认证身份 + 请求的 scope」合成作用域并写入上下文。

    `normalize_scope` 拒绝未知取值（回落 shared），而不是抛错——
    但无论取值如何，租户/用户都来自认证层，参数本身无法提权。
    """
    return bind_scope(user, normalize_scope(scope))


def _invalidate_content_cache(resolved: TenantScope) -> None:
    """知识库内容变更后清空受影响的语义缓存。

    不做这一步的话，用户上传新文档后提问仍会命中"上传前"的缓存答案，
    而且因为走的是缓存命中路径，不会有任何报错——属于静默给出错误答案。

    清除范围按写入目标区分：
    - 写入**组织共享库** → 全组织成员的缓存都可能过时，按租户前缀清；
    - 写入**个人私有库** → 只影响本人，按个人前缀清。
    """
    prefix = resolved.tenant_prefix if not resolved.is_personal else f"{resolved.read_key}|"
    try:
        removed = purge_prefix(prefix)
        if removed:
            logger.info("semantic_cache_invalidated", prefix=prefix, removed=removed)
    except Exception:
        logger.warning("semantic_cache_invalidation_failed", prefix=prefix, exc_info=True)


def _cache_namespace(resolved: TenantScope) -> str:
    """缓存命名空间 = 读取身份 + 活跃索引版本（版本变化后自动失效旧答案）。"""
    try:
        version = resolve_active_version(resolved)
        return f"{resolved.read_key}|{version.collection_name}"
    except Exception:
        logger.warning("cache_namespace_resolve_failed", exc_info=True)
        return f"{resolved.read_key}|default"


@router.get("/stats")
def api_stats(
    scope: Optional[str] = Query(None, description="shared | personal，仅影响返回的明细口径"),
    current_user: Optional[dict] = Depends(get_optional_user),
):
    """知识库统计：同时返回组织共享库与个人私有库的规模。"""
    base = _bind(current_user, scope)

    if base.is_anonymous:
        return {**get_stats(base), "shared": None, "personal": None}

    shared = TenantScope(base.tenant_id, base.user_id, "shared")
    personal = TenantScope(base.tenant_id, base.user_id, "personal")
    return {
        **get_stats(shared),
        "tenant_id": base.tenant_id,
        "shared": get_stats(shared),
        "personal": get_stats(personal),
    }


@router.get("/supported-types")
def api_supported_types():
    return {"types": list(SUPPORTED_TYPES.keys())}


@router.post("/upload")
@limiter.limit("30/minute")
async def api_upload(
    request: Request,
    file: UploadFile = File(...),
    scope: str = Query("shared", description="shared=组织共享 | personal=我的私有"),
    current_user: dict = Depends(get_current_user),
):
    if not file.filename:
        raise HTTPException(400, "文件名不能为空")
    if not get_file_type(file.filename):
        raise HTTPException(400, f"不支持的文件类型，支持: {list(SUPPORTED_TYPES.keys())}")

    safe_filename = os.path.basename(file.filename)
    if not safe_filename or safe_filename in (".", ".."):
        raise HTTPException(400, "文件名非法")

    resolved = _bind(current_user, scope)

    # 上传原件按作用域分目录：组织共享文档与个人私有文档物理分开
    filename = f"{uuid.uuid4().hex}_{safe_filename}"
    filepath = os.path.join(str(uploads_dir(resolved)), filename)

    content = await file.read()
    if len(content) > settings.MAX_FILE_SIZE:
        raise HTTPException(400, f"文件超过 {settings.MAX_FILE_SIZE // 1024 // 1024}MB 限制")

    async with aiofiles.open(filepath, "wb") as f:
        await f.write(content)

    try:
        # 解析是 CPU/IO 密集的同步操作，直接在 async 端点里跑会冻结事件循环
        text, file_type = await asyncio.to_thread(parse_file, filepath)
    except Exception as e:
        raise HTTPException(500, f"文件解析失败: {str(e)}")

    if not text or not text.strip():
        raise HTTPException(400, "文件内容为空")

    chunks = await asyncio.to_thread(
        chunk_text, text,
        metadata={"source": safe_filename, "file_type": file_type, "char_count": len(text)},
    )
    if not chunks:
        raise HTTPException(500, "文本切割失败")

    # 切片 → embedding → 写库同样是同步阻塞链路，统一移出事件循环
    count = await asyncio.to_thread(add_documents, chunks, resolved)
    _invalidate_content_cache(resolved)
    return {
        "status": "ok", "filename": safe_filename, "file_type": file_type,
        "char_count": len(text), "chunks": count,
        "scope": resolved.scope, "collection": resolved.collection,
        "user_scoped": True,
        "message": f"已索引 {safe_filename}（{count} 个片段，"
                   f"{'组织共享' if not resolved.is_personal else '我的私有'}）",
    }


@router.post("/upload-text")
@limiter.limit("30/minute")
async def api_upload_text(
    request: Request,
    text: str = Query(..., description="要索引的文本内容"),
    source: str = Query("manual", description="来源标识"),
    scope: str = Query("shared", description="shared=组织共享 | personal=我的私有"),
    current_user: dict = Depends(get_current_user),
):
    if not text or not text.strip():
        raise HTTPException(400, "文本内容不能为空")
    resolved = _bind(current_user, scope)
    chunks = await asyncio.to_thread(
        chunk_text, text,
        metadata={"source": source, "file_type": "text", "char_count": len(text)},
    )
    count = await asyncio.to_thread(add_documents, chunks, resolved)
    _invalidate_content_cache(resolved)
    return {
        "status": "ok", "source": source, "char_count": len(text), "chunks": count,
        "scope": resolved.scope, "collection": resolved.collection, "user_scoped": True,
    }


@router.get("/search")
def api_search(
    q: str = Query(..., description="搜索查询"),
    top_k: int = Query(None, description="返回结果数"),
    format: str = Query("json", description="返回格式: json | text"),
    scope: Optional[str] = Query(None, description="shared | personal（读取时两者都会检索）"),
    current_user: Optional[dict] = Depends(get_optional_user),
):
    resolved = _bind(current_user, scope)
    if format == "text":
        return {"results": search_formatted(q, top_k, resolved)}
    return {"query": q, "results": search(q, top_k, resolved)}


@router.delete("/source")
def api_delete_source(
    source: str = Query(..., description="要删除的文档来源名称"),
    scope: str = Query("shared", description="shared=组织共享 | personal=我的私有"),
    current_user: dict = Depends(get_current_user),
):
    # 删除是破坏性操作：必须登录，且只能在**自己有权访问的那个空间**里删。
    # 组织共享库允许成员维护（协作场景需要），个人私有库只有本人能碰。
    resolved = _bind(current_user, scope)
    removed = delete_by_source(source, resolved)
    _invalidate_content_cache(resolved)
    return {
        "status": "ok", "source": source, "removed_chunks": removed,
        "scope": resolved.scope,
        "message": f"已删除 {source} 的索引",
    }


@router.get("/context")
def api_context(
    q: str = Query(..., description="搜索查询"),
    top_k: int = Query(None, description="返回结果数"),
    scope: Optional[str] = Query(None),
    current_user: Optional[dict] = Depends(get_optional_user),
):
    resolved = _bind(current_user, scope)
    return {"context": search_formatted(q, top_k, resolved)}


@router.post("/ask")
@limiter.limit("60/minute")
def api_ask(
    request: Request,
    body: dict = Body(...),
    current_user: Optional[dict] = Depends(get_optional_user),
):
    """RAG 完整闭环: 用户问题 → 缓存检查 → 检索 → 模型路由 → LLM 生成 → 带引用返回"""
    question = body.get("question", "").strip()
    if not question:
        raise HTTPException(400, "问题不能为空")

    top_k = body.get("top_k") or settings.rag.retrieval.top_k
    resolved = _bind(current_user, body.get("scope"))
    cache_namespace = _cache_namespace(resolved)

    # 语义缓存检查
    cached = cache_get(question, namespace=cache_namespace)
    if cached:
        return {
            "question": question,
            "answer": cached["answer"],
            "sources": cached["sources"],
            "model": cached["model"],
            "retrieval_count": cached.get("retrieval_count", 0),
            "cache_hit": True,
        }

    chunks = search(question, top_k, resolved)
    route = route_model(question, [c["score"] for c in chunks])

    if route.needs_clarification:
        return {
            "question": question,
            "answer": route.clarification_question or "请提供更多细节",
            "sources": [],
            "model": "router",
            "retrieval_count": len(chunks),
            "cache_hit": False,
            "router_tier": route.tier,
            "router_reason": route.reason,
            "needs_clarification": True,
        }

    user_api_key = request.headers.get("X-API-Key") or None
    user_model = request.headers.get("X-LLM-Model") or route.model
    result = generate_answer(
        question, chunks, body.get("history", []),
        model=user_model, api_key=user_api_key, scope=resolved,
    )
    cache_put(
        question, result["answer"], result["sources"], result["model"],
        namespace=cache_namespace,
    )

    return {
        "question": question,
        "answer": result["answer"],
        "sources": result["sources"],
        "model": result["model"],
        "retrieval_count": len(chunks),
        "cache_hit": False,
        "router_tier": route.tier,
        "router_reason": route.reason,
    }


@router.get("/ask/stream")
@limiter.limit("60/minute")
def api_ask_stream(
    request: Request,
    q: str = Query(..., description="用户问题"),
    top_k: int = Query(None, description="检索结果数"),
    scope: Optional[str] = Query(None, description="shared | personal（读取时两者都会检索）"),
    current_user: Optional[dict] = Depends(get_optional_user),
):
    """流式 RAG 问答（SSE）"""
    resolved = _bind(current_user, scope)
    user_api_key = request.headers.get("X-API-Key") or None
    user_model = request.headers.get("X-LLM-Model") or None

    # scope 显式透传给生成器：SSE 的响应体是在端点返回**之后**才被迭代的，
    # 不要依赖生成器执行时上下文仍然有效。
    return StreamingResponse(
        stream_ask(q, top_k, scope=resolved, api_key=user_api_key, model=user_model),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"},
    )


# 保留读取作用域集合的显式引用，便于排障时确认"这次查询覆盖了哪些库"
__all__ = ["router", "read_scopes"]
