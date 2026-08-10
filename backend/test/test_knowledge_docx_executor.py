from pathlib import Path

from app.knowledge_agent.executors.registry import build_executor_registry
from app.knowledge_agent.profiler import profile_file


FIXTURES = Path(__file__).resolve().parents[2] / "knowledge" / "fixtures"


def _execute(name: str):
    source = FIXTURES / name
    profile = profile_file(source, root=FIXTURES)
    chunks = build_executor_registry()["docx_layout_aware_v1"].execute(
        source, profile=profile, run_id="run-1"
    )
    return profile, chunks


def test_docx_executor_preserves_headings_and_tables():
    _, chunks = _execute("clean-handbook.docx")

    assert chunks
    assert any(chunk.heading_path for chunk in chunks)
    assert any(chunk.metadata.get("block_type") == "table" for chunk in chunks)
    assert all(chunk.source_path == "clean-handbook.docx" for chunk in chunks)


def test_docx_executor_handles_messy_content_and_records_image_count():
    profile, chunks = _execute("messy-notes.docx")

    assert chunks
    assert len({chunk.chunk_id for chunk in chunks}) == len(chunks)
    if profile.image_count:
        assert all(
            chunk.metadata.get("document_image_count") == profile.image_count
            for chunk in chunks
        )
