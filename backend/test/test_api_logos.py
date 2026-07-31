"""api/logos.py — Logos 对话总结接口测试 /api/knowledge/logos"""
import os
from datetime import datetime

from app.config import settings


def _memory_dir():
    # 与 api/logos.py 一致：Path(settings.UPLOAD_DIR).parent / "memory"
    return os.path.join(os.path.dirname(settings.UPLOAD_DIR), "memory")


def test_logos_writes_memory_file(client):
    r = client.post("/api/knowledge/logos", json={"conversation": "用户：搭建知识库\n助手：已完成 RAG 流程"})
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "ok"
    assert data["summary_length"] > 0
    # 无 LLM_API_KEY（conftest 已清除）→ 无 LLM 分支
    today = datetime.now().strftime("%Y-%m-%d")
    memory_file = os.path.join(_memory_dir(), f"{today}.md")
    assert os.path.exists(memory_file)
    assert "orbit_test_" in memory_file  # 写入临时目录而非真实 data/
    content = open(memory_file, encoding="utf-8").read()
    assert "对话总结" in content
    assert "搭建知识库" in content


def test_logos_appends_second_conversation(client):
    conv = "用户：第二次对话\n助手：好的"
    client.post("/api/knowledge/logos", json={"conversation": conv})
    r = client.post("/api/knowledge/logos", json={"conversation": conv})
    assert r.status_code == 200
    today = datetime.now().strftime("%Y-%m-%d")
    content = open(os.path.join(_memory_dir(), f"{today}.md"), encoding="utf-8").read()
    assert "第 2 次对话" in content or "第 3 次对话" in content  # 取决于同日期已有记录数


def test_logos_empty_conversation(client):
    r = client.post("/api/knowledge/logos", json={"conversation": "  "})
    assert r.status_code == 400
    assert "不能为空" in r.json()["detail"]


def test_logos_with_llm_mock(client, mock_llm, monkeypatch):
    """有 LLM_API_KEY 时用 LLM 生成总结"""
    monkeypatch.setenv("LLM_API_KEY", "sk-test")
    r = client.post("/api/knowledge/logos", json={"conversation": "用户：总结这个\n助手：好"})
    assert r.status_code == 200
    assert mock_llm["requests"], "LLM 应被调用"
    today = datetime.now().strftime("%Y-%m-%d")
    content = open(os.path.join(_memory_dir(), f"{today}.md"), encoding="utf-8").read()
    assert "这是 Mock LLM 的回答" in content
