from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


FileType = Literal["markdown", "text", "pdf", "docx", "xlsx", "unknown"]
DecisionSource = Literal["agent", "rule", "fallback"]
TableQuality = Literal["stable", "messy", "unknown"]
AgentStatus = Literal["success", "unavailable", "error"]
RunStatus = Literal[
    "planned",
    "review_required",
    "approved",
    "indexing",
    "evaluating",
    "promoted",
    "rejected",
    "failed",
    "rolled_back",
    "invalidated",
]


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


class AgentAttempt(BaseModel):
    """Sanitized metadata and optional suggestion from one Agent call."""

    model_config = ConfigDict(frozen=True)

    status: AgentStatus
    model: str
    duration_ms: int = Field(ge=0)
    suggestion: dict[str, Any] | None = None
    error_category: str | None = None


class PlannedDocument(BaseModel):
    model_config = ConfigDict(frozen=True)

    profile: CorpusProfile
    decision: StrategyDecision
    agent_attempt: AgentAttempt | None = None


class FolderPlan(BaseModel):
    model_config = ConfigDict(frozen=True)

    run_id: str
    folder_path: str
    status: RunStatus
    dry_run: Literal[True] = True
    vector_store_writes: Literal[0] = 0
    document_count: int = Field(ge=0)
    documents: tuple[PlannedDocument, ...]


class KnowledgeRunRecord(BaseModel):
    """A tenant-scoped persisted summary of one KnowledgeRun."""

    model_config = ConfigDict(frozen=True)

    run_id: str
    user_id: int | None = None
    folder_path: str
    status: RunStatus
    dry_run: bool
    vector_store_writes: int = Field(ge=0)
    document_count: int = Field(ge=0)
    created_at: str
    updated_at: str | None = None
    approved_at: str | None = None
