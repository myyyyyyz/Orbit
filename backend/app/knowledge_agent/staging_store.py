import hashlib
import json
import re
from collections.abc import Callable, Sequence
from typing import Any

from app.knowledge_agent.models import KnowledgeChunk


class EmbeddingFailed(RuntimeError):
    """Sanitized boundary for encoder failures."""


class StorageFailed(RuntimeError):
    """Sanitized boundary for Chroma failures."""


def staging_collection_name(run_id: str, user_id: int | None) -> str:
    tenant = hashlib.sha256(str(user_id).encode("utf-8")).hexdigest()[:8]
    sanitized_run = re.sub(r"[^a-zA-Z0-9]", "", run_id)[:32]
    if not sanitized_run:
        sanitized_run = hashlib.sha256(run_id.encode("utf-8")).hexdigest()[:12]
    return f"kr_{tenant}_{sanitized_run}"


def _chunk_metadata(chunk: KnowledgeChunk) -> dict[str, str | int | float | bool]:
    metadata: dict[str, str | int | float | bool | None] = {
        **chunk.metadata,
        "run_id": chunk.run_id,
        "source_path": chunk.source_path,
        "source_hash": chunk.source_hash,
        "strategy_id": chunk.strategy_id,
        "chunk_index": chunk.chunk_index,
        "page": chunk.page,
        "sheet": chunk.sheet,
        "heading_path": json.dumps(chunk.heading_path, ensure_ascii=False),
    }
    return {key: value for key, value in metadata.items() if value is not None}


class StagingStore:
    """Run-scoped vector storage that is never visible as an active collection."""

    def __init__(
        self,
        *,
        client: Any | None = None,
        encoder: Callable[[list[str]], Sequence[Sequence[float]]] | None = None,
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

    def upsert(self, chunks: Sequence[KnowledgeChunk], *, user_id: int | None) -> int:
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

    def count(self, *, run_id: str, user_id: int | None) -> int:
        collection = self._get_client().get_or_create_collection(
            name=staging_collection_name(run_id, user_id),
            metadata={"hnsw:space": "cosine"},
        )
        return collection.count()

    def delete(self, *, run_id: str, user_id: int | None) -> None:
        self._get_client().delete_collection(staging_collection_name(run_id, user_id))
