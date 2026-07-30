"""LLM 生成模块 — 把检索结果 + 用户问题发给 LLM 生成答案"""

import os
import json
import urllib.request
from ..config import settings


def _get_llm_config():
    """从环境变量读取 LLM 配置"""
    api_key = os.getenv("LLM_API_KEY", "")
    base_url = os.getenv("LLM_BASE_URL", "https://api.openai.com/v1/chat/completions")
    model = os.getenv("LLM_MODEL", "gpt-4o-mini")
    return api_key, base_url, model


def generate_answer(question: str, context_chunks: list[dict], history: list[dict] = None, model: str = None) -> dict:
    """
    RAG 生成：检索结果 + 用户问题 → LLM → 带引用的答案

    参数:
        model: 指定 LLM 模型名。不传时使用 LLM_MODEL 环境变量默认值。
               调用方应通过此参数显式传入模型，避免并发竞态条件。

    返回: {
        "answer": str,           # LLM 生成的答案
        "sources": list[dict],   # 引用的来源
        "model": str,            # 使用的模型
        "context_count": int,    # 注入的上下文数
    }
    """
    api_key, base_url, default_model = _get_llm_config()
    if model is None:
        model = default_model

    # 构建系统提示
    system_prompt = """你是一个知识库问答助手。根据下面提供的知识库检索结果回答用户问题。

规则：
1. 只根据【知识库检索结果】中的内容回答，不要编造
2. 如果检索结果中没有相关信息，明确说"知识库中未找到相关内容"
3. 在回答中引用来源，格式：【来源: {source}】
4. 回答要简洁准确，用中文"""

    # 构建上下文
    context_parts = []
    sources = []
    for i, chunk in enumerate(context_chunks, 1):
        source = chunk.get("metadata", {}).get("source", "未知")
        text = chunk.get("text", "")
        score = chunk.get("score", 0)
        context_parts.append(f"【检索结果 {i}】（来源: {source}，相关度: {score:.0%}）\n{text}")
        sources.append({"source": source, "score": score, "preview": text[:80]})

    context_text = "\n\n---\n\n".join(context_parts) if context_parts else "（无检索结果）"

    user_message = f"""## 知识库检索结果

{context_text}

---

## 用户问题

{question}

请根据以上检索结果回答。"""

    # 构建 messages
    messages = [{"role": "system", "content": system_prompt}]
    if history:
        messages.extend(history[-4:])  # 最近 2 轮对话
    messages.append({"role": "user", "content": user_message})

    # 如果没有 API key，返回检索结果作为 fallback
    if not api_key:
        return {
            "answer": f"（未配置 LLM_API_KEY，以下为检索结果摘要）\n\n根据知识库检索，最相关的内容来自：{', '.join(s['source'] for s in sources)}\n\n{context_chunks[0]['text'] if context_chunks else '无结果'}",
            "sources": sources,
            "model": "fallback (no LLM)",
            "context_count": len(context_chunks),
        }

    # 调用 LLM
    payload = json.dumps({
        "model": model,
        "messages": messages,
        "temperature": 0.3,
        "max_tokens": 1000,
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

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            result = json.loads(resp.read())
            answer = result["choices"][0]["message"]["content"]
            return {
                "answer": answer,
                "sources": sources,
                "model": model,
                "context_count": len(context_chunks),
            }
    except Exception as e:
        return {
            "answer": f"LLM 调用失败: {str(e)}\n\n以下为检索结果：\n{context_chunks[0]['text'] if context_chunks else '无结果'}",
            "sources": sources,
            "model": f"error: {model}",
            "context_count": len(context_chunks),
        }
