"""LangGraph nodes and routing functions for the Incident Agent."""

from __future__ import annotations

import json
from typing import Any, Callable, Sequence

from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from langchain_core.tools import BaseTool
from langgraph.prebuilt import ToolNode
from pydantic import ValidationError

from ..core.redaction import redact_for_model, redact_payload, redact_text
from ..schemas.incident import IncidentReport
from ..schemas.tool import ToolResult
from .state import AgentState

REPORT_SYSTEM_PROMPT = """
你是 Incident Agent 的结构化报告节点。
只能依据用户输入和工具事实生成报告，不得编造证据。
证据不足时必须降低 confidence，并在 summary 或 possible_causes 中说明。
只返回合法 JSON，不要输出 Markdown 代码块或额外解释。
JSON 必须包含 summary、category、evidence、possible_causes、
troubleshooting_steps、references、confidence 字段。
category 只能是 database、network、application、dependency、unknown。
confidence 只能是 low、medium、high。
evidence 必须是对象列表，每个对象必须有 source 和 detail。
source 只能使用以下业务来源值，不能填写工具函数名：
analyze_log → fault_log；search_knowledge → knowledge_base；
get_service_status → service_status；工具失败 → tool_error。
""".strip()


EVIDENCE_SOURCE_ALIASES = {
    "analyze_log": "fault_log",
    "analyze_log_tool": "fault_log",
    "search_knowledge": "knowledge_base",
    "get_service_status": "service_status",
    "get_service_status_tool": "service_status",
}


def _message_summary(messages: Sequence[BaseMessage]) -> list[dict[str, Any]]:
    """Convert LangChain messages into JSON-safe report context."""

    result: list[dict[str, Any]] = []
    for message in messages:
        item: dict[str, Any] = {
            "type": type(message).__name__,
            "content": message.content,
        }
        if isinstance(message, AIMessage) and message.tool_calls:
            item["tool_calls"] = [
                {
                    "name": call.get("name"),
                    "args": call.get("args", {}),
                    "id": call.get("id"),
                }
                for call in message.tool_calls
            ]
        if isinstance(message, ToolMessage):
            item["tool_call_id"] = message.tool_call_id
            item["name"] = message.name
        result.append(item)
    return result


def parse_report(raw_report: Any) -> IncidentReport:
    """Parse JSON and validate the final report contract."""

    if not isinstance(raw_report, str):
        raw_report = json.dumps(raw_report, ensure_ascii=False)
    data = json.loads(raw_report)
    if isinstance(data, dict) and isinstance(data.get("evidence"), list):
        # 模型有时会把工具函数名当成业务来源；只归一化白名单别名，
        # 其他值仍交给 Pydantic 拒绝，避免放宽证据来源约束。
        normalized_evidence = []
        for item in data["evidence"]:
            if isinstance(item, dict):
                normalized_item = dict(item)
                source = normalized_item.get("source")
                normalized_item["source"] = EVIDENCE_SOURCE_ALIASES.get(
                    source,
                    source,
                )
                normalized_evidence.append(normalized_item)
            else:
                normalized_evidence.append(item)
        data = {**data, "evidence": normalized_evidence}
    return IncidentReport.model_validate(data)


def _fallback_tool_result() -> dict[str, Any]:
    """The unified result used when a tool payload cannot be parsed."""

    return ToolResult(
        ok=False,
        error_code="INVALID_TOOL_RESULT",
        error="工具结果不是合法的统一结果结构",
    ).model_dump()


def _redact_report(report: IncidentReport) -> dict[str, Any]:
    """Mask credentials in every free-text field before persistence."""

    data = report.model_dump()
    return {
        **data,
        "summary": redact_text(data["summary"]),
        "possible_causes": [
            redact_text(item) for item in data["possible_causes"]
        ],
        "troubleshooting_steps": [
            redact_text(item) for item in data["troubleshooting_steps"]
        ],
        "references": [redact_text(item) for item in data["references"]],
        "evidence": redact_payload(data["evidence"]),
    }


def _redacting_tool_node(tools: Sequence[BaseTool]) -> Any:
    """Wrap ``ToolNode`` so raw tool output never re-enters the model context.

    ``ToolNode`` copies the tool's return value into ``ToolMessage.content``.
    Masking here keeps the model, ``observe``, the report node and the database
    all working on the same already-masked text.
    """

    base_node = ToolNode(list(tools))

    def redacting_node(state: AgentState) -> dict[str, Any]:
        result = base_node.invoke(state)
        messages = [
            message.model_copy(
                update={"content": redact_text(str(message.content))}
            )
            if isinstance(message, ToolMessage)
            else message
            for message in result.get("messages", [])
        ]
        return {**result, "messages": messages}

    return redacting_node


def make_agent_node(model: Any, tools: Sequence[BaseTool]) -> Callable[[AgentState], dict[str, Any]]:
    """Create a node that asks the model whether tools are needed."""

    model_with_tools = model.bind_tools(list(tools))

    def agent_node(state: AgentState) -> dict[str, Any]:
        current_iteration = state["iteration"] + 1
        response = model_with_tools.invoke(state["messages"])
        if getattr(response, "content", None):
            response = response.model_copy(
                update={
                    "content": redact_for_model(str(response.content)),
                }
            )
        if getattr(response, "tool_calls", None):
            # The model may echo a credential it saw in the log straight back
            # into a tool argument. Those arguments are replayed into the
            # report context by ``_message_summary``, so they must be masked
            # before the message enters AgentState.
            response = response.model_copy(
                update={
                    "tool_calls": [
                        {
                            **call,
                            "args": redact_payload(call.get("args", {})),
                        }
                        for call in response.tool_calls
                    ]
                }
            )
        steps = list(state["steps"])
        steps.append(
            {
                "iteration": current_iteration,
                "node": "agent",
                "action": "model_request",
                "tool_call_count": len(getattr(response, "tool_calls", []) or []),
                "status": "success",
            }
        )
        return {
            "messages": [response],
            "iteration": current_iteration,
            "steps": steps,
        }

    return agent_node


def make_observe_node() -> Callable[[AgentState], dict[str, Any]]:
    """Create a node that turns new ToolMessages into business observations."""

    def observe_tools_node(state: AgentState) -> dict[str, Any]:
        all_tool_messages = [
            message
            for message in state["messages"]
            if isinstance(message, ToolMessage)
        ]
        processed_count = len(state["observations"])
        new_tool_messages = all_tool_messages[processed_count:]

        observations = list(state["observations"])
        steps = list(state["steps"])
        has_failure = False
        latest_error: str | None = None

        for message in new_tool_messages:
            try:
                result = json.loads(message.content)
                # 工具结果同样可能带凭据（例如用户日志原样回显），
                # 落库前统一脱敏，保证 observations 与 messages 一致。
                result = redact_payload(
                    ToolResult.model_validate(result).model_dump()
                )
            except (json.JSONDecodeError, TypeError, ValidationError):
                result = _fallback_tool_result()

            tool_name = getattr(message, "name", None) or "unknown_tool"
            observations.append(
                {
                    "iteration": state["iteration"],
                    "tool_name": tool_name,
                    "tool_call_id": message.tool_call_id,
                    "result": result,
                }
            )
            steps.append(
                {
                    "iteration": state["iteration"],
                    "node": "observe",
                    "action": "observe_tool_result",
                    "tool_name": tool_name,
                    "tool_call_id": message.tool_call_id,
                    "ok": result["ok"],
                    "status": "success" if result["ok"] else "failed",
                    "error_code": result["error_code"],
                }
            )

            if not result["ok"]:
                has_failure = True
                latest_error = result["error"] or "工具执行失败或没有有效结果"

        return {
            "observations": observations,
            "steps": steps,
            "status": "tool_failed" if has_failure else state["status"],
            "error": latest_error,
        }

    return observe_tools_node


def make_report_node(report_model: Any) -> Callable[[AgentState], dict[str, Any]]:
    """Create a node that generates and validates an IncidentReport."""

    def report_node(state: AgentState) -> dict[str, Any]:
        report_messages = [
            SystemMessage(content=REPORT_SYSTEM_PROMPT),
            HumanMessage(
                content=(
                    "对话消息：\n"
                    f"{json.dumps(_message_summary(state['messages']), ensure_ascii=False, indent=2)}"
                    "\n\n工具观察结果：\n"
                    f"{json.dumps(state['observations'], ensure_ascii=False, indent=2)}"
                )
            ),
        ]

        steps = list(state["steps"])
        try:
            response = report_model.invoke(report_messages)
            report = parse_report(response.content)
        except json.JSONDecodeError as exc:
            steps.append(
                {
                    "iteration": state["iteration"],
                    "node": "report",
                    "action": "validate_report",
                    "status": "failed",
                    "error_code": "INVALID_JSON",
                }
            )
            return {
                "steps": steps,
                "status": "report_validation_failed",
                "error": f"报告不是合法 JSON：{exc}",
            }
        except (ValidationError, TypeError, ValueError) as exc:
            steps.append(
                {
                    "iteration": state["iteration"],
                    "node": "report",
                    "action": "validate_report",
                    "status": "failed",
                    "error_code": "INVALID_REPORT",
                }
            )
            return {
                "steps": steps,
                "status": "report_validation_failed",
                "error": f"报告结构校验失败：{exc}",
            }

        steps.append(
            {
                "iteration": state["iteration"],
                "node": "report",
                "action": "validate_report",
                "status": "success",
            }
        )
        return {
            "report": _redact_report(report),
            "steps": steps,
            "status": "completed",
            "error": None,
        }

    return report_node


def degrade_node(state: AgentState) -> dict[str, Any]:
    """End with a readable degraded status after a tool/report failure."""

    steps = list(state["steps"])
    steps.append(
        {
            "iteration": state["iteration"],
            "node": "degrade",
            "action": "finish_degraded",
            "status": "degraded",
        }
    )
    return {
        "steps": steps,
        "status": "degraded",
        "error": state["error"] or "执行失败或没有有效结果",
    }


def limit_node(
    state: AgentState,
    max_iterations: int | None = None,
) -> dict[str, Any]:
    """End safely once the model-request budget is exhausted."""

    effective_max_iterations = max_iterations or state.get("max_iterations")
    if effective_max_iterations is None:
        raise ValueError("缺少 max_iterations 配置")

    steps = list(state["steps"])
    steps.append(
        {
            "iteration": state["iteration"],
            "node": "limit",
            "action": "stop_at_max_iterations",
            "status": "max_iterations",
        }
    )
    return {
        "steps": steps,
        "status": "max_iterations",
        "error": f"达到最大模型请求次数：{effective_max_iterations}",
    }


def route_after_agent(
    state: AgentState,
    max_iterations: int | None = None,
) -> str:
    """Route an AI response to tools, report, or the iteration guard."""

    effective_max_iterations = max_iterations or state.get("max_iterations")
    if effective_max_iterations is None:
        raise ValueError("缺少 max_iterations 配置")

    last_message = state["messages"][-1]
    if not isinstance(last_message, AIMessage) or not last_message.tool_calls:
        return "report"
    if state["iteration"] >= effective_max_iterations:
        return "limit"
    return "tools"


def route_after_observe(state: AgentState) -> str:
    """Stop on the first failed tool result; otherwise ask the model again."""

    return "degrade" if state["status"] == "tool_failed" else "agent"
