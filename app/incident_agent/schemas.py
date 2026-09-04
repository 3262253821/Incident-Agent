"""Input, tool-result and final-report contracts for the MVP."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class IncidentAnalyzeRequest(BaseModel):
    """Request submitted by the Web UI or CLI."""

    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=200)
    content: str = Field(min_length=1, max_length=20_000)
    knowledge_base_id: int = Field(gt=0)
    top_k: int = Field(default=5, ge=1, le=10)


class AnalyzeLogArgs(BaseModel):
    """Arguments for the deterministic log-analysis tool."""

    model_config = ConfigDict(extra="forbid")

    log_text: str = Field(min_length=1, max_length=20_000)


class SearchKnowledgeArgs(BaseModel):
    """Arguments for the DevAtlas retrieval tool."""

    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=1, max_length=2_000)
    knowledge_base_id: int = Field(gt=0)
    top_k: int = Field(default=5, ge=1, le=10)


class GetServiceStatusArgs(BaseModel):
    """Arguments for the service-status tool."""

    model_config = ConfigDict(extra="forbid")

    service_name: str = Field(min_length=1, max_length=100)


class ToolResult(BaseModel):
    """Unified result returned by every Agent tool."""

    model_config = ConfigDict(extra="forbid")

    ok: bool
    data: dict[str, Any] = Field(default_factory=dict)
    error_code: str | None = None
    error: str | None = None


class EvidenceItem(BaseModel):
    """One evidence item in the final report."""

    model_config = ConfigDict(extra="forbid")

    source: Literal[
        "fault_log",
        "knowledge_base",
        "service_status",
        "tool_error",
    ]
    detail: str = Field(min_length=1)
    document_id: int | None = None
    version_id: int | None = None
    version_number: int | None = None
    chunk_index: int | None = None
    filename: str | None = None


class IncidentReport(BaseModel):
    """Validated final report produced by the report node."""

    model_config = ConfigDict(extra="forbid")

    summary: str = Field(min_length=1)
    category: Literal[
        "database",
        "network",
        "application",
        "dependency",
        "unknown",
    ]
    evidence: list[EvidenceItem] = Field(min_length=1)
    possible_causes: list[str] = Field(min_length=1)
    troubleshooting_steps: list[str] = Field(min_length=1)
    references: list[str] = Field(default_factory=list)
    confidence: Literal["low", "medium", "high"]


class RagSource(BaseModel):
    """Source metadata returned by DevAtlas search."""

    model_config = ConfigDict(extra="ignore")

    document_id: int
    version_id: int
    version_number: int
    chunk_index: int
    filename: str
    content: str
    distance: float
    page_number: int | None = None


class RagSearchResponse(BaseModel):
    """Validated response contract for DevAtlas /search."""

    model_config = ConfigDict(extra="ignore")

    question: str
    context: str
    sources: list[RagSource]


class RunResponse(BaseModel):
    """Public response returned by the Agent API."""

    run_id: str
    status: str
    report: IncidentReport | None = None
    observations: list[dict[str, Any]] = Field(default_factory=list)
    steps: list[dict[str, Any]] = Field(default_factory=list)
    error: str | None = None
