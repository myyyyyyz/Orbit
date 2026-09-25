"""知识库核心路由: /api/knowledge/*"""
import asyncio
import os
import uuid
import aiofiles
from typing import Optional
from fastapi import APIRouter, UploadFile, File, HTTPException, Query, Body, Depends, Request
from fastapi.responses import StreamingResponse

from ..config import settings
from ..ingest import parse_file, get_file_type, SUPPORTED_TYPES
from ..chunk import chunk_text
from ..store import add_documents, delete_by_source, get_stats
from ..search import resolve_active_version, search, search_formatted
from ..generate import generate_answer
from ..router import route_model
from ..cache import get as cache_get, put as cache_put, purge_user as cache_purge_user
from ..stream import stream_ask
from ..middleware.auth import get_optional_user
from ..rate_limit import limiter

router = APIRouter(prefix="/api/v1/knowledge", tags=["knowledge"])


def _invalidate_user_cache(user_id) -> None:
    """知识库内容变更后清空该用户的语义缓存。

    不做这一步的话，用户上传新文档后提问仍会命中"上传前"的缓存答案，
    而且因为走的是缓存命中路径，不会有任何报错——属于静默给出错误答案。
    """
    try:
        removed = cache_purge_user(user_id)
        if removed:
            from ..logging_config import get_logger
            get_logger(__name__).info("semantic_cache_invalidated", user_id=user_id, removed=removed)
    except Exception:
        from ..logging_config import get_logger
        get_logger(__name__).warning("semantic_cache_invalidation_failed", user_id=user_id, exc_info=True)


@router.get("/stats")
def api_stats(current_user: Optional[dict] = Depends(get_optional_user)):
    user_id = current_user["user_id"] if current_user else None
    return get_stats(user_id)


@router.get("/supported-types")
def api_supported_types():
    return {"types": list(SUPPORTED_TYPES.keys())}


@router.post("/upload")
@limiter.limit("30/minute")
async def api_upload(
    request: Request,
    file: UploadFile = File(...),
    current_user: Optional[dict] = Depends(get_optional_user),
):
    if not file.filename:
        raise HTTPException(400, "文件名不能为空")
    if not get_file_type(file.filename):
        raise HTTPException(400, f"不支持的文件类型，支持: {list(SUPPORTED_TYPES.keys())}")

    safe_filename = os.path.basename(file.filename)
    if not safe_filename or safe_filename in (".", ".."):
        raise HTTPException(400, "文件名非法")
    filename = f"{uuid.uuid4().hex}_{safe_filename}"
    filepath = os.path.join(settings.UPLOAD_DIR, filename)

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

    user_id = current_user["user_id"] if current_user else None
    # 切片 → embedding → 写库同样是同步阻塞链路，统一移出事件循环
    count = await asyncio.to_thread(add_documents, chunks, user_id)
    _invalidate_user_cache(user_id)
    return {
        "status": "ok", "filename": safe_filename, "file_type": file_type,
        "char_count": len(text), "chunks": count, "user_scoped": user_id is not None,
        "message": f"已索引 {safe_filename}（{count} 个片段）",
    }


@router.post("/upload-text")
@limiter.limit("30/minute")
async def api_upload_text(
    request: Request,
    text: str = Query(..., description="要索引的文本内容"),
    source: str = Query("manual", description="来源标识"),
    current_user: Optional[dict] = Depends(get_optional_user),
):
    if not text or not text.strip():
        raise HTTPException(400, "文本内容不能为空")
    chunks = await asyncio.to_thread(
        chunk_text, text,
        metadata={"source": source, "file_type": "text", "char_count": len(text)},
    )
    user_id = current_user["user_id"] if current_user else None
    count = await asyncio.to_thread(add_documents, chunks, user_id)
    _invalidate_user_cache(user_id)
    return {"status": "ok", "source": source, "char_count": len(text), "chunks": count, "user_scoped": user_id is not None}


@router.get("/search")
def api_search(
    q: str = Query(..., description="搜索查询"),
    top_k: int = Query(None, description="返回结果数"),
    format: str = Query("json", description="返回格式: json | text"),
    current_user: Optional[dict] = Depends(get_optional_user),
):
    user_id = current_user["user_id"] if current_user else None
    if format == "text":
        return {"results": search_formatted(q, top_k, user_id)}
    return {"query": q, "results": search(q, top_k, user_id)}


@router.delete("/source")
def api_delete_source(
    source: str = Query(..., description="要删除的文档来源名称"),
    current_user: Optional[dict] = Depends(get_optional_user),
):
    user_id = current_user["user_id"] if current_user else None
    delete_by_source(source, user_id)
    _invalidate_user_cache(user_id)
    return {"status": "ok", "source": source, "message": f"已删除 {source} 的索引"}


@router.get("/context")
def api_context(
    q: str = Query(..., description="搜索查询"),
    top_k: int = Query(None, description="返回结果数"),
    current_user: Optional[dict] = Depends(get_optional_user),
):
    user_id = current_user["user_id"] if current_user else None
    return {"context": search_formatted(q, top_k, user_id)}


@router.post("/ask")
@limiter.limit("60/minute")
def api_ask(request: Request, body: dict = Body(...), current_user: Optional[dict] = Depends(get_optional_user)):
    """RAG 完整闭环: 用户问题 → 缓存检查 → 检索 → 模型路由 → LLM 生成 → 带引用返回"""
    question = body.get("question", "").strip()
    if not question:
        raise HTTPException(400, "问题不能为空")

    top_k = body.get("top_k") or settings.rag.retrieval.top_k
    user_id = current_user["user_id"] if current_user else None
    active_version = resolve_active_version(user_id)
    cache_namespace = f"{user_id}:{active_version.collection_name}"

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

    chunks = search(question, top_k, user_id)
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
    result = generate_answer(question, chunks, body.get("history", []), model=user_model, api_key=user_api_key)
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
    current_user: Optional[dict] = Depends(get_optional_user),
):
    """流式 RAG 问答（SSE）"""
    user_id = current_user["user_id"] if current_user else None
    user_api_key = request.headers.get("X-API-Key") or None
    user_model = request.headers.get("X-LLM-Model") or None
    return StreamingResponse(
        stream_ask(q, top_k, user_id=user_id, api_key=user_api_key, model=user_model),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"},
    )
