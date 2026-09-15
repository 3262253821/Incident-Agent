"""Tests that a degraded summary survives persistence (P0-3-3 完整性修复).

The live probe found a gap: the summary existed only in the POST response, so
reopening the run from history showed ``degraded_summary: null``. These tests pin
the round-trip: what the live response returns must be what the history endpoint
returns later.
"""

from __future__ import annotations

from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.incident_agent.core.statuses import RunStatus
from app.incident_agent.db.session import Base, get_db
from app.incident_agent.dependencies import get_access_token, get_current_user
from app.incident_agent.models import AgentRun
from app.incident_agent.schemas.auth import UserPublic
from app.incident_agent.schemas.incident import IncidentAnalyzeRequest
from app.incident_agent.services import authorizer as authorizer_module
from app.incident_agent.services.authorizer import StaticKnowledgeBaseAuthorizer
from app.incident_agent.services.incident import execute_incident
from app.incident_agent.services.rag_client import MockRagGateway
from app.main import app


class FakeModel:
    def __init__(self, responses):
        self.responses = list(responses)

    def bind_tools(self, tools):
        return self

    def invoke(self, messages):
        if not self.responses:
            raise AssertionError("FakeModel 没有预置更多响应")
        return self.responses.pop(0)


def make_user() -> UserPublic:
    return UserPublic(
        id=1,
        username="test-user",
        role="user",
        is_active=True,
        created_at="2026-09-04T00:00:00Z",
        updated_at="2026-09-04T00:00:00Z",
    )


def make_engine():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return engine


def failing_model() -> FakeModel:
    """First round calls search_knowledge, then there is nothing left to return."""

    return FakeModel(
        [
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "search_knowledge",
                        "args": {"query": "订单服务 502"},
                        "id": "call-search",
                    }
                ],
            )
        ]
    )


def run_degraded_incident(Session):
    """Produce a degraded run through the real service with a failing gateway."""

    with Session() as db:
        return execute_incident(
            db,
            user=make_user(),
            request=IncidentAnalyzeRequest(
                title="订单服务故障",
                content="网关返回 502",
                knowledge_base_id=3,
            ),
            access_token="token",
            model=failing_model(),
            rag_gateway=MockRagGateway(mode="unavailable"),
            knowledge_base_authorizer=StaticKnowledgeBaseAuthorizer(),
        )


# --------------------------------------------------------------------------
# Persistence
# --------------------------------------------------------------------------


def test_degraded_summary_is_written_to_the_run_row():
    engine = make_engine()
    Session = sessionmaker(bind=engine, expire_on_commit=False)

    result = run_degraded_incident(Session)

    assert result.status == RunStatus.DEGRADED
    assert result.degraded_summary is not None

    with Session() as db:
        run = db.scalar(select(AgentRun))
        assert run is not None
        assert run.degraded_summary is not None
        assert run.degraded_summary["reason"] == RunStatus.DEGRADED
        assert run.degraded_summary["failed_tools"] == ["search_knowledge"]
        assert run.degraded_summary["text"]


def test_persisted_summary_matches_the_live_response():
    """The whole point of the fix: no divergence between response and storage."""

    engine = make_engine()
    Session = sessionmaker(bind=engine, expire_on_commit=False)

    result = run_degraded_incident(Session)

    with Session() as db:
        run = db.scalar(select(AgentRun))

    assert run.degraded_summary == result.degraded_summary.model_dump()


def test_successful_run_stores_no_summary():
    """A completed run must not carry a degraded summary in its row."""

    engine = make_engine()
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    report = (
        '{"summary":"订单服务 502。","category":"database",'
        '"evidence":[{"source":"knowledge_base","detail":'
        '"订单服务返回 502 可能与数据库连接超时有关，建议检查 MySQL、连接池和网络连通性。"}],'
        '"possible_causes":["数据库连接超时"],'
        '"troubleshooting_steps":["检查数据库"],'
        '"references":[],"confidence":"medium"}'
    )
    model = FakeModel(
        [
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "search_knowledge",
                        "args": {"query": "订单服务 502"},
                        "id": "call-search",
                    }
                ],
            ),
            AIMessage(content="证据已足够。"),
            AIMessage(content=report),
        ]
    )

    with Session() as db:
        result = execute_incident(
            db,
            user=make_user(),
            request=IncidentAnalyzeRequest(
                title="订单服务故障",
                content="网关返回 502",
                knowledge_base_id=3,
            ),
            access_token="token",
            model=model,
            rag_gateway=MockRagGateway(),
            knowledge_base_authorizer=StaticKnowledgeBaseAuthorizer(),
        )
        run = db.scalar(select(AgentRun))

    assert result.status == RunStatus.COMPLETED
    assert result.degraded_summary is None
    assert run.degraded_summary is None


# --------------------------------------------------------------------------
# API round trip
# --------------------------------------------------------------------------


def _patch_authorizer(monkeypatch):
    def fake_authorizer_init(self, base_url: str, timeout_seconds: float = 20.0):
        import httpx

        self._client = httpx.Client(
            base_url=base_url.rstrip("/"),
            transport=httpx.MockTransport(
                lambda request: httpx.Response(
                    200,
                    json={"id": 3, "owner_id": 1, "name": "订单服务手册"},
                )
            ),
        )

    monkeypatch.setattr(
        authorizer_module.HttpKnowledgeBaseAuthorizer,
        "__init__",
        fake_authorizer_init,
    )


def test_history_endpoint_returns_the_persisted_summary(monkeypatch):
    """The regression: reopening the run from history must show the summary."""

    engine = make_engine()
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    client = TestClient(app)

    run_degraded_incident(Session)
    _patch_authorizer(monkeypatch)

    def override_db():
        Base.metadata.create_all(engine)
        db = Session()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_current_user] = make_user
    app.dependency_overrides[get_access_token] = lambda: "token"
    app.dependency_overrides[get_db] = override_db

    try:
        listed = client.get("/api/v1/runs")
        with Session() as db:
            run_id = db.scalar(select(AgentRun)).run_id
        detail = client.get(f"/api/v1/runs/{run_id}")
    finally:
        app.dependency_overrides.clear()

    assert listed.status_code == 200
    assert detail.status_code == 200

    # 列表自 P1-3-1 起只返回摘要，完整降级摘要必须仍然能从详情接口读回来。
    summary = listed.json()[0]
    assert summary["run_id"] == run_id
    assert summary["status"] == RunStatus.DEGRADED
    assert summary["observations_count"] >= 1
    assert "degraded_summary" not in summary

    restored = detail.json()["degraded_summary"]
    assert restored is not None, "历史详情必须返回已持久化的降级摘要"
    assert restored["reason"] == RunStatus.DEGRADED
    assert restored["failed_tools"] == ["search_knowledge"]
    assert restored["text"]
    assert restored["suggestions"]
