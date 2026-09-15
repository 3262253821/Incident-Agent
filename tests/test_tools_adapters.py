"""设计文档章节：§6.1 analyze_log、§6.2 search_knowledge、§6.3 get_service_status、§7 统一工具结果协议。
"""

from __future__ import annotations

from app.incident_agent.services.rag_client import MockRagGateway
from app.incident_agent.services.tools import build_tools


def test_build_tools_exposes_expected_names():
    tools = build_tools(MockRagGateway())

    assert [item.name for item in tools] == [
        "analyze_log",
        "search_knowledge",
        "get_service_status",
    ]


def test_search_knowledge_success():
    gateway = MockRagGateway()
    tools = build_tools(gateway, access_token="local-test-token")

    result = tools[1].invoke(
        {
            "query": "订单服务 502",
            "knowledge_base_id": 1,
            "top_k": 5,
        }
    )

    assert result["ok"] is True
    assert result["data"]["sources"][0]["version_id"] == 21
    assert gateway.calls[0]["has_access_token"] is True


def test_search_knowledge_uses_request_scoped_top_k_and_knowledge_base():
    gateway = MockRagGateway()
    tools = build_tools(
        gateway,
        knowledge_base_id=7,
        top_k=8,
        access_token="local-test-token",
    )

    result = tools[1].invoke(
        {
            "query": "订单服务 502",
            # Tool schema 不再把这两个边界参数交给模型控制。
            "knowledge_base_id": 999,
            "top_k": 1,
        }
    )

    assert result["ok"] is True
    assert gateway.calls[0]["knowledge_base_id"] == 7
    assert gateway.calls[0]["top_k"] == 8


def test_search_knowledge_tool_schema_only_exposes_query():
    tool = build_tools(MockRagGateway(), knowledge_base_id=3, top_k=5)[1]

    assert set(tool.args_schema.model_fields) == {"query"}


def test_search_knowledge_no_results_is_successful():
    tools = build_tools(MockRagGateway(mode="no_results"))

    result = tools[1].invoke(
        {
            "query": "不存在的故障",
            "knowledge_base_id": 1,
        }
    )

    assert result["ok"] is True
    assert result["data"]["sources"] == []


def test_search_knowledge_timeout_is_normalized():
    tools = build_tools(MockRagGateway(mode="timeout"))

    result = tools[1].invoke(
        {
            "query": "订单服务 502",
            "knowledge_base_id": 1,
        }
    )

    assert result["ok"] is False
    assert result["error_code"] == "RAG_TIMEOUT"


def test_search_knowledge_invalid_arguments_are_rejected():
    tools = build_tools(MockRagGateway())

    result = tools[1].invoke(
        {
            "query": "",
            "knowledge_base_id": 1,
        }
    )

    assert result["ok"] is False
    assert result["error_code"] == "INVALID_ARGUMENTS"


def test_service_status_unknown_service_is_normalized():
    tools = build_tools(MockRagGateway())

    result = tools[2].invoke(
        {
            "service_name": "gateway",
        }
    )

    assert result["ok"] is False
    assert result["error_code"] == "UNKNOWN_SERVICE"
