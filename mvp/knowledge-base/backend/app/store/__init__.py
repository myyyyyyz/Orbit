"""ChromaDB 存储模块（支持多租户 Collection 隔离）"""

import uuid
import threading
from typing import Optional

import chromadb
from chromadb.config import Settings as ChromaSettings
from ..config import settings
from ..embed import encode


_client = None
_client_lock = threading.Lock()


def get_client() -> chromadb.ClientAPI:
    """获取 ChromaDB 客户端（线程安全单例）"""
    global _client
    if _client is None:
        with _client_lock:
            if _client is None:
                _client = chromadb.PersistentClient(
                    path=settings.CHROMA_PERSIST_DIR,
                    settings=ChromaSettings(anonymized_telemetry=False),
                )
    return _client


def get_collection(user_id: Optional[int] = None) -> chromadb.Collection:
    """
    获取 Collection。

    - user_id=None: 全局默认 Collection（向后兼容）
    - user_id=1:   Collection "user_1"（多租户隔离）
    """
    client = get_client()
    collection_name = f"user_{user_id}" if user_id else settings.CHROMA_COLLECTION
    return client.get_or_create_collection(
        name=collection_name,
        metadata={"hnsw:space": "cosine"},
    )


def add_documents(documents: list[dict], user_id: Optional[int] = None) -> int:
    """
    批量添加文档到向量库。
    - documents: [{"text": str, "metadata": dict}, ...]
    - user_id: 可选，写入到专属 Collection
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
    collection_name = f"user_{user_id}" if user_id else settings.CHROMA_COLLECTION
    _invalidate_count_cache(collection_name)

    return len(documents)


def delete_by_source(source: str, user_id: Optional[int] = None):
    """删除指定来源的所有 chunks"""
    collection = get_collection(user_id)
    results = collection.get(where={"source": source})
    if results["ids"]:
        collection.delete(ids=results["ids"])

    # 失效 count 缓存（lazy import 避免循环依赖）
    from ..search import _invalidate_count_cache
    collection_name = f"user_{user_id}" if user_id else settings.CHROMA_COLLECTION
    _invalidate_count_cache(collection_name)


def get_stats(user_id: Optional[int] = None) -> dict:
    """获取知识库统计信息"""
    collection = get_collection(user_id)
    name = f"user_{user_id}" if user_id else settings.CHROMA_COLLECTION
    return {
        "collection": name,
        "total_chunks": collection.count(),
        "persist_dir": settings.CHROMA_PERSIST_DIR,
    }
