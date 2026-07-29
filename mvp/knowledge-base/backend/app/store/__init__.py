"""ChromaDB 存储模块"""

import chromadb
from chromadb.config import Settings as ChromaSettings
from ..config import settings
from ..embed import encode


_client = None


def get_client() -> chromadb.ClientAPI:
    global _client
    if _client is None:
        _client = chromadb.PersistentClient(
            path=settings.CHROMA_PERSIST_DIR,
            settings=ChromaSettings(anonymized_telemetry=False),
        )
    return _client


def get_collection() -> chromadb.Collection:
    client = get_client()
    return client.get_or_create_collection(
        name=settings.CHROMA_COLLECTION,
        metadata={"hnsw:space": "cosine"},
    )


def add_documents(documents: list[dict]) -> int:
    """
    批量添加文档到向量库。
    每个 document: {"text": str, "metadata": dict}
    返回添加的 chunk 数量
    """
    if not documents:
        return 0

    collection = get_collection()
    texts = [d["text"] for d in documents]
    metadatas = [d.get("metadata", {}) for d in documents]

    # 生成 embedding
    embeddings = encode(texts)

    # 生成 ID
    import uuid
    ids = [f"chunk_{uuid.uuid4().hex[:12]}" for _ in documents]

    collection.add(
        ids=ids,
        embeddings=embeddings,
        documents=texts,
        metadatas=metadatas,
    )

    return len(documents)


def delete_by_source(source: str):
    """删除指定来源的所有 chunks"""
    collection = get_collection()
    results = collection.get(where={"source": source})
    if results["ids"]:
        collection.delete(ids=results["ids"])


def get_stats() -> dict:
    """获取知识库统计信息"""
    collection = get_collection()
    return {
        "collection": settings.CHROMA_COLLECTION,
        "total_chunks": collection.count(),
        "persist_dir": settings.CHROMA_PERSIST_DIR,
    }
