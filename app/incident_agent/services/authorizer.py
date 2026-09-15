"""DevAtlas knowledge-base adapter: ownership pre-check and read-only catalog.

The Agent used to rely on the retrieval tool to discover that a knowledge base
was unavailable: if the model never called ``search_knowledge``, the run was
created and finished without DevAtlas ever seeing the knowledge-base id. This
module makes the ownership check an explicit, mandatory step that happens
*before* any Agent run row is written.

The same HTTP client also serves the frontend's knowledge-base dropdown
(``GET /api/v1/knowledge-bases``). The browser must not call DevAtlas directly
(the frontend is on another origin, so that would need CORS on DevAtlas), and
the Agent must not keep its own copy of "which knowledge bases exist" while
someone else answers "who may see them". One client, one token pass-through,
one error mapping.
"""

from __future__ import annotations

import json
from typing import Any, Protocol

import httpx

from ..schemas.knowledge_base import KnowledgeBaseOption, RagKnowledgeBase

# Message labels: both operations share the same failure mapping, only the
# wording differs. Keeping them as one parameter is what stops the two paths
# from slowly drifting apart.
_AUTHORIZATION_LABEL = "知识库授权校验"
_CATALOG_LABEL = "知识库列表"


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


class KnowledgeBaseCatalog(Protocol):
    """Interface used to fill the frontend's knowledge-base dropdown."""

    def list_accessible(self, *, access_token: str) -> list[KnowledgeBaseOption]:
        """Return the knowledge bases the token's owner may analyse."""


class HttpKnowledgeBaseAuthorizer:
    """HTTP implementation for the DevAtlas knowledge-base endpoints.

    Implements both ``KnowledgeBaseAuthorizer`` (the mandatory pre-flight check)
    and ``KnowledgeBaseCatalog`` (the dropdown). Every call carries the
    **caller's** token, so DevAtlas stays the only authority on what a user may
    see; the Agent neither stores the token nor re-signs it.
    """

    LIST_PATH = "/api/v1/knowledge-bases"
    DETAIL_PATH = "/api/v1/knowledge-bases/{knowledge_base_id}"

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

    # -- internals ---------------------------------------------------------

    def _get(self, path: str, access_token: str, *, label: str) -> httpx.Response:
        """GET one DevAtlas path, mapping transport failures to Agent errors."""

        try:
            return self._client.get(
                path,
                headers={"Authorization": f"Bearer {access_token}"},
            )
        except httpx.TimeoutException as exc:
            raise KnowledgeBaseAuthorizationUnavailableError(
                status_code=503,
                error_code="AUTH_TIMEOUT",
                message=f"DevAtlas {label}请求超时",
            ) from exc
        except httpx.RequestError as exc:
            raise KnowledgeBaseAuthorizationUnavailableError(
                status_code=503,
                error_code="AUTH_NETWORK_ERROR",
                message=f"无法连接 DevAtlas {label}服务",
            ) from exc

    def _raise_for_status(self, response: httpx.Response, *, label: str) -> None:
        """Map an upstream status code onto the normalized Agent vocabulary."""

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
                message=f"DevAtlas {label}服务返回错误",
            )

    def _decode_json(self, response: httpx.Response, *, label: str) -> Any:
        try:
            return response.json()
        except (json.JSONDecodeError, TypeError, ValueError) as exc:
            raise KnowledgeBaseAuthorizationUnavailableError(
                status_code=502,
                error_code="AUTH_INVALID_RESPONSE",
                message=f"DevAtlas {label}响应格式不符合约定",
            ) from exc

    def _invalid_response(
        self,
        *,
        label: str,
    ) -> KnowledgeBaseAuthorizationUnavailableError:
        return KnowledgeBaseAuthorizationUnavailableError(
            status_code=502,
            error_code="AUTH_INVALID_RESPONSE",
            message=f"DevAtlas {label}响应格式不符合约定",
        )

    # -- contracts ---------------------------------------------------------

    def ensure_access(
        self,
        *,
        knowledge_base_id: int,
        access_token: str,
    ) -> RagKnowledgeBase:
        label = _AUTHORIZATION_LABEL
        response = self._get(
            self.DETAIL_PATH.format(knowledge_base_id=knowledge_base_id),
            access_token,
            label=label,
        )

        # DevAtlas answers 404 for "missing" and "not yours" alike.
        if response.status_code == 404:
            raise KnowledgeBaseAccessDeniedError()

        self._raise_for_status(response, label=label)

        payload = self._decode_json(response, label=label)
        try:
            return RagKnowledgeBase.model_validate(payload)
        except (TypeError, ValueError) as exc:
            raise self._invalid_response(label=label) from exc

    def list_accessible(self, *, access_token: str) -> list[KnowledgeBaseOption]:
        """Return the caller's knowledge bases, newest updated first.

        DevAtlas filters the list by the token's owner and answers ``[]`` when
        the user has none, so a ``404`` here cannot mean "you own nothing": it
        means the upstream route is missing (for example a version mismatch).
        That is reported as an upstream error rather than disguised as an empty
        dropdown, which would look like a user with no knowledge bases.
        """

        label = _CATALOG_LABEL
        response = self._get(self.LIST_PATH, access_token, label=label)
        self._raise_for_status(response, label=label)

        payload = self._decode_json(response, label=label)
        if not isinstance(payload, list):
            raise self._invalid_response(label=label)

        try:
            return [KnowledgeBaseOption.model_validate(item) for item in payload]
        except (TypeError, ValueError) as exc:
            raise self._invalid_response(label=label) from exc


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
