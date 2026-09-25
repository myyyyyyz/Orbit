"""SQLite 连接工厂（统一 PRAGMA 策略）。

生产问题：默认 SQLite 使用 rollback journal + 无 busy_timeout，只要出现
"写请求 vs 写请求"并发，第二个写者立刻拿到 `database is locked` 并直接抛错。
本项目是多租户 + Agent Loop 双写场景，属于必然触发的形态。

策略：
- WAL：读写不互斥，写不阻塞读（对 SSE 长连接下的并发读尤其重要）。
- busy_timeout：遇到锁时等待而非立刻失败（默认 15s，可用 SQLITE_BUSY_TIMEOUT_MS 调整）。
- synchronous=NORMAL：WAL 下兼顾安全与吞吐的官方推荐档位。
- foreign_keys：SQLite 默认**不**开启外键约束，schema 里写的外键形同注释。
  生产默认开启；非生产默认关闭（历史数据/测试夹具可能不满足约束），
  可用 SQLITE_FOREIGN_KEYS=1|0 显式覆盖。
"""

import os
import sqlite3
from typing import Optional


def busy_timeout_ms() -> int:
    return int(os.getenv("SQLITE_BUSY_TIMEOUT_MS", "15000"))


def _foreign_keys_enabled() -> bool:
    flag = os.getenv("SQLITE_FOREIGN_KEYS")
    if flag is not None:
        return flag.lower() in ("1", "true", "yes")
    from .config import is_production
    return is_production()


def connect(db_path: str, timeout: Optional[float] = None) -> sqlite3.Connection:
    """建立带生产级 PRAGMA 的 SQLite 连接（row_factory=Row）。"""
    if timeout is None:
        timeout = busy_timeout_ms() / 1000.0
    conn = sqlite3.connect(db_path, timeout=timeout)
    conn.row_factory = sqlite3.Row
    try:
        cur = conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute(f"PRAGMA busy_timeout={busy_timeout_ms()}")
        cur.execute("PRAGMA synchronous=NORMAL")
        cur.execute(f"PRAGMA foreign_keys={'ON' if _foreign_keys_enabled() else 'OFF'}")
        cur.close()
    except sqlite3.Error:
        # PRAGMA 失败不应阻止连接可用（如只读文件系统）
        pass
    return conn
