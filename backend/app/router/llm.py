"""Layer 3：LLM 分类 — 边缘案例兜底，仅在前两层都不确定时调用"""

import json
import os
import urllib.request
import logging

from ..llm.client import default_base_url_for, resolve_model

logger = logging.getLogger(__name__)


def _llm_classify(query: str) -> tuple[str, float, str]:
    """
    LLM 分类兜底。
    仅在前两层都不确定时才调用，此时用最便宜的模型。
    """
    api_key = os.getenv("LLM_API_KEY", "")
    # 兜底模型/端点一律取唯一事实源，不写字面量（见 rules.py 的说明）
    model = resolve_model("LLM_MODEL_FAST")
    base_url = os.getenv("LLM_BASE_URL") or default_base_url_for(model)

    if not api_key:
        return "balanced", 0.3, "fallback_balanced"

    system_prompt = """你是一个意图分类器。将用户查询分类到以下类型之一。

类型列表：
- definition: 定义/概念查询（什么是、意思是）
- list: 列表查询（有哪些、列出）
- howto: 用法查询（怎么用、如何）
- code_gen: 代码生成（写、创建、实现）
- analyze: 分析推理（分析、对比、评估）
- debug: 调试排错（bug、错误）
- architecture: 架构设计
- workflow: 流程/步骤
- out_of_scope: 与知识库查询无关的闲聊或请求
- unknown: 无法判断

返回 JSON 格式：{"tier": "fast|balanced|strong", "intent": "...", "confidence": 0.0-1.0}
tier 规则：definition/list/howto→fast, code_gen/analyze/debug→strong, 其他→balanced"""

    payload = json.dumps({
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": query},
        ],
        "temperature": 0,
        "max_tokens": 100,
        "response_format": {"type": "json_object"},
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
        with urllib.request.urlopen(req, timeout=10) as resp:
            result = json.loads(resp.read())
            content = result["choices"][0]["message"]["content"]
            parsed = json.loads(content)
            return parsed.get("tier", "balanced"), parsed.get("confidence", 0.5), parsed.get("intent", "unknown")
    except Exception:
        logger.debug("LLM classifier fallback: balanced route with low confidence", exc_info=True)
        return "balanced", 0.3, "fallback_balanced"
