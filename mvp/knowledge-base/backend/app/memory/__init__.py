"""
长期记忆模块 — 跨会话上下文恢复

用户打开聊天时，自动加载上次的项目状态和上下文。
- L1: 当前对话上下文（会话内完整保留）
- L2: 近期对话摘要（压缩存储）
- L3: 持久化长期记忆（关键决策、偏好、项目信息）
"""

import json
import sqlite3
import os
from typing import Optional
from datetime import datetime


DB_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "memory.db")


def _get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


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


# ── 用户画像 ──────────────────────────────────────

def save_user_profile(user_id: int, role: str = None, preferences: dict = None,
                      common_skills: list = None, output_style: str = None):
    """保存/更新用户画像"""
    init_memory_db()
    conn = _get_db()
    try:
        existing = conn.execute("SELECT user_id FROM user_profile WHERE user_id = ?", (user_id,)).fetchone()
        if existing:
            conn.execute("""
                UPDATE user_profile SET
                    role = COALESCE(?, role),
                    preferences = COALESCE(?, preferences),
                    common_skills = COALESCE(?, common_skills),
                    output_style = COALESCE(?, output_style),
                    updated_at = datetime('now')
                WHERE user_id = ?
            """, (
                role,
                json.dumps(preferences, ensure_ascii=False) if preferences else None,
                json.dumps(common_skills, ensure_ascii=False) if common_skills else None,
                output_style,
                user_id,
            ))
        else:
            conn.execute("""
                INSERT INTO user_profile (user_id, role, preferences, common_skills, output_style)
                VALUES (?, ?, ?, ?, ?)
            """, (
                user_id,
                role,
                json.dumps(preferences or {}, ensure_ascii=False),
                json.dumps(common_skills or [], ensure_ascii=False),
                output_style or "default",
            ))
        conn.commit()
    finally:
        conn.close()


def get_user_profile(user_id: int) -> Optional[dict]:
    """获取用户画像"""
    init_memory_db()
    conn = _get_db()
    try:
        row = conn.execute("SELECT * FROM user_profile WHERE user_id = ?", (user_id,)).fetchone()
        if not row:
            return None
        return {
            "user_id": row["user_id"],
            "role": row["role"],
            "preferences": json.loads(row["preferences"]) if row["preferences"] else {},
            "common_skills": json.loads(row["common_skills"]) if row["common_skills"] else [],
            "output_style": row["output_style"],
            "updated_at": row["updated_at"],
        }
    finally:
        conn.close()


# ── 项目上下文 ────────────────────────────────────

def save_project_context(user_id: int, project_name: str, tech_stack: str = None,
                         current_progress: str = None, key_decisions: list = None):
    """保存项目上下文"""
    init_memory_db()
    conn = _get_db()
    try:
        conn.execute("""
            INSERT INTO project_context (user_id, project_name, tech_stack, current_progress, key_decisions)
            VALUES (?, ?, ?, ?, ?)
        """, (
            user_id, project_name, tech_stack, current_progress,
            json.dumps(key_decisions or [], ensure_ascii=False),
        ))
        conn.commit()
    finally:
        conn.close()


def get_latest_project(user_id: int) -> Optional[dict]:
    """获取用户最近的项目上下文"""
    init_memory_db()
    conn = _get_db()
    try:
        row = conn.execute(
            "SELECT * FROM project_context WHERE user_id = ? ORDER BY updated_at DESC LIMIT 1",
            (user_id,),
        ).fetchone()
        if not row:
            return None
        return {
            "project_name": row["project_name"],
            "tech_stack": row["tech_stack"],
            "current_progress": row["current_progress"],
            "key_decisions": json.loads(row["key_decisions"]) if row["key_decisions"] else [],
            "updated_at": row["updated_at"],
        }
    finally:
        conn.close()


# ── 对话摘要 ──────────────────────────────────────

def save_conversation_summary(user_id: int, summary: str, key_points: list = None):
    """保存对话摘要"""
    init_memory_db()
    conn = _get_db()
    try:
        conn.execute("""
            INSERT INTO conversation_summary (user_id, summary, key_points)
            VALUES (?, ?, ?)
        """, (user_id, summary, json.dumps(key_points or [], ensure_ascii=False)))
        conn.commit()
    finally:
        conn.close()


def get_recent_summaries(user_id: int, limit: int = 5) -> list:
    """获取最近的对话摘要"""
    init_memory_db()
    conn = _get_db()
    try:
        rows = conn.execute(
            "SELECT * FROM conversation_summary WHERE user_id = ? ORDER BY created_at DESC LIMIT ?",
            (user_id, limit),
        ).fetchall()
        return [{
            "summary": r["summary"],
            "key_points": json.loads(r["key_points"]) if r["key_points"] else [],
            "created_at": r["created_at"],
        } for r in rows]
    finally:
        conn.close()


# ── 上下文恢复 ────────────────────────────────────

def restore_context(user_id: int) -> dict:
    """
    跨会话上下文恢复：用户打开聊天时调用。
    返回完整的上下文快照。
    """
    profile = get_user_profile(user_id)
    project = get_latest_project(user_id)
    summaries = get_recent_summaries(user_id, limit=3)

    return {
        "user_profile": profile,
        "current_project": project,
        "recent_summaries": summaries,
        "restored_at": datetime.now().isoformat(),
        "has_context": bool(profile or project or summaries),
    }
