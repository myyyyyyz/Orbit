"""Human approval orchestration for immutable KnowledgeRun plans."""

from __future__ import annotations

from pathlib import Path

from .models import KnowledgeRunRecord
from .profiler import scan_folder
from .repository import get_run, load_source_hashes, transition_run
from .run_state import transition_status


class RunNotFound(LookupError):
    """Raised when a run is absent or belongs to another tenant."""


class RunStateConflict(RuntimeError):
    """Raised when another request changed the run before this transition."""


def approve_run(
    run_id: str,
    *,
    knowledge_root: Path,
    database_path: Path,
    user_id: int | None,
) -> KnowledgeRunRecord:
    """Approve an unchanged plan, or invalidate it when its source manifest drifted."""

    run = get_run(run_id, database_path=database_path, user_id=user_id)
    if run is None:
        raise RunNotFound(run_id)

    stored_manifest = load_source_hashes(
        run_id, database_path=database_path, user_id=user_id
    )
    resolved_root = knowledge_root.resolve()
    source_folder = (resolved_root / run.folder_path).resolve()
    try:
        source_folder.relative_to(resolved_root)
    except ValueError as exc:
        raise RunStateConflict("KnowledgeRun 文件夹越出知识库根目录") from exc
    source_exists = source_folder.is_dir()
    profiles = scan_folder(source_folder) if source_exists else []
    current_manifest = {
        profile.source_path: profile.source_hash for profile in profiles
    }
    target = (
        "approved"
        if source_exists and current_manifest == stored_manifest
        else "invalidated"
    )
    transition_status(run.status, target)
    changed = transition_run(
        run_id,
        target=target,
        expected=run.status,
        database_path=database_path,
        user_id=user_id,
    )
    if not changed:
        raise RunStateConflict(run_id)

    updated = get_run(run_id, database_path=database_path, user_id=user_id)
    if updated is None:
        raise RunNotFound(run_id)
    return updated
