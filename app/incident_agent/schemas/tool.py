"""Tool argument and unified tool-result contracts."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


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

