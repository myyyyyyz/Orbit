from pathlib import Path

from app.knowledge_agent.pipeline import plan_folder


FIXTURES = Path(__file__).resolve().parents[2] / "knowledge" / "fixtures"


def test_plan_folder_persists_audit_without_vector_store_writes(tmp_path):
    database_path = tmp_path / "knowledge-agent.sqlite3"

    plan = plan_folder(FIXTURES, knowledge_root=FIXTURES.parent, database_path=database_path, user_id=7)

    assert plan.dry_run is True
    assert plan.document_count == 7
    assert plan.vector_store_writes == 0
    assert plan.run_id
    assert database_path.exists()
    assert {document.decision.strategy_id for document in plan.documents} >= {
        "pdf_ocr_review_v1",
        "spreadsheet_structured_v1",
    }


def test_plan_folder_rejects_a_folder_outside_knowledge_root(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()

    try:
        plan_folder(outside, knowledge_root=FIXTURES.parent, database_path=tmp_path / "audit.sqlite3")
    except ValueError as exc:
        assert "outside" in str(exc).lower()
    else:
        raise AssertionError("Expected path traversal protection")
