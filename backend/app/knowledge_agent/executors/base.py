from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from app.knowledge_agent.chunk_ids import make_chunk_id
from app.knowledge_agent.models import CorpusProfile, KnowledgeChunk


class ExecutionBlocked(RuntimeError):
    """A known, sanitized condition that prevents strategy execution."""

    def __init__(self, category: str):
        super().__init__(category)
        self.category = category


class StrategyExecutor(Protocol):
    def execute(
        self, source: Path, *, profile: CorpusProfile, run_id: str
    ) -> tuple[KnowledgeChunk, ...]: ...


class OcrAdapter(Protocol):
    def extract_pages(self, source: Path) -> tuple[str, ...]: ...


class UnavailableOcrAdapter:
    def extract_pages(self, source: Path) -> tuple[str, ...]:
        raise ExecutionBlocked("ocr_unavailable")


@dataclass(frozen=True)
class ChunkDraft:
    text: str
    locator: str
    page: int | None = None
    sheet: str | None = None
    heading_path: tuple[str, ...] = ()
    metadata: dict[str, str | int | float | bool] = field(default_factory=dict)


def build_chunks(
    drafts: list[ChunkDraft],
    *,
    profile: CorpusProfile,
    run_id: str,
    strategy_id: str,
) -> tuple[KnowledgeChunk, ...]:
    """Build ordered chunks through the single deterministic-ID path."""

    chunks: list[KnowledgeChunk] = []
    for draft in drafts:
        text = draft.text.strip()
        if not text:
            continue
        chunk_index = len(chunks)
        chunks.append(
            KnowledgeChunk(
                chunk_id=make_chunk_id(
                    run_id=run_id,
                    source_hash=profile.source_hash,
                    strategy_id=strategy_id,
                    chunk_index=chunk_index,
                    locator=f"{profile.source_path}\0{draft.locator}",
                ),
                text=text,
                run_id=run_id,
                source_path=profile.source_path,
                source_hash=profile.source_hash,
                strategy_id=strategy_id,
                chunk_index=chunk_index,
                page=draft.page,
                sheet=draft.sheet,
                heading_path=draft.heading_path,
                metadata=draft.metadata,
            )
        )
    return tuple(chunks)
