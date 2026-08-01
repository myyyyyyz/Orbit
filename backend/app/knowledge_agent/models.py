from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


FileType = Literal["markdown", "text", "pdf", "docx", "xlsx", "unknown"]
DecisionSource = Literal["agent", "rule", "fallback"]
TableQuality = Literal["stable", "messy", "unknown"]


class CorpusProfile(BaseModel):
    """A deterministic, serializable description of one knowledge file."""

    model_config = ConfigDict(frozen=True)

    source_path: str
    source_hash: str
    file_type: FileType
    page_count: int = Field(default=0, ge=0)
    text_extraction_ratio: float = Field(default=1.0, ge=0.0, le=1.0)
    heading_count: int = Field(default=0, ge=0)
    table_count: int = Field(default=0, ge=0)
    image_count: int = Field(default=0, ge=0)
    sheet_count: int = Field(default=0, ge=0)
    merged_cell_count: int = Field(default=0, ge=0)
    blank_row_count: int = Field(default=0, ge=0)
    table_quality: TableQuality = "unknown"


class StrategyDecision(BaseModel):
    """A strategy selected by an Agent suggestion or deterministic fallback."""

    model_config = ConfigDict(frozen=True)

    strategy_id: str
    decision_source: DecisionSource
    confidence: float = Field(ge=0.0, le=1.0)
    reason: str = Field(min_length=1)
    requires_review: bool = False


class PlannedDocument(BaseModel):
    model_config = ConfigDict(frozen=True)

    profile: CorpusProfile
    decision: StrategyDecision


class FolderPlan(BaseModel):
    model_config = ConfigDict(frozen=True)

    run_id: str
    dry_run: Literal[True] = True
    vector_store_writes: Literal[0] = 0
    document_count: int = Field(ge=0)
    documents: tuple[PlannedDocument, ...]
