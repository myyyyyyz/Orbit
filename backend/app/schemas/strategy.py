"""RAG strategy configuration models."""
from typing import Optional
from pydantic import BaseModel, Field


class ChunkPatch(BaseModel):
    chunk_size: Optional[int] = Field(default=None, ge=50, le=5000)
    chunk_overlap: Optional[int] = Field(default=None, ge=0, le=500)


class EmbedPatch(BaseModel):
    embedding_model: Optional[str] = None


class StoragePatch(BaseModel):
    pass


class RetrievalPatch(BaseModel):
    top_k: Optional[int] = Field(default=None, ge=1, le=50)
    search_mode: Optional[str] = None
    rerank_enabled: Optional[bool] = None


class StrategyPatch(BaseModel):
    chunk: Optional[ChunkPatch] = None
    embed: Optional[EmbedPatch] = None
    storage: Optional[StoragePatch] = None
    retrieval: Optional[RetrievalPatch] = None


def _apply_section(target: object, patch: Optional[BaseModel]) -> None:
    """Apply non-None fields from a Pydantic patch to a target object via setattr."""
    if patch is None:
        return
    for field_name, value in patch.model_dump(exclude_none=True).items():
        setattr(target, field_name, value)
