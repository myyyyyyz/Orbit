"""SQLite audit persistence for Knowledge Agent runs."""


import base64
from typing import Optional
import binascii
import json
import sqlite3
from pathlib import Path

from .models import (
    CorpusProfile,
    FolderPlan,
    KnowledgeRunRecord,
    KnowledgeRunPage,
    PlannedDocument,
    RunStatus,
    StrategyDecision,
)
from .run_state import transition_status


class InvalidRunCursor(ValueError):
    """Raised for malformed or non-canonical run-list cursors."""


def _connect(database_path: Path) -> sqlite3.Connection:
    database_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(database_path)
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def _ensure_schema(connection: sqlite3.Connection) -> None:
    """Create or incrementally migrate the audit schema for every entry point."""

    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS knowledge_agent_runs (
            run_id TEXT PRIMARY KEY,
            user_id INTEGER,
            folder_path TEXT NOT NULL,
            status TEXT NOT NULL,
            dry_run INTEGER NOT NULL,
            vector_store_writes INTEGER NOT NULL,
            document_count INTEGER NOT NULL,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at TEXT,
            approved_at TEXT
        );
        CREATE TABLE IF NOT EXISTS knowledge_agent_documents (
            run_id TEXT NOT NULL,
            source_path TEXT NOT NULL,
            source_hash TEXT NOT NULL,
            profile_json TEXT NOT NULL,
            decision_json TEXT NOT NULL,
            PRIMARY KEY (run_id, source_path),
            FOREIGN KEY (run_id) REFERENCES knowledge_agent_runs(run_id)
        );
        """
    )
    run_columns = {
        row[1]
        for row in connection.execute(
            "PRAGMA table_info(knowledge_agent_runs)"
        ).fetchall()
    }
    run_migrations = {
        "folder_path": "ALTER TABLE knowledge_agent_runs ADD COLUMN folder_path TEXT NOT NULL DEFAULT '.'",
        "status": "ALTER TABLE knowledge_agent_runs ADD COLUMN status TEXT NOT NULL DEFAULT 'planned'",
        "updated_at": "ALTER TABLE knowledge_agent_runs ADD COLUMN updated_at TEXT",
        "approved_at": "ALTER TABLE knowledge_agent_runs ADD COLUMN approved_at TEXT",
        "staging_collection": "ALTER TABLE knowledge_agent_runs ADD COLUMN staging_collection TEXT",
        "chunk_count": "ALTER TABLE knowledge_agent_runs ADD COLUMN chunk_count INTEGER NOT NULL DEFAULT 0",
        "execution_error": "ALTER TABLE knowledge_agent_runs ADD COLUMN execution_error TEXT",
        "indexing_started_at": "ALTER TABLE knowledge_agent_runs ADD COLUMN indexing_started_at TEXT",
        "indexing_completed_at": "ALTER TABLE knowledge_agent_runs ADD COLUMN indexing_completed_at TEXT",
    }
    for column, statement in run_migrations.items():
        if column not in run_columns:
            connection.execute(statement)

    document_columns = {
        row[1]
        for row in connection.execute(
            "PRAGMA table_info(knowledge_agent_documents)"
        ).fetchall()
    }


def save_plan(plan: FolderPlan, *, database_path: Path, user_id: Optional[int]) -> None:
    """Persist audit data only. This module has no vector-store dependency."""

    with _connect(database_path) as connection:
        _ensure_schema(connection)
        connection.execute(
            """
            INSERT INTO knowledge_agent_runs
                (run_id, user_id, folder_path, status, dry_run, vector_store_writes, document_count)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                plan.run_id,
                user_id,
                plan.folder_path,
                plan.status,
                1,
                0,
                plan.document_count,
            ),
        )
        connection.executemany(
            """
            INSERT INTO knowledge_agent_documents
                (run_id, source_path, source_hash, profile_json, decision_json)
            VALUES (?, ?, ?, ?, ?)
            """,
            [
                (
                    plan.run_id,
                    document.profile.source_path,
                    document.profile.source_hash,
                    document.profile.model_dump_json(),
                    document.decision.model_dump_json(),
                )
                for document in plan.documents
            ],
        )


def get_run(
    run_id: str, *, database_path: Path, user_id: Optional[int]
) -> Optional[KnowledgeRunRecord]:
    """Load one run without exposing records owned by another tenant."""

    with _connect(database_path) as connection:
        _ensure_schema(connection)
        row = connection.execute(
            """
            SELECT run_id, user_id, folder_path, status, dry_run,
                   vector_store_writes, document_count, created_at,
                   updated_at, approved_at, staging_collection, chunk_count,
                   execution_error, indexing_started_at, indexing_completed_at
            FROM knowledge_agent_runs
            WHERE run_id = ? AND user_id IS ?
            """,
            (run_id, user_id),
        ).fetchone()
    if row is None:
        return None
    return KnowledgeRunRecord(
        run_id=row[0],
        user_id=row[1],
        folder_path=row[2],
        status=row[3],
        dry_run=bool(row[4]),
        vector_store_writes=row[5],
        document_count=row[6],
        created_at=row[7],
        updated_at=row[8],
        approved_at=row[9],
        staging_collection=row[10],
        chunk_count=row[11],
        execution_error=row[12],
        indexing_started_at=row[13],
        indexing_completed_at=row[14],
    )


def _encode_run_cursor(created_at: str, run_id: str) -> str:
    payload = json.dumps([created_at, run_id], separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(payload).decode().rstrip("=")


def _decode_run_cursor(cursor: str) -> tuple[str, str]:
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded).decode())
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError, binascii.Error) as exc:
        raise InvalidRunCursor("invalid_run_cursor") from exc
    if (
        not isinstance(payload, list)
        or len(payload) != 2
        or not all(isinstance(item, str) and item for item in payload)
    ):
        raise InvalidRunCursor("invalid_run_cursor")
    return payload[0], payload[1]


def list_runs(
    *,
    database_path: Path,
    user_id: Optional[int],
    limit: int = 20,
    cursor: Optional[str] = None,
) -> KnowledgeRunPage:
    """List one tenant's newest runs with stable keyset pagination."""

    if limit < 1 or limit > 100:
        raise ValueError("invalid_run_limit")
    cursor_values = _decode_run_cursor(cursor) if cursor is not None else None
    with _connect(database_path) as connection:
        _ensure_schema(connection)
        rows = connection.execute(
            """
            SELECT run_id, user_id, folder_path, status, dry_run,
                   vector_store_writes, document_count, created_at,
                   updated_at, approved_at, staging_collection, chunk_count,
                   execution_error, indexing_started_at, indexing_completed_at
            FROM knowledge_agent_runs
            WHERE user_id IS ?
              AND (? IS NULL OR created_at < ? OR (created_at = ? AND run_id < ?))
            ORDER BY created_at DESC, run_id DESC
            LIMIT ?
            """,
            (
                user_id,
                cursor_values[0] if cursor_values else None,
                cursor_values[0] if cursor_values else None,
                cursor_values[0] if cursor_values else None,
                cursor_values[1] if cursor_values else None,
                limit + 1,
            ),
        ).fetchall()
    has_more = len(rows) > limit
    visible = rows[:limit]
    items = tuple(
        KnowledgeRunRecord(
            run_id=row[0], user_id=row[1], folder_path=row[2], status=row[3],
            dry_run=bool(row[4]), vector_store_writes=row[5],
            document_count=row[6], created_at=row[7], updated_at=row[8],
            approved_at=row[9], staging_collection=row[10], chunk_count=row[11],
            execution_error=row[12], indexing_started_at=row[13],
            indexing_completed_at=row[14],
        )
        for row in visible
    )
    next_cursor = None
    if has_more and visible:
        next_cursor = _encode_run_cursor(visible[-1][7], visible[-1][0])
    return KnowledgeRunPage(items=items, next_cursor=next_cursor)


def load_planned_documents(
    run_id: str, *, database_path: Path, user_id: Optional[int]
) -> tuple[PlannedDocument, ...]:
    """Restore the immutable execution inputs without storing document text."""

    with _connect(database_path) as connection:
        _ensure_schema(connection)
        rows = connection.execute(
            """
            SELECT documents.profile_json, documents.decision_json
            FROM knowledge_agent_documents AS documents
            JOIN knowledge_agent_runs AS runs ON runs.run_id = documents.run_id
            WHERE documents.run_id = ? AND runs.user_id IS ?
            ORDER BY documents.source_path
            """,
            (run_id, user_id),
        ).fetchall()
    return tuple(
        PlannedDocument(
            profile=CorpusProfile.model_validate_json(profile_json),
            decision=StrategyDecision.model_validate_json(decision_json),
        )
        for profile_json, decision_json in rows
    )


def save_execution_result(
    run_id: str,
    *,
    staging_collection: str,
    chunk_count: int,
    vector_store_writes: int,
    execution_error: Optional[str],
    completed: bool,
    database_path: Path,
    user_id: Optional[int],
) -> bool:
    """Persist execution audit counters and sanitized outcome only."""

    with _connect(database_path) as connection:
        _ensure_schema(connection)
        cursor = connection.execute(
            """
            UPDATE knowledge_agent_runs
            SET dry_run = 0,
                staging_collection = ?,
                chunk_count = ?,
                vector_store_writes = ?,
                execution_error = ?,
                indexing_started_at = COALESCE(indexing_started_at, datetime('now')),
                indexing_completed_at = CASE
                    WHEN ? THEN datetime('now')
                    ELSE indexing_completed_at
                END,
                updated_at = datetime('now')
            WHERE run_id = ? AND user_id IS ? AND status = 'indexing'
            """,
            (
                staging_collection,
                chunk_count,
                vector_store_writes,
                execution_error,
                int(completed),
                run_id,
                user_id,
            ),
        )
    return cursor.rowcount == 1


def load_source_hashes(
    run_id: str, *, database_path: Path, user_id: Optional[int]
) -> dict[str, str]:
    """Load the immutable source manifest for one tenant-owned run."""

    with _connect(database_path) as connection:
        _ensure_schema(connection)
        rows = connection.execute(
            """
            SELECT documents.source_path, documents.source_hash
            FROM knowledge_agent_documents AS documents
            JOIN knowledge_agent_runs AS runs ON runs.run_id = documents.run_id
            WHERE documents.run_id = ? AND runs.user_id IS ?
            ORDER BY documents.source_path
            """,
            (run_id, user_id),
        ).fetchall()
    return {source_path: source_hash for source_path, source_hash in rows}


def transition_run(
    run_id: str,
    *,
    target: RunStatus,
    expected: RunStatus,
    database_path: Path,
    user_id: Optional[int],
) -> bool:
    """Atomically apply a valid transition when the persisted state is expected."""

    transition_status(expected, target)
    with _connect(database_path) as connection:
        _ensure_schema(connection)
        cursor = connection.execute(
            """
            UPDATE knowledge_agent_runs
            SET status = ?,
                updated_at = datetime('now'),
                approved_at = CASE
                    WHEN ? = 'approved' THEN datetime('now')
                    ELSE approved_at
                END
            WHERE run_id = ? AND user_id IS ? AND status = ?
            """,
            (target, target, run_id, user_id, expected),
        )
    return cursor.rowcount == 1
