"""Atomic active-index promotion and rollback for Knowledge Agent runs."""

from collections.abc import Callable
from typing import Optional
from pathlib import Path
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from ..config import settings
from .evaluation_repository import _ensure_evaluation_schema
from .repository import _connect, _ensure_schema
from .staging_store import staging_collection_name


class ReleaseConflict(RuntimeError):
    """A safe, stable reason why promotion or rollback was refused."""


class ActiveIndexVersion(BaseModel):
    model_config = ConfigDict(frozen=True)

    run_id: Optional[str]
    collection_name: str
    generation: int = Field(ge=0)
    legacy: bool
    previous_run_id: Optional[str] = None
    previous_collection_name: Optional[str] = None


def _tenant_key(user_id: Optional[int]) -> str:
    # 匿名（user_id=None）使用独立键 "anon"，不再复用 "global"。
    # 历史版本把所有未登录请求归到 "global"，等于让匿名访客共享同一份
    # active index / release 记录；改用独立键后，匿名的读写只落在匿名空间，
    # 与任何登录用户、以及历史遗留的 global 记录彻底隔离。
    return "anon" if user_id is None else str(user_id)


def _legacy_collection(user_id: Optional[int]) -> str:
    # 匿名用户回退到独立的匿名沙箱，而不是全局 `documents` 库——
    # 否则未登录访客会读到（并可经由 upload/delete 改写）全局共享空间。
    return f"user_{user_id}" if user_id is not None else settings.ANON_COLLECTION


def _ensure_release_schema(connection) -> None:
    _ensure_schema(connection)
    _ensure_evaluation_schema(connection)
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS knowledge_active_indexes (
            tenant_key TEXT PRIMARY KEY,
            user_id INTEGER,
            run_id TEXT,
            collection_name TEXT NOT NULL,
            generation INTEGER NOT NULL,
            updated_at TEXT NOT NULL DEFAULT (datetime('now')),
            FOREIGN KEY (run_id) REFERENCES knowledge_agent_runs(run_id)
        );
        CREATE TABLE IF NOT EXISTS knowledge_index_releases (
            release_id TEXT PRIMARY KEY,
            tenant_key TEXT NOT NULL,
            user_id INTEGER,
            run_id TEXT NOT NULL UNIQUE,
            collection_name TEXT NOT NULL,
            previous_run_id TEXT,
            previous_collection_name TEXT NOT NULL,
            status TEXT NOT NULL,
            promoted_at TEXT NOT NULL DEFAULT (datetime('now')),
            rolled_back_at TEXT,
            FOREIGN KEY (run_id) REFERENCES knowledge_agent_runs(run_id)
        );
        """
    )


def _read_active(connection, user_id: Optional[int]) -> ActiveIndexVersion:
    row = connection.execute(
        """
        SELECT active.run_id, active.collection_name, active.generation,
               releases.previous_run_id, releases.previous_collection_name
        FROM knowledge_active_indexes AS active
        LEFT JOIN knowledge_index_releases AS releases
          ON releases.run_id = active.run_id
        WHERE active.tenant_key = ?
        """,
        (_tenant_key(user_id),),
    ).fetchone()
    if row is None:
        return ActiveIndexVersion(
            run_id=None,
            collection_name=_legacy_collection(user_id),
            generation=0,
            legacy=True,
        )
    return ActiveIndexVersion(
        run_id=row[0], collection_name=row[1], generation=row[2],
        legacy=row[0] is None, previous_run_id=row[3],
        previous_collection_name=row[4],
    )


def get_active_index(
    *, user_id: Optional[int], database_path: Path
) -> ActiveIndexVersion:
    with _connect(database_path) as connection:
        _ensure_release_schema(connection)
        return _read_active(connection, user_id)


def promote_run(
    run_id: str,
    *,
    database_path: Path,
    user_id: Optional[int],
    collection_exists: Callable[[str], bool],
) -> ActiveIndexVersion:
    collection_name = staging_collection_name(run_id, user_id)
    with _connect(database_path) as connection:
        _ensure_release_schema(connection)
        connection.execute("BEGIN IMMEDIATE")
        run = connection.execute(
            "SELECT status, staging_collection FROM knowledge_agent_runs "
            "WHERE run_id = ? AND user_id IS ?",
            (run_id, user_id),
        ).fetchone()
        if run is None:
            raise ReleaseConflict("run_not_found")
        if run[0] != "evaluating":
            raise ReleaseConflict("run_not_evaluating")
        if run[1] != collection_name:
            raise ReleaseConflict("staging_collection_mismatch")
        if not collection_exists(collection_name):
            raise ReleaseConflict("staging_collection_missing")
        report = connection.execute(
            "SELECT status FROM knowledge_evaluation_runs "
            "WHERE run_id = ? AND user_id IS ?",
            (run_id, user_id),
        ).fetchone()
        if report is None or report[0] != "passed":
            raise ReleaseConflict("evaluation_not_passed")

        previous = _read_active(connection, user_id)
        connection.execute(
            """INSERT INTO knowledge_index_releases
               (release_id, tenant_key, user_id, run_id, collection_name,
                previous_run_id, previous_collection_name, status)
               VALUES (?, ?, ?, ?, ?, ?, ?, 'active')""",
            (
                uuid4().hex, _tenant_key(user_id), user_id, run_id,
                collection_name, previous.run_id, previous.collection_name,
            ),
        )
        generation = previous.generation + 1
        connection.execute(
            """INSERT INTO knowledge_active_indexes
               (tenant_key, user_id, run_id, collection_name, generation)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(tenant_key) DO UPDATE SET
                 user_id=excluded.user_id, run_id=excluded.run_id,
                 collection_name=excluded.collection_name,
                 generation=excluded.generation, updated_at=datetime('now')""",
            (_tenant_key(user_id), user_id, run_id, collection_name, generation),
        )
        cursor = connection.execute(
            "UPDATE knowledge_agent_runs SET status='promoted', "
            "updated_at=datetime('now') WHERE run_id=? AND user_id IS ? "
            "AND status='evaluating'",
            (run_id, user_id),
        )
        if cursor.rowcount != 1:
            raise ReleaseConflict("concurrent_run_update")
        return ActiveIndexVersion(
            run_id=run_id, collection_name=collection_name,
            generation=generation, legacy=False,
            previous_run_id=previous.run_id,
            previous_collection_name=previous.collection_name,
        )


def rollback_run(
    run_id: str,
    *,
    database_path: Path,
    user_id: Optional[int],
    collection_exists: Callable[[str], bool],
) -> ActiveIndexVersion:
    with _connect(database_path) as connection:
        _ensure_release_schema(connection)
        connection.execute("BEGIN IMMEDIATE")
        current = _read_active(connection, user_id)
        if current.run_id != run_id:
            raise ReleaseConflict("run_not_active")
        release = connection.execute(
            """SELECT previous_run_id, previous_collection_name, status
               FROM knowledge_index_releases
               WHERE run_id = ? AND tenant_key = ?""",
            (run_id, _tenant_key(user_id)),
        ).fetchone()
        if release is None:
            raise ReleaseConflict("release_not_found")
        if release[2] != "active":
            raise ReleaseConflict("release_not_active")
        previous_run_id, previous_collection = release[0], release[1]
        if not collection_exists(previous_collection):
            raise ReleaseConflict("rollback_target_missing")

        generation = current.generation + 1
        connection.execute(
            """UPDATE knowledge_active_indexes
               SET run_id=?, collection_name=?, generation=?,
                   updated_at=datetime('now') WHERE tenant_key=?""",
            (
                previous_run_id, previous_collection, generation,
                _tenant_key(user_id),
            ),
        )
        connection.execute(
            """UPDATE knowledge_index_releases
               SET status='rolled_back', rolled_back_at=datetime('now')
               WHERE run_id=? AND tenant_key=? AND status='active'""",
            (run_id, _tenant_key(user_id)),
        )
        cursor = connection.execute(
            "UPDATE knowledge_agent_runs SET status='rolled_back', "
            "updated_at=datetime('now') WHERE run_id=? AND user_id IS ? "
            "AND status='promoted'",
            (run_id, user_id),
        )
        if cursor.rowcount != 1:
            raise ReleaseConflict("concurrent_run_update")
        return _read_active(connection, user_id)
