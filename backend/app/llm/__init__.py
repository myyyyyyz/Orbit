"""公共 LLM 客户端层 — 配置解析、请求构造、Prompt 构建、重试/熔断。

供 generate/（非流式）与 stream/（流式）复用，消除两处重复的
模型名→URL 映射、HTTP 请求构造与 RAG Prompt 拼装逻辑。
"""
from .client import (
    get_llm_config,
    get_fallback_llm_config,
    resolve_api_key,
    build_chat_request,
    build_chat_call,
    default_base_url_for,
    DEFAULT_LLM_MODEL,
    DEFAULT_LLM_BASE_URL,
)
from .prompts import (
    STRICT_RAG_SYSTEM_PROMPT,
    LENIENT_RAG_SYSTEM_PROMPT,
    CHAT_SYSTEM_PROMPT,
    build_context_text,
    build_sources,
    build_rag_user_message,
    build_strict_rag_user_message,
)
# P0-3: LLM 调用重试与熔断
from .retry import (
    call_llm_with_retry,
    LLMCallFailedError,
    LLM_PRIMARY_MODEL,
    LLM_FALLBACK_MODEL,
)

__all__ = [
    "get_llm_config",
    "get_fallback_llm_config",
    "resolve_api_key",
    "build_chat_request",
    "build_chat_call",
    "default_base_url_for",
    "DEFAULT_LLM_MODEL",
    "DEFAULT_LLM_BASE_URL",
    "STRICT_RAG_SYSTEM_PROMPT",
    "LENIENT_RAG_SYSTEM_PROMPT",
    "CHAT_SYSTEM_PROMPT",
    "build_context_text",
    "build_sources",
    "build_rag_user_message",
    "build_strict_rag_user_message",
    # P0-3: 重试与熔断
    "call_llm_with_retry",
    "LLMCallFailedError",
    "LLM_PRIMARY_MODEL",
    "LLM_FALLBACK_MODEL",
]
