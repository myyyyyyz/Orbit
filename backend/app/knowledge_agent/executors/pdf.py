from pathlib import Path

from PyPDF2 import PdfReader

from app.chunk import chunk_text
from app.knowledge_agent.executors.base import (
    ChunkDraft,
    ExecutionBlocked,
    OcrAdapter,
    build_chunks,
)
from app.knowledge_agent.models import CorpusProfile, KnowledgeChunk


class PdfTextHierarchicalExecutor:
    strategy_id = "pdf_text_hierarchical_v1"

    def execute(
        self, source: Path, *, profile: CorpusProfile, run_id: str
    ) -> tuple[KnowledgeChunk, ...]:
        drafts: list[ChunkDraft] = []
        for page_number, page in enumerate(PdfReader(source).pages, start=1):
            text = page.extract_text() or ""
            for part_number, part in enumerate(chunk_text(text)):
                drafts.append(
                    ChunkDraft(
                        text=part["text"],
                        locator=f"page:{page_number}:part:{part_number}",
                        page=page_number,
                        metadata={"extraction_method": "pdf_text"},
                    )
                )
        chunks = build_chunks(
            drafts,
            profile=profile,
            run_id=run_id,
            strategy_id=self.strategy_id,
        )
        if not chunks:
            raise ExecutionBlocked("pdf_text_empty")
        return chunks


class PdfOcrReviewExecutor:
    strategy_id = "pdf_ocr_review_v1"

    def __init__(self, ocr: OcrAdapter):
        self.ocr = ocr

    def execute(
        self, source: Path, *, profile: CorpusProfile, run_id: str
    ) -> tuple[KnowledgeChunk, ...]:
        drafts: list[ChunkDraft] = []
        for page_number, text in enumerate(self.ocr.extract_pages(source), start=1):
            for part_number, part in enumerate(chunk_text(text)):
                drafts.append(
                    ChunkDraft(
                        text=part["text"],
                        locator=f"page:{page_number}:ocr:{part_number}",
                        page=page_number,
                        metadata={
                            "extraction_method": "ocr",
                            "requires_review": True,
                        },
                    )
                )
        chunks = build_chunks(
            drafts,
            profile=profile,
            run_id=run_id,
            strategy_id=self.strategy_id,
        )
        if not chunks:
            raise ExecutionBlocked("ocr_empty")
        return chunks
