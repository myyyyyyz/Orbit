"""
JWT 认证与授权。

用法:
    from .middleware.auth import get_current_user, create_access_token

    @app.get("/api/protected")
    def protected_route(current_user: dict = Depends(get_current_user)):
        return {"user": current_user["username"]}

    @app.post("/admin/only")
    def admin_only(_: dict = Depends(require_role("admin"))):
        ...

令牌模型（上线加固）：
- Access Token：短时效（默认 60 分钟），用于常规接口。
- Refresh Token：长时效（默认 7 天），仅用于换取新的 Access Token。
  通过 `type` 声明区分，Refresh 不能当 Access 使用（verify_access_token 会拒绝）。
- `jti` + 进程内撤销表：支持登出后立即失效。**多 worker 部署时撤销表不共享**，
  需替换为 Redis（同语义缓存的一致约束，见 docs/PRODUCTION-READINESS.md）。
"""

import os
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from jose import JWTError, jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer

from ..config import is_production
from ..logging_config import get_logger

logger = get_logger(__name__)

# ── 配置 ──────────────────────────────────────────

ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "60"))
REFRESH_TOKEN_EXPIRE_DAYS = int(os.getenv("REFRESH_TOKEN_EXPIRE_DAYS", "7"))

TOKEN_TYPE_ACCESS = "access"
TOKEN_TYPE_REFRESH = "refresh"

_VALID_ROLES = ("user", "admin")


def get_secret_key() -> str:
    """解析 JWT 签名密钥（唯一入口）。

    策略与 config._validate_config_on_startup 保持一致：
    - 生产环境（ENV=production）缺失/过短 → 直接抛错，绝不用随机密钥对外服务；
      否则多副本之间签名不一致，且重启即全员掉线，属于静默故障。
    - 非生产环境 → 生成进程内随机密钥并大声告警，方便本地开发。
    """
    key = (os.getenv("SECRET_KEY") or "").strip()
    if len(key) >= 32:
        return key

    if is_production():
        raise RuntimeError(
            "SECRET_KEY 未设置或长度不足（生产环境需 >= 32 字符），拒绝启动。"
            "生成方式：python3 -c \"import secrets; print(secrets.token_hex(32))\""
        )

    if key:
        logger.warning("secret_key_too_short", length=len(key), hint="生产环境需 >= 32 字符")
    else:
        import secrets
        key = secrets.token_hex(32)
        logger.warning(
            "secret_key_missing_dev_fallback",
            hint="已生成进程内随机密钥；服务重启后所有 Token 失效。生产环境请务必配置 SECRET_KEY。",
        )
    return key


oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login", auto_error=False)


# ── 令牌撤销表（单进程 MVP）─────────────────────────

_revoked: dict[str, float] = {}          # jti -> exp 时间戳（秒）
_revoked_lock = threading.Lock()
MAX_REVOKED_ENTRIES = 10_000


def revoke_payload(payload: dict) -> None:
    """把某个 Token 的 jti 加入撤销表（登出 / 强制下线）。"""
    jti = payload.get("jti")
    if not jti:
        return
    exp = float(payload.get("exp") or (time.time() + REFRESH_TOKEN_EXPIRE_DAYS * 86400))
    with _revoked_lock:
        _purge_revoked_locked()
        if len(_revoked) >= MAX_REVOKED_ENTRIES:
            # 容量保护：淘汰最早过期的一条，避免无限增长
            oldest = min(_revoked, key=lambda k: _revoked[k])
            _revoked.pop(oldest, None)
        _revoked[jti] = exp


def is_revoked(payload: dict) -> bool:
    jti = payload.get("jti")
    if not jti:
        return False
    with _revoked_lock:
        exp = _revoked.get(jti)
        if exp is None:
            return False
        if exp < time.time():
            _revoked.pop(jti, None)
            return False
        return True


def _purge_revoked_locked() -> None:
    now = time.time()
    for jti in [k for k, exp in _revoked.items() if exp < now]:
        _revoked.pop(jti, None)


def reset_revocation_store() -> None:
    """清空撤销表（仅供测试）。"""
    with _revoked_lock:
        _revoked.clear()


# ── Token 签发 ────────────────────────────────────

def _create_token(
    username: str,
    user_id: int,
    token_type: str,
    expires_delta: timedelta,
    tenant_id: Optional[str] = None,
    role: Optional[str] = None,
) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": username,
        "user_id": user_id,
        "tenant_id": tenant_id,
        "role": role,
        "type": token_type,
        "jti": uuid.uuid4().hex,
        "iat": now,
        "exp": now + expires_delta,
    }
    return jwt.encode(payload, get_secret_key(), algorithm=ALGORITHM)


def create_access_token(username: str, user_id: int, tenant_id: Optional[str] = None,
                        role: Optional[str] = None) -> str:
    """签发短时效 Access Token。"""
    return _create_token(
        username, user_id, TOKEN_TYPE_ACCESS,
        timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES), tenant_id, role,
    )


def create_refresh_token(username: str, user_id: int, tenant_id: Optional[str] = None,
                         role: Optional[str] = None) -> str:
    """签发 Refresh Token（长时效，仅用于换发 Access Token）。"""
    return _create_token(
        username, user_id, TOKEN_TYPE_REFRESH,
        timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS), tenant_id, role,
    )


def create_token_pair(username: str, user_id: int, tenant_id: Optional[str] = None,
                      role: Optional[str] = None) -> dict:
    """一次签发 access + refresh，供登录/注册接口返回。"""
    return {
        "access_token": create_access_token(username, user_id, tenant_id, role),
        "refresh_token": create_refresh_token(username, user_id, tenant_id, role),
        "token_type": "bearer",
        "expires_in": ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    }


# ── Token 验证 ─────────────────────────────────────

def _decode(token: str) -> Optional[dict]:
    """解码并验签。不抛异常——由调用方决定如何处理失败。"""
    try:
        return jwt.decode(token, get_secret_key(), algorithms=[ALGORITHM])
    except JWTError:
        return None


def verify_access_token(token: str) -> Optional[dict]:
    """验证 Access Token，返回 payload 或 None。

    注意：
    - 拒绝 refresh 类型（防止用长效令牌直接调用业务接口绕过短时效约束）。
    - 校验撤销表（登出后立即失效）。
    - 不使用 lru_cache 缓存解码结果——缓存会引入安全问题
      （过期 Token 在缓存中被续命、内存 dump 泄露 payload）。
    """
    payload = _decode(token)
    if not payload:
        return None
    if payload.get("type") == TOKEN_TYPE_REFRESH:
        return None
    if is_revoked(payload):
        return None
    return payload


def verify_refresh_token(token: str) -> Optional[dict]:
    """验证 Refresh Token。旧版 Token（无 type）视为无效，不发新令牌。"""
    payload = _decode(token)
    if not payload:
        return None
    if payload.get("type") != TOKEN_TYPE_REFRESH:
        return None
    if is_revoked(payload):
        return None
    return payload


# ── FastAPI 依赖注入 ──────────────────────────────

def _user_from_payload(payload: dict) -> dict:
    return {
        "user_id": payload.get("user_id"),
        "username": payload.get("sub"),
        "tenant_id": payload.get("tenant_id"),
        "role": payload.get("role"),
        "jti": payload.get("jti"),
        # 带上 exp，登出时撤销表可以按真实过期时间清理，而不是一律按 Refresh 时长兜底
        "exp": payload.get("exp"),
    }


def _unauthorized(detail: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


async def get_current_user(token: str = Depends(oauth2_scheme)) -> dict:
    """
    FastAPI 依赖注入：从 Authorization: Bearer <token> 中提取当前用户。

    Raises HTTPException(401) 当 Token 缺失、无效、过期或已撤销时。
    返回: {"user_id": 1, "username": "lover_a", "tenant_id": "org_123", "role": "user"}
    """
    if not token:
        raise _unauthorized("未提供认证 Token（Authorization: Bearer <token>）")
    payload = verify_access_token(token)
    if not payload:
        raise _unauthorized("Token 无效、已过期或已登出")
    return _user_from_payload(payload)


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
    return _user_from_payload(payload)


# ── 授权（RBAC）────────────────────────────────────

def _load_role(user_id: Optional[int]) -> Optional[str]:
    """从数据库读取用户当前角色（权威来源）。

    Token 里的 role 只是签发时的快照；降权必须立即生效，因此这里回查一次。
    查询失败一律视为无权限（fail-closed），不因为数据库抖动而放开管理接口。
    """
    if not user_id:
        return None
    try:
        from ..multitenant import get_user_by_id

        user = get_user_by_id(user_id)
        return (user or {}).get("role")
    except Exception:
        logger.warning("role_lookup_failed", user_id=user_id, exc_info=True)
        return None


def require_role(*allowed_roles: str):
    """生成一个校验角色的依赖：`Depends(require_role("admin"))`。

    历史缺陷：全仓有认证没有授权，`users.role` 字段形同虚设——
    全局 kill switch（pause-all）、工具策略等管理接口任何注册用户都能调用。
    """
    if not allowed_roles:
        raise ValueError("require_role 至少需要一个角色")

    async def _dependency(current_user: dict = Depends(get_current_user)) -> dict:
        role = _load_role(current_user.get("user_id"))
        if role not in allowed_roles:
            logger.warning(
                "rbac_denied",
                user_id=current_user.get("user_id"),
                role=role,
                required=list(allowed_roles),
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"权限不足，需要角色: {', '.join(allowed_roles)}",
            )
        current_user["role"] = role
        return current_user

    return _dependency
