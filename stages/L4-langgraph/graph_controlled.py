from __future__ import annotations

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
from langgraph.prebuilt import ToolNode, tools_condition

# 最大模型请求次数
MAX_ITERATIONS = 3


@tool
def get_service_status(service_name: str) -> dict[str, object]:
    """查询指定服务的模拟运行状态。"""

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

    return statuses.get(
        service_name,
        {
            "status": "unknown",
            "error_count": None,
        },
    )


class AgentState(TypedDict):
    """图中节点之间传递的状态。"""

    # 消息历史
    messages: Annotated[list[BaseMessage], add_messages]
    # 模型请求轮数
    iteration: int
    # 整个图目前的状态
    status: str
    # 错误信息,异常或保护性结束的原因
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

    def agent_node(
        state: AgentState,
    ) -> dict[str, object]:
        """请求模型，并增加模型请求轮数。"""

        # 增加模型请求轮数
        current_iteration = state["iteration"] + 1

        print(
            f"\n===== 第 {current_iteration} 次模型请求 ====="
        )

        response = model_with_tools.invoke(state["messages"])

        print("模型文本：", response.content or "没有普通文本")
        print("工具调用：", response.tool_calls)

        return {
            "messages": [response],
            "iteration": current_iteration,
        }

    # 定义limit节点,处理达到最大模型请求次数的节点
    def limit_node(
        state: AgentState,
    ) -> dict[str, str]:
        """达到最大模型请求次数后的结束节点。"""

        print(
            f"\n达到最大模型请求次数 {MAX_ITERATIONS}，"
            "停止继续调用工具。"
        )

        return {
            "status": "max_iterations",
            "error": (
                f"达到最大模型请求次数：{MAX_ITERATIONS}"
            ),
        }

    # 定义路由节点,根据agent节点的返回结果，判断是否调用工具
    def route_after_agent(state: AgentState) -> str:
        """决定 agent 执行后下一步去哪里。"""
    
        # [-1]表示拿到最后一条消息
        last_message = state["messages"][-1]

        # isinstance(x, AIMessage) 的意思是 判断 x 是否是 AIMessage 类型的对象
        if not isinstance(last_message, AIMessage):
            return "end"

        # 没有工具调用，说明模型已经给出最终回答。
        if not last_message.tool_calls:
            return "end"

        # 还有工具调用，但已经达到上限。
        if state["iteration"] >= MAX_ITERATIONS:
            return "limit"

        # 还有工具调用，且没有达到上限。
        return "tools"

    graph_builder = StateGraph(AgentState)

    graph_builder.add_node("agent", agent_node)
    graph_builder.add_node("tools", ToolNode(tools))
    graph_builder.add_node("limit", limit_node)

    graph_builder.add_edge(START, "agent")

    graph_builder.add_conditional_edges(
        "agent",
        route_after_agent,
        {
            "tools": "tools",
            "limit": "limit",
            "end": END,
        },
    )

    graph_builder.add_edge("tools", "agent")
    graph_builder.add_edge("limit", END)

    return graph_builder.compile()


def main() -> None:
    graph = build_graph()

    initial_state: AgentState = {
        "messages": [
            SystemMessage(
                content=(
                    "你是故障分析助手。"
                    "如果需要服务状态，请调用 get_service_status。"
                    "只能提供排查建议，不能执行命令。"
                )
            ),
            HumanMessage(
                content=(
                    "订单服务返回 502，"
                    "请检查 order-service 的当前状态。"
                )
            ),
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

    print("\n===== 最后一条消息 =====")
    print(final_state["messages"][-1].content)


if __name__ == "__main__":
    main()