"""语义缓存存储：get / put / stats / clear 与缓存条目管理。

- 缓存 Key: query 的 embedding
- 命中条件: cosine similarity > CACHE_THRESHOLD (默认 0.95)
- 存储: 内存字典（MVP），生产可换 Redis
- TTL: 1 小时（文档未更新时有效）
"""

import time
from typing import Optional
from .. import cache as _cache_module  # 延迟引用 encode，允许测试 monkeypatch cache.encode
from ._index import CacheIndex
from .similarity import find_similar


def encode(texts):
    """编码入口：委托给父包 cache.encode（可被测试替换）。"""
    return _cache_module.encode(texts)

# 缓存条目: {cache_key: {"answer": str, "sources": list, "timestamp": float, "query": str, "embedding": list}}
_cache: dict = {}

# C3: Faiss 向量索引（可选加速器，与 _cache 同步维护）
_index = CacheIndex()

CACHE_THRESHOLD = 0.95      # cosine similarity 命中阈值（C1: 改为自适应阈值后作为中长文本基准）
CACHE_TTL_SECONDS = 3600    # 1 小时
MAX_CACHE_SIZE = 500        # 最大缓存条目数

# 命中率统计（C4: 可观测性）
_hit_count = 0
_miss_count = 0
# 最近查询结果采样（趋势面板）: [{"ts": float, "hit": bool}, ...]，上限 100 条
HISTORY_MAX = 100
_history: list[dict] = []


def _adaptive_threshold(query: str) -> float:
    """C1: 根据 query 长度动态调整缓存命中阈值。

    参考 CodeFuse-ModelCache 的长/短文本差异化阈值设计：
    - 短查询（≤20 字）：放宽到 0.88（短文字面相似通常代表相同意图，0.95 太严）
    - 中查询（21-100 字）：保持 0.95（基准）
    - 长查询（>100 字）：收紧到 0.97（长文局部相似不一定是同一问题，避免误命中）
    """
    length = len(query or "")
    if length <= 20:
        return 0.88
    elif length <= 100:
        return 0.95
    else:
        return 0.97


def _find_similar(
    query_embedding: list[float], threshold: float = CACHE_THRESHOLD,
    namespace: Optional[str] = None,
) -> Optional[dict]:
    """在缓存中查找相似查询（阈值由调用方传入，兼容既有调用面）。

    C3: 优先用 Faiss 索引加速；索引不可用/维度不符时回退暴力搜索。
    namespace: 多租户缓存隔离——只匹配相同 namespace 的条目。
    """
    # C3: Faiss 索引加速路径（候选仍需 namespace 过滤）
    if _index.enabled:
        candidates = _index.search(query_embedding, top_k=10)
        if candidates:
            now = time.time()
            best_score = 0.0
            best_entry = None
            for key, score in candidates:
                entry = _cache.get(key)
                if entry is None or now - entry["timestamp"] > CACHE_TTL_SECONDS:
                    continue
                if entry.get("namespace") != namespace:
                    continue
                if score > best_score:
                    best_score = score
                    best_entry = entry
            if best_entry and best_score >= threshold:
                best_entry["cache_hit_score"] = round(best_score, 4)
                return best_entry
            return None

    # 回退：暴力搜索（同时清理过期条目）
    return find_similar(query_embedding, _cache, CACHE_TTL_SECONDS, threshold, namespace)


def get(query: str, temperature: float = 0.0, namespace: Optional[str] = None) -> Optional[dict]:
    """
    查询缓存。
    如果命中，返回 {"answer": ..., "sources": ..., "cache_hit": True, "cache_hit_score": ...}
    如果未命中，返回 None

    C1: 阈值按 query 长度自适应（_adaptive_threshold）。
    C2: temperature 联动缓存——高创造性请求按概率跳过缓存，避免返回过期结果。
    namespace: 多租户缓存隔离——只查询相同 namespace 的条目。
    """
    # C2: temperature 联动——高 temperature 降低缓存使用（参考 GPTCache）
    if temperature > 0.7:
        skip_prob = (temperature - 0.7) / 1.3  # 0.7→0, 2.0→1.0
        import random
        if random.random() < skip_prob:
            _increment_miss()
            return None

    # 生成 query embedding
    embeddings = encode([query])
    if not embeddings:
        return None

    query_embedding = embeddings[0]
    # C1: 自适应阈值
    threshold = _adaptive_threshold(query)
    hit = _find_similar(query_embedding, threshold, namespace)

    if hit:
        _increment_hit()
        _record_result(True)
        return {
            "answer": hit["answer"],
            "sources": hit["sources"],
            "model": "cache",
            "cache_hit": True,
            "cache_hit_score": hit.get("cache_hit_score", 0),
        }

    _increment_miss()
    _record_result(False)
    return None


def _increment_hit():
    global _hit_count
    _hit_count += 1


def _increment_miss():
    global _miss_count
    _miss_count += 1


def _record_result(hit: bool):
    """C4: 采样记录查询结果（供前端趋势面板）。"""
    global _history
    _history.append({"ts": time.time(), "hit": hit})
    if len(_history) > HISTORY_MAX:
        _history = _history[-HISTORY_MAX:]


def put(query: str, answer: str, sources: list, model: str, namespace: Optional[str] = None):
    """存入缓存。

    namespace: 多租户缓存隔离——同 key 不同 namespace 互不干扰。
    """
    # LRU: 超过最大大小时删除最早的
    if len(_cache) >= MAX_CACHE_SIZE:
        oldest_key = min(_cache, key=lambda k: _cache[k]["timestamp"])
        _index.remove(oldest_key)  # C3: 同步索引
        del _cache[oldest_key]

    embeddings = encode([query])
    if not embeddings:
        return

    cache_key = f"q_{hash((namespace, query))}"
    _cache[cache_key] = {
        "query": query,
        "answer": answer,
        "sources": sources,
        "model": model,
        "namespace": namespace,
        "embedding": embeddings[0],
        "timestamp": time.time(),
    }
    # C3: 同步写入 Faiss 索引
    _index.add(cache_key, embeddings[0])


def stats() -> dict:
    """缓存统计"""
    now = time.time()
    active = sum(1 for v in _cache.values() if now - v["timestamp"] <= CACHE_TTL_SECONDS)
    total = _hit_count + _miss_count
    return {
        "total_entries": len(_cache),
        "active_entries": active,
        "max_size": MAX_CACHE_SIZE,
        "ttl_seconds": CACHE_TTL_SECONDS,
        "threshold": CACHE_THRESHOLD,
        # C4: 命中率指标
        "hit_count": _hit_count,
        "miss_count": _miss_count,
        "hit_rate": round(_hit_count / max(total, 1), 4),
        # C3: 索引状态
        "index_enabled": _index.enabled,
        "index_ntotal": _index.ntotal,
        # C4: 趋势采样（最近 20 条，供前端迷你趋势条）
        "history": _history[-20:],
    }


def clear():
    """清空缓存"""
    global _hit_count, _miss_count, _history
    _cache.clear()
    _index.reset()  # C3: 同步清空索引
    _hit_count = 0
    _miss_count = 0
    _history = []


def purge_namespace(namespace: Optional[str] = None) -> int:
    """按 namespace 精确清除缓存条目，返回清除条数。

    namespace=None 时清空全部（等同于 clear()）。
    """
    if namespace is None:
        n = len(_cache)
        clear()
        return n
    keys = [k for k, v in _cache.items() if v.get("namespace") == namespace]
    for k in keys:
        _cache.pop(k, None)
        _index.remove(k)  # C3: 同步索引
    return len(keys)


def purge_user(user_id) -> int:
    """清除某用户的所有缓存条目，返回清除条数。

    知识库更新（上传/删除文档）后必须调用：否则用户会拿到"更新前"的旧答案，
    且因为是缓存命中，不会有任何报错或提示——属于静默错误。
    这里按 `{user_id}:` 前缀匹配而非精确 namespace，因为发布新版本后
    collection_name 会变化，精确匹配会漏掉旧命名空间下的陈旧条目。
    """
    prefix = f"{user_id}:"
    keys = [
        k for k, v in _cache.items()
        if str(v.get("namespace") or "").startswith(prefix)
    ]
    for k in keys:
        _cache.pop(k, None)
        _index.remove(k)
    return len(keys)
