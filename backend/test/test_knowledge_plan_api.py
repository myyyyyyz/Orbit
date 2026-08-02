from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import knowledge_plan
from app.knowledge_agent.adapter import OpenAICompatibleKnowledgeAgent
from app.knowledge_agent.models import AgentAttempt
from app.middleware.auth import get_current_user


class StaticAgent:
    def recommend(self, profile, evidence):
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
            model="api-test-model",
            duration_ms=1,
            suggestion={
                "strategy_id": strategy_by_type[profile.file_type],
                "confidence": 0.9,
                "reason": "API test suggestion",
                "requires_review": False,
            },
        )


def test_plan_folder_endpoint_requires_authentication():
    app = FastAPI()
    app.include_router(knowledge_plan.router)

    response = TestClient(app).post("/api/knowledge/plan-folder", json={"path": "fixtures"})

    assert response.status_code == 401


def test_plan_folder_endpoint_returns_dry_run_without_vector_writes(tmp_path, monkeypatch):
    app = FastAPI()
    app.include_router(knowledge_plan.router)
    app.dependency_overrides[get_current_user] = lambda: {"user_id": 42}
    monkeypatch.setattr(knowledge_plan, "_database_path", lambda: tmp_path / "audit.sqlite3")
    monkeypatch.setattr(
        OpenAICompatibleKnowledgeAgent,
        "from_env",
        classmethod(lambda cls: StaticAgent()),
    )

    response = TestClient(app).post("/api/knowledge/plan-folder", json={"path": "fixtures"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["dry_run"] is True
    assert payload["vector_store_writes"] == 0
    assert payload["document_count"] == 7
    assert all(document["agent_attempt"]["status"] == "success" for document in payload["documents"])


def test_plan_folder_endpoint_can_disable_agent(tmp_path, monkeypatch):
    class ForbiddenAgent:
        def recommend(self, profile, evidence):
            raise AssertionError("Agent must not run when use_agent is false")

    app = FastAPI()
    app.include_router(knowledge_plan.router)
    app.dependency_overrides[get_current_user] = lambda: {"user_id": 42}
    monkeypatch.setattr(knowledge_plan, "_database_path", lambda: tmp_path / "audit.sqlite3")
    monkeypatch.setattr(
        OpenAICompatibleKnowledgeAgent,
        "from_env",
        classmethod(lambda cls: ForbiddenAgent()),
    )

    response = TestClient(app).post(
        "/api/knowledge/plan-folder",
        json={"path": "fixtures", "use_agent": False},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["vector_store_writes"] == 0
    assert all(document["agent_attempt"] is None for document in payload["documents"])
