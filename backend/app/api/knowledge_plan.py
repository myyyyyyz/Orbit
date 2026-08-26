"""Authenticated, non-ingesting Knowledge Agent planning endpoint."""


import os
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from ..config import settings
from ..knowledge_agent.adapter import OpenAICompatibleKnowledgeAgent
from ..knowledge_agent.approval import RunNotFound, RunStateConflict, approve_run
from ..knowledge_agent.execution import execute_run
from ..knowledge_agent.evaluation import evaluate_run
from ..knowledge_agent.evaluation_dataset import load_evaluation_cases
from ..knowledge_agent.evaluation_repository import get_evaluation_report
from ..knowledge_agent.executors.registry import build_executor_registry
from ..knowledge_agent.pipeline import plan_folder
from ..knowledge_agent.models import FolderPlan
from ..knowledge_agent.repository import (
    InvalidRunCursor,
    get_run,
    list_runs,
    load_planned_documents,
)
from ..knowledge_agent.releases import (
    ReleaseConflict,
    get_active_index,
    promote_run,
    rollback_run,
)
from ..knowledge_agent.run_state import InvalidRunTransition
from ..knowledge_agent.staging_store import StagingStore, StorageFailed
from ..middleware.auth import get_current_user


router = APIRouter(prefix="/api/v1/knowledge", tags=["knowledge"])
# 知识源根目录：KNOWLEDGE_ROOT 环境变量优先（容器内为 /app/knowledge），否则项目根 knowledge/
# Knowledge Agent 只允许在此目录内规划，越界请求会被 _assert_descendant 拒绝
_KNOWLEDGE_ROOT = Path(
    os.getenv("KNOWLEDGE_ROOT")
    or Path(__file__).resolve().parents[3] / "knowledge"
).resolve()
_EVALUATION_DATASET = _KNOWLEDGE_ROOT / "evals" / "questions.jsonl"


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


@router.get("/runs/{run_id}/plan", response_model=FolderPlan)
def api_get_run_plan(
    run_id: str,
    current_user: dict = Depends(get_current_user),
):
    """Restore the immutable strategy plan for an authenticated tenant."""

    run = get_run(
        run_id,
        database_path=_database_path(),
        user_id=current_user["user_id"],
    )
    if run is None:
        raise HTTPException(status_code=404, detail="KnowledgeRun not found")
    documents = load_planned_documents(
        run_id,
        database_path=_database_path(),
        user_id=current_user["user_id"],
    )
    return FolderPlan(
        run_id=run.run_id,
        folder_path=run.folder_path,
        status=run.status,
        document_count=run.document_count,
        documents=documents,
    )


@router.get("/runs")
def api_list_runs(
    limit: int = Query(default=20, ge=1, le=100),
    cursor: Optional[str] = None,
    current_user: dict = Depends(get_current_user),
):
    """Return one stable, tenant-scoped page for workbench recovery."""

    try:
        return list_runs(
            database_path=_database_path(),
            user_id=current_user["user_id"],
            limit=limit,
            cursor=cursor,
        )
    except InvalidRunCursor as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


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


@router.post("/runs/{run_id}/execute")
def api_execute_run(
    run_id: str,
    current_user: dict = Depends(get_current_user),
):
    """Execute an approved plan into an isolated staging collection."""

    try:
        run = execute_run(
            run_id,
            knowledge_root=_KNOWLEDGE_ROOT,
            database_path=_database_path(),
            user_id=current_user["user_id"],
            executors=build_executor_registry(),
            staging_store=StagingStore(),
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
                "message": "源文件已变化，请重新生成计划后再执行",
            },
        )
    if run.status == "failed":
        raise HTTPException(
            status_code=422,
            detail={
                "status": "failed",
                "execution_error": run.execution_error,
            },
        )
    return run


@router.post("/runs/{run_id}/evaluate")
def api_evaluate_run(
    run_id: str,
    current_user: dict = Depends(get_current_user),
):
    """Evaluate the isolated staging index against the versioned retrieval set."""

    try:
        report = evaluate_run(
            run_id,
            database_path=_database_path(),
            user_id=current_user["user_id"],
            cases=load_evaluation_cases(_EVALUATION_DATASET),
            staging_store=StagingStore(),
        )
    except RunNotFound as exc:
        raise HTTPException(status_code=404, detail="KnowledgeRun 不存在") from exc
    except (InvalidRunTransition, RunStateConflict) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if report.status == "failed":
        raise HTTPException(
            status_code=422,
            detail=report.model_dump(mode="json"),
        )
    return report


@router.get("/runs/{run_id}/evaluation")
def api_get_evaluation(
    run_id: str,
    current_user: dict = Depends(get_current_user),
):
    report = get_evaluation_report(
        run_id,
        database_path=_database_path(),
        user_id=current_user["user_id"],
    )
    if report is None:
        raise HTTPException(status_code=404, detail="评测报告不存在")
    return report


@router.post("/runs/{run_id}/promote")
def api_promote_run(
    run_id: str,
    current_user: dict = Depends(get_current_user),
):
    store = StagingStore()
    try:
        return promote_run(
            run_id,
            database_path=_database_path(),
            user_id=current_user["user_id"],
            collection_exists=lambda name: store.collection_exists(name),
        )
    except ReleaseConflict as exc:
        status_code = 404 if str(exc) == "run_not_found" else 409
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc
    except StorageFailed as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/active-version")
def api_get_active_version(
    current_user: dict = Depends(get_current_user),
):
    return get_active_index(
        user_id=current_user["user_id"], database_path=_database_path()
    )


@router.post("/runs/{run_id}/rollback")
def api_rollback_run(
    run_id: str,
    current_user: dict = Depends(get_current_user),
):
    store = StagingStore()
    try:
        return rollback_run(
            run_id,
            database_path=_database_path(),
            user_id=current_user["user_id"],
            collection_exists=lambda name: store.collection_exists(name),
        )
    except ReleaseConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except StorageFailed as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
