"""设计文档 §17.2「最少 10 条案例」的图级覆盖 + §16.1 大输入。

§17.2 列了十条必须有的案例。这一份文件把**此前没有自动化覆盖**的那几条落到可执行
断言上，并在每条的 docstring 里写明对应案例号；已有覆盖的案例在
``docs/测试对照-设计文档章节.md`` 的对照表里指向原测试，不重复写一遍：

```text
案例 1  正常分析              test_graph_workflow.test_graph_normal_path_runs_tool_observe_and_report
案例 2  timeout 无数据库关键词 本文件 test_case_02_...
案例 3  未知服务名            本文件 test_case_03_...（工具层另有 test_tools_adapters）
案例 4  空日志 / 缺少标题      tests/test_input_boundaries.py（含超长与大输入）
案例 5  知识库无相关内容       本文件 test_case_05_...
案例 6  检索工具抛异常         本文件 test_case_06_...
案例 7  服务状态工具超时       本文件 test_case_07_...（该工具是本地 mock，见其 docstring）
案例 8  报告非法 JSON          test_graph_workflow + test_report_repair
案例 9  重复请求相同工具       本文件 test_case_09_...
案例 10 达到最大循环次数       test_graph_workflow.test_graph_stops_at_max_model_iterations
```
"""

from __future__ import annotations

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.incident_agent.db.session import Base
from app.incident_agent.graph.workflow import build_graph
from app.incident_agent.schemas.auth import UserPublic
from app.incident_agent.schemas.incident import IncidentAnalyzeRequest
from app.incident_agent.services.authorizer import StaticKnowledgeBaseAuthorizer
from app.incident_agent.services.incident import execute_incident
from app.incident_agent.services.rag_client import MockRagGateway
from app.incident_agent.services.tools import build_tools

FAULT_LOG_REPORT = (
    '{"summary":"日志显示请求超时，且未出现数据库相关信号。",'
    '"category":"network",'
    '"evidence":[{"source":"fault_log","detail":"日志命中 timeout 信号。"}],'
    '"possible_causes":["上游连接超时"],'
    '"troubleshooting_steps":["检查上游响应耗时"],'
    '"references":[],"confidence":"medium"}'
)

KB_CLAIM_REPORT = (
    '{"summary":"知识库手册指出了根因。","category":"database",'
    '"evidence":[{"source":"knowledge_base","detail":"手册说明连接池配置过小。"}],'
    '"possible_causes":["连接池耗尽"],'
    '"troubleshooting_steps":["扩大连接池"],'
    '"references":[],"confidence":"high"}'
)


class FakeModel:
    """Deterministic model double (same shape the other graph tests use)."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.last_response = None

    def bind_tools(self, tools):
        return self

    def invoke(self, messages):
        if not self.responses:
            if self.last_response is None:
                raise AssertionError("FakeModel 没有预置任何响应")
            return self.last_response
        self.last_response = self.responses.pop(0)
        return self.last_response


def make_state(content: str = "订单服务返回 502，MySQL 连接超时") -> dict:
    return {
        "run_id": "run-case",
        "owner_user_id": 1,
        "title": "订单服务故障",
        "input_content": content,
        "knowledge_base_id": 3,
        "top_k": 5,
        "messages": [
            SystemMessage(content="你是故障分析助手。"),
            HumanMessage(content=content),
        ],
        "observations": [],
        "steps": [],
        "iteration": 0,
        "max_iterations": 4,
        "status": "running",
        "error": None,
        "report": None,
    }


def tool_call(name: str, arguments: dict, call_id: str) -> AIMessage:
    return AIMessage(
        content="",
        tool_calls=[{"name": name, "args": arguments, "id": call_id}],
    )


# --------------------------------------------------------------------------
# 案例 2：日志里有 timeout，但没有数据库关键词
# --------------------------------------------------------------------------


def test_case_02_timeout_only_log_completes_with_fault_log_evidence():
    """§17.2 案例 2 + §6.1：timeout 单独出现也要被识别成证据来源。

    "没有数据库关键词"是关键：如果信号识别只认 MySQL/连接池，这类故障就只能
    降级；这里断言 timeout 命中而 database_error 未命中，且报告仍然通过校验。
    """

    log_text = "gateway: upstream request timed out after 3000ms"
    agent_model = FakeModel(
        [
            tool_call("analyze_log", {"log_text": log_text}, "call-log"),
            AIMessage(content="证据已足够。"),
        ]
    )
    graph = build_graph(
        model=agent_model,
        report_model=FakeModel([AIMessage(content=FAULT_LOG_REPORT)]),
        tools=build_tools(MockRagGateway()),
    )

    result = graph.invoke(make_state(log_text))

    assert result["status"] == "completed"
    signals = result["observations"][0]["result"]["data"]["signals"]
    assert {signal["type"] for signal in signals} == {"timeout"}
    assert result["report"]["confidence"] == "medium"


# --------------------------------------------------------------------------
# 案例 3：未知服务名
# --------------------------------------------------------------------------


def test_case_03_unknown_service_degrades_with_a_concrete_suggestion():
    """§17.2 案例 3 + §16.5：失败降级要保留证据并给出下一步建议。"""

    agent_model = FakeModel(
        [tool_call("get_service_status", {"service_name": "gateway"}, "call-status")]
    )
    graph = build_graph(
        model=agent_model,
        report_model=FakeModel([]),
        tools=build_tools(MockRagGateway()),
    )

    result = graph.invoke(make_state("请检查 gateway 服务状态"))

    assert result["status"] == "degraded"
    assert result["report"] is None
    summary = result["degraded_summary"]
    assert summary["failed_tools"] == ["get_service_status"]
    assert summary["successful_tools"] == []
    assert summary["service_statuses"] == []
    assert any("mock" in item for item in summary["suggestions"])

    observation = result["observations"][0]
    assert observation["result"]["error_code"] == "UNKNOWN_SERVICE"
    step = [item for item in result["steps"] if item["action"] == "tool_call"][0]
    assert step["error_code"] == "UNKNOWN_SERVICE"
    assert step["status"] == "failed"


# --------------------------------------------------------------------------
# 案例 5：知识库无相关内容（检索成功但零来源）
# --------------------------------------------------------------------------


def test_case_05_empty_retrieval_cannot_be_reported_as_knowledge_base_evidence():
    """§17.2 案例 5 + §10.4：检索返回 0 条来源时，模型不能靠它写结论。

    ``no_results`` 是**成功**的检索（``ok=True``、``sources=[]``）。模型却拿着
    它写了一条 knowledge_base 证据 —— 服务端核验必须剔除，整份报告只剩零条
    可核实证据，于是状态是 ``insufficient_evidence`` 而不是 ``completed``。
    """

    agent_model = FakeModel(
        [
            tool_call("search_knowledge", {"query": "连接池耗尽"}, "call-search"),
            AIMessage(content="证据已足够。"),
        ]
    )
    graph = build_graph(
        model=agent_model,
        report_model=FakeModel([AIMessage(content=KB_CLAIM_REPORT)]),
        tools=build_tools(MockRagGateway(mode="no_results")),
    )

    result = graph.invoke(make_state("连接池相关故障"))

    observation = result["observations"][0]
    assert observation["result"]["ok"] is True
    assert observation["result"]["data"]["sources"] == []

    assert result["status"] == "insufficient_evidence"
    assert result["report"] is None
    assert "不再返回结论" in result["error"]
    assert "knowledge_base×1" in result["error"]
    assert result["degraded_summary"]["knowledge_base_sources"] == []


# --------------------------------------------------------------------------
# 案例 6 / 7：检索工具抛异常、检索超时
# --------------------------------------------------------------------------


def _run_search_case(mode: str):
    agent_model = FakeModel(
        [tool_call("search_knowledge", {"query": "订单服务 502"}, "call-search")]
    )
    graph = build_graph(
        model=agent_model,
        report_model=FakeModel([]),
        tools=build_tools(MockRagGateway(mode=mode)),
    )
    return graph.invoke(make_state("订单服务 502"))


def test_case_06_search_tool_exception_degrades_with_a_normalized_code():
    """§17.2 案例 6 + §16.2：工具异常必须归一化，不能把 traceback 交给用户。"""

    result = _run_search_case("unavailable")

    assert result["status"] == "degraded"
    assert "Traceback" not in result["error"]
    assert "site-packages" not in result["error"]
    observation = result["observations"][0]
    assert observation["result"]["error_code"] == "RAG_UNAVAILABLE"
    assert observation["result"]["error"] == "模拟 DevAtlas 不可用"
    assert any("DevAtlas" in item for item in result["degraded_summary"]["suggestions"])


def test_case_07_retrieval_timeout_is_reported_as_a_timeout():
    """§17.2 案例 7：超时必须是超时，而不是一句通用失败。

    设计文档写的是"服务状态工具超时"。``get_service_status`` 在 MVP 里是**进程内
    的 mock**（没有网络与 I/O），因此它不存在可复现的超时路径 —— 真正会超时的
    外部工具只有 ``search_knowledge``，所以案例 7 在这里用它覆盖；真实服务状态
    provider 属于 P2-5（清单里仍未做）。
    """

    result = _run_search_case("timeout")

    assert result["status"] == "degraded"
    observation = result["observations"][0]
    assert observation["result"]["error_code"] == "RAG_TIMEOUT"
    assert any("超时" in item for item in result["degraded_summary"]["suggestions"])


# --------------------------------------------------------------------------
# 案例 9：模型重复请求同一个工具
# --------------------------------------------------------------------------


def test_case_09_repeated_identical_tool_calls_are_recorded_and_bounded():
    """§17.2 案例 9 + §9.5：重复调用既不合并成一条，也不会无限循环。

    三次模型轮次都请求**完全相同**的 analyze_log 调用：第三次轮次触到上限，因此
    真正执行的是前两次。断言两次都留下了自己的 observation 与步骤（工具不会
    因为参数相同就"去重"），并且迭代次数被上限截住。
    """

    def same_call(call_id: str) -> AIMessage:
        return tool_call("analyze_log", {"log_text": "502"}, call_id)

    agent_model = FakeModel(
        [same_call("call-1"), same_call("call-2"), same_call("call-3")]
    )
    graph = build_graph(
        model=agent_model,
        report_model=FakeModel([]),
        tools=build_tools(MockRagGateway()),
        max_iterations=3,
    )

    result = graph.invoke(make_state())

    assert result["status"] == "max_iterations"
    assert result["iteration"] == 3
    assert len(result["observations"]) == 2
    assert [item["tool_call_id"] for item in result["observations"]] == [
        "call-1",
        "call-2",
    ]
    tool_steps = [item for item in result["steps"] if item["action"] == "tool_call"]
    assert [item["tool_call_id"] for item in tool_steps] == ["call-1", "call-2"]
    assert {item["arguments_summary"]["log_text_length"] for item in tool_steps} == {3}


# --------------------------------------------------------------------------
# §16.2 另一条真实边界：模型传了缺参数的调用
# --------------------------------------------------------------------------


def test_model_tool_call_with_a_missing_argument_is_normalized_not_crashed():
    """模型传的调用缺必填参数时，链路不能崩，也不能把裸异常当结果。

    LangChain 在进入工具函数体之前就用参数 schema 拒绝了这次调用，
    ``ToolNode`` 把它变成一条错误 ``ToolMessage``，``observe`` 再归一化成
    ``INVALID_TOOL_RESULT``。这条链路此前没有测试，属于 §16.2 的"工具异常必须
    转换为统一 ToolResult"。
    """

    agent_model = FakeModel(
        [tool_call("analyze_log", {"wrong_field": "502"}, "call-bad")]
    )
    graph = build_graph(
        model=agent_model,
        report_model=FakeModel([]),
        tools=build_tools(MockRagGateway()),
    )

    result = graph.invoke(make_state())

    assert result["status"] == "degraded"
    observation = result["observations"][0]
    assert observation["tool_name"] == "analyze_log"
    assert observation["result"]["ok"] is False
    assert observation["result"]["error_code"] == "INVALID_TOOL_RESULT"
    step = [item for item in result["steps"] if item["action"] == "tool_call"][0]
    assert step["status"] == "failed"


# --------------------------------------------------------------------------
# §16.1 大输入：20_000 字的日志端到端
# --------------------------------------------------------------------------


def test_large_log_run_stays_bounded_and_never_echoes_the_input():
    """§16.1 + §12.1 + §15.2：日志上限内的最大输入不会原样回到响应里。

    用 API 允许的最大日志（20_000 字）跑完整服务：信号按类型封顶（每类 3 条），
    步骤只保存 ``log_text_length``，响应体里既没有日志原文也没有那个唯一标记。
    """

    marker = "MARKER-9f2c1a"
    unit = f"{marker} 2026-09-15 ERROR 502 mysql connection timeout\n"
    # 恰好用满 API 允许的 20_000 字（§16.1 的上限是包含边界）。
    log_text = (unit * 400)[:20_000]
    assert len(log_text) == 20_000

    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    user = UserPublic(
        id=1,
        username="test-user",
        role="user",
        is_active=True,
        created_at="2026-09-04T00:00:00Z",
        updated_at="2026-09-04T00:00:00Z",
    )
    model = FakeModel(
        [
            tool_call("analyze_log", {"log_text": log_text}, "call-log"),
            AIMessage(content="证据已足够。"),
            AIMessage(content=FAULT_LOG_REPORT),
        ]
    )

    with Session() as db:
        response = execute_incident(
            db,
            user=user,
            request=IncidentAnalyzeRequest(
                title="大日志分析",
                content=log_text,
                knowledge_base_id=3,
            ),
            access_token="test-token",
            model=model,
            rag_gateway=MockRagGateway(),
            knowledge_base_authorizer=StaticKnowledgeBaseAuthorizer(),
        )

    assert response.status == "completed"

    # 每类信号最多 3 条：5xx / timeout / database_error 各命中 3 条 = 9。
    signals = response.observations[0]["result"]["data"]["signals"]
    assert len(signals) == 9
    assert {signal["type"] for signal in signals} == {
        "http_5xx",
        "timeout",
        "database_error",
    }
    assert all(signal["line_number"] is not None for signal in signals)

    tool_step = [step for step in response.steps if step["action"] == "tool_call"][0]
    assert tool_step["arguments_summary"] == {"log_text_length": len(log_text)}

    body = response.model_dump_json()
    assert marker not in body
    # 参数摘要里只有长度这一个键，没有原文（上面已断言）。
    assert set(tool_step["arguments_summary"]) == {"log_text_length"}
    # 20_000 字输入没有把响应撑大：整个响应远小于输入本身。
    assert len(body) < len(log_text)
