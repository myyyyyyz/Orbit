"""memory/ — 长期记忆模块测试（memory.db 已隔离到临时目录）"""
import random

from app.memory import (
    init_memory_db, save_user_profile, get_user_profile,
    save_project_context, get_latest_project,
    save_conversation_summary, get_recent_summaries, restore_context,
)


def _uid():
    return random.randint(100000, 999999)


def test_init_memory_db_idempotent():
    init_memory_db()
    init_memory_db()


def test_user_profile_create_and_get():
    uid = _uid()
    save_user_profile(uid, role="developer", preferences={"lang": "zh"}, common_skills=["python"], output_style="code_first")
    p = get_user_profile(uid)
    assert p["role"] == "developer"
    assert p["preferences"] == {"lang": "zh"}
    assert p["common_skills"] == ["python"]
    assert p["output_style"] == "code_first"
    assert p["user_id"] == uid


def test_user_profile_partial_update():
    """COALESCE 部分更新：只更新 role，其余字段保留"""
    uid = _uid()
    save_user_profile(uid, role="pm", preferences={"a": 1}, common_skills=["sage"], output_style="doc")
    save_user_profile(uid, role="manager")
    p = get_user_profile(uid)
    assert p["role"] == "manager"           # 已更新
    assert p["preferences"] == {"a": 1}     # 保留
    assert p["common_skills"] == ["sage"]   # 保留
    assert p["output_style"] == "doc"       # 保留


def test_user_profile_defaults():
    uid = _uid()
    save_user_profile(uid)
    p = get_user_profile(uid)
    assert p["preferences"] == {}
    assert p["common_skills"] == []
    assert p["output_style"] == "default"


def test_get_user_profile_nonexistent():
    assert get_user_profile(_uid()) is None


def _backdate(table, where_col, where_val, time_col, offset_seconds):
    """SQLite datetime('now') 为秒级精度，同秒插入排序不稳定；测试中将先插入的记录时间戳往前拨"""
    import app.memory as mem
    conn = mem._get_db()
    conn.execute(
        f"UPDATE {table} SET {time_col} = datetime('now', ?) WHERE {where_col} = ?",
        (f"-{offset_seconds} seconds", where_val),
    )
    conn.commit()
    conn.close()


def test_project_context_save_and_latest():
    uid = _uid()
    save_project_context(uid, "旧项目", tech_stack="Vue")
    _backdate("project_context", "project_name", "旧项目", "updated_at", 60)
    save_project_context(uid, "Orbit", tech_stack="FastAPI+Next.js", current_progress="80%", key_decisions=["选 ChromaDB", "用 SSE"])
    latest = get_latest_project(uid)
    assert latest["project_name"] == "Orbit"
    assert latest["tech_stack"] == "FastAPI+Next.js"
    assert latest["current_progress"] == "80%"
    assert latest["key_decisions"] == ["选 ChromaDB", "用 SSE"]


def test_get_latest_project_nonexistent():
    assert get_latest_project(_uid()) is None


def test_conversation_summaries_limit_and_order():
    uid = _uid()
    for i in range(7):
        save_conversation_summary(uid, f"摘要{i}", key_points=[f"要点{i}"])
        # 时间戳按序递增，避免秒级精度下同秒排序不稳定
        _backdate("conversation_summary", "summary", f"摘要{i}", "created_at", 60 - i * 5)
    recent = get_recent_summaries(uid, limit=5)
    assert len(recent) == 5
    assert recent[0]["summary"] == "摘要6"  # 最新在前
    assert recent[0]["key_points"] == ["要点6"]


def test_get_recent_summaries_empty():
    assert get_recent_summaries(_uid()) == []


def test_restore_context_empty():
    result = restore_context(_uid())
    assert result["has_context"] is False
    assert result["user_profile"] is None
    assert result["current_project"] is None
    assert result["recent_summaries"] == []
    assert "restored_at" in result


def test_restore_context_full():
    uid = _uid()
    save_user_profile(uid, role="developer")
    save_project_context(uid, "Orbit")
    save_conversation_summary(uid, "讨论了架构")
    result = restore_context(uid)
    assert result["has_context"] is True
    assert result["user_profile"]["role"] == "developer"
    assert result["current_project"]["project_name"] == "Orbit"
    assert len(result["recent_summaries"]) == 1
