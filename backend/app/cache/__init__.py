"""
语义缓存模块

对相同/高度相似的查询直接返回缓存结果，避免重复调 LLM。
实现拆分为：similarity（相似度计算）、storage（缓存存储），此处仅做导出。

注意：`encode` 在此显式导出——storage 通过 `from .. import cache` 访问
`cache.encode`，保证测试可 monkeypatch 整个缓存模块的编码器。
"""
from ..embed import encode
from .similarity import cosine_similarity, find_similar
from .storage import (
    _cache,
    CACHE_THRESHOLD,
    CACHE_TTL_SECONDS,
    MAX_CACHE_SIZE,
    _find_similar,
    get,
    put,
    stats,
    clear,
    purge_namespace,
    purge_user,
)

__all__ = [
    "encode",
    "cosine_similarity",
    "find_similar",
    "_cache",
    "CACHE_THRESHOLD",
    "CACHE_TTL_SECONDS",
    "MAX_CACHE_SIZE",
    "_find_similar",
    "get",
    "put",
    "stats",
    "clear",
    "purge_namespace",
    "purge_user",
]
