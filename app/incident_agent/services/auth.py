"""Small HTTP client for the DevAtlas authentication endpoints."""

from __future__ import annotations

import json

import httpx

from ..schemas.auth import LoginRequest, TokenResponse, UserPublic


class DevAtlasAuthError(Exception):
    """Normalized, safe error from the DevAtlas auth service."""

    def __init__(self, status_code: int, message: str):
        super().__init__(message)
        self.status_code = status_code
        self.message = message


class DevAtlasAuthClient:
    """Proxy login and current-user validation without storing tokens."""

    def __init__(self, base_url: str, timeout_seconds: float = 20.0):
        self._client = httpx.Client(
            base_url=base_url.rstrip("/"),
            timeout=httpx.Timeout(timeout_seconds),
        )

    def close(self) -> None:
        self._client.close()

    def login(self, data: LoginRequest) -> TokenResponse:
        try:
            response = self._client.post(
                "/api/v1/auth/login",
                json=data.model_dump(),
            )
        except httpx.TimeoutException as exc:
            raise DevAtlasAuthError(503, "DevAtlas 登录服务请求超时") from exc
        except httpx.RequestError as exc:
            raise DevAtlasAuthError(503, "无法连接 DevAtlas 登录服务") from exc

        if response.status_code == 401:
            raise DevAtlasAuthError(401, "用户名或密码错误")
        if response.status_code == 403:
            raise DevAtlasAuthError(403, "用户已被禁用")
        if response.is_error:
            raise DevAtlasAuthError(502, "DevAtlas 登录服务返回错误")

        try:
            return TokenResponse.model_validate(response.json())
        except (json.JSONDecodeError, TypeError, ValueError) as exc:
            raise DevAtlasAuthError(502, "DevAtlas 登录响应格式不符合约定") from exc

    def current_user(self, access_token: str) -> UserPublic:
        try:
            response = self._client.get(
                "/api/v1/auth/me",
                headers={"Authorization": f"Bearer {access_token}"},
            )
        except httpx.TimeoutException as exc:
            raise DevAtlasAuthError(503, "DevAtlas 用户验证请求超时") from exc
        except httpx.RequestError as exc:
            raise DevAtlasAuthError(503, "无法连接 DevAtlas 用户验证服务") from exc

        if response.status_code in (401, 403):
            raise DevAtlasAuthError(401, "登录状态无效或已过期")
        if response.is_error:
            raise DevAtlasAuthError(502, "DevAtlas 用户验证服务返回错误")

        try:
            return UserPublic.model_validate(response.json())
        except (json.JSONDecodeError, TypeError, ValueError) as exc:
            raise DevAtlasAuthError(502, "DevAtlas 用户信息格式不符合约定") from exc

    def __enter__(self) -> "DevAtlasAuthClient":
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.close()

