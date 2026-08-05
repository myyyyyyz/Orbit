"""Authenticated, non-ingesting Knowledge Agent planning endpoint."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ..config import settings
from ..knowledge_agent.adapter import OpenAICompatibleKnowledgeAgent
from ..knowledge_agent.approval import RunNotFound, RunStateConflict, approve_run
from ..knowledge_agent.pipeline import plan_folder
from ..knowledge_agent.repository import get_run
from ..knowledge_agent.run_state import InvalidRunTransition
from ..middleware.auth import get_current_user


router = APIRouter(prefix="/api/knowledge", tags=["knowledge"])
_KNOWLEDGE_ROOT = Path(__file__).resolve().parents[3] / "knowledge"


class PlanFolderRequest(BaseModel):
    """The relative folder to inspect and optional precomputed Agent suggestions."""

    path: str = Field(min_length=1, description="Path relative to the repository knowledge folder")
    use_agent: bool = True
    agent_suggestions: dict[str, dict[str, Any]] = Field(default_factory=dict)


def _database_path() -> Path:
    database_url = settings.DATABASE_URL
    if not database_url.startswith("sqlite:///"):
        raise ValueError("Knowledge Agent planning currently requires a SQLite DATABASE_URL")
    return Path(database_url.removeprefix("sqlite:///"))


@router.post("/plan-folder")
def api_plan_folder(
    request: PlanFolderRequest,
    current_user: dict = Depends(get_current_user),
):
    """Create an auditable strategy plan; never chunk, embed, or write vectors."""

    relative_path = Path(request.path)
    if relative_path.is_absolute():
        raise HTTPException(status_code=400, detail="path 必须是 knowledge 目录内的相对路径")
    try:
        agent = OpenAICompatibleKnowledgeAgent.from_env() if request.use_agent else None
        plan = plan_folder(
            _KNOWLEDGE_ROOT / relative_path,
            knowledge_root=_KNOWLEDGE_ROOT,
            database_path=_database_path(),
            user_id=current_user["user_id"],
            agent_suggestions=request.agent_suggestions,
            agent=agent,
        )
    except (ValueError, OSError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return plan


@router.get("/runs/{run_id}")
def api_get_run(
    run_id: str,
    current_user: dict = Depends(get_current_user),
):
    """Return a tenant-owned run summary without raw document evidence."""

    run = get_run(
        run_id,
        database_path=_database_path(),
        user_id=current_user["user_id"],
    )
    if run is None:
        raise HTTPException(status_code=404, detail="KnowledgeRun 不存在")
    return run


@router.post("/runs/{run_id}/approve")
def api_approve_run(
    run_id: str,
    current_user: dict = Depends(get_current_user),
):
    """Approve an unchanged plan; source drift permanently invalidates it."""

    try:
        run = approve_run(
            run_id,
            knowledge_root=_KNOWLEDGE_ROOT,
            database_path=_database_path(),
            user_id=current_user["user_id"],
        )
    except RunNotFound as exc:
        raise HTTPException(status_code=404, detail="KnowledgeRun 不存在") from exc
    except (InvalidRunTransition, RunStateConflict) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if run.status == "invalidated":
        raise HTTPException(
            status_code=409,
            detail={
                "status": "invalidated",
                "message": "源文件已变化，请重新生成计划后再审批",
            },
        )
    return run
