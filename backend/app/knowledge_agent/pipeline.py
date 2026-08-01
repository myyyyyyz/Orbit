"""The non-ingesting Knowledge Agent folder planning pipeline."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any
from uuid import uuid4

from .models import FolderPlan, PlannedDocument
from .profiler import scan_folder
from .repository import save_plan
from .selector import select_strategy


def _assert_descendant(folder: Path, knowledge_root: Path) -> None:
    try:
        folder.resolve().relative_to(knowledge_root.resolve())
    except ValueError as exc:
        raise ValueError("Requested folder is outside the configured knowledge root") from exc


def plan_folder(
    folder: Path,
    *,
    knowledge_root: Path,
    database_path: Path,
    user_id: int | None = None,
    agent_suggestions: Mapping[str, Mapping[str, Any]] | None = None,
) -> FolderPlan:
    """Profile and select strategies without creating chunks or vectors."""

    folder = folder.resolve()
    knowledge_root = knowledge_root.resolve()
    _assert_descendant(folder, knowledge_root)
    profiles = scan_folder(folder)
    suggestions = agent_suggestions or {}
    documents = tuple(
        PlannedDocument(
            profile=profile,
            decision=select_strategy(profile, suggestions.get(profile.source_path)),
        )
        for profile in profiles
    )
    plan = FolderPlan(
        run_id=uuid4().hex,
        document_count=len(documents),
        documents=documents,
    )
    save_plan(plan, database_path=database_path, user_id=user_id)
    return plan
