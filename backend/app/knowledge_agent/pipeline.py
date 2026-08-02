"""The non-ingesting Knowledge Agent folder planning pipeline."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any, Protocol
from uuid import uuid4

from .evidence import read_evidence
from .models import AgentAttempt, CorpusProfile, FolderPlan, PlannedDocument
from .profiler import scan_folder
from .repository import save_plan
from .selector import select_strategy


class KnowledgeAgent(Protocol):
    def recommend(self, profile: CorpusProfile, evidence: str) -> AgentAttempt: ...


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
    agent: KnowledgeAgent | None = None,
) -> FolderPlan:
    """Profile and select strategies without creating chunks or vectors."""

    folder = folder.resolve()
    knowledge_root = knowledge_root.resolve()
    _assert_descendant(folder, knowledge_root)
    profiles = scan_folder(folder)
    suggestions = agent_suggestions or {}
    documents: list[PlannedDocument] = []
    for profile in profiles:
        suggestion = suggestions.get(profile.source_path)
        attempt = None
        if suggestion is None and agent is not None:
            evidence = read_evidence(folder / profile.source_path)
            attempt = agent.recommend(profile, evidence)
            suggestion = attempt.suggestion if attempt.status == "success" else None
        documents.append(
            PlannedDocument(
                profile=profile,
                decision=select_strategy(profile, suggestion),
                agent_attempt=attempt,
            )
        )
    plan = FolderPlan(
        run_id=uuid4().hex,
        document_count=len(documents),
        documents=tuple(documents),
    )
    save_plan(plan, database_path=database_path, user_id=user_id)
    return plan
