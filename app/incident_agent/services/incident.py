"""Application service that executes and persists one Agent run."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from langchain_core.messages import HumanMessage, SystemMessage
from sqlalchemy.orm import Session

from ..core.config import Settings, get_settings
from ..graph.state import AgentState
from ..graph.workflow import build_graph_with_gateway
from ..models import AgentRun
from ..schemas.auth import UserPublic
from ..schemas.incident import IncidentAnalyzeRequest, RunResponse
from .llm import create_chat_model
from .rag_client import HttpRagGateway, RagGateway
from .storage import append_steps, create_run, finish_run

AGENT_SYSTEM_PROMPT = """
你是 Incident Agent 故障分析助手。
请根据用户提供的故障标题和日志，选择合适的工具收集证据。
工具失败时不要继续调用工具，应当降级结束。
只能提供排查建议，不能执行命令、重启服务或修改生产配置。
报告必须区分已观察事实、可能原因和建议，不得把推测写成确定根因。
""".strip()


def _initial_state(
    *,
    run_id: str,
    user: UserPublic,
    request: IncidentAnalyzeRequest,
    top_k: int,
    max_iterations: int,
) -> AgentState:
    """Build the first state without placing the JWT into it."""

    return {
        "run_id": run_id,
        "owner_user_id": user.id,
        "title": request.title.strip(),
        "input_content": request.content.strip(),
        "knowledge_base_id": request.knowledge_base_id,
        "top_k": top_k,
        "messages": [
            SystemMessage(content=AGENT_SYSTEM_PROMPT),
            HumanMessage(
                content=(
                    f"故障标题：{request.title.strip()}\n"
                    f"故障内容：{request.content.strip()}\n"
                    f"知识库 ID：{request.knowledge_base_id}"
                )
            ),
        ],
        "observations": [],
        "steps": [],
        "iteration": 0,
        "max_iterations": max_iterations,
        "status": "running",
        "error": None,
        "report": None,
    }


def _response_from_state(state: AgentState) -> RunResponse:
    """Convert the final graph state to the public API response."""

    return RunResponse(
        run_id=state["run_id"],
        status=state["status"],
        report=state["report"],
        observations=state["observations"],
        steps=state["steps"],
        error=state["error"],
    )


def execute_incident(
    db: Session,
    *,
    user: UserPublic,
    request: IncidentAnalyzeRequest,
    access_token: str,
    settings: Settings | None = None,
    model: Any | None = None,
    rag_gateway: RagGateway | None = None,
) -> RunResponse:
    """Run the Graph and persist both success and controlled failure states.

    ``model`` and ``rag_gateway`` are injectable for deterministic tests. In
    production they default to DeepSeek and the DevAtlas HTTP adapter.
    """

    settings = settings or get_settings()
    effective_top_k = request.top_k or settings.default_top_k
    run_id = str(uuid4())
    run: AgentRun = create_run(
        db,
        run_id=run_id,
        owner_user_id=user.id,
        title=request.title,
        input_content=request.content,
        knowledge_base_id=request.knowledge_base_id,
        model_name=settings.model,
        max_iterations=settings.max_iterations,
    )

    owned_gateway = rag_gateway is None
    gateway = rag_gateway or HttpRagGateway(
        settings.devatlas_base_url,
        settings.devatlas_timeout_seconds,
    )
    state = _initial_state(
        run_id=run_id,
        user=user,
        request=request,
        top_k=effective_top_k,
        max_iterations=settings.max_iterations,
    )

    try:
        graph = build_graph_with_gateway(
            model=model or create_chat_model(settings),
            rag_gateway=gateway,
            knowledge_base_id=request.knowledge_base_id,
            top_k=effective_top_k,
            access_token=access_token,
            max_iterations=settings.max_iterations,
        )
        final_state = graph.invoke(state)
    except Exception:
        final_state = {
            **state,
            "status": "degraded",
            "error": "Agent 执行失败，请检查模型或外部服务状态",
        }
    finally:
        if owned_gateway and hasattr(gateway, "close"):
            gateway.close()

    append_steps(db, run, final_state["steps"])
    finish_run(
        db,
        run,
        status=final_state["status"],
        iteration=final_state["iteration"],
        observations=final_state["observations"],
        report=final_state["report"],
        error=final_state["error"],
    )
    return _response_from_state(final_state)
