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
from langgraph.prebuilt import ToolNode, tools_condition


# 将函数包装成工具对象，自动读取工具名，参数和描述
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


# State 是图运行时持续携带的共享数据
class AgentState(TypedDict):
    """LangGraph 在节点之间传递的状态。"""

    # messages 是一个消息列表，用于存储对话历史；
    # add_messages 标注确保在节点之间传递时，消息会被自动添加到列表中，不会覆盖之前的列表，采取的是追加合并
    messages: Annotated[list[BaseMessage], add_messages]


# 创建模型实例
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

# 构建 LangGraph 图
def build_graph():
    # 绑定工具到模型实例
    tools = [get_service_status]
    model_with_tools = create_model().bind_tools(tools)

    # 定义agent节点
    def agent_node(state: AgentState) -> dict[str, list[BaseMessage]]:
        """调用模型，由模型决定调用工具或给出最终回答。"""

        response = model_with_tools.invoke(state["messages"])

        print("\n[agent 节点]")
        print("模型文本：", response.content or "没有普通文本")
        print("工具调用：", response.tool_calls)

        return {"messages": [response]}

    # 创建图对象，创建一张 State 类型为 AgentState 的流程图
    graph_builder = StateGraph(AgentState)

    # 注册节点agent和tools
    graph_builder.add_node("agent", agent_node)
    # 执行逻辑用LangGraph内置的ToolNode(tools) 自动完成读取最后一条AIMessage的tool_calls
    # 然后根据工具名找到工具，执行工具，生成ToolMessage，返回{"messages": [ToolMessage]}
    graph_builder.add_node("tools", ToolNode(tools))

    # 添加边,START是LangGraph的内置起点
    graph_builder.add_edge(START, "agent")

    # 添加条件边，根据agent节点的返回结果，判断是否调用工具
    graph_builder.add_conditional_edges(
        # 每次agent执行完，它检查最后一条 AIMessage 是否含有 tool_calls
        # 有tools，跳到下面的tools节点，否则跳到END节点
        "agent",
        tools_condition,
        {
            "tools": "tools",
            END: END,
        },
    )
    # tools执行完，无条件返回agent节点，相当于ReAct的循环流程
    graph_builder.add_edge("tools", "agent")

    # compile() 把图配置转换成可运行的 graph 对象
    return graph_builder.compile()


def main() -> None:
    # 构建图
    graph = build_graph()

    # 初始state
    initial_state = {
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
        ]
    }

    # 从START节点开始执行图，直到END节点,返回最终的state
    final_state = graph.invoke(initial_state)

    print("\n===== 最终消息历史 =====")

    for index, message in enumerate(
        final_state["messages"],
        start=1,
    ):
        print(f"\n{index}. {type(message).__name__}")

        if isinstance(message, AIMessage):
            print("文本：", message.content or "没有普通文本")
            print("工具调用：", message.tool_calls)
        else:
            print("内容：", message.content)

    final_message = final_state["messages"][-1]

    print("\n===== 最终回答 =====")
    print(final_message.content)

    print("\n===== 图结构 =====")
    print(
        json.dumps(
            graph.get_graph().to_json(),
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()