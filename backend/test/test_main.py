"""main.py — 应用入口测试：健康/就绪探针、X-Request-ID 中间件、CORS、安全头"""
import uuid


# ── /health：存活探针（刻意极简，不探外部依赖）──

def test_health_liveness(client):
    r = client.get("/health")
    assert r.status_code == 200
    data = r.json()
    assert data["service"] == "knowledge-base"
    assert data["status"] == "ok"


# ── /health/detail：依赖明细（永远 200，body 表达健康度）──

def test_health_detail_reports_dependencies(client):
    r = client.get("/health/detail")
    assert r.status_code == 200
    data = r.json()
    assert data["chromadb"] == "ok"
    assert data["sqlite"] == "ok"
    assert data["llm_api"] == "skipped (no API key)"  # conftest 已清除环境变量
    assert data["status"] == "ok"


# ── /ready：就绪探针（关键依赖不可用时 503）──

def test_ready_ok_when_dependencies_healthy(client):
    r = client.get("/ready")
    assert r.status_code == 200
    assert r.json()["status"] in ("ok", "degraded")


def test_ready_returns_503_when_chromadb_down(client, monkeypatch):
    """关键依赖不可用必须 503，否则负载均衡会把流量继续打到坏节点。"""
    import app.main as main_mod

    def boom():
        return {
            "service": "knowledge-base", "version": "1.0.0",
            "chromadb": "unhealthy: boom", "sqlite": "ok",
            "llm_api": "ok", "status": "unavailable",
        }
    monkeypatch.setattr(main_mod, "_run_dependency_checks", boom)
    r = client.get("/ready")
    assert r.status_code == 503
    assert r.json()["status"] == "unavailable"


# ── 中间件 ──

def test_request_id_generated(client):
    r = client.get("/health")
    assert "x-request-id" in r.headers
    uuid.UUID(r.headers["x-request-id"])  # 是合法 UUID


def test_request_id_passthrough(client):
    r = client.get("/health", headers={"X-Request-ID": "my-custom-req-id-123"})
    assert r.headers["x-request-id"] == "my-custom-req-id-123"


def test_cors_headers(client):
    r = client.options("/health", headers={
        "Origin": "http://localhost:3000",
        "Access-Control-Request-Method": "GET",
    })
    assert r.headers.get("access-control-allow-origin") == "http://localhost:3000"


def test_security_headers_present(client):
    r = client.get("/health")
    assert r.headers.get("x-content-type-options") == "nosniff"
    assert r.headers.get("x-frame-options") == "DENY"
    assert r.headers.get("referrer-policy") == "no-referrer"


def test_unknown_route_404(client):
    r = client.get("/api/nonexistent")
    assert r.status_code == 404
