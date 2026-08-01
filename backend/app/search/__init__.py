"""搜索模块：向量检索 + 结果后处理（支持多租户）"""

import time
import threading
from typing import Optional

from ..config import settings
from ..embed import encode
from ..store import get_collection

# count 缓存（避免每次搜索都调用 O(n) 的 collection.count()）
_count_cache: dict = {}  # {collection_name: {"value": int, "ts": float}}
_count_lock = threading.Lock()


def _get_cached_count(collection, name: str, ttl: float = 5.0) -> int:
    """获取缓存的 collection count，TTL 内复用"""
    now = time.time()
    with _count_lock:
        entry = _count_cache.get(name)
        if entry and (now - entry["ts"]) < ttl:
            return entry["value"]
    count = collection.count()
    with _count_lock:
        _count_cache[name] = {"value": count, "ts": now}
    return count


def _invalidate_count_cache(name: str = None):
    """失效 count 缓存（add/delete 后调用）"""
    with _count_lock:
        if name:
            _count_cache.pop(name, None)
        else:
            _count_cache.clear()


def search(query: str, top_k: int = None, user_id: Optional[int] = None) -> list[dict]:
    """
    语义搜索知识库。

    - user_id=None: 搜索全局 Collection
    - user_id=1:    搜索 Collection "user_1"

    返回: [{"text": str, "metadata": dict, "score": float}, ...]
    """
    if top_k is None:
        top_k = settings.TOP_K
    if top_k < 1:
        return []

    collection = get_collection(user_id)
    collection_name = f"user_{user_id}" if user_id else settings.CHROMA_COLLECTION

    if _get_cached_count(collection, collection_name) == 0:
        return []

    # 查询向量化
    query_embedding = encode([query])[0]

    # 语义检索
    results = collection.query(
        query_embeddings=[query_embedding],
        n_results=min(top_k, collection.count()),
        include=["documents", "metadatas", "distances"],
    )

    if not results["ids"] or not results["ids"][0]:
        return []

    items = []
    for i in range(len(results["ids"][0])):
        distance = results["distances"][0][i] if results["distances"] else 1.0
        score = 1.0 - distance  # cosine distance → similarity
        items.append({
            "text": results["documents"][0][i],
            "metadata": results["metadatas"][0][i] if results["metadatas"] else {},
            "score": round(score, 4),
        })

    # 按相似度降序
    items.sort(key=lambda x: x["score"], reverse=True)
    return items


def search_formatted(query: str, top_k: int = None, user_id: Optional[int] = None) -> str:
    """
    搜索并返回格式化文本，可直接注入 Agent 上下文。
    """
    items = search(query, top_k, user_id)
    if not items:
        return "（知识库中未找到相关内容）"

    lines = ["## 知识库检索结果\n"]
    for i, item in enumerate(items, 1):
        source = item["metadata"].get("source", "未知")
        lines.append(f"### 结果 {i}（相关度: {item['score']:.0%} | 来源: {source}）")
        lines.append(item["text"])
        lines.append("")

    return "\n".join(lines)
