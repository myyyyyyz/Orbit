"""Atomic active-index promotion and rollback for Knowledge Agent runs.

多租户口径
----------
- 版本登记表按 **TenantScope** 归属（`tenant_key = scope.storage_key`），
  与它指向的 Collection 粒度保持一致：组织共享库一套版本、每位成员的
  私有库各自一套版本。历史实现按 `user_id` 归属，与"组织共享知识库"的
  产品语义不符（同事之间看不到彼此的索引版本切换）。
- `knowledge_agent_runs` 表仍按 `user_id` 归属（run 是"谁发起的一次摄取"），
  由 `scope.user_id` 提供。这两个维度不同但都不缺：run 记发起人，
  版本记作用域。
"""

from collections.abc import Callable
from typing import Optional
from pathlib import Path
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from ..multitenant.context import TenantScope, get_current_scope
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


def _resolve(scope: Optional[TenantScope]) -> TenantScope:
    return scope if scope is not None else get_current_scope()


def _tenant_key(scope: TenantScope) -> str:
    """版本登记表的归属键。

    匿名（tenant_id 缺失）用独立键 "anon"，不再复用 "global"——
    历史版本把所有未登录请求归到 "global"，等于让匿名访客共享同一份
    active index / release 记录。
    """
    return scope.storage_key


def _legacy_collection(scope: TenantScope) -> str:
    """尚无版本记录时的默认 Collection —— 由作用域决定，绝不落到全局库。

    ⚠️ 这里是 P0-1（匿名可读写全局库）的成因所在：旧实现写成
    `f"user_{user_id}" if user_id else settings.CHROMA_COLLECTION`，
    未登录访客会读到（并可经由 upload/delete 改写）全局共享空间。
    """
    return scope.collection


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


def _read_active(connection, scope: TenantScope) -> ActiveIndexVersion:
    row = connection.execute(
        """
        SELECT active.run_id, active.collection_name, active.generation,
               releases.previous_run_id, releases.previous_collection_name
        FROM knowledge_active_indexes AS active
        LEFT JOIN knowledge_index_releases AS releases
          ON releases.run_id = active.run_id
        WHERE active.tenant_key = ?
        """,
        (_tenant_key(scope),),
    ).fetchone()
    if row is None:
        return ActiveIndexVersion(
            run_id=None,
            collection_name=_legacy_collection(scope),
            generation=0,
            legacy=True,
        )
    return ActiveIndexVersion(
        run_id=row[0], collection_name=row[1], generation=row[2],
        legacy=row[0] is None, previous_run_id=row[3],
        previous_collection_name=row[4],
    )


def get_active_index(
    *, scope: Optional[TenantScope] = None, database_path: Path
) -> ActiveIndexVersion:
    """读取某作用域当前的 active index 版本（无记录时回退到该作用域默认库）。"""
    resolved = _resolve(scope)
    with _connect(database_path) as connection:
        _ensure_release_schema(connection)
        return _read_active(connection, resolved)


def promote_run(
    run_id: str,
    *,
    database_path: Path,
    scope: Optional[TenantScope] = None,
    collection_exists: Callable[[str], bool],
) -> ActiveIndexVersion:
    resolved = _resolve(scope)
    user_id = resolved.user_id
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

        previous = _read_active(connection, resolved)
        connection.execute(
            """INSERT INTO knowledge_index_releases
               (release_id, tenant_key, user_id, run_id, collection_name,
                previous_run_id, previous_collection_name, status)
               VALUES (?, ?, ?, ?, ?, ?, ?, 'active')""",
            (
                uuid4().hex, _tenant_key(resolved), user_id, run_id,
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
            (_tenant_key(resolved), user_id, run_id, collection_name, generation),
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
    scope: Optional[TenantScope] = None,
    collection_exists: Callable[[str], bool],
) -> ActiveIndexVersion:
    resolved = _resolve(scope)
    user_id = resolved.user_id
    with _connect(database_path) as connection:
        _ensure_release_schema(connection)
        connection.execute("BEGIN IMMEDIATE")
        current = _read_active(connection, resolved)
        if current.run_id != run_id:
            raise ReleaseConflict("run_not_active")
        release = connection.execute(
            """SELECT previous_run_id, previous_collection_name, status
               FROM knowledge_index_releases
               WHERE run_id = ? AND tenant_key = ?""",
            (run_id, _tenant_key(resolved)),
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
                _tenant_key(resolved),
            ),
        )
        connection.execute(
            """UPDATE knowledge_index_releases
               SET status='rolled_back', rolled_back_at=datetime('now')
               WHERE run_id=? AND tenant_key=? AND status='active'""",
            (run_id, _tenant_key(resolved)),
        )
        cursor = connection.execute(
            "UPDATE knowledge_agent_runs SET status='rolled_back', "
            "updated_at=datetime('now') WHERE run_id=? AND user_id IS ? "
            "AND status='promoted'",
            (run_id, user_id),
        )
        if cursor.rowcount != 1:
            raise ReleaseConflict("concurrent_run_update")
        return _read_active(connection, resolved)
