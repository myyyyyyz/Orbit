from pathlib import Path

from app.knowledge_agent.executors.registry import build_executor_registry
from app.knowledge_agent.profiler import profile_file


FIXTURES = Path(__file__).resolve().parents[2] / "knowledge" / "fixtures"


def _execute(name: str):
    source = FIXTURES / name
    profile = profile_file(source, root=FIXTURES)
    chunks = build_executor_registry()["spreadsheet_structured_v1"].execute(
        source, profile=profile, run_id="run-1"
    )
    return chunks


def test_xlsx_executor_creates_sheet_scoped_row_chunks():
    chunks = _execute("clean-projects.xlsx")

    assert chunks
    assert {chunk.sheet for chunk in chunks} == {"Projects"}
    assert any("ORB-2407" in chunk.text for chunk in chunks)
    assert all(chunk.metadata["row_number"] >= 1 for chunk in chunks)


def test_xlsx_executor_handles_messy_multiple_sheets_without_empty_chunks():
    chunks = _execute("messy-operations.xlsx")

    assert chunks
    assert len({chunk.sheet for chunk in chunks}) > 1
    assert all(chunk.text.strip() for chunk in chunks)
    assert len({chunk.chunk_id for chunk in chunks}) == len(chunks)
