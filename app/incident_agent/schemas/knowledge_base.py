"""Validated response contract for the DevAtlas knowledge-base detail API."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class RagKnowledgeBase(BaseModel):
    """Subset of DevAtlas ``KnowledgeBasePublic`` used for the pre-flight check.

    Only ``id`` and ``name`` are needed: the check exists to prove that the
    requested knowledge base belongs to the authenticated user, and the name is
    only used for readable log context. Extra fields are ignored so DevAtlas can
    add fields without breaking the Agent.
    """

    model_config = ConfigDict(extra="ignore")

    id: int
    name: str
