"""LangGraph state contract."""

from __future__ import annotations

from typing import Annotated, Any, TypedDict

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages


class AgentState(TypedDict):
    """Data shared by all nodes during one Incident Agent run."""

    run_id: str
    owner_user_id: int
    title: str
    input_content: str
    knowledge_base_id: int
    top_k: int
    messages: Annotated[list[BaseMessage], add_messages]
    observations: list[dict[str, Any]]
    steps: list[dict[str, Any]]
    iteration: int
    max_iterations: int
    status: str
    error: str | None
    report: dict[str, Any] | None

