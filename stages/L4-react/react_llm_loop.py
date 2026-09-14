from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from openai import OpenAI

# 练习目录名包含短横线，先把 L3-tools 加入导入路径。
L3_TOOLS_DIR = Path(__file__).resolve().parents[1] / "L3-tools"

if str(L3_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(L3_TOOLS_DIR))

from tools import run_tool  # noqa: E402

MAX_ITERATIONS = 4


@dataclass
class ReActState:
    """保存一次真实模型 ReAct 运行过程中的状态。"""
    # 给模型看的完整对话上下文
    messages: list[dict[str, Any]]

    # Agent 已经获得的工具事实
    observations: list[dict[str, Any]] = field(default_factory=list)

    # 记录 Agent 做过哪些执行动作
    steps: list[dict[str, Any]] = field(default_factory=list)

    iteration: int = 0
    status: str = "running"
    final_answer: str | None = None


TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "search_knowledge",
            "description": "在指定知识库中检索故障相关文档片段。",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "需要检索的故障现象。",
                    },
                    "knowledge_base_id": {
                        "type": "integer",
                        "description": "知识库 ID。",
                    },
                    "top_k": {
                        "type": "integer",
                        "description": "最多返回多少个结果。",
                    },
                },
                "required": ["query", "knowledge_base_id"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "analyze_log",
            "description": "从故障日志中提取 502、超时、数据库错误等信号。",
            "parameters": {
                "type": "object",
                "properties": {
                    "log_text": {
                        "type": "string",
                        "description": "需要分析的完整日志文本。",
                    },
                },
                "required": ["log_text"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_service_status",
            "description": "查询指定服务当前的模拟运行状态。",
            "parameters": {
                "type": "object",
                "properties": {
                    "service_name": {
                        "type": "string",
                        "description": (
                            "服务名称，例如 order-service "
                            "或 user-service。"
                        ),
                    },
                },
                "required": ["service_name"],
                "additionalProperties": False,
            },
        },
    },
]


SYSTEM_PROMPT = """
你是 Incident Agent，一个研发故障分析助手。

请根据用户提供的故障标题和日志分析问题。
需要事实依据时，调用合适的工具。
工具结果是 Python 后端真实执行的结果，不得编造或修改。

你只能提供检查和排查建议，不得执行命令，
不得声称服务已经被修复或重启。

每次调用工具后，读取工具返回结果再决定下一步。
如果证据足够，或者工具失败、没有有效结果，
就停止调用工具并给出中文分析。
不要无限调用工具。
""".strip()


def create_client() -> tuple[OpenAI, str]:
    """读取配置并创建模型客户端。"""

    load_dotenv()

    api_key = os.getenv("DEEPSEEK_API_KEY") or os.getenv("OPENAI_API_KEY")

    if not api_key:
        raise RuntimeError(
            "没有找到 API Key，请检查本机 .env 配置。"
        )

    base_url = os.getenv(
        "DEEPSEEK_BASE_URL",
        "https://api.deepseek.com",
    )
    model = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")

    return OpenAI(api_key=api_key, base_url=base_url), model


def build_assistant_message(
    assistant: Any,
) -> dict[str, Any]:
    """把 SDK 的助手消息转换为 messages 使用的字典。"""

    tool_calls = assistant.tool_calls or []

    message: dict[str, Any] = {
        "role": "assistant",
        "content": assistant.content or "",
    }

    if tool_calls:
        message["tool_calls"] = [
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

    return message


def run_react(
    client: OpenAI,
    model: str,
    state: ReActState,
) -> ReActState:
    """执行真实模型参与的 Reason → Act → Observation 循环。"""

    while (
        state.status == "running"
        and state.iteration < MAX_ITERATIONS
    ):
        state.iteration += 1

        print(f"\n===== 第 {state.iteration} 轮模型请求 =====")

        response = client.chat.completions.create(
            model=model,
            messages=state.messages,
            tools=TOOL_DEFINITIONS,
            tool_choice="auto",
            temperature=0.1,
        )

        assistant = response.choices[0].message
        tool_calls = assistant.tool_calls or []

        # 保存模型本轮的 assistant 消息。
        assistant_message = build_assistant_message(assistant)
        state.messages.append(assistant_message)

        # 没有 tool_calls，说明模型直接给出了最终回答。
        if not tool_calls:
            state.status = "completed"
            state.final_answer = assistant.content or ""

            print("模型决定结束工具调用。")
            break

        # 有多少个 tool_calls，就执行多少个工具。
        for call in tool_calls:
            tool_name = call.function.name
            raw_arguments = call.function.arguments or "{}"

            state.steps.append(
                {
                    "iteration": state.iteration,
                    "action": "call_tool",
                    "tool_name": tool_name,
                }
            )

            print(f"模型请求调用工具：{tool_name}")
            print(f"工具参数：{raw_arguments}")

            result = run_tool(tool_name, raw_arguments)
            result_data = result.model_dump()

            print("工具结果：")
            print(
                json.dumps(
                    result_data,
                    ensure_ascii=False,
                    indent=2,
                )
            )

            # Observation：把工具事实保存到 Agent 状态。
            state.observations.append(
                {
                    "iteration": state.iteration,
                    "tool_name": tool_name,
                    "result": result_data,
                }
            )

            # 把工具结果放回消息，供下一轮模型读取。
            state.messages.append(
                {
                    "role": "tool",
                    "tool_call_id": call.id,
                    "content": json.dumps(
                        result_data,
                        ensure_ascii=False,
                    ),
                }
            )

    if state.status == "running":
        state.status = "max_iterations"
        print(
            f"达到最大循环次数 {MAX_ITERATIONS}，流程停止。"
        )

    return state


def main() -> None:
    client, model = create_client()

    state = ReActState(
        messages=[
            {
                "role": "system",
                "content": SYSTEM_PROMPT,
            },
            {
                "role": "user",
                "content": (
                    "故障标题：订单服务返回 502\n"
                    "故障日志：gateway returned 502; "
                    "order-service mysql connection timeout\n"
                    "知识库 ID：1"
                ),
            },
        ]
    )

    final_state = run_react(client, model, state)

    print("\n===== 最终结果 =====")
    print(f"状态：{final_state.status}")
    print(f"循环次数：{final_state.iteration}")

    if final_state.final_answer:
        print("最终回答：")
        print(final_state.final_answer)

    print("\n===== 执行轨迹 =====")
    print(
        json.dumps(
            final_state.steps,
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()