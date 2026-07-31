"""api/memory.py — 长期记忆接口测试 /api/memory/*"""


def test_save_and_get_profile(client, auth_headers):
    r = client.post("/api/memory/profile", json={
        "role": "developer", "preferences": {"lang": "zh"},
        "common_skills": ["python"], "output_style": "code_first",
    }, headers=auth_headers)
    assert r.status_code == 200

    r = client.get("/api/memory/profile", headers=auth_headers)
    assert r.status_code == 200
    data = r.json()
    assert data["role"] == "developer"
    assert data["preferences"] == {"lang": "zh"}
    assert data["common_skills"] == ["python"]


def test_get_profile_not_found(client, auth_headers):
    r = client.get("/api/memory/profile", headers=auth_headers)
    assert r.status_code == 404


def test_save_project(client, auth_headers):
    r = client.post("/api/memory/project", json={
        "project_name": "Orbit", "tech_stack": "FastAPI",
        "current_progress": "测试中", "key_decisions": ["用 pytest"],
    }, headers=auth_headers)
    assert r.status_code == 200


def test_save_project_missing_name(client, auth_headers):
    r = client.post("/api/memory/project", json={}, headers=auth_headers)
    assert r.status_code == 400


def test_save_summary(client, auth_headers):
    r = client.post("/api/memory/summary", json={
        "summary": "讨论了测试策略", "key_points": ["全模块覆盖"],
    }, headers=auth_headers)
    assert r.status_code == 200


def test_save_summary_missing(client, auth_headers):
    r = client.post("/api/memory/summary", json={}, headers=auth_headers)
    assert r.status_code == 400


def test_restore_context(client, auth_headers):
    client.post("/api/memory/profile", json={"role": "pm"}, headers=auth_headers)
    client.post("/api/memory/project", json={"project_name": "Orbit"}, headers=auth_headers)
    r = client.get("/api/memory/restore", headers=auth_headers)
    assert r.status_code == 200
    data = r.json()
    assert data["has_context"] is True
    assert data["user_profile"]["role"] == "pm"
    assert data["current_project"]["project_name"] == "Orbit"


def test_memory_requires_auth(client):
    assert client.get("/api/memory/profile").status_code == 401
    assert client.get("/api/memory/restore").status_code == 401
    assert client.post("/api/memory/profile", json={}).status_code == 401
