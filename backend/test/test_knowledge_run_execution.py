import shutil
from dataclasses import dataclass
from pathlib import Path

import pytest

from app.knowledge_agent.approval import approve_run
from app.knowledge_agent.catalog import STRATEGY_CATALOG
from app.knowledge_agent.chunk_ids import make_chunk_id
from app.knowledge_agent.execution import execute_run
from app.knowledge_agent.executors.base import ExecutionBlocked
from app.knowledge_agent.models import KnowledgeChunk
from app.knowledge_agent.pipeline import plan_folder
from app.knowledge_agent.run_state import InvalidRunTransition
from app.knowledge_agent.staging_store import EmbeddingFailed, staging_collection_name


SOURCE_FIXTURES = Path(__file__).resolve().parents[2] / "knowledge" / "fixtures"


class StaticExecutor:
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
                    locator="static",
                ),
                text=source.name + " knowledge",
                run_id=run_id,
                source_path=profile.source_path,
                source_hash=profile.source_hash,
                strategy_id=self.strategy_id,
                chunk_index=0,
            ),
        )


class FailingExecutor:
    def __init__(self, category):
        self.category = category

    def execute(self, source, *, profile, run_id):
        raise ExecutionBlocked(self.category)


class RecordingStagingStore:
    def __init__(self):
        self.writes = []
        self.deleted = []
        self.active_collection_writes = 0

    def upsert(self, chunks, *, user_id):
        self.writes.extend(chunks)
        return len(chunks)

    def delete(self, *, run_id, user_id):
        self.deleted.append(staging_collection_name(run_id, user_id))


class FailingStagingStore(RecordingStagingStore):
    def upsert(self, chunks, *, user_id):
        raise RuntimeError("raw storage detail must not escape")


class FailingEmbeddingStore(RecordingStagingStore):
    def upsert(self, chunks, *, user_id):
        raise EmbeddingFailed("embedding_error")


@dataclass
class ExecutionContext:
    plan: object
    knowledge_root: Path
    database: Path
    policy: Path
    executors: dict
    store: RecordingStagingStore


@pytest.fixture
def context(tmp_path):
    knowledge_root = tmp_path / "knowledge"
    fixtures = knowledge_root / "fixtures"
    shutil.copytree(SOURCE_FIXTURES, fixtures)
    database = tmp_path / "audit.sqlite3"
    plan = plan_folder(
        fixtures,
        knowledge_root=knowledge_root,
        database_path=database,
        user_id=7,
    )
    executors = {
        strategy_id: StaticExecutor(strategy_id)
        for strategy_id in STRATEGY_CATALOG
    }
    return ExecutionContext(
        plan=plan,
        knowledge_root=knowledge_root,
        database=database,
        policy=fixtures / "clean-policy.md",
        executors=executors,
        store=RecordingStagingStore(),
    )


def _approve(context):
    return approve_run(
        context.plan.run_id,
        knowledge_root=context.knowledge_root,
        database_path=context.database,
        user_id=7,
    )


def _execute(context):
    return execute_run(
        context.plan.run_id,
        knowledge_root=context.knowledge_root,
        database_path=context.database,
        user_id=7,
        executors=context.executors,
        staging_store=context.store,
    )


def test_execute_run_rejects_unapproved_plan(context):
    with pytest.raises(InvalidRunTransition):
        _execute(context)
    assert context.store.writes == []


def test_execute_approved_run_writes_only_staging_and_hands_off_to_evaluation(context):
    _approve(context)

    result = _execute(context)

    assert result.status == "evaluating"
    assert result.dry_run is False
    assert result.vector_store_writes == result.chunk_count
    assert result.chunk_count == context.plan.document_count
    assert result.staging_collection.startswith("kr_")
    assert result.indexing_started_at is not None
    assert result.indexing_completed_at is not None
    assert context.store.active_collection_writes == 0


def test_executor_failure_deletes_staging_and_marks_run_failed(context):
    context.executors["pdf_ocr_review_v1"] = FailingExecutor("ocr_unavailable")
    _approve(context)

    result = _execute(context)

    assert result.status == "failed"
    assert result.execution_error == "ocr_unavailable"
    assert result.vector_store_writes == 0
    assert result.chunk_count == 0
    assert context.store.deleted == [result.staging_collection]


def test_source_change_after_approval_invalidates_before_indexing(context):
    _approve(context)
    context.policy.write_text("changed", encoding="utf-8")

    result = _execute(context)

    assert result.status == "invalidated"
    assert result.dry_run is True
    assert context.store.writes == []
    assert context.store.deleted == []


def test_staging_write_failure_is_sanitized_and_fully_cleaned(context):
    context.store = FailingStagingStore()
    _approve(context)

    result = _execute(context)

    assert result.status == "failed"
    assert result.execution_error == "storage_error"
    assert result.vector_store_writes == 0
    assert result.chunk_count == 0
    assert "raw storage detail" not in result.execution_error
    assert context.store.deleted == [result.staging_collection]


def test_embedding_failure_has_a_distinct_sanitized_category(context):
    context.store = FailingEmbeddingStore()
    _approve(context)

    result = _execute(context)

    assert result.status == "failed"
    assert result.execution_error == "embedding_error"
    assert result.vector_store_writes == 0
    assert context.store.deleted == [result.staging_collection]
