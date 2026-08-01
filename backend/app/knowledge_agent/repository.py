"""SQLite audit persistence for Knowledge Agent dry runs."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from .models import FolderPlan


def _connect(database_path: Path) -> sqlite3.Connection:
    database_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(database_path)
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def save_plan(plan: FolderPlan, *, database_path: Path, user_id: int | None) -> None:
    """Persist audit data only. This module has no vector-store dependency."""

    with _connect(database_path) as connection:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS knowledge_agent_runs (
                run_id TEXT PRIMARY KEY,
                user_id INTEGER,
                dry_run INTEGER NOT NULL,
                vector_store_writes INTEGER NOT NULL,
                document_count INTEGER NOT NULL,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
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
        connection.execute(
            """
            INSERT INTO knowledge_agent_runs
                (run_id, user_id, dry_run, vector_store_writes, document_count)
            VALUES (?, ?, ?, ?, ?)
            """,
            (plan.run_id, user_id, 1, 0, plan.document_count),
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
