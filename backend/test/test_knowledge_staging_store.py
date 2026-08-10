import pytest

from app.knowledge_agent.models import KnowledgeChunk
from app.knowledge_agent.staging_store import (
    EmbeddingFailed,
    StagingStore,
    staging_collection_name,
)


class FakeCollection:
    def __init__(self):
        self.records = {}

    def upsert(self, *, ids, embeddings, documents, metadatas):
        for index, chunk_id in enumerate(ids):
            self.records[chunk_id] = {
                "embedding": embeddings[index],
                "document": documents[index],
                "metadata": metadatas[index],
            }

    def count(self):
        return len(self.records)


class FakeClient:
    def __init__(self):
        self.collections = {}

    def get_or_create_collection(self, *, name, metadata=None):
        return self.collections.setdefault(name, FakeCollection())

    def delete_collection(self, name):
        self.collections.pop(name, None)


def _chunks():
    common = {
        "run_id": "run-1",
        "source_path": "policy.md",
        "source_hash": "a" * 64,
        "strategy_id": "markdown_hierarchical_v1",
    }
    return tuple(
        KnowledgeChunk(
            chunk_id=f"kc_{index:040d}",
            text=f"knowledge {index}",
            chunk_index=index,
            heading_path=("Policy",),
            metadata={"requires_review": False},
            **common,
        )
        for index in range(2)
    )


def test_staging_collection_is_run_and_tenant_scoped():
    assert staging_collection_name("a" * 32, 7) != staging_collection_name("a" * 32, 8)
    assert staging_collection_name("a" * 32, 7) != staging_collection_name("b" * 32, 7)


def test_default_chroma_client_is_loaded_lazily():
    store = StagingStore(encoder=lambda texts: [[0.1]] * len(texts))

    assert store.client is None


def test_upsert_is_idempotent_and_metadata_is_scalar():
    client = FakeClient()
    chunks = _chunks()
    store = StagingStore(
        client=client,
        encoder=lambda texts: [[0.1, 0.2]] * len(texts),
    )

    assert store.upsert(chunks, user_id=7) == len(chunks)
    assert store.upsert(chunks, user_id=7) == len(chunks)
    assert store.count(run_id=chunks[0].run_id, user_id=7) == len(chunks)
    collection = client.collections[staging_collection_name("run-1", 7)]
    metadata = next(iter(collection.records.values()))["metadata"]
    assert metadata["heading_path"] == '["Policy"]'
    assert all(not isinstance(value, (dict, list, tuple)) for value in metadata.values())


def test_delete_removes_only_target_run_collection():
    client = FakeClient()
    store = StagingStore(client=client, encoder=lambda texts: [[0.1]] * len(texts))
    store.upsert(_chunks(), user_id=7)
    client.get_or_create_collection(name=staging_collection_name("other", 7))

    store.delete(run_id="run-1", user_id=7)

    assert staging_collection_name("run-1", 7) not in client.collections
    assert staging_collection_name("other", 7) in client.collections


def test_real_chroma_upsert_is_idempotent():
    chromadb = pytest.importorskip("chromadb")
    store = StagingStore(
        client=chromadb.EphemeralClient(),
        encoder=lambda texts: [[0.1, 0.2]] * len(texts),
    )
    chunks = _chunks()

    store.upsert(chunks, user_id=7)
    store.upsert(chunks, user_id=7)

    assert store.count(run_id="run-1", user_id=7) == len(chunks)


def test_encoder_failure_has_a_typed_sanitized_boundary():
    def fail_encoder(texts):
        raise RuntimeError("model host secret")

    store = StagingStore(client=FakeClient(), encoder=fail_encoder)

    with pytest.raises(EmbeddingFailed, match="embedding_error"):
        store.upsert(_chunks(), user_id=7)
