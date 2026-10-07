"""api/strategy.py — RAG 策略接口测试 /api/v1/knowledge/strategy

鉴权口径（本次加固）：GET 需登录，PATCH 需 admin（改的是全局 RAG 策略）。
"""
import pytest

from app.config import settings


@pytest.fixture(autouse=True)
def _restore_strategy():
    """策略是全局单例，测试后恢复原值避免污染其他测试"""
    original_top_k = settings.rag.retrieval.top_k
    original_size = settings.rag.chunk.size
    original_version = settings.rag.version
    yield
    settings.rag.retrieval.top_k = original_top_k
    settings.rag.chunk.size = original_size
    settings.rag.version = original_version


def test_strategy_requires_auth(client, auth_headers):
    """回归：此前 GET/PATCH 均无任何认证依赖，匿名即可读改全局 RAG 策略。"""
    assert client.get("/api/v1/knowledge/strategy").status_code == 401
    assert client.patch("/api/v1/knowledge/strategy", json={"retrieval": {"top_k": 10}}).status_code == 401
    # 普通登录用户可以读，但不能改
    assert client.get("/api/v1/knowledge/strategy", headers=auth_headers).status_code == 200
    assert client.patch(
        "/api/v1/knowledge/strategy", json={"retrieval": {"top_k": 10}}, headers=auth_headers
    ).status_code == 403


def test_get_strategy_structure(client, auth_headers):
    r = client.get("/api/v1/knowledge/strategy", headers=auth_headers)
    assert r.status_code == 200
    data = r.json()
    for section in ("chunk", "embed", "storage", "retrieval"):
        assert section in data
    assert data["chunk"]["size"] == 500
    assert data["retrieval"]["top_k"] == 5
    # embed 段只读：embedding 是单一实现（ONNX + all-MiniLM-L6-v2）
    assert data["_readonly"] == ["version", "embed"]
    assert data["embed"]["backend"] == "onnx"
    assert "ollama_host" not in data["embed"]
    assert "version" in data


def test_patch_strategy_top_k(client, admin_headers):
    r = client.patch("/api/v1/knowledge/strategy", json={"retrieval": {"top_k": 10}}, headers=admin_headers)
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "ok"
    assert any(c["field"] == "retrieval.top_k" and c["after"] == 10 for c in data["changes"])
    assert settings.rag.retrieval.top_k == 10


def test_patch_strategy_bumps_version(client, auth_headers, admin_headers):
    before = client.get("/api/v1/knowledge/strategy", headers=auth_headers).json()["version"]
    r = client.patch("/api/v1/knowledge/strategy", json={"retrieval": {"top_k": 8}}, headers=admin_headers)
    assert r.json()["version"] != before


def test_patch_strategy_invalid_value(client, admin_headers):
    r = client.patch("/api/v1/knowledge/strategy", json={"retrieval": {"top_k": 999}}, headers=admin_headers)
    assert r.status_code == 400
    assert "策略更新失败" in r.json()["detail"]


def test_patch_strategy_chunk_size(client, admin_headers):
    r = client.patch("/api/v1/knowledge/strategy", json={"chunk": {"chunk_size": 800}}, headers=admin_headers)
    assert r.status_code == 200
    assert settings.rag.chunk.size == 800


def test_patch_strategy_ignores_unset_sections(client, admin_headers):
    """只传 retrieval 时 chunk 不变"""
    r = client.patch("/api/v1/knowledge/strategy", json={"retrieval": {"top_k": 6}}, headers=admin_headers)
    changed_fields = [c["field"] for c in r.json()["changes"]]
    assert changed_fields == ["retrieval.top_k"]


def test_patch_strategy_accepts_flat_payload(client, admin_headers):
    """前端 StrategyPanel 提交的是扁平对象，必须真正生效。

    回归：此前顶层字段被 pydantic 静默忽略 —— 接口返回 200 + changes=[]，
    用户看到"保存成功"，实际配置一字未改。
    """
    r = client.patch("/api/v1/knowledge/strategy", json={"chunk_size": 900, "top_k": 12}, headers=admin_headers)
    assert r.status_code == 200
    assert settings.rag.chunk.size == 900
    assert settings.rag.retrieval.top_k == 12
    changed = {c["field"] for c in r.json()["changes"]}
    assert changed == {"chunk.size", "retrieval.top_k"}


def test_patch_strategy_rejects_embed_change(client, admin_headers):
    """embedding 是单一实现，不接受运行时换模型（换模型必须重建向量库）。"""
    before = settings.rag.embed.model
    r = client.patch(
        "/api/v1/knowledge/strategy", json={"embed": {"embedding_model": "bge-m3"}}, headers=admin_headers
    )
    # embed 已从 Schema 移除 → 该字段被忽略，不产生任何变更
    assert r.status_code == 200
    assert r.json()["changes"] == []
    assert settings.rag.embed.model == before == "all-MiniLM-L6-v2"
