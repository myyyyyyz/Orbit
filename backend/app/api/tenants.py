"""组织（租户）管理路由: /api/v1/tenants/*

角色口径
--------
- ``owner``  ：创建者。改名、轮换邀请码、调整成员角色（含最后一个 owner 保护）
- ``admin``  ：可改名、轮换邀请码、查看成员
- ``member`` ：只读（查看组织信息与成员列表）

平台级 ``admin``（`users.role`）与租户内角色是两套权限，互不继承：
把平台管理员当成"所有组织的 owner"会让任何一个组织都能被全局运维账号接管，
而那正是多租户最不该出现的能力。
"""

from typing import Optional

from fastapi import APIRouter, Body, Depends, HTTPException

from ..logging_config import get_logger
from ..middleware.auth import get_current_user, require_tenant_role
from ..multitenant import (
    TENANT_ROLES,
    TenantError,
    collections_for,
    list_members,
    rename_tenant,
    rotate_invite_code,
    tenant_summary,
    update_member_role,
)

router = APIRouter(prefix="/api/v1/tenants", tags=["tenants"])
logger = get_logger(__name__)


def _require_tenant(current_user: dict) -> str:
    tenant_id = current_user.get("tenant_id")
    if not tenant_id:
        raise HTTPException(403, "当前账号未归属任何组织")
    return tenant_id


@router.get("/me")
def api_my_tenant(current_user: dict = Depends(get_current_user)):
    """当前用户所属组织的概览（名称 / 配额 / 邀请码 / 成员数 / 可用知识库）。"""
    tenant_id = _require_tenant(current_user)
    try:
        summary = tenant_summary(tenant_id)
    except TenantError as exc:
        raise HTTPException(404, str(exc)) from exc

    summary["my_role"] = current_user.get("tenant_role")
    summary["my_user_id"] = current_user.get("user_id")
    summary["collections"] = collections_for(tenant_id, current_user.get("user_id"))
    return summary


@router.get("/me/members")
def api_tenant_members(current_user: dict = Depends(get_current_user)):
    """组织成员列表（不含任何凭据字段）。"""
    tenant_id = _require_tenant(current_user)
    members = list_members(tenant_id)
    return {
        "tenant_id": tenant_id,
        "count": len(members),
        "members": members,
        "roles": list(TENANT_ROLES),
    }


@router.patch("/me")
def api_rename_tenant(
    body: dict = Body(...),
    current_user: dict = Depends(require_tenant_role("owner", "admin")),
):
    """修改组织名称（owner / admin）。"""
    tenant_id = _require_tenant(current_user)
    try:
        tenant = rename_tenant(tenant_id, body.get("name", ""))
    except TenantError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"status": "ok", "id": tenant["id"], "name": tenant["name"]}


@router.post("/me/invite-code")
def api_rotate_invite_code(
    current_user: dict = Depends(require_tenant_role("owner", "admin")),
):
    """轮换邀请码（owner / admin）。旧码立即失效。"""
    tenant_id = _require_tenant(current_user)
    try:
        code = rotate_invite_code(tenant_id)
    except TenantError as exc:
        raise HTTPException(400, str(exc)) from exc
    logger.info("invite_code_rotated", tenant_id=tenant_id,
                by_user=current_user.get("user_id"))
    return {"status": "ok", "invite_code": code}


@router.patch("/me/members/{user_id}")
def api_update_member_role(
    user_id: int,
    body: dict = Body(...),
    current_user: dict = Depends(require_tenant_role("owner")),
):
    """调整成员在组织内的角色（仅 owner）。

    内置保护：不能把**最后一个 owner** 降级，否则组织再没人能管理成员与配置。
    """
    tenant_id = _require_tenant(current_user)
    tenant_role = (body.get("tenant_role") or "").strip()
    if tenant_role not in TENANT_ROLES:
        raise HTTPException(400, f"tenant_role 必须是 {', '.join(TENANT_ROLES)}")
    try:
        member = update_member_role(tenant_id, user_id, tenant_role)
    except TenantError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"status": "ok", "member": member}
