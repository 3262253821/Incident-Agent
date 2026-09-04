from __future__ import annotations

import json
import os

from dotenv import load_dotenv
from langchain_core.messages import (
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from langchain_core.tools import tool
from langchain_openai import ChatOpenAI


# 把函数包装成工具
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


def main() -> None:
    model = create_model()

    tools = [get_service_status]
    # bind_tools 只是把工具说明提供给模型，并不会执行工具
    # 配合上面的 @tool 装饰器，相当于之前的TOOL_DEFINITIONS 模型才能调用工具
    model_with_tools = model.bind_tools(tools)

    messages = [
        SystemMessage(
            content=(
                "你是故障分析助手。"
                "如果需要服务状态，请调用 get_service_status。"
            )
        ),
        HumanMessage(
            content="订单服务返回 502，请检查 order-service 的状态。"
        ),
    ]

    print("===== 第一次请求模型 =====")

    # 这个invoke相当于之前的client.chat.completions.create
    assistant_message = model_with_tools.invoke(messages)

    print("模型文本：")
    print(assistant_message.content or "没有普通文本")

    print("模型工具调用：")
    print(assistant_message.tool_calls)

    messages.append(assistant_message)

    if not assistant_message.tool_calls:
        print("模型没有请求工具。")
        return

    # 从工具列表中根据工具名称获取工具对象
    tool_map = {
        tool_item.name: tool_item
        for tool_item in tools
    }

    # 执行工具调用
    for call in assistant_message.tool_calls:
        tool_name = call["name"]
        arguments = call["args"]

        print(f"\n执行工具：{tool_name}")
        print("工具参数：")
        print(json.dumps(arguments, ensure_ascii=False, indent=2))

        tool = tool_map.get(tool_name)

        if tool is None:
            result = {
                "ok": False,
                "error": f"未知工具：{tool_name}",
            }
        else:
            result = tool.invoke(arguments)

        print("工具结果：")
        print(json.dumps(result, ensure_ascii=False, indent=2))

        messages.append(
            ToolMessage(
                content=json.dumps(
                    result,
                    ensure_ascii=False,
                ),
                tool_call_id=call["id"],
            )
        )

    print("\n===== 第二次请求模型 =====")

    final_message = model_with_tools.invoke(messages)

    print("最终回答：")
    print(final_message.content)


if __name__ == "__main__":
    main()