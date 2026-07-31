"""api/knowledge.py — 知识库核心接口测试 /api/knowledge/*"""
import uuid


def _source():
    return "pytest_api_" + uuid.uuid4().hex[:8] + ".md"


def test_stats(client):
    r = client.get("/api/knowledge/stats")
    assert r.status_code == 200
    data = r.json()
    assert "collection" in data
    assert "total_chunks" in data


def test_supported_types(client):
    r = client.get("/api/knowledge/supported-types")
    assert r.status_code == 200
    assert set(r.json()["types"]) == {".pdf", ".md", ".txt", ".markdown"}


def test_upload_text_success(client):
    source = _source()
    r = client.post(f"/api/knowledge/upload-text?source={source}", params={"text": "Orbit 支持知识库 RAG 检索功能"})
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "ok"
    assert data["chunks"] >= 1
    assert data["user_scoped"] is False


def test_upload_text_empty(client):
    r = client.post("/api/knowledge/upload-text", params={"text": "  "})
    assert r.status_code == 400


def test_upload_file_markdown(client):
    filename = _source()
    content = "# 上传测试\n\n这是通过 multipart 上传的 Markdown 文档内容。".encode()
    r = client.post("/api/knowledge/upload", files={"file": (filename, content, "text/markdown")})
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "ok"
    assert data["file_type"] == "markdown"
    assert data["chunks"] >= 1


def test_upload_file_unsupported_type(client):
    r = client.post("/api/knowledge/upload", files={"file": ("evil.exe", b"MZ", "application/octet-stream")})
    assert r.status_code == 400
    assert "不支持的文件类型" in r.json()["detail"]


def test_search_json_format(client):
    source = _source()
    client.post("/api/knowledge/upload-text", params={"text": "向量数据库支持高维向量的相似度检索", "source": source})
    r = client.get("/api/knowledge/search", params={"q": "向量相似度检索", "top_k": 3})
    assert r.status_code == 200
    data = r.json()
    assert data["query"] == "向量相似度检索"
    assert len(data["results"]) >= 1
    assert data["results"][0]["metadata"]["source"] == source


def test_search_text_format(client):
    source = _source()
    client.post("/api/knowledge/upload-text", params={"text": "搜索格式化输出专用测试文本", "source": source})
    r = client.get("/api/knowledge/search", params={"q": "格式化输出", "format": "text"})
    assert r.status_code == 200
    assert "## 知识库检索结果" in r.json()["results"]


def test_context_endpoint(client):
    source = _source()
    client.post("/api/knowledge/upload-text", params={"text": "上下文接口测试内容", "source": source})
    r = client.get("/api/knowledge/context", params={"q": "上下文接口"})
    assert r.status_code == 200
    assert "context" in r.json()


def test_delete_source(client):
    source = _source()
    client.post("/api/knowledge/upload-text", params={"text": "待删除的测试文档", "source": source})
    r = client.delete("/api/knowledge/source", params={"source": source})
    assert r.status_code == 200
    # 删除后搜不到
    results = client.get("/api/knowledge/search", params={"q": "待删除的测试文档"}).json()["results"]
    assert all(item["metadata"]["source"] != source for item in results)


def test_ask_empty_question(client):
    r = client.post("/api/knowledge/ask", json={"question": "  "})
    assert r.status_code == 400


def test_ask_fallback_without_api_key(client):
    """无 API key → 检索 fallback 答案（集成链路：upload → ask）"""
    source = _source()
    client.post("/api/knowledge/upload-text", params={
        "text": "Orbit 是一套 AI Agent 端到端系统，核心功能包括知识库 RAG 检索。",
        "source": source,
    })
    question = "Orbit 的核心功能是什么？" + uuid.uuid4().hex[:6]  # 避免命中历史缓存
    r = client.post("/api/knowledge/ask", json={"question": question})
    assert r.status_code == 200
    data = r.json()
    assert "未配置 LLM_API_KEY" in data["answer"]
    assert data["model"] == "fallback (no LLM)"
    assert data["cache_hit"] is False
    assert data["retrieval_count"] >= 1
    assert any(s["source"] == source for s in data["sources"])


def test_ask_stream_sse(client):
    """SSE 流式接口：事件格式 + 无 key fallback"""
    source = _source()
    client.post("/api/knowledge/upload-text", params={
        "text": "流式接口测试：Orbit 支持 SSE 流式问答输出。",
        "source": source,
    })
    q = "Orbit 支持什么输出方式？" + uuid.uuid4().hex[:6]
    r = client.get("/api/knowledge/ask/stream", params={"q": q})
    assert r.status_code == 200
    assert "text/event-stream" in r.headers["content-type"]
    body = r.text
    assert "event: status" in body
    assert "event: answer" in body
    assert "event: done" in body
    assert "未配置 LLM_API_KEY" in body


def test_ask_stream_chat_mode_no_relevant(client):
    """闲聊问题：阈值过滤后无相关结果 → '与知识库无关' 文案（Bug3 回归测试）"""
    r = client.get("/api/knowledge/ask/stream", params={"q": "hello " + uuid.uuid4().hex[:6]})
    assert r.status_code == 200
    assert "与知识库无关" in r.text


def test_upload_search_with_auth_user_scope(client, auth_headers):
    """带 token 上传 → 写入用户隔离 collection"""
    source = _source()
    r = client.post("/api/knowledge/upload-text", params={"text": "用户私有知识库内容", "source": source}, headers=auth_headers)
    assert r.status_code == 200
    assert r.json()["user_scoped"] is True
    # 匿名全局库搜不到该内容
    anon = client.get("/api/knowledge/search", params={"q": "用户私有知识库内容"}).json()["results"]
    assert all(item["metadata"]["source"] != source for item in anon)
