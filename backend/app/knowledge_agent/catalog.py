from dataclasses import dataclass

from .models import CorpusProfile


@dataclass(frozen=True)
class StrategyDefinition:
    strategy_id: str
    supported_file_types: frozenset[str]
    requires_review: bool = False


STRATEGY_CATALOG: dict[str, StrategyDefinition] = {
    "markdown_hierarchical_v1": StrategyDefinition(
        "markdown_hierarchical_v1", frozenset({"markdown", "text"})
    ),
    "docx_layout_aware_v1": StrategyDefinition(
        "docx_layout_aware_v1", frozenset({"docx"})
    ),
    "spreadsheet_structured_v1": StrategyDefinition(
        "spreadsheet_structured_v1", frozenset({"xlsx"})
    ),
    "pdf_text_hierarchical_v1": StrategyDefinition(
        "pdf_text_hierarchical_v1", frozenset({"pdf"})
    ),
    "pdf_ocr_review_v1": StrategyDefinition(
        "pdf_ocr_review_v1", frozenset({"pdf"}), requires_review=True
    ),
}


def is_compatible(strategy_id: str, profile: CorpusProfile) -> bool:
    strategy = STRATEGY_CATALOG.get(strategy_id)
    if strategy is None or profile.file_type not in strategy.supported_file_types:
        return False
    if strategy_id == "pdf_text_hierarchical_v1" and profile.text_extraction_ratio < 0.1:
        return False
    return True
