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

实现拆分为：models（决策模型）、rules（规则引擎）、semantic（语义路由）、
llm（LLM 分类）、service（统一入口），此处仅做导出。
"""
from .models import RouteDecision
from .rules import (
    MODEL_PRESETS,
    build_model_presets,
    INTENT_TAXONOMY,
    SIMPLE_PATTERNS,
    COMPLEX_PATTERNS,
    OUT_OF_SCOPE_INDICATORS,
    SAFETY_PATTERNS,
    _regex_classify,
)
from .semantic import _semantic_classify
from .llm import _llm_classify
from .service import (
    route_model,
    detect_intent,
    CLARIFY_THRESHOLD,
    CONFIDENCE_DOWNGRADE,
)
from .security import security_scan, local_model_name
from .base import BaseRouter, RouterPipeline, build_default_pipeline
from .plugins import RegexRouter, SemanticRouter, LLMRouter

__all__ = [
    "RouteDecision",
    "MODEL_PRESETS",
    "build_model_presets",
    "INTENT_TAXONOMY",
    "SIMPLE_PATTERNS",
    "COMPLEX_PATTERNS",
    "OUT_OF_SCOPE_INDICATORS",
    "SAFETY_PATTERNS",
    "_regex_classify",
    "_semantic_classify",
    "_llm_classify",
    "route_model",
    "detect_intent",
    "CLARIFY_THRESHOLD",
    "CONFIDENCE_DOWNGRADE",
    # R5: 安全分类器
    "security_scan",
    "local_model_name",
    # R3: Router 插件化
    "BaseRouter",
    "RouterPipeline",
    "build_default_pipeline",
    "RegexRouter",
    "SemanticRouter",
    "LLMRouter",
]
