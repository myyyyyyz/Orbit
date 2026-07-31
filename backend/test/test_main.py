"""main.py — 应用入口测试：/health、X-Request-ID 中间件、CORS"""
import uuid


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    data = r.json()
    assert data["service"] == "knowledge-base"
    assert data["chromadb"] == "ok"
    assert data["sqlite"] == "ok"
    assert data["llm_api"] == "skipped (no API key)"  # conftest 已清除环境变量
    assert data["status"] == "ok"


def test_request_id_generated(client):
    r = client.get("/health")
    assert "x-request-id" in r.headers
    # 是合法 UUID
    uuid.UUID(r.headers["x-request-id"])


def test_request_id_passthrough(client):
    r = client.get("/health", headers={"X-Request-ID": "my-custom-req-id-123"})
    assert r.headers["x-request-id"] == "my-custom-req-id-123"


def test_cors_headers(client):
    r = client.options("/health", headers={
        "Origin": "http://localhost:3000",
        "Access-Control-Request-Method": "GET",
    })
    assert r.headers.get("access-control-allow-origin") == "http://localhost:3000"


def test_unknown_route_404(client):
    r = client.get("/api/nonexistent")
    assert r.status_code == 404
