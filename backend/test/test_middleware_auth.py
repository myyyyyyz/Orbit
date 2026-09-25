"""middleware/auth.py — JWT 认证 + RBAC 授权测试"""
import asyncio
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException
from jose import jwt

import app.middleware.auth as auth_mod
from app.middleware.auth import (
    create_access_token, create_refresh_token, create_token_pair,
    verify_access_token, verify_refresh_token,
    get_current_user, get_optional_user,
    require_role, revoke_payload, reset_revocation_store,
    ALGORITHM,
)


# ── 签发 / 校验 ──

def test_create_and_verify_roundtrip():
    token = create_access_token("alice", 1, tenant_id="org_1", role="admin")
    payload = verify_access_token(token)
    assert payload["sub"] == "alice"
    assert payload["user_id"] == 1
    assert payload["tenant_id"] == "org_1"
    assert payload["role"] == "admin"
    assert payload["type"] == "access"
    assert payload["jti"]
    assert "exp" in payload
    assert "iat" in payload


def test_access_token_ttl_is_short():
    """上线加固：access token 不应再是 7 天长效。"""
    token = create_access_token("alice", 1)
    payload = verify_access_token(token)
    ttl = payload["exp"] - payload["iat"]
    assert ttl <= 24 * 3600, f"access token 有效期过长: {ttl}s"


def test_verify_tampered_token():
    token = create_access_token("alice", 1)
    tampered = token[:-4] + "xxxx"
    assert verify_access_token(tampered) is None


def test_verify_expired_token():
    expired = jwt.encode(
        {"sub": "alice", "user_id": 1, "exp": datetime.now(timezone.utc) - timedelta(days=1)},
        auth_mod.get_secret_key(), algorithm=ALGORITHM,
    )
    assert verify_access_token(expired) is None


def test_verify_garbage_token():
    assert verify_access_token("not.a.jwt") is None


def test_verify_multiple_calls_consistent():
    token = create_access_token("dave", 4)
    p1 = verify_access_token(token)
    p2 = verify_access_token(token)
    assert p1 == p2
    assert p1["sub"] == "dave"


# ── Refresh Token 隔离（P0 加固点）──

def test_refresh_token_cannot_be_used_as_access():
    """refresh token 不能直接调用业务接口，否则短时效 access 形同虚设。"""
    refresh = create_refresh_token("alice", 1)
    assert verify_refresh_token(refresh) is not None
    assert verify_access_token(refresh) is None


def test_access_token_cannot_be_used_as_refresh():
    access = create_access_token("alice", 1)
    assert verify_refresh_token(access) is None


def test_refresh_token_longer_ttl_than_access():
    access_p = verify_access_token(create_access_token("a", 1))
    refresh_p = verify_refresh_token(create_refresh_token("a", 1))
    assert (refresh_p["exp"] - refresh_p["iat"]) > (access_p["exp"] - access_p["iat"])


def test_token_pair_shape():
    pair = create_token_pair("alice", 1, "org_1", "user")
    assert set(pair) == {"access_token", "refresh_token", "token_type", "expires_in"}
    assert pair["token_type"] == "bearer"
    assert pair["expires_in"] > 0


# ── 撤销（登出即时失效）──

def test_revoked_token_rejected():
    token = create_access_token("alice", 1)
    payload = verify_access_token(token)
    assert payload is not None

    revoke_payload(payload)
    assert verify_access_token(token) is None
    assert verify_refresh_token(create_refresh_token("b", 2)) is not None  # 不影响他人

    reset_revocation_store()
    assert verify_access_token(token) is not None


def test_revoke_without_jti_is_noop():
    revoke_payload({})  # 不应抛异常
    reset_revocation_store()


# ── 依赖注入 ──

def test_get_current_user_valid():
    token = create_access_token("bob", 2)
    user = asyncio.run(get_current_user(token))
    assert user["user_id"] == 2
    assert user["username"] == "bob"
    assert user["tenant_id"] is None
    assert user["jti"]


def test_get_current_user_missing_token():
    with pytest.raises(HTTPException) as exc:
        asyncio.run(get_current_user(None))
    assert exc.value.status_code == 401
    assert "未提供认证 Token" in exc.value.detail


def test_get_current_user_invalid_token():
    with pytest.raises(HTTPException) as exc:
        asyncio.run(get_current_user("bad-token"))
    assert exc.value.status_code == 401
    assert "无效" in exc.value.detail


def test_get_optional_user():
    token = create_access_token("carol", 3, "org_2")
    assert asyncio.run(get_optional_user(None)) is None
    assert asyncio.run(get_optional_user("bad")) is None
    user = asyncio.run(get_optional_user(token))
    assert user["username"] == "carol"
    assert user["tenant_id"] == "org_2"


# ── RBAC ──

def test_require_role_allows_matching_role(monkeypatch):
    monkeypatch.setattr(auth_mod, "_load_role", lambda uid: "admin")
    dep = require_role("admin")
    token = create_access_token("admin_user", 7)
    user = asyncio.run(get_current_user(token))
    assert asyncio.run(dep(user))["role"] == "admin"


def test_require_role_rejects_wrong_role(monkeypatch):
    monkeypatch.setattr(auth_mod, "_load_role", lambda uid: "user")
    dep = require_role("admin")
    token = create_access_token("normal_user", 8)
    user = asyncio.run(get_current_user(token))
    with pytest.raises(HTTPException) as exc:
        asyncio.run(dep(user))
    assert exc.value.status_code == 403


def test_require_role_fail_closed_when_db_unavailable(monkeypatch):
    """数据库查询失败必须视为无权限，不能因为抖动而放开管理接口。"""
    def boom(source, *a, **k):
        raise RuntimeError("db down")
    monkeypatch.setattr("app.multitenant.get_user_by_id", boom)
    dep = require_role("admin")
    token = create_access_token("admin_user", 9)
    user = asyncio.run(get_current_user(token))
    with pytest.raises(HTTPException) as exc:
        asyncio.run(dep(user))
    assert exc.value.status_code == 403


def test_require_role_without_roles_raises():
    with pytest.raises(ValueError):
        require_role()
