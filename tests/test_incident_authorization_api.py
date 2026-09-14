"""API-level knowledge-base authorization tests.

These go through FastAPI so the HTTP status codes are covered end to end, and
they assert the persisted side effect: a rejected knowledge base must not leave
an ``agent_runs`` row behind.
"""

from __future__ import annotations

import httpx
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.incident_agent.db.session import Base, get_db
from app.incident_agent.dependencies import get_access_token, get_current_user
from app.incident_agent.models import AgentRun
from app.incident_agent.schemas.auth import UserPublic
from app.incident_agent.services import authorizer as authorizer_module
from app.main import app

client = TestClient(app)


def make_user() -> UserPublic:
    return UserPublic(
        id=1,
        username="test-user",
        role="user",
        is_active=True,
        created_at="2026-09-04T00:00:00Z",
        updated_at="2026-09-04T00:00:00Z",
    )


def make_session():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


def _install_overrides(Session):
    """Authenticate as a fixed user and bind the route to an in-memory DB."""

    def override_db():
        db = Session()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_current_user] = make_user
    app.dependency_overrides[get_access_token] = lambda: "token-abc"
    app.dependency_overrides[get_db] = override_db


def _patch_authorizer(monkeypatch, upstream_status: int, captured: list):
    """Replace the real HTTP authorizer with a stubbed DevAtlas transport."""

    def fake_init(self, base_url: str, timeout_seconds: float = 20.0):
        def handler(request: httpx.Request) -> httpx.Response:
            captured.append(
                {
                    "path": request.url.path,
                    "authorization": request.headers.get("Authorization"),
                }
            )
            if upstream_status == 0:
                raise httpx.ConnectError("devatlas down", request=request)
            if upstream_status == 200:
                return httpx.Response(
                    200,
                    json={"id": 3, "owner_id": 1, "name": "订单服务手册"},
                )
            return httpx.Response(
                upstream_status,
                json={"detail": "Knowledge base not found"},
            )

        self._client = httpx.Client(
            base_url=base_url.rstrip("/"),
            timeout=httpx.Timeout(timeout_seconds),
            transport=httpx.MockTransport(handler),
        )

    monkeypatch.setattr(
        authorizer_module.HttpKnowledgeBaseAuthorizer,
        "__init__",
        fake_init,
    )


def test_analyze_rejects_knowledge_base_that_devatlas_does_not_own(monkeypatch):
    Session = make_session()
    captured: list = []
    _install_overrides(Session)
    _patch_authorizer(monkeypatch, 404, captured)

    try:
        response = client.post(
            "/api/v1/incidents/analyze",
            json={
                "title": "订单服务返回 502",
                "content": "MySQL connection timeout",
                "knowledge_base_id": 999,
            },
        )

        with Session() as db:
            run_count = db.query(AgentRun).count()
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 404
    assert response.json()["detail"] == "知识库不存在或当前用户无权访问"
    assert run_count == 0
    assert captured == [
        {
            "path": "/api/v1/knowledge-bases/999",
            "authorization": "Bearer token-abc",
        }
    ]


def test_analyze_returns_401_with_challenge_when_token_is_rejected(monkeypatch):
    Session = make_session()
    _install_overrides(Session)
    _patch_authorizer(monkeypatch, 401, [])

    try:
        response = client.post(
            "/api/v1/incidents/analyze",
            json={
                "title": "订单服务返回 502",
                "content": "MySQL connection timeout",
                "knowledge_base_id": 3,
            },
        )

        with Session() as db:
            run_count = db.query(AgentRun).count()
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"] == "Bearer"
    assert run_count == 0


def test_analyze_returns_503_when_devatlas_is_unreachable(monkeypatch):
    Session = make_session()
    _install_overrides(Session)
    _patch_authorizer(monkeypatch, 0, [])

    try:
        response = client.post(
            "/api/v1/incidents/analyze",
            json={
                "title": "订单服务返回 502",
                "content": "MySQL connection timeout",
                "knowledge_base_id": 3,
            },
        )

        with Session() as db:
            run_count = db.query(AgentRun).count()
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 503
    assert "DevAtlas" in response.json()["detail"]
    assert run_count == 0


def test_analyze_rejects_unknown_request_fields_before_authorization(monkeypatch):
    Session = make_session()
    captured: list = []
    _install_overrides(Session)
    _patch_authorizer(monkeypatch, 200, captured)

    try:
        response = client.post(
            "/api/v1/incidents/analyze",
            json={
                "title": "订单服务返回 502",
                "content": "MySQL connection timeout",
                "knowledge_base_id": 3,
                "owner_id": 1,
            },
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 422
    assert captured == []
