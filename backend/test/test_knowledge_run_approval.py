import shutil
from pathlib import Path

from app.knowledge_agent.approval import approve_run
from app.knowledge_agent.pipeline import plan_folder


SOURCE_FIXTURES = Path(__file__).resolve().parents[2] / "knowledge" / "fixtures"


def _make_plan(tmp_path):
    knowledge_root = tmp_path / "knowledge"
    fixtures = knowledge_root / "fixtures"
    shutil.copytree(SOURCE_FIXTURES, fixtures)
    database_path = tmp_path / "audit.sqlite3"
    plan = plan_folder(
        fixtures,
        knowledge_root=knowledge_root,
        database_path=database_path,
        user_id=7,
    )
    return plan, fixtures, knowledge_root, database_path


def test_approve_run_when_source_manifest_is_unchanged(tmp_path):
    plan, _, knowledge_root, database_path = _make_plan(tmp_path)

    approved = approve_run(
        plan.run_id,
        knowledge_root=knowledge_root,
        database_path=database_path,
        user_id=7,
    )

    assert approved.status == "approved"
    assert approved.approved_at is not None
    assert approved.vector_store_writes == 0


def test_approve_run_invalidates_plan_when_source_content_changes(tmp_path):
    plan, fixtures, knowledge_root, database_path = _make_plan(tmp_path)
    (fixtures / "clean-policy.md").write_text("changed", encoding="utf-8")

    invalidated = approve_run(
        plan.run_id,
        knowledge_root=knowledge_root,
        database_path=database_path,
        user_id=7,
    )

    assert invalidated.status == "invalidated"
    assert invalidated.approved_at is None


def test_approve_run_invalidates_plan_when_file_is_added(tmp_path):
    plan, fixtures, knowledge_root, database_path = _make_plan(tmp_path)
    (fixtures / "added.md").write_text("new knowledge", encoding="utf-8")

    invalidated = approve_run(
        plan.run_id,
        knowledge_root=knowledge_root,
        database_path=database_path,
        user_id=7,
    )

    assert invalidated.status == "invalidated"


def test_approve_run_invalidates_plan_when_file_is_removed(tmp_path):
    plan, fixtures, knowledge_root, database_path = _make_plan(tmp_path)
    (fixtures / "clean-policy.md").unlink()

    invalidated = approve_run(
        plan.run_id,
        knowledge_root=knowledge_root,
        database_path=database_path,
        user_id=7,
    )

    assert invalidated.status == "invalidated"


def test_approve_run_invalidates_plan_when_folder_is_removed(tmp_path):
    plan, fixtures, knowledge_root, database_path = _make_plan(tmp_path)
    shutil.rmtree(fixtures)

    invalidated = approve_run(
        plan.run_id,
        knowledge_root=knowledge_root,
        database_path=database_path,
        user_id=7,
    )

    assert invalidated.status == "invalidated"


def test_approve_run_does_not_approve_a_removed_empty_folder(tmp_path):
    knowledge_root = tmp_path / "knowledge"
    empty_folder = knowledge_root / "empty"
    empty_folder.mkdir(parents=True)
    database_path = tmp_path / "audit.sqlite3"
    plan = plan_folder(
        empty_folder,
        knowledge_root=knowledge_root,
        database_path=database_path,
        user_id=7,
    )
    shutil.rmtree(empty_folder)

    invalidated = approve_run(
        plan.run_id,
        knowledge_root=knowledge_root,
        database_path=database_path,
        user_id=7,
    )

    assert invalidated.status == "invalidated"
