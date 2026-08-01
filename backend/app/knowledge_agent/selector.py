from collections.abc import Mapping
from typing import Any

from .catalog import STRATEGY_CATALOG, is_compatible
from .models import CorpusProfile, StrategyDecision


def _fallback(profile: CorpusProfile) -> StrategyDecision:
    if profile.file_type == "pdf" and profile.text_extraction_ratio < 0.1:
        return StrategyDecision(
            strategy_id="pdf_ocr_review_v1",
            decision_source="fallback",
            confidence=0.95,
            reason="PDF 文本提取率过低，按扫描件进入 OCR 与人工复核路径。",
            requires_review=True,
        )

    strategy_by_type = {
        "markdown": "markdown_hierarchical_v1",
        "text": "markdown_hierarchical_v1",
        "docx": "docx_layout_aware_v1",
        "xlsx": "spreadsheet_structured_v1",
        "pdf": "pdf_text_hierarchical_v1",
    }
    strategy_id = strategy_by_type.get(profile.file_type, "markdown_hierarchical_v1")
    return StrategyDecision(
        strategy_id=strategy_id,
        decision_source="fallback",
        confidence=0.8,
        reason="未获得可用的 Agent 建议，使用与文件画像匹配的确定性兜底策略。",
        requires_review=False,
    )


def _validated_agent_decision(
    profile: CorpusProfile, suggestion: Mapping[str, Any]
) -> StrategyDecision | None:
    strategy_id = suggestion.get("strategy_id")
    confidence = suggestion.get("confidence")
    reason = suggestion.get("reason")
    if not isinstance(strategy_id, str) or not is_compatible(strategy_id, profile):
        return None
    if isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
        return None
    if not 0.0 <= float(confidence) <= 1.0 or not isinstance(reason, str) or not reason.strip():
        return None

    strategy = STRATEGY_CATALOG[strategy_id]
    return StrategyDecision(
        strategy_id=strategy_id,
        decision_source="agent",
        confidence=float(confidence),
        reason=reason.strip(),
        requires_review=strategy.requires_review,
    )


def select_strategy(
    profile: CorpusProfile, suggestion: Mapping[str, Any] | None = None
) -> StrategyDecision:
    """Accept only catalog-compatible Agent output; otherwise use safe rules."""

    if suggestion is not None:
        decision = _validated_agent_decision(profile, suggestion)
        if decision is not None:
            return decision
    return _fallback(profile)
