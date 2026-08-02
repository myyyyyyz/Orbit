import sqlite3
from pathlib import Path

from app.knowledge_agent.models import AgentAttempt
from app.knowledge_agent.pipeline import plan_folder


FIXTURES = Path(__file__).resolve().parents[2] / "knowledge" / "fixtures"


class RecordingAgent:
    def __init__(self, failing_source: str | None = None):
        self.calls = []
        self.failing_source = failing_source

    def recommend(self, profile, evidence):
        self.calls.append((profile.source_path, evidence))
        if profile.source_path == self.failing_source:
            return AgentAttempt(
                status="error",
                model="test-model",
                duration_ms=3,
                error_category="timeout",
            )
        strategy_by_type = {
            "markdown": "markdown_hierarchical_v1",
            "docx": "docx_layout_aware_v1",
            "xlsx": "spreadsheet_structured_v1",
            "pdf": (
                "pdf_ocr_review_v1"
                if profile.text_extraction_ratio < 0.1
                else "pdf_text_hierarchical_v1"
            ),
        }
        return AgentAttempt(
            status="success",
            model="test-model",
            duration_ms=3,
            suggestion={
                "strategy_id": strategy_by_type[profile.file_type],
                "confidence": 0.9,
                "reason": "fixture strategy",
                "requires_review": False,
            },
        )


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


def test_plan_folder_calls_agent_per_file_and_persists_sanitized_trace(tmp_path):
    agent = RecordingAgent()
    database_path = tmp_path / "audit.sqlite3"

    plan = plan_folder(
        FIXTURES,
        knowledge_root=FIXTURES.parent,
        database_path=database_path,
        agent=agent,
    )

    assert len(agent.calls) == 7
    assert all(len(evidence) <= 6000 for _, evidence in agent.calls)
    assert all(document.agent_attempt is not None for document in plan.documents)
    with sqlite3.connect(database_path) as connection:
        saved = connection.execute(
            "SELECT COUNT(*) FROM knowledge_agent_documents WHERE agent_attempt_json IS NOT NULL"
        ).fetchone()[0]
    assert saved == 7


def test_explicit_suggestion_takes_precedence_over_agent_call(tmp_path):
    agent = RecordingAgent()

    plan = plan_folder(
        FIXTURES,
        knowledge_root=FIXTURES.parent,
        database_path=tmp_path / "audit.sqlite3",
        agent=agent,
        agent_suggestions={
            "clean-policy.md": {
                "strategy_id": "markdown_hierarchical_v1",
                "confidence": 0.99,
                "reason": "explicit test suggestion",
                "requires_review": False,
            }
        },
    )

    assert "clean-policy.md" not in {source for source, _ in agent.calls}
    policy = next(
        document for document in plan.documents if document.profile.source_path == "clean-policy.md"
    )
    assert policy.decision.reason == "explicit test suggestion"
    assert policy.agent_attempt is None


def test_agent_failure_falls_back_for_one_file_without_aborting_folder(tmp_path):
    agent = RecordingAgent(failing_source="text-report.pdf")

    plan = plan_folder(
        FIXTURES,
        knowledge_root=FIXTURES.parent,
        database_path=tmp_path / "audit.sqlite3",
        agent=agent,
    )

    failed = next(
        document for document in plan.documents if document.profile.source_path == "text-report.pdf"
    )
    successful = next(
        document for document in plan.documents if document.profile.source_path == "clean-policy.md"
    )
    assert failed.decision.decision_source == "fallback"
    assert failed.agent_attempt.error_category == "timeout"
    assert successful.decision.decision_source == "agent"
