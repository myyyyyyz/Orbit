"""安全分类器（R5）：内联到路由决策的输入维度。

参考 vLLM Semantic Router 的信号层设计——安全不是"事后拦截"，
而是路由决策的前置输入：检测到 PII → 锁定本地模型不出站；
检测到注入/越狱 → 保守参数 + 明确拒绝引导。
"""

import os
import re

from ..llm.client import resolve_model

# PII 模式（保守检测，避免误报普通数字）
PII_PATTERNS = [
    (r"\b\d{17}[\dXx]\b", "身份证号"),
    (r"\b1[3-9]\d{9}\b", "手机号"),
    (r"\b\d{16,19}\b", "银行卡号"),
    (r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", "邮箱"),
    (r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b", "AWS密钥"),
    (r"\bsk-[A-Za-z0-9]{20,}\b", "API密钥"),
    (r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b", "JWT令牌"),
]

# 注入/越狱模式
INJECTION_PATTERNS = [
    (r"(?i)ignore\s+(all\s+)?(previous|above|prior)\s+(instructions?|prompts?)", "指令忽略"),
    (r"忘记所有(的)?指令|忽略(之前的|以上|所有)?指令|忽略所有提示词", "指令忽略"),
    (r"(?i)system\s*prompt|输出(系统)?提示词|泄露(系统)?提示词", "系统提示词泄露"),
    (r"(?i)reveal\s+(your|the)\s*(system|initial|base)\s*prompt", "系统提示词泄露"),
    (r"(?i)pretend\s+to\s+be|act\s+as\s+(a\s+)?(dan|assistant)", "角色扮演越狱"),
    (r"(?i)\b(dan|do\s+anything\s+now|jailbreak)\b", "越狱关键词"),
    (r"(?i)developer\s+mode|super\s+mode|unrestricted\s+mode", "越狱模式"),
]


def security_scan(query: str) -> dict:
    """扫描 query 的安全信号。

    返回:
    {
        "pii": [{"type": str, "match": str}],
        "pii_detected": bool,
        "injection_matches": list[str],
        "injection_risk": float,   # 0-1，命中条数 / 3 封顶
        "dangerous": bool,          # 任一 PII 或注入风险 > 0
    }
    """
    query = query or ""
    pii = []
    for pattern, label in PII_PATTERNS:
        m = re.search(pattern, query)
        if m:
            # 截断匹配内容展示（避免在日志/回复中回显完整密钥）
            matched = m.group(0)
            shown = matched[:6] + "***" if len(matched) > 9 else matched
            pii.append({"type": label, "match": shown})

    injection_matches = []
    for pattern, label in INJECTION_PATTERNS:
        if re.search(pattern, query):
            injection_matches.append(label)

    injection_risk = min(len(injection_matches) / 3, 1.0)

    return {
        "pii": pii,
        "pii_detected": len(pii) > 0,
        "injection_matches": injection_matches,
        "injection_risk": round(injection_risk, 2),
        "dangerous": len(pii) > 0 or injection_risk > 0,
    }


def local_model_name() -> str:
    """本地模型名（PII 不出站时锁定）。

    注意：命中 PII 时会**把路由锁定到这个模型**，所以它必须与已配置的端点
    兼容。此前兜底写死 "gpt-4o-mini"，在 DeepSeek 端点上会导致该分支必定失败
    （PII 场景反而比普通场景更容易报错，方向正好相反）。
    """
    return resolve_model("LLM_MODEL_LOCAL", "LLM_MODEL_FAST")
