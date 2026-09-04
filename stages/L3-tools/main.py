from __future__ import annotations

import json
import os
from typing import Any

from dotenv import load_dotenv
from openai import OpenAI
from report_models import IncidentReport
from tools import run_tool

MAX_STEPS = 3

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
                "required": [
                    "query",
                    "knowledge_base_id",
                ],
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
                        "description": "服务名称，例如 order-service。",
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

请分析用户提供的故障标题和日志。
需要事实依据时，选择合适的工具获取信息。
工具结果是后端真实执行结果，不得编造或修改。

你只能提供排查建议，不得执行命令，不得声称服务已经被修复。
如果证据不足，必须在报告中明确说明。

当证据足够或无法继续获取证据时，停止调用工具，
并只返回合法 JSON，不要添加 Markdown 代码块或额外解释。

JSON 必须包含以下字段：
summary、category、evidence、possible_causes、
troubleshooting_steps、references、confidence。

category 只能是：
database、network、application、dependency、unknown。

confidence 只能是：
low、medium、high。
""".strip()


def create_client() -> tuple[OpenAI, str]:
    # load_dotenv() 从 .env 文件加载环境变量，或从系统环境变量中获取
    load_dotenv()

    api_key = os.getenv("DEEPSEEK_API_KEY") or os.getenv("OPENAI_API_KEY")

    if not api_key:
        raise RuntimeError("没有找到 API Key，请检查本机 .env 配置。")

    base_url = os.getenv(
        "DEEPSEEK_BASE_URL",
        "https://api.deepseek.com",
    )
    model = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")

    return OpenAI(api_key=api_key, base_url=base_url), model


def parse_report(content: str) -> IncidentReport:
    """解析模型返回的 JSON，并校验报告结构。"""

    text = content.strip()

    if text.startswith("```"):
        lines = text.splitlines()

        if lines and lines[0].startswith("```"):
            lines = lines[1:]

        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]

        text = "\n".join(lines).strip()

    data = json.loads(text)

    return IncidentReport.model_validate(data)


def main() -> None:
    # 1. 创建模型客户端
    client, model = create_client()

    # 2. 初始化消息列表
    # 系统提示
    # 用户输入
    messages: list[dict[str, Any]] = [
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

    # 3. 模型请求循环
    for step in range(1, MAX_STEPS + 1):
        print(f"\n===== 第 {step} 次模型请求 =====")

        response = client.chat.completions.create(
            model=model,
            messages=messages,
            tools=TOOL_DEFINITIONS,
            tool_choice="auto",
            temperature=0.1,
        )
        
        # 4. 处理模型响应
        assistant = response.choices[0].message
        # 模型调用的工具列表
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

        # 让模型知道自己的调用记录,保存的是模型对于工具调用的请求记录
        messages.append(assistant_message)

        if not tool_calls:
            try:
                report = parse_report(assistant.content or "")

                print("结构化报告校验成功：")
                print(
                    json.dumps(
                        report.model_dump(),
                        ensure_ascii=False,
                        indent=2,
                    )
                )
            except json.JSONDecodeError as exc:
                print(f"模型返回的内容不是合法 JSON：{exc}")
            except Exception as exc:
                print(f"报告结构校验失败：{exc}")

            return
        
        # 5. 处理工具调用
        for call in tool_calls:
            tool_name = call.function.name
            raw_arguments = call.function.arguments or "{}"

            print(f"模型请求调用工具：{tool_name}")
            print(f"工具参数：{raw_arguments}")

            result = run_tool(tool_name, raw_arguments)

            print("工具执行结果：")
            print(
                json.dumps(
                    result.model_dump(),
                    ensure_ascii=False,
                    indent=2,
                )
            )
            print("-------------------------")

            # 让模型知道自己的工具执行结果,保存的是python调用工具处理后的结果
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": call.id,
                    "content": json.dumps(
                        result.model_dump(),
                        ensure_ascii=False,
                    ),
                }
            )

    print(f"\n达到最大模型请求轮数 {MAX_STEPS}，流程停止。")


if __name__ == "__main__":
    main()
