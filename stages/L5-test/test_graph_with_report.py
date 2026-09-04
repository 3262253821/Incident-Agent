import json
import sys
from pathlib import Path

from langchain_core.messages import (
    AIMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)


L4_LANGGRAPH_DIR = Path(__file__).resolve().parents[1] / "L4-langgraph"

if str(L4_LANGGRAPH_DIR) not in sys.path:
    sys.path.insert(0, str(L4_LANGGRAPH_DIR))

import graph_with_report


class FakeModel:
    """固定返回结果的离线模拟模型。"""

    def __init__(self, mode: str):
        self.mode = mode
        self.agent_calls = 0

    def bind_tools(self, tools):
        return self

    def invoke(self, messages):
        first_message = messages[0]

        # report_node 使用普通模型生成报告
        if (
            isinstance(first_message, SystemMessage)
            and "报告生成节点" in first_message.content
        ):
            if self.mode == "invalid_report":
                return AIMessage(content="这不是合法 JSON")

            return AIMessage(
                content=json.dumps(
                    {
                        "summary": "订单服务可能因数据库连接超时返回 502。",
                        "category": "database",
                        "evidence": [
                            {
                                "source": "fault_log",
                                "detail": "日志出现 502 和 MySQL connection timeout",
                            }
                        ],
                        "possible_causes": [
                            "数据库连接超时",
                        ],
                        "troubleshooting_steps": [
                            "检查 MySQL 状态",
                        ],
                        "references": [
                            "订单服务故障排查手册.md",
                        ],
                        "confidence": "medium",
                    },
                    ensure_ascii=False,
                )
            )

        self.agent_calls += 1

        # repeat 模式：每次都继续请求工具
        if self.mode == "repeat":
            service_name = "order-service"

        elif self.mode == "unknown_service":
            service_name = "gateway"

        else:
            has_tool_result = any(
                isinstance(message, ToolMessage)
                for message in messages
            )

            # 正常模式：工具执行一次后，不再调用工具
            if has_tool_result:
                return AIMessage(
                    content="工具结果已经足够，可以生成报告。",
                    tool_calls=[],
                )

            service_name = "order-service"

        return AIMessage(
            content="",
            tool_calls=[
                {
                    "name": "get_service_status",
                    "args": {
                        "service_name": service_name,
                    },
                    "id": f"call_{self.agent_calls}",
                    "type": "tool_call",
                }
            ],
        )


def create_initial_state():
    return {
        "messages": [
            SystemMessage(
                content="你是 Incident Agent。",
            ),
            HumanMessage(
                content="订单服务返回 502，请分析原因。",
            ),
        ],
        "observations": [],
        "steps": [],
        "iteration": 0,
        "status": "running",
        "error": None,
        "report": None,
    }


def run_offline_graph(monkeypatch, mode):
    fake_model = FakeModel(mode)

    monkeypatch.setattr(
        graph_with_report,
        "create_model",
        lambda: fake_model,
    )

    graph = graph_with_report.build_graph()
    final_state = graph.invoke(create_initial_state())

    return final_state


def test_normal_path_generates_report(monkeypatch):
    final_state = run_offline_graph(monkeypatch, "normal")

    assert final_state["status"] == "completed"
    assert final_state["report"] is not None
    assert final_state["report"]["category"] == "database"
    assert len(final_state["observations"]) == 1


def test_unknown_service_degrades(monkeypatch):
    final_state = run_offline_graph(
        monkeypatch,
        "unknown_service",
    )

    assert final_state["status"] == "degraded"
    assert final_state["report"] is None
    assert "未知服务：gateway" in final_state["error"]


def test_invalid_report_degrades(monkeypatch):
    final_state = run_offline_graph(
        monkeypatch,
        "invalid_report",
    )

    assert final_state["status"] == "degraded"
    assert final_state["report"] is None
    assert "报告不是合法 JSON" in final_state["error"]


def test_max_iterations_protects_graph(monkeypatch):
    final_state = run_offline_graph(
        monkeypatch,
        "repeat",
    )

    assert final_state["status"] == "max_iterations"
    assert final_state["iteration"] == graph_with_report.MAX_ITERATIONS
    assert final_state["error"] == (
        f"达到最大模型请求次数："
        f"{graph_with_report.MAX_ITERATIONS}"
    )