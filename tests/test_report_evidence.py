"""Evidence-support tests for the report node (P0-3-1).

A structurally valid report is not an evidence-backed report. These tests pin
the rule: a report with no successful tool observation must not be presented as
a completed analysis, and the model's own confidence claim must be dropped.
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.incident_agent.core.statuses import RunStatus, StepErrorCode
from app.incident_agent.db.session import Base, get_db
from app.incident_agent.dependencies import get_access_token, get_current_user
from app.incident_agent.graph.nodes import make_report_node
from app.incident_agent.graph.workflow import build_graph
from app.incident_agent.models import AgentRun
from app.incident_agent.schemas.auth import UserPublic
from app.incident_agent.services import authorizer as authorizer_module
from app.incident_agent.services import incident as incident_module
from app.incident_agent.services.rag_client import MockRagGateway
from app.incident_agent.services.tools import build_tools
from app.main import app

REPORT_WITH_HIGH_CONFIDENCE = (
    '{"summary":"订单服务可能因数据库连接超时返回 502。","category":"database",'
    '"evidence":[{"source":"fault_log","detail":"日志命中 502 和 timeout。"}],'
    '"possible_causes":["数据库连接超时"],'
    '"troubleshooting_steps":["检查 MySQL 可用性"],'
    '"references":[],"confidence":"high"}'
)

REPORT_WITH_LOW_CONFIDENCE = REPORT_WITH_HIGH_CONFIDENCE.replace(
    '"confidence":"high"',
    '"confidence":"low"',
)


class FakeModel:
    """Deterministic model double."""

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


def make_state(*, observations: list | None = None, iteration: int = 1) -> dict:
    return {
        "run_id": "run-evidence-1",
        "owner_user_id": 1,
        "title": "订单服务故障",
        "input_content": "网关返回 502",
        "knowledge_base_id": 3,
        "top_k": 5,
        "messages": [
            SystemMessage(content="你是故障分析助手。"),
            HumanMessage(content="网关返回 502"),
        ],
        "observations": observations if observations is not None else [],
        "steps": [],
        "iteration": iteration,
        "max_iterations": 4,
        "status": RunStatus.RUNNING,
        "error": None,
        "report": None,
    }


def successful_observation() -> dict:
    return {
        "iteration": 1,
        "tool_name": "analyze_log",
        "tool_call_id": "call-log",
        "result": {
            "ok": True,
            "data": {"signals": [{"type": "http_502"}], "signal_count": 1},
            "error_code": None,
            "error": None,
        },
    }


def failed_observation() -> dict:
    return {
        "iteration": 1,
        "tool_name": "get_service_status",
        "tool_call_id": "call-status",
        "result": {
            "ok": False,
            "data": {},
            "error_code": "UNKNOWN_SERVICE",
            "error": "未知服务：gateway",
        },
    }


# --------------------------------------------------------------------------
# The report node itself
# --------------------------------------------------------------------------


def test_report_without_any_observation_is_marked_insufficient_evidence():
    node = make_report_node(FakeModel([AIMessage(content=REPORT_WITH_HIGH_CONFIDENCE)]))

    result = node(make_state(observations=[]))

    assert result["status"] == RunStatus.INSUFFICIENT_EVIDENCE
    assert result["report"] is not None
    assert result["error"] == "未取得任何成功的工具证据，报告仅基于用户描述生成"


def test_unsupported_report_confidence_is_clamped_to_low():
    """The model asking for ``high`` must not survive zero evidence."""

    node = make_report_node(FakeModel([AIMessage(content=REPORT_WITH_HIGH_CONFIDENCE)]))

    result = node(make_state(observations=[]))

    assert result["report"]["confidence"] == "low"


def test_unsupported_report_records_a_diagnosable_step():
    node = make_report_node(FakeModel([AIMessage(content=REPORT_WITH_HIGH_CONFIDENCE)]))

    result = node(make_state(observations=[]))

    evidence_steps = [
        step
        for step in result["steps"]
        if step.get("action") == "check_evidence_support"
    ]
    assert len(evidence_steps) == 1
    assert evidence_steps[0]["status"] == "failed"
    assert evidence_steps[0]["error_code"] == StepErrorCode.NO_TOOL_EVIDENCE


def test_report_with_a_successful_observation_stays_completed():
    node = make_report_node(FakeModel([AIMessage(content=REPORT_WITH_HIGH_CONFIDENCE)]))

    result = node(make_state(observations=[successful_observation()]))

    assert result["status"] == RunStatus.COMPLETED
    assert result["error"] is None
    assert result["report"]["confidence"] == "high"


def test_failed_observations_do_not_count_as_evidence():
    """A report whose only tools failed is as unsupported as a report with none."""

    node = make_report_node(FakeModel([AIMessage(content=REPORT_WITH_HIGH_CONFIDENCE)]))

    result = node(make_state(observations=[failed_observation()]))

    assert result["status"] == RunStatus.INSUFFICIENT_EVIDENCE
    assert result["report"]["confidence"] == "low"


def test_mixed_observations_count_as_supported():
    node = make_report_node(FakeModel([AIMessage(content=REPORT_WITH_HIGH_CONFIDENCE)]))

    result = node(
        make_state(observations=[failed_observation(), successful_observation()])
    )

    assert result["status"] == RunStatus.COMPLETED
    assert result["report"]["confidence"] == "high"


def test_low_confidence_report_is_never_raised():
    """The clamp only lowers confidence; it must not rewrite a cautious model."""

    node = make_report_node(FakeModel([AIMessage(content=REPORT_WITH_LOW_CONFIDENCE)]))

    result = node(make_state(observations=[successful_observation()]))

    assert result["status"] == RunStatus.COMPLETED
    assert result["report"]["confidence"] == "low"


# --------------------------------------------------------------------------
# End to end through the compiled graph
# --------------------------------------------------------------------------


def test_graph_without_tool_calls_never_reports_completed():
    agent_model = FakeModel([AIMessage(content="无需工具，直接给结论。")])
    report_model = FakeModel([AIMessage(content=REPORT_WITH_HIGH_CONFIDENCE)])
    graph = build_graph(
        model=agent_model,
        report_model=report_model,
        tools=build_tools(MockRagGateway()),
    )

    result = graph.invoke(make_state(observations=[]))

    assert result["status"] == RunStatus.INSUFFICIENT_EVIDENCE
    assert result["status"] != RunStatus.COMPLETED
    assert result["report"] is not None
    assert result["observations"] == []
    assert result["report"]["confidence"] == "low"


def test_graph_with_a_successful_tool_still_completes():
    agent_model = FakeModel(
        [
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "analyze_log",
                        "args": {"log_text": "502 mysql timeout"},
                        "id": "call-log",
                    }
                ],
            ),
            AIMessage(content="证据已足够。"),
        ]
    )
    graph = build_graph(
        model=agent_model,
        report_model=FakeModel([AIMessage(content=REPORT_WITH_HIGH_CONFIDENCE)]),
        tools=build_tools(MockRagGateway()),
    )

    result = graph.invoke(make_state(observations=[]))

    assert result["status"] == RunStatus.COMPLETED
    assert len(result["observations"]) == 1
    assert result["report"]["confidence"] == "high"


# --------------------------------------------------------------------------
# API level: the new status must reach the client and be persisted as-is
# --------------------------------------------------------------------------


def test_analyze_api_returns_insufficient_evidence_status(monkeypatch):
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    client = TestClient(app)

    def override_db():
        Base.metadata.create_all(engine)
        db = Session()
        try:
            yield db
        finally:
            db.close()

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

    class NoToolModel:
        """Never calls a tool, so the report has no evidence behind it."""

        def bind_tools(self, tools):
            return self

        def invoke(self, messages):
            return AIMessage(content=REPORT_WITH_HIGH_CONFIDENCE)

    monkeypatch.setattr(
        authorizer_module.HttpKnowledgeBaseAuthorizer,
        "__init__",
        fake_authorizer_init,
    )
    monkeypatch.setattr(
        incident_module,
        "create_chat_model",
        lambda settings: NoToolModel(),
    )
    app.dependency_overrides[get_current_user] = make_user
    app.dependency_overrides[get_access_token] = lambda: "token"
    app.dependency_overrides[get_db] = override_db

    try:
        response = client.post(
            "/api/v1/incidents/analyze",
            json={
                "title": "订单服务故障",
                "content": "网关返回 502，没有可用工具证据",
                "knowledge_base_id": 3,
            },
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == RunStatus.INSUFFICIENT_EVIDENCE
    assert payload["status"] != RunStatus.COMPLETED
    assert payload["report"] is not None
    assert payload["report"]["confidence"] == "low"
    assert payload["observations"] == []

    with Session() as db:
        run = db.scalar(select(AgentRun))
        assert run is not None
        assert run.status == RunStatus.INSUFFICIENT_EVIDENCE
