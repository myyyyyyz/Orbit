"""middleware/auth.py — JWT 认证中间件测试"""
import asyncio
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException
from jose import jwt

import app.middleware.auth as auth_mod
from app.middleware.auth import (
    create_access_token, verify_access_token,
    get_current_user, get_optional_user,
    ALGORITHM,
)


def test_create_and_verify_roundtrip():
    token = create_access_token("alice", 1, tenant_id="org_1")
    payload = verify_access_token(token)
    assert payload["sub"] == "alice"
    assert payload["user_id"] == 1
    assert payload["tenant_id"] == "org_1"
    assert "exp" in payload
    assert "iat" in payload


def test_verify_tampered_token():
    token = create_access_token("alice", 1)
    tampered = token[:-4] + "xxxx"
    assert verify_access_token(tampered) is None


def test_verify_expired_token():
    expired = jwt.encode(
        {"sub": "alice", "user_id": 1, "exp": datetime.now(timezone.utc) - timedelta(days=1)},
        auth_mod._SECRET_KEY, algorithm=ALGORITHM,
    )
    assert verify_access_token(expired) is None


def test_verify_garbage_token():
    assert verify_access_token("not.a.jwt") is None


def test_get_current_user_valid():
    token = create_access_token("bob", 2)
    user = asyncio.run(get_current_user(token))
    assert user == {"user_id": 2, "username": "bob", "tenant_id": None}


def test_get_current_user_missing_token():
    with pytest.raises(HTTPException) as exc:
        asyncio.run(get_current_user(None))
    assert exc.value.status_code == 401
    assert "未提供认证 Token" in exc.value.detail


def test_get_current_user_invalid_token():
    with pytest.raises(HTTPException) as exc:
        asyncio.run(get_current_user("bad-token"))
    assert exc.value.status_code == 401
    assert "无效或已过期" in exc.value.detail


def test_get_optional_user():
    token = create_access_token("carol", 3, "org_2")
    assert asyncio.run(get_optional_user(None)) is None
    assert asyncio.run(get_optional_user("bad")) is None
    user = asyncio.run(get_optional_user(token))
    assert user["username"] == "carol"
    assert user["tenant_id"] == "org_2"


def test_decode_token_lru_cache():
    """同一 token 重复验证走 LRU 缓存"""
    auth_mod._decode_token.cache_clear()
    token = create_access_token("dave", 4)
    verify_access_token(token)
    verify_access_token(token)
    info = auth_mod._decode_token.cache_info()
    assert info.hits >= 1
