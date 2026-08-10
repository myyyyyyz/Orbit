import re
from pathlib import Path

from docx import Document
from docx.table import Table
from docx.text.paragraph import Paragraph

from app.chunk import chunk_text
from app.knowledge_agent.executors.base import ChunkDraft, build_chunks
from app.knowledge_agent.models import CorpusProfile, KnowledgeChunk


_HEADING_STYLE = re.compile(r"^Heading\s+([1-6])$", re.IGNORECASE)


class DocxLayoutAwareExecutor:
    strategy_id = "docx_layout_aware_v1"

    def execute(
        self, source: Path, *, profile: CorpusProfile, run_id: str
    ) -> tuple[KnowledgeChunk, ...]:
        document = Document(source)
        headings: list[str] = []
        drafts: list[ChunkDraft] = []
        block_number = 0
        shared_metadata: dict[str, str | int | float | bool] = {}
        if profile.image_count:
            shared_metadata["document_image_count"] = profile.image_count

        for block in document.iter_inner_content():
            block_number += 1
            if isinstance(block, Paragraph):
                text = block.text.strip()
                if not text:
                    continue
                style_name = block.style.name if block.style is not None else ""
                heading_match = _HEADING_STYLE.match(style_name)
                if heading_match:
                    level = int(heading_match.group(1))
                    headings[level - 1 :] = [text]
                    continue
                for part_number, part in enumerate(chunk_text(text)):
                    drafts.append(
                        ChunkDraft(
                            text=part["text"],
                            locator=f"block:{block_number}:paragraph:{part_number}",
                            heading_path=tuple(headings),
                            metadata={**shared_metadata, "block_type": "paragraph"},
                        )
                    )
                continue

            if isinstance(block, Table):
                for row_number, row in enumerate(block.rows, start=1):
                    cells = [cell.text.strip() for cell in row.cells]
                    if not any(cells):
                        continue
                    drafts.append(
                        ChunkDraft(
                            text=" | ".join(cells),
                            locator=f"block:{block_number}:table-row:{row_number}",
                            heading_path=tuple(headings),
                            metadata={
                                **shared_metadata,
                                "block_type": "table",
                                "row_number": row_number,
                            },
                        )
                    )

        return build_chunks(
            drafts,
            profile=profile,
            run_id=run_id,
            strategy_id=self.strategy_id,
        )
