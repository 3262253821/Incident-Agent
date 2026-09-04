from __future__ import annotations

import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from app.incident_agent.graph.state import AgentState
from app.incident_agent.graph.nodes import parse_report
from app.incident_agent.graph.workflow import build_graph
from app.incident_agent.services.rag_client import MockRagGateway
from app.incident_agent.services.tools import build_tools


VALID_REPORT = (
    '{"summary":"订单服务可能因数据库连接超时返回502。",'
    '"category":"database",'
    '"evidence":[{"source":"fault_log","detail":"日志命中502和timeout。"}],'
    '"possible_causes":["数据库连接超时"],'
    '"troubleshooting_steps":["检查MySQL可用性"],'
    '"references":[],"confidence":"medium"}'
)


class FakeModel:
    """Deterministic model double for graph tests."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.bound_tools = []

    def bind_tools(self, tools):
        self.bound_tools = list(tools)
        return self

    def invoke(self, messages):
        if not self.responses:
            raise AssertionError("FakeModel 没有预置更多响应")
        response = self.responses.pop(0)
        return response


def make_state(content: str = "订单服务返回502，MySQL连接超时") -> AgentState:
    return {
        "run_id": "run-test-1",
        "owner_user_id": 1,
        "title": "订单服务故障",
        "input_content": content,
        "knowledge_base_id": 3,
        "top_k": 5,
        "messages": [
            SystemMessage(content="你是故障分析助手。"),
            HumanMessage(content=content),
        ],
        "observations": [],
        "steps": [],
        "iteration": 0,
        "max_iterations": 4,
        "status": "running",
        "error": None,
        "report": None,
    }


def test_graph_normal_path_runs_tool_observe_and_report():
    agent_model = FakeModel(
        [
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "analyze_log",
                        "args": {"log_text": "502 mysql timeout"},
                        "id": "call-1",
                    }
                ],
            ),
            AIMessage(content="证据已足够。"),
        ]
    )
    report_model = FakeModel([AIMessage(content=VALID_REPORT)])
    graph = build_graph(
        model=agent_model,
        report_model=report_model,
        tools=build_tools(MockRagGateway()),
    )

    result = graph.invoke(make_state())

    assert result["status"] == "completed"
    assert result["iteration"] == 2
    assert result["report"]["category"] == "database"
    assert result["observations"][0]["tool_name"] == "analyze_log"
    assert any(step["node"] == "report" for step in result["steps"])


def test_parse_report_maps_known_tool_names_to_business_sources():
    raw_report = (
        '{"summary":"已收集证据。","category":"database",'
        '"evidence":['
        '{"source":"analyze_log","detail":"日志命中超时。"},'
        '{"source":"search_knowledge","detail":"知识库有相关手册。"},'
        '{"source":"get_service_status","detail":"服务处于降级状态。"}],'
        '"possible_causes":["数据库连接超时"],'
        '"troubleshooting_steps":["检查数据库"],'
        '"references":[],"confidence":"medium"}'
    )

    report = parse_report(raw_report)

    assert [item.source for item in report.evidence] == [
        "fault_log",
        "knowledge_base",
        "service_status",
    ]


def test_graph_executes_multiple_tool_calls_in_one_tool_node_turn():
    agent_model = FakeModel(
        [
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "analyze_log",
                        "args": {"log_text": "502 mysql timeout"},
                        "id": "call-log",
                    },
                    {
                        "name": "get_service_status",
                        "args": {"service_name": "order-service"},
                        "id": "call-status",
                    },
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

    assert result["status"] == "completed"
    assert {item["tool_name"] for item in result["observations"]} == {
        "analyze_log",
        "get_service_status",
    }
    assert len(result["observations"]) == 2


def test_graph_stops_and_degrades_on_tool_failure():
    agent_model = FakeModel(
        [
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "get_service_status",
                        "args": {"service_name": "gateway"},
                        "id": "call-failed",
                    }
                ],
            )
        ]
    )
    graph = build_graph(
        model=agent_model,
        report_model=FakeModel([]),
        tools=build_tools(MockRagGateway()),
    )

    result = graph.invoke(make_state("请检查 gateway 状态"))

    assert result["status"] == "degraded"
    assert "未知服务" in result["error"]
    assert len(result["observations"]) == 1
    assert result["observations"][0]["result"]["error_code"] == "UNKNOWN_SERVICE"


def test_graph_marks_invalid_report_without_calling_tools_again():
    agent_model = FakeModel([AIMessage(content="没有更多工具需要调用。")])
    report_model = FakeModel([AIMessage(content="这不是 JSON")])
    graph = build_graph(
        model=agent_model,
        report_model=report_model,
        tools=build_tools(MockRagGateway()),
    )

    result = graph.invoke(make_state("无法确定原因"))

    assert result["status"] == "report_validation_failed"
    assert result["report"] is None
    assert "不是合法 JSON" in result["error"]


def test_graph_stops_at_max_model_iterations():
    repeated_call = lambda call_id: AIMessage(
        content="",
        tool_calls=[
            {
                "name": "analyze_log",
                "args": {"log_text": "502"},
                "id": call_id,
            }
        ],
    )
    agent_model = FakeModel([repeated_call("call-1"), repeated_call("call-2")])
    graph = build_graph(
        model=agent_model,
        report_model=FakeModel([]),
        tools=build_tools(MockRagGateway()),
        max_iterations=2,
    )

    result = graph.invoke(make_state())

    assert result["status"] == "max_iterations"
    assert result["iteration"] == 2
    assert len(result["observations"]) == 1
    assert "最大模型请求次数" in result["error"]
