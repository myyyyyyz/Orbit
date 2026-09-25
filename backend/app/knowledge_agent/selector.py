from .models import CorpusProfile, StrategyDecision


def _fallback(profile: CorpusProfile) -> StrategyDecision:
    strategy_by_type = {
        "markdown": "markdown_hierarchical_v1",
        "text": "markdown_hierarchical_v1",
        "docx": "docx_layout_aware_v1",
        "xlsx": "spreadsheet_structured_v1",
        # pdf_vision_v1 自带页内图片检测/复杂度分流（OCR 或视觉 LLM）
        # 与按标题分章，扫描件（文本提取率低）同样走此策略。
        "pdf": "pdf_vision_v1",
    }
    strategy_id = strategy_by_type.get(profile.file_type, "markdown_hierarchical_v1")
    return StrategyDecision(
        strategy_id=strategy_id,
        decision_source="fallback",
        confidence=0.8,
        reason="依据文件类型匹配确定性策略，无需 LLM 介入。",
        requires_review=False,
    )


def select_strategy(profile: CorpusProfile) -> StrategyDecision:
    """依据文件画像选择切分策略（确定性，无 LLM 覆盖层）。"""

    return _fallback(profile)
