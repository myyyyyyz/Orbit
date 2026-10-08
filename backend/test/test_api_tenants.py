"""api/tenants.py — 组织管理接口测试 /api/v1/tenants/*

覆盖：组织概览 / 成员列表 / 改名 / 轮换邀请码 / 调整成员角色 /
角色越权（member 不能改名、非 owner 不能调角色）。
"""
import uuid


def _register(username=None, **kwargs):
    from app.multitenant import register_user
    name = username or "pytest_tenant_" + uuid.uuid4().hex[:8]
    result = register_user(name, "pytest_pass_123", **kwargs)
    if "error" in result:
        raise AssertionError(result)
    return name, result


def _headers(name, result):
    from app.middleware.auth import create_access_token
    return {
        "Authorization": "Bearer " + create_access_token(
            name, result["user_id"], result["tenant_id"],
            tenant_role=result.get("tenant_role"),
        )
    }


def test_my_tenant_summary(client, auth_context):
    r = client.get("/api/v1/tenants/me", headers=auth_context["headers"])
    assert r.status_code == 200
    data = r.json()
    assert data["id"] == auth_context["tenant_id"]
    assert data["name"] == auth_context["tenant_name"]
    assert data["my_role"] == "owner"
    assert data["plan"] == "free"
    assert data["max_collections"] == 5
    assert data["member_count"] == 1
    assert data["invite_code"]
    assert data["collections"]["shared"] == auth_context["collections"]["shared"]


def test_my_tenant_requires_auth(client):
    assert client.get("/api/v1/tenants/me").status_code == 401


def test_members_listing_hides_credentials(client, auth_context):
    r = client.get("/api/v1/tenants/me/members", headers=auth_context["headers"])
    assert r.status_code == 200
    data = r.json()
    assert data["count"] == 1
    member = data["members"][0]
    assert member["tenant_role"] == "owner"
    assert "password_hash" not in member
    assert set(data["roles"]) == {"owner", "admin", "member"}


def test_owner_can_rename_and_rotate_invite_code(client, auth_context):
    r = client.patch(
        "/api/v1/tenants/me",
        json={"name": "改名后的组织"},
        headers=auth_context["headers"],
    )
    assert r.status_code == 200
    assert r.json()["name"] == "改名后的组织"

    old_code = auth_context["invite_code"]
    r = client.post("/api/v1/tenants/me/invite-code", headers=auth_context["headers"])
    assert r.status_code == 200
    new_code = r.json()["invite_code"]
    assert new_code and new_code != old_code

    from app.multitenant import get_tenant_by_invite_code
    assert get_tenant_by_invite_code(old_code) is None
    assert get_tenant_by_invite_code(new_code)["id"] == auth_context["tenant_id"]


def test_rename_rejects_empty_name(client, auth_context):
    r = client.patch(
        "/api/v1/tenants/me", json={"name": "   "}, headers=auth_context["headers"]
    )
    assert r.status_code == 400


def test_member_cannot_rename_or_rotate_invite_code(client, auth_context):
    """member 角色越权必须被拒（403）——这是本次新增的组织内 RBAC。"""
    name, member = _register(invite_code=auth_context["invite_code"])
    headers = _headers(name, member)
    assert member["tenant_role"] == "member"

    assert client.patch(
        "/api/v1/tenants/me", json={"name": "越权改名"}, headers=headers
    ).status_code == 403
    assert client.post(
        "/api/v1/tenants/me/invite-code", headers=headers
    ).status_code == 403


def test_only_owner_can_change_member_role(client, auth_context):
    admin_name, admin = _register(invite_code=auth_context["invite_code"])
    member_name, member = _register(invite_code=auth_context["invite_code"])

    from app.multitenant import update_member_role
    update_member_role(auth_context["tenant_id"], admin["user_id"], "admin")

    # admin 不能调整成员角色（仅 owner 可以）
    r = client.patch(
        f"/api/v1/tenants/me/members/{member['user_id']}",
        json={"tenant_role": "admin"},
        headers=_headers(admin_name, admin),
    )
    assert r.status_code == 403

    # owner 可以
    r = client.patch(
        f"/api/v1/tenants/me/members/{member['user_id']}",
        json={"tenant_role": "admin"},
        headers=auth_context["headers"],
    )
    assert r.status_code == 200
    assert r.json()["member"]["tenant_role"] == "admin"


def test_role_update_rejects_invalid_role(client, auth_context):
    name, member = _register(invite_code=auth_context["invite_code"])
    r = client.patch(
        f"/api/v1/tenants/me/members/{member['user_id']}",
        json={"tenant_role": "superuser"},
        headers=auth_context["headers"],
    )
    assert r.status_code == 400


def test_join_organization_endpoint(client, auth_context):
    """已有账号可用邀请码加入组织（auth/join）。"""
    name, outsider = _register()
    headers = _headers(name, outsider)
    assert outsider["tenant_id"] != auth_context["tenant_id"]

    r = client.post(
        "/api/v1/auth/join",
        json={"invite_code": auth_context["invite_code"]},
        headers=headers,
    )
    assert r.status_code == 200
    data = r.json()
    assert data["tenant_id"] == auth_context["tenant_id"]
    assert data["tenant_role"] == "member"

    r = client.post("/api/v1/auth/join", json={"invite_code": "bad-code"}, headers=headers)
    assert r.status_code == 400


def test_join_requires_auth(client):
    assert client.post("/api/v1/auth/join", json={"invite_code": "x"}).status_code == 401


def test_join_rotates_token_to_new_tenant(client, auth_context):
    """加入组织必须换发令牌。

    回归：`get_current_user` 只读 Token 里的 tenant_id、**不回查 DB**——
    若 join 只返回成员信息而不换发令牌，用户会「已加入新组织，
    但后续请求仍以旧组织身份执行」（用旧 Token 查 /auth/me 即可复现）。
    """
    name, outsider = _register()
    old_token = _headers(name, outsider)["Authorization"].split(" ", 1)[1]

    r = client.post(
        "/api/v1/auth/join",
        json={"invite_code": auth_context["invite_code"]},
        headers={"Authorization": "Bearer " + old_token},
    )
    assert r.status_code == 200
    data = r.json()
    assert data["access_token"], "join 必须返回新签发的 access_token"
    # 租户不同 → payload 不同 → 令牌必然不同
    assert data["access_token"] != old_token

    me = client.get(
        "/api/v1/auth/me", headers={"Authorization": "Bearer " + data["access_token"]}
    )
    assert me.status_code == 200
    body = me.json()
    assert body["tenant_id"] == auth_context["tenant_id"]
    assert body["tenant_role"] == "member"
    assert body["collections"]["shared"] == auth_context["collections"]["shared"]


def test_register_with_invite_code_through_api(client, auth_context):
    """通过注册接口带邀请码加入组织 → 返回 member 身份与组织名。"""
    r = client.post("/api/v1/auth/register", json={
        "username": "pytest_join_" + uuid.uuid4().hex[:8],
        "password": "pytest_pass_123",
        "invite_code": auth_context["invite_code"],
    })
    assert r.status_code == 200
    data = r.json()
    assert data["tenant_id"] == auth_context["tenant_id"]
    assert data["tenant_role"] == "member"
    assert data["access_token"]
    assert data["refresh_token"]


def test_register_with_org_name_through_api(client):
    r = client.post("/api/v1/auth/register", json={
        "username": "pytest_neworg_" + uuid.uuid4().hex[:8],
        "password": "pytest_pass_123",
        "org_name": "接口创建的组织",
    })
    assert r.status_code == 200
    data = r.json()
    assert data["tenant_role"] == "owner"
    assert data["tenant_name"] == "接口创建的组织"
    assert data["tenant_id"].startswith("org_")


def test_register_rejects_bad_invite_code_through_api(client):
    r = client.post("/api/v1/auth/register", json={
        "username": "pytest_badcode_" + uuid.uuid4().hex[:8],
        "password": "pytest_pass_123",
        "invite_code": "definitely-not-valid",
    })
    assert r.status_code == 400
    assert "邀请码" in r.json()["detail"]


def test_me_exposes_tenant_identity(client, auth_context):
    r = client.get("/api/v1/auth/me", headers=auth_context["headers"])
    assert r.status_code == 200
    data = r.json()
    assert data["tenant_id"] == auth_context["tenant_id"]
    assert data["tenant_role"] == "owner"
    assert data["tenant_name"] == auth_context["tenant_name"]
    assert data["collections"]["shared"] == auth_context["collections"]["shared"]
    assert "password_hash" not in data
