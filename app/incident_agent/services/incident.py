"""Application service that executes and persists one Agent run."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from langchain_core.messages import HumanMessage, SystemMessage
from sqlalchemy.orm import Session

from ..core.config import Settings, get_settings
from ..core.redaction import redact_for_model
from ..core.statuses import RunStatus
from ..graph.state import AgentState
from ..graph.workflow import build_graph_with_gateway
from ..models import AgentRun
from ..schemas.auth import UserPublic
from ..schemas.incident import IncidentAnalyzeRequest, RunResponse
from .authorizer import (
    HttpKnowledgeBaseAuthorizer,
    KnowledgeBaseAuthorizationError,
    KnowledgeBaseAuthorizer,
)
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


class KnowledgeBaseAccessError(Exception):
    """Raised when the requested knowledge base fails the pre-flight check.

    Carries the safe, DevAtlas-shaped status code so the router can answer
    without a run ever being created.
    """

    def __init__(self, exc: KnowledgeBaseAuthorizationError):
        super().__init__(exc.message)
        self.status_code = exc.status_code
        self.error_code = exc.error_code
        self.message = exc.message


def _initial_state(
    *,
    run_id: str,
    user: UserPublic,
    request: IncidentAnalyzeRequest,
    title: str,
    content: str,
    top_k: int,
    max_iterations: int,
) -> AgentState:
    """Build the first state without placing the JWT into it.

    ``title`` and ``content`` must already be redacted: the Agent no longer
    keeps the raw incident log anywhere, so the model context, the persisted
    rows and the API response all carry the same masked text.
    """

    return {
        "run_id": run_id,
        "owner_user_id": user.id,
        "title": title,
        "input_content": content,
        "knowledge_base_id": request.knowledge_base_id,
        "top_k": top_k,
        "messages": [
            SystemMessage(content=AGENT_SYSTEM_PROMPT),
            HumanMessage(
                content=(
                    f"故障标题：{title}\n"
                    f"故障内容：{content}\n"
                    f"知识库 ID：{request.knowledge_base_id}"
                )
            ),
        ],
        "observations": [],
        "steps": [],
        "iteration": 0,
        "max_iterations": max_iterations,
        "status": RunStatus.RUNNING,
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
    knowledge_base_authorizer: KnowledgeBaseAuthorizer | None = None,
) -> RunResponse:
    """Run the Graph and persist both success and controlled failure states.

    ``model``, ``rag_gateway`` and ``knowledge_base_authorizer`` are injectable
    for deterministic tests. In production they default to DeepSeek and the
    DevAtlas HTTP adapters.

    The knowledge-base ownership check runs *before* ``create_run``: a request
    for a missing or foreign knowledge base must not leave a persisted run
    behind, and it must not depend on the model deciding to call the retrieval
    tool.

    Incident input is redacted once, here, before it is handed to the model or
    written to MySQL. The raw log therefore never reaches the graph state, the
    model context, the database or the response.
    """

    settings = settings or get_settings()
    effective_top_k = request.top_k or settings.default_top_k
    redacted_title = redact_for_model(request.title.strip(), max_length=200)
    redacted_content = redact_for_model(request.content.strip())

    owned_authorizer = knowledge_base_authorizer is None
    authorizer: KnowledgeBaseAuthorizer = (
        knowledge_base_authorizer
        or HttpKnowledgeBaseAuthorizer(
            settings.devatlas_base_url,
            settings.devatlas_timeout_seconds,
        )
    )
    run_id = str(uuid4())
    owned_gateway = rag_gateway is None
    gateway: RagGateway | None = None

    try:
        try:
            authorizer.ensure_access(
                knowledge_base_id=request.knowledge_base_id,
                access_token=access_token,
            )
        except KnowledgeBaseAuthorizationError as exc:
            raise KnowledgeBaseAccessError(exc) from exc

        run: AgentRun = create_run(
            db,
            run_id=run_id,
            owner_user_id=user.id,
            title=redacted_title,
            input_content=redacted_content,
            knowledge_base_id=request.knowledge_base_id,
            model_name=settings.model,
            max_iterations=settings.max_iterations,
        )

        gateway = rag_gateway or HttpRagGateway(
            settings.devatlas_base_url,
            settings.devatlas_timeout_seconds,
        )
        state = _initial_state(
            run_id=run_id,
            user=user,
            request=request,
            title=redacted_title,
            content=redacted_content,
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
                "status": RunStatus.DEGRADED,
                "error": "Agent 执行失败，请检查模型或外部服务状态",
            }
    finally:
        if owned_authorizer and hasattr(authorizer, "close"):
            authorizer.close()
        if owned_gateway and gateway is not None and hasattr(gateway, "close"):
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
