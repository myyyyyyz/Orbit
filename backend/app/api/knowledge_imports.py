"""Authenticated local-folder imports for the governed Knowledge workflow."""

import os
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Response, UploadFile

from ..config import settings
from ..knowledge_agent.imports import (
    ImportConflict,
    ImportNotFound,
    ImportValidationError,
    complete_import,
    create_import,
    delete_import,
    get_import,
    upload_import_file,
)
from ..middleware.auth import get_current_user


router = APIRouter(prefix="/api/v1/knowledge/imports", tags=["knowledge-imports"])
# 与 knowledge_plan 共享同一解析规则：KNOWLEDGE_ROOT 环境变量优先
_KNOWLEDGE_ROOT = Path(
    os.getenv("KNOWLEDGE_ROOT")
    or Path(__file__).resolve().parents[3] / "knowledge"
).resolve()


def _database_path() -> Path:
    database_url = settings.DATABASE_URL
    if not database_url.startswith("sqlite:///"):
        raise ValueError("Knowledge imports currently require SQLite")
    return Path(database_url.removeprefix("sqlite:///"))


def _raise_import_error(exc: Exception) -> None:
    if isinstance(exc, ImportNotFound):
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if isinstance(exc, ImportConflict):
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if isinstance(exc, ImportValidationError):
        status = 413 if str(exc) in {"file_size_limit", "batch_size_limit", "file_count_limit"} else 400
        raise HTTPException(status_code=status, detail=str(exc)) from exc
    raise exc


@router.post("", status_code=201)
def api_create_import(current_user: dict = Depends(get_current_user)):
    return create_import(
        database_path=_database_path(),
        knowledge_root=_KNOWLEDGE_ROOT,
        user_id=current_user["user_id"],
    )


@router.get("/{import_id}")
def api_get_import(import_id: str, current_user: dict = Depends(get_current_user)):
    batch = get_import(
        import_id,
        database_path=_database_path(),
        user_id=current_user["user_id"],
    )
    if batch is None:
        raise HTTPException(status_code=404, detail="import_not_found")
    return batch


@router.post("/{import_id}/files")
def api_upload_import_file(
    import_id: str,
    relative_path: str = Form(...),
    file: UploadFile = File(...),
    current_user: dict = Depends(get_current_user),
):
    try:
        return upload_import_file(
            import_id,
            relative_path=relative_path,
            stream=file.file,
            database_path=_database_path(),
            knowledge_root=_KNOWLEDGE_ROOT,
            user_id=current_user["user_id"],
        )
    except (ImportNotFound, ImportConflict, ImportValidationError) as exc:
        _raise_import_error(exc)


@router.post("/{import_id}/complete")
def api_complete_import(import_id: str, current_user: dict = Depends(get_current_user)):
    try:
        return complete_import(
            import_id,
            database_path=_database_path(),
            knowledge_root=_KNOWLEDGE_ROOT,
            user_id=current_user["user_id"],
        )
    except (ImportNotFound, ImportConflict, ImportValidationError) as exc:
        _raise_import_error(exc)


@router.delete("/{import_id}", status_code=204)
def api_delete_import(import_id: str, current_user: dict = Depends(get_current_user)):
    try:
        delete_import(
            import_id,
            database_path=_database_path(),
            knowledge_root=_KNOWLEDGE_ROOT,
            user_id=current_user["user_id"],
        )
    except (ImportNotFound, ImportConflict, ImportValidationError) as exc:
        _raise_import_error(exc)
    return Response(status_code=204)
