"""
流式输出模块

SSE (Server-Sent Events) 流式返回 RAG 问答结果。
用户看到的是逐步生成的答案，而非等待完整结果。
"""

import json
import urllib.request
import os
from fastapi.responses import StreamingResponse
from ..config import settings
from ..search import search
from ..router import route_model
from ..cache import get as cache_get, put as cache_put
from ..embed import encode


def stream_ask(question: str, top_k: int = None, user_id: int = None):
    """
    流式 RAG 问答生成器。
    yield SSE 格式的数据。

    参数:
        user_id: 可选，已登录用户的 ID，用于租户隔离检索。
    """
    if top_k is None:
        top_k = settings.rag.retrieval.top_k

    # ── Event 1: 开始 ──
    yield _sse("status", {"stage": "start", "question": question})

    # ── Event 2: 检查缓存 ──
    cached = cache_get(question)
    if cached:
        yield _sse("status", {
            "stage": "cache_hit",
            "score": cached.get("cache_hit_score", 0),
        })
        yield _sse("answer", {"text": cached["answer"], "sources": cached["sources"], "model": "cache"})
        yield _sse("done", {"model": "cache", "cached": True})
        return

    yield _sse("status", {"stage": "cache_miss"})

    # ── Event 3: 检索 ──
    yield _sse("status", {"stage": "retrieving", "top_k": top_k})
    chunks = search(question, top_k, user_id)

    if not chunks:
        yield _sse("answer", {"text": "知识库中未找到相关内容。", "sources": [], "model": "none"})
        yield _sse("done", {"model": "none", "retrieval_count": 0})
        return

    yield _sse("status", {
        "stage": "retrieved",
        "count": len(chunks),
        "top_score": round(chunks[0]["score"], 4) if chunks else 0,
    })

    # ── Event 4: 模型路由 ──
    scores = [c["score"] for c in chunks]
    route = route_model(question, scores)
    yield _sse("status", {
        "stage": "routing",
        "tier": route.tier,
        "model": route.model,
        "reason": route.reason,
        "confidence": route.confidence,
        "needs_clarification": route.needs_clarification,
    })

    # ── Event 5: 生成（流式）──
    api_key = os.getenv("LLM_API_KEY", "")
    base_url = os.getenv("LLM_BASE_URL", "https://api.openai.com/v1/chat/completions")

    sources = [{"source": c["metadata"].get("source", "?"), "score": c["score"], "preview": c["text"][:80]} for c in chunks]

    if not api_key:
        # Fallback: 无 LLM 时返回检索结果
        fallback_text = f"（未配置 LLM_API_KEY）\n\n最相关内容来自：{sources[0]['source']}\n\n{chunks[0]['text']}"
        yield _sse("answer", {"text": fallback_text, "sources": sources, "model": "fallback"})
        yield _sse("done", {"model": "fallback", "retrieval_count": len(chunks)})
        return

    # 构建 LLM 请求
    context_parts = []
    for i, chunk in enumerate(chunks, 1):
        source = chunk["metadata"].get("source", "未知")
        context_parts.append(f"【检索结果 {i}】（来源: {source}）\n{chunk['text']}")

    context_text = "\n\n---\n\n".join(context_parts)

    system_prompt = """你是一个知识库问答助手。根据检索结果回答用户问题。
只根据检索结果回答，不编造。引用来源格式：【来源: {source}】。
如果检索结果中没有相关信息，说"知识库中未找到相关内容"。"""

    user_message = f"## 检索结果\n\n{context_text}\n\n---\n\n## 问题\n\n{question}"

    payload = json.dumps({
        "model": route.model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ],
        "temperature": route.temperature,
        "max_tokens": route.max_tokens,
        "stream": True,  # 启用流式
    }).encode()

    req = urllib.request.Request(
        base_url,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )

    full_answer = ""
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            for line in resp:
                line = line.decode("utf-8").strip()
                if not line or not line.startswith("data: "):
                    continue
                data = line[6:]
                if data == "[DONE]":
                    break
                try:
                    chunk_data = json.loads(data)
                    delta = chunk_data.get("choices", [{}])[0].get("delta", {})
                    token = delta.get("content", "")
                    if token:
                        full_answer += token
                        yield _sse("token", {"text": token})
                except json.JSONDecodeError:
                    continue

        # 存入缓存
        cache_put(question, full_answer, sources, route.model)

        yield _sse("sources", {"sources": sources})
        yield _sse("done", {
            "model": route.model,
            "retrieval_count": len(chunks),
            "cached": False,
            "answer_length": len(full_answer),
        })

    except Exception as e:
        yield _sse("error", {"message": str(e)})
        yield _sse("done", {"model": route.model, "error": True})


def _sse(event: str, data: dict) -> str:
    """格式化为 SSE 事件"""
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"
