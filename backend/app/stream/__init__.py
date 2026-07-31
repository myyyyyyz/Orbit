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

# 相关度阈值：cosine 相似度低于此值的检索结果视为与问题无关（如闲聊匹配到文档）
MIN_RELEVANCE_SCORE = 0.3


def stream_ask(question: str, top_k: int = None, user_id: int = None, api_key: str = None, model: str = None):
    """
    流式 RAG 问答生成器。
    yield SSE 格式的数据。

    参数:
        user_id: 可选，已登录用户的 ID，用于租户隔离检索。
        api_key: 前端传入的 LLM API Key，优先于环境变量。
        model: 前端传入的模型名，优先于路由器默认模型。
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

    # ── Event 3: 检索（含相关度过滤）──
    yield _sse("status", {"stage": "retrieving", "top_k": top_k})
    chunks = [c for c in search(question, top_k, user_id) if c["score"] >= MIN_RELEVANCE_SCORE]

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
    if not api_key:
        api_key = os.getenv("LLM_API_KEY", "")
    # 模型优先级：前端指定 > 路由器选择 > 环境变量默认
    model_name = model or route.model or os.getenv("LLM_MODEL", "gpt-4o-mini")
    if "deepseek" in model_name.lower():
        default_url = "https://api.deepseek.com/v1/chat/completions"
    elif "claude" in model_name.lower():
        default_url = "https://api.anthropic.com/v1/messages"
    else:
        default_url = "https://api.openai.com/v1/chat/completions"
    base_url = os.getenv("LLM_BASE_URL", default_url)

    sources = [{"source": c["metadata"].get("source", "?"), "score": c["score"], "preview": c["text"][:80]} for c in chunks]

    if not api_key:
        # Fallback: 无 LLM 时返回检索结果
        if chunks:
            fallback_text = f"（未配置 LLM_API_KEY）\n\n最相关内容来自：{sources[0]['source']}\n\n{chunks[0]['text']}"
        else:
            fallback_text = "（未配置 LLM_API_KEY，且问题与知识库无关。请在设置中配置模型的 API Key。）"
        yield _sse("answer", {"text": fallback_text, "sources": sources, "model": "fallback"})
        yield _sse("done", {"model": "fallback", "retrieval_count": len(chunks)})
        return

    # 构建 LLM 请求：有相关检索结果走 RAG 模式，否则走纯对话模式
    if chunks:
        context_parts = []
        for i, chunk in enumerate(chunks, 1):
            source = chunk["metadata"].get("source", "未知")
            context_parts.append(f"【检索结果 {i}】（来源: {source}）\n{chunk['text']}")

        context_text = "\n\n---\n\n".join(context_parts)

        system_prompt = """你是一个知识库问答助手。根据检索结果回答用户问题。
规则：
1. 优先根据检索结果回答，不要编造
2. 只有检索结果确实与问题相关时才引用来源，格式：【来源: xxx】
3. 如果问题是打招呼、闲聊，或与检索内容无关，自然友好地回答，不要强行引用来源
4. 回答简洁准确，用中文"""

        user_message = f"## 检索结果\n\n{context_text}\n\n---\n\n## 问题\n\n{question}"
    else:
        system_prompt = "你是一个友好的 AI 助手，简洁自然地回答用户的问题。"
        user_message = question

    payload = json.dumps({
        "model": model_name,
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
        cache_put(question, full_answer, sources, model_name)

        yield _sse("sources", {"sources": sources})
        yield _sse("done", {
            "model": model_name,
            "retrieval_count": len(chunks),
            "cached": False,
            "answer_length": len(full_answer),
        })

    except Exception as e:
        yield _sse("error", {"message": str(e)})
        yield _sse("done", {"model": model_name, "error": True})


def _sse(event: str, data: dict) -> str:
    """格式化为 SSE 事件"""
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"
