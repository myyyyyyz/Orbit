from pathlib import Path

import pytest

from app.knowledge_agent.executors.base import ExecutionBlocked
from app.knowledge_agent.executors.registry import build_executor_registry
from app.knowledge_agent.profiler import profile_file


FIXTURES = Path(__file__).resolve().parents[2] / "knowledge" / "fixtures"


class StaticOcr:
    def extract_pages(self, source: Path) -> tuple[str, ...]:
        return ("扫描通知需要人工复核",)


def test_text_pdf_executor_preserves_page_number():
    source = FIXTURES / "text-report.pdf"
    profile = profile_file(source, root=FIXTURES)

    chunks = build_executor_registry()["pdf_text_hierarchical_v1"].execute(
        source, profile=profile, run_id="run-1"
    )

    assert any("ORB-2407" in chunk.text for chunk in chunks)
    assert all(chunk.page and chunk.page >= 1 for chunk in chunks)


def test_scanned_pdf_uses_injected_ocr_adapter():
    source = FIXTURES / "scanned-notice.pdf"
    profile = profile_file(source, root=FIXTURES)

    chunks = build_executor_registry(ocr=StaticOcr())["pdf_ocr_review_v1"].execute(
        source, profile=profile, run_id="run-1"
    )

    assert chunks[0].page == 1
    assert "人工复核" in chunks[0].text


def test_scanned_pdf_without_ocr_is_explicitly_blocked():
    source = FIXTURES / "scanned-notice.pdf"
    profile = profile_file(source, root=FIXTURES)

    with pytest.raises(ExecutionBlocked, match="ocr_unavailable"):
        build_executor_registry()["pdf_ocr_review_v1"].execute(
            source, profile=profile, run_id="run-1"
        )
