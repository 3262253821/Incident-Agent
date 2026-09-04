"""Incident analysis routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..dependencies import get_access_token, get_current_user
from ..db.session import get_db
from ..schemas.auth import UserPublic
from ..schemas.incident import IncidentAnalyzeRequest, RunResponse
from ..services.incident import execute_incident


router = APIRouter(prefix="/api/v1/incidents", tags=["incidents"])


@router.post("/analyze", response_model=RunResponse)
def analyze_incident(
    request: IncidentAnalyzeRequest,
    current_user: UserPublic = Depends(get_current_user),
    access_token: str = Depends(get_access_token),
    db: Session = Depends(get_db),
) -> RunResponse:
    """Authenticate, execute the Agent graph and return its persisted result."""

    return execute_incident(
        db,
        user=current_user,
        request=request,
        access_token=access_token,
    )
