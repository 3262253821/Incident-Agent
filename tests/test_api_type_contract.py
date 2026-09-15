"""前后端类型契约测试（P1-5-2）。

设计文档章节：§13.1 API 一览、§13.3 API 状态码（前后端契约一致性属 P1-5-2）。

P1-5-2 的要求是「由 OpenAPI 生成 TS 类型，**或在 CI 比对手写类型**」。这里选后者，
理由是前端 `web/src/types/api.ts` 是手写的、只覆盖实际用到的接口，而生成器会引入
新依赖并把整份 spec 变成第二份真相；比对则用同一份 pytest 门禁（CI 后端 job）。

比对分两类，覆盖了 `web/src/types/api.ts` 里的**每一个**接口：

1. **有 Pydantic 模型的接口**（13 个）逐字段比对 `app.openapi()` 的组件 schema：
   字段集合必须完全相等（缺失=真实漂移、多出=死字段）、可空性一致、枚举取值一致，
   并且**响应字段不许写成可选**——FastAPI 会把模型声明的每个键都下发，空值就是
   `null`，写成 `?` 会让"键不存在"和"值是 null"看起来一样。
2. **后端没有模型的载荷**（`AgentStep` / `Observation` / `ToolResult`）用**真实载荷**
   比对：跑一次真实 Graph，把 `POST /analyze`（`_response_from_state`）与
   `GET /runs/{id}`（`append_steps` 落库后 `_to_response`）两条路径的步骤逐字段比较，
   再与 TS 接口的字段集合对齐。这比 schema 比对更强——它顺带证明**两个接口回答的是
   同一个形状**（P1-5-2 修掉的正是这里：analyze 曾经透出 `state["steps"]` 原样，泄漏
   `_started_at`/`ok`/`attempts`/`tool_call_count`/`unverified_count`，且没有
   `step_index`）。
3. `RunHistoryQuery` 比对 `GET /api/v1/runs` 的查询参数名。

`test_contract_rules_catch_synthetic_drift` 用合成样例证明比对规则抓得到真实漂移，
`test_typescript_parser_rejects_inline_object_types` 保证解析器不会静默漏读字段。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from langchain_core.messages import AIMessage
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.incident_agent.db.session import Base
from app.incident_agent.graph.workflow import build_graph
from app.incident_agent.routers.runs import _to_response
from app.incident_agent.schemas.incident import RunSummary
from app.incident_agent.services.incident import _response_from_state
from app.incident_agent.services.rag_client import MockRagGateway
from app.incident_agent.services.storage import append_steps, create_run
from app.incident_agent.services.tools import build_tools
from app.main import app as fastapi_app

PROJECT_ROOT = Path(__file__).resolve().parents[1]
TS_FILE = PROJECT_ROOT / "web" / "src" / "types" / "api.ts"

_FIELD = re.compile(r"^(?P<name>[A-Za-z_][A-Za-z0-9_]*)(?P<optional>\?)?: (?P<type>.+)$")

VALID_REPORT = (
    '{"summary":"订单服务 502。","category":"database",'
    '"evidence":[{"source":"knowledge_base","detail":'
    '"订单服务返回 502 可能与数据库连接超时有关，建议检查 MySQL、连接池和网络连通性。"}],'
    '"possible_causes":["数据库连接超时"],'
    '"troubleshooting_steps":["检查数据库"],'
    '"references":[],"confidence":"medium"}'
)
LOG_TEXT = "502 mysql timeout password=devpass123"


# --------------------------------------------------------------------------
# TypeScript 侧：接口解析
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class TsField:
    type: str
    optional: bool
    line: int


@dataclass(frozen=True)
class TsInterface:
    name: str
    fields: dict[str, TsField]

    @property
    def names(self) -> set[str]:
        return set(self.fields)


def parse_typescript_interfaces(source: str, *, label: str = "api.ts") -> dict[str, TsInterface]:
    """Parse flat ``export interface`` blocks into ``{name: (type, optional)}``.

    Deliberately strict: an inline object type, a duplicate field or an unparsable
    line raises instead of being skipped, because a silently half-parsed interface
    would make every contract assertion below vacuous.
    """

    interfaces: dict[str, TsInterface] = {}
    current: str | None = None
    fields: dict[str, TsField] = {}

    for number, raw in enumerate(source.splitlines(), start=1):
        line = raw.strip()
        if current is None:
            opener = re.match(r"^export interface (\w+) \{$", line)
            if opener:
                current = opener.group(1)
                fields = {}
            continue
        if line == "}":
            interfaces[current] = TsInterface(current, fields)
            current = None
            continue
        if not line or line.startswith("/") or line.startswith("*"):
            continue
        matched = _FIELD.match(line)
        if matched is None:
            raise AssertionError(f"{label}:{number} 解析不了这一行：{line!r}")
        type_text = matched.group("type").strip()
        if type_text.startswith("{") or type_text.endswith("{"):
            raise AssertionError(
                f"{label}:{number} 出现内联对象类型，请改成具名 interface：{line!r}"
            )
        name = matched.group("name")
        if name in fields:
            raise AssertionError(f"{label}:{number} {current}.{name} 重复定义")
        fields[name] = TsField(type_text, bool(matched.group("optional")), number)
    if current is not None:
        raise AssertionError(f"{label}: 接口 {current} 没有闭合的 }}")
    return interfaces


def load_typescript_interfaces() -> dict[str, TsInterface]:
    assert TS_FILE.is_file(), f"找不到前端类型文件：{TS_FILE}"
    return parse_typescript_interfaces(
        TS_FILE.read_text(encoding="utf-8"),
        label=TS_FILE.relative_to(PROJECT_ROOT).as_posix(),
    )


# --------------------------------------------------------------------------
# 后端侧：OpenAPI / 契约规则
# --------------------------------------------------------------------------


def _is_nullable(prop: dict[str, Any]) -> bool:
    if prop.get("type") == "null":
        return True
    return any(
        option.get("type") == "null"
        for key in ("anyOf", "oneOf")
        for option in prop.get(key, [])
    )


def _enum_values(prop: dict[str, Any]) -> set[str]:
    if prop.get("enum"):
        return {str(value) for value in prop["enum"]}
    if "const" in prop:
        return {str(prop["const"])}
    return set()


def _ts_union_members(type_text: str) -> set[str]:
    """`'a' | 'b' | null` → `{'a', 'b'}`；不是字符串字面量联合时返回空集。"""

    members = {part.strip() for part in type_text.split("|")}
    members.discard("null")
    if not members:
        return set()
    for member in members:
        if len(member) < 2 or member[0] not in "'\"" or member[-1] != member[0]:
            return set()
    return {member[1:-1] for member in members}


@dataclass(frozen=True)
class Binding:
    """One TS interface ↔ one OpenAPI component schema."""

    interface: str
    schema: str
    direction: str  # "response" | "request"
    skip: frozenset[str] = frozenset()


BINDINGS: tuple[Binding, ...] = (
    Binding("User", "UserPublic", "response"),
    Binding("LoginResponse", "TokenResponse", "response"),
    Binding("IncidentRequest", "IncidentAnalyzeRequest", "request"),
    Binding("KnowledgeBaseOption", "KnowledgeBaseOption", "response"),
    Binding("EvidenceItem", "EvidenceItem", "response"),
    Binding("UnverifiedEvidenceItem", "UnverifiedEvidenceItem", "response"),
    Binding("IncidentReport", "IncidentReport", "response"),
    Binding("DegradedLogSignal", "DegradedLogSignal", "response"),
    Binding("DegradedKnowledgeBaseSource", "DegradedKnowledgeBaseSource", "response"),
    Binding("DegradedSummary", "DegradedSummary", "response"),
    Binding("RunSummary", "RunSummary", "response"),
    Binding("RunHistoryPage", "RunSummaryPage", "response"),
    # 后端把轨迹存成 JSON dict，schema 只能描述成 array<object>，
    # 这两个字段的字段集合由下面的真实载荷测试负责。
    Binding("RunResponse", "RunResponse", "response", frozenset({"steps", "observations"})),
)

#: 后端没有对应 Pydantic 模型的接口，由真实载荷比对（见本模块 docstring 第 2 类）。
PAYLOAD_ONLY_INTERFACES = frozenset({"AgentStep", "Observation", "ToolResult"})
#: 只描述查询参数的接口，比对 `GET /api/v1/runs` 的 parameter 名。
QUERY_ONLY_INTERFACES = frozenset({"RunHistoryQuery"})


def compare_interface(
    interface: TsInterface,
    schema: dict[str, Any],
    *,
    direction: str,
    skip: frozenset[str] = frozenset(),
) -> list[str]:
    """Return human-readable problems; empty list means the two sides agree.

    Nullability is checked asymmetrically on purpose:

    - **响应**：载荷是什么样就必须写成什么样，可空性必须完全一致；
    - **请求**：客户端可以比后端更窄（例如后端允许 `top_k: int | None`，但前端永远
      发一个整数），反过来才是缺陷——TS 允许 `null`、后端却会 422。
    """

    properties = {
        name: prop
        for name, prop in (schema.get("properties") or {}).items()
        if name not in skip
    }
    required = set(schema.get("required") or ())
    fields = {name: spec for name, spec in interface.fields.items() if name not in skip}
    problems: list[str] = []

    for name in sorted(set(properties) - set(fields)):
        problems.append(f"{interface.name}.{name}：后端会下发，TS 类型里缺失")
    for name in sorted(set(fields) - set(properties)):
        problems.append(f"{interface.name}.{name}：TS 类型里有，后端不下发（死字段）")

    for name in sorted(set(fields) & set(properties)):
        prop, spec = properties[name], fields[name]
        backend_nullable = _is_nullable(prop)
        ts_nullable = "| null" in spec.type
        if direction == "response" and backend_nullable != ts_nullable:
            backend = "可空" if backend_nullable else "不可空"
            problems.append(
                f"{interface.name}.{name}：可空性不一致（后端{backend}，TS 是 `{spec.type}`）"
            )
        if direction == "request" and not backend_nullable and ts_nullable:
            problems.append(
                f"{interface.name}.{name}：后端不接受 null，TS 却允许（`{spec.type}`）"
            )
        enum = _enum_values(prop)
        if enum and _ts_union_members(spec.type) != enum:
            problems.append(
                f"{interface.name}.{name}：取值集合不一致"
                f"（后端 {sorted(enum)}，TS 是 `{spec.type}`）"
            )
        if direction == "response" and spec.optional:
            problems.append(
                f"{interface.name}.{name}：响应字段不能写成可选"
                "（FastAPI 总会下发该键，空值是 null）"
            )
        if direction == "request" and name in required and spec.optional:
            problems.append(f"{interface.name}.{name}：后端必填字段不能写成可选")
    return problems


def _report(problems: list[str]) -> str:
    return "前后端类型契约不一致：\n" + "\n".join(f"  - {line}" for line in problems)


# --------------------------------------------------------------------------
# 1) 与 OpenAPI schema 比对
# --------------------------------------------------------------------------


def test_typescript_interfaces_match_the_openapi_schemas():
    interfaces = load_typescript_interfaces()
    components = fastapi_app.openapi()["components"]["schemas"]

    problems: list[str] = []
    for binding in BINDINGS:
        assert binding.interface in interfaces, f"TS 类型里没有 {binding.interface}"
        assert binding.schema in components, f"OpenAPI 里没有 {binding.schema}"
        problems.extend(
            compare_interface(
                interfaces[binding.interface],
                components[binding.schema],
                direction=binding.direction,
                skip=binding.skip,
            )
        )

    assert not problems, _report(problems)


def test_every_typescript_interface_is_accounted_for():
    """新增接口必须显式归类，否则契约比对会悄悄漏掉它。"""

    interfaces = load_typescript_interfaces()
    covered = (
        {binding.interface for binding in BINDINGS}
        | set(PAYLOAD_ONLY_INTERFACES)
        | set(QUERY_ONLY_INTERFACES)
    )

    assert set(interfaces) == covered, (
        f"未归类：{sorted(set(interfaces) - covered)}；"
        f"已删除但仍登记：{sorted(covered - set(interfaces))}"
    )


def test_run_history_query_matches_the_list_endpoint_parameters():
    parameters = fastapi_app.openapi()["paths"]["/api/v1/runs"]["get"]["parameters"]
    query_names = {param["name"] for param in parameters if param["in"] == "query"}
    interfaces = load_typescript_interfaces()

    assert query_names == interfaces["RunHistoryQuery"].names


def test_response_models_always_emit_every_declared_field():
    """「响应字段不许可选」这条规则的依据，用真实序列化验证而不是假设。"""

    summary = RunSummary(
        run_id="run-1",
        title="订单服务故障",
        status="completed",
        knowledge_base_id=3,
        iteration=1,
        max_iterations=4,
        steps_count=2,
        observations_count=1,
    )
    payload = summary.model_dump(mode="json")

    declared = set(RunSummary.model_fields) | set(RunSummary.model_computed_fields)
    assert set(payload) == declared
    assert payload["error"] is None
    assert payload["interrupted"] is False
    assert payload["duration_ms"] is None


# --------------------------------------------------------------------------
# 2) 轨迹与观察：用真实载荷比对（这两个在后端是 JSON dict）
# --------------------------------------------------------------------------


class FakeModel:
    def __init__(self, responses: list[AIMessage]) -> None:
        self.responses = list(responses)

    def bind_tools(self, tools: Any) -> FakeModel:
        return self

    def invoke(self, messages: Any) -> AIMessage:
        return self.responses.pop(0)


def make_state() -> dict[str, Any]:
    return {
        "run_id": "run-contract-1",
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


def run_graph() -> dict[str, Any]:
    """Run the real Graph with deterministic fakes (same harness as test_logging_and_steps)."""

    model = FakeModel(
        [
            AIMessage(
                content="",
                tool_calls=[
                    {"name": "analyze_log", "args": {"log_text": LOG_TEXT}, "id": "c1"}
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


def make_session():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


def test_analyze_and_detail_agree_on_the_step_payload():
    """/analyze 与 /runs/{id} 必须返回同一套步骤字段，且与 TS 的 AgentStep 一致。"""

    expected = load_typescript_interfaces()["AgentStep"].names
    state = run_graph()
    analyze = _response_from_state(state)

    Session = make_session()
    with Session() as db:
        run = create_run(
            db,
            run_id=state["run_id"],
            owner_user_id=1,
            title="订单服务故障",
            input_content=LOG_TEXT,
            knowledge_base_id=3,
            model_name="deepseek-chat",
            max_iterations=4,
        )
        append_steps(db, run, state["steps"])
        detail = _to_response(run)

    assert analyze.steps and detail.steps
    # 每条步骤都是同一套字段（P1-5-2 之前 analyze 是 5 条 4 种形状）。
    assert {frozenset(step) for step in analyze.steps} == {frozenset(expected)}
    assert {frozenset(step) for step in detail.steps} == {frozenset(expected)}
    # 不只是形状相同：同一次运行在两边的取值也逐字段相同。
    assert analyze.steps == detail.steps
    assert [step["step_index"] for step in analyze.steps] == list(
        range(1, len(analyze.steps) + 1)
    )
    # Graph 内部字段不再泄漏到公开契约。
    for leaked in ("_started_at", "ok", "attempts", "tool_call_count", "unverified_count"):
        assert all(leaked not in step for step in analyze.steps), leaked


def test_observation_payload_matches_the_typescript_contract():
    interfaces = load_typescript_interfaces()
    state = run_graph()

    assert state["observations"], "这次运行应当产生工具观察"
    observation = state["observations"][0]

    assert set(observation) == interfaces["Observation"].names
    assert set(observation["result"]) == interfaces["ToolResult"].names
    # analyze 直接透出 state 的 observations；两个接口的观察形状本来就一致。
    assert _response_from_state(state).observations == state["observations"]


# --------------------------------------------------------------------------
# 3) 规则与解析器自身的反证
# --------------------------------------------------------------------------


def test_contract_rules_catch_synthetic_drift():
    drifted_ts = parse_typescript_interfaces(
        "\n".join(
            [
                "export interface Demo {",
                "  kept: string",
                "  dead_field: string",
                "  wrong_nullable: string | null",
                "  wrong_enum: 'a' | 'b'",
                "  optional_in_response?: string",
                "}",
            ]
        ),
        label="demo.ts",
    )["Demo"]
    backend = {
        "required": ["kept", "wrong_nullable", "wrong_enum", "optional_in_response"],
        "properties": {
            "kept": {"type": "string"},
            "missing_in_ts": {"type": "string"},
            "wrong_nullable": {"type": "string"},
            "wrong_enum": {"type": "string", "enum": ["a", "c"]},
            "optional_in_response": {"type": "string"},
        },
    }

    problems = "\n".join(compare_interface(drifted_ts, backend, direction="response"))

    assert "Demo.dead_field" in problems  # 死字段
    assert "Demo.missing_in_ts" in problems  # 后端有、TS 缺
    assert "Demo.wrong_nullable" in problems  # 可空性不一致
    assert "Demo.wrong_enum" in problems  # 枚举不一致
    assert "Demo.optional_in_response" in problems  # 响应字段写成可选

    matching_ts = parse_typescript_interfaces(
        "\n".join(
            [
                "export interface Ok {",
                "  a: string",
                "  b: string | null",
                "  c: 'x' | 'y'",
                "}",
            ]
        ),
        label="ok.ts",
    )["Ok"]
    matching_backend = {
        "required": ["a", "b", "c"],
        "properties": {
            "a": {"type": "string"},
            "b": {"anyOf": [{"type": "string"}, {"type": "null"}]},
            "c": {"type": "string", "enum": ["x", "y"]},
        },
    }

    assert compare_interface(matching_ts, matching_backend, direction="response") == []

    # 请求方向的可空性是单向的：客户端可以比后端更窄，反过来不行。
    request_ts = parse_typescript_interfaces(
        "\n".join(
            [
                "export interface Req {",
                "  narrow: string",
                "  wide: string | null",
                "  required_but_optional?: string",
                "}",
            ]
        ),
        label="req.ts",
    )["Req"]
    request_backend = {
        "required": ["required_but_optional"],
        "properties": {
            "narrow": {"anyOf": [{"type": "string"}, {"type": "null"}]},
            "wide": {"type": "string"},
            "required_but_optional": {"type": "string"},
        },
    }

    request_problems = "\n".join(
        compare_interface(request_ts, request_backend, direction="request")
    )

    assert "Req.narrow" not in request_problems
    assert "Req.wide" in request_problems
    assert "Req.required_but_optional" in request_problems


def test_typescript_parser_rejects_inline_object_types():
    with pytest.raises(AssertionError, match="内联对象类型"):
        parse_typescript_interfaces(
            "export interface Bad {\n  nested: {\n    b: string\n  }\n}\n",
            label="bad.ts",
        )
