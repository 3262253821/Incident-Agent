"""Tests for model timeouts, the request budget and error normalization (P0-4-1).

Three separate concerns:

- ``create_chat_model`` must not inherit the SDK's 600s timeout / 2 retries;
- both model-calling nodes must respect the shared request deadline;
- SDK exceptions must become ``MODEL_*`` codes instead of leaking to the caller.

设计文档章节：§11.4 超时和重试（含「已实现：模型超时、请求预算与错误归一化」）。
"""

from __future__ import annotations

import httpx
import openai
import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from app.incident_agent.core.config import Settings
from app.incident_agent.core.errors import (
    AGENT_INTERNAL_ERROR,
    MODEL_AUTH_ERROR,
    MODEL_RATE_LIMITED,
    MODEL_TIMEOUT,
    MODEL_UNAVAILABLE,
    REQUEST_TIMEOUT,
    describe_model_error,
)
from app.incident_agent.core.statuses import RunStatus
from app.incident_agent.graph.deadline import (
    MESSAGE as DEADLINE_MESSAGE,
)
from app.incident_agent.graph.deadline import (
    RequestDeadline,
    RequestTimeoutError,
)
from app.incident_agent.graph.workflow import build_graph
from app.incident_agent.services.llm import create_chat_model
from app.incident_agent.services.rag_client import MockRagGateway
from app.incident_agent.services.tools import build_tools

VALID_REPORT = (
    '{"summary":"订单服务 502。","category":"database",'
    '"evidence":[{"source":"fault_log","detail":"日志命中 502 与 timeout。"}],'
    '"possible_causes":["数据库连接超时"],'
    '"troubleshooting_steps":["检查数据库"],'
    '"references":[],"confidence":"medium"}'
)


def _request() -> httpx.Request:
    return httpx.Request("POST", "https://api.deepseek.com/chat/completions")


def _settings(**overrides) -> Settings:
    base = dict(
        agent_host="127.0.0.1",
        agent_port=8001,
        model="deepseek-chat",
        model_base_url="https://api.deepseek.com",
        model_timeout_seconds=30.0,
        request_timeout_seconds=90.0,
        devatlas_base_url="http://127.0.0.1:8000",
        devatlas_timeout_seconds=20.0,
        max_iterations=4,
        default_top_k=5,
        database_url="sqlite+pysqlite:///:memory:",
        web_origins=("http://127.0.0.1:5174",),
    )
    base.update(overrides)
    return Settings(**base)


class FakeModel:
    """Model double that either returns canned replies or raises."""

    def __init__(self, responses=None, raises: BaseException | None = None):
        self.responses = list(responses or [])
        self.raises = raises
        self.invoke_count = 0

    def bind_tools(self, tools):
        return self

    def invoke(self, messages):
        self.invoke_count += 1
        if self.raises is not None:
            raise self.raises
        if not self.responses:
            raise AssertionError("FakeModel 没有预置更多响应")
        return self.responses.pop(0)


def make_state(**overrides) -> dict:
    state = {
        "run_id": "run-timeout-1",
        "owner_user_id": 1,
        "title": "订单服务故障",
        "input_content": "网关返回 502",
        "knowledge_base_id": 3,
        "top_k": 5,
        "messages": [
            SystemMessage(content="你是故障分析助手。"),
            HumanMessage(content="网关返回 502"),
        ],
        "observations": [],
        "steps": [],
        "iteration": 0,
        "max_iterations": 4,
        "status": RunStatus.RUNNING,
        "error": None,
        "report": None,
    }
    state.update(overrides)
    return state


def observation() -> dict:
    return {
        "iteration": 1,
        "tool_name": "analyze_log",
        "tool_call_id": "call-log",
        "result": {
            "ok": True,
            "data": {"signals": [{"type": "http_502"}], "signal_count": 1},
            "error_code": None,
            "error": None,
        },
    }


# --------------------------------------------------------------------------
# Model client configuration
# --------------------------------------------------------------------------


def test_model_client_sets_explicit_timeout_and_disables_retries(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    captured: dict = {}

    import app.incident_agent.services.llm as llm_module

    class CapturingChatOpenAI:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr(llm_module, "ChatOpenAI", CapturingChatOpenAI)

    create_chat_model(_settings(model_timeout_seconds=30.0))

    assert captured["max_retries"] == 0
    assert captured["timeout"] == (5.0, 30.0)
    assert captured["model"] == "deepseek-chat"
    assert captured["temperature"] == 0.1


def test_model_client_timeout_shrinks_for_a_tiny_budget(monkeypatch):
    """A connect timeout longer than the read timeout makes no sense."""

    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    captured: dict = {}

    import app.incident_agent.services.llm as llm_module

    class CapturingChatOpenAI:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr(llm_module, "ChatOpenAI", CapturingChatOpenAI)

    create_chat_model(_settings(model_timeout_seconds=2.0))

    assert captured["timeout"] == 2.0


def test_model_client_requires_an_api_key(monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    with pytest.raises(RuntimeError, match="DEEPSEEK_API_KEY"):
        create_chat_model(_settings())


# --------------------------------------------------------------------------
# Error normalization
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("exception", "expected_code"),
    [
        (openai.APITimeoutError(request=_request()), MODEL_TIMEOUT),
        (
            openai.RateLimitError(
                "rl",
                response=httpx.Response(429, request=_request()),
                body=None,
            ),
            MODEL_RATE_LIMITED,
        ),
        (openai.APIConnectionError(request=_request()), MODEL_UNAVAILABLE),
        (
            openai.AuthenticationError(
                "bad",
                response=httpx.Response(401, request=_request()),
                body=None,
            ),
            MODEL_AUTH_ERROR,
        ),
        (TimeoutError("slow"), MODEL_TIMEOUT),
        (ValueError("unexpected"), AGENT_INTERNAL_ERROR),
    ],
)
def test_sdk_exceptions_map_to_safe_error_codes(exception, expected_code):
    error_code, message = describe_model_error(exception)

    assert error_code == expected_code
    # 返回的说明必须是固定文案，绝不能是 str(exc)。
    assert str(exception) not in message


# --------------------------------------------------------------------------
# Request deadline
# --------------------------------------------------------------------------


def test_deadline_disabled_when_no_budget_is_configured():
    deadline = RequestDeadline(None)

    assert deadline.enabled is False
    assert deadline.remaining_seconds is None
    deadline.check()  # 不应抛异常


def test_deadline_raises_once_the_budget_is_gone():
    deadline = RequestDeadline.expired()

    with pytest.raises(RequestTimeoutError) as excinfo:
        deadline.check()

    assert excinfo.value.error_code == REQUEST_TIMEOUT
    assert excinfo.value.message == DEADLINE_MESSAGE


def test_agent_node_stops_calling_the_model_when_the_budget_is_gone():
    """The model must not be invoked at all once the deadline has passed."""

    model = FakeModel([AIMessage(content="不应该被调用")])
    graph = build_graph(
        model=model,
        report_model=FakeModel([]),
        tools=build_tools(MockRagGateway()),
        deadline=RequestDeadline.expired(),
    )

    result = graph.invoke(make_state())

    assert model.invoke_count == 0
    assert result["status"] == RunStatus.DEGRADED
    assert DEADLINE_MESSAGE in result["error"]
    assert REQUEST_TIMEOUT in result["error"]  # 归一化错误码进入 error 文案
    assert result["report"] is None
    assert result["degraded_summary"]["reason"] == RunStatus.DEGRADED
    assert "超过了请求时间预算" in result["degraded_summary"]["suggestions"][0]


def test_report_node_also_respects_the_budget():
    """A finished agent round must not start the report round past the budget."""

    model = FakeModel([AIMessage(content="无需工具，直接给结论。")])
    graph = build_graph(
        model=model,
        report_model=FakeModel([AIMessage(content=VALID_REPORT)]),
        tools=build_tools(MockRagGateway()),
        deadline=None,
    )
    # 先确认没有 deadline 时能正常跑完，再换成已过期的 deadline。
    assert graph.invoke(make_state())["status"] == RunStatus.INSUFFICIENT_EVIDENCE

    report_model = FakeModel([AIMessage(content=VALID_REPORT)])
    graph_with_deadline = build_graph(
        model=FakeModel([AIMessage(content="无需工具。")]),
        report_model=report_model,
        tools=build_tools(MockRagGateway()),
        deadline=RequestDeadline.expired(),
    )

    result = graph_with_deadline.invoke(make_state(observations=[observation()]))

    assert report_model.invoke_count == 0
    assert result["status"] == RunStatus.DEGRADED
    assert REQUEST_TIMEOUT in result["error"]


def test_model_failure_inside_the_agent_node_is_normalized():
    model = FakeModel(raises=openai.APITimeoutError(request=_request()))
    graph = build_graph(
        model=model,
        report_model=FakeModel(raises=openai.APITimeoutError(request=_request())),
        tools=build_tools(MockRagGateway()),
    )

    result = graph.invoke(make_state())

    assert result["status"] == RunStatus.DEGRADED
    assert result["report"] is None
    assert result["error"] == "调用模型超时（MODEL_TIMEOUT）"
    assert "Request timed out" not in str(result)
    steps = [step for step in result["steps"] if step["action"] == "call_model"]
    assert steps and steps[0]["error_code"] == MODEL_TIMEOUT


def test_rate_limit_failure_is_distinguishable_from_a_timeout():
    model = FakeModel(
        raises=openai.RateLimitError(
            "rl",
            response=httpx.Response(429, request=_request()),
            body=None,
        )
    )
    graph = build_graph(
        model=model,
        report_model=FakeModel(
            raises=openai.RateLimitError(
                "rl",
                response=httpx.Response(429, request=_request()),
                body=None,
            )
        ),
        tools=build_tools(MockRagGateway()),
    )

    result = graph.invoke(make_state())

    assert MODEL_RATE_LIMITED in result["error"]
    assert "稍后重试" in result["degraded_summary"]["suggestions"][0]


def test_evidence_obtained_before_the_failure_is_still_summarized():
    """A timeout after a successful tool call must keep that evidence."""

    model = FakeModel(
        [
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "analyze_log",
                        "args": {"log_text": "502 mysql timeout"},
                        "id": "call-log",
                    }
                ],
            )
        ],
    )

    class FailAfterFirst(FakeModel):
        def invoke(self, messages):
            self.invoke_count += 1
            if self.invoke_count == 1:
                return self.responses.pop(0)
            raise openai.APITimeoutError(request=_request())

    graph = build_graph(
        model=FailAfterFirst(list(model.responses)),
        report_model=FakeModel(raises=openai.APITimeoutError(request=_request())),
        tools=build_tools(MockRagGateway()),
    )

    result = graph.invoke(make_state())

    assert result["status"] == RunStatus.DEGRADED
    assert len(result["observations"]) == 1
    summary = result["degraded_summary"]
    assert summary["successful_tools"] == ["analyze_log"]
    assert summary["log_signals"]


def test_unknown_failure_does_not_leak_the_exception_text():
    secret = "sk-should-never-appear-in-the-response"
    model = FakeModel(raises=ValueError(f"boom {secret}"))
    graph = build_graph(
        model=model,
        report_model=FakeModel(raises=ValueError(f"boom {secret}")),
        tools=build_tools(MockRagGateway()),
    )

    result = graph.invoke(make_state())

    assert result["status"] == RunStatus.DEGRADED
    assert secret not in str(result)
    assert AGENT_INTERNAL_ERROR in result["error"]


def test_step_error_code_is_recorded_for_a_deadline_stop():
    graph = build_graph(
        model=FakeModel([AIMessage(content="不应调用")]),
        report_model=FakeModel([]),
        tools=build_tools(MockRagGateway()),
        deadline=RequestDeadline.expired(),
    )

    result = graph.invoke(make_state())

    codes = [
        step.get("error_code")
        for step in result["steps"]
        if step.get("action") == "call_model"
    ]
    assert codes and set(codes) == {REQUEST_TIMEOUT}
    assert result["degraded_summary"]["failed_tools"] == []
