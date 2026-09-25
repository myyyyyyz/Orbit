"""记忆数据库：连接与建表"""

import os

from ..sqlite_utils import connect as _sqlite_connect


DB_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "memory.db")


def _get_db():
    # 统一 PRAGMA（WAL + busy_timeout），详见 app/sqlite_utils.py
    return _sqlite_connect(DB_PATH)


def init_memory_db():
    """初始化记忆数据库"""
    conn = _get_db()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS user_profile (
            user_id INTEGER PRIMARY KEY,
            role TEXT,
            preferences TEXT,
            common_skills TEXT,
            output_style TEXT,
            updated_at TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS project_context (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            project_name TEXT,
            tech_stack TEXT,
            current_progress TEXT,
            key_decisions TEXT,
            created_at TEXT DEFAULT (datetime('now')),
            updated_at TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS conversation_summary (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            summary TEXT,
            key_points TEXT,
            created_at TEXT DEFAULT (datetime('now'))
        );
    """)
    conn.commit()
    conn.close()
