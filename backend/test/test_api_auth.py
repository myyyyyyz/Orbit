"""api/auth.py — 认证接口测试 /api/auth/*"""
import uuid


def _username():
    return "pytest_api_" + uuid.uuid4().hex[:8]


def test_register_success(client):
    username = _username()
    r = client.post("/api/auth/register", json={"username": username, "password": "pass123", "tenant_id": "org_t"})
    assert r.status_code == 200
    data = r.json()
    assert data["access_token"]
    assert data["token_type"] == "bearer"
    assert data["username"] == username
    assert data["tenant_id"] == "org_t"
    assert data["collection_name"] == f"user_{data['user_id']}"


def test_register_missing_fields(client):
    r = client.post("/api/auth/register", json={"username": "", "password": ""})
    assert r.status_code == 400
    assert "不能为空" in r.json()["detail"]


def test_register_duplicate(client):
    username = _username()
    client.post("/api/auth/register", json={"username": username, "password": "pass123"})
    r = client.post("/api/auth/register", json={"username": username, "password": "pass123"})
    assert r.status_code == 400
    assert "已存在" in r.json()["detail"]


def test_login_success(client):
    username = _username()
    client.post("/api/auth/register", json={"username": username, "password": "pass123"})
    r = client.post("/api/auth/login", json={"username": username, "password": "pass123"})
    assert r.status_code == 200
    data = r.json()
    assert data["access_token"]
    assert data["role"] == "user"


def test_login_wrong_password(client):
    username = _username()
    client.post("/api/auth/register", json={"username": username, "password": "pass123"})
    r = client.post("/api/auth/login", json={"username": username, "password": "wrong"})
    assert r.status_code == 401


def test_login_missing_fields(client):
    r = client.post("/api/auth/login", json={})
    assert r.status_code == 400


def test_me_with_valid_token(client, auth_headers):
    r = client.get("/api/auth/me", headers=auth_headers)
    assert r.status_code == 200
    data = r.json()
    assert data["username"].startswith("pytest_")
    assert data["collection_name"] == f"user_{data['user_id']}"


def test_me_without_token(client):
    r = client.get("/api/auth/me")
    assert r.status_code == 401


def test_me_with_invalid_token(client):
    r = client.get("/api/auth/me", headers={"Authorization": "Bearer invalid.token.here"})
    assert r.status_code == 401
