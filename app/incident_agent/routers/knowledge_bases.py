"""Read-only knowledge-base proxy for the frontend dropdown.

Why a proxy instead of letting the browser call DevAtlas:

- the frontend is served from another origin (``127.0.0.1:5174``), so a direct
  call would require CORS on DevAtlas — a change to the other project;
- the token stays a pass-through. The Agent does not decode it, does not store
  it and does not re-sign it, and DevAtlas remains the only place that decides
  which knowledge bases a user may see;
- when DevAtlas is down the frontend gets the same normalized error shape as
  every other Agent endpoint instead of a raw CORS/browser failure.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from ..core.config import get_settings
from ..dependencies import get_access_token, get_current_user
from ..schemas.auth import UserPublic
from ..schemas.knowledge_base import KnowledgeBaseOption
from ..services.authorizer import (
    HttpKnowledgeBaseAuthorizer,
    KnowledgeBaseAuthorizationError,
)

router = APIRouter(prefix="/api/v1/knowledge-bases", tags=["knowledge-bases"])


@router.get("", response_model=list[KnowledgeBaseOption])
def list_knowledge_bases(
    current_user: UserPublic = Depends(get_current_user),
    access_token: str = Depends(get_access_token),
) -> list[KnowledgeBaseOption]:
    """Return the knowledge bases the authenticated user may analyse.

    ``current_user`` is required so a stale token fails here with the same
    ``401`` + ``WWW-Authenticate`` contract as the other routes, but it is not
    used for filtering: DevAtlas filters by the token's owner itself, so there is
    exactly one source of truth about ownership. This route never touches the
    Agent database — a user with no history can still pick a knowledge base.
    """

    settings = get_settings()
    catalog = HttpKnowledgeBaseAuthorizer(
        settings.devatlas_base_url,
        settings.devatlas_timeout_seconds,
    )

    try:
        return catalog.list_accessible(access_token=access_token)
    except KnowledgeBaseAuthorizationError as exc:
        raise HTTPException(
            status_code=exc.status_code,
            detail=exc.message,
            headers={"WWW-Authenticate": "Bearer"}
            if exc.status_code == status.HTTP_401_UNAUTHORIZED
            else None,
        ) from exc
    finally:
        catalog.close()
