"""api/knowledge.py — 知识库核心接口测试 /api/v1/knowledge/*

鉴权口径（本次加固）：
- 读类（stats/search/context/ask）保留匿名：数据落在独立匿名沙箱，
  不会触达任何登录用户的 collection。
- 写类（upload/upload-text/delete）要求登录：此前匿名写入的是**全局共享**
  collection，任意未登录访客都能写入并删除他人内容。
"""
import uuid


def _source():
    return "pytest_api_" + uuid.uuid4().hex[:8] + ".md"


def test_stats(client):
    r = client.get("/api/v1/knowledge/stats")
    assert r.status_code == 200
    data = r.json()
    assert "collection" in data
    assert "total_chunks" in data


def test_supported_types(client):
    r = client.get("/api/v1/knowledge/supported-types")
    assert r.status_code == 200
    assert set(r.json()["types"]) == {".pdf", ".md", ".txt", ".markdown"}


def test_write_endpoints_require_login(client):
    """写类端点对匿名一律 401（回归：此前匿名写入全局共享 collection）。"""
    assert client.post("/api/v1/knowledge/upload-text", params={"text": "x"}).status_code == 401
    assert client.post(
        "/api/v1/knowledge/upload",
        files={"file": ("a.md", b"# hi", "text/markdown")},
    ).status_code == 401
    assert client.delete("/api/v1/knowledge/source", params={"source": "a.md"}).status_code == 401


def test_anon_search_uses_isolated_sandbox(client, auth_headers):
    """匿名检索只看到匿名沙箱：登录用户上传的内容对它不可见。"""
    source = _source()
    r = client.post(
        "/api/v1/knowledge/upload-text",
        params={"text": "登录用户私有的知识库内容", "source": source},
        headers=auth_headers,
    )
    assert r.status_code == 200

    stats = client.get("/api/v1/knowledge/stats").json()
    anon_results = client.get("/api/v1/knowledge/search", params={"q": "私有知识库内容"}).json()["results"]
    assert all(item["metadata"]["source"] != source for item in anon_results)
    # 匿名沙箱与登录用户库是两个不同的 collection
    assert stats["collection"] != "user_1"


def test_upload_text_success(client, auth_headers):
    source = _source()
    r = client.post(
        f"/api/v1/knowledge/upload-text?source={source}",
        params={"text": "Orbit 支持知识库 RAG 检索功能"},
        headers=auth_headers,
    )
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "ok"
    assert data["chunks"] >= 1
    assert data["user_scoped"] is True


def test_upload_text_empty(client, auth_headers):
    r = client.post("/api/v1/knowledge/upload-text", params={"text": "  "}, headers=auth_headers)
    assert r.status_code == 400


def test_upload_file_markdown(client, auth_headers):
    filename = _source()
    content = "# 上传测试\n\n这是通过 multipart 上传的 Markdown 文档内容。".encode()
    r = client.post(
        "/api/v1/knowledge/upload",
        files={"file": (filename, content, "text/markdown")},
        headers=auth_headers,
    )
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "ok"
    assert data["file_type"] == "markdown"
    assert data["chunks"] >= 1


def test_upload_file_unsupported_type(client, auth_headers):
    r = client.post(
        "/api/v1/knowledge/upload",
        files={"file": ("evil.exe", b"MZ", "application/octet-stream")},
        headers=auth_headers,
    )
    assert r.status_code == 400
    assert "不支持的文件类型" in r.json()["detail"]


def test_search_json_format(client, auth_headers):
    source = _source()
    client.post(
        "/api/v1/knowledge/upload-text",
        params={"text": "向量数据库支持高维向量的相似度检索", "source": source},
        headers=auth_headers,
    )
    r = client.get("/api/v1/knowledge/search", params={"q": "向量相似度检索", "top_k": 3}, headers=auth_headers)
    assert r.status_code == 200
    data = r.json()
    assert data["query"] == "向量相似度检索"
    assert len(data["results"]) >= 1
    assert data["results"][0]["metadata"]["source"] == source


def test_search_text_format(client, auth_headers):
    source = _source()
    client.post(
        "/api/v1/knowledge/upload-text",
        params={"text": "搜索格式化输出专用测试文本", "source": source},
        headers=auth_headers,
    )
    r = client.get(
        "/api/v1/knowledge/search", params={"q": "格式化输出", "format": "text"}, headers=auth_headers
    )
    assert r.status_code == 200
    assert "## 知识库检索结果" in r.json()["results"]


def test_context_endpoint(client, auth_headers):
    source = _source()
    client.post(
        "/api/v1/knowledge/upload-text",
        params={"text": "上下文接口测试内容", "source": source},
        headers=auth_headers,
    )
    r = client.get("/api/v1/knowledge/context", params={"q": "上下文接口"}, headers=auth_headers)
    assert r.status_code == 200
    assert "context" in r.json()


def test_delete_source(client, auth_headers):
    source = _source()
    client.post(
        "/api/v1/knowledge/upload-text",
        params={"text": "待删除的测试文档", "source": source},
        headers=auth_headers,
    )
    r = client.delete("/api/v1/knowledge/source", params={"source": source}, headers=auth_headers)
    assert r.status_code == 200
    # 删除后搜不到
    results = client.get(
        "/api/v1/knowledge/search", params={"q": "待删除的测试文档"}, headers=auth_headers
    ).json()["results"]
    assert all(item["metadata"]["source"] != source for item in results)


def test_ask_empty_question(client):
    r = client.post("/api/v1/knowledge/ask", json={"question": "  "})
    assert r.status_code == 400


def test_ask_fallback_without_api_key(client, auth_headers):
    """无 API key → 检索 fallback 答案（集成链路：upload → ask）"""
    source = _source()
    client.post(
        "/api/v1/knowledge/upload-text",
        params={
            "text": "Orbit 是一套 AI Agent 端到端系统，核心功能包括知识库 RAG 检索。",
            "source": source,
        },
        headers=auth_headers,
    )
    question = "Orbit 的核心功能是什么？" + uuid.uuid4().hex[:6]  # 避免命中历史缓存
    r = client.post("/api/v1/knowledge/ask", json={"question": question}, headers=auth_headers)
    assert r.status_code == 200
    data = r.json()
    assert "未配置 LLM_API_KEY" in data["answer"]
    assert data["model"] == "fallback (no LLM)"
    assert data["cache_hit"] is False
    assert data["retrieval_count"] >= 1
    assert any(s["source"] == source for s in data["sources"])


def test_ask_stream_sse(client, auth_headers):
    """SSE 流式接口：事件格式 + 无 key fallback"""
    source = _source()
    client.post(
        "/api/v1/knowledge/upload-text",
        params={
            "text": "流式接口测试：Orbit 支持 SSE 流式问答输出。",
            "source": source,
        },
        headers=auth_headers,
    )
    q = "Orbit 支持什么输出方式？" + uuid.uuid4().hex[:6]
    r = client.get("/api/v1/knowledge/ask/stream", params={"q": q}, headers=auth_headers)
    assert r.status_code == 200
    assert "text/event-stream" in r.headers["content-type"]
    body = r.text
    assert "event: status" in body
    assert "event: answer" in body
    assert "event: done" in body
    assert "未配置 LLM_API_KEY" in body


def test_ask_stream_chat_mode_no_relevant(client):
    """闲聊问题：阈值过滤后无相关结果 → '与知识库无关' 文案（Bug3 回归测试）"""
    r = client.get("/api/v1/knowledge/ask/stream", params={"q": "hello " + uuid.uuid4().hex[:6]})
    assert r.status_code == 200
    assert "与知识库无关" in r.text


def test_upload_search_with_auth_user_scope(client, auth_headers):
    """带 token 上传 → 写入用户隔离 collection，匿名沙箱不可见"""
    source = _source()
    r = client.post(
        "/api/v1/knowledge/upload-text",
        params={"text": "用户私有知识库内容", "source": source},
        headers=auth_headers,
    )
    assert r.status_code == 200
    assert r.json()["user_scoped"] is True
    # 匿名（独立沙箱）搜不到该内容
    anon = client.get("/api/v1/knowledge/search", params={"q": "用户私有知识库内容"}).json()["results"]
    assert all(item["metadata"]["source"] != source for item in anon)
