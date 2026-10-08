"""tenant membership — 让 tenant_id 真正参与隔离

Revision ID: c4f1a9d27b30
Revises: f7a4c3a193d7
Create Date: 2026-10-07

背景
----
初始 schema 里 `tenants` / `users.tenant_id` 已存在，但**从未参与任何过滤**
（`releases.py` 只按 user_id 查、`get_user_collection()` 仍返回 `user_{id}`），
所以实际形态是"多用户单租户"，`tenant ≡ user`。本迁移补齐租户模型所需的字段，
并把历史用户回填到各自的默认组织，使 `tenant_id` 从死字段变成隔离依据。

变更
----
1. ``tenants``：加 ``invite_code`` / ``owner_user_id`` / ``updated_at``
2. ``users``：加 ``tenant_role``（租户内角色，与平台级 ``role`` 分离）
3. ``sessions``：加 ``tenant_id``（会话也归租户，便于按租户统计与清理）
4. 回填：为每个尚无租户的用户创建一个组织并置为 owner，历史数据不丢归属

注意
----
- 时间戳列**不能**用 ``datetime('now')`` 作 ADD COLUMN 的默认值
  （SQLite 只接受常量默认值），因此先建列再回填。
- 不改动既有 revision ``f7a4c3a193d7``，避免破坏已部署实例的版本记录。
"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'c4f1a9d27b30'
down_revision: Union[str, Sequence[str], None] = 'f7a4c3a193d7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _column_exists(table: str, column: str) -> bool:
    """SQLite 没有 ADD COLUMN IF NOT EXISTS，只能自查 pragma 后决定是否执行。"""
    bind = op.get_bind()
    rows = bind.exec_driver_sql(f"PRAGMA table_info({table})").fetchall()
    return any(row[1] == column for row in rows)


def upgrade() -> None:
    # ── 1. tenants：邀请码 / owner / 更新时间 ──
    if not _column_exists("tenants", "invite_code"):
        op.execute("ALTER TABLE tenants ADD COLUMN invite_code TEXT")
    if not _column_exists("tenants", "owner_user_id"):
        op.execute("ALTER TABLE tenants ADD COLUMN owner_user_id INTEGER")
    if not _column_exists("tenants", "updated_at"):
        op.execute("ALTER TABLE tenants ADD COLUMN updated_at TEXT")

    # 回填历史租户的 invite_code / updated_at（列刚加时全为 NULL）
    op.execute(
        "UPDATE tenants SET invite_code = lower(hex(randomblob(6))) "
        "WHERE invite_code IS NULL OR invite_code = ''"
    )
    op.execute(
        "UPDATE tenants SET updated_at = COALESCE(created_at, datetime('now')) "
        "WHERE updated_at IS NULL"
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_tenants_invite_code "
        "ON tenants(invite_code)"
    )

    # ── 2. users：租户内角色 ──
    if not _column_exists("users", "tenant_role"):
        op.execute(
            "ALTER TABLE users ADD COLUMN tenant_role TEXT NOT NULL DEFAULT 'member'"
        )

    # ── 3. sessions：租户维度 ──
    if not _column_exists("sessions", "tenant_id"):
        op.execute("ALTER TABLE sessions ADD COLUMN tenant_id TEXT")

    # ── 4. 回填：无租户的历史用户各自建组织并置为 owner ──
    #
    # 归属不能丢：直接在 users.tenant_id 上找租户是行不通的（它就是 NULL），
    # 所以按"一人一组织"的确定性 id 规则建组织，再用同一规则回填用户。
    op.execute(
        """
        INSERT INTO tenants (id, name, plan, max_collections, max_storage_mb,
                             invite_code, owner_user_id, created_at, updated_at)
        SELECT 'org_u' || u.id, u.username || ' 的组织', 'free', 5, 500,
               lower(hex(randomblob(6))), u.id, datetime('now'), datetime('now')
        FROM users AS u
        WHERE u.tenant_id IS NULL
          AND NOT EXISTS (SELECT 1 FROM tenants AS t WHERE t.id = 'org_u' || u.id)
        """
    )
    op.execute(
        """
        UPDATE users
        SET tenant_id = 'org_u' || id,
            tenant_role = 'owner'
        WHERE tenant_id IS NULL
        """
    )
    op.execute(
        """
        UPDATE users
        SET tenant_role = 'owner'
        WHERE tenant_role = 'member'
          AND id IN (SELECT owner_user_id FROM tenants WHERE owner_user_id IS NOT NULL)
        """
    )

    # 会话归属跟随其所属用户
    op.execute(
        """
        UPDATE sessions
        SET tenant_id = (SELECT u.tenant_id FROM users AS u WHERE u.id = sessions.user_id)
        WHERE tenant_id IS NULL
        """
    )

    op.execute("CREATE INDEX IF NOT EXISTS idx_users_tenant ON users(tenant_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_sessions_tenant ON sessions(tenant_id)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_sessions_tenant")
    op.execute("DROP INDEX IF EXISTS idx_users_tenant")
    op.execute("DROP INDEX IF EXISTS idx_tenants_invite_code")

    for table, column in (
        ("sessions", "tenant_id"),
        ("users", "tenant_role"),
        ("tenants", "updated_at"),
        ("tenants", "owner_user_id"),
        ("tenants", "invite_code"),
    ):
        if _column_exists(table, column):
            op.execute(f"ALTER TABLE {table} DROP COLUMN {column}")
