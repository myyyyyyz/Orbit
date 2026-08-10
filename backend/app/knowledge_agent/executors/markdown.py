import re
from pathlib import Path

from app.chunk import chunk_text
from app.knowledge_agent.executors.base import ChunkDraft, build_chunks
from app.knowledge_agent.models import CorpusProfile, KnowledgeChunk


_ATX_HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")


class MarkdownHierarchicalExecutor:
    strategy_id = "markdown_hierarchical_v1"

    def execute(
        self, source: Path, *, profile: CorpusProfile, run_id: str
    ) -> tuple[KnowledgeChunk, ...]:
        text = source.read_text(encoding="utf-8", errors="replace")
        drafts: list[ChunkDraft] = []
        headings: list[str] = []
        section_lines: list[str] = []
        section_path: tuple[str, ...] = ()

        def flush_section() -> None:
            section = "\n".join(section_lines).strip()
            if not section:
                return
            path_label = "/".join(section_path) or "root"
            for part_index, part in enumerate(chunk_text(section)):
                drafts.append(
                    ChunkDraft(
                        text=part["text"],
                        locator=f"heading:{path_label}:part:{part_index}",
                        heading_path=section_path,
                        metadata={"block_type": "section"},
                    )
                )

        for line in text.splitlines():
            match = _ATX_HEADING.match(line)
            if match is None:
                section_lines.append(line)
                continue

            flush_section()
            level = len(match.group(1))
            title = match.group(2).strip()
            headings[level - 1 :] = [title]
            section_path = tuple(headings)
            section_lines = [line]

        flush_section()
        return build_chunks(
            drafts,
            profile=profile,
            run_id=run_id,
            strategy_id=self.strategy_id,
        )
