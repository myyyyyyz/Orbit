"""文档操作：批量入库 / 按来源删除 / 统计"""

import uuid
from typing import Optional

from ..config import settings
from ..embed import encode
from .client import collection_name, get_collection


def add_documents(documents: list[dict], user_id: Optional[int] = None) -> int:
    """
    批量添加文档到向量库。
    - documents: [{"text": str, "metadata": dict}, ...]
    - user_id: 可选，写入到专属 Collection；为 None 时写入匿名沙箱（非全局库）
    返回添加的 chunk 数量
    """
    if not documents:
        return 0

    collection = get_collection(user_id)
    texts = [d["text"] for d in documents]
    metadatas = [d.get("metadata", {}) for d in documents]

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
    _invalidate_count_cache(collection_name(user_id))

    return len(documents)


def delete_by_source(source: str, user_id: Optional[int] = None):
    """删除指定来源的所有 chunks"""
    collection = get_collection(user_id)
    results = collection.get(where={"source": source})
    if results["ids"]:
        collection.delete(ids=results["ids"])

    # 失效 count 缓存（lazy import 避免循环依赖）
    from ..search import _invalidate_count_cache
    _invalidate_count_cache(collection_name(user_id))


def get_stats(user_id: Optional[int] = None) -> dict:
    """获取知识库统计信息"""
    collection = get_collection(user_id)
    return {
        "collection": collection_name(user_id),
        "total_chunks": collection.count(),
        "persist_dir": settings.CHROMA_PERSIST_DIR,
    }
