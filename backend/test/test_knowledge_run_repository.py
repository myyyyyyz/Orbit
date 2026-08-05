import sqlite3
from pathlib import Path

from app.knowledge_agent.pipeline import plan_folder
from app.knowledge_agent.repository import get_run, transition_run


FIXTURES = Path(__file__).resolve().parents[2] / "knowledge" / "fixtures"


def test_get_run_returns_none_before_audit_schema_exists(tmp_path):
    assert get_run(
        "missing-run",
        database_path=tmp_path / "new.sqlite3",
        user_id=7,
    ) is None


def test_get_run_migrates_a_legacy_dry_run_schema(tmp_path):
    database_path = tmp_path / "legacy.sqlite3"
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            """
            CREATE TABLE knowledge_agent_runs (
                run_id TEXT PRIMARY KEY,
                user_id INTEGER,
                dry_run INTEGER NOT NULL,
                vector_store_writes INTEGER NOT NULL,
                document_count INTEGER NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            INSERT INTO knowledge_agent_runs
                (run_id, user_id, dry_run, vector_store_writes, document_count, created_at)
            VALUES ('legacy-run', 7, 1, 0, 2, '2026-08-01 00:00:00')
            """
        )

    migrated = get_run("legacy-run", database_path=database_path, user_id=7)

    assert migrated is not None
    assert migrated.folder_path == "."
    assert migrated.status == "planned"


def test_plan_persists_initial_status_and_relative_folder_path(tmp_path):
    database_path = tmp_path / "audit.sqlite3"

    plan = plan_folder(
        FIXTURES,
        knowledge_root=FIXTURES.parent,
        database_path=database_path,
        user_id=7,
    )

    saved = get_run(plan.run_id, database_path=database_path, user_id=7)
    assert saved is not None
    assert saved.status == "review_required"
    assert saved.status == plan.status
    assert saved.folder_path == "fixtures"
    assert saved.vector_store_writes == 0


def test_transition_run_uses_expected_status_for_atomic_update(tmp_path):
    database_path = tmp_path / "audit.sqlite3"
    plan = plan_folder(
        FIXTURES,
        knowledge_root=FIXTURES.parent,
        database_path=database_path,
        user_id=7,
    )

    assert transition_run(
        plan.run_id,
        target="approved",
        expected=plan.status,
        database_path=database_path,
        user_id=7,
    ) is True
    assert transition_run(
        plan.run_id,
        target="approved",
        expected=plan.status,
        database_path=database_path,
        user_id=7,
    ) is False
    assert get_run(plan.run_id, database_path=database_path, user_id=7).status == "approved"


def test_get_run_does_not_cross_tenant_boundary(tmp_path):
    database_path = tmp_path / "audit.sqlite3"
    plan = plan_folder(
        FIXTURES,
        knowledge_root=FIXTURES.parent,
        database_path=database_path,
        user_id=7,
    )

    assert get_run(plan.run_id, database_path=database_path, user_id=8) is None
