"""设计文档 §7（统一工具结果协议）、§16.2（工具异常）、§17.3（硬断言）。

P1-4-1 里点名要补的"工具结果非法"：工具返回的东西**不是**统一
``ToolResult`` 形状时，``observe`` 必须给出一个可诊断的失败观察，而不是崩溃、
不是静默丢弃、也不能把原始载荷当证据留下来。

覆盖的非法形状（每一条都对应一种真实可能）：非 JSON 文本、JSON 但不是对象、
缺 ``ok``、``ok`` 类型错误、多出未约定的字段（``extra="forbid"``）。
"""

from __future__ import annotations

import json

import pytest
from langchain_core.messages import AIMessage, ToolMessage

from app.incident_agent.core.statuses import InternalRunStatus, StepStatus
from app.incident_agent.graph.nodes import make_observe_node
from app.incident_agent.schemas.tool import ToolResult

MALFORMED_PAYLOADS = [
    "这不是 JSON：工具直接把异常文本写进了 content",
    "[1, 2, 3]",
    "null",
    '{"data": {"signals": []}}',  # 缺 ok
    '{"ok": 2, "data": {}}',  # ok 不是布尔值
    '{"ok": null, "data": {}}',  # ok 是空值
    '{"ok": true, "data": {}, "unexpected": 1}',  # 未约定字段
]


def make_state(
    *contents: str,
    tool_name: str = "analyze_log",
    arguments: dict | None = None,
    observations: list | None = None,
    status: str = "running",
):
    """Build a minimal AgentState holding the given ToolMessages."""

    args = arguments if arguments is not None else {"log_text": "502 mysql"}
    tool_messages = [
        ToolMessage(content=content, tool_call_id=f"call-{index}", name=tool_name)
        for index, content in enumerate(contents or ["{}"])
    ]
    ai_message = AIMessage(
        content="",
        tool_calls=[
            {"name": tool_name, "args": args, "id": f"call-{index}"}
            for index in range(len(tool_messages))
        ],
    )
    return {
        "run_id": "run-observe",
        "iteration": 1,
        "messages": [ai_message, *tool_messages],
        "observations": list(observations or []),
        "steps": [],
        "status": status,
        "error": None,
    }


def successful_payload() -> str:
    return ToolResult(
        ok=True,
        data={
            "signals": [
                {
                    "type": "timeout",
                    "value": "第 1 行命中 timeout",
                    "matched_text": "timeout",
                    "line_number": 1,
                }
            ],
            "signal_count": 1,
        },
    ).model_dump_json()


@pytest.mark.parametrize("payload", MALFORMED_PAYLOADS)
def test_malformed_tool_payload_becomes_an_invalid_tool_result(payload):
    result = make_observe_node()(make_state(payload))

    observation = result["observations"][0]
    assert observation["result"] == {
        "ok": False,
        "data": {},
        "error_code": "INVALID_TOOL_RESULT",
        "error": "工具结果不是合法的统一结果结构",
    }

    step = result["steps"][0]
    assert step["status"] == StepStatus.FAILED
    assert step["error_code"] == "INVALID_TOOL_RESULT"
    assert step["ok"] is False

    # 一次失败观察就要让路由停止继续问模型（§9.3 工具失败路径）。
    assert result["status"] == InternalRunStatus.TOOL_FAILED
    assert result["error"]


def test_invalid_tool_result_never_echoes_the_raw_payload():
    payload = '{"ok": true, 但这里有凭据 password=hunter2 并且不是 JSON'

    result = make_observe_node()(make_state(payload))

    stored = json.dumps(result["observations"], ensure_ascii=False)
    assert "hunter2" not in stored
    assert "password" not in stored
    # 结果摘要只留计数与错误码，不复制 content。
    summary = result["steps"][0]["result_summary"]
    assert summary == {
        "ok": False,
        "signal_count": 0,
        "error_code": "INVALID_TOOL_RESULT",
    }


@pytest.mark.parametrize(
    ("payload", "expected_ok"),
    [
        ('{"ok": "true", "data": {}}', True),
        ('{"ok": "false", "data": {}}', False),
        ('{"ok": "yes", "data": {}}', True),
        ('{"ok": "no", "data": {}}', False),
    ],
)
def test_boolean_like_strings_are_coerced_and_other_values_are_not(
    payload,
    expected_ok,
):
    """记录真实的宽松解析边界（不是设计文档要求的，但不写就会被误解）。

    Pydantic 的宽松模式接受 ``"true"/"false"/"yes"/"no"`` 这类布尔字符串并映射
    到正确的布尔值，而 ``2``、``1.5``、``null``、``"maybe"`` 一律拒绝（见上一条
    测试）。前者是有意的容错，后者才是非法形状。
    """

    result = make_observe_node()(make_state(payload))

    assert result["observations"][0]["result"]["ok"] is expected_ok


def test_valid_tool_result_is_stored_with_its_payload_and_summaries():
    result = make_observe_node()(
        make_state(successful_payload(), arguments={"log_text": "502 mysql timeout"})
    )

    observation = result["observations"][0]
    assert observation["result"]["ok"] is True
    assert observation["result"]["data"]["signal_count"] == 1
    assert observation["tool_name"] == "analyze_log"
    assert observation["tool_call_id"] == "call-0"

    step = result["steps"][0]
    assert step["status"] == StepStatus.SUCCESS
    # §15.2：原始日志文本绝不入库，只留长度。
    assert step["arguments_summary"] == {"log_text_length": 17}
    assert step["result_summary"] == {
        "ok": True,
        "signal_count": 1,
        "signal_types": ["timeout"],
    }
    assert result["status"] == "running"
    assert result["error"] is None


def test_observe_processes_each_tool_message_exactly_once():
    state = make_state(successful_payload(), successful_payload())
    node = make_observe_node()

    first = node(state)
    assert len(first["observations"]) == 2
    assert len(first["steps"]) == 2

    # 第二轮拿到的是上一轮的输出，消息列表没有变化。
    second = node({**state, **first})

    assert len(second["observations"]) == 2
    assert len(second["steps"]) == 2


def test_tool_message_without_a_name_is_recorded_as_unknown_tool():
    state = make_state(successful_payload())
    # name 缺失时不能编造工具名，也不能丢掉这条轨迹。
    state["messages"][1] = ToolMessage(
        content=successful_payload(),
        tool_call_id="call-0",
    )

    result = make_observe_node()(state)

    assert result["observations"][0]["tool_name"] == "unknown_tool"
    assert result["steps"][0]["tool_name"] == "unknown_tool"


def test_one_failed_result_among_successful_ones_still_fails_the_run():
    state = make_state(successful_payload(), "not-json")

    result = make_observe_node()(state)

    assert [item["result"]["ok"] for item in result["observations"]] == [True, False]
    assert result["status"] == InternalRunStatus.TOOL_FAILED
    assert result["error"] == "工具结果不是合法的统一结果结构"
