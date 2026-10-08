"""检索核心：向量检索 + count 缓存 + Active Index 版本解析（多租户）。

读取语义（用户明确要求的产品行为）：
- 匿名访客 → 只读匿名沙箱
- 已登录   → **组织共享库** ∪ **本人私有库**，两路结果按相似度合并后取 top_k

写入是另一回事：由端点的 `scope` 参数决定落到共享库还是私有库
（见 `api/knowledge.py`），读取时不做这个区分。
"""

import logging
import threading
import time
from pathlib import Path
from typing import Optional

from ..config import settings
from .. import search as _search_module  # 延迟引用，允许测试 monkeypatch search.encode / get_active_index 等
from ..multitenant.context import get_current_scope, read_scopes

logger = logging.getLogger(__name__)

# count 缓存（避免每次搜索都调用 O(n) 的 collection.count()）
_count_cache: dict = {}  # {collection_name: {"value": int, "ts": float}}
_count_lock = threading.Lock()


def _knowledge_database_path() -> Path:
    """Knowledge Agent active indexes 依赖的 SQLite 数据库路径。"""
    database_url = settings.DATABASE_URL
    if not database_url.startswith("sqlite:///"):
        raise ValueError("Knowledge Agent active indexes require SQLite")
    return Path(database_url.removeprefix("sqlite:///"))


def resolve_scope(scope=None):
    """解析作用域；未传入时读取请求级租户上下文（fail-closed 到匿名沙箱）。"""
    return scope if scope is not None else get_current_scope()


def resolve_active_version(scope=None):
    """解析**单个作用域**的 active index 版本（未配置时回退到该作用域的默认 Collection）。"""
    resolved = resolve_scope(scope)
    return _search_module.get_active_index(
        scope=resolved, database_path=_search_module._knowledge_database_path()
    )


def resolve_active_collection(scope=None):
    """解析单个作用域 active index 版本对应的 Collection。"""
    resolved = resolve_scope(scope)
    version = resolve_active_version(resolved)
    return _search_module.get_collection_by_name(version.collection_name), version


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


def _search_one(scope, query_embedding, top_k: int, where: dict = None) -> list[dict]:
    """在单个作用域内做向量检索。

    where: ChromaDB 元数据精确过滤条件（结构化槽位走这条路，而非 embedding）。
    注意：Chroma 的 where 语义是「字段存在且相等」——摄取期未写入该字段的
    chunk 会直接被过滤掉，因此调用方需确保入库时确实写了对应字段
    （见 knowledge_agent/staging_store.py::_chunk_metadata）。
    """
    collection, version = resolve_active_collection(scope)
    name = version.collection_name

    if _get_cached_count(collection, name) == 0:
        return []

    query_kwargs = {
        "query_embeddings": [query_embedding],
        "n_results": min(top_k, collection.count()),
        "include": ["documents", "metadatas", "distances"],
    }
    if where:
        query_kwargs["where"] = where

    try:
        results = collection.query(**query_kwargs)
    except Exception:
        # 过滤字段在旧索引中不存在时降级为不过滤，绝不让检索整体失败
        logger.warning("vector_search_where_failed_fallback", exc_info=True)
        query_kwargs.pop("where", None)
        results = collection.query(**query_kwargs)

    if not results.get("ids") or not results["ids"][0]:
        return []

    documents = results.get("documents") or [[]]
    metadatas = results.get("metadatas") or [[]]
    distances = results.get("distances") or [[]]

    items = []
    for i in range(len(results["ids"][0])):
        distance = distances[0][i] if distances and distances[0] else 1.0
        metadata = metadatas[0][i] if metadatas and metadatas[0] and metadatas[0][i] else {}
        items.append({
            "text": documents[0][i] if documents and documents[0] else "",
            # 标注来源作用域：前端可据此区分"组织文档 / 我的私有文档"
            "metadata": {**metadata, "scope": scope.scope, "collection": name},
            "score": round(1.0 - distance, 4),  # cosine distance → similarity
        })
    return items


def search(query: str, top_k: int = None, scope=None, where: dict = None) -> list[dict]:
    """
    语义搜索知识库（跨"组织共享 + 个人私有"合并）。

    - scope=None:            取请求级租户上下文
    - scope=TenantScope(...): 显式指定；读取时仍会展开为共享∪私有
    - where:                 可选元数据精确过滤（结构化槽位），与向量检索叠加

    返回: [{"text": str, "metadata": dict, "score": float}, ...]
    """
    if top_k is None:
        top_k = settings.TOP_K
    if top_k < 1:
        return []

    resolved = resolve_scope(scope)
    scopes = read_scopes(resolved)

    # 查询向量化（延迟引用，允许测试 monkeypatch）
    query_embedding = _search_module.encode([query])[0]

    merged: list[dict] = []
    seen: set[str] = set()
    for one in scopes:
        for item in _search_one(one, query_embedding, top_k, where=where):
            text = item.get("text") or ""
            # 同一个 chunk 可能同时出现在两个空间（内容相同），按文本去重保留高分
            if text and text in seen:
                continue
            if text:
                seen.add(text)
            merged.append(item)

    # 按相似度降序
    merged.sort(key=lambda x: x.get("score", 0.0), reverse=True)
    return merged[:top_k]
