"""Incident analysis routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from ..dependencies import get_access_token, get_current_user
from ..schemas.auth import UserPublic
from ..schemas.incident import IncidentAnalyzeRequest


router = APIRouter(prefix="/api/v1/incidents", tags=["incidents"])


@router.post("/analyze", status_code=status.HTTP_501_NOT_IMPLEMENTED)
def analyze_incident(
    request: IncidentAnalyzeRequest,
    current_user: UserPublic = Depends(get_current_user),
    _access_token: str = Depends(get_access_token),
) -> None:
    """Reserve the analysis contract until the LangGraph phase is implemented."""

    del current_user
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="LangGraph Agent 尚未接入，分析接口将在阶段 3完成",
    )

