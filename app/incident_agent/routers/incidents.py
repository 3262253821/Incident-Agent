"""Incident analysis routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from ..core.config import get_settings
from ..db.session import get_db
from ..dependencies import get_access_token, get_current_user
from ..schemas.auth import UserPublic
from ..schemas.incident import IncidentAnalyzeRequest, RunResponse
from ..services.authorizer import (
    HttpKnowledgeBaseAuthorizer,
    KnowledgeBaseAuthorizationError,
)
from ..services.incident import KnowledgeBaseAccessError, execute_incident

router = APIRouter(prefix="/api/v1/incidents", tags=["incidents"])


@router.post("/analyze", response_model=RunResponse)
def analyze_incident(
    request: IncidentAnalyzeRequest,
    current_user: UserPublic = Depends(get_current_user),
    access_token: str = Depends(get_access_token),
    db: Session = Depends(get_db),
) -> RunResponse:
    """Authenticate, verify knowledge-base access, then execute the Agent."""

    settings = get_settings()
    authorizer = HttpKnowledgeBaseAuthorizer(
        settings.devatlas_base_url,
        settings.devatlas_timeout_seconds,
    )

    try:
        return execute_incident(
            db,
            user=current_user,
            request=request,
            access_token=access_token,
            knowledge_base_authorizer=authorizer,
        )
    except KnowledgeBaseAccessError as exc:
        raise HTTPException(
            status_code=exc.status_code,
            detail=exc.message,
            headers={"WWW-Authenticate": "Bearer"}
            if exc.status_code == status.HTTP_401_UNAUTHORIZED
            else None,
        ) from exc
    except KnowledgeBaseAuthorizationError as exc:
        # Defensive: normalizes any authorizer failure that escaped the service.
        raise HTTPException(
            status_code=exc.status_code,
            detail=exc.message,
        ) from exc
    finally:
        authorizer.close()
