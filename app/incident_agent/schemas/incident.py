"""Incident input, evidence, report and public response contracts."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class IncidentAnalyzeRequest(BaseModel):
    """Request submitted by the Web UI or CLI."""

    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=200)
    content: str = Field(min_length=1, max_length=20_000)
    knowledge_base_id: int = Field(gt=0)
    # 未提供时由运行时 Settings.default_top_k 注入，避免配置与接口默认值脱节。
    top_k: int | None = Field(default=None, ge=1, le=10)


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


class UnverifiedEvidenceItem(BaseModel):
    """Evidence that could not be traced back to this run's observations.

    Kept for diagnosis and transparency: the caller can see what the model
    claimed and why it was dropped, instead of silently losing it.
    """

    model_config = ConfigDict(extra="forbid")

    source: str
    detail: str
    document_id: int | None = None
    version_id: int | None = None
    chunk_index: int | None = None


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
    # Filled by the server-side evidence check, never by the model: the report
    # prompt does not ask for it and ``extra="forbid"`` would reject it if it did.
    unverified_evidence: list[UnverifiedEvidenceItem] = Field(
        default_factory=list,
    )


class DegradedKnowledgeBaseSource(BaseModel):
    """One real knowledge-base source, used in a deterministic degraded summary."""

    model_config = ConfigDict(extra="forbid")

    document_id: int | None = None
    version_id: int | None = None
    version_number: int | None = None
    chunk_index: int | None = None
    filename: str | None = None


class DegradedLogSignal(BaseModel):
    """One signal the log tool really matched, with its location."""

    model_config = ConfigDict(extra="forbid")

    type: str
    matched_text: str
    line_number: int | None = None


class DegradedSummary(BaseModel):
    """Deterministic, model-free summary of a failed or degraded run.

    Built only from persisted observations so that a failure still tells the
    user what *was* established, instead of collapsing to a single error string.
    """

    model_config = ConfigDict(extra="forbid")

    reason: str
    text: str
    failed_tools: list[str] = Field(default_factory=list)
    successful_tools: list[str] = Field(default_factory=list)
    log_signals: list[DegradedLogSignal] = Field(default_factory=list)
    knowledge_base_sources: list[DegradedKnowledgeBaseSource] = Field(
        default_factory=list,
    )
    service_statuses: list[str] = Field(default_factory=list)
    suggestions: list[str] = Field(default_factory=list)


class RunResponse(BaseModel):
    """Public response returned by the Agent API."""

    run_id: str
    status: str
    report: IncidentReport | None = None
    observations: list[dict[str, Any]] = Field(default_factory=list)
    steps: list[dict[str, Any]] = Field(default_factory=list)
    error: str | None = None
    # Only present when the run did not end in a validated report.
    degraded_summary: DegradedSummary | None = None
    # True when a previous process died mid-run and a later startup reclaimed it.
    interrupted: bool = False
