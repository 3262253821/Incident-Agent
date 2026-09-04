"""Adapters for the DevAtlas retrieval API."""

from __future__ import annotations

import json
from typing import Protocol

import httpx

from ..schemas.rag import RagSearchResponse


class RagGatewayError(Exception):
    """A safe, normalized error from the retrieval gateway."""

    def __init__(self, error_code: str, message: str):
        super().__init__(message)
        self.error_code = error_code
        self.message = message


class RagGateway(Protocol):
    """Interface used by the Agent search tool."""

    def search_knowledge(
        self,
        *,
        query: str,
        knowledge_base_id: int,
        top_k: int,
        access_token: str | None = None,
    ) -> RagSearchResponse:
        """Search a DevAtlas knowledge base."""


class HttpRagGateway:
    """HTTP implementation for DevAtlas's retrieval-only endpoint."""

    def __init__(self, base_url: str, timeout_seconds: float = 20.0):
        self._client = httpx.Client(
            base_url=base_url.rstrip("/"),
            timeout=httpx.Timeout(timeout_seconds),
        )

    def close(self) -> None:
        """Close the underlying HTTP connection pool."""

        self._client.close()

    def __enter__(self) -> "HttpRagGateway":
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.close()

    def search_knowledge(
        self,
        *,
        query: str,
        knowledge_base_id: int,
        top_k: int,
        access_token: str | None = None,
    ) -> RagSearchResponse:
        headers: dict[str, str] = {}

        if access_token:
            headers["Authorization"] = f"Bearer {access_token}"

        try:
            response = self._client.post(
                f"/api/v1/knowledge-bases/{knowledge_base_id}/search",
                json={"question": query, "top_k": top_k},
                headers=headers,
            )
        except httpx.TimeoutException as exc:
            raise RagGatewayError(
                "RAG_TIMEOUT",
                "DevAtlas 检索请求超时",
            ) from exc
        except httpx.RequestError as exc:
            raise RagGatewayError(
                "RAG_NETWORK_ERROR",
                "无法连接 DevAtlas 检索服务",
            ) from exc

        error_mapping = {
            401: ("RAG_UNAUTHORIZED", "DevAtlas 鉴权失败"),
            404: (
                "RAG_KNOWLEDGE_BASE_NOT_FOUND",
                "知识库不存在或当前用户无权访问",
            ),
            422: ("RAG_INVALID_ARGUMENTS", "DevAtlas 检索参数不合法"),
            503: ("RAG_UNAVAILABLE", "DevAtlas 检索服务暂不可用"),
        }

        if response.status_code in error_mapping:
            error_code, message = error_mapping[response.status_code]
            raise RagGatewayError(error_code, message)

        if response.is_error:
            raise RagGatewayError(
                "RAG_HTTP_ERROR",
                f"DevAtlas 检索请求失败（HTTP {response.status_code}）",
            )

        try:
            payload = response.json()
            return RagSearchResponse.model_validate(payload)
        except (json.JSONDecodeError, TypeError, ValueError) as exc:
            raise RagGatewayError(
                "RAG_INVALID_RESPONSE",
                "DevAtlas 返回的数据格式不符合约定",
            ) from exc


class MockRagGateway:
    """Deterministic gateway for offline tests and local development."""

    def __init__(self, mode: str = "success"):
        self.mode = mode
        self.calls: list[dict[str, object]] = []

    def search_knowledge(
        self,
        *,
        query: str,
        knowledge_base_id: int,
        top_k: int,
        access_token: str | None = None,
    ) -> RagSearchResponse:
        self.calls.append(
            {
                "query": query,
                "knowledge_base_id": knowledge_base_id,
                "top_k": top_k,
                "has_access_token": bool(access_token),
            }
        )

        if self.mode == "timeout":
            raise RagGatewayError("RAG_TIMEOUT", "模拟 DevAtlas 检索超时")

        if self.mode == "unavailable":
            raise RagGatewayError("RAG_UNAVAILABLE", "模拟 DevAtlas 不可用")

        if self.mode == "invalid_response":
            raise RagGatewayError(
                "RAG_INVALID_RESPONSE",
                "模拟 DevAtlas 返回非法结构",
            )

        if self.mode == "no_results":
            return RagSearchResponse(
                question=query,
                context="",
                sources=[],
            )

        return RagSearchResponse(
            question=query,
            context=(
                "订单服务返回 502 可能与数据库连接超时有关，"
                "建议检查 MySQL、连接池和网络连通性。"
            ),
            sources=[
                {
                    "document_id": 10,
                    "version_id": 21,
                    "version_number": 2,
                    "chunk_index": 2,
                    "filename": "订单服务故障排查手册.md",
                    "content": (
                        "订单服务返回 502 可能与数据库连接超时有关，"
                        "建议检查 MySQL、连接池和网络连通性。"
                    ),
                    "distance": 0.25,
                    "page_number": None,
                }
            ],
        )
