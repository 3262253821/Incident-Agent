"""Pre-flight knowledge-base authorization tests.

Covers the contract that used to be implicit: DevAtlas answers ``404`` for both
"knowledge base does not exist" and "knowledge base belongs to another user",
so the Agent must treat those the same, and must never let a run be created
before the check passes.

设计文档章节：§2.3 集成原则、§11.1 适配器接口、§13.2 分析请求。
"""

from __future__ import annotations

import httpx
import pytest
from langchain_core.messages import AIMessage
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.incident_agent.db.session import Base
from app.incident_agent.models import AgentRun, AgentStep
from app.incident_agent.schemas.auth import UserPublic
from app.incident_agent.schemas.incident import IncidentAnalyzeRequest
from app.incident_agent.services.authorizer import (
    HttpKnowledgeBaseAuthorizer,
    KnowledgeBaseAccessDeniedError,
    KnowledgeBaseAuthorizationUnavailableError,
    StaticKnowledgeBaseAuthorizer,
)
from app.incident_agent.services.incident import (
    KnowledgeBaseAccessError,
    execute_incident,
)
from app.incident_agent.services.rag_client import MockRagGateway

VALID_REPORT = (
    '{"summary":"已收集证据。","category":"database",'
    '"evidence":[{"source":"fault_log","detail":"命中 502 与超时。"}],'
    '"possible_causes":["数据库连接超时"],'
    '"troubleshooting_steps":["检查数据库"],'
    '"references":[],"confidence":"medium"}'
)


class FakeModel:
    """Deterministic model double that records how often it was asked."""

    def __init__(self, responses: list[AIMessage]):
        self.responses = list(responses)
        self.invoke_count = 0

    def bind_tools(self, tools):
        return self

    def invoke(self, messages):
        self.invoke_count += 1
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


def make_session():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


def make_request(*, knowledge_base_id: int = 3) -> IncidentAnalyzeRequest:
    return IncidentAnalyzeRequest(
        title="订单服务故障",
        content="网关返回 502",
        knowledge_base_id=knowledge_base_id,
    )


def make_http_authorizer(handler) -> HttpKnowledgeBaseAuthorizer:
    """Build the real HTTP adapter on top of a stubbed DevAtlas transport."""

    authorizer = HttpKnowledgeBaseAuthorizer(
        "http://devatlas.invalid",
        timeout_seconds=1.0,
    )
    authorizer._client = httpx.Client(
        base_url="http://devatlas.invalid",
        timeout=httpx.Timeout(1.0),
        transport=httpx.MockTransport(handler),
    )
    return authorizer


# --------------------------------------------------------------------------
# HTTP adapter: DevAtlas status codes -> normalized Agent errors
# --------------------------------------------------------------------------


def test_authorizer_returns_knowledge_base_when_devatlas_allows_access():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v1/knowledge-bases/7"
        assert request.headers["Authorization"] == "Bearer token-abc"
        return httpx.Response(
            200,
            json={
                "id": 7,
                "owner_id": 1,
                "name": "订单服务手册",
                "description": None,
                "created_at": "2026-09-01T00:00:00Z",
                "updated_at": "2026-09-02T00:00:00Z",
            },
        )

    knowledge_base = make_http_authorizer(handler).ensure_access(
        knowledge_base_id=7,
        access_token="token-abc",
    )

    assert knowledge_base.id == 7
    assert knowledge_base.name == "订单服务手册"


def test_authorizer_accepts_the_full_devatlas_knowledgebase_payload():
    """Guard the field contract against DevAtlas ``KnowledgeBasePublic``.

    The real response also carries ``owner_id``, ``description`` and two
    datetime fields; the Agent only needs ``id`` and ``name`` and must tolerate
    the rest instead of failing on unknown fields.
    """

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "id": 3,
                "owner_id": 1,
                "name": "订单服务故障排查手册",
                "description": "订单服务相关的历史故障与排查记录",
                "created_at": "2026-09-04T10:00:00",
                "updated_at": "2026-09-10T18:30:00",
            },
        )

    knowledge_base = make_http_authorizer(handler).ensure_access(
        knowledge_base_id=3,
        access_token="token-abc",
    )

    assert knowledge_base.id == 3
    assert knowledge_base.name == "订单服务故障排查手册"


def test_authorizer_maps_devatlas_404_to_access_denied():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"detail": "Knowledge base not found"})

    with pytest.raises(KnowledgeBaseAccessDeniedError) as excinfo:
        make_http_authorizer(handler).ensure_access(
            knowledge_base_id=999,
            access_token="token-abc",
        )

    assert excinfo.value.status_code == 404
    assert excinfo.value.error_code == "RAG_KNOWLEDGE_BASE_NOT_FOUND"


@pytest.mark.parametrize("upstream_status", [401, 403])
def test_authorizer_maps_rejected_token_to_unauthorized(upstream_status: int):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(upstream_status, json={"detail": "nope"})

    with pytest.raises(KnowledgeBaseAuthorizationUnavailableError) as excinfo:
        make_http_authorizer(handler).ensure_access(
            knowledge_base_id=3,
            access_token="expired-token",
        )

    assert excinfo.value.status_code == 401
    assert excinfo.value.error_code == "AUTH_UNAUTHORIZED"


def test_authorizer_maps_devatlas_500_to_bad_gateway():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="boom")

    with pytest.raises(KnowledgeBaseAuthorizationUnavailableError) as excinfo:
        make_http_authorizer(handler).ensure_access(
            knowledge_base_id=3,
            access_token="token-abc",
        )

    assert excinfo.value.status_code == 502
    assert excinfo.value.error_code == "AUTH_UPSTREAM_ERROR"


def test_authorizer_rejects_response_that_is_not_the_agreed_shape():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"unexpected": True})

    with pytest.raises(KnowledgeBaseAuthorizationUnavailableError) as excinfo:
        make_http_authorizer(handler).ensure_access(
            knowledge_base_id=3,
            access_token="token-abc",
        )

    assert excinfo.value.error_code == "AUTH_INVALID_RESPONSE"


def test_authorizer_maps_timeout_to_service_unavailable():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("too slow", request=request)

    with pytest.raises(KnowledgeBaseAuthorizationUnavailableError) as excinfo:
        make_http_authorizer(handler).ensure_access(
            knowledge_base_id=3,
            access_token="token-abc",
        )

    assert excinfo.value.status_code == 503
    assert excinfo.value.error_code == "AUTH_TIMEOUT"


# --------------------------------------------------------------------------
# Service: the check must happen before any Agent run row exists
# --------------------------------------------------------------------------


def test_execute_incident_checks_access_before_creating_a_run():
    Session = make_session()
    authorizer = StaticKnowledgeBaseAuthorizer(mode="allowed")
    model = FakeModel(
        [
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "analyze_log",
                        "args": {"log_text": "502 mysql timeout"},
                        "id": "call-log-only",
                    }
                ],
            ),
            AIMessage(content="证据已足够。"),
            AIMessage(content=VALID_REPORT),
        ]
    )

    with Session() as db:
        result = execute_incident(
            db,
            user=make_user(),
            request=make_request(knowledge_base_id=7),
            access_token="token-abc",
            model=model,
            rag_gateway=MockRagGateway(),
            knowledge_base_authorizer=authorizer,
        )

    assert result.status == "completed"
    assert authorizer.calls == [
        {"knowledge_base_id": 7, "has_access_token": True},
    ]


def test_log_only_run_cannot_bypass_authorization_and_leaves_no_run_row():
    """The core regression: no search_knowledge call, still fully authorized."""

    Session = make_session()
    authorizer = StaticKnowledgeBaseAuthorizer(mode="denied")
    # This model only ever touches the deterministic log tool. Under the old
    # behaviour DevAtlas was never contacted, so the run succeeded anyway.
    model = FakeModel([AIMessage(content="无需工具，直接给结论。")])

    with Session() as db:
        with pytest.raises(KnowledgeBaseAccessError) as excinfo:
            execute_incident(
                db,
                user=make_user(),
                request=make_request(knowledge_base_id=999),
                access_token="token-abc",
                model=model,
                rag_gateway=MockRagGateway(),
                knowledge_base_authorizer=authorizer,
            )

        assert excinfo.value.status_code == 404
        assert excinfo.value.error_code == "RAG_KNOWLEDGE_BASE_NOT_FOUND"
        assert db.query(AgentRun).count() == 0
        assert db.query(AgentStep).count() == 0

    assert model.invoke_count == 0
    assert authorizer.calls == [
        {"knowledge_base_id": 999, "has_access_token": True},
    ]


def test_unavailable_authorization_service_creates_no_run():
    Session = make_session()
    authorizer = StaticKnowledgeBaseAuthorizer(mode="unavailable")

    with Session() as db:
        with pytest.raises(KnowledgeBaseAccessError) as excinfo:
            execute_incident(
                db,
                user=make_user(),
                request=make_request(),
                access_token="token-abc",
                model=FakeModel([]),
                rag_gateway=MockRagGateway(),
                knowledge_base_authorizer=authorizer,
            )

        assert excinfo.value.status_code == 503
        assert db.query(AgentRun).count() == 0
