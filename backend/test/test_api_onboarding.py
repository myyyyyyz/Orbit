"""api/onboarding.py — 新手引导接口测试 /api/onboarding/*"""


def test_template(client):
    r = client.get("/api/onboarding/template")
    assert r.status_code == 200
    data = r.json()
    assert data["title"]
    assert len(data["roles"]) == 5


def test_roles(client):
    r = client.get("/api/onboarding/roles")
    assert r.status_code == 200
    roles = r.json()
    assert "developer" in roles
    assert "enterprise" in roles


def test_role_config(client):
    r = client.get("/api/onboarding/roles/developer")
    assert r.status_code == 200
    data = r.json()
    assert data["label"] == "开发者"
    assert "recommended_skills" in data
    assert "quick_actions" in data


def test_role_config_not_found(client):
    r = client.get("/api/onboarding/roles/no_such_role")
    assert r.status_code == 404
    assert "角色不存在" in r.json()["detail"]
