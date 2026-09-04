from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Annotated, Any, TypedDict

from dotenv import load_dotenv
from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from langchain_core.tools import tool
from langchain_openai import ChatOpenAI
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode


L3_TOOLS_DIR = Path(__file__).resolve().parents[1] / "L3-tools"

if str(L3_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(L3_TOOLS_DIR))

from report_models import IncidentReport
from tools import run_tool as run_l3_tool


MAX_ITERATIONS = 4


@tool
def analyze_log(log_text: str) -> dict[str, Any]:
    """从故障日志中提取 502、超时、数据库错误等信号。"""

    result = run_l3_tool(
        "analyze_log",
        json.dumps(
            {"log_text": log_text},
            ensure_ascii=False,
        ),
    )

    return result.model_dump()


@tool
def search_knowledge(
    query: str,
    knowledge_base_id: int,
    top_k: int = 3,
) -> dict[str, Any]:
    """在指定知识库中检索故障相关文档片段。"""

    result = run_l3_tool(
        "search_knowledge",
        json.dumps(
            {
                "query": query,
                "knowledge_base_id": knowledge_base_id,
                "top_k": top_k,
            },
            ensure_ascii=False,
        ),
    )

    return result.model_dump()


@tool
def get_service_status(service_name: str) -> dict[str, Any]:
    """查询指定服务当前的模拟运行状态。"""

    result = run_l3_tool(
        "get_service_status",
        json.dumps(
            {"service_name": service_name},
            ensure_ascii=False,
        ),
    )

    return result.model_dump()


class AgentState(TypedDict):
    """Incident Agent 在图节点之间共享的状态。"""

    messages: Annotated[list[BaseMessage], add_messages]
    observations: list[dict[str, Any]]
    steps: list[dict[str, Any]]
    iteration: int
    status: str
    error: str | None
    report: dict[str, Any] | None


def create_model() -> ChatOpenAI:
    load_dotenv()

    api_key = os.getenv("DEEPSEEK_API_KEY") or os.getenv("OPENAI_API_KEY")

    if not api_key:
        raise RuntimeError("没有找到 API Key，请检查本机 .env 配置。")

    return ChatOpenAI(
        model=os.getenv("DEEPSEEK_MODEL", "deepseek-chat"),
        api_key=api_key,
        base_url=os.getenv(
            "DEEPSEEK_BASE_URL",
            "https://api.deepseek.com",
        ),
        temperature=0.1,
    )


def build_graph():
    tools = [
        analyze_log,
        search_knowledge,
        get_service_status,
    ]

    base_model = create_model()
    model_with_tools = base_model.bind_tools(tools)
    report_model = base_model

    def agent_node(state: AgentState) -> dict[str, object]:
        """请求模型，由模型决定是否调用工具。"""

        current_iteration = state["iteration"] + 1

        print(f"\n===== 第 {current_iteration} 次模型请求 =====")

        response = model_with_tools.invoke(state["messages"])

        print("模型文本：", response.content or "没有普通文本")
        print("工具调用：", response.tool_calls)

        return {
            "messages": [response],
            "iteration": current_iteration,
        }

    def observe_tools_node(state: AgentState) -> dict[str, object]:
        """读取新增 ToolMessage，记录事实与执行轨迹。"""

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
            except json.JSONDecodeError:
                result = {
                    "ok": False,
                    "error_code": "INVALID_TOOL_RESULT",
                    "error": "工具结果不是合法 JSON",
                }

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
                    "action": "observe_tool_result",
                    "tool_name": tool_name,
                    "ok": result.get("ok"),
                }
            )

            if not result.get("ok"):
                has_failure = True
                latest_error = result.get(
                    "error",
                    "工具执行失败或没有有效结果",
                )

        print(f"本轮新增工具结果：{len(new_tool_messages)} 条")

        return {
            "observations": observations,
            "steps": steps,
            "status": "tool_failed" if has_failure else state["status"],
            "error": latest_error,
        }

    def report_node(state: AgentState) -> dict[str, object]:
        """依据对话和工具事实，生成并校验结构化故障报告。"""

        # 整理消息
        message_summary = [
            {
                "type": type(message).__name__,
                "content": message.content,
            }
            for message in state["messages"]
        ]

        report_messages = [
            SystemMessage(
                content=(
                    "你是 Incident Agent 的报告生成节点。"
                    "只能依据用户输入和工具事实生成报告，不得编造证据。"
                    "证据不足时必须在 summary 或 possible_causes 中说明。"
                    "只返回合法 JSON，不要输出 Markdown 代码块。"
                    "JSON 必须包含以下字段："
                    "summary、category、evidence、possible_causes、"
                    "troubleshooting_steps、references、confidence。"
                    "category 只能是 database、network、application、"
                    "dependency、unknown。"
                    "confidence 只能是 low、medium、high。"
                    "evidence 必须是对象列表，每个对象必须有 source 和 detail。"
                )
            ),
            HumanMessage(
                content=(
                    "对话消息：\n"
                    f"{json.dumps(message_summary, ensure_ascii=False, indent=2)}"
                    "\n\n工具观察结果：\n"
                    f"{json.dumps(state['observations'], ensure_ascii=False, indent=2)}"
                )
            ),
        ]

        response = report_model.invoke(report_messages)

        print("\n[report 节点]")
        print("模型原始报告：")
        print(response.content)

        raw_report = response.content

        if not isinstance(raw_report, str):
            raw_report = json.dumps(raw_report, ensure_ascii=False)

        try:
            data = json.loads(raw_report)
            report = IncidentReport.model_validate(data)

            return {
                "report": report.model_dump(),
                "status": "completed",
                "error": None,
            }

        except json.JSONDecodeError as exc:
            return {
                "status": "degraded",
                "error": f"报告不是合法 JSON：{exc}",
            }

        except Exception as exc:
            return {
                "status": "degraded",
                "error": f"报告结构校验失败：{exc}",
            }

    def degrade_node(state: AgentState) -> dict[str, str]:
        """工具或报告失败时，降级结束。"""

        error = state["error"] or "执行失败或没有有效结果"

        print(f"\n降级结束：{error}")

        return {
            "status": "degraded",
            "error": error,
        }

    def limit_node(state: AgentState) -> dict[str, str]:
        """达到最大模型请求次数时，保护性结束。"""

        error = f"达到最大模型请求次数：{MAX_ITERATIONS}"

        print(f"\n{error}，停止继续调用工具。")

        return {
            "status": "max_iterations",
            "error": error,
        }

    def route_after_agent(state: AgentState) -> str:
        """决定模型节点后的下一条边。"""

        last_message = state["messages"][-1]

        if not isinstance(last_message, AIMessage):
            return "report"

        if not last_message.tool_calls:
            return "report"

        if state["iteration"] >= MAX_ITERATIONS:
            return "limit"

        return "tools"

    def route_after_observe(state: AgentState) -> str:
        """工具执行后，决定继续模型还是降级结束。"""

        if state["status"] == "tool_failed":
            return "degrade"

        return "agent"

    graph_builder = StateGraph(AgentState)

    graph_builder.add_node("agent", agent_node)
    graph_builder.add_node("tools", ToolNode(tools))
    graph_builder.add_node("observe", observe_tools_node)
    graph_builder.add_node("report", report_node)
    graph_builder.add_node("degrade", degrade_node)
    graph_builder.add_node("limit", limit_node)

    graph_builder.add_edge(START, "agent")

    graph_builder.add_conditional_edges(
        "agent",
        route_after_agent,
        {
            "tools": "tools",
            "report": "report",
            "limit": "limit",
        },
    )

    graph_builder.add_edge("tools", "observe")

    graph_builder.add_conditional_edges(
        "observe",
        route_after_observe,
        {
            "agent": "agent",
            "degrade": "degrade",
        },
    )

    graph_builder.add_edge("report", END)
    graph_builder.add_edge("degrade", END)
    graph_builder.add_edge("limit", END)

    return graph_builder.compile()


def run_case(
    graph,
    case_name: str,
    user_content: str,
) -> None:
    print(f"\n\n########## {case_name} ##########")

    initial_state: AgentState = {
        "messages": [
            SystemMessage(
                content=(
                    "你是 Incident Agent。"
                    "请根据故障信息选择合适工具。"
                    "工具失败时不要继续调用工具，应当降级结束。"
                    "只能提供排查建议，不能执行命令。"
                )
            ),
            HumanMessage(content=user_content),
        ],
        "observations": [],
        "steps": [],
        "iteration": 0,
        "status": "running",
        "error": None,
        "report": None,
    }

    final_state = graph.invoke(initial_state)

    print("\n===== 最终状态 =====")
    print("iteration：", final_state["iteration"])
    print("status：", final_state["status"])
    print("error：", final_state["error"])

    print("\n===== observations =====")
    print(
        json.dumps(
            final_state["observations"],
            ensure_ascii=False,
            indent=2,
        )
    )

    print("\n===== steps =====")
    print(
        json.dumps(
            final_state["steps"],
            ensure_ascii=False,
            indent=2,
        )
    )

    print("\n===== 最终报告 =====")

    if final_state["report"] is None:
        print("没有生成报告。")
    else:
        print(
            json.dumps(
                final_state["report"],
                ensure_ascii=False,
                indent=2,
            )
        )


def main() -> None:
    graph = build_graph()

    run_case(
        graph,
        "正常路径",
        (
            "订单服务返回 502，"
            "日志显示 order-service mysql connection timeout。"
            "知识库 ID 是 1。"
        ),
    )

    run_case(
        graph,
        "未知服务降级路径",
        (
            "gateway 返回 502，"
            "请检查 gateway 当前状态。"
        ),
    )


if __name__ == "__main__":
    main()