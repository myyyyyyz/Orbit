"""api/auth.py — 认证接口测试 /api/v1/auth/*"""
import uuid

PASSWORD = "pass12345"  # >= 8 位（注册接口现在强制最短长度）


def _username():
    return "pytest_api_" + uuid.uuid4().hex[:8]


def _register(client, username, password=PASSWORD, **extra):
    return client.post("/api/v1/auth/register",
                       json={"username": username, "password": password, **extra})


def test_register_success(client):
    username = _username()
    r = _register(client, username, tenant_id="org_t")
    assert r.status_code == 200
    data = r.json()
    assert data["access_token"]
    assert data["refresh_token"]
    assert data["token_type"] == "bearer"
    assert data["username"] == username
    assert data["tenant_id"] == "org_t"
    assert data["collection_name"] == f"user_{data['user_id']}"


def test_register_rejects_short_password(client):
    r = _register(client, _username(), password="1234")
    assert r.status_code == 400
    assert "8" in r.json()["detail"]


def test_register_missing_fields(client):
    r = client.post("/api/v1/auth/register", json={"username": "", "password": ""})
    assert r.status_code == 400
    assert "不能为空" in r.json()["detail"]


def test_register_duplicate(client):
    username = _username()
    _register(client, username)
    r = _register(client, username)
    assert r.status_code == 400
    assert "已存在" in r.json()["detail"]


def test_login_success(client):
    username = _username()
    _register(client, username)
    r = client.post("/api/v1/auth/login", json={"username": username, "password": PASSWORD})
    assert r.status_code == 200
    data = r.json()
    assert data["access_token"]
    assert data["refresh_token"]
    assert data["role"] == "user"


def test_login_wrong_password(client):
    username = _username()
    _register(client, username)
    r = client.post("/api/v1/auth/login", json={"username": username, "password": "wrong-password"})
    assert r.status_code == 401


def test_login_missing_fields(client):
    r = client.post("/api/v1/auth/login", json={})
    assert r.status_code == 400


# ── Refresh Token ──

def test_refresh_returns_new_pair(client):
    username = _username()
    reg = _register(client, username).json()
    r = client.post("/api/v1/auth/refresh", json={"refresh_token": reg["refresh_token"]})
    assert r.status_code == 200
    data = r.json()
    assert data["access_token"]
    assert data["refresh_token"]
    # 轮换：新 refresh 与旧的不同
    assert data["refresh_token"] != reg["refresh_token"]


def test_refresh_token_is_single_use(client):
    """旧 refresh 用过一次后必须失效（防重放）。"""
    reg = _register(client, _username()).json()
    old_refresh = reg["refresh_token"]
    assert client.post("/api/v1/auth/refresh", json={"refresh_token": old_refresh}).status_code == 200
    assert client.post("/api/v1/auth/refresh", json={"refresh_token": old_refresh}).status_code == 401


def test_refresh_rejects_access_token(client):
    reg = _register(client, _username()).json()
    r = client.post("/api/v1/auth/refresh", json={"refresh_token": reg["access_token"]})
    assert r.status_code == 401


def test_refresh_without_token(client):
    assert client.post("/api/v1/auth/refresh", json={}).status_code == 400


# ── 登出即时失效 ──

def test_logout_invalidates_access_token(client):
    reg = _register(client, _username()).json()
    headers = {"Authorization": f"Bearer {reg['access_token']}"}
    assert client.get("/api/v1/auth/me", headers=headers).status_code == 200

    r = client.post("/api/v1/auth/logout", json={"refresh_token": reg["refresh_token"]}, headers=headers)
    assert r.status_code == 200

    assert client.get("/api/v1/auth/me", headers=headers).status_code == 401
    # refresh 也一并撤销
    assert client.post("/api/v1/auth/refresh",
                       json={"refresh_token": reg["refresh_token"]}).status_code == 401


# ── /me ──

def test_me_with_valid_token(client, auth_headers):
    r = client.get("/api/v1/auth/me", headers=auth_headers)
    assert r.status_code == 200
    data = r.json()
    assert data["username"].startswith("pytest_")
    assert data["collection_name"] == f"user_{data['user_id']}"


def test_me_without_token(client):
    assert client.get("/api/v1/auth/me").status_code == 401


def test_me_with_invalid_token(client):
    r = client.get("/api/v1/auth/me", headers={"Authorization": "Bearer invalid.token.here"})
    assert r.status_code == 401


def test_access_token_rejected_where_refresh_expected_is_not_confused(client):
    """access token 调受保护接口正常，但同一 token 不能换新令牌（已在上面覆盖）。"""
    reg = _register(client, _username()).json()
    token = reg["access_token"]
    assert client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"}).status_code == 200
