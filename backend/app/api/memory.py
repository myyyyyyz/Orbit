"""长期记忆路由: /api/memory/*"""
from fastapi import APIRouter, Body, Depends, HTTPException

from ..memory import (
    save_user_profile, get_user_profile, save_project_context,
    save_conversation_summary, restore_context,
)
from ..middleware.auth import get_current_user

router = APIRouter(prefix="/api/memory", tags=["memory"])


@router.post("/profile")
def api_save_profile(body: dict = Body(...), current_user: dict = Depends(get_current_user)):
    save_user_profile(
        current_user["user_id"],
        role=body.get("role"),
        preferences=body.get("preferences"),
        common_skills=body.get("common_skills"),
        output_style=body.get("output_style"),
    )
    return {"status": "ok", "message": "用户画像已保存"}


@router.get("/profile")
def api_get_profile(current_user: dict = Depends(get_current_user)):
    profile = get_user_profile(current_user["user_id"])
    if not profile:
        raise HTTPException(404, "用户画像不存在")
    return profile


@router.post("/project")
def api_save_project(body: dict = Body(...), current_user: dict = Depends(get_current_user)):
    project_name = body.get("project_name")
    if not project_name:
        raise HTTPException(400, "project_name 不能为空")
    save_project_context(
        current_user["user_id"], project_name,
        tech_stack=body.get("tech_stack"),
        current_progress=body.get("current_progress"),
        key_decisions=body.get("key_decisions"),
    )
    return {"status": "ok", "message": "项目上下文已保存"}


@router.post("/summary")
def api_save_summary(body: dict = Body(...), current_user: dict = Depends(get_current_user)):
    summary = body.get("summary")
    if not summary:
        raise HTTPException(400, "summary 不能为空")
    save_conversation_summary(current_user["user_id"], summary, body.get("key_points"))
    return {"status": "ok", "message": "对话摘要已保存"}


@router.get("/restore")
def api_restore_context(current_user: dict = Depends(get_current_user)):
    return restore_context(current_user["user_id"])
