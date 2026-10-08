"""api/knowledge.py — 知识库核心接口测试 /api/v1/knowledge/*

鉴权与隔离口径（多租户改造后）：
- 读类（stats/search/context/ask）保留匿名：数据落在独立匿名沙箱，
  不会触达任何租户的 collection。
- 写类（upload/upload-text/delete）要求登录：此前匿名写入的是**全局共享**
  collection，任意未登录访客都能写入并删除他人内容。
- 写入由 ``scope`` 决定落「组织共享库」还是「个人私有库」；
  读取则两者都覆盖（组织共享 + 本人私有）。
"""
import uuid

from app.config import settings


def _source():
    return "pytest_api_" + uuid.uuid4().hex[:8] + ".md"


def _fresh_headers():
    """注册一个全新租户的用户，返回该用户的请求头（用于跨组织隔离验证）。"""
    from app.multitenant import register_user
    from app.middleware.auth import create_access_token

    username = "pytest_iso_" + uuid.uuid4().hex[:8]
    result = register_user(username, "pytest_pass_123")
    token = create_access_token(
        username, result["user_id"], result["tenant_id"],
        tenant_role=result.get("tenant_role"),
    )
    return {"Authorization": "Bearer " + token}, result["tenant_id"], result["user_id"]


def test_stats(client):
    r = client.get("/api/v1/knowledge/stats")
    assert r.status_code == 200
    data = r.json()
    assert "collection" in data
    assert "total_chunks" in data


def test_stats_authenticated_reports_shared_and_personal(client, auth_context):
    """已登录时统计同时给出组织共享库与个人私有库（两个不同的 collection）。"""
    r = client.get("/api/v1/knowledge/stats", headers=auth_context["headers"])
    assert r.status_code == 200
    data = r.json()
    assert data["tenant_id"] == auth_context["tenant_id"]
    assert data["shared"]["collection"] == auth_context["collections"]["shared"]
    assert data["personal"]["collection"] == auth_context["collections"]["personal"]
    assert data["shared"]["collection"] != data["personal"]["collection"]
    # 都不等于匿名沙箱与历史全局库
    for bucket in (data["shared"], data["personal"]):
        assert bucket["collection"] not in (settings.ANON_COLLECTION, settings.CHROMA_COLLECTION)


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


def test_anon_search_uses_isolated_sandbox(client, auth_context):
    """匿名检索只看到匿名沙箱：登录用户上传的内容对它不可见。"""
    source = _source()
    r = client.post(
        "/api/v1/knowledge/upload-text",
        params={"text": "登录用户私有的知识库内容", "source": source},
        headers=auth_context["headers"],
    )
    assert r.status_code == 200

    stats = client.get("/api/v1/knowledge/stats").json()
    anon_results = client.get("/api/v1/knowledge/search", params={"q": "私有知识库内容"}).json()["results"]
    assert all(item["metadata"]["source"] != source for item in anon_results)
    # 匿名沙箱既不是租户共享库，也不是历史全局库
    assert stats["collection"] == settings.ANON_COLLECTION
    assert stats["collection"] != settings.CHROMA_COLLECTION
    assert stats["collection"] != auth_context["collections"]["shared"]


def test_upload_text_success(client, auth_context):
    source = _source()
    r = client.post(
        f"/api/v1/knowledge/upload-text?source={source}",
        params={"text": "Orbit 支持知识库 RAG 检索功能"},
        headers=auth_context["headers"],
    )
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "ok"
    assert data["chunks"] >= 1
    assert data["user_scoped"] is True
    # 默认写入组织共享库
    assert data["scope"] == "shared"
    assert data["collection"] == auth_context["collections"]["shared"]


def test_upload_text_empty(client, auth_context):
    r = client.post("/api/v1/knowledge/upload-text", params={"text": "  "}, headers=auth_context["headers"])
    assert r.status_code == 400


def test_upload_file_markdown(client, auth_context):
    filename = _source()
    content = "# 上传测试\n\n这是通过 multipart 上传的 Markdown 文档内容。".encode()
    r = client.post(
        "/api/v1/knowledge/upload",
        files={"file": (filename, content, "text/markdown")},
        headers=auth_context["headers"],
    )
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "ok"
    assert data["file_type"] == "markdown"
    assert data["chunks"] >= 1


def test_upload_file_unsupported_type(client, auth_context):
    r = client.post(
        "/api/v1/knowledge/upload",
        files={"file": ("evil.exe", b"MZ", "application/octet-stream")},
        headers=auth_context["headers"],
    )
    assert r.status_code == 400
    assert "不支持的文件类型" in r.json()["detail"]


def test_search_json_format(client, auth_context):
    source = _source()
    client.post(
        "/api/v1/knowledge/upload-text",
        params={"text": "向量数据库支持高维向量的相似度检索", "source": source},
        headers=auth_context["headers"],
    )
    r = client.get("/api/v1/knowledge/search", params={"q": "向量相似度检索", "top_k": 3}, headers=auth_context["headers"])
    assert r.status_code == 200
    data = r.json()
    assert data["query"] == "向量相似度检索"
    assert len(data["results"]) >= 1
    assert data["results"][0]["metadata"]["source"] == source


def test_search_text_format(client, auth_context):
    source = _source()
    client.post(
        "/api/v1/knowledge/upload-text",
        params={"text": "搜索格式化输出专用测试文本", "source": source},
        headers=auth_context["headers"],
    )
    r = client.get(
        "/api/v1/knowledge/search", params={"q": "格式化输出", "format": "text"}, headers=auth_context["headers"]
    )
    assert r.status_code == 200
    assert "## 知识库检索结果" in r.json()["results"]


def test_context_endpoint(client, auth_context):
    source = _source()
    client.post(
        "/api/v1/knowledge/upload-text",
        params={"text": "上下文接口测试内容", "source": source},
        headers=auth_context["headers"],
    )
    r = client.get("/api/v1/knowledge/context", params={"q": "上下文接口"}, headers=auth_context["headers"])
    assert r.status_code == 200
    assert "context" in r.json()


def test_delete_source(client, auth_context):
    source = _source()
    client.post(
        "/api/v1/knowledge/upload-text",
        params={"text": "待删除的测试文档", "source": source},
        headers=auth_context["headers"],
    )
    r = client.delete("/api/v1/knowledge/source", params={"source": source}, headers=auth_context["headers"])
    assert r.status_code == 200
    # 删除后搜不到
    results = client.get(
        "/api/v1/knowledge/search", params={"q": "待删除的测试文档"}, headers=auth_context["headers"]
    ).json()["results"]
    assert all(item["metadata"]["source"] != source for item in results)


def test_upload_personal_scope_writes_to_personal_collection(client, auth_context):
    """scope=personal → 写入个人私有库；同组织同事也搜不到。"""
    source = _source()
    r = client.post(
        "/api/v1/knowledge/upload-text",
        params={"text": "我的个人私有草稿内容", "source": source, "scope": "personal"},
        headers=auth_context["headers"],
    )
    assert r.status_code == 200
    assert r.json()["scope"] == "personal"
    assert r.json()["collection"] == auth_context["collections"]["personal"]

    # 本人能搜到
    mine = client.get(
        "/api/v1/knowledge/search", params={"q": "个人私有草稿"}, headers=auth_context["headers"]
    ).json()["results"]
    assert any(item["metadata"]["source"] == source for item in mine)
    assert any(item["metadata"]["scope"] == "personal" for item in mine)


def test_cross_organization_isolation_via_api(client, auth_context):
    """跨组织隔离：A 组织上传的文档，B 组织检索不到。"""
    source = _source()
    client.post(
        "/api/v1/knowledge/upload-text",
        params={"text": "A 组织的机密项目代号：天枢", "source": source},
        headers=auth_context["headers"],
    )

    other_headers, _, _ = _fresh_headers()
    results = client.get(
        "/api/v1/knowledge/search", params={"q": "机密项目代号 天枢"}, headers=other_headers
    ).json()["results"]
    assert all(item["metadata"]["source"] != source for item in results)


def test_invalid_scope_falls_back_to_shared(client, auth_context):
    """非法 scope 不报错也不提权：归一化为组织共享库。"""
    source = _source()
    r = client.post(
        "/api/v1/knowledge/upload-text",
        params={"text": "非法 scope 测试内容", "source": source, "scope": "root"},
        headers=auth_context["headers"],
    )
    assert r.status_code == 200
    assert r.json()["scope"] == "shared"
    assert r.json()["collection"] == auth_context["collections"]["shared"]


def test_ask_empty_question(client):
    r = client.post("/api/v1/knowledge/ask", json={"question": "  "})
    assert r.status_code == 400


def test_ask_fallback_without_api_key(client, auth_context):
    """无 API key → 检索 fallback 答案（集成链路：upload → ask）"""
    source = _source()
    client.post(
        "/api/v1/knowledge/upload-text",
        params={
            "text": "Orbit 是一套 AI Agent 端到端系统，核心功能包括知识库 RAG 检索。",
            "source": source,
        },
        headers=auth_context["headers"],
    )
    question = "Orbit 的核心功能是什么？" + uuid.uuid4().hex[:6]  # 避免命中历史缓存
    r = client.post("/api/v1/knowledge/ask", json={"question": question}, headers=auth_context["headers"])
    assert r.status_code == 200
    data = r.json()
    assert "未配置 LLM_API_KEY" in data["answer"]
    assert data["model"] == "fallback (no LLM)"
    assert data["cache_hit"] is False
    assert data["retrieval_count"] >= 1
    assert any(s["source"] == source for s in data["sources"])


def test_ask_stream_sse(client, auth_context):
    """SSE 流式接口：事件格式 + 无 key fallback"""
    source = _source()
    client.post(
        "/api/v1/knowledge/upload-text",
        params={
            "text": "流式接口测试：Orbit 支持 SSE 流式问答输出。",
            "source": source,
        },
        headers=auth_context["headers"],
    )
    q = "Orbit 支持什么输出方式？" + uuid.uuid4().hex[:6]
    r = client.get("/api/v1/knowledge/ask/stream", params={"q": q}, headers=auth_context["headers"])
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


def test_upload_search_with_auth_user_scope(client, auth_context):
    """带 token 上传 → 写入租户隔离 collection，匿名沙箱不可见"""
    source = _source()
    r = client.post(
        "/api/v1/knowledge/upload-text",
        params={"text": "用户私有知识库内容", "source": source},
        headers=auth_context["headers"],
    )
    assert r.status_code == 200
    assert r.json()["user_scoped"] is True
    # 匿名（独立沙箱）搜不到该内容
    anon = client.get("/api/v1/knowledge/search", params={"q": "用户私有知识库内容"}).json()["results"]
    assert all(item["metadata"]["source"] != source for item in anon)


def test_scope_parameter_cannot_forge_tenant_identity(client, auth_context):
    """scope 只是"写到哪个空间"的选择器，不能用来越权访问别的租户。

    这里用一个**伪造的租户前缀**做 scope 值：它必须被归一化，
    并且写入仍然落在当前用户自己的组织共享库里。
    """
    other_headers, other_tenant_id, _ = _fresh_headers()
    source = _source()

    r = client.post(
        "/api/v1/knowledge/upload-text",
        params={"text": "伪造租户测试内容", "source": source, "scope": other_tenant_id},
        headers=auth_context["headers"],
    )
    assert r.status_code == 200
    assert r.json()["collection"] == auth_context["collections"]["shared"]

    # 目标租户依然搜不到
    results = client.get(
        "/api/v1/knowledge/search", params={"q": "伪造租户测试内容"}, headers=other_headers
    ).json()["results"]
    assert all(item["metadata"]["source"] != source for item in results)
