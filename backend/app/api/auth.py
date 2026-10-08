"""认证路由: /api/v1/auth/*

令牌模型：
- 登录/注册返回 access_token（短时效）+ refresh_token（长时效）。
- /refresh 用 refresh_token 换发新的一对令牌，并撤销旧的 refresh（轮换）。
- /logout 撤销当前 access 与随请求提交的 refresh，立即失效而非等自然过期。

租户模型（本轮改造）：
- 注册时**必选**落地到一个组织：不传邀请码 → 新建组织并成为 owner；
  传邀请码 → 加入该组织并成为 member。
- 令牌里带 tenant_id / tenant_role，但授权判定一律回查数据库。
"""

from typing import Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Request

from ..logging_config import get_logger
from ..middleware.auth import (
    ACCESS_TOKEN_EXPIRE_MINUTES,
    create_token_pair,
    get_current_user,
    revoke_payload,
    verify_refresh_token,
)
from ..multitenant import (
    TenantError,
    collections_for,
    get_public_user,
    get_tenant,
    join_tenant_by_invite_code,
    login_user,
    register_user,
)
from ..rate_limit import limiter

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])
logger = get_logger(__name__)


def _token_response(result: dict, username: str, tenant_id: Optional[str]) -> dict:
    """把注册/登录结果整理成令牌响应（含组织信息与可用知识库名）。"""
    role = result.get("role")
    tenant_role = result.get("tenant_role")
    user_id = result["user_id"]
    return {
        **create_token_pair(username, user_id, tenant_id, role, tenant_role),
        "user_id": user_id,
        "username": username,
        "role": role,
        "tenant_id": tenant_id,
        "tenant_role": tenant_role,
        "tenant_name": result.get("tenant_name"),
        # 邀请码仅在新建组织时回给 owner（member 拿到也无害，但没必要扩散）
        "invite_code": result.get("invite_code"),
        "collections": result.get("collections") or collections_for(tenant_id, user_id),
    }


@router.post("/register")
@limiter.limit("5/minute")
def api_register(request: Request, body: dict = Body(...)):
    """注册账号并落地到组织。

    body:
        username    必填
        password    必填（≥8 位）
        org_name    可选，新建组织的名称（不传邀请码时生效）
        invite_code 可选，加入已有组织；优先级高于 org_name
    """
    username = (body.get("username") or "").strip()
    password = (body.get("password") or "").strip()
    org_name = (body.get("org_name") or "").strip() or None
    invite_code = (body.get("invite_code") or "").strip() or None

    if not username or not password:
        raise HTTPException(400, "用户名和密码不能为空")
    if len(password) < 8:
        raise HTTPException(400, "密码长度至少 8 位")

    result = register_user(
        username, password, org_name=org_name, invite_code=invite_code
    )
    if "error" in result:
        raise HTTPException(400, result["error"])
    return _token_response(result, username, result.get("tenant_id"))


@router.post("/login")
@limiter.limit("10/minute")
def api_login(request: Request, body: dict = Body(...)):
    username = (body.get("username") or "").strip()
    password = (body.get("password") or "").strip()
    if not username or not password:
        raise HTTPException(400, "用户名和密码不能为空")
    result = login_user(username, password)
    if not result:
        raise HTTPException(401, "用户名或密码错误")
    return _token_response(result, username, result.get("tenant_id"))


@router.post("/refresh")
@limiter.limit("30/minute")
def api_refresh(request: Request, body: dict = Body(...)):
    """用 refresh_token 换发新令牌（轮换：旧 refresh 立即失效）。"""
    refresh_token = (body.get("refresh_token") or "").strip()
    if not refresh_token:
        auth = request.headers.get("Authorization", "")
        if auth.lower().startswith("bearer "):
            refresh_token = auth[7:].strip()
    if not refresh_token:
        raise HTTPException(400, "缺少 refresh_token")

    payload = verify_refresh_token(refresh_token)
    if not payload:
        raise HTTPException(401, "refresh_token 无效、已过期或已登出")

    user = get_public_user(payload.get("user_id"))
    if not user:
        raise HTTPException(401, "用户不存在")

    # 轮换：旧 refresh 立即作废，避免被重复使用（replay）
    revoke_payload(payload)
    return _token_response(
        {
            "user_id": user["id"],
            "role": user.get("role"),
            "tenant_role": user.get("tenant_role"),
            "tenant_name": (get_tenant(user.get("tenant_id")) or {}).get("name"),
        },
        user["username"],
        user.get("tenant_id"),
    )


@router.post("/logout")
async def api_logout(
    body: Optional[dict] = Body(default=None),
    current_user: dict = Depends(get_current_user),
):
    """登出：撤销当前 access_token；如提交了 refresh_token 一并撤销。"""
    revoke_payload(current_user)

    refresh_token = (body or {}).get("refresh_token")
    if refresh_token:
        payload = verify_refresh_token(refresh_token)
        if payload and payload.get("user_id") == current_user.get("user_id"):
            revoke_payload(payload)

    return {"status": "ok", "message": "已登出，令牌立即失效"}


@router.get("/me")
def api_me(current_user: dict = Depends(get_current_user)):
    user = get_public_user(current_user["user_id"])
    if not user:
        raise HTTPException(404, "用户不存在")
    tenant = get_tenant(user.get("tenant_id")) if user.get("tenant_id") else None
    return {
        "user_id": user["id"],
        "username": user["username"],
        # 平台级角色（全站管理权）
        "role": user.get("role"),
        # 租户内角色（本组织的成员/设置管理权）
        "tenant_role": user.get("tenant_role"),
        "tenant_id": user.get("tenant_id"),
        "tenant_name": tenant["name"] if tenant else None,
        "invite_code": tenant["invite_code"] if tenant else None,
        "collections": collections_for(user.get("tenant_id"), user["id"]),
        "access_token_expires_in": ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    }


@router.post("/join")
@limiter.limit("10/minute")
def api_join_organization(
    request: Request,
    body: dict = Body(...),
    current_user: dict = Depends(get_current_user),
):
    """用邀请码加入（或切换到）目标组织。

    ⚠️ 会替换当前账号的租户归属：原组织中的**个人私有文档**仍留在原组织空间，
    不会跟随迁移（跨租户搬运会破坏隔离边界）。共享库内容本来就属于原组织，
    自然也不会带走。
    """
    invite_code = (body.get("invite_code") or "").strip()
    if not invite_code:
        raise HTTPException(400, "邀请码不能为空")
    try:
        member = join_tenant_by_invite_code(current_user["user_id"], invite_code)
    except TenantError as exc:
        raise HTTPException(400, str(exc)) from exc
    tenant = get_tenant(member.get("tenant_id")) or {}
    logger.info("user_joined_tenant", user_id=member.get("id"),
                tenant_id=member.get("tenant_id"))
    # 换发令牌：get_current_user 只读 Token 里的 tenant_id、**不回查 DB**，
    # 不换发会让用户「已经加入新组织，但后续请求仍以旧组织身份执行」。
    user = get_public_user(current_user["user_id"]) or {}
    payload = {
        "user_id": user.get("id"),
        "role": user.get("role"),
        "tenant_role": user.get("tenant_role"),
        "tenant_name": tenant.get("name"),
        "invite_code": None,
        "collections": collections_for(user.get("tenant_id"), user.get("id")),
    }
    return {
        "status": "ok",
        "message": "已加入组织",
        **_token_response(payload, current_user["username"], user.get("tenant_id")),
    }
