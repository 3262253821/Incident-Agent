"""Validated contracts for the DevAtlas knowledge-base API.

Two models with two different jobs:

- ``RagKnowledgeBase`` is what the Agent **accepts from** DevAtlas when it
  verifies ownership before a run starts;
- ``KnowledgeBaseOption`` is what the Agent **returns to** the browser for the
  knowledge-base dropdown.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class RagKnowledgeBase(BaseModel):
    """Subset of DevAtlas ``KnowledgeBasePublic`` used for the pre-flight check.

    ``id`` and ``name`` are needed to prove that the requested knowledge base
    belongs to the authenticated user and to give logs readable context;
    ``description`` is optional so the same model can carry the list response.
    Extra fields are ignored so DevAtlas can add fields without breaking the
    Agent.
    """

    model_config = ConfigDict(extra="ignore")

    id: int
    name: str
    description: str | None = None


class KnowledgeBaseOption(BaseModel):
    """One selectable knowledge base in the frontend dropdown.

    Deliberately **not** ``RagKnowledgeBase``: the upstream payload also carries
    ``owner_id`` / ``created_at`` / ``updated_at``, and the browser only needs
    the fields a user can recognise. Keeping a separate response model means a
    new DevAtlas field cannot leak into the Agent's public contract by accident.
    """

    id: int
    name: str
    description: str | None = None
