from __future__ import annotations

import json
import os
from typing import Any

from dotenv import load_dotenv
from openai import OpenAI

# 1. 最大迭代次数
MAX_STEPS = 3


# 2. 工具函数
def search_knowledge(
    query: str,
    knowledge_base_id: int,
) -> dict[str, Any]:
    """本地模拟知识库检索工具。"""

    if not query.strip():
        return {
            "ok": False,
            "sources": [],
            "error": "query 不能为空",
        }

    return {
        "ok": True,
        "sources": [
            {
                "content": (
                    "订单服务返回 502 可能与数据库连接超时有关。"
                    "建议检查 MySQL 可用性、连接池状态和网络连通性。"
                ),
                "filename": "订单服务故障排查手册.md",
                "version_id": 3,
                "chunk_index": 2,
            }
        ],
        "error": None,
    }


# 3. 工具函数映射
TOOL_HANDLERS = {
    "search_knowledge": search_knowledge,
}

# 4. 工具的"说明书"：告诉模型这个工具叫什么、要什么参数
TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "search_knowledge",
            "description": "在指定知识库中检索与故障问题相关的文档片段。",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "需要检索的问题或故障现象。",
                    },
                    "knowledge_base_id": {
                        "type": "integer",
                        "description": "知识库 ID。",
                    },
                },
                "required": ["query", "knowledge_base_id"],
                "additionalProperties": False,
            },
        },
    }
]


SYSTEM_PROMPT = """
你是 Incident Agent，一个研发故障分析助手。

请根据用户提供的故障信息进行分析。
如果需要文档依据，请调用 search_knowledge 工具。
不得编造工具结果或文档引用。
证据不足时必须明确说明。
你只能提供排查建议，不得执行任何命令。
""".strip()


def create_client() -> tuple[OpenAI, str]:
    load_dotenv()

    api_key = os.getenv("DEEPSEEK_API_KEY") or os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError(
            "没有找到 API Key，请在本机 .env 中配置 "
            "DEEPSEEK_API_KEY 或 OPENAI_API_KEY。"
        )

    base_url = os.getenv(
        "DEEPSEEK_BASE_URL",
        "https://api.deepseek.com",
    )
    model = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")

    return OpenAI(api_key=api_key, base_url=base_url), model


def execute_tool(tool_name: str, raw_arguments: str) -> dict[str, Any]:
    """解析参数、查找工具并执行。"""

    try:
        arguments = json.loads(raw_arguments or "{}")
    except json.JSONDecodeError:
        return {
            "ok": False,
            "sources": [],
            "error": "模型返回的工具参数不是合法 JSON",
        }

    handler = TOOL_HANDLERS.get(tool_name)
    if handler is None:
        return {
            "ok": False,
            "sources": [],
            "error": f"未知工具：{tool_name}",
        }

    try:
        return handler(**arguments)
    except TypeError as exc:
        return {
            "ok": False,
            "sources": [],
            "error": f"工具参数校验失败：{exc}",
        }
    except Exception as exc:
        return {
            "ok": False,
            "sources": [],
            "error": f"工具执行失败：{exc}",
        }


def main() -> None:
    client, model = create_client()

    messages: list[dict[str, Any]] = [
        # system,告诉模型这是一个故障分析助手，需要根据用户提供的故障信息进行分析
        {
            "role": "system",
            "content": SYSTEM_PROMPT,
        },
        # user,用户提供的故障信息
        {
            "role": "user",
            "content": (
                "订单服务返回 502，日志显示连接 MySQL 超时。"
                "请先检索知识库，再根据证据给出初步分析。"
                "知识库 ID 是 1。"
            ),
        },
    ]

    # 5. 模型请求循环，是否调用工具
    for step in range(1, MAX_STEPS + 1):
        print(f"\n===== 第 {step} 次模型请求 =====")

        response = client.chat.completions.create(
            model=model,
            messages=messages,
            tools=TOOL_DEFINITIONS,
            # auto,模型会根据上下文自动选择是否调用工具
            tool_choice="auto",
            temperature=0.1,
        )

        assistant = response.choices[0].message
        tool_calls = assistant.tool_calls or []

        assistant_message: dict[str, Any] = {
            "role": "assistant",
            "content": assistant.content or "",
        }

        if tool_calls:
            assistant_message["tool_calls"] = [
                {
                    "id": call.id,
                    "type": "function",
                    "function": {
                        "name": call.function.name,
                        "arguments": call.function.arguments,
                    },
                }
                for call in tool_calls
            ]

        messages.append(assistant_message)

        if not tool_calls:
            print("最终回答：")
            print(assistant.content or "模型没有返回文本。")
            return

        # 6. 工具调用循环
        for call in tool_calls:
            tool_name = call.function.name
            raw_arguments = call.function.arguments or "{}"

            print(f"模型请求调用工具：{tool_name}")
            print(f"模型提供的参数：{raw_arguments}")

            result = execute_tool(tool_name, raw_arguments)

            print("工具执行结果：")
            # 将结果放回消息列表，方便后续模型请求
            print(json.dumps(result, ensure_ascii=False, indent=2))

            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": call.id,
                    "content": json.dumps(
                        result,
                        ensure_ascii=False,
                    ),
                }
            )

    print(f"\n达到最大步骤数 {MAX_STEPS}，流程停止。")


if __name__ == "__main__":
    main()
