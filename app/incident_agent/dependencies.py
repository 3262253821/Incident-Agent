"""FastAPI dependencies shared by routers."""

from __future__ import annotations

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .core.config import get_settings
from .schemas.auth import UserPublic
from .services.auth import DevAtlasAuthClient, DevAtlasAuthError

bearer_scheme = HTTPBearer(auto_error=False)


def get_access_token(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> str:
    """Extract a Bearer token without putting it into Agent state or storage."""

    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="需要有效的 Bearer Token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return credentials.credentials


def get_current_user(access_token: str = Depends(get_access_token)) -> UserPublic:
    """Validate the token against DevAtlas and return only public user data."""

    settings = get_settings()
    try:
        with DevAtlasAuthClient(
            settings.devatlas_base_url,
            settings.devatlas_timeout_seconds,
        ) as client:
            return client.current_user(access_token)
    except DevAtlasAuthError as exc:
        raise HTTPException(
            status_code=exc.status_code,
            detail=exc.message,
            headers={"WWW-Authenticate": "Bearer"}
            if exc.status_code == status.HTTP_401_UNAUTHORIZED
            else None,
        ) from exc

