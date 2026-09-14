"""Tolerant report parsing and the bounded repair retry (P1-2-1).

Two layers are covered:

- ``graph/report_json.py``: decoding tolerates Markdown fences, surrounding
  prose and trailing commas without touching an unrelated document that only
  looks like JSON;
- the report node: at most **one** repair request after a failed attempt, and a
  controlled degradation when both attempts fail.
"""

from __future__ import annotations

import json

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from app.incident_agent.core.statuses import RunStatus, StepErrorCode, StepStatus
from app.incident_agent.graph.nodes import (
    REPAIR_INSTRUCTION,
    REPORT_MAX_ATTEMPTS,
    parse_report,
)
from app.incident_agent.graph.report_json import (
    extract_json_object,
    parse_json_tolerantly,
    remove_trailing_commas,
    strip_code_fence,
    unwrap_json,
)
from app.incident_agent.graph.workflow import build_graph
from app.incident_agent.schemas.rag import RagSearchResponse
from app.incident_agent.services.tools import build_tools

KB_CONTENT = "订单服务返回 502 可能与数据库连接超时有关，建议检查 MySQL、连接池和网络连通性。"

VALID_REPORT_DICT = {
    "summary": "订单服务 502。",
    "category": "database",
    "evidence": [{"source": "knowledge_base", "detail": KB_CONTENT}],
    "possible_causes": ["数据库连接超时"],
    "troubleshooting_steps": ["检查数据库"],
    "references": [],
    "confidence": "medium",
}
VALID_REPORT = json.dumps(VALID_REPORT_DICT, ensure_ascii=False)


class FakeModel:
    """Model double that records every message list it is asked to complete."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls: list[list] = []

    def bind_tools(self, tools):
        return self

    def invoke(self, messages):
        self.calls.append(list(messages))
        if not self.responses:
            raise AssertionError("FakeModel 没有预置更多响应")
        return self.responses.pop(0)


def make_state(observations: list | None = None) -> dict:
    return {
        "run_id": "run-repair-1",
        "owner_user_id": 1,
        "title": "订单服务故障",
        "input_content": KB_CONTENT,
        "knowledge_base_id": 3,
        "top_k": 5,
        "messages": [],
        "observations": observations if observations is not None else [],
        "steps": [],
        "iteration": 1,
        "max_iterations": 4,
        "status": RunStatus.RUNNING,
        "error": None,
        "report": None,
    }


def search_observation() -> dict:
    return {
        "iteration": 1,
        "tool_name": "search_knowledge",
        "tool_call_id": "call-search",
        "result": {
            "ok": True,
            "data": {
                "question": "订单服务 502",
                "context": KB_CONTENT,
                "sources": [
                    {
                        "document_id": 10,
                        "version_id": 21,
                        "version_number": 2,
                        "chunk_index": 2,
                        "filename": "手册.md",
                        "content": KB_CONTENT,
                        "distance": 0.2,
                        "page_number": None,
                    }
                ],
            },
            "error_code": None,
            "error": None,
        },
    }


class MatchingGateway:
    """Retrieval double whose content matches what VALID_REPORT cites.

    Without this the evidence check (P0-3-2) correctly drops the citation and the
    run ends as ``insufficient_evidence`` instead of ``completed``, which would
    hide what these tests are actually about.
    """

    def search_knowledge(self, *, query, knowledge_base_id, top_k, access_token=None):
        return RagSearchResponse(
            question=query,
            context=KB_CONTENT,
            sources=[
                {
                    "document_id": 10,
                    "version_id": 21,
                    "version_number": 2,
                    "chunk_index": 2,
                    "filename": "手册.md",
                    "content": KB_CONTENT,
                    "distance": 0.2,
                    "page_number": None,
                }
            ],
        )


def run_report_node(responses: list, observations: list | None = None):
    """Run the graph so the report node executes, returning (result, report_model)."""

    report_model = FakeModel(responses)
    agent_model = FakeModel([AIMessage(content="无需工具，直接给结论。")])
    graph = build_graph(
        model=agent_model,
        report_model=report_model,
        tools=build_tools(MatchingGateway()),
    )
    # 默认带上一条真实的检索观察：否则证据无法核实，报告会被整体剔除，
    # 状态变成 insufficient_evidence，反而掩盖了这些用例真正要验证的解析与修复行为。
    if observations is None:
        observations = [search_observation()]
    return graph.invoke(make_state(observations)), report_model


# --------------------------------------------------------------------------
# Tolerant decoding primitives
# --------------------------------------------------------------------------


def test_strip_code_fence_handles_json_labelled_fences():
    assert strip_code_fence('```json\n{"a": 1}\n```') == '{"a": 1}'
    assert strip_code_fence('```\n{"a": 1}\n```') == '{"a": 1}'
    assert strip_code_fence('{"a": 1}') == '{"a": 1}'


def test_extract_json_object_drops_surrounding_prose():
    text = '好的，这是报告：\n{"a": 1}\n希望有帮助。'

    assert extract_json_object(text) == '{"a": 1}'


def test_extract_json_object_is_not_fooled_by_braces_inside_strings():
    text = '{"a": "值里有 } 这个字符", "b": 2}'

    assert extract_json_object(text) == text


def test_extract_json_object_handles_escaped_quotes():
    text = '前缀 {"a": "他说 \\"你好\\"", "b": 2} 后缀'

    assert extract_json_object(text) == '{"a": "他说 \\"你好\\"", "b": 2}'


def test_remove_trailing_commas():
    assert remove_trailing_commas('{"a": 1,}') == '{"a": 1}'
    assert remove_trailing_commas('{"a": [1, 2,]}') == '{"a": [1, 2]}'
    # 字符串里的逗号不受影响
    assert remove_trailing_commas('{"a": "x, y"}') == '{"a": "x, y"}'


def test_unwrap_json_combines_every_cleanup():
    messy = '说明文字\n```json\n{"a": 1,}\n```\n结束'

    assert unwrap_json(messy) == '{"a": 1,}'


def test_parse_json_tolerantly_decodes_the_common_slips():
    assert parse_json_tolerantly('```json\n{"a": 1}\n```') == {"a": 1}
    assert parse_json_tolerantly('前言 {"a": 1} 后记') == {"a": 1}
    assert parse_json_tolerantly('{"a": 1,}') == {"a": 1}


def test_parse_json_tolerantly_still_rejects_garbage():
    with pytest.raises(json.JSONDecodeError):
        parse_json_tolerantly("这不是 JSON 也不是对象")


def test_parse_report_accepts_a_fenced_report():
    fenced = f"```json\n{VALID_REPORT}\n```"

    report = parse_report(fenced)

    assert report.category == "database"
    assert report.confidence == "medium"


def test_parse_report_accepts_prose_around_the_object():
    report = parse_report(f"下面是报告：\n{VALID_REPORT}\n以上。")

    assert report.summary == VALID_REPORT_DICT["summary"]


def test_parse_report_accepts_trailing_commas():
    messy = VALID_REPORT.replace('"confidence": "medium"', '"confidence": "medium",')

    report = parse_report(messy)

    assert report.confidence == "medium"


# --------------------------------------------------------------------------
# The bounded repair retry
# --------------------------------------------------------------------------


def test_markdown_fence_no_longer_costs_the_whole_run():
    """The regression P1-2-1 is about: a fence should not degrade the run."""

    result, report_model = run_report_node([AIMessage(content=f"```json\n{VALID_REPORT}\n```")])

    assert result["status"] == RunStatus.COMPLETED
    assert result["report"] is not None
    # 没有失败过，因此不需要修复请求
    assert len(report_model.calls) == 1


def test_one_repair_request_recovers_from_invalid_json():
    result, report_model = run_report_node(
        [
            AIMessage(content="我不会输出 JSON"),
            AIMessage(content=VALID_REPORT),
        ]
    )

    assert result["status"] == RunStatus.COMPLETED
    assert result["report"] is not None
    assert len(report_model.calls) == REPORT_MAX_ATTEMPTS == 2

    actions = [step["action"] for step in result["steps"]]
    assert "repair_report" in actions


def test_repair_request_carries_the_previous_output_and_instructions():
    _, report_model = run_report_node(
        [
            AIMessage(content="坏输出"),
            AIMessage(content=VALID_REPORT),
        ]
    )

    repair_messages = report_model.calls[1]
    contents = " ".join(str(getattr(m, "content", "")) for m in repair_messages)

    assert "坏输出" in contents
    assert REPAIR_INSTRUCTION in contents


def test_repair_is_attempted_only_once():
    result, report_model = run_report_node(
        [
            AIMessage(content="不是 JSON"),
            AIMessage(content="还是不是 JSON"),
            AIMessage(content="第三次也不该被调用"),
        ]
    )

    assert result["status"] == RunStatus.REPORT_VALIDATION_FAILED
    assert len(report_model.calls) == REPORT_MAX_ATTEMPTS


def test_two_failures_degrade_with_a_diagnosable_step():
    result, _ = run_report_node(
        [
            AIMessage(content="不是 JSON"),
            AIMessage(content="依然不是 JSON"),
        ]
    )

    assert result["status"] == RunStatus.REPORT_VALIDATION_FAILED
    assert result["report"] is None

    repair_steps = [
        step for step in result["steps"] if step["action"] == "repair_report"
    ]
    assert len(repair_steps) == 1
    assert repair_steps[0]["status"] == StepStatus.FAILED

    final = [step for step in result["steps"] if step["action"] == "validate_report"]
    assert final[-1]["status"] == StepStatus.FAILED
    assert final[-1]["error_code"] == StepErrorCode.INVALID_JSON
    assert final[-1]["attempts"] == REPORT_MAX_ATTEMPTS


def test_structural_failure_also_triggers_the_repair_path():
    """A schema violation (not just broken JSON) is worth one repair attempt."""

    wrong_category = json.dumps(
        {**VALID_REPORT_DICT, "category": "hardware"}, ensure_ascii=False
    )
    result, report_model = run_report_node(
        [
            AIMessage(content=wrong_category),
            AIMessage(content=VALID_REPORT),
        ]
    )

    assert result["status"] == RunStatus.COMPLETED
    assert len(report_model.calls) == 2


def test_repair_does_not_relax_the_contract():
    """The repair instruction must not let a fenced/wrong report through.

    A reply that still violates the schema keeps the run degraded, proving the
    repair path revalidates instead of trusting the second answer.
    """

    wrong_category = json.dumps(
        {**VALID_REPORT_DICT, "category": "hardware"}, ensure_ascii=False
    )
    result, _ = run_report_node(
        [
            AIMessage(content=wrong_category),
            AIMessage(content=wrong_category),
        ]
    )

    assert result["status"] == RunStatus.REPORT_VALIDATION_FAILED
    assert result["report"] is None
    final = [step for step in result["steps"] if step["action"] == "validate_report"]
    assert final[-1]["error_code"] == StepErrorCode.INVALID_REPORT


def test_successful_first_attempt_records_attempts_one():
    result, _ = run_report_node([AIMessage(content=VALID_REPORT)])

    success = [
        step
        for step in result["steps"]
        if step["action"] == "validate_report" and step["status"] == StepStatus.SUCCESS
    ]
    assert success[-1]["attempts"] == 1
    assert isinstance(success[-1]["duration_ms"], int)


def test_repair_respects_the_request_budget():
    """The repair round is a model call, so the deadline still applies."""

    from app.incident_agent.graph.deadline import RequestDeadline

    report_model = FakeModel([AIMessage(content="不是 JSON")])
    graph = build_graph(
        model=FakeModel([AIMessage(content="无需工具。")]),
        report_model=report_model,
        tools=build_tools(MatchingGateway()),
        deadline=RequestDeadline.expired(),
    )

    result = graph.invoke(make_state())

    assert result["status"] == RunStatus.DEGRADED
    assert report_model.calls == []


def test_repair_messages_keep_untrusted_data_delimited():
    """The repair prompt reuses the delimited context, not raw observations."""

    _, report_model = run_report_node(
        [
            AIMessage(content="坏输出"),
            AIMessage(content=VALID_REPORT),
        ],
        observations=[search_observation()],
    )

    repair_text = " ".join(
        str(getattr(m, "content", "")) for m in report_model.calls[1]
    )

    assert "<untrusted-tool-data>" in repair_text
    assert isinstance(report_model.calls[1][-1], HumanMessage)
