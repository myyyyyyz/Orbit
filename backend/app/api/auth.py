"""认证路由: /api/auth/*"""
from typing import Optional
from fastapi import APIRouter, Body, Depends, HTTPException, Request
from slowapi import Limiter
from slowapi.util import get_remote_address

from ..multitenant import register_user, login_user, get_user_by_id, get_user_collection
from ..middleware.auth import get_current_user, create_access_token

router = APIRouter(prefix="/api/auth", tags=["auth"])
limiter = Limiter(key_func=get_remote_address)


@router.post("/register")
@limiter.limit("5/minute")
def api_register(request: Request, body: dict = Body(...)):
    username = body.get("username", "").strip()
    password = body.get("password", "").strip()
    tenant_id = body.get("tenant_id")
    if not username or not password:
        raise HTTPException(400, "用户名和密码不能为空")
    result = register_user(username, password, tenant_id)
    if "error" in result:
        raise HTTPException(400, result["error"])
    token = create_access_token(username, result["user_id"], tenant_id)
    return {
        "access_token": token, "token_type": "bearer", "user_id": result["user_id"],
        "username": username, "tenant_id": tenant_id, "collection_name": result["collection_name"],
    }


@router.post("/login")
@limiter.limit("5/minute")
def api_login(request: Request, body: dict = Body(...)):
    username = body.get("username", "").strip()
    password = body.get("password", "").strip()
    if not username or not password:
        raise HTTPException(400, "用户名和密码不能为空")
    result = login_user(username, password)
    if not result:
        raise HTTPException(401, "用户名或密码错误")
    token = create_access_token(username, result["user_id"], result.get("tenant_id"))
    return {
        "access_token": token, "token_type": "bearer", "user_id": result["user_id"],
        "username": username, "role": result.get("role"),
        "tenant_id": result.get("tenant_id"), "collection_name": result["collection_name"],
    }


@router.get("/me")
def api_me(current_user: dict = Depends(get_current_user)):
    user = get_user_by_id(current_user["user_id"])
    if not user:
        raise HTTPException(404, "用户不存在")
    return {
        "user_id": user["id"], "username": user["username"], "role": user["role"],
        "tenant_id": user["tenant_id"], "collection_name": get_user_collection(current_user["user_id"]),
    }
