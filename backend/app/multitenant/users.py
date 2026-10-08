"""用户管理：注册 / 登录 / 查询。

租户语义（本轮改造的核心）：
- 注册时**必选**落地到一个组织：不给邀请码 → 自动建组织并成为 ``owner``；
  给邀请码 → 加入该组织并成为 ``member``。
- 登录后返回该用户的 ``tenant_id`` 与 ``tenant_role``，供认证层写入租户上下文。
- 用户与租户是多对一：一个用户只属于一个组织（同一组织的成员共享知识库）。
"""

from typing import Optional

from ..logging_config import get_logger
from .db import _get_db, init_db
from .password import _hash_password, _verify_password
from .tenants import (
    TenantError,
    add_member,
    collections_for,
    create_tenant,
    get_tenant,
    get_tenant_by_invite_code,
)

logger = get_logger(__name__)


def _user_payload(row) -> dict:
    """把 users 行整理成对外可用的用户信息（剔除 password_hash）。"""
    user_id = row["id"]
    tenant_id = row["tenant_id"]
    return {
        "user_id": user_id,
        "username": row["username"],
        "role": row["role"],
        "tenant_id": tenant_id,
        "tenant_role": row["tenant_role"] if "tenant_role" in row.keys() else None,
        "collections": collections_for(tenant_id, user_id),
    }


def register_user(
    username: str,
    password: str,
    *,
    org_name: Optional[str] = None,
    invite_code: Optional[str] = None,
) -> dict:
    """注册用户并落到某个组织。

    参数:
        org_name:    新建组织的名称；仅在**未提供邀请码**时生效。
        invite_code: 加入已有组织的邀请码；优先级高于 ``org_name``。

    返回: {"user_id", "username", "role", "tenant_id", "tenant_role",
          "tenant_name", "invite_code", "collections"} 或 {"error": "..."}
    """
    init_db()
    conn = _get_db()
    try:
        existing = conn.execute(
            "SELECT id FROM users WHERE username = ?", (username,)
        ).fetchone()
        if existing:
            return {"error": "用户名已存在"}
    finally:
        conn.close()

    # 先确定归属组织：邀请码 → 加入；否则 → 新建
    join_tenant = None
    if invite_code:
        join_tenant = get_tenant_by_invite_code(invite_code)
        if join_tenant is None:
            return {"error": "邀请码无效或已失效"}

    if join_tenant is None:
        try:
            tenant = create_tenant(org_name or f"{username} 的组织")
        except TenantError as exc:
            return {"error": str(exc)}
        tenant_role = "owner"
    else:
        tenant = join_tenant
        tenant_role = "member"

    tenant_id = tenant["id"]

    conn = _get_db()
    try:
        cursor = conn.execute(
            "INSERT INTO users (username, password_hash, tenant_id, tenant_role) "
            "VALUES (?, ?, ?, ?)",
            (username, _hash_password(password), tenant_id, tenant_role),
        )
        user_id = cursor.lastrowid
        conn.commit()

        # 新建组织时把 owner 记回 tenants（供"最后一位 owner 不可降级"等校验使用）
        if tenant_role == "owner":
            conn.execute(
                "UPDATE tenants SET owner_user_id = ? WHERE id = ? AND owner_user_id IS NULL",
                (user_id, tenant_id),
            )
            conn.commit()

        # 回读 role：schema 里是 `role TEXT DEFAULT 'user'`，由数据库决定默认值。
        # 不要在这里硬编码 'user'——回读才能保证与登录路径（login_user 返回
        # row["role"]）一致，也才能在使用不同默认值的库上不出现
        # "注册 role=null、登录 role=user"的不对称（前端据此渲染角色相关 UI）。
        row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        payload = _user_payload(row)
        payload["tenant_name"] = tenant["name"]
        # 邀请码只回给该组织的 owner/admin，避免 member 随手把码扩散出去
        payload["invite_code"] = tenant["invite_code"] if tenant_role == "owner" else None
        logger.info("user_registered", user_id=user_id, tenant_id=tenant_id,
                    tenant_role=tenant_role)
        return payload
    finally:
        conn.close()


def login_user(username: str, password: str) -> Optional[dict]:
    """登录验证；返回用户信息（含租户归属与可用知识库）。"""
    init_db()
    conn = _get_db()
    try:
        row = conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
        if not row or not _verify_password(password, row["password_hash"]):
            return None

        payload = _user_payload(row)
        tenant = get_tenant(payload["tenant_id"]) if payload["tenant_id"] else None
        payload["tenant_name"] = tenant["name"] if tenant else None
        payload["invite_code"] = tenant["invite_code"] if tenant else None
        return payload
    finally:
        conn.close()


def get_user_by_id(user_id: int) -> Optional[dict]:
    """根据 ID 获取用户（**含** password_hash，仅供内部使用）。"""
    init_db()
    conn = _get_db()
    try:
        row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def get_public_user(user_id: int) -> Optional[dict]:
    """根据 ID 获取用户，剔除 password_hash（供 API 层直接返回）。"""
    user = get_user_by_id(user_id)
    if not user:
        return None
    user.pop("password_hash", None)
    return user


def join_tenant_by_invite_code(user_id: int, invite_code: str) -> dict:
    """用邀请码加入组织（已有账号的迁移入口）。

    ⚠️ 会替换该用户原有的租户归属；原租户中的私有文档仍留在原租户空间，
    不会跟随迁移（跨租户搬运会破坏隔离边界）。
    """
    tenant = get_tenant_by_invite_code(invite_code)
    if tenant is None:
        raise TenantError("邀请码无效或已失效")
    return add_member(user_id, tenant["id"], "member")


def get_user_collection(user_id: int) -> Optional[str]:
    """返回该用户所属**组织共享库**的 Collection 名（无租户时返回 None）。

    仅用于展示与排障；实际入库/检索请统一走 ``context.TenantScope``。
    """
    user = get_user_by_id(user_id)
    if not user or not user.get("tenant_id"):
        return None
    return collections_for(user["tenant_id"], user_id)["shared"]
