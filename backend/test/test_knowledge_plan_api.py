import shutil
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import knowledge_plan
from app.knowledge_agent.catalog import STRATEGY_CATALOG
from app.knowledge_agent.chunk_ids import make_chunk_id
from app.knowledge_agent.models import KnowledgeChunk
from app.knowledge_agent.evaluation_models import EvaluationReport
from app.knowledge_agent.releases import ActiveIndexVersion
from app.knowledge_agent.staging_store import staging_collection_name
from app.middleware.auth import get_current_user


SOURCE_KNOWLEDGE = Path(__file__).resolve().parents[2] / "knowledge"


class RecordingStagingStore:
    def __init__(self):
        self.writes = []
        self.deleted = []

    def upsert(self, chunks, *, user_id):
        self.writes.extend(chunks)
        return len(chunks)

    def delete(self, *, run_id, user_id):
        self.deleted.append(staging_collection_name(run_id, user_id))


class ApiStaticExecutor:
    def __init__(self, strategy_id):
        self.strategy_id = strategy_id

    def execute(self, source, *, profile, run_id):
        return (
            KnowledgeChunk(
                chunk_id=make_chunk_id(
                    run_id=run_id,
                    source_hash=profile.source_hash,
                    strategy_id=self.strategy_id,
                    chunk_index=0,
                    locator=profile.source_path,
                ),
                text=source.name,
                run_id=run_id,
                source_path=profile.source_path,
                source_hash=profile.source_hash,
                strategy_id=self.strategy_id,
                chunk_index=0,
            ),
        )


def _static_registry():
    return {
        strategy_id: ApiStaticExecutor(strategy_id)
        for strategy_id in STRATEGY_CATALOG
    }


def test_plan_folder_endpoint_requires_authentication():
    app = FastAPI()
    app.include_router(knowledge_plan.router)

    response = TestClient(app).post("/api/v1/knowledge/plan-folder", json={"path": "fixtures"})

    assert response.status_code == 401


def test_run_list_endpoint_requires_authentication():
    app = FastAPI()
    app.include_router(knowledge_plan.router)

    response = TestClient(app).get("/api/v1/knowledge/runs")

    assert response.status_code == 401


def test_run_list_endpoint_returns_only_current_tenant_runs(tmp_path, monkeypatch):
    app = FastAPI()
    app.include_router(knowledge_plan.router)
    app.dependency_overrides[get_current_user] = lambda: {"user_id": 42}
    monkeypatch.setattr(
        knowledge_plan, "_database_path", lambda: tmp_path / "audit.sqlite3"
    )
    client = TestClient(app)
    planned = client.post(
        "/api/v1/knowledge/plan-folder",
        json={"path": "fixtures"},    ).json()

    response = client.get("/api/v1/knowledge/runs", params={"limit": 20})

    assert response.status_code == 200
    assert [item["run_id"] for item in response.json()["items"]] == [planned["run_id"]]
    assert response.json()["next_cursor"] is None


def test_run_list_endpoint_rejects_invalid_cursor(tmp_path, monkeypatch):
    app = FastAPI()
    app.include_router(knowledge_plan.router)
    app.dependency_overrides[get_current_user] = lambda: {"user_id": 42}
    monkeypatch.setattr(
        knowledge_plan, "_database_path", lambda: tmp_path / "audit.sqlite3"
    )

    response = TestClient(app).get(
        "/api/v1/knowledge/runs", params={"cursor": "invalid"}
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "invalid_run_cursor"


def test_plan_folder_endpoint_returns_dry_run_without_vector_writes(tmp_path, monkeypatch):
    app = FastAPI()
    app.include_router(knowledge_plan.router)
    app.dependency_overrides[get_current_user] = lambda: {"user_id": 42}
    monkeypatch.setattr(knowledge_plan, "_database_path", lambda: tmp_path / "audit.sqlite3")

    response = TestClient(app).post("/api/v1/knowledge/plan-folder", json={"path": "fixtures"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["dry_run"] is True
    assert payload["vector_store_writes"] == 0
    assert payload["document_count"] == 7


def test_plan_folder_endpoint_does_not_expose_agent_attempt(tmp_path, monkeypatch):
    app = FastAPI()
    app.include_router(knowledge_plan.router)
    app.dependency_overrides[get_current_user] = lambda: {"user_id": 42}
    monkeypatch.setattr(knowledge_plan, "_database_path", lambda: tmp_path / "audit.sqlite3")

    payload = TestClient(app).post(
        "/api/v1/knowledge/plan-folder", json={"path": "fixtures"}
    ).json()
    assert all("agent_attempt" not in document for document in payload["documents"])


def test_run_can_be_read_and_approved_without_vector_writes(tmp_path, monkeypatch):
    knowledge_root = tmp_path / "knowledge"
    shutil.copytree(SOURCE_KNOWLEDGE / "fixtures", knowledge_root / "fixtures")
    app = FastAPI()
    app.include_router(knowledge_plan.router)
    app.dependency_overrides[get_current_user] = lambda: {"user_id": 42}
    monkeypatch.setattr(knowledge_plan, "_KNOWLEDGE_ROOT", knowledge_root)
    monkeypatch.setattr(knowledge_plan, "_database_path", lambda: tmp_path / "audit.sqlite3")

    planned = TestClient(app).post(
        "/api/v1/knowledge/plan-folder",
        json={"path": "fixtures"},    )
    run_id = planned.json()["run_id"]

    saved = TestClient(app).get(f"/api/v1/knowledge/runs/{run_id}")
    approved = TestClient(app).post(f"/api/v1/knowledge/runs/{run_id}/approve")

    assert saved.status_code == 200
    assert saved.json()["status"] == "review_required"
    assert approved.status_code == 200
    assert approved.json()["status"] == "approved"
    assert approved.json()["vector_store_writes"] == 0


def test_planned_run_detail_restores_documents_for_current_tenant(tmp_path, monkeypatch):
    knowledge_root = tmp_path / "knowledge"
    shutil.copytree(SOURCE_KNOWLEDGE / "fixtures", knowledge_root / "fixtures")
    app = FastAPI()
    app.include_router(knowledge_plan.router)
    current = {"user_id": 42}
    app.dependency_overrides[get_current_user] = lambda: current
    monkeypatch.setattr(knowledge_plan, "_KNOWLEDGE_ROOT", knowledge_root)
    monkeypatch.setattr(
        knowledge_plan, "_database_path", lambda: tmp_path / "audit.sqlite3"
    )
    client = TestClient(app)
    planned = client.post(
        "/api/v1/knowledge/plan-folder",
        json={"path": "fixtures"},    ).json()

    restored = client.get(f"/api/v1/knowledge/runs/{planned['run_id']}/plan")
    current["user_id"] = 99
    hidden = client.get(f"/api/v1/knowledge/runs/{planned['run_id']}/plan")

    assert restored.status_code == 200
    assert restored.json() == planned
    assert hidden.status_code == 404


def test_approve_endpoint_returns_conflict_after_source_change(tmp_path, monkeypatch):
    knowledge_root = tmp_path / "knowledge"
    shutil.copytree(SOURCE_KNOWLEDGE / "fixtures", knowledge_root / "fixtures")
    app = FastAPI()
    app.include_router(knowledge_plan.router)
    app.dependency_overrides[get_current_user] = lambda: {"user_id": 42}
    monkeypatch.setattr(knowledge_plan, "_KNOWLEDGE_ROOT", knowledge_root)
    monkeypatch.setattr(knowledge_plan, "_database_path", lambda: tmp_path / "audit.sqlite3")
    client = TestClient(app)
    planned = client.post(
        "/api/v1/knowledge/plan-folder",
        json={"path": "fixtures"},    )
    run_id = planned.json()["run_id"]
    (knowledge_root / "fixtures" / "clean-policy.md").write_text(
        "changed", encoding="utf-8"
    )

    response = client.post(f"/api/v1/knowledge/runs/{run_id}/approve")

    assert response.status_code == 409
    assert response.json()["detail"]["status"] == "invalidated"


def test_run_endpoint_hides_other_tenants_runs(tmp_path, monkeypatch):
    knowledge_root = tmp_path / "knowledge"
    shutil.copytree(SOURCE_KNOWLEDGE / "fixtures", knowledge_root / "fixtures")
    app = FastAPI()
    app.include_router(knowledge_plan.router)
    current = {"user_id": 42}
    app.dependency_overrides[get_current_user] = lambda: current
    monkeypatch.setattr(knowledge_plan, "_KNOWLEDGE_ROOT", knowledge_root)
    monkeypatch.setattr(knowledge_plan, "_database_path", lambda: tmp_path / "audit.sqlite3")
    client = TestClient(app)
    planned = client.post(
        "/api/v1/knowledge/plan-folder",
        json={"path": "fixtures"},    )
    current["user_id"] = 99

    response = client.get(f"/api/v1/knowledge/runs/{planned.json()['run_id']}")

    assert response.status_code == 404


def test_approved_run_can_execute_to_evaluating(tmp_path, monkeypatch):
    knowledge_root = tmp_path / "knowledge"
    shutil.copytree(SOURCE_KNOWLEDGE / "fixtures", knowledge_root / "fixtures")
    app = FastAPI()
    app.include_router(knowledge_plan.router)
    app.dependency_overrides[get_current_user] = lambda: {"user_id": 42}
    database = tmp_path / "audit.sqlite3"
    monkeypatch.setattr(knowledge_plan, "_KNOWLEDGE_ROOT", knowledge_root)
    monkeypatch.setattr(knowledge_plan, "_database_path", lambda: database)
    monkeypatch.setattr(knowledge_plan, "build_executor_registry", _static_registry)
    store = RecordingStagingStore()
    monkeypatch.setattr(knowledge_plan, "StagingStore", lambda: store)
    client = TestClient(app)
    planned = client.post(
        "/api/v1/knowledge/plan-folder",
        json={"path": "fixtures"},    )
    run_id = planned.json()["run_id"]
    assert client.post(f"/api/v1/knowledge/runs/{run_id}/approve").status_code == 200

    response = client.post(f"/api/v1/knowledge/runs/{run_id}/execute")

    assert response.status_code == 200
    assert response.json()["status"] == "evaluating"
    assert response.json()["staging_collection"].startswith("kr_")
    assert response.json()["vector_store_writes"] == len(store.writes)


def test_unapproved_run_returns_conflict_without_initializing_chroma(tmp_path, monkeypatch):
    knowledge_root = tmp_path / "knowledge"
    shutil.copytree(SOURCE_KNOWLEDGE / "fixtures", knowledge_root / "fixtures")
    app = FastAPI()
    app.include_router(knowledge_plan.router)
    app.dependency_overrides[get_current_user] = lambda: {"user_id": 42}
    monkeypatch.setattr(knowledge_plan, "_KNOWLEDGE_ROOT", knowledge_root)
    monkeypatch.setattr(
        knowledge_plan, "_database_path", lambda: tmp_path / "audit.sqlite3"
    )
    client = TestClient(app)
    planned = client.post(
        "/api/v1/knowledge/plan-folder",
        json={"path": "fixtures"},    )

    response = client.post(
        f"/api/v1/knowledge/runs/{planned.json()['run_id']}/execute"
    )

    assert response.status_code == 409


def test_evaluate_report_promote_active_and_rollback_endpoints(tmp_path, monkeypatch):
    app = FastAPI()
    app.include_router(knowledge_plan.router)
    app.dependency_overrides[get_current_user] = lambda: {"user_id": 42}
    monkeypatch.setattr(
        knowledge_plan, "_database_path", lambda: tmp_path / "audit.sqlite3"
    )
    report = EvaluationReport(
        attempt_id="attempt-1", run_id="run-1", status="passed",
        dataset_version="rag-retrieval.v1", source_hit_rate_at_5=1,
        locator_hit_rate_at_5=1, mean_reciprocal_rank=1,
        mean_ndcg_at_5=1, expected_vector_count=1,
        actual_vector_count=1, duration_ms=1,
    )
    promoted = ActiveIndexVersion(
        run_id="run-1", collection_name="kr_active", generation=1,
        legacy=False, previous_collection_name="user_42",
    )
    rolled_back = ActiveIndexVersion(
        run_id=None, collection_name="user_42", generation=2, legacy=True,
    )
    monkeypatch.setattr(knowledge_plan, "load_evaluation_cases", lambda path: ())
    monkeypatch.setattr(knowledge_plan, "evaluate_run", lambda *a, **k: report)
    monkeypatch.setattr(
        knowledge_plan, "get_evaluation_report", lambda *a, **k: report
    )
    monkeypatch.setattr(knowledge_plan, "promote_run", lambda *a, **k: promoted)
    monkeypatch.setattr(
        knowledge_plan, "get_active_index", lambda *a, **k: promoted
    )
    monkeypatch.setattr(
        knowledge_plan, "rollback_run", lambda *a, **k: rolled_back
    )
    monkeypatch.setattr(knowledge_plan, "StagingStore", lambda: object())
    client = TestClient(app)

    assert client.post("/api/v1/knowledge/runs/run-1/evaluate").json() == report.model_dump(mode="json")
    assert client.get("/api/v1/knowledge/runs/run-1/evaluation").status_code == 200
    assert client.post("/api/v1/knowledge/runs/run-1/promote").json()["generation"] == 1
    assert client.get("/api/v1/knowledge/active-version").json()["collection_name"] == "kr_active"
    assert client.post("/api/v1/knowledge/runs/run-1/rollback").json()["legacy"] is True


def test_evaluation_infrastructure_failure_returns_422(tmp_path, monkeypatch):
    app = FastAPI()
    app.include_router(knowledge_plan.router)
    app.dependency_overrides[get_current_user] = lambda: {"user_id": 42}
    monkeypatch.setattr(
        knowledge_plan, "_database_path", lambda: tmp_path / "audit.sqlite3"
    )
    monkeypatch.setattr(knowledge_plan, "load_evaluation_cases", lambda path: ())
    monkeypatch.setattr(knowledge_plan, "StagingStore", lambda: object())
    monkeypatch.setattr(
        knowledge_plan,
        "evaluate_run",
        lambda *a, **k: EvaluationReport(
            attempt_id="attempt-failed", run_id="run-1", status="failed",
            dataset_version="rag-retrieval.v1", source_hit_rate_at_5=0,
            locator_hit_rate_at_5=0, mean_reciprocal_rank=0,
            mean_ndcg_at_5=0, expected_vector_count=1,
            actual_vector_count=0, error_category="storage_error",
            duration_ms=1,
        ),
    )

    response = TestClient(app).post("/api/v1/knowledge/runs/run-1/evaluate")

    assert response.status_code == 422
    assert response.json()["detail"]["error_category"] == "storage_error"
