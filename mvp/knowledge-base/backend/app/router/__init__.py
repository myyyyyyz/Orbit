"""
模型路由模块 — 任务分流

根据查询复杂度自动选择模型：
- 简单问答（定义、FAQ、查表）→ 快模型（低成本低延迟）
- 复杂任务（推理、代码、多步分析）→ 强模型（高质量）
- 默认 → 中等模型
"""

import re
import os
from typing import Optional


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
}


# ── 意图识别规则 ──────────────────────────────────

# 简单意图：定义、查询、FAQ
SIMPLE_PATTERNS = [
    r'什么是|是什么|意思是',           # 定义查询
    r'有哪些|列表|清单',              # 列表查询
    r'怎么用|如何使用|用法',           # 用法查询
    r'在哪|哪里|路径',               # 位置查询
    r'多少|几个|数量',              # 数量查询
    r'^.{1,15}$',                  # 短查询（<15字）
]

# 复杂意图：推理、代码、多步
COMPLEX_PATTERNS = [
    r'写一个|生成|创建|实现',         # 代码生成
    r'分析|对比|比较|评估',          # 分析推理
    r'为什么|原因|根本',            # 因果推理
    r'重构|优化|改进|设计',          # 架构设计
    r'步骤|流程|怎么做到',           # 多步流程
    r'bug|错误|报错|异常|修复',      # 调试
    r'安全|漏洞|风险',             # 安全分析
]


def detect_intent(query: str) -> str:
    """
    意图识别：返回 'simple' | 'complex' | 'balanced'
    """
    query_lower = query.lower().strip()

    # 先检查复杂模式
    for pattern in COMPLEX_PATTERNS:
        if re.search(pattern, query_lower):
            return "complex"

    # 再检查简单模式
    for pattern in SIMPLE_PATTERNS:
        if re.search(pattern, query_lower):
            return "simple"

    # 默认中等
    return "balanced"


def route_model(query: str, retrieval_scores: list[float] = None) -> dict:
    """
    模型路由：根据查询 + 检索结果质量选择最优模型

    返回: {
        "tier": "fast" | "balanced" | "strong",
        "model": str,
        "max_tokens": int,
        "temperature": float,
        "reason": str,
    }
    """
    intent = detect_intent(query)

    # 如果检索结果质量很高（top-1 > 0.7），即使复杂问题也可以用快模型
    if retrieval_scores and len(retrieval_scores) > 0:
        top_score = retrieval_scores[0]
        if top_score > 0.7 and intent != "complex":
            return {**MODEL_PRESETS["fast"], "tier": "fast", "reason": f"检索高置信度({top_score:.0%})+{intent}意图→快模型"}
    
    # 复杂任务必须用强模型
    if intent == "complex":
        return {**MODEL_PRESETS["strong"], "tier": "strong", "reason": "复杂意图（推理/代码/分析）→强模型"}

    # 简单任务用快模型
    if intent == "simple":
        return {**MODEL_PRESETS["fast"], "tier": "fast", "reason": "简单意图（定义/查询/FAQ）→快模型"}

    # 默认中等
    return {**MODEL_PRESETS["balanced"], "tier": "balanced", "reason": "通用意图→中等模型"}
