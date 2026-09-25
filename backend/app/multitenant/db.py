"""多租户数据库：连接、路径解析、schema 迁移（Alembic 管理）。

迁移文件位于 alembic/versions/，由 `alembic upgrade head` 管理 schema 版本。
"""

import os
import threading

from alembic.config import Config as AlembicConfig
from alembic import command

from ..config import settings
from ..sqlite_utils import connect as _sqlite_connect


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
    # 统一 PRAGMA：WAL + busy_timeout + foreign_keys（详见 app/sqlite_utils.py）
    return _sqlite_connect(DB_PATH)


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
            _sqlite_connect(DB_PATH).close()

        alembic_ini = os.path.join(os.path.dirname(__file__), "..", "..", "alembic.ini")
        alembic_cfg = AlembicConfig(alembic_ini)

        # 始终用应用实际使用的库地址覆盖 alembic.ini 的默认值。
        #
        # 为什么必须无条件覆盖：alembic.ini 里写的是 `sqlite:///../multitenant.db`，
        # 这是**相对进程 CWD** 解析的；而应用的库路径 `DB_PATH` 由
        # `settings.DATABASE_URL` 相对 `__file__` 解析，与 CWD 无关。
        # 未显式设置 DATABASE_URL 时（本地直接 uvicorn、非 compose 部署）
        # 两者会指向**不同文件**：迁移把 users/sessions/tenants 建到 CWD 相对路径，
        # 应用却去读另一个库，注册/登录直接报 `no such table: users`。
        # compose 里因为显式设了 DATABASE_URL 才侥幸躲过——典型的"容器能跑、
        # 本地/裸机上线就崩"。
        #
        # `settings.DATABASE_URL` 本身已实现"环境变量优先"，所以以它为唯一事实源
        # 既保证与运行时同库，也不会丢失环境变量优先级。
        alembic_cfg.set_main_option("sqlalchemy.url", settings.DATABASE_URL)

        command.upgrade(alembic_cfg, "head")
        _migrated = True
