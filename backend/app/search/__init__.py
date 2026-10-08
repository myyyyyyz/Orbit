"""搜索模块：向量检索 + 结果后处理（支持多租户 + Active Index 版本机制）

实现拆分为：core（检索核心 + count 缓存 + active index 解析）、
format（结果格式化），此处仅做导出。

注意：`get_active_index` / `get_collection_by_name` / `ActiveIndexVersion`
在此显式导出——core 通过 `from .. import search` 访问这些属性，
保证测试可 monkeypatch `search.get_active_index` 等。
"""
from ..embed import encode
from ..knowledge_agent.releases import ActiveIndexVersion, get_active_index
from ..store import get_collection_by_name
from .core import (
    _count_cache,
    _count_lock,
    _get_cached_count,
    _invalidate_count_cache,
    _knowledge_database_path,
    resolve_active_collection,
    resolve_active_version,
    resolve_scope,
    search,
)
from .format import search_formatted

__all__ = [
    "encode",
    "ActiveIndexVersion",
    "get_active_index",
    "get_collection_by_name",
    "_count_cache",
    "_count_lock",
    "_get_cached_count",
    "_invalidate_count_cache",
    "_knowledge_database_path",
    "resolve_active_collection",
    "resolve_active_version",
    "resolve_scope",
    "search",
    "search_formatted",
]
