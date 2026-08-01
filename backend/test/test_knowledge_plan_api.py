from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import knowledge_plan
from app.middleware.auth import get_current_user


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

    response = TestClient(app).post("/api/knowledge/plan-folder", json={"path": "fixtures"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["dry_run"] is True
    assert payload["vector_store_writes"] == 0
    assert payload["document_count"] == 7
