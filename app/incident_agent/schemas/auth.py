"""Authentication contracts exchanged with DevAtlas."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict


class LoginRequest(BaseModel):
    """Credentials forwarded to DevAtlas for authentication."""

    username: str
    password: str


class UserPublic(BaseModel):
    """Public user information returned by DevAtlas."""

    model_config = ConfigDict(extra="ignore")

    id: int
    username: str
    role: str
    is_active: bool
    created_at: datetime
    updated_at: datetime


class TokenResponse(BaseModel):
    """Access token response forwarded to the Web UI."""

    access_token: str
    token_type: Literal["bearer"]
    expires_in: int
    user: UserPublic

