"""统一入口：混合路由 — 规则引擎 → 语义路由 → LLM 分类 → 检索置信度降级 → 安全内联"""

from typing import Optional

from .models import RouteDecision
from .rules import (
    _regex_classify, MODEL_PRESETS, INTENT_TAXONOMY,
    _extract_slots, _missing_required_slots, _slot_question,
)
from .semantic import _semantic_classify
from .llm import _llm_classify
from .security import security_scan, local_model_name

CLARIFY_THRESHOLD = 0.45    # 低于此置信度时追问用户
CONFIDENCE_DOWNGRADE = 0.7  # 检索高置信度自动降级到 fast

# R2: Hybrid Route 参数
RULE_WEIGHT = 0.6           # 规则置信度权重
SEMANTIC_WEIGHT = 0.4       # 语义相似度权重
SEMANTIC_CONFLICT = 0.15    # 语义相似度低于此值视为"与规则明显冲突"，触发 LLM 兜底


def _hybrid_confidence(query: str, intent: str, rule_conf: float) -> tuple[float, bool]:
    """R2: 规则置信度 + 语义相似度联合打分，返回 (hybrid_conf, conflict)。

    参考 semantic-router 的 HybridRouteLayer：
    - 规则命中且语义不冲突（如"什么是 Docker"命中 definition，语义也像定义）
      → conflict=False，采用规则（hybrid 分用于 reason/confidence 展示）
    - 规则命中但语义强烈反对（如"帮我写 Dockerfile"被 definition 规则命中，
      语义更像 code_gen）→ conflict=True，触发 LLM 兜底
    - embedding 不可用时退回纯规则置信度，不冲突（优雅降级）

    注意：语义权重仅用于"检测冲突"，不用于把高置信度规则拉低——
    因为规则引擎本身就是高置信才命中（conf 0.6-0.9）。
    """
    try:
        from .semantic import _intent_similarity
        sem_conf = _intent_similarity(query, intent)
    except Exception:
        sem_conf = None
    if sem_conf is None:
        return rule_conf, False
    hybrid = RULE_WEIGHT * rule_conf + SEMANTIC_WEIGHT * sem_conf
    conflict = sem_conf < SEMANTIC_CONFLICT
    return hybrid, conflict


def analyze_query(query: str, pipeline: Optional["RouterPipeline"] = None) -> dict:
    """
    阶段一：意图 + 槽位提取（**不依赖检索结果**，可在检索之前调用）。

    这是 route_model 的前半段拆分，单独暴露的目的：让 stream_ask 能在检索之前
    拿到 slots，用于 query 改写与元数据过滤，从而让槽位真正反哺检索。
    档位决策（decide_tier）留到拿到检索分之后再做，避免"检索高置信度降级"逻辑丢失。

    返回: {"intent": str, "confidence": float, "tier": str, "slots": dict,
           "missing_slots": list, "reason": str}
    """
    tier = "balanced"
    confidence = 0.5
    intent = "balanced"
    reason = ""

    if pipeline is not None:
        p_tier, p_conf, p_intent = pipeline.route(query)
        tier, confidence, intent = p_tier, p_conf, p_intent
        reason = f"自定义 Pipeline（{pipeline.routers[0].name if pipeline.routers else '?'} 等 {len(pipeline.routers)} 层）→ {tier}"
    else:
        # ── Layer 1: 规则引擎 ──
        rule_tier, rule_conf, rule_intent = _regex_classify(query)

        if rule_tier and rule_conf >= 0.7:
            hybrid_conf, conflict = _hybrid_confidence(query, rule_intent, rule_conf)
            if not conflict:
                tier, confidence, intent = rule_tier, hybrid_conf, rule_intent
                reason = f"规则匹配+Hybrid验证（{intent}, conf={hybrid_conf:.0%}）"
            else:
                llm_tier, llm_conf, llm_intent = _llm_classify(query)
                tier, confidence, intent = llm_tier, llm_conf, llm_intent
                reason = (f"规则冲突→LLM 分类（{intent}, conf={llm_conf:.0%}，"
                          f"语义冲突{hybrid_conf:.0%}<{SEMANTIC_CONFLICT:.0%}）")
        elif rule_tier:
            tier, confidence, intent = rule_tier, rule_conf, rule_intent
            reason = f"规则匹配（{intent}, conf={confidence:.0%}）→ 语义确认中"

            sem_tier, sem_conf, sem_intent = _semantic_classify(query)
            if sem_tier and sem_conf > rule_conf:
                tier, confidence, intent = sem_tier, sem_conf, sem_intent
                reason = f"语义路由覆盖（{intent}, conf={sem_conf:.0%}，超越规则 {rule_conf:.0%}）"
        else:
            sem_tier, sem_conf, sem_intent = _semantic_classify(query)
            if sem_tier and sem_conf >= 0.45:
                tier, confidence, intent = sem_tier, sem_conf, sem_intent
                reason = f"语义路由命中（{intent}, conf={sem_conf:.0%}）"
            elif sem_conf >= 0.25:
                llm_tier, llm_conf, llm_intent = _llm_classify(query)
                tier, confidence, intent = llm_tier, llm_conf, llm_intent
                reason = f"LLM 分类（{intent}, conf={llm_conf:.0%}）"
            else:
                tier, confidence, intent = "unknown", 0.0, "unknown"
                reason = "规则+语义均无法识别，标记为 unknown"

    slots = _extract_slots(query, intent)
    missing_slots = _missing_required_slots(intent, slots)

    return {
        "tier": tier,
        "confidence": confidence,
        "intent": intent,
        "reason": reason,
        "slots": slots,
        "missing_slots": missing_slots,
    }


def route_model(query: str, retrieval_scores: list[float] = None,
                budget_remaining_pct: float = 1.0,
                pipeline: Optional["RouterPipeline"] = None,
                analysis: Optional[dict] = None) -> RouteDecision:
    """
    混合路由：规则引擎 → 语义路由 → LLM 分类 → 检索置信度降级 → 成本感知降级 → 安全内联

    R3: pipeline 可选参数——传入 RouterPipeline 时用它替代内置三层逻辑
    （用户自定义路由策略，参考 LLMRouter 插件体系）。
    R4: budget_remaining_pct 为当前预算剩余比例（0-1，默认 1.0=预算充足）。
    预算紧张时自动降级模型档位（参考 LLMRouter 的 alpha*perf - beta*cost）。

    返回 RouteDecision（结构化路由决策）
    """
    # ── 路由决策：复用 analyze_query（意图+槽位，不依赖检索）──
    # 拆两阶段的目的见 analyze_query docstring：让槽位能在检索之前产生。
    # 调用方若已跑过 analyze_query（例如 stream_ask 在检索前跑过一次），
    # 可把结果传进来复用，避免重复执行规则/语义/LLM 三层判定。
    if analysis is None:
        analysis = analyze_query(query, pipeline=pipeline)
    elif pipeline is not None:
        analysis = analyze_query(query, pipeline=pipeline)
    tier = analysis["tier"]
    confidence = analysis["confidence"]
    intent = analysis["intent"]
    reason = analysis["reason"]
    slots = analysis["slots"]
    missing_slots = analysis["missing_slots"]

    # ── 检索置信度降级 ──
    if retrieval_scores and len(retrieval_scores) > 0:
        top_score = retrieval_scores[0]
        if top_score > CONFIDENCE_DOWNGRADE and tier not in ("strong", "unknown", "out_of_scope"):
            tier = "fast"
            reason += f" + 检索高置信度({top_score:.0%})→降级至 fast"

    # ── R4: 成本感知降级（参考 LLMRouter 成本-性能权衡）──
    if budget_remaining_pct < 0.3 and tier == "strong":
        tier = "balanced"
        reason += f" + 预算仅剩{budget_remaining_pct:.0%}→strong 降级 balanced"
    elif budget_remaining_pct < 0.1 and tier == "balanced":
        tier = "fast"
        reason += f" + 预算仅剩{budget_remaining_pct:.0%}→balanced 降级 fast"

    # ── 置信度门控 ──
    needs_clarification = False
    clarification_question = ""

    if tier == "unknown":
        needs_clarification = True
        clarification_question = "抱歉，我不太确定你想做什么。能再描述一下吗？"
    elif confidence < CLARIFY_THRESHOLD and tier != "out_of_scope":
        needs_clarification = True
        # 优先问"缺哪个参数"，比泛泛确认意图更可执行
        slot_q = _slot_question(intent, missing_slots)
        if slot_q:
            clarification_question = slot_q
        else:
            clarification_question = f"你的意思是「{INTENT_TAXONOMY.get(intent, {}).get('intents', {}).get(intent, '查询')}」吗？请确认一下。"

    if tier == "out_of_scope":
        needs_clarification = True
        clarification_question = "抱歉，我只能回答知识库相关的问题。请尝试问我关于文档内容的问题。"

    # ── R5: 安全分类器内联（参考 vLLM Semantic Router 信号层）──
    security = security_scan(query)
    if security["pii_detected"]:
        # PII → 锁定本地模型（不出站）+ 保守参数
        tier = "fast"
        local_model = local_model_name()
        reason += f" + PII 检测({[p['type'] for p in security['pii']][:3]})→锁定本地模型"
        if security["injection_risk"] > 0:
            reason += f" + 注入风险({security['injection_risk']:.0%})→安全模式"
        needs_clarification = True
        clarification_question = ("检测到敏感信息（如证件号/手机号/密钥），为避免数据出站，"
                                  "本回答将严格限于本地处理。请确认是否继续？")
        return RouteDecision(
            tier=tier,
            model=local_model,
            max_tokens=200,
            temperature=0.0,
            confidence=round(confidence, 4),
            reason=reason,
            needs_clarification=True,
            clarification_question=clarification_question,
            intent=intent,
            slots=slots,
            missing_slots=missing_slots,
        )
    elif security["injection_risk"] > 0.5:
        # 高注入风险 → 保守参数 + 明确拒绝引导
        reason += f" + 注入风险({security['injection_risk']:.0%})→安全模式"
        needs_clarification = True
        clarification_question = "检测到疑似指令注入/越狱意图。我只能处理知识库相关的正常提问，请换一种问法。"

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
        slots=slots,
        missing_slots=missing_slots,
    )


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
