"""
语义缓存模块

对相同/高度相似的查询直接返回缓存结果，避免重复调 LLM。
- 缓存 Key: query 的 embedding
- 命中条件: cosine similarity > CACHE_THRESHOLD (默认 0.95)
- 存储: 内存字典（MVP），生产可换 Redis
- TTL: 1 小时（文档未更新时有效）
"""

import time
from typing import Optional
from ..embed import encode

# 缓存条目: {cache_key: {"answer": str, "sources": list, "timestamp": float, "query": str, "embedding": list}}
_cache: dict = {}

CACHE_THRESHOLD = 0.95      # cosine similarity 命中阈值
CACHE_TTL_SECONDS = 3600    # 1 小时
MAX_CACHE_SIZE = 500        # 最大缓存条目数


def _find_similar(query_embedding: list[float]) -> Optional[dict]:
    """在缓存中查找相似查询"""
    now = time.time()

    # 清理过期条目
    expired_keys = [k for k, v in _cache.items() if now - v["timestamp"] > CACHE_TTL_SECONDS]
    for k in expired_keys:
        del _cache[k]

    # 暴力搜索（MVP，条目少时够用）
    best_score = 0.0
    best_entry = None

    for key, entry in _cache.items():
        if now - entry["timestamp"] > CACHE_TTL_SECONDS:
            continue

        # cosine similarity
        emb = entry["embedding"]
        if len(emb) != len(query_embedding):
            continue

        dot = sum(a * b for a, b in zip(query_embedding, emb))
        norm_a = sum(a * a for a in query_embedding) ** 0.5
        norm_b = sum(b * b for b in emb) ** 0.5

        if norm_a == 0 or norm_b == 0:
            continue

        score = dot / (norm_a * norm_b)

        if score > best_score:
            best_score = score
            best_entry = entry

    if best_score >= CACHE_THRESHOLD and best_entry:
        best_entry["cache_hit_score"] = round(best_score, 4)
        return best_entry

    return None


def get(query: str) -> Optional[dict]:
    """
    查询缓存。
    如果命中，返回 {"answer": ..., "sources": ..., "cache_hit": True, "cache_hit_score": ...}
    如果未命中，返回 None
    """
    # 生成 query embedding
    embeddings = encode([query])
    if not embeddings:
        return None

    query_embedding = embeddings[0]
    hit = _find_similar(query_embedding)

    if hit:
        return {
            "answer": hit["answer"],
            "sources": hit["sources"],
            "model": "cache",
            "cache_hit": True,
            "cache_hit_score": hit.get("cache_hit_score", 0),
        }

    return None


def put(query: str, answer: str, sources: list, model: str):
    """存入缓存"""
    # LRU: 超过最大大小时删除最早的
    if len(_cache) >= MAX_CACHE_SIZE:
        oldest_key = min(_cache, key=lambda k: _cache[k]["timestamp"])
        del _cache[oldest_key]

    embeddings = encode([query])
    if not embeddings:
        return

    cache_key = f"q_{hash(query)}"
    _cache[cache_key] = {
        "query": query,
        "answer": answer,
        "sources": sources,
        "model": model,
        "embedding": embeddings[0],
        "timestamp": time.time(),
    }


def stats() -> dict:
    """缓存统计"""
    now = time.time()
    active = sum(1 for v in _cache.values() if now - v["timestamp"] <= CACHE_TTL_SECONDS)
    return {
        "total_entries": len(_cache),
        "active_entries": active,
        "max_size": MAX_CACHE_SIZE,
        "ttl_seconds": CACHE_TTL_SECONDS,
        "threshold": CACHE_THRESHOLD,
    }


def clear():
    """清空缓存"""
    _cache.clear()
