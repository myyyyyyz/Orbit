"""api/logos.py — Logos 对话总结接口测试 /api/v1/knowledge/logos

目录口径（多租户后）：
- 匿名   → ``<DATA_DIR>/anon/memory/YYYY-MM-DD.md``
- 已登录 → ``<DATA_DIR>/tenants/{tenant}/users/{user}/memory/YYYY-MM-DD.md``
"""
import os
from datetime import datetime

from app.config import DATA_DIR


def _memory_dir(tenant_id: str = None, user_id: int = None) -> str:
    """与 app/multitenant/paths.user_memory_dir 保持一致的目录规则。"""
    if not tenant_id:
        return os.path.join(DATA_DIR, "anon", "memory")
    return os.path.join(DATA_DIR, "tenants", tenant_id, "users", str(user_id), "memory")


def _today() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def test_logos_writes_memory_file(client):
    r = client.post("/api/v1/knowledge/logos", json={"conversation": "用户：搭建知识库\n助手：已完成 RAG 流程"})
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "ok"
    assert data["summary_length"] > 0
    # 无 LLM_API_KEY（conftest 已清除）→ 无 LLM 分支
    memory_file = os.path.join(_memory_dir(), f"{_today()}.md")
    assert os.path.exists(memory_file)
    assert "orbit_test_" in memory_file  # 写入临时目录而非真实 data/
    content = open(memory_file, encoding="utf-8").read()
    assert "对话总结" in content
    assert "搭建知识库" in content


def test_logos_appends_second_conversation(client):
    conv = "用户：第二次对话\n助手：好的"
    client.post("/api/v1/knowledge/logos", json={"conversation": conv})
    r = client.post("/api/v1/knowledge/logos", json={"conversation": conv})
    assert r.status_code == 200
    content = open(os.path.join(_memory_dir(), f"{_today()}.md"), encoding="utf-8").read()
    assert "第 2 次对话" in content or "第 3 次对话" in content  # 取决于同日期已有记录数


def test_logos_isolates_per_user(client, auth_context):
    """登录用户的对话总结写入自己租户/自己的目录，不落进匿名目录。

    回归：此前所有用户（含匿名）都追加到同一个 memory/YYYY-MM-DD.md。
    """
    r = client.post(
        "/api/v1/knowledge/logos",
        json={"conversation": "用户：私有对话\n助手：已记录"},
        headers=auth_context["headers"],
    )
    assert r.status_code == 200

    scoped_file = os.path.join(
        _memory_dir(auth_context["tenant_id"], auth_context["user_id"]), f"{_today()}.md"
    )
    assert os.path.exists(scoped_file), "登录用户的总结应落在自己的目录"
    assert "私有对话" in open(scoped_file, encoding="utf-8").read()

    # 该内容不得出现在匿名目录里
    anon_file = os.path.join(_memory_dir(), f"{_today()}.md")
    if os.path.exists(anon_file):
        assert "私有对话" not in open(anon_file, encoding="utf-8").read()


def test_logos_isolated_between_tenants(client, auth_context):
    """不同租户的记忆目录必须物理分开（跨组织不可读）。"""
    import uuid
    from app.multitenant import register_user
    from app.middleware.auth import create_access_token

    other_name = "pytest_other_" + uuid.uuid4().hex[:8]
    other = register_user(other_name, "pytest_pass_123")
    other_headers = {
        "Authorization": "Bearer " + create_access_token(
            other_name, other["user_id"], other["tenant_id"],
            tenant_role=other.get("tenant_role"),
        )
    }

    marker = "跨租户标记_" + uuid.uuid4().hex[:8]
    r = client.post(
        "/api/v1/knowledge/logos",
        json={"conversation": f"用户：{marker}\n助手：已记录"},
        headers=auth_context["headers"],
    )
    assert r.status_code == 200

    mine = os.path.join(
        _memory_dir(auth_context["tenant_id"], auth_context["user_id"]), f"{_today()}.md"
    )
    assert marker in open(mine, encoding="utf-8").read()

    other_dir = _memory_dir(other["tenant_id"], other["user_id"])
    other_file = os.path.join(other_dir, f"{_today()}.md")
    if os.path.exists(other_file):
        assert marker not in open(other_file, encoding="utf-8").read()


def test_logos_empty_conversation(client):
    r = client.post("/api/v1/knowledge/logos", json={"conversation": "  "})
    assert r.status_code == 400
    assert "不能为空" in r.json()["detail"]


def test_logos_with_llm_mock(client, mock_llm, monkeypatch):
    """有 LLM_API_KEY 时用 LLM 生成总结"""
    monkeypatch.setenv("LLM_API_KEY", "sk-test")
    r = client.post("/api/v1/knowledge/logos", json={"conversation": "用户：总结这个\n助手：好"})
    assert r.status_code == 200
    assert mock_llm["requests"], "LLM 应被调用"
    content = open(os.path.join(_memory_dir(), f"{_today()}.md"), encoding="utf-8").read()
    assert "这是 Mock LLM 的回答" in content


def test_extract_key_points():
    """key_points 解析：正常 / 无标记 / 坏 JSON / 超长截断"""
    from app.api.logos import _extract_key_points, KEY_POINTS_MAX

    # 正常解析（忽略 Markdown 部分，只取 KEY_POINTS 行）
    text = "## 总结\n做了什么\n\nKEY_POINTS: [\"要点1\", \"要点2\", \"要点3\"]"
    assert _extract_key_points(text) == ["要点1", "要点2", "要点3"]

    # 无标记 → 空列表
    assert _extract_key_points("没有要点的总结") == []

    # 坏 JSON → 空列表（容错，不影响主功能）
    assert _extract_key_points("KEY_POINTS: [\"未闭合") == []

    # 空输入 → 空列表
    assert _extract_key_points("") == []

    # 超长列表截断
    long_text = 'KEY_POINTS: [' + ", ".join(f'"p{i}"' for i in range(30)) + "]"
    assert len(_extract_key_points(long_text)) == KEY_POINTS_MAX


def test_logos_saves_summary_with_auth(client, auth_context):
    """带认证调用 logos → 无 LLM 降级路径也落库 conversation_summary（key_points 为空）"""
    r = client.post(
        "/api/v1/knowledge/logos",
        json={"conversation": "用户：搭建知识库\n助手：已完成 RAG 流程"},
        headers=auth_context["headers"],
    )
    assert r.status_code == 200
    data = r.json()
    assert data["saved_to_memory_db"] is True
    assert data["key_points"] == []  # 无 LLM 分支 → 无 KEY_POINTS → 空列表

    from app.memory import get_recent_summaries
    recent = get_recent_summaries(auth_context["user_id"], limit=1)
    assert len(recent) == 1
    assert "对话总结" in recent[0]["summary"]
    assert recent[0]["key_points"] == []
