"""RAG / 对话 Prompt 构建。

generate/（非流式）使用严格版：只根据知识库回答；
stream/（流式）使用宽松版：闲聊、无关问题自然回答，不强行引用来源。
"""

# 严格版：只根据知识库检索结果回答（generate_answer 使用）
STRICT_RAG_SYSTEM_PROMPT = """你是一个知识库问答助手。根据下面提供的知识库检索结果回答用户问题。

规则：
1. 只根据【知识库检索结果】中的内容回答，不要编造
2. 如果检索结果中没有相关信息，明确说"知识库中未找到相关内容"
3. 在回答中引用来源，格式：【来源: {source}】
4. 回答要简洁准确，用中文"""

# 宽松版：优先根据检索结果，闲聊/无关问题自然回答（stream_ask 使用）
LENIENT_RAG_SYSTEM_PROMPT = """你是一个知识库问答助手。根据检索结果回答用户问题。
规则：
1. 优先根据检索结果回答，不要编造
2. 只有检索结果确实与问题相关时才引用来源，格式：【来源: xxx】
3. 如果问题是打招呼、闲聊，或与检索内容无关，自然友好地回答，不要强行引用来源
4. 回答简洁准确，用中文"""

# 纯对话模式（无相关检索结果时）
CHAT_SYSTEM_PROMPT = "你是一个友好的 AI 助手，简洁自然地回答用户的问题。"


def build_context_text(chunks: list[dict], with_score: bool = False, default_source: str = "未知") -> str:
    """把检索 chunks 拼成 prompt 上下文文本。

    参数:
        with_score: 是否在每条结果中附带相关度百分比（generate 的严格版使用）。
    """
    parts = []
    for i, chunk in enumerate(chunks, 1):
        source = chunk.get("metadata", {}).get("source", default_source)
        text = chunk.get("text", "")
        if with_score:
            score = chunk.get("score", 0)
            parts.append(f"【检索结果 {i}】（来源: {source}，相关度: {score:.0%}）\n{text}")
        else:
            parts.append(f"【检索结果 {i}】（来源: {source}）\n{text}")
    return "\n\n---\n\n".join(parts)


def build_sources(chunks: list[dict], default_source: str = "未知") -> list[dict]:
    """从检索 chunks 提取来源列表（用于答案附带引用）。"""
    return [
        {
            "source": c.get("metadata", {}).get("source", default_source),
            "score": c.get("score", 0),
            "preview": c.get("text", "")[:80],
        }
        for c in chunks
    ]


def build_rag_user_message(question: str, context_text: str, slots: dict = None) -> str:
    """宽松版 RAG 用户消息（stream_ask 使用）。

    slots 非空时附带「已识别到的关键信息」，把槽位填充结果显式告诉生成模型，
    用于消解指代/时间歧义（如把「上周的部署文档」锚定为 time=上周、doc_type=部署文档）。
    slots 为空时输出与历史版本完全一致，保持向后兼容。
    """
    base = f"## 检索结果\n\n{context_text}\n\n---\n\n## 问题\n\n{question}"
    if not slots:
        return base
    slot_lines = "\n".join(f"- {k}: {v}" for k, v in slots.items())
    return f"{base}\n\n---\n\n## 已识别到的关键信息\n\n{slot_lines}"


def build_strict_rag_user_message(question: str, context_text: str) -> str:
    """严格版 RAG 用户消息（generate_answer 使用）。"""
    return f"""## 知识库检索结果

{context_text}

---

## 用户问题

{question}

请根据以上检索结果回答。"""
