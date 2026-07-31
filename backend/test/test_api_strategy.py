"""api/strategy.py — RAG 策略接口测试 /api/knowledge/strategy"""
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


def test_get_strategy_structure(client):
    r = client.get("/api/knowledge/strategy")
    assert r.status_code == 200
    data = r.json()
    for section in ("chunk", "embed", "storage", "retrieval"):
        assert section in data
    assert data["chunk"]["size"] == 500
    assert data["retrieval"]["top_k"] == 5
    assert data["_readonly"] == ["version"]
    assert "version" in data


def test_patch_strategy_top_k(client):
    r = client.patch("/api/knowledge/strategy", json={"retrieval": {"top_k": 10}})
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "ok"
    assert any(c["field"] == "retrieval.top_k" and c["after"] == 10 for c in data["changes"])
    assert settings.rag.retrieval.top_k == 10


def test_patch_strategy_bumps_version(client):
    before = client.get("/api/knowledge/strategy").json()["version"]
    r = client.patch("/api/knowledge/strategy", json={"retrieval": {"top_k": 8}})
    assert r.json()["version"] != before


def test_patch_strategy_invalid_value(client):
    r = client.patch("/api/knowledge/strategy", json={"retrieval": {"top_k": 999}})
    assert r.status_code == 400
    assert "策略更新失败" in r.json()["detail"]


def test_patch_strategy_chunk_size(client):
    r = client.patch("/api/knowledge/strategy", json={"chunk": {"chunk_size": 800}})
    assert r.status_code == 200
    assert settings.rag.chunk.size == 800


def test_patch_strategy_ignores_unset_sections(client):
    """只传 retrieval 时 chunk 不变"""
    r = client.patch("/api/knowledge/strategy", json={"retrieval": {"top_k": 6}})
    changed_fields = [c["field"] for c in r.json()["changes"]]
    assert changed_fields == ["retrieval.top_k"]
