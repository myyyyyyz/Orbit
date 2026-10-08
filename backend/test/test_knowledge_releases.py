import pytest

from app.knowledge_agent.evaluation_models import EvaluationReport
from app.knowledge_agent.evaluation_repository import save_evaluation_report
from app.knowledge_agent.repository import _connect, _ensure_schema, get_run
from app.knowledge_agent.releases import (
    ReleaseConflict,
    get_active_index,
    promote_run,
    rollback_run,
)
from app.knowledge_agent.staging_store import staging_collection_name
from app.multitenant import TenantScope

# 作用域即隔离边界：同一用户的"组织共享库"与"个人私有库"是两套版本
SCOPE_A = TenantScope("org_rel_a", 7, "shared")
SCOPE_OTHER_TENANT = TenantScope("org_rel_b", 8, "shared")


def _run(database, run_id, user_id=7, status="evaluating"):
    with _connect(database) as connection:
        _ensure_schema(connection)
        connection.execute(
            """INSERT INTO knowledge_agent_runs
               (run_id, user_id, folder_path, status, dry_run,
                vector_store_writes, document_count, staging_collection,
                chunk_count)
               VALUES (?, ?, '.', ?, 0, 1, 1, ?, 1)""",
            (run_id, user_id, status, staging_collection_name(run_id, user_id)),
        )


def _passed(database, run_id, user_id=7):
    save_evaluation_report(
        EvaluationReport(
            attempt_id=f"attempt-{run_id}", run_id=run_id, status="passed",
            dataset_version="rag-retrieval.v1", source_hit_rate_at_5=1,
            locator_hit_rate_at_5=1, mean_reciprocal_rank=1,
            mean_ndcg_at_5=1, expected_vector_count=1,
            actual_vector_count=1, duration_ms=1,
        ),
        database_path=database,
        user_id=user_id,
    )


def test_promote_requires_passed_report_and_is_tenant_scoped(tmp_path):
    database = tmp_path / "audit.sqlite3"
    _run(database, "candidate")

    with pytest.raises(ReleaseConflict, match="evaluation_not_passed"):
        promote_run(
            "candidate", database_path=database, scope=SCOPE_A,
            collection_exists=lambda name: True,
        )
    _passed(database, "candidate")
    # 别的租户（user_id=8）不能提升本租户的 run
    with pytest.raises(ReleaseConflict, match="run_not_found"):
        promote_run(
            "candidate", database_path=database, scope=SCOPE_OTHER_TENANT,
            collection_exists=lambda name: True,
        )


def test_promote_and_rollback_switch_active_pointer_atomically(tmp_path):
    database = tmp_path / "audit.sqlite3"
    existing = {SCOPE_A.collection}
    for run_id in ("first", "second"):
        _run(database, run_id)
        _passed(database, run_id)
        existing.add(staging_collection_name(run_id, 7))

    first = promote_run(
        "first", database_path=database, scope=SCOPE_A,
        collection_exists=existing.__contains__,
    )
    # 尚无版本记录时回退到**该作用域**的默认库（组织共享库），不是全局库
    assert first.previous_collection_name == SCOPE_A.collection
    assert first.generation == 1
    second = promote_run(
        "second", database_path=database, scope=SCOPE_A,
        collection_exists=existing.__contains__,
    )
    assert second.generation == 2
    assert second.previous_run_id == "first"

    active = rollback_run(
        "second", database_path=database, scope=SCOPE_A,
        collection_exists=existing.__contains__,
    )
    assert active.run_id == "first"
    assert active.collection_name == staging_collection_name("first", 7)
    assert active.generation == 3
    assert active == get_active_index(scope=SCOPE_A, database_path=database)
    assert get_run("second", database_path=database, user_id=7).status == "rolled_back"


def test_personal_scope_has_its_own_release_registry(tmp_path):
    """组织共享库与个人私有库的版本登记互不干扰。"""
    database = tmp_path / "audit.sqlite3"
    personal = TenantScope("org_rel_a", 7, "personal")
    existing = {SCOPE_A.collection, personal.collection}
    for run_id in ("r1",):
        _run(database, run_id)
        _passed(database, run_id)
        existing.add(staging_collection_name(run_id, 7))

    promoted = promote_run(
        "r1", database_path=database, scope=SCOPE_A,
        collection_exists=existing.__contains__,
    )
    assert promoted.generation == 1

    # 个人作用域仍是"无版本记录"状态
    personal_active = get_active_index(scope=personal, database_path=database)
    assert personal_active.run_id is None
    assert personal_active.legacy is True
    assert personal_active.collection_name == personal.collection


def test_missing_rollback_target_leaves_pointer_unchanged(tmp_path):
    database = tmp_path / "audit.sqlite3"
    _run(database, "candidate")
    _passed(database, "candidate")
    promoted = promote_run(
        "candidate", database_path=database, scope=SCOPE_A,
        collection_exists=lambda name: name != SCOPE_A.collection,
    )

    with pytest.raises(ReleaseConflict, match="rollback_target_missing"):
        rollback_run(
            "candidate", database_path=database, scope=SCOPE_A,
            collection_exists=lambda name: False,
        )
    assert get_active_index(scope=SCOPE_A, database_path=database) == promoted
