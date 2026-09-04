from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any


MAX_ITERATIONS = 4


@dataclass
# 记忆本轮已经知道什么，以及每一轮做了什么
class ReActState:
    """ReAct 循环运行过程中保存的状态。"""

    title: str
    log_text: str
    knowledge_base_id: int

    # 工具执行后产生的观察结果
    observations: list[dict[str, Any]] = field(default_factory=list)

    # 每一轮做了什么
    steps: list[dict[str, Any]] = field(default_factory=list)

    # iteration: 当前是第几轮
    iteration: int = 0

    # status: 当前状态，默认为running，正在运行中
    status: str = "running"


def analyze_log(log_text: str) -> dict[str, Any]:
    """从日志中提取简单故障信号。"""

    if not log_text.strip():
        return {
            "ok": False,
            "error_code": "EMPTY_LOG",
            "error": "日志不能为空",
        }

    patterns = {
        "http_502": r"\b502\b",
        "timeout": r"timeout|超时",
        "database_error": r"mysql|database|数据库",
    }

    signals: list[dict[str, str]] = []

    for signal_type, pattern in patterns.items():
        if re.search(pattern, log_text, re.IGNORECASE):
            signals.append(
                {
                    "type": signal_type,
                    "value": "命中日志关键词",
                }
            )

    return {
        "ok": True,
        "data": {
            "signals": signals,
            "signal_count": len(signals),
        },
    }


def search_knowledge(
    query: str,
    knowledge_base_id: int,
) -> dict[str, Any]:
    """模拟知识库检索。"""

    if not query.strip():
        return {
            "ok": False,
            "error_code": "EMPTY_QUERY",
            "error": "检索问题不能为空",
        }

    # 用“股价”模拟一个与知识库无关的问题
    if "股价" in query:
        return {
            "ok": False,
            "error_code": "NO_EVIDENCE",
            "error": "知识库中没有足够的相关依据",
        }

    return {
        "ok": True,
        "data": {
            "sources": [
                {
                    "content": (
                        "订单服务返回 502 可能与数据库连接超时有关，"
                        "建议检查 MySQL、连接池和网络连通性。"
                    ),
                    "filename": "订单服务故障排查手册.md",
                    "version_id": 3,
                    "chunk_index": 2,
                }
            ],
            "knowledge_base_id": knowledge_base_id,
        },
    }

# 工具注册表
TOOL_HANDLERS = {
    "analyze_log": analyze_log,
    "search_knowledge": search_knowledge,
}

# 真正执行工具，返回工具执行结果，以及工具执行是否成功
def execute_tool(
    tool_name: str,
    arguments: dict[str, Any],
) -> dict[str, Any]:
    """根据工具名执行工具。"""

    handler = TOOL_HANDLERS.get(tool_name)

    if handler is None:
        return {
            "ok": False,
            "error_code": "UNKNOWN_TOOL",
            "error": f"未知工具：{tool_name}",
        }

    try:
        return handler(**arguments)
    except TypeError as exc:
        return {
            "ok": False,
            "error_code": "INVALID_ARGUMENTS",
            "error": f"工具参数错误：{exc}",
        }
    except Exception as exc:
        return {
            "ok": False,
            "error_code": "TOOL_ERROR",
            "error": f"工具执行失败：{exc}",
        }

# 决定下一步做什么
def decide_next_action(
    state: ReActState,
) -> dict[str, Any]:
    """
    暂时模拟 Agent 的下一步决策。

    正式版本中，这里会改成：
    读取 LLM 响应
    → 解析模型要调用的工具
    → 返回同样格式的 action。
    """

    # 先查看调用过的工具
    observed_tool_names = {
        observation["tool_name"]
        for observation in state.observations
    }

    if "analyze_log" not in observed_tool_names:
        return {
            "action": "call_tool",
            "tool_name": "analyze_log",
            "arguments": {
                "log_text": state.log_text,
            },
            "reason": "还没有日志信号，先分析故障日志。",
        }

    if "search_knowledge" not in observed_tool_names:
        return {
            "action": "call_tool",
            "tool_name": "search_knowledge",
            "arguments": {
                "query": f"{state.title} {state.log_text}",
                "knowledge_base_id": state.knowledge_base_id,
            },
            "reason": "已经得到日志信号，继续检索知识库证据。",
        }

    return {
        "action": "finish",
        "tool_name": None,
        "arguments": {},
        "reason": "日志信号和知识库证据都已获取，停止调用工具。",
    }

# 控制整个循环
def run_react(state: ReActState) -> ReActState:
    """运行 Reason → Act → Observation 循环。"""

    while (
        state.status == "running"
        and state.iteration < MAX_ITERATIONS
    ):
        state.iteration += 1

        print(f"\n===== 第 {state.iteration} 轮 =====")

        # Reason：决定下一步动作
        decision = decide_next_action(state)

        state.steps.append(
            {
                "iteration": state.iteration,
                "action": decision["action"],
                "tool_name": decision["tool_name"],
                "reason": decision["reason"],
            }
        )

        print(f"Reason：{decision['reason']}")

        if decision["action"] == "finish":
            state.status = "completed"
            print("Action：结束循环")
            break

        # Act：执行工具
        tool_name = decision["tool_name"]
        arguments = decision["arguments"]

        print(f"Action：调用 {tool_name}")
        print(
            json.dumps(
                arguments,
                ensure_ascii=False,
                indent=2,
            )
        )
        # 这才是真正执行工具的地方，返回工具执行结果，以及工具执行是否成功
        result = execute_tool(tool_name, arguments)

        # Observation：记录工具结果
        observation = {
            "tool_name": tool_name,
            "result": result,
        }
        # 将工具执行结果记录到state.observations中
        state.observations.append(observation)

        print("Observation：")
        print(
            json.dumps(
                result,
                ensure_ascii=False,
                indent=2,
            )
        )

        if not result.get("ok"):
            state.status = "degraded"
            print("工具没有提供可继续使用的结果，降级结束。")
            break

    if state.status == "running":
        state.status = "max_iterations"
        print(f"达到最大循环次数 {MAX_ITERATIONS}，停止。")

    return state


def main() -> None:
    cases = [
        (
            "正常路径",
            ReActState(
                title="订单服务返回 502",
                log_text=(
                    "gateway returned 502; "
                    "order-service mysql connection timeout"
                ),
                knowledge_base_id=1,
            ),
        ),
        (
            "无检索结果路径",
            ReActState(
                title="股价查询问题",
                log_text="客户端请求股价数据，但知识库没有相关内容",
                knowledge_base_id=1,
            ),
        ),
    ]

    for case_name, state in cases:
        print(f"\n\n########## {case_name} ##########")

        final_state = run_react(state)

        print("\n最终状态：")
        print(
            json.dumps(
                {
                    "status": final_state.status,
                    "iteration": final_state.iteration,
                    "steps": final_state.steps,
                },
                ensure_ascii=False,
                indent=2,
            )
        )


if __name__ == "__main__":
    main()