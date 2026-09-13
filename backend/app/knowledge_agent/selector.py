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
        reason="依据文件类型匹配确定性策略，无需 LLM 介入。",
        requires_review=False,
    )


def select_strategy(profile: CorpusProfile) -> StrategyDecision:
    """依据文件画像选择切分策略（确定性，无 LLM 覆盖层）。"""

    return _fallback(profile)
