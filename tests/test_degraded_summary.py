"""Tests for the deterministic degraded summary (P0-3-3).

A failed run must still tell the user what was actually established. The summary
is assembled from recorded observations only, so these tests also assert that no
model output and no invented content can appear in it.

设计文档章节：§16.5 失败降级、§11.4 超时与重试。
"""

from __future__ import annotations

from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.incident_agent.core.statuses import RunStatus
from app.incident_agent.db.session import Base, get_db
from app.incident_agent.dependencies import get_access_token, get_current_user
from app.incident_agent.graph.evidence import (
    GENERIC_SUGGESTION,
    MAX_LOG_SIGNALS,
    build_degraded_summary,
)
from app.incident_agent.graph.workflow import build_graph
from app.incident_agent.models import AgentRun
from app.incident_agent.schemas.auth import UserPublic
from app.incident_agent.schemas.incident import IncidentAnalyzeRequest
from app.incident_agent.services import authorizer as authorizer_module
from app.incident_agent.services.authorizer import StaticKnowledgeBaseAuthorizer
from app.incident_agent.services.incident import execute_incident
from app.incident_agent.services.rag_client import MockRagGateway
from app.incident_agent.services.tools import build_tools
from app.main import app

KB_CONTENT = "订单服务返回 502 可能与数据库连接超时有关，建议检查 MySQL、连接池和网络连通性。"

VALID_REPORT = (
    '{"summary":"订单服务 502。","category":"database",'
    '"evidence":[{"source":"knowledge_base","detail":"' + KB_CONTENT + '"}],'
    '"possible_causes":["数据库连接超时"],'
    '"troubleshooting_steps":["检查数据库"],'
    '"references":[],"confidence":"medium"}'
)


class FakeModel:
    def __init__(self, responses):
        self.responses = list(responses)
        self.last_response = None

    def bind_tools(self, tools):
        return self

    def invoke(self, messages):
        # P1-2-1 之后报告节点可能多调一次（修复重试）。响应耗尽时重复最后一个，
        # 使"每次都返回非法内容"这类用例仍然表达同一个语义。
        if not self.responses:
            if self.last_response is None:
                raise AssertionError("FakeModel 没有预置任何响应")
            return self.last_response
        response = self.responses.pop(0)
        self.last_response = response
        return response


def make_user() -> UserPublic:
    return UserPublic(
        id=1,
        username="test-user",
        role="user",
        is_active=True,
        created_at="2026-09-04T00:00:00Z",
        updated_at="2026-09-04T00:00:00Z",
    )


def search_observation(*, ok: bool = True) -> dict:
    if not ok:
        return {
            "iteration": 1,
            "tool_name": "search_knowledge",
            "tool_call_id": "call-search",
            "result": {
                "ok": False,
                "data": {},
                "error_code": "RAG_UNAVAILABLE",
                "error": "DevAtlas 检索服务暂不可用",
            },
        }
    return {
        "iteration": 1,
        "tool_name": "search_knowledge",
        "tool_call_id": "call-search",
        "result": {
            "ok": True,
            "data": {
                "question": "订单服务 502",
                "context": KB_CONTENT,
                "sources": [
                    {
                        "document_id": 10,
                        "version_id": 21,
                        "version_number": 2,
                        "chunk_index": 2,
                        "filename": "订单服务故障排查手册.md",
                        "content": KB_CONTENT,
                        "distance": 0.25,
                        "page_number": None,
                    }
                ],
            },
            "error_code": None,
            "error": None,
        },
    }


def log_observation(*, signals: list | None = None, ok: bool = True) -> dict:
    return {
        "iteration": 1,
        "tool_name": "analyze_log",
        "tool_call_id": "call-log",
        "result": {
            "ok": ok,
            "data": {
                "signals": signals
                if signals is not None
                else [{"type": "http_502", "matched_text": "502", "line_number": 3}],
                "signal_count": len(signals) if signals is not None else 1,
            },
            "error_code": None if ok else "INVALID_ARGUMENTS",
            "error": None if ok else "日志参数校验失败",
        },
    }


def status_observation() -> dict:
    return {
        "iteration": 1,
        "tool_name": "get_service_status",
        "tool_call_id": "call-status",
        "result": {
            "ok": True,
            "data": {
                "service_name": "order-service",
                "status": "degraded",
                "deploy_version": "2026.08.31",
                "error_count": 27,
            },
            "error_code": None,
            "error": None,
        },
    }


def make_state(observations: list | None = None) -> dict:
    return {
        "run_id": "run-degraded-1",
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
        "iteration": 1,
        "max_iterations": 2,
        "status": RunStatus.RUNNING,
        "error": None,
        "report": None,
    }


# --------------------------------------------------------------------------
# The builder itself
# --------------------------------------------------------------------------


def test_summary_collects_failed_tools_and_error_codes():
    summary = build_degraded_summary(
        [search_observation(ok=False)],
        status=RunStatus.DEGRADED,
        error="工具执行失败",
    )

    assert summary.failed_tools == ["search_knowledge"]
    assert summary.successful_tools == []
    assert summary.reason == RunStatus.DEGRADED
    assert "RAG_UNAVAILABLE" in summary.text
    assert "DevAtlas 检索服务已启动" in summary.suggestions[0]


def test_summary_keeps_the_evidence_that_was_actually_obtained():
    summary = build_degraded_summary(
        [log_observation(), search_observation(), status_observation()],
        status=RunStatus.MAX_ITERATIONS,
        error="达到最大模型请求次数：2",
    )

    assert summary.successful_tools == [
        "analyze_log",
        "search_knowledge",
        "get_service_status",
    ]
    assert summary.log_signals[0].type == "http_502"
    assert summary.log_signals[0].matched_text == "502"
    assert summary.log_signals[0].line_number == 3
    assert summary.knowledge_base_sources[0].document_id == 10
    assert summary.knowledge_base_sources[0].chunk_index == 2
    assert summary.knowledge_base_sources[0].filename == "订单服务故障排查手册.md"
    assert "order-service：degraded" in summary.service_statuses
    assert "订单服务故障排查手册.md chunk 2" in summary.text
    assert "第 3 行" in summary.text


def test_summary_never_copies_the_model_report_into_the_text():
    """Only structured facts are rendered; error text is the caller's, not the model's."""

    summary = build_degraded_summary(
        [log_observation()],
        status=RunStatus.DEGRADED,
        error="报告结构校验失败：1 validation error",
    )

    assert "根因是内存泄漏" not in summary.text
    assert summary.suggestions == [GENERIC_SUGGESTION]


def test_summary_caps_log_signals_and_sources():
    many_signals = [
        {"type": f"signal_{index}", "matched_text": "x", "line_number": index}
        for index in range(50)
    ]
    summary = build_degraded_summary(
        [log_observation(signals=many_signals)],
        status=RunStatus.DEGRADED,
        error="e",
    )

    assert len(summary.log_signals) == MAX_LOG_SIGNALS


def test_summary_deduplicates_suggestions_but_keeps_order():
    summary = build_degraded_summary(
        [search_observation(ok=False), search_observation(ok=False)],
        status=RunStatus.DEGRADED,
        error="e",
    )

    assert summary.failed_tools == ["search_knowledge"]
    assert len(summary.suggestions) == 1


def test_summary_without_any_observation_says_so():
    summary = build_degraded_summary([], status=RunStatus.DEGRADED, error="e")

    assert "没有产生任何可用的工具观察结果" in summary.text
    assert summary.failed_tools == []
    assert summary.successful_tools == []


def test_summary_tolerates_malformed_observations():
    summary = build_degraded_summary(
        [None, "x", {"result": {"ok": True}}, {"tool_name": "analyze_log"}],
        status=RunStatus.DEGRADED,
        error="e",
    )

    # 没有 tool_name 的脏记录被跳过；有 tool_name 但没有 result 的算失败工具。
    assert summary.failed_tools == ["analyze_log"]
    assert summary.successful_tools == []


# --------------------------------------------------------------------------
# The three failure paths
# --------------------------------------------------------------------------


def test_tool_failure_path_returns_a_summary():
    agent_model = FakeModel(
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
    graph = build_graph(
        model=agent_model,
        report_model=FakeModel([]),
        tools=build_tools(MockRagGateway(mode="unavailable")),
    )

    result = graph.invoke(make_state())

    assert result["status"] == RunStatus.DEGRADED
    summary = result["degraded_summary"]
    assert summary is not None
    assert summary["failed_tools"] == ["search_knowledge"]
    assert summary["suggestions"]
    assert result["report"] is None


def test_report_validation_failure_path_returns_a_summary():
    agent_model = FakeModel([AIMessage(content="没有更多工具需要调用。")])
    graph = build_graph(
        model=agent_model,
        report_model=FakeModel([AIMessage(content="这不是 JSON")]),
        tools=build_tools(MockRagGateway()),
    )

    result = graph.invoke(make_state(observations=[log_observation()]))

    assert result["status"] == RunStatus.REPORT_VALIDATION_FAILED
    summary = result["degraded_summary"]
    assert summary is not None
    assert summary["reason"] == RunStatus.REPORT_VALIDATION_FAILED
    # 已经拿到的日志证据必须保留在摘要里。
    assert summary["log_signals"][0]["type"] == "http_502"
    assert "报告不是合法 JSON" in summary["text"]


def test_max_iterations_path_returns_a_summary():
    def repeated(call_id: str) -> AIMessage:
        return AIMessage(
            content="",
            tool_calls=[
                {
                    "name": "analyze_log",
                    "args": {"log_text": "502 mysql timeout"},
                    "id": call_id,
                }
            ],
        )

    graph = build_graph(
        model=FakeModel([repeated("call-1"), repeated("call-2")]),
        report_model=FakeModel([]),
        tools=build_tools(MockRagGateway()),
        max_iterations=2,
    )

    result = graph.invoke(make_state(observations=[log_observation()]))

    assert result["status"] == RunStatus.MAX_ITERATIONS
    summary = result["degraded_summary"]
    assert summary is not None
    assert summary["reason"] == RunStatus.MAX_ITERATIONS
    assert summary["successful_tools"] == ["analyze_log"]
    assert summary["log_signals"]


def test_insufficient_evidence_path_returns_a_summary():
    graph = build_graph(
        model=FakeModel([AIMessage(content="无需工具。")]),
        report_model=FakeModel([AIMessage(content=VALID_REPORT)]),
        tools=build_tools(MockRagGateway()),
    )

    result = graph.invoke(make_state())

    assert result["status"] == RunStatus.INSUFFICIENT_EVIDENCE
    summary = result["degraded_summary"]
    assert summary is not None
    assert summary["reason"] == RunStatus.INSUFFICIENT_EVIDENCE
    # 零工具证据时引用无法追溯，报告被整体剔除，摘要要说明这一点。
    assert "无法追溯到本次工具结果" in summary["text"]
    assert "不再返回结论" in summary["text"]
    assert summary["failed_tools"] == []


def test_completed_run_has_no_degraded_summary():
    agent_model = FakeModel(
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
        ]
    )
    graph = build_graph(
        model=agent_model,
        report_model=FakeModel([AIMessage(content=VALID_REPORT)]),
        tools=build_tools(MockRagGateway()),
    )

    result = graph.invoke(make_state())

    assert result["status"] == RunStatus.COMPLETED
    assert result.get("degraded_summary") is None


# --------------------------------------------------------------------------
# Service and API level
# --------------------------------------------------------------------------


def test_execute_incident_persists_and_returns_the_summary(monkeypatch):
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
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
            )
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
            rag_gateway=MockRagGateway(mode="unavailable"),
            knowledge_base_authorizer=StaticKnowledgeBaseAuthorizer(),
        )

        run = db.scalar(select(AgentRun))
        assert run is not None
        assert run.status == RunStatus.DEGRADED

    assert result.report is None
    assert result.degraded_summary is not None
    assert result.degraded_summary.failed_tools == ["search_knowledge"]
    assert "DevAtlas 检索服务已启动" in result.degraded_summary.suggestions[0]


def test_graph_crash_still_produces_a_summary():
    """A model/dependency exception must not collapse to a bare error string."""

    class ExplodingModel:
        def bind_tools(self, tools):
            raise RuntimeError("model backend exploded")

    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)

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
            model=ExplodingModel(),
            rag_gateway=MockRagGateway(),
            knowledge_base_authorizer=StaticKnowledgeBaseAuthorizer(),
        )

    assert result.status == RunStatus.DEGRADED
    assert result.degraded_summary is not None
    assert result.degraded_summary.reason == RunStatus.DEGRADED


def test_degraded_summary_reaches_the_api(monkeypatch):
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

    class DegradingModel:
        """第一轮调用检索工具，第二轮直接给结论。"""

        def __init__(self):
            self.calls = 0

        def bind_tools(self, tools):
            return self

        def invoke(self, messages):
            self.calls += 1
            if self.calls == 1:
                return AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "name": "search_knowledge",
                            "args": {"query": "订单服务 502"},
                            "id": "call-search",
                        }
                    ],
                )
            return AIMessage(content="证据已足够。")

    monkeypatch.setattr(
        authorizer_module.HttpKnowledgeBaseAuthorizer,
        "__init__",
        fake_authorizer_init,
    )
    import app.incident_agent.services.incident as incident_module

    monkeypatch.setattr(
        incident_module,
        "create_chat_model",
        lambda settings: DegradingModel(),
    )
    monkeypatch.setattr(
        incident_module,
        "create_report_model",
        lambda settings: DegradingModel(),
    )
    monkeypatch.setattr(
        incident_module,
        "HttpRagGateway",
        lambda base_url, timeout: MockRagGateway(mode="unavailable"),
    )
    app.dependency_overrides[get_current_user] = make_user
    app.dependency_overrides[get_access_token] = lambda: "token"
    app.dependency_overrides[get_db] = override_db

    try:
        response = client.post(
            "/api/v1/incidents/analyze",
            json={
                "title": "订单服务故障",
                "content": "网关返回 502，DevAtlas 不可用",
                "knowledge_base_id": 3,
            },
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == RunStatus.DEGRADED
    assert payload["report"] is None
    summary = payload["degraded_summary"]
    assert summary is not None
    assert summary["failed_tools"] == ["search_knowledge"]
    assert summary["text"]
    assert summary["suggestions"]
