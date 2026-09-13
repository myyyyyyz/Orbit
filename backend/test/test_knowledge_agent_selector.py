from app.knowledge_agent.models import CorpusProfile
from app.knowledge_agent.selector import select_strategy


def make_profile(**overrides):
    values = {
        "source_path": "knowledge/fixtures/report.pdf",
        "source_hash": "a" * 64,
        "file_type": "pdf",
        "text_extraction_ratio": 0.9,
    }
    values.update(overrides)
    return CorpusProfile(**values)


def test_clean_text_pdf_uses_hierarchical_pdf_fallback():
    decision = select_strategy(make_profile())

    assert decision.strategy_id == "pdf_text_hierarchical_v1"
    assert decision.decision_source == "fallback"
    assert decision.requires_review is False


def test_scanned_pdf_is_routed_to_ocr_review_fallback():
    decision = select_strategy(make_profile(text_extraction_ratio=0.02))

    assert decision.strategy_id == "pdf_ocr_review_v1"
    assert decision.requires_review is True


def test_unknown_file_type_falls_back_to_markdown_strategy():
    decision = select_strategy(make_profile(file_type="unknown"))

    assert decision.strategy_id == "markdown_hierarchical_v1"
    assert decision.decision_source == "fallback"
    assert decision.requires_review is False
