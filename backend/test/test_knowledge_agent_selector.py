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


def test_incompatible_agent_strategy_falls_back_to_safe_pdf_strategy():
    decision = select_strategy(
        make_profile(),
        {"strategy_id": "spreadsheet_structured_v1", "confidence": 0.98, "reason": "wrong type"},
    )

    assert decision.strategy_id == "pdf_text_hierarchical_v1"
    assert decision.decision_source == "fallback"


def test_valid_compatible_agent_strategy_is_accepted():
    decision = select_strategy(
        make_profile(),
        {
            "strategy_id": "pdf_text_hierarchical_v1",
            "confidence": 0.88,
            "reason": "text extraction is reliable",
        },
    )

    assert decision.decision_source == "agent"
    assert decision.confidence == 0.88
