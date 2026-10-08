"""租户（组织）与成员管理。

数据模型（见 alembic/versions/*_tenant_membership.py）：

- ``tenants``：``id TEXT PK`` / ``name`` / ``plan`` / ``max_collections`` /
  ``max_storage_mb`` / ``invite_code`` / ``owner_user_id``
- ``users.tenant_id``  → 所属租户（成员与租户是多对一）
- ``users.tenant_role`` → 租户内角色：``owner`` / ``admin`` / ``member``

与 ``users.role``（平台级 ``user`` / ``admin``）分开：平台管理员管全站，
租户内角色只管本组织的成员与设置。把两者混为一谈，就会出现
"某组织 owner 顺手拿到平台管理员权限"这类越权。
"""

import secrets
from typing import Optional

from ..logging_config import get_logger
from .db import _get_db, init_db

logger = get_logger(__name__)

TENANT_ROLES = ("owner", "admin", "member")
DEFAULT_PLAN = "free"
DEFAULT_MAX_COLLECTIONS = 5
DEFAULT_MAX_STORAGE_MB = 500


class TenantError(RuntimeError):
    """租户操作的可预期失败（对外转成 4xx，不泄露内部细节）。"""


def _new_tenant_id() -> str:
    """租户 ID 由服务端生成（不接受客户端传入，避免伪造 / 撞号）。"""
    return f"org_{secrets.token_hex(8)}"


def _new_invite_code() -> str:
    return secrets.token_hex(6)


# ── 查询 ──────────────────────────────────────────


def get_tenant(tenant_id: str) -> Optional[dict]:
    if not tenant_id:
        return None
    init_db()
    conn = _get_db()
    try:
        row = conn.execute("SELECT * FROM tenants WHERE id = ?", (tenant_id,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def get_tenant_by_invite_code(invite_code: str) -> Optional[dict]:
    code = (invite_code or "").strip()
    if not code:
        return None
    init_db()
    conn = _get_db()
    try:
        row = conn.execute(
            "SELECT * FROM tenants WHERE invite_code = ?", (code,)
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def list_tenants(limit: int = 200) -> list[dict]:
    init_db()
    conn = _get_db()
    try:
        rows = conn.execute(
            "SELECT * FROM tenants ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def list_members(tenant_id: str) -> list[dict]:
    """列出租户成员（只返回可对外暴露的字段，**不含** password_hash）。"""
    if not tenant_id:
        return []
    init_db()
    conn = _get_db()
    try:
        rows = conn.execute(
            "SELECT id, username, role, tenant_role, created_at FROM users "
            "WHERE tenant_id = ? ORDER BY id",
            (tenant_id,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def count_members(tenant_id: str) -> int:
    if not tenant_id:
        return 0
    init_db()
    conn = _get_db()
    try:
        row = conn.execute(
            "SELECT COUNT(*) AS n FROM users WHERE tenant_id = ?", (tenant_id,)
        ).fetchone()
        return int(row["n"]) if row else 0
    finally:
        conn.close()


# ── 创建 / 修改 ────────────────────────────────────


def create_tenant(
    name: str,
    *,
    owner_user_id: Optional[int] = None,
    plan: str = DEFAULT_PLAN,
    max_collections: int = DEFAULT_MAX_COLLECTIONS,
    max_storage_mb: int = DEFAULT_MAX_STORAGE_MB,
) -> dict:
    """创建租户，返回租户整行（含 ``invite_code``，供组织 owner 分享）。"""
    clean_name = (name or "").strip() or "未命名组织"
    if len(clean_name) > 80:
        raise TenantError("组织名称过长（上限 80 字符）")

    init_db()
    conn = _get_db()
    try:
        tenant_id = _new_tenant_id()
        invite_code = _new_invite_code()
        conn.execute(
            "INSERT INTO tenants "
            "(id, name, plan, max_collections, max_storage_mb, invite_code, owner_user_id) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                tenant_id, clean_name, plan, max_collections, max_storage_mb,
                invite_code, owner_user_id,
            ),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM tenants WHERE id = ?", (tenant_id,)).fetchone()
        logger.info("tenant_created", tenant_id=tenant_id, owner_user_id=owner_user_id)
        return dict(row)
    finally:
        conn.close()


def rename_tenant(tenant_id: str, name: str) -> dict:
    clean_name = (name or "").strip()
    if not clean_name:
        raise TenantError("组织名称不能为空")
    if len(clean_name) > 80:
        raise TenantError("组织名称过长（上限 80 字符）")

    init_db()
    conn = _get_db()
    try:
        cursor = conn.execute(
            "UPDATE tenants SET name = ?, updated_at = datetime('now') WHERE id = ?",
            (clean_name, tenant_id),
        )
        conn.commit()
        if cursor.rowcount != 1:
            raise TenantError("组织不存在")
        row = conn.execute("SELECT * FROM tenants WHERE id = ?", (tenant_id,)).fetchone()
        return dict(row)
    finally:
        conn.close()


def rotate_invite_code(tenant_id: str) -> str:
    init_db()
    conn = _get_db()
    try:
        code = _new_invite_code()
        cursor = conn.execute(
            "UPDATE tenants SET invite_code = ?, updated_at = datetime('now') WHERE id = ?",
            (code, tenant_id),
        )
        conn.commit()
        if cursor.rowcount != 1:
            raise TenantError("组织不存在")
        return code
    finally:
        conn.close()


def add_member(
    user_id: int, tenant_id: str, tenant_role: str = "member"
) -> dict:
    """把已有用户加入（或迁移到）某租户。

    ⚠️ 会**替换**用户原有租户归属。调用方（注册 / 加入组织接口）负责语义校验。
    """
    if tenant_role not in TENANT_ROLES:
        raise TenantError(f"非法租户角色: {tenant_role}")

    init_db()
    conn = _get_db()
    try:
        existing = conn.execute(
            "SELECT id FROM users WHERE id = ?", (user_id,)
        ).fetchone()
        if existing is None:
            raise TenantError("用户不存在")
        tenant = conn.execute(
            "SELECT id FROM tenants WHERE id = ?", (tenant_id,)
        ).fetchone()
        if tenant is None:
            raise TenantError("组织不存在")

        conn.execute(
            "UPDATE users SET tenant_id = ?, tenant_role = ? WHERE id = ?",
            (tenant_id, tenant_role, user_id),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        result = dict(row)
        result.pop("password_hash", None)
        logger.info("tenant_member_added", tenant_id=tenant_id, user_id=user_id,
                    tenant_role=tenant_role)
        return result
    finally:
        conn.close()


def update_member_role(tenant_id: str, user_id: int, tenant_role: str) -> dict:
    if tenant_role not in TENANT_ROLES:
        raise TenantError(f"非法租户角色: {tenant_role}")

    init_db()
    conn = _get_db()
    try:
        target = conn.execute(
            "SELECT id, tenant_role FROM users WHERE id = ? AND tenant_id = ?",
            (user_id, tenant_id),
        ).fetchone()
        if target is None:
            raise TenantError("成员不存在")

        # 不能把最后一个 owner 降权——否则组织再没人能管理成员与配额
        if target["tenant_role"] == "owner" and tenant_role != "owner":
            owners = conn.execute(
                "SELECT COUNT(*) AS n FROM users WHERE tenant_id = ? AND tenant_role = 'owner'",
                (tenant_id,),
            ).fetchone()
            if owners and int(owners["n"]) <= 1:
                raise TenantError("不能降级最后一个 owner")

        conn.execute(
            "UPDATE users SET tenant_role = ? WHERE id = ? AND tenant_id = ?",
            (tenant_role, user_id, tenant_id),
        )
        conn.commit()
        row = conn.execute(
            "SELECT id, username, role, tenant_role FROM users WHERE id = ?", (user_id,)
        ).fetchone()
        return dict(row)
    finally:
        conn.close()


def tenant_summary(tenant_id: str) -> dict:
    """租户概览（组织信息 + 成员数 + 配额），供前端设置页展示。"""
    tenant = get_tenant(tenant_id)
    if tenant is None:
        raise TenantError("组织不存在")
    return {
        "id": tenant["id"],
        "name": tenant["name"],
        "plan": tenant["plan"],
        "max_collections": tenant["max_collections"],
        "max_storage_mb": tenant["max_storage_mb"],
        "invite_code": tenant.get("invite_code"),
        "owner_user_id": tenant.get("owner_user_id"),
        "created_at": tenant.get("created_at"),
        "member_count": count_members(tenant_id),
    }


def collections_for(tenant_id: Optional[str], user_id: Optional[int]) -> dict:
    """返回该用户可用的两个知识库 Collection 名（供前端展示 / 排障）。"""
    from .naming import anon_collection, personal_collection, shared_collection

    if not tenant_id:
        return {"shared": None, "personal": None, "anonymous": anon_collection()}
    return {
        "shared": shared_collection(tenant_id),
        "personal": personal_collection(tenant_id, user_id) if user_id is not None else None,
        "anonymous": anon_collection(),
    }
