"""Execution orchestration from an approved plan into an isolated staging index."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from .approval import (
    RunNotFound,
    RunStateConflict,
    source_manifest_matches,
)
from .executors.base import ExecutionBlocked, StrategyExecutor
from .models import KnowledgeRunRecord
from .repository import (
    get_run,
    load_planned_documents,
    save_execution_result,
    transition_run,
)
from .run_state import transition_status
from .staging_store import EmbeddingFailed, StagingStore, staging_collection_name


_KNOWN_BLOCKED_ERRORS = {"ocr_unavailable", "ocr_empty"}


def _load_result(
    run_id: str, *, database_path: Path, user_id: int | None
) -> KnowledgeRunRecord:
    result = get_run(run_id, database_path=database_path, user_id=user_id)
    if result is None:
        raise RunNotFound(run_id)
    return result


def _mark_failed(
    run_id: str,
    *,
    category: str,
    collection: str,
    staging_store: StagingStore,
    database_path: Path,
    user_id: int | None,
) -> KnowledgeRunRecord:
    try:
        staging_store.delete(run_id=run_id, user_id=user_id)
    except Exception:
        pass
    saved = save_execution_result(
        run_id,
        staging_collection=collection,
        chunk_count=0,
        vector_store_writes=0,
        execution_error=category,
        completed=True,
        database_path=database_path,
        user_id=user_id,
    )
    if not saved:
        raise RunStateConflict(run_id)
    changed = transition_run(
        run_id,
        target="failed",
        expected="indexing",
        database_path=database_path,
        user_id=user_id,
    )
    if not changed:
        raise RunStateConflict(run_id)
    return _load_result(run_id, database_path=database_path, user_id=user_id)


def execute_run(
    run_id: str,
    *,
    knowledge_root: Path,
    database_path: Path,
    user_id: int | None,
    executors: Mapping[str, StrategyExecutor],
    staging_store: StagingStore,
) -> KnowledgeRunRecord:
    """Execute an approved run without touching the active tenant collection."""

    run = _load_result(run_id, database_path=database_path, user_id=user_id)
    transition_status(run.status, "indexing")
    if not source_manifest_matches(
        run,
        knowledge_root=knowledge_root,
        database_path=database_path,
        user_id=user_id,
    ):
        changed = transition_run(
            run_id,
            target="invalidated",
            expected="approved",
            database_path=database_path,
            user_id=user_id,
        )
        if not changed:
            raise RunStateConflict(run_id)
        return _load_result(run_id, database_path=database_path, user_id=user_id)

    changed = transition_run(
        run_id,
        target="indexing",
        expected="approved",
        database_path=database_path,
        user_id=user_id,
    )
    if not changed:
        raise RunStateConflict(run_id)

    collection = staging_collection_name(run_id, user_id)
    started = save_execution_result(
        run_id,
        staging_collection=collection,
        chunk_count=0,
        vector_store_writes=0,
        execution_error=None,
        completed=False,
        database_path=database_path,
        user_id=user_id,
    )
    if not started:
        raise RunStateConflict(run_id)

    source_folder = (knowledge_root.resolve() / run.folder_path).resolve()
    chunk_count = 0
    for document in load_planned_documents(
        run_id, database_path=database_path, user_id=user_id
    ):
        try:
            source = (source_folder / document.profile.source_path).resolve()
            source.relative_to(source_folder)
            executor = executors[document.decision.strategy_id]
            chunks = executor.execute(
                source,
                profile=document.profile,
                run_id=run_id,
            )
        except ExecutionBlocked as exc:
            category = (
                exc.category if exc.category in _KNOWN_BLOCKED_ERRORS else "parse_error"
            )
            return _mark_failed(
                run_id,
                category=category,
                collection=collection,
                staging_store=staging_store,
                database_path=database_path,
                user_id=user_id,
            )
        except Exception:
            return _mark_failed(
                run_id,
                category="parse_error",
                collection=collection,
                staging_store=staging_store,
                database_path=database_path,
                user_id=user_id,
            )

        try:
            written = staging_store.upsert(chunks, user_id=user_id)
            if written != len(chunks):
                raise RuntimeError("partial staging write")
            chunk_count += written
        except EmbeddingFailed:
            return _mark_failed(
                run_id,
                category="embedding_error",
                collection=collection,
                staging_store=staging_store,
                database_path=database_path,
                user_id=user_id,
            )
        except Exception:
            return _mark_failed(
                run_id,
                category="storage_error",
                collection=collection,
                staging_store=staging_store,
                database_path=database_path,
                user_id=user_id,
            )

    saved = save_execution_result(
        run_id,
        staging_collection=collection,
        chunk_count=chunk_count,
        vector_store_writes=chunk_count,
        execution_error=None,
        completed=True,
        database_path=database_path,
        user_id=user_id,
    )
    if not saved:
        raise RunStateConflict(run_id)
    changed = transition_run(
        run_id,
        target="evaluating",
        expected="indexing",
        database_path=database_path,
        user_id=user_id,
    )
    if not changed:
        raise RunStateConflict(run_id)
    return _load_result(run_id, database_path=database_path, user_id=user_id)
