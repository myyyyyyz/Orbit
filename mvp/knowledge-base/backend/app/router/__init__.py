"""
模型路由模块 — 任务分流（v2：混合路由）

三层级联路由：
- Layer 1（规则引擎）：快速过滤，微秒级，处理 80% 常见查询
- Layer 2（语义路由）：Embedding 匹配意图描述，处理规则无法覆盖的变体表达
- Layer 3（LLM 分类）：边缘案例兜底，仅在前两层都不确定时调用

返回结构化路由决策：
- tier: fast | balanced | strong | unknown | out_of_scope
- confidence: 0.0 ~ 1.0
- needs_clarification: 是否需要追问用户
"""

import re
import os
import logging
from typing import Optional, List, Literal
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


# ================================================================
# 结构化路由决策
# ================================================================

class RouteDecision(BaseModel):
    """路由决策（结构化输出）"""
    tier: Literal["fast", "balanced", "strong", "unknown", "out_of_scope"] = Field(
        description="模型档位：fast=快模型, balanced=中等, strong=强模型, unknown=无法识别, out_of_scope=领域外"
    )
    model: str = Field(description="具体模型名")
    max_tokens: int = Field(default=500, description="最大输出 token 数")
    temperature: float = Field(default=0.3, description="生成温度")
    confidence: float = Field(default=0.5, ge=0.0, le=1.0, description="置信度")
    reason: str = Field(default="", description="路由理由")
    needs_clarification: bool = Field(default=False, description="是否需要追问用户")
    clarification_question: str = Field(default="", description="追问问题（needs_clarification=True 时）")
    intent: str = Field(default="balanced", description="识别的意图类型")

    class Config:
        use_enum_values = True


# ================================================================
# Layer 1: 规则引擎
# ================================================================

# ── 模型预设 ──────────────────────────────────────

MODEL_PRESETS = {
    "fast": {
        "model": os.getenv("LLM_MODEL_FAST", "gpt-4o-mini"),
        "max_tokens": 500,
        "temperature": 0.3,
        "desc": "快模型：简单问答、定义查询、FAQ",
    },
    "balanced": {
        "model": os.getenv("LLM_MODEL_BALANCED", "gpt-4o"),
        "max_tokens": 1000,
        "temperature": 0.3,
        "desc": "中等模型：通用问答、文档总结",
    },
    "strong": {
        "model": os.getenv("LLM_MODEL_STRONG", "gpt-4o"),
        "max_tokens": 2000,
        "temperature": 0.2,
        "desc": "强模型：代码生成、多步推理、架构设计",
    },
    "unknown": {
        "model": os.getenv("LLM_MODEL_FAST", "gpt-4o-mini"),
        "max_tokens": 300,
        "temperature": 0.2,
        "desc": "未知意图：尝试从知识库检索回答",
    },
    "out_of_scope": {
        "model": os.getenv("LLM_MODEL_FAST", "gpt-4o-mini"),
        "max_tokens": 200,
        "temperature": 0.1,
        "desc": "领域外：礼貌拒绝 + 引导回知识库范围",
    },
}

# ── 意图体系（三层：domain → intent → task）──

INTENT_TAXONOMY = {
    "knowledge": {
        "domain": "知识库查询",
        "intents": {
            "definition": "定义/概念查询（什么是、意思是）",
            "list": "列表查询（有哪些、列出）",
            "howto": "用法查询（怎么用、如何）",
            "where": "位置查询（在哪里、路径）",
            "count": "数量查询（多少、几个）",
        },
        "default_tier": "fast",
    },
    "generation": {
        "domain": "内容生成",
        "intents": {
            "code_gen": "代码生成（写一个、创建、实现）",
            "document": "文档生成（写一份报告、生成文档）",
        },
        "default_tier": "strong",
    },
    "analysis": {
        "domain": "分析与推理",
        "intents": {
            "analyze": "分析推理（分析、对比、评估）",
            "causal": "因果推理（为什么、原因）",
            "security": "安全分析（漏洞、风险）",
        },
        "default_tier": "strong",
    },
    "troubleshooting": {
        "domain": "排错与修复",
        "intents": {
            "debug": "调试（bug、错误、异常）",
            "fix": "修复（怎么修复、解决方案）",
        },
        "default_tier": "strong",
    },
    "design": {
        "domain": "架构设计",
        "intents": {
            "architecture": "架构设计（设计、重构、优化）",
            "workflow": "流程设计（步骤、流程、怎么做到）",
        },
        "default_tier": "strong",
    },
}

# ── 规则映射 ────────────────────────────────────

SIMPLE_PATTERNS = [
    (r'什么是|是什么|意思是', 'definition', 0.85),
    (r'有哪些|列表|清单', 'list', 0.85),
    (r'怎么用|如何使用|用法', 'howto', 0.80),
    (r'在哪|哪里|路径', 'where', 0.85),
    (r'多少|几个|数量', 'count', 0.85),
    (r'^.{1,15}$', 'short_query', 0.60),  # 短查询，置信度低
]

COMPLEX_PATTERNS = [
    (r'写一个|生成|创建|实现', 'code_gen', 0.80),
    (r'分析|对比|比较|评估', 'analyze', 0.85),
    (r'为什么|原因|根本', 'causal', 0.80),
    (r'重构|优化|改进|设计', 'architecture', 0.85),
    (r'步骤|流程|怎么做到', 'workflow', 0.80),
    (r'bug|错误|报错|异常|修复', 'debug', 0.90),
    (r'安全|漏洞|风险', 'security', 0.85),
    (r'报告|文档|总结', 'document', 0.75),
]

# 领域外关键词
OUT_OF_SCOPE_INDICATORS = [
    r'外卖|点餐|订餐|快递|打车|天气|股票|新闻|热搜|八卦',
    r'你是谁|你叫什么|你有什么功能',
    r'聊天|闲聊|讲故事|冷笑话|笑话|唱歌|诗',
]

# 安全预检
SAFETY_PATTERNS = [
    (r'(?i)ignore\s+(all\s+)?(previous|above|prior)\s+(instructions?|prompts?)', "prompt_injection"),
    (r'(?i)system\s*prompt', "prompt_leak"),
    (r'(?i)forget\s+everything', "prompt_injection"),
]


def _regex_classify(query: str) -> tuple[Optional[str], float, str]:
    """
    规则引擎分类。
    返回: (tier, confidence, intent_name) 或 (None, 0, "") 表示规则无法匹配
    """
    query_lower = query.lower().strip()

    # 安全预检
    for pattern, threat_type in SAFETY_PATTERNS:
        if re.search(pattern, query_lower):
            return "out_of_scope", 1.0, threat_type

    # 领域外检测
    for pattern in OUT_OF_SCOPE_INDICATORS:
        if re.search(pattern, query_lower):
            return "out_of_scope", 0.8, "out_of_scope"

    # 先复杂后简单（避免短查询误判）
    best_complex = None
    for pattern, intent, conf in COMPLEX_PATTERNS:
        if re.search(pattern, query_lower):
            if best_complex is None or conf > best_complex[1]:
                best_complex = ("strong", conf, intent)

    if best_complex:
        return best_complex

    best_simple = None
    for pattern, intent, conf in SIMPLE_PATTERNS:
        if re.search(pattern, query_lower):
            if best_simple is None or conf > best_simple[1]:
                best_simple = ("fast", conf, intent)

    if best_simple:
        return best_simple

    # 规则无法匹配 → 升级到语义路由
    return None, 0.0, ""


# ================================================================
# Layer 2: 语义路由（Embedding 相似度匹配）
# ================================================================

_intent_descriptions = None
_intent_embeddings = None


def _build_intent_embeddings():
    """惰性构建意图描述的 embedding（首次调用时）"""
    global _intent_descriptions, _intent_embeddings

    if _intent_embeddings is not None:
        return

    from ..embed import encode

    _intent_descriptions = []
    for domain_name, domain_info in INTENT_TAXONOMY.items():
        for intent_name, intent_desc in domain_info["intents"].items():
            full_desc = f"{domain_info['domain']} - {intent_name}: {intent_desc}"
            _intent_descriptions.append({
                "domain": domain_name,
                "intent": intent_name,
                "tier": domain_info["default_tier"],
                "desc": full_desc,
            })

    if _intent_descriptions:
        desc_texts = [d["desc"] for d in _intent_descriptions]
        _intent_embeddings = encode(desc_texts)


def _semantic_classify(query: str) -> tuple[Optional[str], float, str]:
    """
    语义路由：用 Embedding 匹配用户查询与意图描述。
    返回: (tier, confidence, intent_name) 或 (None, 0, "") 表示语义也不确定
    """
    try:
        _build_intent_embeddings()
    except Exception:
        logger.debug("Intent embed build skipped (fallback to regex only)")
        return None, 0.0, ""

    if not _intent_embeddings:
        return None, 0.0, ""

    from ..embed import encode

    query_embedding = encode([query])
    if not query_embedding:
        return None, 0.0, ""

    query_emb = query_embedding[0]

    # cosine similarity
    best_match = None
    best_score = 0.0
    norm_q = sum(x * x for x in query_emb) ** 0.5

    for i, intent_emb in enumerate(_intent_embeddings):
        if len(intent_emb) != len(query_emb):
            continue
        dot = sum(a * b for a, b in zip(query_emb, intent_emb))
        norm_i = sum(x * x for x in intent_emb) ** 0.5
        if norm_q == 0 or norm_i == 0:
            continue
        score = dot / (norm_q * norm_i)
        if score > best_score:
            best_score = score
            best_match = _intent_descriptions[i]

    # 阈值判断
    SEMANTIC_HIGH_THRESHOLD = 0.45   # 高于此值认为匹配
    SEMANTIC_LOW_THRESHOLD = 0.25    # 低于此值认为 unknown

    if best_match and best_score >= SEMANTIC_HIGH_THRESHOLD:
        return best_match["tier"], best_score, best_match["intent"]
    elif best_score >= SEMANTIC_LOW_THRESHOLD:
        # 模糊匹配 → LLM 分类兜底
        return None, best_score, ""
    else:
        return "unknown", best_score, "unknown"


# ================================================================
# Layer 3: LLM 分类（兜底）
# ================================================================

def _llm_classify(query: str) -> tuple[str, float, str]:
    """
    LLM 分类兜底。
    仅在前两层都不确定时才调用，此时用最便宜的模型。
    """
    import json
    import urllib.request

    api_key = os.getenv("LLM_API_KEY", "")
    base_url = os.getenv("LLM_BASE_URL", "https://api.openai.com/v1/chat/completions")

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
        "model": os.getenv("LLM_MODEL_FAST", "gpt-4o-mini"),
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


# ================================================================
# 统一入口：混合路由
# ================================================================

CLARIFY_THRESHOLD = 0.45    # 低于此置信度时追问用户
CONFIDENCE_DOWNGRADE = 0.7  # 检索高置信度自动降级到 fast


def route_model(query: str, retrieval_scores: list[float] = None) -> RouteDecision:
    """
    混合路由：规则引擎 → 语义路由 → LLM 分类 → 检索置信度降级

    返回 RouteDecision（结构化路由决策）
    """
    tier = "balanced"
    confidence = 0.5
    intent = "balanced"
    reason = ""

    # ── Layer 1: 规则引擎 ──
    rule_tier, rule_conf, rule_intent = _regex_classify(query)

    if rule_tier and rule_conf >= 0.7:
        # 规则高置信度 → 直接采用
        tier, confidence, intent = rule_tier, rule_conf, rule_intent
        reason = f"规则匹配（{intent}, conf={confidence:.0%}）"
    elif rule_tier:
        # 规则低置信度 → 保留候选，继续语义路由
        tier, confidence, intent = rule_tier, rule_conf, rule_intent
        reason = f"规则匹配（{intent}, conf={confidence:.0%}）→ 语义确认中"

        # 同时尝试语义路由
        sem_tier, sem_conf, sem_intent = _semantic_classify(query)
        if sem_tier and sem_conf > rule_conf:
            tier, confidence, intent = sem_tier, sem_conf, sem_intent
            reason = f"语义路由覆盖（{intent}, conf={sem_conf:.0%}，超越规则 {rule_conf:.0%}）"
    elif rule_tier is None:
        # 规则完全未匹配 → 语义路由
        sem_tier, sem_conf, sem_intent = _semantic_classify(query)
        if sem_tier and sem_conf >= 0.45:
            tier, confidence, intent = sem_tier, sem_conf, sem_intent
            reason = f"语义路由命中（{intent}, conf={sem_conf:.0%}）"
        elif sem_conf >= 0.25:
            # 语义模糊 → LLM 分类
            llm_tier, llm_conf, llm_intent = _llm_classify(query)
            tier, confidence, intent = llm_tier, llm_conf, llm_intent
            reason = f"LLM 分类（{intent}, conf={llm_conf:.0%}）"
        else:
            # 完全不确定 → unknown
            tier, confidence, intent = "unknown", 0.0, "unknown"
            reason = "规则+语义均无法识别，标记为 unknown"

    # ── 检索置信度降级 ──
    if retrieval_scores and len(retrieval_scores) > 0:
        top_score = retrieval_scores[0]
        if top_score > CONFIDENCE_DOWNGRADE and tier not in ("strong", "unknown", "out_of_scope"):
            tier = "fast"
            reason += f" + 检索高置信度({top_score:.0%})→降级至 fast"

    # ── 置信度门控 ──
    needs_clarification = False
    clarification_question = ""

    if tier == "unknown":
        needs_clarification = True
        clarification_question = "抱歉，我不太确定你想做什么。能再描述一下吗？"
    elif confidence < CLARIFY_THRESHOLD and tier != "out_of_scope":
        needs_clarification = True
        clarification_question = f"你的意思是「{INTENT_TAXONOMY.get(intent, {}).get('intents', {}).get(intent, '查询')}」吗？请确认一下。"

    if tier == "out_of_scope":
        needs_clarification = True
        clarification_question = "抱歉，我只能回答知识库相关的问题。请尝试问我关于文档内容的问题。"

    # ── 构建决策 ──
    preset = MODEL_PRESETS.get(tier, MODEL_PRESETS["balanced"])
    return RouteDecision(
        tier=tier,
        model=preset["model"],
        max_tokens=preset["max_tokens"],
        temperature=preset["temperature"],
        confidence=round(confidence, 4),
        reason=reason,
        needs_clarification=needs_clarification,
        clarification_question=clarification_question if needs_clarification else "",
        intent=intent,
    )


# ================================================================
# 兼容旧接口
# ================================================================

def detect_intent(query: str) -> str:
    """意图识别（兼容旧接口），返回 'simple' | 'complex' | 'balanced' | 'unknown'"""
    decision = route_model(query)
    mapping = {
        "fast": "simple",
        "balanced": "balanced",
        "strong": "complex",
        "unknown": "unknown",
        "out_of_scope": "unknown",
    }
    return mapping.get(decision.tier, "balanced")
