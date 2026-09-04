"""Authentication proxy routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from ..core.config import get_settings
from ..dependencies import get_current_user
from ..schemas.auth import LoginRequest, TokenResponse, UserPublic
from ..services.auth import DevAtlasAuthClient, DevAtlasAuthError

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


@router.post("/login", response_model=TokenResponse)
def login(data: LoginRequest) -> TokenResponse:
    """Forward credentials to DevAtlas; Agent does not authenticate locally."""

    settings = get_settings()
    try:
        with DevAtlasAuthClient(
            settings.devatlas_base_url,
            settings.devatlas_timeout_seconds,
        ) as client:
            return client.login(data)
    except DevAtlasAuthError as exc:
        headers = (
            {"WWW-Authenticate": "Bearer"}
            if exc.status_code == status.HTTP_401_UNAUTHORIZED
            else None
        )
        raise HTTPException(
            status_code=exc.status_code,
            detail=exc.message,
            headers=headers,
        ) from exc


@router.get("/me", response_model=UserPublic)
def read_current_user(
    current_user: UserPublic = Depends(get_current_user),
) -> UserPublic:
    """Validate the current token through DevAtlas and return its user."""

    return current_user

