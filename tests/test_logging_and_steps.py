"""Structured logging and step-trace tests (P1-1).

Covers the three parts of P1-1:

- ``core/logging.py``: JSON lines, secret masking, truncation, idempotent setup;
- the graph/service: ``duration_ms`` and sanitized summaries on every step;
- ``analyze_log``: matched fragment + line number, explicit 5xx boundaries.
"""

from __future__ import annotations

import io
import json
import logging
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from langchain_core.messages import AIMessage

from app.incident_agent.core.logging import (
    LOGGER_NAME,
    REDACTED,
    JsonLogFormatter,
    configure_logging,
    sanitize,
    truncate,
)
from app.incident_agent.graph.workflow import build_graph
from app.incident_agent.services.rag_client import MockRagGateway
from app.incident_agent.services.tools import analyze_log, build_tools

SECRET = "sk-super-secret-should-never-be-logged"
TOKEN = "SECRET-TOKEN-abc123"
LOG_TEXT = f"502 mysql timeout password=devpass123 api_key: {SECRET}"

VALID_REPORT = (
    '{"summary":"订单服务 502。","category":"database",'
    '"evidence":[{"source":"knowledge_base","detail":'
    '"订单服务返回 502 可能与数据库连接超时有关，建议检查 MySQL、连接池和网络连通性。"}],'
    '"possible_causes":["数据库连接超时"],'
    '"troubleshooting_steps":["检查数据库"],'
    '"references":[],"confidence":"medium"}'
)


class FakeModel:
    def __init__(self, responses):
        self.responses = list(responses)

    def bind_tools(self, tools):
        return self

    def invoke(self, messages):
        if not self.responses:
            raise AssertionError("FakeModel 没有预置更多响应")
        return self.responses.pop(0)


def make_state() -> dict:
    return {
        "run_id": "run-log-1",
        "owner_user_id": 1,
        "title": "订单服务故障",
        "input_content": LOG_TEXT,
        "knowledge_base_id": 3,
        "top_k": 5,
        "messages": [],
        "observations": [],
        "steps": [],
        "iteration": 0,
        "max_iterations": 4,
        "status": "running",
        "error": None,
        "report": None,
    }


def capture_logs() -> io.StringIO:
    """Point the shared logger's handler at a buffer for the duration of a test."""

    logger = configure_logging()
    buffer = io.StringIO()
    for handler in logger.handlers:
        handler.stream = buffer
    return buffer


# --------------------------------------------------------------------------
# Formatter and sanitizer
# --------------------------------------------------------------------------


def test_truncate_caps_length_and_reports_the_original_size():
    short = truncate("abc")
    long = truncate("x" * 500)

    assert short == "abc"
    assert long.startswith("x" * 120)
    assert "共 500 字符" in long


def test_sanitize_masks_secret_fields_at_any_depth():
    payload = {
        "run_id": "r1",
        "password": "devpass123",
        "nested": {"api_key": SECRET, "token": "abc", "safe": "keep me"},
        "items": [{"secret": "s", "tool": "analyze_log"}],
    }

    cleaned = sanitize(payload)

    assert cleaned["run_id"] == "r1"
    assert cleaned["password"] == REDACTED
    assert cleaned["nested"]["api_key"] == REDACTED
    assert cleaned["nested"]["token"] == REDACTED
    assert cleaned["nested"]["safe"] == "keep me"
    assert cleaned["items"][0]["secret"] == REDACTED
    assert cleaned["items"][0]["tool"] == "analyze_log"


def test_sanitize_truncates_long_free_text():
    cleaned = sanitize({"error": "e" * 1000})

    assert len(str(cleaned["error"])) < 200


def test_formatter_emits_one_json_object_with_the_extra_fields():
    record = logging.LogRecord(
        name="incident_agent.test",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="工具调用完成",
        args=(),
        exc_info=None,
    )
    record.run_id = "run-1"
    record.tool_name = "analyze_log"
    record.duration_ms = 42
    record.password = "devpass123"

    payload = json.loads(JsonLogFormatter().format(record))

    assert payload["message"] == "工具调用完成"
    assert payload["level"] == "INFO"
    assert payload["run_id"] == "run-1"
    assert payload["tool_name"] == "analyze_log"
    assert payload["duration_ms"] == 42
    assert payload["password"] == REDACTED


def test_configure_logging_is_idempotent():
    first = configure_logging()
    count_after_first = len(first.handlers)
    second = configure_logging()

    assert first is second
    assert len(second.handlers) == count_after_first == 1
    assert second.propagate is False


def test_configure_logging_can_emit_plain_text():
    logger = configure_logging(fmt="text")
    try:
        assert not isinstance(logger.handlers[0].formatter, JsonLogFormatter)
    finally:
        configure_logging(fmt="json")


# --------------------------------------------------------------------------
# Graph: durations and sanitized step summaries
# --------------------------------------------------------------------------


def run_graph_with_two_tools():
    model = FakeModel(
        [
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "search_knowledge",
                        "args": {"query": "订单服务 502"},
                        "id": "c1",
                    }
                ],
            ),
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "analyze_log",
                        "args": {"log_text": LOG_TEXT},
                        "id": "c2",
                    }
                ],
            ),
            AIMessage(content="证据已足够。"),
            AIMessage(content=VALID_REPORT),
        ]
    )
    graph = build_graph(
        model=model,
        report_model=FakeModel([AIMessage(content=VALID_REPORT)]),
        tools=build_tools(MockRagGateway()),
    )
    return graph.invoke(make_state())


def test_every_tool_step_records_a_duration():
    capture_logs()
    result = run_graph_with_two_tools()

    tool_steps = [s for s in result["steps"] if s.get("action") == "tool_call"]
    assert len(tool_steps) == 2
    assert all(isinstance(s["duration_ms"], int) for s in tool_steps)
    assert all(s["duration_ms"] >= 0 for s in tool_steps)


def test_model_request_steps_record_a_duration():
    capture_logs()
    result = run_graph_with_two_tools()

    model_steps = [s for s in result["steps"] if s.get("action") == "model_request"]
    assert model_steps
    assert all(isinstance(s["duration_ms"], int) for s in model_steps)


def test_tool_arguments_summary_never_contains_the_raw_text():
    """The summary records the *redacted* length, which is what the model saw."""

    capture_logs()
    result = run_graph_with_two_tools()

    tool_steps = {s["tool_name"]: s for s in result["steps"] if s.get("action") == "tool_call"}

    recorded_length = tool_steps["analyze_log"]["arguments_summary"]["log_text_length"]
    # 凭据在进入模型前已被掩码，所以记录的长度接近原始长度但不相等；
    # 关键是它小于原文，证明送进工具的不是未脱敏文本。
    assert 0 < recorded_length < len(LOG_TEXT)
    assert tool_steps["search_knowledge"]["arguments_summary"] == {
        "query_length": len("订单服务 502")
    }

    blob = json.dumps(result["steps"], ensure_ascii=False)
    assert LOG_TEXT not in blob
    assert "devpass123" not in blob
    assert SECRET not in blob


def test_tool_result_summary_keeps_counts_not_content():
    capture_logs()
    result = run_graph_with_two_tools()

    tool_steps = {s["tool_name"]: s for s in result["steps"] if s.get("action") == "tool_call"}

    log_summary = tool_steps["analyze_log"]["result_summary"]
    assert log_summary["ok"] is True
    assert log_summary["signal_count"] == 3
    assert set(log_summary["signal_types"]) == {
        "database_error",
        "http_5xx",
        "timeout",
    }

    search_summary = tool_steps["search_knowledge"]["result_summary"]
    assert search_summary["source_count"] == 1
    assert search_summary["document_ids"] == [10]


def test_logs_are_json_lines_that_share_one_run_id():
    buffer = capture_logs()
    result = run_graph_with_two_tools()

    lines = [line for line in buffer.getvalue().splitlines() if line.strip()]
    assert lines, "运行过程中应该产生日志"
    payloads = [json.loads(line) for line in lines]

    assert all(isinstance(payload, dict) for payload in payloads)
    assert all(payload.get("run_id") == result["run_id"] for payload in payloads)
    assert {"agent", "observe", "report"} <= {
        payload.get("node") for payload in payloads
    }


def test_logs_never_contain_credentials_or_raw_incident_text():
    buffer = capture_logs()
    run_graph_with_two_tools()

    logs = buffer.getvalue()

    assert SECRET not in logs
    assert "devpass123" not in logs
    assert LOG_TEXT not in logs
    assert TOKEN not in logs


def test_tool_failure_is_logged_with_its_error_code():
    buffer = capture_logs()
    model = FakeModel(
        [
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "get_service_status",
                        "args": {"service_name": "gateway"},
                        "id": "c-fail",
                    }
                ],
            )
        ]
    )
    graph = build_graph(
        model=model,
        report_model=FakeModel([]),
        tools=build_tools(MockRagGateway()),
    )

    result = graph.invoke(make_state())

    assert result["status"] == "degraded"
    payloads = [json.loads(line) for line in buffer.getvalue().splitlines() if line.strip()]
    failed = [p for p in payloads if p.get("status") == "failed"]
    assert any(p.get("error_code") == "UNKNOWN_SERVICE" for p in failed)


# --------------------------------------------------------------------------
# analyze_log: matched fragment, line number, explicit boundaries
# --------------------------------------------------------------------------


def signals_of(text: str) -> list[dict]:
    result = analyze_log(text)
    assert result["ok"] is True
    return result["data"]["signals"]


def types_of(text: str) -> set[str]:
    return {signal["type"] for signal in signals_of(text)}


def test_analyze_log_reports_line_numbers_and_fragments():
    signals = signals_of("line one ok\nMySQL connection timeout\nHTTP 502\n")

    by_type = {signal["type"]: signal for signal in signals}

    assert by_type["database_error"]["line_number"] == 2
    assert by_type["timeout"]["line_number"] == 2
    assert by_type["http_5xx"]["line_number"] == 3
    assert by_type["http_5xx"]["matched_text"] == "502"
    assert "第 3 行" in by_type["http_5xx"]["value"]


def test_timeout_only_log_is_detected_without_database_keywords():
    """Design doc case 2: `timeout` with no database keyword at all."""

    found = types_of("gateway timeout after 30s")

    assert "timeout" in found
    assert "database_error" not in found


def test_order_id_containing_502_is_not_a_5xx_signal():
    assert "http_5xx" not in types_of("order_id=15020304567 查询超时")


def test_502_with_separators_matches():
    assert "http_5xx" in types_of("502-Bad Gateway from upstream")
    assert "http_5xx" in types_of("HTTP/1.1 502")


def test_other_5xx_codes_are_covered():
    assert "http_5xx" in types_of("503 Service Unavailable")
    assert "http_5xx" in types_of("upstream returned 504")


def test_signals_are_capped_per_type():
    noisy = "\n".join(f"HTTP 502 attempt {index}" for index in range(20))

    signals = signals_of(noisy)

    assert len(signals) <= 3 * 3  # MAX_SIGNALS_PER_TYPE × number of types


def test_analyze_log_still_rejects_empty_input():
    result = analyze_log("")

    assert result["ok"] is False
    assert result["error_code"] == "INVALID_ARGUMENTS"
