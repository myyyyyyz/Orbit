"""cache/ — 语义缓存模块测试"""
import time

import app.cache as cache_mod
from app.cache import get, put, stats, clear, _find_similar, _cache
from app.embed import encode


def setup_function():
    clear()


def test_put_and_get_exact_hit():
    put("什么是向量数据库", "向量数据库是...", [{"source": "a.md"}], "gpt-4o-mini")
    hit = get("什么是向量数据库")
    assert hit is not None
    assert hit["answer"] == "向量数据库是..."
    assert hit["model"] == "cache"
    assert hit["cache_hit"] is True
    assert hit["cache_hit_score"] >= cache_mod.CACHE_THRESHOLD
    assert hit["sources"] == [{"source": "a.md"}]


def test_get_miss_for_unrelated_query():
    """相似度低于阈值不命中（构造正交向量，不依赖语义模型不确定性）"""
    _cache["k1"] = {
        "query": "q1", "answer": "a", "sources": [], "model": "m",
        "embedding": [1.0] + [0.0] * 383,
        "timestamp": time.time(),
    }
    orthogonal = [0.0, 1.0] + [0.0] * 382  # 与缓存条目正交 → 相似度 0
    assert _find_similar(orthogonal) is None


def test_get_empty_cache():
    assert get("任意问题") is None


def test_ttl_expiry(monkeypatch):
    """过期条目被清理且不命中"""
    put("过期问题", "旧答案", [], "model")
    key = next(iter(_cache))
    _cache[key]["timestamp"] = time.time() - cache_mod.CACHE_TTL_SECONDS - 10
    assert get("过期问题") is None
    assert len(_cache) == 0  # 过期条目已清理


def test_lru_eviction(monkeypatch):
    """超过 MAX_CACHE_SIZE 时淘汰最旧条目"""
    monkeypatch.setattr(cache_mod, "MAX_CACHE_SIZE", 3)
    for i in range(3):
        put(f"问题{i}", f"答案{i}", [], "model")
    # 最旧条目的时间戳往前拨，确保淘汰它
    oldest_key = min(_cache, key=lambda k: _cache[k]["timestamp"])
    _cache[oldest_key]["timestamp"] = time.time() - 100
    put("问题3", "答案3", [], "model")
    assert len(_cache) == 3
    queries = [v["query"] for v in _cache.values()]
    assert "问题3" in queries
    assert "问题0" not in queries  # 最旧的被淘汰


def test_find_similar_dimension_mismatch():
    """向量维度不一致的条目被跳过"""
    put("正常问题", "答案", [], "model")
    _cache["bad_entry"] = {
        "query": "坏条目", "answer": "x", "sources": [], "model": "m",
        "embedding": [0.1, 0.2],  # 维度不符
        "timestamp": time.time(),
    }
    emb = encode(["正常问题"])[0]
    hit = _find_similar(emb)
    assert hit is not None
    assert hit["query"] == "正常问题"


def test_stats():
    clear()
    s = stats()
    assert s["total_entries"] == 0
    assert s["max_size"] == cache_mod.MAX_CACHE_SIZE
    assert s["ttl_seconds"] == cache_mod.CACHE_TTL_SECONDS
    assert s["threshold"] == cache_mod.CACHE_THRESHOLD
    put("统计问题", "答案", [], "model")
    assert stats()["total_entries"] == 1
    assert stats()["active_entries"] == 1


def test_clear():
    put("待清空", "答案", [], "model")
    clear()
    assert len(_cache) == 0
    assert stats()["total_entries"] == 0
