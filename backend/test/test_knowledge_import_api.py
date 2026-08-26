from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import knowledge_imports, knowledge_plan
from app.middleware.auth import get_current_user


def _client(tmp_path, monkeypatch, current):
    app = FastAPI()
    app.include_router(knowledge_imports.router)
    app.include_router(knowledge_plan.router)
    app.dependency_overrides[get_current_user] = lambda: current
    database = tmp_path / "audit.sqlite3"
    root = tmp_path / "knowledge"
    monkeypatch.setattr(knowledge_imports, "_database_path", lambda: database)
    monkeypatch.setattr(knowledge_imports, "_KNOWLEDGE_ROOT", root)
    monkeypatch.setattr(knowledge_plan, "_database_path", lambda: database)
    monkeypatch.setattr(knowledge_plan, "_KNOWLEDGE_ROOT", root)
    return TestClient(app)


def test_import_endpoints_require_authentication():
    app = FastAPI()
    app.include_router(knowledge_imports.router)
    assert TestClient(app).post("/api/v1/knowledge/imports").status_code == 401


def test_import_api_freezes_folder_then_reuses_existing_planner(tmp_path, monkeypatch):
    current = {"user_id": 42}
    client = _client(tmp_path, monkeypatch, current)

    created = client.post("/api/v1/knowledge/imports")
    import_id = created.json()["import_id"]
    uploaded = client.post(
        f"/api/v1/knowledge/imports/{import_id}/files",
        data={"relative_path": "team/policy.md"},
        files={"file": ("policy.md", b"# Policy\nStable content", "text/markdown")},
    )
    completed = client.post(f"/api/v1/knowledge/imports/{import_id}/complete")
    planned = client.post(
        "/api/v1/knowledge/plan-folder",
        json={"path": completed.json()["relative_path"], "use_agent": False},
    )

    assert created.status_code == 201
    assert uploaded.status_code == 200
    assert uploaded.json()["file_count"] == 1
    assert completed.status_code == 200
    assert completed.json()["status"] == "ready"
    assert planned.status_code == 200
    assert planned.json()["document_count"] == 1


def test_import_api_hides_other_tenants_and_maps_validation_errors(tmp_path, monkeypatch):
    current = {"user_id": 42}
    client = _client(tmp_path, monkeypatch, current)
    import_id = client.post("/api/v1/knowledge/imports").json()["import_id"]
    invalid = client.post(
        f"/api/v1/knowledge/imports/{import_id}/files",
        data={"relative_path": "../secret.md"},
        files={"file": ("secret.md", b"no", "text/markdown")},
    )
    current["user_id"] = 99
    hidden = client.get(f"/api/v1/knowledge/imports/{import_id}")

    assert invalid.status_code == 400
    assert invalid.json()["detail"] == "invalid_relative_path"
    assert hidden.status_code == 404


def test_import_api_deletes_only_unfrozen_batch(tmp_path, monkeypatch):
    current = {"user_id": 42}
    client = _client(tmp_path, monkeypatch, current)
    import_id = client.post("/api/v1/knowledge/imports").json()["import_id"]

    deleted = client.delete(f"/api/v1/knowledge/imports/{import_id}")
    missing = client.get(f"/api/v1/knowledge/imports/{import_id}")

    assert deleted.status_code == 204
    assert missing.status_code == 404
