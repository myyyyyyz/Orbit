"""multitenant/ — 多租户模块测试（SQLite 已隔离到临时目录）

覆盖：注册即建组织 / 邀请码入组 / 成员与角色 / 配额概览 / 会话归属 /
密码哈希 / 命名规则。
"""
import uuid

import pytest

from app.multitenant import (
    TENANT_ROLES,
    TenantError,
    _hash_password,
    _get_db,
    _verify_password,
    add_member,
    collections_for,
    count_members,
    create_tenant,
    get_tenant,
    get_tenant_by_invite_code,
    get_session,
    get_latest_session,
    get_user_by_id,
    init_db,
    join_tenant_by_invite_code,
    list_members,
    login_user,
    register_user,
    rename_tenant,
    rotate_invite_code,
    save_session,
    tenant_summary,
    update_member_role,
)
from app.multitenant.naming import (
    personal_collection,
    shared_collection,
    slug,
)


def _uname(prefix="pytest_mt"):
    return prefix + "_" + uuid.uuid4().hex[:8]


# ── 基础 ──────────────────────────────────────────

def test_init_db_idempotent():
    init_db()
    init_db()  # 重复初始化不报错


def test_password_hash_and_verify():
    h = _hash_password("my_secret_123")
    assert h != "my_secret_123"
    assert h.startswith("$2b$")
    assert _verify_password("my_secret_123", h)
    assert not _verify_password("wrong_password", h)


def test_password_hash_truncates_72_bytes():
    """bcrypt 72 字节限制：超长密码截断后不报错"""
    long_pwd = "a" * 200
    h = _hash_password(long_pwd)
    assert _verify_password("a" * 72, h)


# ── 命名规则 ──────────────────────────────────────

def test_slug_is_idempotent_for_safe_values():
    assert slug("org_acme") == "org_acme"
    assert slug("org-123.v2") == "org-123.v2"


def test_slug_never_returns_invalid_chroma_name():
    for raw in ["org/a b", "组织", "x" * 200, "", "..", "-lead", "trail-"]:
        out = slug(raw)
        assert 1 <= len(out) <= 42
        assert out[0].isalnum() and out[-1].isalnum()
        assert all(c.isalnum() or c in "._-" for c in out)


def test_slug_is_injective_for_unsafe_inputs():
    """不同输入不能规范成同一个名字（截断会破坏这一点）。"""
    assert slug("org/a") != slug("org-a")
    assert slug("x" * 100 + "A") != slug("x" * 100 + "B")


def test_collection_namespaces_do_not_collide():
    """共享库与私有库用不同前缀，绝不可能撞名。"""
    assert shared_collection("a:1") != personal_collection("a", "1")
    assert shared_collection("org") == "t_org"
    assert personal_collection("org", 7).startswith("p_")


# ── 注册 / 登录 ───────────────────────────────────

def test_register_creates_organization_and_owner():
    username = _uname()
    result = register_user(username, "pass123")
    assert result["username"] == username
    assert result["user_id"] > 0
    # 注册即建组织，注册者是 owner
    assert result["tenant_id"].startswith("org_")
    assert result["tenant_role"] == "owner"
    assert result["tenant_name"] == f"{username} 的组织"
    assert result["invite_code"]
    assert result["collections"]["shared"] == shared_collection(result["tenant_id"])
    assert result["collections"]["personal"] == personal_collection(
        result["tenant_id"], result["user_id"]
    )


def test_register_with_org_name():
    username = _uname()
    result = register_user(username, "pass123", org_name="Acme 研发团队")
    assert result["tenant_name"] == "Acme 研发团队"
    tenant = get_tenant(result["tenant_id"])
    assert tenant["name"] == "Acme 研发团队"
    assert tenant["owner_user_id"] == result["user_id"]


def test_register_with_invite_code_joins_existing_org():
    owner = register_user(_uname(), "pass123", org_name="共享组织")
    member_name = _uname()
    member = register_user(
        member_name, "pass123", invite_code=owner["invite_code"]
    )
    assert member["tenant_id"] == owner["tenant_id"]
    assert member["tenant_role"] == "member"
    # member 不该拿到邀请码（避免随手扩散）
    assert member["invite_code"] is None
    assert count_members(owner["tenant_id"]) == 2


def test_register_with_invalid_invite_code_is_rejected():
    result = register_user(_uname(), "pass123", invite_code="nope_not_a_code")
    assert "error" in result
    assert "邀请码" in result["error"]


def test_register_duplicate_username():
    username = _uname()
    register_user(username, "pass123")
    result = register_user(username, "other_pass")
    assert result == {"error": "用户名已存在"}


def test_login_returns_tenant_identity():
    username = _uname()
    reg = register_user(username, "correct_pass")
    result = login_user(username, "correct_pass")
    assert result is not None
    assert result["username"] == username
    assert result["role"] == "user"
    assert result["tenant_id"] == reg["tenant_id"]
    assert result["tenant_role"] == "owner"
    assert result["tenant_name"] == reg["tenant_name"]


def test_login_wrong_password():
    username = _uname()
    register_user(username, "correct_pass")
    assert login_user(username, "wrong_pass") is None


def test_login_nonexistent_user():
    assert login_user(_uname("nobody"), "pass") is None


def test_get_user_by_id():
    username = _uname()
    reg = register_user(username, "pass123")
    user = get_user_by_id(reg["user_id"])
    assert user["username"] == username
    assert user["tenant_id"] == reg["tenant_id"]
    assert user["tenant_role"] == "owner"
    assert "password_hash" in user  # 内部字段存在（API 层负责过滤）
    assert get_user_by_id(999999) is None


# ── 组织与成员管理 ─────────────────────────────────

def test_create_and_get_tenant():
    tenant = create_tenant("独立组织")
    assert tenant["id"].startswith("org_")
    assert tenant["plan"] == "free"
    assert tenant["max_collections"] == 5
    assert get_tenant(tenant["id"])["name"] == "独立组织"
    assert get_tenant("org_不存在") is None


def test_get_tenant_by_invite_code():
    tenant = create_tenant("邀请码组织")
    assert get_tenant_by_invite_code(tenant["invite_code"])["id"] == tenant["id"]
    assert get_tenant_by_invite_code("") is None


def test_rotate_invite_code_invalidates_old():
    tenant = create_tenant("轮换组织")
    old = tenant["invite_code"]
    new = rotate_invite_code(tenant["id"])
    assert new != old
    assert get_tenant_by_invite_code(old) is None
    assert get_tenant_by_invite_code(new)["id"] == tenant["id"]


def test_rename_tenant():
    tenant = create_tenant("旧名字")
    renamed = rename_tenant(tenant["id"], "新名字")
    assert renamed["name"] == "新名字"
    with pytest.raises(TenantError):
        rename_tenant(tenant["id"], "   ")
    with pytest.raises(TenantError):
        rename_tenant("org_不存在", "x")


def test_list_members_never_exposes_password_hash():
    owner = register_user(_uname(), "pass123")
    members = list_members(owner["tenant_id"])
    assert len(members) == 1
    assert members[0]["tenant_role"] == "owner"
    assert "password_hash" not in members[0]


def test_add_member_moves_user_into_tenant():
    tenant = create_tenant("目标组织")
    other = register_user(_uname(), "pass123")
    assert other["tenant_id"] != tenant["id"]

    moved = add_member(other["user_id"], tenant["id"], "admin")
    assert moved["tenant_id"] == tenant["id"]
    assert moved["tenant_role"] == "admin"
    assert "password_hash" not in moved


def test_add_member_rejects_unknown_tenant_and_role():
    user = register_user(_uname(), "pass123")
    with pytest.raises(TenantError):
        add_member(user["user_id"], "org_不存在")
    with pytest.raises(TenantError):
        add_member(user["user_id"], user["tenant_id"], "superuser")


def test_join_tenant_by_invite_code():
    target = create_tenant("被加入组织")
    user = register_user(_uname(), "pass123")
    member = join_tenant_by_invite_code(user["user_id"], target["invite_code"])
    assert member["tenant_id"] == target["id"]
    assert member["tenant_role"] == "member"
    with pytest.raises(TenantError):
        join_tenant_by_invite_code(user["user_id"], "bad-code")


def test_update_member_role_and_last_owner_protection():
    owner = register_user(_uname(), "pass123")
    tenant_id = owner["tenant_id"]

    # 不能把最后一个 owner 降级
    with pytest.raises(TenantError, match="最后一个 owner"):
        update_member_role(tenant_id, owner["user_id"], "member")

    member = register_user(_uname(), "pass123", invite_code=owner["invite_code"])
    updated = update_member_role(tenant_id, member["user_id"], "admin")
    assert updated["tenant_role"] == "admin"
    assert "password_hash" not in updated

    # 有了第二个 owner 之后，原 owner 可以降级
    update_member_role(tenant_id, member["user_id"], "owner")
    demoted = update_member_role(tenant_id, owner["user_id"], "member")
    assert demoted["tenant_role"] == "member"

    with pytest.raises(TenantError):
        update_member_role(tenant_id, 999999, "admin")


def test_tenant_summary_has_quota_and_member_count():
    owner = register_user(_uname(), "pass123", org_name="概览组织")
    summary = tenant_summary(owner["tenant_id"])
    assert summary["name"] == "概览组织"
    assert summary["plan"] == "free"
    assert summary["max_collections"] == 5
    assert summary["max_storage_mb"] == 500
    assert summary["invite_code"]
    assert summary["member_count"] == 1
    with pytest.raises(TenantError):
        tenant_summary("org_不存在")


def test_collections_for_anonymous_and_member():
    anon = collections_for(None, None)
    assert anon["shared"] is None and anon["personal"] is None
    assert anon["anonymous"]

    owner = register_user(_uname(), "pass123")
    names = collections_for(owner["tenant_id"], owner["user_id"])
    assert names["shared"] == shared_collection(owner["tenant_id"])
    assert names["personal"] == personal_collection(owner["tenant_id"], owner["user_id"])


def test_tenant_roles_constant():
    assert set(TENANT_ROLES) == {"owner", "admin", "member"}


# ── 会话 ──────────────────────────────────────────

def test_session_lifecycle_carries_tenant():
    reg = register_user(_uname(), "pass123")
    uid = reg["user_id"]
    sid = save_session(uid, "项目上下文：Orbit 开发中")
    assert len(sid) == 16  # token_hex(8)

    s = get_session(sid)
    assert s["context"] == "项目上下文：Orbit 开发中"
    assert s["user_id"] == uid
    # 会话同样带租户归属（便于按租户统计 / 清理）
    assert s["tenant_id"] == reg["tenant_id"]

    latest = get_latest_session(uid)
    assert latest["id"] == sid


def test_get_session_nonexistent():
    assert get_session("no_such_session") is None


def test_get_latest_session_empty():
    reg = register_user(_uname(), "pass123")
    # 新用户无会话（注意：auth_token fixture 的 pytest_user 可能有）
    assert get_latest_session(reg["user_id"]) is None


# ── 迁移回填 ──────────────────────────────────────

def test_migration_backfilled_tenant_role_column():
    """迁移必须让 users.tenant_role 存在且有值（否则租户授权无从判定）。"""
    conn = _get_db()
    try:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(users)").fetchall()}
        assert {"tenant_id", "tenant_role"} <= columns
        tenant_columns = {row[1] for row in conn.execute("PRAGMA table_info(tenants)").fetchall()}
        assert {"invite_code", "owner_user_id"} <= tenant_columns
        session_columns = {row[1] for row in conn.execute("PRAGMA table_info(sessions)").fetchall()}
        assert "tenant_id" in session_columns

        rows = conn.execute("SELECT COUNT(*) AS n FROM users WHERE tenant_id IS NULL").fetchone()
        assert rows["n"] == 0, "所有用户都必须有租户归属（回填不能漏）"
    finally:
        conn.close()
