"""LLM API 配置解析与 HTTP 请求构造（OpenAI 兼容协议）。"""

import json
import os
import urllib.request

# ── 默认值唯一事实源 ───────────────────────────────────────────
# 历史缺陷：compose / .env.example / retry.py / client.py 四处默认模型各不相同
# （deepseek-chat / deepseek-v4-pro / gpt-4o-mini），导致"本地能跑、容器里换了个模型"。
# 此处统一为常量，其他模块一律引用，不再各自写死字面量。
DEFAULT_LLM_MODEL = "deepseek-chat"
DEFAULT_LLM_BASE_URL = "https://api.deepseek.com/v1/chat/completions"


def default_base_url_for(model: str) -> str:
    """按模型名推断 API 地址（仅在未显式配置 LLM_BASE_URL 时作为兜底）。"""
    name = (model or "").lower()
    if "deepseek" in name:
        return "https://api.deepseek.com/v1/chat/completions"
    if "claude" in name:
        return "https://api.anthropic.com/v1/messages"
    if "qwen" in name or "dashscope" in name:
        return "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"
    return "https://api.openai.com/v1/chat/completions"


def get_llm_config(model: str = None):
    """从环境变量读取 LLM 配置，根据模型名自动选择 API 地址。

    返回: (api_key, base_url, model)
    """
    api_key = os.getenv("LLM_API_KEY", "")
    model = model or os.getenv("LLM_MODEL") or DEFAULT_LLM_MODEL
    base_url = os.getenv("LLM_BASE_URL") or default_base_url_for(model)
    return api_key, base_url, model


def get_fallback_llm_config():
    """解析 Fallback 模型配置，未配置时返回 None。

    返回: (api_key, base_url, model) 或 None

    独立于主模型解析——这是 Fallback 能"真正切换模型"的前提：
    调用方用它重建请求，而不是复用主模型已经构造好的 request。
    """
    model = (os.getenv("LLM_FALLBACK_MODEL") or "").strip()
    if not model:
        return None
    api_key = (os.getenv("LLM_FALLBACK_API_KEY") or "").strip() or os.getenv("LLM_API_KEY", "")
    # 优先用 fallback 专属 base_url；否则按模型名推断（不能再套用主模型的 LLM_BASE_URL，
    # 否则跨厂商 fallback 会把请求发到主模型端点）
    base_url = os.getenv("LLM_FALLBACK_BASE_URL") or default_base_url_for(model)
    return api_key, base_url, model


def resolve_api_key(api_key: str = None) -> str:
    """优先使用传入的 api_key，为空（None 或空字符串）时回退到环境变量 LLM_API_KEY。"""
    return api_key or os.getenv("LLM_API_KEY", "")


def build_chat_request(base_url: str, api_key: str, payload: dict) -> urllib.request.Request:
    """构造 OpenAI 兼容的 chat/completions POST 请求。"""
    return urllib.request.Request(
        base_url,
        data=json.dumps(payload).encode(),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )


def build_chat_call(base_url: str, api_key: str, payload: dict, timeout: int = 30):
    """构造"可直接调用"的请求闭包（供 call_llm_with_retry 使用）。

    返回一个无参 callable，每次调用都复用同一 Request 对象。
    """
    req = build_chat_request(base_url, api_key, payload)

    def _call():
        return urllib.request.urlopen(req, timeout=timeout)

    return _call
