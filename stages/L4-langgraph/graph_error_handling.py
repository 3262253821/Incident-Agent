from __future__ import annotations

import json
import os
from typing import Annotated, TypedDict

from dotenv import load_dotenv
from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
)
from langchain_core.tools import tool
from langchain_openai import ChatOpenAI
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode

MAX_ITERATIONS = 3


@tool
def get_service_status(service_name: str) -> dict[str, object]:
    """查询指定服务的模拟运行状态；未知服务返回失败结果。"""

    statuses = {
        "order-service": {
            "status": "degraded",
            "error_count": 27,
        },
        "user-service": {
            "status": "healthy",
            "error_count": 0,
        },
    }

    service = statuses.get(service_name)

    if service is None:
        return {
            "ok": False,
            "error_code": "UNKNOWN_SERVICE",
            "error": f"未知服务：{service_name}",
        }

    return {
        "ok": True,
        "data": {
            "service_name": service_name,
            **service,
        },
    }


class AgentState(TypedDict):
    """图中节点之间传递的状态。"""

    messages: Annotated[list[BaseMessage], add_messages]
    iteration: int
    status: str
    error: str | None


def create_model() -> ChatOpenAI:
    load_dotenv()

    api_key = os.getenv("DEEPSEEK_API_KEY") or os.getenv("OPENAI_API_KEY")

    if not api_key:
        raise RuntimeError(
            "没有找到 API Key，请检查本机 .env 配置。"
        )

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
    tools = [get_service_status]
    model_with_tools = create_model().bind_tools(tools)

    def agent_node(state: AgentState) -> dict[str, object]:
        """请求模型，并更新模型请求轮数。"""

        current_iteration = state["iteration"] + 1

        print(f"\n===== 第 {current_iteration} 次模型请求 =====")

        response = model_with_tools.invoke(state["messages"])

        print("模型文本：", response.content or "没有普通文本")
        print("工具调用：", response.tool_calls)

        return {
            "messages": [response],
            "iteration": current_iteration,
        }

    def complete_node(state: AgentState) -> dict[str, str | None]:
        """模型不再调用工具时，标记正常完成。"""

        print("\n模型不再请求工具，正常完成。")

        return {
            "status": "completed",
            "error": None,
        }

    def degrade_node(state: AgentState) -> dict[str, str]:
        """工具没有返回有效事实时，标记降级结束。"""

        last_message = state["messages"][-1]
        error = "工具执行失败或没有有效结果"

        if hasattr(last_message, "content"):
            try:
                tool_result = json.loads(last_message.content)
                error = tool_result.get("error", error)
            except json.JSONDecodeError:
                pass

        print(f"\n工具失败，降级结束：{error}")

        return {
            "status": "degraded",
            "error": error,
        }

    def limit_node(state: AgentState) -> dict[str, str]:
        """模型循环超过上限时，标记保护性结束。"""

        error = f"达到最大模型请求次数：{MAX_ITERATIONS}"

        print(f"\n{error}，停止继续调用工具。")

        return {
            "status": "max_iterations",
            "error": error,
        }

    def route_after_agent(state: AgentState) -> str:
        """agent 执行后，决定去完成、工具或上限节点。"""

        last_message = state["messages"][-1]

        if not isinstance(last_message, AIMessage):
            return "complete"

        if not last_message.tool_calls:
            return "complete"

        if state["iteration"] >= MAX_ITERATIONS:
            return "limit"

        return "tools"

    def route_after_tools(state: AgentState) -> str:
        """tools 执行后，根据最后一条 ToolMessage 的结果决定下一步。"""

        last_message = state["messages"][-1]

        try:
            tool_result = json.loads(last_message.content)
        except json.JSONDecodeError:
            return "degrade"

        if not tool_result.get("ok"):
            return "degrade"

        return "agent"

    graph_builder = StateGraph(AgentState)

    graph_builder.add_node("agent", agent_node)
    graph_builder.add_node("tools", ToolNode(tools))
    graph_builder.add_node("complete", complete_node)
    graph_builder.add_node("degrade", degrade_node)
    graph_builder.add_node("limit", limit_node)

    graph_builder.add_edge(START, "agent")

    graph_builder.add_conditional_edges(
        "agent",
        route_after_agent,
        {
            "tools": "tools",
            "complete": "complete",
            "limit": "limit",
        },
    )

    graph_builder.add_conditional_edges(
        "tools",
        route_after_tools,
        {
            "agent": "agent",
            "degrade": "degrade",
        },
    )

    graph_builder.add_edge("complete", END)
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
                    "你是故障分析助手。"
                    "需要服务状态时，调用 get_service_status。"
                    "工具失败或没有有效结果时，不要继续调用工具，"
                    "应直接给出证据不足的说明。"
                    "只能提供排查建议，不能执行命令。"
                )
            ),
            HumanMessage(content=user_content),
        ],
        "iteration": 0,
        "status": "running",
        "error": None,
    }

    final_state = graph.invoke(initial_state)

    print("\n===== 最终状态 =====")
    print("iteration：", final_state["iteration"])
    print("status：", final_state["status"])
    print("error：", final_state["error"])
    print("最后消息：")
    print(final_state["messages"][-1].content)


def main() -> None:
    graph = build_graph()

    run_case(
        graph,
        "正常路径",
        "订单服务返回 502，请检查 order-service 的当前状态。",
    )

    run_case(
        graph,
        "未知服务降级路径",
        "gateway 返回 502，请检查 gateway 的当前状态。",
    )


if __name__ == "__main__":
    main()