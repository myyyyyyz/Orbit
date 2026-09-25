"""认证路由: /api/v1/auth/*

令牌模型：
- 登录/注册返回 access_token（短时效）+ refresh_token（长时效）。
- /refresh 用 refresh_token 换发新的一对令牌，并撤销旧的 refresh（轮换）。
- /logout 撤销当前 access 与随请求提交的 refresh，立即失效而非等自然过期。
"""
from typing import Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Request

from ..multitenant import register_user, login_user, get_user_by_id, get_user_collection
from ..middleware.auth import (
    get_current_user,
    create_token_pair,
    verify_refresh_token,
    revoke_payload,
    ACCESS_TOKEN_EXPIRE_MINUTES,
)
from ..rate_limit import limiter

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


def _token_response(result: dict, username: str, tenant_id: Optional[str]) -> dict:
    role = result.get("role")
    return {
        **create_token_pair(username, result["user_id"], tenant_id, role),
        "user_id": result["user_id"],
        "username": username,
        "role": role,
        "tenant_id": tenant_id,
        "collection_name": result.get("collection_name"),
    }


@router.post("/register")
@limiter.limit("5/minute")
def api_register(request: Request, body: dict = Body(...)):
    username = body.get("username", "").strip()
    password = body.get("password", "").strip()
    tenant_id = body.get("tenant_id")
    if not username or not password:
        raise HTTPException(400, "用户名和密码不能为空")
    if len(password) < 8:
        raise HTTPException(400, "密码长度至少 8 位")
    result = register_user(username, password, tenant_id)
    if "error" in result:
        raise HTTPException(400, result["error"])
    return _token_response(result, username, tenant_id)


@router.post("/login")
@limiter.limit("10/minute")
def api_login(request: Request, body: dict = Body(...)):
    username = body.get("username", "").strip()
    password = body.get("password", "").strip()
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

    user = get_user_by_id(payload.get("user_id"))
    if not user:
        raise HTTPException(401, "用户不存在")

    # 轮换：旧 refresh 立即作废，避免被重复使用（replay）
    revoke_payload(payload)
    return {
        **create_token_pair(
            user["username"], user["id"], user.get("tenant_id"), user.get("role"),
        ),
        "user_id": user["id"],
        "username": user["username"],
        "role": user.get("role"),
        "tenant_id": user.get("tenant_id"),
        "collection_name": get_user_collection(user["id"]),
    }


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
    user = get_user_by_id(current_user["user_id"])
    if not user:
        raise HTTPException(404, "用户不存在")
    return {
        "user_id": user["id"], "username": user["username"], "role": user["role"],
        "tenant_id": user["tenant_id"], "collection_name": get_user_collection(current_user["user_id"]),
        "access_token_expires_in": ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    }
