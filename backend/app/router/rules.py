"""Layer 1：规则引擎 — 快速过滤（微秒级），处理 80% 常见查询"""

import re
import logging
from typing import Optional

from ..llm.client import resolve_model

logger = logging.getLogger(__name__)


# ── 模型预设 ──────────────────────────────────────
#
# 兜底值一律取 DEFAULT_LLM_MODEL（client.py 里的唯一事实源），**不要写字面量**。
# 历史缺陷：这里写死了 OpenAI 的 "gpt-4o-mini" / "gpt-4o"，而线上端点指向
# DeepSeek。stream/service.py 的模型优先级是「前端指定 > 路由选择 > 环境变量」，
# 于是路由一给建议就把 "gpt-4o-mini" 发给 DeepSeek → HTTP 400，
# 用户侧表现为"路由阶段卡片显示 gpt-4o-mini，然后答案生成失败"。
#
# 想要分档用不同模型时，显式设置 LLM_MODEL_FAST / LLM_MODEL_BALANCED /
# LLM_MODEL_STRONG；不设置则三档都等于主模型（单一厂商部署的实际情况）。

def build_model_presets() -> dict:
    """构造模型预设表。

    独立成函数（而非模块级字面量）是为了让测试能在受控环境变量下重建，
    验证"未配置时各档兜底值 == DEFAULT_LLM_MODEL"这一不变量。
    """
    fast = resolve_model("LLM_MODEL_FAST")
    balanced = resolve_model("LLM_MODEL_BALANCED")
    strong = resolve_model("LLM_MODEL_STRONG")
    return {
        "fast": {
            "model": fast,
            "max_tokens": 500,
            "temperature": 0.3,
            "desc": "快模型：简单问答、定义查询、FAQ",
        },
        "balanced": {
            "model": balanced,
            "max_tokens": 1000,
            "temperature": 0.3,
            "desc": "中等模型：通用问答、文档总结",
        },
        "strong": {
            "model": strong,
            "max_tokens": 2000,
            "temperature": 0.2,
            "desc": "强模型：代码生成、多步推理、架构设计",
        },
        "unknown": {
            "model": fast,
            "max_tokens": 300,
            "temperature": 0.2,
            "desc": "未知意图：尝试从知识库检索回答",
        },
        "out_of_scope": {
            "model": fast,
            "max_tokens": 200,
            "temperature": 0.1,
            "desc": "领域外：礼貌拒绝 + 引导回知识库范围",
        },
    }


MODEL_PRESETS = build_model_presets()


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
    (r'有哪些|列表|清单|列出|列举', 'list', 0.85),  # R1: 补充"列出/列举"
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
    (r'报告|文档|总结|周报|周记', 'document', 0.75),  # R1: 补充"周报/周记"
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
    # R1: 补充中文注入模式
    (r'忘记所有(的)?指令|忽略(之前的|以上|所有)?指令|忽略所有提示词|忽略以上提示', "prompt_injection"),
    (r'输出(系统)?提示词|泄露(系统)?提示词|显示(系统)?prompt', "prompt_leak"),
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

    # R1: 数量词优先——"知识库里有多少文档"应判 count 而非 document。
    # 数量查询语义明确（conf=0.85），优先于 complex 的内容生成判断。
    COUNT_PATTERN = r'多少|几个|几种|多少种|几项|数量|总计|总共'
    if re.search(COUNT_PATTERN, query_lower):
        return "fast", 0.85, "count"

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
