"""Incident input, evidence, report and public response contracts."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    computed_field,
    field_serializer,
)

# 列表接口只带足以识别一条失败的信息；完整错误文本留给详情接口。
ERROR_SUMMARY_MAX_LENGTH = 240


def iso_utc(value: datetime | None) -> str | None:
    """Serialise a stored naive-UTC datetime as ISO 8601 with an explicit offset.

    Timestamps are persisted as **naive UTC** (see ``models.agent_run.utc_now``),
    because neither MySQL ``DATETIME`` nor SQLite keeps the offset. Adding the
    ``+00:00`` designator is therefore an API-boundary job: without it the
    frontend would parse a UTC wall clock as local time.
    """

    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat()


def summarize_error(
    error: str | None,
    *,
    max_length: int = ERROR_SUMMARY_MAX_LENGTH,
) -> str | None:
    """Shorten a stored error so a history list stays small.

    ``AgentRun.error`` is a ``TEXT`` column: a graph failure can carry a provider
    message plus the elapsed-budget note. The list only needs enough to recognise
    the failure; the untruncated string stays available on the detail endpoint.
    """

    if error is None:
        return None
    text = error.strip()
    if len(text) <= max_length:
        return text
    return f"{text[: max_length - 1].rstrip()}…"


def elapsed_ms(
    started_at: datetime | None,
    completed_at: datetime | None,
    *,
    interrupted: bool = False,
) -> int | None:
    """Wall-clock duration of a finished run in milliseconds, else ``None``.

    Three cases return ``None`` on purpose:

    - the run has not finished (a ``running`` row has no ``completed_at``);
    - the run was reclaimed by a later startup: ``reclaim_stale_runs`` writes
      ``completed_at = 回收时刻``, so the subtraction would measure how long the
      process stayed dead, not how long the analysis took. Reporting that as
      "耗时" would be actively misleading, so an interrupted run reports no
      duration;
    - a clock that moved backwards yields ``None`` rather than a negative value.
    """

    if interrupted or started_at is None or completed_at is None:
        return None
    seconds = (completed_at - started_at).total_seconds()
    if seconds < 0:
        return None
    return int(round(seconds * 1000))


class IncidentAnalyzeRequest(BaseModel):
    """Request submitted by the Web UI or CLI.

    ``str_strip_whitespace`` exists because ``min_length=1`` alone accepts a
    title or log that is only spaces: the design requires "空标题/空内容 → 422"
    (§16.1), and a blank prompt would otherwise reach the model and the tools.
    Stripping happens before the length check, so ``"   "`` becomes ``""`` and is
    rejected. The frontend trims as well; this is the server-side guarantee.
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

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


class RunSummary(BaseModel):
    """Lightweight history row returned by ``GET /api/v1/runs``.

    The list endpoint must not carry full trajectories: the history drawer only
    renders identity, outcome and counts, while ``observations``/``report`` can be
    arbitrarily large JSON. ``GET /api/v1/runs/{run_id}`` still returns the full
    ``RunResponse`` payload, so opening a row costs one extra request by design.

    There is deliberately no ``has_report`` boolean: ``report`` and
    ``degraded_summary`` are JSON columns, and "no report" is stored either as SQL
    ``NULL`` or as the JSON literal ``null`` depending on the write path (verified
    on MySQL 8.0 with ``JSON_TYPE``). ``status`` already carries the outcome, and
    a boolean derived from ``IS NOT NULL`` would have been true for both.
    """

    run_id: str
    title: str
    status: str
    knowledge_base_id: int
    iteration: int
    max_iterations: int
    steps_count: int
    observations_count: int
    interrupted: bool = False
    error: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None

    @field_serializer("started_at", "completed_at", when_used="json")
    def _serialise_timestamps(self, value: datetime | None) -> str | None:
        return iso_utc(value)

    @computed_field
    @property
    def duration_ms(self) -> int | None:
        """Analysis duration, derived so both endpoints answer it identically."""

        return elapsed_ms(
            self.started_at,
            self.completed_at,
            interrupted=self.interrupted,
        )


class RunSummaryPage(BaseModel):
    """One page of history rows (P1-3-3).

    Cursor pagination instead of offset: rows are ordered by
    ``(started_at DESC, id DESC)`` and ``next_cursor`` carries the last row's key,
    so a run created while the user is reading page 1 cannot shift the window the
    way ``offset`` would (which repeats or skips rows).

    There is no ``total``: counting a growing table on every page costs a second
    scan, and the only question the UI asks is "is there more" —
    ``next_cursor is None`` answers exactly that.
    """

    items: list[RunSummary] = Field(default_factory=list)
    next_cursor: str | None = None


class RunResponse(BaseModel):
    """Public response returned by the Agent API."""

    run_id: str
    # 详情接口也要能回答「这是什么故障、什么时候跑的、花了多久」。
    title: str
    status: str
    started_at: datetime | None = None
    completed_at: datetime | None = None
    report: IncidentReport | None = None
    observations: list[dict[str, Any]] = Field(default_factory=list)
    steps: list[dict[str, Any]] = Field(default_factory=list)
    error: str | None = None
    # Only present when the run did not end in a validated report.
    degraded_summary: DegradedSummary | None = None
    # True when a previous process died mid-run and a later startup reclaimed it.
    interrupted: bool = False

    @field_serializer("started_at", "completed_at", when_used="json")
    def _serialise_timestamps(self, value: datetime | None) -> str | None:
        return iso_utc(value)

    @computed_field
    @property
    def duration_ms(self) -> int | None:
        """Analysis duration; ``None`` for a run that has not finished yet."""

        return elapsed_ms(
            self.started_at,
            self.completed_at,
            interrupted=self.interrupted,
        )
