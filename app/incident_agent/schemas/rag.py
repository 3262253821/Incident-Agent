"""Validated response contracts for the DevAtlas retrieval API."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


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

