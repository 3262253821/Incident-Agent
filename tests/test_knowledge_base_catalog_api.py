"""Knowledge-base dropdown proxy: contract, error mapping and trimming.

The frontend cannot call DevAtlas directly (different origin), so the Agent
exposes a read-only proxy at ``GET /api/v1/knowledge-bases``. These tests pin the
properties that make the proxy safe to rely on:

- the **caller's** token is forwarded verbatim and DevAtlas stays the owner
  filter — the Agent never invents or widens the list;
- upstream failures keep the normalized Agent contract (``401`` with a
  challenge, safe ``502``/``503``) instead of leaking status codes or text;
- a broken upstream payload is an error, not an empty dropdown;
- the endpoint never touches the Agent database.
"""

from __future__ import annotations

import httpx
import pytest
from fastapi.testclient import TestClient

from app.incident_agent.dependencies import get_access_token, get_current_user
from app.incident_agent.schemas.auth import UserPublic
from app.incident_agent.services.authorizer import (
    HttpKnowledgeBaseAuthorizer,
    KnowledgeBaseAuthorizationUnavailableError,
)
from app.main import app

client = TestClient(app)

DEVATLAS_PAYLOAD = [
    {
        "id": 4,
        "owner_id": 5,
        "name": "DevAtlas 开发演示知识库",
        "description": "DevAtlas 演示用知识库",
        "created_at": "2026-09-04T10:00:00",
        "updated_at": "2026-09-10T18:30:00",
    },
    {
        "id": 7,
        "owner_id": 5,
        "name": "订单服务手册",
        "description": None,
        "created_at": "2026-09-01T00:00:00",
        "updated_at": "2026-09-02T00:00:00",
    },
]


def make_user() -> UserPublic:
    return UserPublic(
        id=5,
        username="devatlas-demo",
        role="user",
        is_active=True,
        created_at="2026-09-04T00:00:00Z",
        updated_at="2026-09-04T00:00:00Z",
    )


def make_catalog(handler) -> HttpKnowledgeBaseAuthorizer:
    """Build the real adapter on top of a stubbed DevAtlas transport."""

    catalog = HttpKnowledgeBaseAuthorizer(
        "http://devatlas.invalid",
        timeout_seconds=1.0,
    )
    catalog._client = httpx.Client(
        base_url="http://devatlas.invalid",
        timeout=httpx.Timeout(1.0),
        transport=httpx.MockTransport(handler),
    )
    return catalog


def install_auth_overrides() -> None:
    """Authenticate as a fixed user; deliberately no ``get_db`` override.

    The proxy route has no database dependency, so leaving ``get_db`` untouched
    makes "the dropdown works without MySQL" part of the assertion rather than a
    comment.
    """

    app.dependency_overrides[get_current_user] = make_user
    app.dependency_overrides[get_access_token] = lambda: "token-abc"


def patch_catalog_transport(monkeypatch, handler, captured: list) -> None:
    """Serve the route's own HTTP client from a stub instead of real DevAtlas."""

    def recording_handler(request: httpx.Request) -> httpx.Response:
        captured.append(
            {
                "method": request.method,
                "path": request.url.path,
                "authorization": request.headers.get("Authorization"),
            }
        )
        return handler(request)

    def fake_init(self, base_url: str, timeout_seconds: float = 20.0):
        self._client = httpx.Client(
            base_url=base_url.rstrip("/"),
            timeout=httpx.Timeout(timeout_seconds),
            transport=httpx.MockTransport(recording_handler),
        )

    monkeypatch.setattr(
        "app.incident_agent.services.authorizer.HttpKnowledgeBaseAuthorizer.__init__",
        fake_init,
    )


def list_payload(request: httpx.Request) -> httpx.Response:
    """Default upstream answer: the real DevAtlas list payload."""

    return httpx.Response(200, json=DEVATLAS_PAYLOAD)


# --------------------------------------------------------------------------
# Adapter: DevAtlas status codes and payloads -> normalized Agent errors
# --------------------------------------------------------------------------


def test_catalog_returns_options_and_forwards_the_callers_token():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert request.url.path == "/api/v1/knowledge-bases"
        assert request.headers["Authorization"] == "Bearer token-abc"
        return httpx.Response(200, json=DEVATLAS_PAYLOAD)

    options = make_catalog(handler).list_accessible(access_token="token-abc")

    assert [option.model_dump() for option in options] == [
        {
            "id": 4,
            "name": "DevAtlas 开发演示知识库",
            "description": "DevAtlas 演示用知识库",
        },
        {"id": 7, "name": "订单服务手册", "description": None},
    ]


def test_catalog_treats_a_non_array_payload_as_an_invalid_response():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"items": DEVATLAS_PAYLOAD})

    with pytest.raises(KnowledgeBaseAuthorizationUnavailableError) as excinfo:
        make_catalog(handler).list_accessible(access_token="token-abc")

    assert excinfo.value.status_code == 502
    assert excinfo.value.error_code == "AUTH_INVALID_RESPONSE"


def test_catalog_rejects_items_that_do_not_match_the_contract():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[{"id": "not-a-number", "name": 7}])

    with pytest.raises(KnowledgeBaseAuthorizationUnavailableError) as excinfo:
        make_catalog(handler).list_accessible(access_token="token-abc")

    assert excinfo.value.error_code == "AUTH_INVALID_RESPONSE"


def test_catalog_treats_a_missing_upstream_route_as_an_upstream_error():
    """A 404 on the *list* endpoint must not look like "you own nothing"."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"detail": "Not Found"})

    with pytest.raises(KnowledgeBaseAuthorizationUnavailableError) as excinfo:
        make_catalog(handler).list_accessible(access_token="token-abc")

    assert excinfo.value.status_code == 502
    assert excinfo.value.error_code == "AUTH_UPSTREAM_ERROR"


def test_catalog_maps_unreachable_devatlas_to_dependency_unavailable():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("devatlas down", request=request)

    with pytest.raises(KnowledgeBaseAuthorizationUnavailableError) as excinfo:
        make_catalog(handler).list_accessible(access_token="token-abc")

    assert excinfo.value.status_code == 503
    assert excinfo.value.error_code == "AUTH_NETWORK_ERROR"


# --------------------------------------------------------------------------
# API: the contract the frontend dropdown consumes
# --------------------------------------------------------------------------


def test_list_endpoint_returns_options_without_owner_fields(monkeypatch):
    captured: list = []
    install_auth_overrides()
    patch_catalog_transport(monkeypatch, list_payload, captured)

    try:
        response = client.get("/api/v1/knowledge-bases")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json() == [
        {
            "id": 4,
            "name": "DevAtlas 开发演示知识库",
            "description": "DevAtlas 演示用知识库",
        },
        {"id": 7, "name": "订单服务手册", "description": None},
    ]
    # owner_id / created_at / updated_at 属于 DevAtlas 的内部字段，不下发浏览器。
    assert "owner_id" not in response.text
    assert "updated_at" not in response.text
    assert captured == [
        {
            "method": "GET",
            "path": "/api/v1/knowledge-bases",
            "authorization": "Bearer token-abc",
        }
    ]


def test_list_endpoint_returns_an_empty_array_when_the_user_owns_nothing(monkeypatch):
    captured: list = []
    install_auth_overrides()
    patch_catalog_transport(
        monkeypatch,
        lambda request: httpx.Response(200, json=[]),
        captured,
    )

    try:
        response = client.get("/api/v1/knowledge-bases")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json() == []


def test_list_endpoint_requires_a_bearer_token(monkeypatch):
    captured: list = []
    patch_catalog_transport(monkeypatch, list_payload, captured)

    try:
        response = client.get("/api/v1/knowledge-bases")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"] == "Bearer"
    assert response.json()["error_code"] == "UNAUTHORIZED"
    # 未通过鉴权时不得联系 DevAtlas。
    assert captured == []


def test_list_endpoint_maps_a_rejected_token_to_401_with_a_challenge(monkeypatch):
    captured: list = []
    install_auth_overrides()
    patch_catalog_transport(
        monkeypatch,
        lambda request: httpx.Response(401, json={"detail": "Token expired"}),
        captured,
    )

    try:
        response = client.get("/api/v1/knowledge-bases")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"] == "Bearer"
    assert response.json()["error_code"] == "UNAUTHORIZED"
    assert captured[0]["authorization"] == "Bearer token-abc"


def test_list_endpoint_maps_an_upstream_failure_to_a_safe_502(monkeypatch):
    captured: list = []
    install_auth_overrides()
    patch_catalog_transport(
        monkeypatch,
        lambda request: httpx.Response(500, text="Traceback: secret path /srv/app"),
        captured,
    )

    try:
        response = client.get("/api/v1/knowledge-bases")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 502
    assert response.json()["error_code"] == "UPSTREAM_ERROR"
    assert "Traceback" not in response.text
    assert "secret path" not in response.text


def test_list_endpoint_maps_unreachable_devatlas_to_503(monkeypatch):
    captured: list = []
    install_auth_overrides()

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("devatlas down", request=request)

    patch_catalog_transport(monkeypatch, handler, captured)

    try:
        response = client.get("/api/v1/knowledge-bases")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 503
    assert response.json()["error_code"] == "DEPENDENCY_UNAVAILABLE"
    assert "DevAtlas" in response.json()["detail"]
