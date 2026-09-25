"""RAG 生成服务：检索结果 + 用户问题 → LLM → 带引用的答案（非流式）。"""

import json
import time

from ..logging_config import get_logger
from ..llm import (
    get_llm_config,
    get_fallback_llm_config,
    build_chat_call,
    STRICT_RAG_SYSTEM_PROMPT,
    build_context_text,
    build_sources,
    build_strict_rag_user_message,
    call_llm_with_retry,
    LLMCallFailedError,
)

logger = get_logger(__name__)


def generate_answer(question: str, context_chunks: list[dict], history: list[dict] = None, model: str = None, api_key: str = None) -> dict:
    """
    RAG 生成：检索结果 + 用户问题 → LLM → 带引用的答案

    参数:
        model: 指定 LLM 模型名。不传时使用 LLM_MODEL 环境变量默认值。
        api_key: API Key。优先使用此参数，不传（None）时回退到环境变量 LLM_API_KEY。

    返回: { "answer", "sources", "model", "context_count" }
    """
    env_key, base_url, model = get_llm_config(model=model)
    if api_key is None:
        api_key = env_key

    # 构建上下文与来源
    context_text = build_context_text(context_chunks, with_score=True) or "（无检索结果）"
    sources = build_sources(context_chunks)
    user_message = build_strict_rag_user_message(question, context_text)

    # 构建 messages
    messages = [{"role": "system", "content": STRICT_RAG_SYSTEM_PROMPT}]
    if history:
        messages.extend(history[-4:])  # 最近 2 轮对话
    messages.append({"role": "user", "content": user_message})

    # 如果没有 API key，返回检索结果作为 fallback
    if not api_key:
        logger.warning("no_api_key_configured", model=model)
        return {
            "answer": f"（未配置 LLM_API_KEY，以下为检索结果摘要）\n\n根据知识库检索，最相关的内容来自：{', '.join(s['source'] for s in sources)}\n\n{context_chunks[0]['text'] if context_chunks else '无结果'}",
            "sources": sources,
            "model": "fallback (no LLM)",
            "context_count": len(context_chunks),
        }

    # P0-3: 调用 LLM（带重试和熔断保护）
    payload = {
        "model": model,
        "messages": messages,
        "temperature": 0.3,
        "max_tokens": 1000,
    }
    primary_call = build_chat_call(base_url, api_key, payload, timeout=30)

    # 关键修复：fallback 必须用 fallback 模型/Key/端点**重建**请求，
    # 不能复用 primary_call（旧实现在这里复用了同一个 req，降级完全无效）。
    fallback_call = None
    fallback_model = None
    fb = get_fallback_llm_config()
    if fb:
        fb_key, fb_url, fallback_model = fb
        fallback_call = build_chat_call(
            fb_url, fb_key, {**payload, "model": fallback_model}, timeout=30,
        )

    start_time = time.monotonic()
    try:
        result = call_llm_with_retry(
            call_fn=primary_call,
            fallback_call_fn=fallback_call,
            model_name=model,
            fallback_model=fallback_model,
        )
        elapsed_ms = int((time.monotonic() - start_time) * 1000)
        resp = json.loads(result["data"].read())
        answer = resp["choices"][0]["message"]["content"]
        usage = resp.get("usage", {})

        logger.info(
            "rag_generate_success",
            model=result["model_used"],
            latency_ms=elapsed_ms,
            prompt_tokens=usage.get("prompt_tokens", 0),
            completion_tokens=usage.get("completion_tokens", 0),
            context_count=len(context_chunks),
        )

        return {
            "answer": answer,
            "sources": sources,
            "model": result["model_used"],
            "context_count": len(context_chunks),
        }
    except LLMCallFailedError as e:
        logger.error("rag_generate_failed", error=str(e)[:200], model=model, context_count=len(context_chunks))
        return {
            "answer": f"LLM 调用失败: {str(e)}\n\n以下为检索结果：\n{context_chunks[0]['text'] if context_chunks else '无结果'}",
            "sources": sources,
            "model": f"error: {model}",
            "context_count": len(context_chunks),
        }
