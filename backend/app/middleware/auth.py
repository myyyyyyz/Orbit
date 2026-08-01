"""
JWT 认证中间件

用法:
    from .middleware.auth import get_current_user, create_access_token

    @app.get("/api/protected")
    def protected_route(current_user: dict = Depends(get_current_user)):
        return {"user": current_user["username"]}
"""

import os
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from jose import JWTError, jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer

logger = logging.getLogger(__name__)

# ── 配置 ──────────────────────────────────────────

ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_DAYS = 7

_SECRET_KEY = os.getenv("SECRET_KEY")
if not _SECRET_KEY:
    import secrets
    _SECRET_KEY = secrets.token_hex(32)
    logger.warning(
        "⚠️  SECRET_KEY 未设置（环境变量 SECRET_KEY），已生成随机密钥。"
        "服务重启后所有 Token 将失效。生产环境请务必设置 SECRET_KEY。"
    )

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login", auto_error=False)


# ── Token 签发 ────────────────────────────────────

def create_access_token(username: str, user_id: int, tenant_id: Optional[str] = None) -> str:
    """签发 JWT Token"""
    now = datetime.now(timezone.utc)
    expire = now + timedelta(days=ACCESS_TOKEN_EXPIRE_DAYS)
    payload = {
        "sub": username,
        "user_id": user_id,
        "tenant_id": tenant_id,
        "exp": expire,
        "iat": now,
    }
    return jwt.encode(payload, _SECRET_KEY, algorithm=ALGORITHM)


# ── Token 验证 ─────────────────────────────────────

def verify_access_token(token: str) -> Optional[dict]:
    """
    验证 JWT Token，返回 payload 或 None。
    不抛异常——由调用方决定如何处理失败。

    注意：不使用 lru_cache 缓存解码结果——JWT HS256 解码本身极快（微秒级），
    缓存会引入安全风险（过期 Token 在缓存中被续命、内存 dump 泄露 payload）。
    """
    try:
        return jwt.decode(token, _SECRET_KEY, algorithms=[ALGORITHM])
    except JWTError:
        return None


# ── FastAPI 依赖注入 ──────────────────────────────

async def get_current_user(token: str = Depends(oauth2_scheme)) -> dict:
    """
    FastAPI 依赖注入：从 Authorization: Bearer <token> 中提取当前用户。

    Raises HTTPException(401) 当 Token 缺失或无效时。
    返回: {"user_id": 1, "username": "lover_a", "tenant_id": "org_123"}
    """
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="未提供认证 Token（Authorization: Bearer <token>）",
            headers={"WWW-Authenticate": "Bearer"},
        )

    payload = verify_access_token(token)
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token 无效或已过期",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return {
        "user_id": payload.get("user_id"),
        "username": payload.get("sub"),
        "tenant_id": payload.get("tenant_id"),
    }


async def get_optional_user(token: str = Depends(oauth2_scheme)) -> Optional[dict]:
    """
    可选认证：有 Token 时返回用户信息，无 Token 时返回 None（不报错）。
    用于需要兼容匿名 + 已登录的场景。
    """
    if not token:
        return None
    payload = verify_access_token(token)
    if not payload:
        return None
    return {
        "user_id": payload.get("user_id"),
        "username": payload.get("sub"),
        "tenant_id": payload.get("tenant_id"),
    }
