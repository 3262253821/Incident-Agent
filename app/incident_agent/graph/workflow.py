"""Graph assembly for the formal Incident Agent workflow."""

from __future__ import annotations

from typing import Any, Sequence

from langchain_core.tools import BaseTool
from langgraph.graph import END, START, StateGraph

from ..services.rag_client import RagGateway
from ..services.tools import build_tools
from .nodes import (
    _redacting_tool_node,
    degrade_node,
    limit_node,
    make_agent_node,
    make_observe_node,
    make_report_node,
    route_after_agent,
    route_after_observe,
)
from .state import AgentState


def build_graph(
    *,
    model: Any,
    tools: Sequence[BaseTool],
    report_model: Any | None = None,
    max_iterations: int = 4,
):
    """Compile the Agent graph with injected model and tools.

    The base model is bound to tools only for the decision node. The report
    model remains unbound so report generation cannot trigger more tools.
    """

    if max_iterations < 1:
        raise ValueError("max_iterations 必须大于 0")
    if not tools:
        raise ValueError("至少需要注册一个工具")

    report_model = report_model or model
    builder = StateGraph(AgentState)
    builder.add_node("agent", make_agent_node(model, tools))
    builder.add_node("tools", _redacting_tool_node(tools))
    builder.add_node("observe", make_observe_node())
    builder.add_node("report", make_report_node(report_model))
    builder.add_node("degrade", degrade_node)
    builder.add_node(
        "limit",
        lambda state: limit_node(
            {**state, "max_iterations": max_iterations},
        ),
    )

    builder.add_edge(START, "agent")
    builder.add_conditional_edges(
        "agent",
        lambda state: route_after_agent(
            {**state, "max_iterations": max_iterations},
        ),
        {"tools": "tools", "report": "report", "limit": "limit"},
    )
    builder.add_edge("tools", "observe")
    builder.add_conditional_edges(
        "observe",
        route_after_observe,
        {"agent": "agent", "degrade": "degrade"},
    )
    builder.add_edge("report", END)
    builder.add_edge("degrade", END)
    builder.add_edge("limit", END)
    return builder.compile()


def build_graph_with_gateway(
    *,
    model: Any,
    rag_gateway: RagGateway,
    knowledge_base_id: int,
    top_k: int,
    access_token: str | None = None,
    report_model: Any | None = None,
    max_iterations: int = 4,
):
    """Compose request-scoped tools and compile the Agent graph."""

    tools = build_tools(
        rag_gateway,
        access_token=access_token,
        knowledge_base_id=knowledge_base_id,
        top_k=top_k,
    )
    return build_graph(
        model=model,
        tools=tools,
        report_model=report_model,
        max_iterations=max_iterations,
    )
