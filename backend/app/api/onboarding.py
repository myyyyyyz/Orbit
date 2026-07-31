"""新手引导路由: /api/onboarding/*"""
from fastapi import APIRouter, HTTPException

from ..onboarding import get_onboarding_template, get_all_roles, get_role_config

router = APIRouter(prefix="/api/onboarding", tags=["onboarding"])


@router.get("/template")
def api_onboarding_template():
    return get_onboarding_template()


@router.get("/roles")
def api_onboarding_roles():
    return get_all_roles()


@router.get("/roles/{role}")
def api_onboarding_role_config(role: str):
    config = get_role_config(role)
    if not config:
        raise HTTPException(404, f"角色不存在: {role}")
    return config
