"""The non-ingesting Knowledge Agent folder planning pipeline."""


from pathlib import Path
from typing import Optional
from uuid import uuid4

from .models import CorpusProfile, FolderPlan, PlannedDocument
from .profiler import scan_folder
from .repository import save_plan
from .run_state import initial_status
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
    user_id: Optional[int] = None,
) -> FolderPlan:
    """Profile and select strategies without creating chunks or vectors."""

    folder = folder.resolve()
    knowledge_root = knowledge_root.resolve()
    _assert_descendant(folder, knowledge_root)
    profiles = scan_folder(folder)
    documents: list[PlannedDocument] = []
    for profile in profiles:
        documents.append(
            PlannedDocument(
                profile=profile,
                decision=select_strategy(profile),
            )
        )
    plan = FolderPlan(
        run_id=uuid4().hex,
        folder_path=folder.relative_to(knowledge_root).as_posix(),
        status=initial_status(
            document.decision.requires_review for document in documents
        ),
        document_count=len(documents),
        documents=tuple(documents),
    )
    save_plan(plan, database_path=database_path, user_id=user_id)
    return plan
