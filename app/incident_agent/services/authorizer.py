"""DevAtlas knowledge-base authorization adapter.

The Agent used to rely on the retrieval tool to discover that a knowledge base
was unavailable: if the model never called ``search_knowledge``, the run was
created and finished without DevAtlas ever seeing the knowledge-base id. This
module makes the ownership check an explicit, mandatory step that happens
*before* any Agent run row is written.
"""

from __future__ import annotations

import json
from typing import Protocol

import httpx

from ..schemas.knowledge_base import RagKnowledgeBase


class KnowledgeBaseAuthorizationError(Exception):
    """Base class for safe, normalized pre-flight failures."""

    def __init__(
        self,
        *,
        status_code: int,
        error_code: str,
        message: str,
    ):
        super().__init__(message)
        self.status_code = status_code
        self.error_code = error_code
        self.message = message


class KnowledgeBaseAccessDeniedError(KnowledgeBaseAuthorizationError):
    """The knowledge base is missing or not visible to the current user.

    DevAtlas answers ``404`` for both "does not exist" and "belongs to someone
    else" on purpose, so the Agent must not try to tell those apart either.
    """

    def __init__(self, message: str = "知识库不存在或当前用户无权访问"):
        super().__init__(
            status_code=404,
            error_code="RAG_KNOWLEDGE_BASE_NOT_FOUND",
            message=message,
        )


class KnowledgeBaseAuthorizationUnavailableError(KnowledgeBaseAuthorizationError):
    """The token was rejected, or DevAtlas itself could not answer."""

    def __init__(
        self,
        *,
        status_code: int,
        error_code: str,
        message: str,
    ):
        super().__init__(
            status_code=status_code,
            error_code=error_code,
            message=message,
        )


class KnowledgeBaseAuthorizer(Protocol):
    """Interface used by the incident service before creating a run."""

    def ensure_access(
        self,
        *,
        knowledge_base_id: int,
        access_token: str,
    ) -> RagKnowledgeBase:
        """Return the knowledge base, or raise a normalized error."""


class HttpKnowledgeBaseAuthorizer:
    """HTTP implementation for ``GET /api/v1/knowledge-bases/{id}``."""

    def __init__(self, base_url: str, timeout_seconds: float = 20.0):
        self._client = httpx.Client(
            base_url=base_url.rstrip("/"),
            timeout=httpx.Timeout(timeout_seconds),
        )

    def close(self) -> None:
        """Close the underlying HTTP connection pool."""

        self._client.close()

    def __enter__(self) -> "HttpKnowledgeBaseAuthorizer":
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.close()

    def ensure_access(
        self,
        *,
        knowledge_base_id: int,
        access_token: str,
    ) -> RagKnowledgeBase:
        try:
            response = self._client.get(
                f"/api/v1/knowledge-bases/{knowledge_base_id}",
                headers={"Authorization": f"Bearer {access_token}"},
            )
        except httpx.TimeoutException as exc:
            raise KnowledgeBaseAuthorizationUnavailableError(
                status_code=503,
                error_code="AUTH_TIMEOUT",
                message="DevAtlas 知识库授权校验请求超时",
            ) from exc
        except httpx.RequestError as exc:
            raise KnowledgeBaseAuthorizationUnavailableError(
                status_code=503,
                error_code="AUTH_NETWORK_ERROR",
                message="无法连接 DevAtlas 知识库授权校验服务",
            ) from exc

        if response.status_code == 404:
            raise KnowledgeBaseAccessDeniedError()

        if response.status_code in (401, 403):
            raise KnowledgeBaseAuthorizationUnavailableError(
                status_code=401,
                error_code="AUTH_UNAUTHORIZED",
                message="登录状态无效或已过期",
            )

        if response.is_error:
            raise KnowledgeBaseAuthorizationUnavailableError(
                status_code=502,
                error_code="AUTH_UPSTREAM_ERROR",
                message="DevAtlas 知识库授权校验服务返回错误",
            )

        try:
            return RagKnowledgeBase.model_validate(response.json())
        except (json.JSONDecodeError, TypeError, ValueError) as exc:
            raise KnowledgeBaseAuthorizationUnavailableError(
                status_code=502,
                error_code="AUTH_INVALID_RESPONSE",
                message="DevAtlas 知识库授权校验响应格式不符合约定",
            ) from exc


class StaticKnowledgeBaseAuthorizer:
    """Deterministic authorizer shared by tests and offline development.

    ``mode`` accepts ``"allowed"``, ``"denied"`` or ``"unavailable"``.
    """

    def __init__(
        self,
        mode: str = "allowed",
        *,
        name: str = "离线测试知识库",
    ):
        self.mode = mode
        self.name = name
        self.calls: list[dict[str, object]] = []

    def ensure_access(
        self,
        *,
        knowledge_base_id: int,
        access_token: str,
    ) -> RagKnowledgeBase:
        self.calls.append(
            {
                "knowledge_base_id": knowledge_base_id,
                "has_access_token": bool(access_token),
            }
        )

        if self.mode == "denied":
            raise KnowledgeBaseAccessDeniedError()

        if self.mode == "unavailable":
            raise KnowledgeBaseAuthorizationUnavailableError(
                status_code=503,
                error_code="AUTH_NETWORK_ERROR",
                message="模拟 DevAtlas 授权校验不可用",
            )

        return RagKnowledgeBase(id=knowledge_base_id, name=self.name)
