"""
多用户/企业隔离模块

每个用户/租户拥有独立的知识库 collection，数据互不可见。
- 认证：JWT Token + bcrypt 密码哈希
- 隔离：ChromaDB collection 按用户隔离（user_{user_id}）
- 权限：read / write / admin 三级
"""

import json
import sqlite3
import os
from typing import Optional
from urllib.parse import urlparse

import secrets

import bcrypt
from ..config import settings


# ── 用户数据库 ────────────────────────────────────

def _resolve_db_path() -> str:
    """从 DATABASE_URL 解析 SQLite 文件路径（预留 PostgreSQL 升级路径）"""
    db_url = settings.DATABASE_URL
    if db_url.startswith("sqlite:///"):
        return db_url[len("sqlite:///"):]
    # 未来: if db_url.startswith("postgresql://") → asyncpg
    raise ValueError(f"不支持的数据库 URL scheme: {db_url}")


DB_PATH = _resolve_db_path()


def _get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """初始化多租户数据库"""
    conn = _get_db()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            role TEXT DEFAULT 'user',
            tenant_id TEXT,
            created_at TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS tenants (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            plan TEXT DEFAULT 'free',
            max_collections INTEGER DEFAULT 5,
            max_storage_mb INTEGER DEFAULT 500,
            created_at TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS sessions (
            id TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL,
            context TEXT,
            created_at TEXT DEFAULT (datetime('now')),
            updated_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (user_id) REFERENCES users(id)
        );
    """)
    conn.commit()
    conn.close()


# ── 密码哈希（bcrypt）──────────────────────────────

def _hash_password(password: str) -> str:
    """bcrypt 哈希（自动加随机盐，work_factor=12）"""
    # 截断到 72 字节（bcrypt 固有限制）
    password_bytes = password.encode("utf-8")[:72]
    return bcrypt.hashpw(password_bytes, bcrypt.gensalt(rounds=12)).decode("utf-8")


def _verify_password(password: str, stored: str) -> bool:
    """bcrypt 验证"""
    return bcrypt.checkpw(password.encode("utf-8"), stored.encode("utf-8"))


# ── 用户管理 ──────────────────────────────────────

def register_user(username: str, password: str, tenant_id: str = None) -> dict:
    """注册用户"""
    init_db()
    conn = _get_db()
    try:
        existing = conn.execute("SELECT id FROM users WHERE username = ?", (username,)).fetchone()
        if existing:
            return {"error": "用户名已存在"}

        cursor = conn.execute(
            "INSERT INTO users (username, password_hash, tenant_id) VALUES (?, ?, ?)",
            (username, _hash_password(password), tenant_id),
        )
        user_id = cursor.lastrowid
        conn.commit()

        return {
            "user_id": user_id,
            "username": username,
            "tenant_id": tenant_id,
            "collection_name": f"user_{user_id}",
        }
    finally:
        conn.close()


def login_user(username: str, password: str) -> Optional[dict]:
    """登录验证"""
    init_db()
    conn = _get_db()
    try:
        row = conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
        if not row or not _verify_password(password, row["password_hash"]):
            return None

        return {
            "user_id": row["id"],
            "username": row["username"],
            "role": row["role"],
            "tenant_id": row["tenant_id"],
            "collection_name": f"user_{row['id']}",
        }
    finally:
        conn.close()


def get_user_by_id(user_id: int) -> Optional[dict]:
    """根据 ID 获取用户"""
    init_db()
    conn = _get_db()
    try:
        row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        if not row:
            return None
        return dict(row)
    finally:
        conn.close()


# ── Collection 隔离 ──────────────────────────────

def get_user_collection(user_id: int) -> str:
    """获取用户的专属 collection 名称"""
    return f"user_{user_id}"


# ── 会话管理（长期记忆用）────────────────────────

def save_session(user_id: int, context: str) -> str:
    """保存会话上下文（长期记忆）"""
    init_db()
    conn = _get_db()
    session_id = secrets.token_hex(8)
    try:
        conn.execute(
            "INSERT INTO sessions (id, user_id, context) VALUES (?, ?, ?)",
            (session_id, user_id, context),
        )
        conn.commit()
        return session_id
    finally:
        conn.close()


def get_session(session_id: str) -> Optional[dict]:
    """获取会话上下文"""
    init_db()
    conn = _get_db()
    try:
        row = conn.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()
        if not row:
            return None
        return dict(row)
    finally:
        conn.close()


def get_latest_session(user_id: int) -> Optional[dict]:
    """获取用户最近的会话（跨会话恢复）"""
    init_db()
    conn = _get_db()
    try:
        row = conn.execute(
            "SELECT * FROM sessions WHERE user_id = ? ORDER BY updated_at DESC LIMIT 1",
            (user_id,),
        ).fetchone()
        if not row:
            return None
        return dict(row)
    finally:
        conn.close()
