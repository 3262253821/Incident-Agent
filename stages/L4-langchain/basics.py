from __future__ import annotations

import json

from langchain_core.messages import (
    AIMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from langchain_core.tools import tool


@tool
def get_service_status(service_name: str) -> dict[str, object]:
    """查询指定服务的模拟状态。"""

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


def main() -> None:
    print("===== 1. LangChain 消息对象 =====")

    messages = [
        SystemMessage(
            content="你是 Incident Agent，只能提供排查建议。"
        ),
        HumanMessage(
            content="订单服务返回 502，请检查服务状态。"
        ),
    ]

    for message in messages:
        print(
            type(message).__name__,
            "→",
            message.content,
        )

    print("\n===== 2. LangChain 工具 =====")

    print("工具名称：", get_service_status.name)
    print("工具描述：", get_service_status.description)
    print(
        "工具参数 Schema：",
        json.dumps(
            get_service_status.args_schema.model_json_schema(),
            ensure_ascii=False,
            indent=2,
        ),
    )

    result = get_service_status.invoke(
        {"service_name": "order-service"}
    )

    print("工具执行结果：")
    print(
        json.dumps(
            result,
            ensure_ascii=False,
            indent=2,
        )
    )

    print("\n===== 3. 模拟模型工具调用消息 =====")

    assistant_message = AIMessage(
        content="",
        tool_calls=[
            {
                "name": "get_service_status",
                "args": {
                    "service_name": "order-service",
                },
                "id": "call_1",
                "type": "tool_call",
            }
        ],
    )

    print("模型请求调用：")
    print(assistant_message.tool_calls)

    tool_message = ToolMessage(
        content=json.dumps(
            result,
            ensure_ascii=False,
        ),
        tool_call_id="call_1",
    )

    print("工具返回消息：")
    print("tool_call_id：", tool_message.tool_call_id)
    print("content：", tool_message.content)

    print("\n===== 4. 消息顺序 =====")

    all_messages = [
        *messages,
        assistant_message,
        tool_message,
    ]

    for index, message in enumerate(all_messages, start=1):
        print(
            f"{index}.",
            type(message).__name__,
            "→",
            message.content,
        )


if __name__ == "__main__":
    main()