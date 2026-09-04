from __future__ import annotations

import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from fastapi.testclient import TestClient

from app.incident_agent.dependencies import get_access_token, get_current_user
from app.incident_agent.schemas.auth import UserPublic
from app.main import app


client = TestClient(app)


def test_health_endpoint_is_public():
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "incident-agent-api",
    }


def test_protected_routes_require_bearer_token():
    response = client.get("/api/v1/auth/me")

    assert response.status_code == 401


def test_incident_contract_is_registered_and_requires_authentication():
    response = client.post(
        "/api/v1/incidents/analyze",
        json={
            "title": "订单服务返回 502",
            "content": "MySQL connection timeout",
            "knowledge_base_id": 1,
        },
    )

    assert response.status_code == 401


def test_incident_route_returns_explicit_not_implemented_until_graph_phase():
    user = UserPublic(
        id=1,
        username="test-user",
        role="user",
        is_active=True,
        created_at="2026-09-04T00:00:00Z",
        updated_at="2026-09-04T00:00:00Z",
    )

    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_access_token] = lambda: "test-token"

    try:
        response = client.post(
            "/api/v1/incidents/analyze",
            json={
                "title": "订单服务返回 502",
                "content": "MySQL connection timeout",
                "knowledge_base_id": 1,
            },
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 501
    assert "LangGraph" in response.json()["detail"]


def test_database_health_endpoint_is_available():
    response = client.get("/health/db")

    assert response.status_code in (200, 503)
    assert response.json()["service"] == "incident-agent-db"

