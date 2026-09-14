from __future__ import annotations

import sys
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from langchain_core.messages import AIMessage

from app.incident_agent.db.session import Base
from app.incident_agent.schemas.auth import UserPublic
from app.incident_agent.schemas.incident import IncidentAnalyzeRequest
from app.incident_agent.services.incident import execute_incident
from app.incident_agent.services.rag_client import MockRagGateway


class FakeModel:
    def __init__(self, responses):
        self.responses = list(responses)

    def bind_tools(self, tools):
        return self

    def invoke(self, messages):
        return self.responses.pop(0)


def test_execute_incident_persists_graph_result():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    user = UserPublic(
        id=1,
        username="test-user",
        role="user",
        is_active=True,
        created_at="2026-09-04T00:00:00Z",
        updated_at="2026-09-04T00:00:00Z",
    )

    report = (
        '{"summary":"可能是数据库连接超时。","category":"database",'
        '"evidence":[{"source":"fault_log","detail":"命中超时。"}],'
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
                        "name": "analyze_log",
                        "args": {"log_text": "502 mysql timeout"},
                        "id": "call-service",
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
            user=user,
            request=IncidentAnalyzeRequest(
                title="订单服务故障",
                content="502 mysql timeout",
                knowledge_base_id=3,
            ),
            access_token="test-token",
            model=model,
            rag_gateway=MockRagGateway(),
        )

        assert result.status == "completed"
        assert result.report is not None
        assert len(result.observations) == 1
        assert len(result.steps) >= 3

        from app.incident_agent.models import AgentRun, AgentStep

        assert db.query(AgentRun).count() == 1
        assert db.query(AgentStep).count() == len(result.steps)


def test_execute_incident_forwards_request_top_k_to_rag_gateway():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    user = UserPublic(
        id=1,
        username="test-user",
        role="user",
        is_active=True,
        created_at="2026-09-04T00:00:00Z",
        updated_at="2026-09-04T00:00:00Z",
    )
    report = (
        '{"summary":"已收集证据。","category":"database",'
        '"evidence":[{"source":"knowledge_base","detail":"命中手册。"}],'
        '"possible_causes":["数据库连接超时"],'
        '"troubleshooting_steps":["检查数据库"],'
        '"references":[],"confidence":"medium"}'
    )
    gateway = MockRagGateway()
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
            user=user,
            request=IncidentAnalyzeRequest(
                title="订单服务故障",
                content="网关返回 502",
                knowledge_base_id=7,
                top_k=8,
            ),
            access_token="test-token",
            model=model,
            rag_gateway=gateway,
        )

    assert result.status == "completed"
    assert gateway.calls[0]["knowledge_base_id"] == 7
    assert gateway.calls[0]["top_k"] == 8
