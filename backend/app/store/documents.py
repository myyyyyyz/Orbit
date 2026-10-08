"""文档操作：批量入库 / 按来源删除 / 统计（按 TenantScope 分区）"""

import uuid

from ..config import settings
from ..embed import encode
from .client import collection_name, get_collection, resolve_scope


def add_documents(documents: list[dict], scope=None) -> int:
    """
    批量添加文档到向量库。

    - documents: [{"text": str, "metadata": dict}, ...]
    - scope: TenantScope；不传时取请求级租户上下文（拿不到即匿名沙箱）
    返回添加的 chunk 数量
    """
    if not documents:
        return 0

    resolved = resolve_scope(scope)
    collection = get_collection(resolved)
    texts = [d["text"] for d in documents]
    metadatas = [d["metadata"] for d in documents]

    # 生成 embedding
    embeddings = encode(texts)

    # 生成 ID
    ids = [f"chunk_{uuid.uuid4().hex[:12]}" for _ in documents]

    collection.add(
        ids=ids,
        embeddings=embeddings,
        documents=texts,
        metadatas=metadatas,
    )

    # 失效 count 缓存（lazy import 避免循环依赖）
    from ..search import _invalidate_count_cache
    _invalidate_count_cache(resolved.collection)

    return len(documents)


def delete_by_source(source: str, scope=None) -> int:
    """删除指定来源的所有 chunks，返回删除数量。

    只作用于**当前作用域**对应的 Collection：组织共享文档在共享库里删、
    个人私有文档在私有库里删，不会误删到另一个空间。
    """
    resolved = resolve_scope(scope)
    collection = get_collection(resolved)
    results = collection.get(where={"source": source})
    ids = results.get("ids") or []
    if ids:
        collection.delete(ids=ids)

    # 失效 count 缓存（lazy import 避免循环依赖）
    from ..search import _invalidate_count_cache
    _invalidate_count_cache(resolved.collection)
    return len(ids)


def get_stats(scope=None) -> dict:
    """获取当前作用域知识库的统计信息。"""
    resolved = resolve_scope(scope)
    collection = get_collection(resolved)
    return {
        "collection": resolved.collection,
        "total_chunks": collection.count(),
        "persist_dir": settings.CHROMA_PERSIST_DIR,
        "tenant_id": resolved.tenant_id,
        "scope": resolved.scope,
    }
