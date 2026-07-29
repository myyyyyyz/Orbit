import os
import uuid
import json
import urllib.request
from typing import Optional, Any
import copy
from fastapi import FastAPI, UploadFile, File, HTTPException, Query, Body
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from .config import settings, RAGStrategy
from .ingest import parse_file, get_file_type, SUPPORTED_TYPES
from .chunk import chunk_text
from .store import add_documents, delete_by_source, get_stats
from .search import search, search_formatted
from .generate import generate_answer
from .router import route_model, detect_intent, MODEL_PRESETS
from .cache import get as cache_get, put as cache_put, stats as cache_stats, clear as cache_clear
from .stream import stream_ask
from .storage_router import route_storage, get_strategy_info, detect_content_type
from .multitenant import register_user, login_user, get_user_by_id, get_user_collection, save_session, get_session, get_latest_session, init_db as init_tenant_db
from .memory import init_memory_db, save_user_profile, get_user_profile, save_project_context, get_latest_project, save_conversation_summary, get_recent_summaries, restore_context
from .onboarding import get_onboarding_template, get_role_config, get_all_roles

app = FastAPI(
    title="Knowledge Base Service",
    description="知识库服务 — 文档上传、向量化、语义检索",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health():
    return {"status": "ok", "service": "knowledge-base"}


@app.get("/api/knowledge/stats")
def api_stats():
    """获取知识库统计"""
    return get_stats()


@app.get("/api/knowledge/supported-types")
def api_supported_types():
    """列出支持的文件类型"""
    return {"types": list(SUPPORTED_TYPES.keys())}


@app.post("/api/knowledge/upload")
async def api_upload(file: UploadFile = File(...)):
    """上传并索引文档"""
    # 验证文件类型
    if not file.filename:
        raise HTTPException(400, "文件名不能为空")
    if not get_file_type(file.filename):
        raise HTTPException(400, f"不支持的文件类型，支持: {list(SUPPORTED_TYPES.keys())}")

    # 保存文件
    filename = f"{uuid.uuid4().hex}_{file.filename}"
    filepath = os.path.join(settings.UPLOAD_DIR, filename)

    content = await file.read()
    if len(content) > settings.MAX_FILE_SIZE:
        raise HTTPException(400, f"文件超过 {settings.MAX_FILE_SIZE // 1024 // 1024}MB 限制")

    with open(filepath, "wb") as f:
        f.write(content)

    # 解析文件
    try:
        text, file_type = parse_file(filepath)
    except Exception as e:
        raise HTTPException(500, f"文件解析失败: {str(e)}")

    if not text or not text.strip():
        raise HTTPException(400, "文件内容为空")

    # 切割
    chunks = chunk_text(text, metadata={
        "source": file.filename,
        "file_type": file_type,
        "char_count": len(text),
    })

    if not chunks:
        raise HTTPException(500, "文本切割失败")

    # 入库
    count = add_documents(chunks)

    return {
        "status": "ok",
        "filename": file.filename,
        "file_type": file_type,
        "char_count": len(text),
        "chunks": count,
        "message": f"已索引 {file.filename}（{count} 个片段）",
    }


@app.post("/api/knowledge/upload-text")
async def api_upload_text(
    text: str = Query(..., description="要索引的文本内容"),
    source: str = Query("manual", description="来源标识"),
):
    """直接上传文本内容进行索引"""
    if not text or not text.strip():
        raise HTTPException(400, "文本内容不能为空")

    chunks = chunk_text(text, metadata={
        "source": source,
        "file_type": "text",
        "char_count": len(text),
    })

    count = add_documents(chunks)
    return {
        "status": "ok",
        "source": source,
        "char_count": len(text),
        "chunks": count,
        "message": f"已索引（{count} 个片段）",
    }


@app.get("/api/knowledge/search")
def api_search(
    q: str = Query(..., description="搜索查询"),
    top_k: int = Query(None, description="返回结果数"),
    format: str = Query("json", description="返回格式: json | text"),
):
    """语义搜索知识库"""
    if format == "text":
        return {"results": search_formatted(q, top_k)}
    return {"query": q, "results": search(q, top_k)}


@app.delete("/api/knowledge/source")
def api_delete_source(source: str = Query(..., description="要删除的文档来源名称")):
    """删除指定来源的所有索引"""
    delete_by_source(source)
    return {"status": "ok", "source": source, "message": f"已删除 {source} 的索引"}


@app.get("/api/knowledge/context")
def api_context(
    q: str = Query(..., description="搜索查询"),
    top_k: int = Query(None, description="返回结果数"),
):
    """
    获取格式化的知识库上下文，可直接注入 Agent。
    这是 Agent Loop 的主要接口。
    """
    return {"context": search_formatted(q, top_k)}


# ================================================================
# RAG 问答端点（检索 + 生成）
# ================================================================

@app.post("/api/knowledge/ask")
def api_ask(body: dict = Body(...)):
    """
    RAG 完整闭环：用户问题 → 缓存检查 → 检索 → 模型路由 → LLM 生成 → 带引用返回

    P3 增强：
    - 语义缓存（相似查询直接返回）
    - 模型路由（简单→快模型，复杂→强模型）
    """
    question = body.get("question", "").strip()
    if not question:
        raise HTTPException(400, "问题不能为空")

    top_k = body.get("top_k") or settings.rag.retrieval.top_k

    # ── P3: 语义缓存检查 ──
    cached = cache_get(question)
    if cached:
        return {
            "question": question,
            "answer": cached["answer"],
            "sources": cached["sources"],
            "model": "cache",
            "retrieval_count": len(cached["sources"]),
            "cache_hit": True,
            "cache_hit_score": cached.get("cache_hit_score", 0),
        }

    # ── 检索 ──
    chunks = search(question, top_k)
    if not chunks:
        return {
            "question": question,
            "answer": "知识库中未找到相关内容。请先上传相关文档。",
            "sources": [],
            "model": "none",
            "retrieval_count": 0,
            "cache_hit": False,
        }

    # ── P3: 模型路由 ──
    scores = [c["score"] for c in chunks]
    route = route_model(question, scores)

    # ── 生成（使用路由选择的模型）──
    # 临时覆盖 LLM 模型
    original_model = os.getenv("LLM_MODEL", "")
    os.environ["LLM_MODEL"] = route["model"]

    result = generate_answer(question, chunks, body.get("history", []))

    # 恢复
    if original_model:
        os.environ["LLM_MODEL"] = original_model

    # ── P3: 存入缓存 ──
    cache_put(question, result["answer"], result["sources"], result["model"])

    return {
        "question": question,
        "answer": result["answer"],
        "sources": result["sources"],
        "model": result["model"],
        "retrieval_count": result["context_count"],
        "cache_hit": False,
        "router_tier": route["tier"],
        "router_reason": route["reason"],
    }


# ================================================================
# P3: 流式输出端点
# ================================================================

@app.get("/api/knowledge/ask/stream")
def api_ask_stream(
    q: str = Query(..., description="用户问题"),
    top_k: int = Query(None, description="检索结果数"),
):
    """
    流式 RAG 问答（SSE）。

    事件流:
    - status: start / cache_hit / cache_miss / retrieving / retrieved / routing
    - token: LLM 生成的 token（逐步返回）
    - answer: 完整答案（fallback 模式）
    - sources: 引用来源
    - done: 完成
    - error: 错误
    """
    return StreamingResponse(
        stream_ask(q, top_k),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# ================================================================
# P3: 缓存管理端点
# ================================================================

@app.get("/api/knowledge/cache/stats")
def api_cache_stats():
    """缓存统计"""
    return cache_stats()


@app.delete("/api/knowledge/cache")
def api_cache_clear():
    """清空缓存"""
    cache_clear()
    return {"status": "ok", "message": "缓存已清空"}


# ================================================================
# P3: 模型路由端点
# ================================================================

@app.get("/api/knowledge/router/models")
def api_router_models():
    """查看模型路由预设"""
    return MODEL_PRESETS


@app.post("/api/knowledge/router/predict")
def api_router_predict(body: dict = Body(...)):
    """预测给定查询会路由到哪个模型"""
    query = body.get("query", "")
    if not query:
        raise HTTPException(400, "查询不能为空")
    intent = detect_intent(query)
    route = route_model(query)
    return {
        "query": query,
        "intent": intent,
        "tier": route["tier"],
        "model": route["model"],
        "reason": route["reason"],
    }


# ================================================================
# Logos 对话总结端点
# ================================================================

@app.post("/api/knowledge/logos")
def api_logos_summarize(body: dict = Body(...)):
    """
    对话结束后触发 Logos 总结，写入 your-memory/YYYY-MM-DD.md

    请求体:
    {
        "conversation": "对话内容摘要",
        "start_time": "10:30",  // 可选
    }
    """
    from datetime import datetime
    import pathlib

    conversation = body.get("conversation", "").strip()
    if not conversation:
        raise HTTPException(400, "对话内容不能为空")

    start_time = body.get("start_time", datetime.now().strftime("%H:%M"))

    # 生成总结（如果有 LLM）
    api_key = os.getenv("LLM_API_KEY", "")
    if api_key:
        from .generate import _get_llm_config
        _, base_url, model = _get_llm_config()

        system_prompt = """你是 Logos 记忆管家。请将以下对话总结为结构化笔记，重点记录：
1. 做了什么（任务概述）
2. 关键决策（技术选型、方案取舍）
3. 遇到的问题和解决方案
4. 灵感与收获
5. 待办事项

用 Markdown 格式输出，简洁有力。"""

        payload = json.dumps({
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": conversation},
            ],
            "temperature": 0.3,
            "max_tokens": 800,
        }).encode()

        req = urllib.request.Request(
            base_url,
            data=payload,
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                result = json.loads(resp.read())
                summary = result["choices"][0]["message"]["content"]
        except:
            summary = f"### 对话总结（LLM 不可用，原始记录）\n\n{conversation[:500]}"
    else:
        summary = f"### 对话总结（无 LLM，原始记录）\n\n{conversation[:500]}"

    # 写入 your-memory/YYYY-MM-DD.md
    memory_dir = pathlib.Path(settings.UPLOAD_DIR).parent / "your-memory"
    memory_dir.mkdir(parents=True, exist_ok=True)

    today = datetime.now().strftime("%Y-%m-%d")
    now = datetime.now().strftime("%H:%M:%S")
    memory_file = memory_dir / f"{today}.md"

    header = f"### {start_time} ~ {now[:5]} | 第 1 次对话\n\n"

    if memory_file.exists():
        # 追加
        with open(memory_file, "r", encoding="utf-8") as f:
            existing = f.read()
        # 递增对话编号
        import re
        count = len(re.findall(r"第 \d+ 次对话", existing)) + 1
        header = f"### {start_time} ~ {now[:5]} | 第 {count} 次对话\n\n"
        with open(memory_file, "a", encoding="utf-8") as f:
            f.write("\n---\n\n" + header + summary + "\n")
    else:
        with open(memory_file, "w", encoding="utf-8") as f:
            f.write(f"# 知识库对话记录 — {today}\n\n")
            f.write(header + summary + "\n")

    return {
        "status": "ok",
        "file": str(memory_file),
        "summary_length": len(summary),
        "message": f"已写入 {memory_file.name}",
    }


# ================================================================
# RAG 策略管理 API
# ================================================================

def _strategy_to_dict() -> dict:
    """将当前 RAG 策略序列化为字典"""
    s = settings.rag
    return {
        "version": s.version,
        "chunk": {
            "method": s.chunk.method,
            "size": s.chunk.size,
            "overlap": s.chunk.overlap,
            "parent_child_enabled": s.chunk.parent_child_enabled,
            "parent_size": s.chunk.parent_size,
            "min_size": s.chunk.min_size,
            "table_preserve": s.chunk.table_preserve,
        },
        "embed": {
            "backend": s.embed.backend,
            "model": s.embed.model,
            "normalize": s.embed.normalize,
            "ollama_host": s.embed.ollama_host,
        },
        "storage": {
            "distance_metric": s.storage.distance_metric,
            "hnsw_M": s.storage.hnsw_M,
            "hnsw_ef_construction": s.storage.hnsw_ef_construction,
            "hnsw_ef_search": s.storage.hnsw_ef_search,
            "collection": s.storage.collection,
        },
        "retrieval": {
            "method": s.retrieval.method,
            "bm25_weight": s.retrieval.bm25_weight,
            "rerank_enabled": s.retrieval.rerank_enabled,
            "query_rewrite_enabled": s.retrieval.query_rewrite_enabled,
            "top_k": s.retrieval.top_k,
            "multi_hop_enabled": s.retrieval.multi_hop_enabled,
            "score_threshold": s.retrieval.score_threshold,
            "dedup": s.retrieval.dedup,
        },
    }


def _apply_strategy_patch(strategy: RAGStrategy, patch: dict):
    """将 patch dict 应用到 strategy 对象"""
    if "chunk" in patch:
        c = patch["chunk"]
        if "method" in c and c["method"] in ("semantic", "fixed_size"):
            strategy.chunk.method = c["method"]
        if "size" in c and isinstance(c["size"], int) and 100 <= c["size"] <= 5000:
            strategy.chunk.size = c["size"]
        if "overlap" in c and isinstance(c["overlap"], int) and 0 <= c["overlap"] <= 1000:
            strategy.chunk.overlap = c["overlap"]
        if "parent_child_enabled" in c and isinstance(c["parent_child_enabled"], bool):
            strategy.chunk.parent_child_enabled = c["parent_child_enabled"]
        if "parent_size" in c and isinstance(c["parent_size"], int):
            strategy.chunk.parent_size = c["parent_size"]
        if "min_size" in c and isinstance(c["min_size"], int):
            strategy.chunk.min_size = c["min_size"]
        if "table_preserve" in c and isinstance(c["table_preserve"], bool):
            strategy.chunk.table_preserve = c["table_preserve"]

    if "embed" in patch:
        e = patch["embed"]
        if "backend" in e and e["backend"] in ("sentence-transformers", "ollama", "openai"):
            strategy.embed.backend = e["backend"]
        if "model" in e and isinstance(e["model"], str):
            strategy.embed.model = e["model"]
        if "normalize" in e and isinstance(e["normalize"], bool):
            strategy.embed.normalize = e["normalize"]
        if "ollama_host" in e and isinstance(e["ollama_host"], str):
            strategy.embed.ollama_host = e["ollama_host"]

    if "storage" in patch:
        st = patch["storage"]
        if "distance_metric" in st and st["distance_metric"] in ("cosine", "l2", "ip"):
            strategy.storage.distance_metric = st["distance_metric"]
        if "hnsw_M" in st and isinstance(st["hnsw_M"], int):
            strategy.storage.hnsw_M = st["hnsw_M"]
        if "hnsw_ef_construction" in st and isinstance(st["hnsw_ef_construction"], int):
            strategy.storage.hnsw_ef_construction = st["hnsw_ef_construction"]
        if "hnsw_ef_search" in st and isinstance(st["hnsw_ef_search"], int):
            strategy.storage.hnsw_ef_search = st["hnsw_ef_search"]

    if "retrieval" in patch:
        r = patch["retrieval"]
        if "method" in r and r["method"] in ("vector", "hybrid", "parent_child"):
            strategy.retrieval.method = r["method"]
        if "bm25_weight" in r and isinstance(r["bm25_weight"], (int, float)):
            strategy.retrieval.bm25_weight = max(0.0, min(1.0, r["bm25_weight"]))
        if "rerank_enabled" in r and isinstance(r["rerank_enabled"], bool):
            strategy.retrieval.rerank_enabled = r["rerank_enabled"]
        if "query_rewrite_enabled" in r and isinstance(r["query_rewrite_enabled"], bool):
            strategy.retrieval.query_rewrite_enabled = r["query_rewrite_enabled"]
        if "top_k" in r and isinstance(r["top_k"], int) and 1 <= r["top_k"] <= 100:
            strategy.retrieval.top_k = r["top_k"]
        if "multi_hop_enabled" in r and isinstance(r["multi_hop_enabled"], bool):
            strategy.retrieval.multi_hop_enabled = r["multi_hop_enabled"]
        if "score_threshold" in r and isinstance(r["score_threshold"], (int, float)):
            strategy.retrieval.score_threshold = max(0.0, min(1.0, r["score_threshold"]))
        if "dedup" in r and r["dedup"] in ("none", "exact", "near"):
            strategy.retrieval.dedup = r["dedup"]


@app.get("/api/knowledge/strategy")
def api_get_strategy():
    """获取当前 RAG 策略（完整所有参数 + 默认值说明）"""
    s = _strategy_to_dict()
    s["_defaults_note"] = "所有字段均有默认值。PATCH /api/knowledge/strategy 可部分更新。embed 大类变更需用户确认。"
    s["_readonly"] = ["version"]
    s["_auto_apply_fields"] = [
        "retrieval.*",           # 检索参数全部可自动调整
        "chunk.method",
        "chunk.overlap",
        "chunk.min_size",
        "storage.hnsw_ef_search",
    ]
    s["_requires_confirm_fields"] = [
        "embed.*",               # 换模型需确认
        "chunk.size",            # 改大小需重新索引
        "chunk.parent_child_enabled",  # 改父子 chunk 需重新索引
        "storage.distance_metric",     # 改度量需重建索引
    ]
    return s


@app.patch("/api/knowledge/strategy")
def api_patch_strategy(patch: dict = Body(...)):
    """部分更新 RAG 策略。仅传需要改的字段。"""
    before = copy.deepcopy(_strategy_to_dict())

    try:
        _apply_strategy_patch(settings.rag, patch)
    except Exception as e:
        raise HTTPException(400, f"策略更新失败: {str(e)}")

    # 更新版本号
    from datetime import datetime
    settings.rag.version = datetime.now().strftime("%Y%m%d") + "-" + \
        str(int(settings.rag.version.split("-")[-1]) + 1).zfill(2)

    after = _strategy_to_dict()

    return {
        "status": "ok",
        "version": settings.rag.version,
        "changes": _diff_strategy(before, after),
    }


def _diff_strategy(before: dict, after: dict) -> list[dict]:
    """对比策略变更"""
    changes = []

    def _compare_section(section: str, b: dict, a: dict):
        for key in b:
            if key in a and b[key] != a[key]:
                changes.append({
                    "field": f"{section}.{key}",
                    "before": b[key],
                    "after": a[key],
                })

    _compare_section("chunk", before["chunk"], after["chunk"])
    _compare_section("embed", before["embed"], after["embed"])
    _compare_section("storage", before["storage"], after["storage"])
    _compare_section("retrieval", before["retrieval"], after["retrieval"])
    return changes


# ================================================================
# P4: 混合存储路由 API
# ================================================================

@app.get("/api/storage/strategies")
def api_storage_strategies():
    """获取所有存储策略"""
    return get_strategy_info()


@app.post("/api/storage/analyze")
def api_storage_analyze(body: dict = Body(...)):
    """
    分析文件，推荐存储策略。
    请求: {"filename": "合同.pdf", "text": "文件内容（可选）", "file_size": 1024}
    """
    filename = body.get("filename", "")
    text = body.get("text", "")
    file_size = body.get("file_size", 0)

    if not filename:
        raise HTTPException(400, "文件名不能为空")

    result = route_storage(filename, text, file_size)
    return result


# ================================================================
# P4: 多用户/企业隔离 API
# ================================================================

@app.post("/api/auth/register")
def api_register(body: dict = Body(...)):
    """注册用户（多租户）"""
    username = body.get("username", "").strip()
    password = body.get("password", "").strip()
    tenant_id = body.get("tenant_id")

    if not username or not password:
        raise HTTPException(400, "用户名和密码不能为空")

    result = register_user(username, password, tenant_id)
    if "error" in result:
        raise HTTPException(400, result["error"])
    return result


@app.post("/api/auth/login")
def api_login(body: dict = Body(...)):
    """登录（多租户）"""
    username = body.get("username", "").strip()
    password = body.get("password", "").strip()

    if not username or not password:
        raise HTTPException(400, "用户名和密码不能为空")

    result = login_user(username, password)
    if not result:
        raise HTTPException(401, "用户名或密码错误")
    return result


@app.get("/api/auth/me/{user_id}")
def api_me(user_id: int):
    """获取用户信息"""
    user = get_user_by_id(user_id)
    if not user:
        raise HTTPException(404, "用户不存在")
    return {
        "user_id": user["id"],
        "username": user["username"],
        "role": user["role"],
        "tenant_id": user["tenant_id"],
        "collection_name": get_user_collection(user_id),
    }


# ================================================================
# P4: 长期记忆 API
# ================================================================

@app.post("/api/memory/profile")
def api_save_profile(body: dict = Body(...)):
    """保存用户画像"""
    user_id = body.get("user_id")
    if not user_id:
        raise HTTPException(400, "user_id 不能为空")
    save_user_profile(
        user_id,
        role=body.get("role"),
        preferences=body.get("preferences"),
        common_skills=body.get("common_skills"),
        output_style=body.get("output_style"),
    )
    return {"status": "ok", "message": "用户画像已保存"}


@app.get("/api/memory/profile/{user_id}")
def api_get_profile(user_id: int):
    """获取用户画像"""
    profile = get_user_profile(user_id)
    if not profile:
        raise HTTPException(404, "用户画像不存在")
    return profile


@app.post("/api/memory/project")
def api_save_project(body: dict = Body(...)):
    """保存项目上下文"""
    user_id = body.get("user_id")
    project_name = body.get("project_name")
    if not user_id or not project_name:
        raise HTTPException(400, "user_id 和 project_name 不能为空")
    save_project_context(
        user_id,
        project_name,
        tech_stack=body.get("tech_stack"),
        current_progress=body.get("current_progress"),
        key_decisions=body.get("key_decisions"),
    )
    return {"status": "ok", "message": "项目上下文已保存"}


@app.post("/api/memory/summary")
def api_save_summary(body: dict = Body(...)):
    """保存对话摘要"""
    user_id = body.get("user_id")
    summary = body.get("summary")
    if not user_id or not summary:
        raise HTTPException(400, "user_id 和 summary 不能为空")
    save_conversation_summary(user_id, summary, body.get("key_points"))
    return {"status": "ok", "message": "对话摘要已保存"}


@app.get("/api/memory/restore/{user_id}")
def api_restore_context(user_id: int):
    """
    跨会话上下文恢复。
    用户打开聊天时调用，返回完整的上下文快照。
    """
    return restore_context(user_id)


# ================================================================
# P4: 新手引导 API
# ================================================================

@app.get("/api/onboarding/template")
def api_onboarding_template():
    """获取新手引导模板（首次使用时展示）"""
    return get_onboarding_template()


@app.get("/api/onboarding/roles")
def api_onboarding_roles():
    """获取所有角色列表"""
    return get_all_roles()


@app.get("/api/onboarding/roles/{role}")
def api_onboarding_role_config(role: str):
    """获取指定角色的完整配置（含推荐 Skill、偏好、快捷操作）"""
    config = get_role_config(role)
    if not config:
        raise HTTPException(404, f"角色不存在: {role}")
    return config
