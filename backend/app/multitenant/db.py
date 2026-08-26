"""多租户数据库：连接、路径解析、schema 迁移（Alembic 管理）。

迁移文件位于 alembic/versions/，由 `alembic upgrade head` 管理 schema 版本。
"""

import os
import sqlite3
import threading

from alembic.config import Config as AlembicConfig
from alembic import command

from ..config import settings


def _resolve_db_path() -> str:
    """从 DATABASE_URL 解析 SQLite 文件路径（预留 PostgreSQL 升级路径）"""
    db_url = settings.DATABASE_URL
    if db_url.startswith("sqlite:///"):
        return db_url[len("sqlite:///"):]
    # 未来: if db_url.startswith("postgresql://") → asyncpg
    raise ValueError(f"不支持的数据库 URL scheme: {db_url}")


DB_PATH = _resolve_db_path()

# ─────────────────────────────────────────────────────────────
# 迁移只执行一次
#
# 业务函数（register_user / create_session 等）历史上都会调用 init_db()，
# 若每次都跑 alembic upgrade 会有两个问题：
#   1) 性能：每次注册/登录都完整执行一遍迁移链路
#   2) 并发：alembic 的 run_env() 依赖模块级全局 proxy（EnvironmentContext），
#      并发进入时先退出的一方会 del globals_['config']，
#      后退出的一方随即抛 KeyError: 'config'
# 因此这里用「一次性标记 + 线程锁」保证进程内只迁移一次，
# 业务侧继续调用 init_db() 不会有副作用。
# ─────────────────────────────────────────────────────────────

_migrated = False
_migrate_lock = threading.Lock()


def _get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(force: bool = False) -> None:
    """确保多租户数据库 schema 已升级到最新版本（进程内幂等）。

    参数:
        force: 忽略一次性标记强制重新执行迁移（仅测试/运维场景使用）。
    """
    global _migrated

    if _migrated and not force:
        return

    with _migrate_lock:
        # 双重检查：等锁期间可能已被其他线程完成
        if _migrated and not force:
            return

        # 确保数据目录存在
        os.makedirs(os.path.dirname(DB_PATH) or ".", exist_ok=True)

        # 数据库文件不存在时先建空文件，供 Alembic 连接
        if not os.path.exists(DB_PATH):
            sqlite3.connect(DB_PATH).close()

        alembic_ini = os.path.join(os.path.dirname(__file__), "..", "..", "alembic.ini")
        alembic_cfg = AlembicConfig(alembic_ini)

        # DATABASE_URL 环境变量优先于 alembic.ini 中的配置
        db_url = os.getenv("DATABASE_URL")
        if db_url:
            alembic_cfg.set_main_option("sqlalchemy.url", db_url)

        command.upgrade(alembic_cfg, "head")
        _migrated = True
