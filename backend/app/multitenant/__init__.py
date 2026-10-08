"""
多用户 / 多租户隔离模块

两级隔离粒度（对应"组织共享 + 个人私有"）：
- 组织共享：租户内所有成员可见 → ChromaDB collection ``t_<tenant>``
- 成员私有：仅本人可见         → ChromaDB collection ``p_<tenant:user>``
- 匿名沙箱：未登录访客         → 独立 collection，**永不**回退全局库

实现拆分：
- ``naming``   命名规则（Collection / 目录）——唯一事实源
- ``context``  请求级租户上下文（ContextVar + TenantScope）
- ``db``       连接 / 路径解析 / Alembic 迁移
- ``password`` 密码哈希
- ``users``    用户管理（注册即建/入组织）
- ``tenants``  组织与成员管理
- ``sessions`` 会话管理
"""

from .context import (
    ANON_SCOPE,
    PERSONAL,
    SHARED,
    TenantScope,
    clear_current_scope,
    get_current_scope,
    read_scopes,
    reset_current_scope,
    scope_for,
    scope_from_user,
    set_current_scope,
)
from .db import DB_PATH, _get_db, init_db
from .naming import (
    anon_collection,
    normalize_scope,
    personal_collection,
    safe_dir_name,
    shared_collection,
    slug,
)
from .password import _hash_password, _verify_password
from .paths import memory_dir, scope_root, uploads_dir, user_memory_dir
from .sessions import get_latest_session, get_session, save_session
from .tenants import (
    TENANT_ROLES,
    TenantError,
    add_member,
    collections_for,
    count_members,
    create_tenant,
    get_tenant,
    get_tenant_by_invite_code,
    list_members,
    list_tenants,
    rename_tenant,
    rotate_invite_code,
    tenant_summary,
    update_member_role,
)
from .users import (
    get_public_user,
    get_user_by_id,
    get_user_collection,
    join_tenant_by_invite_code,
    login_user,
    register_user,
)

__all__ = [
    # context
    "ANON_SCOPE",
    "PERSONAL",
    "SHARED",
    "TenantScope",
    "clear_current_scope",
    "get_current_scope",
    "read_scopes",
    "reset_current_scope",
    "scope_for",
    "scope_from_user",
    "set_current_scope",
    # naming
    "anon_collection",
    "normalize_scope",
    "personal_collection",
    "safe_dir_name",
    "shared_collection",
    "slug",
    # db
    "DB_PATH",
    "_get_db",
    "init_db",
    # paths
    "memory_dir",
    "scope_root",
    "uploads_dir",
    "user_memory_dir",
    # password
    "_hash_password",
    "_verify_password",
    # users
    "get_public_user",
    "get_user_by_id",
    "get_user_collection",
    "join_tenant_by_invite_code",
    "login_user",
    "register_user",
    # tenants
    "TENANT_ROLES",
    "TenantError",
    "add_member",
    "collections_for",
    "count_members",
    "create_tenant",
    "get_tenant",
    "get_tenant_by_invite_code",
    "list_members",
    "list_tenants",
    "rename_tenant",
    "rotate_invite_code",
    "tenant_summary",
    "update_member_role",
    # sessions
    "save_session",
    "get_session",
    "get_latest_session",
]
