"""Agent Loop 持久化：loop_groups / loop_events / run_logs 表（挂靠 multitenant.db）。

落地文档: docs/AGENT-LOOP-INTEGRATION.md §4
设计:
- loop_groups: 一个 session 最多一个活跃 loop（session_id UNIQUE + 启动时检查）。
- loop_events: Event Sourcing，整个 loop 过程的事件流，可回放、可审计、多 session 天然隔离。
- run_logs: 结构化运行日志（P1-4），每次 loop 结束写入，支持指标查询。
"""

import json
import os
from datetime import datetime
from typing import Any, Optional

from ..multitenant.db import _get_db, init_db


def init_loop_db():
    """初始化所有表（幂等）。"""
    init_db()
    conn = _get_db()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS loop_groups (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            session_id TEXT UNIQUE NOT NULL,
            status TEXT NOT NULL DEFAULT 'running',
            current_agent TEXT,
            iteration_count INTEGER DEFAULT 0,
            task_desc TEXT,
            project_dir TEXT,
            plan_json TEXT,
            created_at TEXT DEFAULT (datetime('now')),
            updated_at TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS loop_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            loop_id INTEGER NOT NULL,
            seq INTEGER NOT NULL,
            agent TEXT NOT NULL,
            event_type TEXT NOT NULL,
            payload TEXT,
            created_at TEXT DEFAULT (datetime('now'))
        );
        CREATE INDEX IF NOT EXISTS idx_loop_events_loop ON loop_events(loop_id, seq);

        -- Project STATE spine: durable per-project cross-loop state
        CREATE TABLE IF NOT EXISTS project_states (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            project_name TEXT NOT NULL,
            project_dir TEXT NOT NULL,
            state_json TEXT NOT NULL,
            created_at TEXT DEFAULT (datetime('now')),
            updated_at TEXT DEFAULT (datetime('now')),
            UNIQUE(user_id, project_name)
        );

        -- Loop schedules: recurring / one-time triggers
        CREATE TABLE IF NOT EXISTS loop_schedules (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            project_name TEXT NOT NULL,
            task_prompt TEXT NOT NULL,
            cron_expr TEXT NOT NULL,
            mode TEXT DEFAULT 'L1',
            enabled INTEGER DEFAULT 1,
            last_run_at TEXT,
            next_run_at TEXT,
            created_at TEXT DEFAULT (datetime('now')),
            updated_at TEXT DEFAULT (datetime('now'))
        );

        -- Loop-level token budget accounting
        CREATE TABLE IF NOT EXISTS loop_budget_usage (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            loop_id INTEGER NOT NULL,
            agent TEXT NOT NULL,
            prompt_tokens INTEGER DEFAULT 0,
            completion_tokens INTEGER DEFAULT 0,
            total_tokens INTEGER DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (loop_id) REFERENCES loop_groups(id) ON DELETE CASCADE
        );

        -- Global runtime switches (e.g. pause-all)
        CREATE TABLE IF NOT EXISTS global_switches (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL,
            updated_at TEXT DEFAULT (datetime('now'))
        );

        -- P1-4: Structured run logs for metrics & observability
        CREATE TABLE IF NOT EXISTS run_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            loop_id INTEGER NOT NULL,
            loop_group_id INTEGER,
            user_id INTEGER NOT NULL,
            project_name TEXT NOT NULL,
            pattern TEXT DEFAULT 'manual',
            started_at TEXT NOT NULL,
            finished_at TEXT,
            duration_s REAL,
            planner_duration_s REAL,
            builder_duration_s REAL,
            reviewer_duration_s REAL,
            items_found INTEGER DEFAULT 0,
            files_changed INTEGER DEFAULT 0,
            iterations INTEGER DEFAULT 0,
            outcome TEXT,
            human_decision TEXT,
            tokens_estimate INTEGER DEFAULT 0,
            prompt_tokens INTEGER DEFAULT 0,
            completion_tokens INTEGER DEFAULT 0,
            total_tokens INTEGER DEFAULT 0,
            denylist_hits INTEGER DEFAULT 0,
            budget_warnings INTEGER DEFAULT 0,
            escalations INTEGER DEFAULT 0,
            state_snapshot TEXT,
            created_at TEXT DEFAULT (datetime('now')),
            updated_at TEXT DEFAULT (datetime('now'))
        );
        CREATE INDEX IF NOT EXISTS idx_run_logs_project ON run_logs(user_id, project_name);
        CREATE INDEX IF NOT EXISTS idx_run_logs_started ON run_logs(started_at);

        -- 项目级工具策略：前端可配置「自动执行清单」与「需人工同意清单」
        -- policy_json = {"auto_commands": [...], "approval_commands": [...]}
        CREATE TABLE IF NOT EXISTS project_tool_policies (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            project_dir TEXT NOT NULL,
            policy_json TEXT NOT NULL,
            created_at TEXT DEFAULT (datetime('now')),
            updated_at TEXT DEFAULT (datetime('now')),
            UNIQUE(user_id, project_dir)
        );
    """)
    conn.commit()
    conn.close()


def create_loop_group(user_id: Optional[int], session_id: str, task_desc: str, project_dir: str = "") -> int:
    """创建 loop 组，返回 loop_id。调用方需先检查 session 无活跃 loop。"""
    init_loop_db()
    conn = _get_db()
    try:
        cur = conn.execute(
            "INSERT INTO loop_groups (user_id, session_id, task_desc, project_dir) VALUES (?, ?, ?, ?)",
            (user_id, session_id, task_desc, project_dir),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def add_loop_event(loop_id: int, agent: str, event_type: str, payload: dict) -> int:
    """追加事件，返回 seq（写入时递增，供前端按序重放）。"""
    init_loop_db()
    conn = _get_db()
    try:
        row = conn.execute(
            "SELECT COALESCE(MAX(seq), 0) + 1 AS next_seq FROM loop_events WHERE loop_id = ?",
            (loop_id,),
        ).fetchone()
        seq = row["next_seq"]
        conn.execute(
            "INSERT INTO loop_events (loop_id, seq, agent, event_type, payload) VALUES (?, ?, ?, ?, ?)",
            (loop_id, seq, agent, event_type, json.dumps(payload, ensure_ascii=False)),
        )
        conn.commit()
        return seq
    finally:
        conn.close()


def list_loop_groups(user_id: Optional[int] = None) -> list[dict]:
    """列出 loop 组；若提供 user_id 则仅返回该用户。"""
    init_loop_db()
    conn = _get_db()
    try:
        if user_id is not None:
            rows = conn.execute(
                "SELECT * FROM loop_groups WHERE user_id = ? ORDER BY created_at DESC", (user_id,)
            ).fetchall()
        else:
            rows = conn.execute("SELECT * FROM loop_groups ORDER BY created_at DESC").fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_loop_group(loop_id: int) -> Optional[dict]:
    init_loop_db()
    conn = _get_db()
    try:
        row = conn.execute("SELECT * FROM loop_groups WHERE id = ?", (loop_id,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def get_active_loop(session_id: str) -> Optional[dict]:
    """查找 session 下 running/paused/awaiting_signoff 的 loop（用于并发冲突检查）。"""
    init_loop_db()
    conn = _get_db()
    try:
        row = conn.execute(
            "SELECT * FROM loop_groups WHERE session_id = ? AND status IN ('running','paused','awaiting_signoff') "
            "ORDER BY id DESC LIMIT 1",
            (session_id,),
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def get_loop_events(loop_id: int) -> list[dict]:
    init_loop_db()
    conn = _get_db()
    try:
        rows = conn.execute(
            "SELECT seq, agent, event_type, payload, created_at FROM loop_events WHERE loop_id = ? ORDER BY seq",
            (loop_id,),
        ).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            try:
                d["payload"] = json.loads(d["payload"]) if d["payload"] else {}
            except json.JSONDecodeError:
                d["payload"] = {}
            out.append(d)
        return out
    finally:
        conn.close()


def update_loop_group(loop_id: int, **fields):
    """按字段名安全更新 loop_groups（白名单校验，防注入/误更新）。"""
    allowed = {"status", "current_agent", "iteration_count", "plan_json", "project_dir", "updated_at"}
    updates = {k: v for k, v in fields.items() if k in allowed}
    if not updates:
        return
    sets = ", ".join(f"{k} = ?" for k in updates)
    values = list(updates.values())
    values.append(loop_id)
    init_loop_db()
    conn = _get_db()
    try:
        conn.execute(f"UPDATE loop_groups SET {sets} WHERE id = ?", values)
        conn.commit()
    finally:
        conn.close()


# ── Project STATE spine helpers ─────────────────────────────────

def get_project_state(user_id: int, project_name: str) -> Optional[dict]:
    init_loop_db()
    conn = _get_db()
    try:
        row = conn.execute(
            "SELECT * FROM project_states WHERE user_id = ? AND project_name = ?",
            (user_id, project_name),
        ).fetchone()
        if not row:
            return None
        d = dict(row)
        try:
            d["state_json"] = json.loads(d["state_json"]) if d["state_json"] else {}
        except json.JSONDecodeError:
            d["state_json"] = {}
        return d
    finally:
        conn.close()


def upsert_project_state(user_id: int, project_name: str, project_dir: str, state: dict):
    init_loop_db()
    conn = _get_db()
    try:
        now = datetime.now().isoformat()
        exists = conn.execute(
            "SELECT 1 FROM project_states WHERE user_id = ? AND project_name = ?",
            (user_id, project_name),
        ).fetchone()
        state_json = json.dumps(state, ensure_ascii=False)
        if exists:
            conn.execute(
                "UPDATE project_states SET project_dir = ?, state_json = ?, updated_at = ? "
                "WHERE user_id = ? AND project_name = ?",
                (project_dir, state_json, now, user_id, project_name),
            )
        else:
            conn.execute(
                "INSERT INTO project_states (user_id, project_name, project_dir, state_json) VALUES (?, ?, ?, ?)",
                (user_id, project_name, project_dir, state_json),
            )
        conn.commit()
    finally:
        conn.close()


# ── Project tool policy helpers ─────────────────────────────────

def get_tool_policy(user_id: int, project_dir: str) -> Optional[dict]:
    """读取项目级工具策略。

    返回 {"auto_commands": [...], "approval_commands": [...]} 或 None（无记录 → 调用方回退默认）。
    """
    init_loop_db()
    conn = _get_db()
    try:
        row = conn.execute(
            "SELECT * FROM project_tool_policies WHERE user_id = ? AND project_dir = ?",
            (int(user_id or 0), project_dir or ""),
        ).fetchone()
        if not row:
            return None
        d = dict(row)
        try:
            d["policy_json"] = json.loads(d["policy_json"]) if d["policy_json"] else {}
        except json.JSONDecodeError:
            d["policy_json"] = {}
        return d
    finally:
        conn.close()


def upsert_tool_policy(user_id: int, project_dir: str, policy: dict):
    """写入/更新项目级工具策略（按 user_id + project_dir 唯一）。"""
    init_loop_db()
    conn = _get_db()
    try:
        now = datetime.now().isoformat()
        uid = int(user_id or 0)
        pdir = project_dir or ""
        policy_json = json.dumps(policy, ensure_ascii=False)
        exists = conn.execute(
            "SELECT 1 FROM project_tool_policies WHERE user_id = ? AND project_dir = ?",
            (uid, pdir),
        ).fetchone()
        if exists:
            conn.execute(
                "UPDATE project_tool_policies SET policy_json = ?, updated_at = ? "
                "WHERE user_id = ? AND project_dir = ?",
                (policy_json, now, uid, pdir),
            )
        else:
            conn.execute(
                "INSERT INTO project_tool_policies (user_id, project_dir, policy_json) VALUES (?, ?, ?)",
                (uid, pdir, policy_json),
            )
        conn.commit()
    finally:
        conn.close()


# ── Budget helpers ──────────────────────────────────────────────

def record_token_usage(loop_id: int, agent: str, prompt_tokens: int, completion_tokens: int):
    """记录一次 LLM 调用的 token 消耗。"""
    init_loop_db()
    conn = _get_db()
    try:
        conn.execute(
            "INSERT INTO loop_budget_usage (loop_id, agent, prompt_tokens, completion_tokens, total_tokens) "
            "VALUES (?, ?, ?, ?, ?)",
            (loop_id, agent, prompt_tokens, completion_tokens, prompt_tokens + completion_tokens),
        )
        conn.commit()
    finally:
        conn.close()


def get_loop_token_usage(loop_id: int) -> dict:
    """返回 loop 累计 token 消耗。"""
    init_loop_db()
    conn = _get_db()
    try:
        row = conn.execute(
            "SELECT COALESCE(SUM(prompt_tokens),0) AS prompt, "
            "COALESCE(SUM(completion_tokens),0) AS completion, "
            "COALESCE(SUM(total_tokens),0) AS total "
            "FROM loop_budget_usage WHERE loop_id = ?",
            (loop_id,),
        ).fetchone()
        return {"prompt": row["prompt"], "completion": row["completion"], "total": row["total"]}
    finally:
        conn.close()


# ── Global switch helpers ───────────────────────────────────────

def get_global_switch(key: str, default: Any = None) -> Any:
    """读取全局开关（JSON 编码）。"""
    init_loop_db()
    conn = _get_db()
    try:
        row = conn.execute("SELECT value FROM global_switches WHERE key = ?", (key,)).fetchone()
        if not row:
            return default
        try:
            return json.loads(row["value"])
        except json.JSONDecodeError:
            return row["value"]
    finally:
        conn.close()


def set_global_switch(key: str, value: Any):
    """写入/更新全局开关。"""
    init_loop_db()
    conn = _get_db()
    try:
        now = datetime.now().isoformat()
        conn.execute(
            "INSERT INTO global_switches (key, value, updated_at) VALUES (?, ?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
            (key, json.dumps(value, ensure_ascii=False), now),
        )
        conn.commit()
    finally:
        conn.close()


# ── Schedule helpers ─────────────────────────────────────────────-

def list_schedules(user_id: int) -> list[dict]:
    init_loop_db()
    conn = _get_db()
    try:
        rows = conn.execute(
            "SELECT id, project_name, task_prompt, cron_expr, mode, enabled, last_run_at, next_run_at, created_at "
            "FROM loop_schedules WHERE user_id = ? ORDER BY created_at DESC",
            (user_id,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def create_schedule(user_id: int, project_name: str, task_prompt: str, cron_expr: str, mode: str, enabled: bool,
                    next_run_at: Optional[str] = None) -> int:
    init_loop_db()
    conn = _get_db()
    try:
        cur = conn.execute(
            "INSERT INTO loop_schedules (user_id, project_name, task_prompt, cron_expr, mode, enabled, next_run_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (user_id, project_name, task_prompt, cron_expr, mode, int(enabled), next_run_at),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def get_schedule(schedule_id: int) -> Optional[dict]:
    init_loop_db()
    conn = _get_db()
    try:
        row = conn.execute("SELECT * FROM loop_schedules WHERE id = ?", (schedule_id,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def update_schedule(schedule_id: int, **fields):
    """安全更新 schedule 记录（白名单字段）。"""
    allowed = {"project_name", "task_prompt", "cron_expr", "mode", "enabled", "last_run_at", "next_run_at", "updated_at"}
    updates = {k: v for k, v in fields.items() if k in allowed}
    if not updates:
        return
    sets = ", ".join(f"{k} = ?" for k in updates)
    values = list(updates.values())
    values.append(schedule_id)
    init_loop_db()
    conn = _get_db()
    try:
        conn.execute(f"UPDATE loop_schedules SET {sets} WHERE id = ?", values)
        conn.commit()
    finally:
        conn.close()


def delete_schedule(schedule_id: int) -> bool:
    init_loop_db()
    conn = _get_db()
    try:
        cur = conn.execute("DELETE FROM loop_schedules WHERE id = ?", (schedule_id,))
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def get_due_schedules(now: Optional[str] = None) -> list[dict]:
    """获取已到触发时间的 schedule（next_run_at <= now）。"""
    now = now or datetime.now().isoformat()
    init_loop_db()
    conn = _get_db()
    try:
        rows = conn.execute(
            "SELECT * FROM loop_schedules WHERE enabled = 1 AND next_run_at IS NOT NULL AND next_run_at <= ?",
            (now,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


# ── P1-4: Run log helpers ─────────────────────────────────────

def create_run_log(**fields) -> int:
    """创建 run_log 记录，返回 id。"""
    allowed = {
        "loop_id", "loop_group_id", "user_id", "project_name", "pattern",
        "started_at", "finished_at", "duration_s",
        "planner_duration_s", "builder_duration_s", "reviewer_duration_s",
        "items_found", "files_changed", "iterations", "outcome", "human_decision",
        "tokens_estimate", "prompt_tokens", "completion_tokens", "total_tokens",
        "denylist_hits", "budget_warnings", "escalations", "state_snapshot",
    }
    f = {k: v for k, v in fields.items() if k in allowed}
    if not f:
        return -1
    columns = ", ".join(f.keys())
    placeholders = ", ".join("?" for _ in f)
    values = list(f.values())
    init_loop_db()
    conn = _get_db()
    try:
        cur = conn.execute(
            f"INSERT INTO run_logs ({columns}) VALUES ({placeholders})", values
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def update_run_log(run_log_id: int, **fields):
    """更新 run_log 字段（白名单安全更新）。"""
    allowed = {
        "finished_at", "duration_s", "planner_duration_s", "builder_duration_s",
        "reviewer_duration_s", "items_found", "files_changed", "iterations",
        "outcome", "human_decision", "tokens_estimate", "prompt_tokens",
        "completion_tokens", "total_tokens", "denylist_hits", "budget_warnings",
        "escalations", "state_snapshot",
    }
    updates = {k: v for k, v in fields.items() if k in allowed}
    if not updates:
        return
    updates["updated_at"] = datetime.now().isoformat()
    sets = ", ".join(f"{k} = ?" for k in updates)
    values = list(updates.values())
    values.append(run_log_id)
    init_loop_db()
    conn = _get_db()
    try:
        conn.execute(f"UPDATE run_logs SET {sets} WHERE id = ?", values)
        conn.commit()
    finally:
        conn.close()


def get_run_logs(user_id: int, project_name: str = "", days: int = 7, limit: int = 100) -> list[dict]:
    """查询 run_logs，支持按项目和天数过滤。"""
    init_loop_db()
    conn = _get_db()
    try:
        if project_name:
            rows = conn.execute(
                "SELECT * FROM run_logs WHERE user_id = ? AND project_name = ? "
                "AND started_at >= datetime('now', ?) "
                "ORDER BY started_at DESC LIMIT ?",
                (user_id, project_name, f"-{days} days", limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM run_logs WHERE user_id = ? "
                "AND started_at >= datetime('now', ?) "
                "ORDER BY started_at DESC LIMIT ?",
                (user_id, f"-{days} days", limit),
            ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_run_log_metrics(user_id: int, project_name: str = "", days: int = 7) -> dict:
    """聚合指标查询（P2-9）。"""
    init_loop_db()
    conn = _get_db()
    try:
        if project_name:
            filter_clause = "WHERE user_id = ? AND project_name = ? AND started_at >= datetime('now', ?)"
            params = (user_id, project_name, f"-{days} days")
        else:
            filter_clause = "WHERE user_id = ? AND started_at >= datetime('now', ?)"
            params = (user_id, f"-{days} days")

        row = conn.execute(
            f"SELECT "
            f"COUNT(*) AS total_runs, "
            f"SUM(CASE WHEN outcome = 'success' THEN 1 ELSE 0 END) AS success_count, "
            f"SUM(CASE WHEN human_decision = 'rejected' THEN 1 ELSE 0 END) AS rejected_count, "
            f"COALESCE(AVG(duration_s), 0) AS avg_duration_s, "
            f"COALESCE(SUM(total_tokens), 0) AS total_tokens, "
            f"COALESCE(SUM(denylist_hits), 0) AS total_denylist_hits, "
            f"COALESCE(SUM(escalations), 0) AS total_escalations, "
            f"COALESCE(AVG(items_found), 0) AS avg_items_found, "
            f"COALESCE(AVG(files_changed), 0) AS avg_files_changed, "
            f"COALESCE(AVG(iterations), 0) AS avg_iterations "
            f"FROM run_logs {filter_clause}",
            params,
        ).fetchone()
        d = dict(row)
        total = d["total_runs"] or 0
        success = d["success_count"] or 0
        rejected = d["rejected_count"] or 0
        human_decisions = success + rejected
        return {
            "total_runs": total,
            "success_rate": round(success / total, 3) if total > 0 else 0,
            "false_positive_rate": round(rejected / human_decisions, 3) if human_decisions > 0 else 0,
            "avg_duration_s": round(d["avg_duration_s"] or 0, 1),
            "total_tokens": d["total_tokens"] or 0,
            "total_denylist_hits": d["total_denylist_hits"] or 0,
            "total_escalations": d["total_escalations"] or 0,
            "avg_items_found": round(d["avg_items_found"] or 0, 1),
            "avg_files_changed": round(d["avg_files_changed"] or 0, 1),
            "avg_iterations": round(d["avg_iterations"] or 0, 1),
            "days": days,
        }
    finally:
        conn.close()


def get_daily_metrics(user_id: int, project_name: str = "", days: int = 7) -> list[dict]:
    """按日分组的指标。"""
    init_loop_db()
    conn = _get_db()
    try:
        if project_name:
            rows = conn.execute(
                "SELECT DATE(started_at) AS day, "
                "COUNT(*) AS runs, "
                "SUM(CASE WHEN outcome = 'success' THEN 1 ELSE 0 END) AS success_count, "
                "COALESCE(SUM(total_tokens), 0) AS tokens "
                "FROM run_logs WHERE user_id = ? AND project_name = ? "
                "AND started_at >= datetime('now', ?) "
                "GROUP BY day ORDER BY day DESC",
                (user_id, project_name, f"-{days} days"),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT DATE(started_at) AS day, "
                "COUNT(*) AS runs, "
                "SUM(CASE WHEN outcome = 'success' THEN 1 ELSE 0 END) AS success_count, "
                "COALESCE(SUM(total_tokens), 0) AS tokens "
                "FROM run_logs WHERE user_id = ? "
                "AND started_at >= datetime('now', ?) "
                "GROUP BY day ORDER BY day DESC",
                (user_id, f"-{days} days"),
            ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


# ── P1-5: Branch lock helpers ─────────────────────────────────

def get_branch_lock(project_dir: str, branch: str) -> Optional[dict]:
    """获取分支锁状态（基于 global_switches）。"""
    key = f"branch-lock:{os.path.basename(project_dir)}:{branch}"
    return get_global_switch(key)

def acquire_branch_lock(project_dir: str, branch: str, loop_id: int) -> bool:
    """尝试获取分支锁。已锁返回 False，否则写入并返回 True。"""
    key = f"branch-lock:{os.path.basename(project_dir)}:{branch}"
    existing = get_global_switch(key)
    if existing:
        return False
    set_global_switch(key, {"loop_id": loop_id, "locked_at": datetime.now().isoformat()})
    return True

def release_branch_lock(project_dir: str, branch: str):
    """释放分支锁。"""
    key = f"branch-lock:{os.path.basename(project_dir)}:{branch}"
    set_global_switch(key, None)
