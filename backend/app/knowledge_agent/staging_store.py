import hashlib
import json
import re
from collections.abc import Callable, Sequence
from typing import Any, Optional, Union

from app.knowledge_agent.models import KnowledgeChunk
from app.knowledge_agent.evaluation_models import RetrievedChunk


class EmbeddingFailed(RuntimeError):
    """Sanitized boundary for encoder failures."""


class StorageFailed(RuntimeError):
    """Sanitized boundary for Chroma failures."""


def staging_collection_name(run_id: str, user_id: Optional[int]) -> str:
    tenant = hashlib.sha256(str(user_id).encode("utf-8")).hexdigest()[:8]
    sanitized_run = re.sub(r"[^a-zA-Z0-9]", "", run_id)[:32]
    if not sanitized_run:
        sanitized_run = hashlib.sha256(run_id.encode("utf-8")).hexdigest()[:12]
    return f"kr_{tenant}_{sanitized_run}"


def _derive_doc_type(source_path: str) -> str:
    """
    从 source_path 推导文档类型（用于 Chroma 元数据过滤）。

    ChromaDB 要求 metadata 值为非 None 的标量，所以这里必须给出确定的兜底值，
    不能返回 None（None 会在 upsert 时被过滤掉，字段缺失导致 where 过滤失效）。
    """
    if not source_path:
        return "unknown"
    name = source_path.replace("\\", "/").rsplit("/", 1)[-1]
    lowered = name.lower()
    # 关键词优先命中中文文档类型（比扩展名更贴近用户的"部署文档/接口文档"表达）
    for keyword, label in (
        ("部署", "部署文档"), ("接口", "接口文档"), ("api", "接口文档"),
        ("架构", "架构文档"), ("需求", "需求文档"), ("设计", "设计文档"),
        ("周报", "周报"), ("月报", "月报"), ("测试", "测试报告"),
        ("验收", "验收报告"), ("复盘", "复盘报告"), ("方案", "方案"),
    ):
        if keyword in lowered:
            return label
    ext = lowered.rsplit(".", 1)[-1] if "." in lowered else ""
    return f"file:{ext}" if ext else "unknown"


def _chunk_metadata(chunk: KnowledgeChunk) -> dict[str, Union[str, int, float, bool]]:
    metadata: dict[str, str | int | float | Optional[bool]] = {
        **chunk.metadata,
        "run_id": chunk.run_id,
        "source_path": chunk.source_path,
        "source_hash": chunk.source_hash,
        "strategy_id": chunk.strategy_id,
        "chunk_index": chunk.chunk_index,
        "page": chunk.page,
        "sheet": chunk.sheet,
        "heading_path": json.dumps(chunk.heading_path, ensure_ascii=False),
        # ── 业务维度元数据：为 where 精确过滤铺路（文档类型）──
        "doc_type": _derive_doc_type(chunk.source_path),
    }
    return {key: value for key, value in metadata.items() if value is not None}


class StagingStore:
    """Run-scoped vector storage that is never visible as an active collection."""

    def __init__(
        self,
        *,
        client: Optional[Any] = None,
        encoder: Optional[Callable[[list[str]], Sequence[Sequence[float]]]] = None,
    ):
        if encoder is None:
            from app.embed import encode

            encoder = encode
        self.client = client
        self.encoder = encoder

    def _get_client(self) -> Any:
        if self.client is None:
            from app.store import get_client

            self.client = get_client()
        return self.client

    def upsert(self, chunks: Sequence[KnowledgeChunk], *, user_id: Optional[int]) -> int:
        if not chunks:
            return 0
        run_ids = {chunk.run_id for chunk in chunks}
        if len(run_ids) != 1:
            raise ValueError("A staging upsert must contain exactly one run_id")

        try:
            collection = self._get_client().get_or_create_collection(
                name=staging_collection_name(chunks[0].run_id, user_id),
                metadata={"hnsw:space": "cosine"},
            )
        except Exception as exc:
            raise StorageFailed("storage_error") from exc
        texts = [chunk.text for chunk in chunks]
        try:
            embeddings = list(self.encoder(texts))
        except Exception as exc:
            raise EmbeddingFailed("embedding_error") from exc
        if len(embeddings) != len(chunks):
            raise EmbeddingFailed("embedding_error")
        try:
            collection.upsert(
                ids=[chunk.chunk_id for chunk in chunks],
                embeddings=embeddings,
                documents=texts,
                metadatas=[_chunk_metadata(chunk) for chunk in chunks],
            )
        except Exception as exc:
            raise StorageFailed("storage_error") from exc
        return len(chunks)

    def count(self, *, run_id: str, user_id: Optional[int]) -> int:
        collection = self._get_client().get_or_create_collection(
            name=staging_collection_name(run_id, user_id),
            metadata={"hnsw:space": "cosine"},
        )
        return collection.count()

    def delete(self, *, run_id: str, user_id: Optional[int]) -> None:
        self._get_client().delete_collection(staging_collection_name(run_id, user_id))

    def exists(self, *, run_id: str, user_id: Optional[int]) -> bool:
        return self.collection_exists(staging_collection_name(run_id, user_id))

    def collection_exists(self, collection_name: str) -> bool:
        """Check a server-resolved collection name without creating it."""

        try:
            names = {
                item if isinstance(item, str) else item.name
                for item in self._get_client().list_collections()
            }
        except Exception as exc:
            raise StorageFailed("storage_error") from exc
        return collection_name in names

    def query(
        self,
        *,
        run_id: str,
        user_id: Optional[int],
        question: str,
        top_k: int,
    ) -> tuple[RetrievedChunk, ...]:
        if top_k < 1:
            return ()
        try:
            collection = self._get_client().get_or_create_collection(
                name=staging_collection_name(run_id, user_id),
                metadata={"hnsw:space": "cosine"},
            )
            count = collection.count()
        except Exception as exc:
            raise StorageFailed("storage_error") from exc
        if count == 0:
            return ()
        try:
            query_embedding = list(self.encoder([question]))
        except Exception as exc:
            raise EmbeddingFailed("embedding_error") from exc
        if len(query_embedding) != 1:
            raise EmbeddingFailed("embedding_error")
        try:
            payload = collection.query(
                query_embeddings=query_embedding,
                n_results=min(top_k, count),
                include=["documents", "metadatas", "distances"],
            )
        except Exception as exc:
            raise StorageFailed("storage_error") from exc

        ids = payload.get("ids", [[]])[0]
        documents = payload.get("documents", [[]])[0]
        metadatas = payload.get("metadatas", [[]])[0]
        distances = payload.get("distances", [[]])[0]
        results: list[RetrievedChunk] = []
        for index, chunk_id in enumerate(ids):
            metadata = metadatas[index] if index < len(metadatas) else {}
            try:
                heading_path = tuple(json.loads(metadata.get("heading_path", "[]")))
            except (TypeError, ValueError, json.JSONDecodeError):
                heading_path = ()
            results.append(
                RetrievedChunk(
                    rank=index + 1,
                    distance=distances[index] if index < len(distances) else 1.0,
                    chunk_id=chunk_id,
                    text=documents[index] if index < len(documents) else "",
                    source_path=metadata.get("source_path", "unknown"),
                    heading_path=heading_path,
                    page=metadata.get("page"),
                    sheet=metadata.get("sheet"),
                    row_number=metadata.get("row_number"),
                    chunk_index=metadata.get("chunk_index", index),
                )
            )
        return tuple(results)
