from __future__ import annotations

import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.incident_agent.rag_client import MockRagGateway
from app.incident_agent.tools import build_tools


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
