from app.knowledge_agent.executors.base import (
    OcrAdapter,
    StrategyExecutor,
    UnavailableOcrAdapter,
)
from app.knowledge_agent.executors.docx import DocxLayoutAwareExecutor
from app.knowledge_agent.executors.markdown import MarkdownHierarchicalExecutor
from app.knowledge_agent.executors.pdf import (
    PdfOcrReviewExecutor,
    PdfTextHierarchicalExecutor,
)
from app.knowledge_agent.executors.xlsx import SpreadsheetStructuredExecutor


def build_executor_registry(
    *, ocr: OcrAdapter | None = None
) -> dict[str, StrategyExecutor]:
    ocr_adapter = ocr or UnavailableOcrAdapter()
    return {
        "markdown_hierarchical_v1": MarkdownHierarchicalExecutor(),
        "docx_layout_aware_v1": DocxLayoutAwareExecutor(),
        "spreadsheet_structured_v1": SpreadsheetStructuredExecutor(),
        "pdf_text_hierarchical_v1": PdfTextHierarchicalExecutor(),
        "pdf_ocr_review_v1": PdfOcrReviewExecutor(ocr_adapter),
    }
