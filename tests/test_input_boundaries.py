"""设计文档 §16.1（输入异常）、§13.2（分析请求）、§6.1–§6.3（工具参数契约）。

P1-4-1 里点名要补的边界：

- 空标题 / 空内容 / 超长内容 / 非法 ``knowledge_base_id`` 必须在**进入模型和工具
  之前**被 422 拒绝（§16.1 的 "→ 不进入模型和工具"）；
- 文档给的界限是**包含**边界（标题 200、内容 20_000、日志 20_000、query 2_000、
  服务名 100），所以恰好等于上限必须通过、上限 +1 必须失败；
- 工具层超限返回统一的 ``INVALID_ARGUMENTS``，且不得把 Python traceback 交给
  调用方（§16.2）。
"""

from __future__ import annotations

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.incident_agent.db.session import Base, get_db
from app.incident_agent.dependencies import get_access_token, get_current_user
from app.incident_agent.models import AgentRun
from app.incident_agent.schemas.auth import UserPublic
from app.incident_agent.schemas.incident import RunResponse
from app.incident_agent.services import authorizer as authorizer_module
from app.incident_agent.services.rag_client import MockRagGateway
from app.incident_agent.services.tools import build_tools
from app.main import app

client = TestClient(app)


def make_user() -> UserPublic:
    return UserPublic(
        id=1,
        username="test-user",
        role="user",
        is_active=True,
        created_at="2026-09-04T00:00:00Z",
        updated_at="2026-09-04T00:00:00Z",
    )


@pytest.fixture
def engine():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture
def session_factory(engine):
    return sessionmaker(bind=engine, expire_on_commit=False)


@pytest.fixture
def install_overrides(session_factory):
    """Authenticate as a fixed user and bind the route to an in-memory DB."""

    def _install() -> None:
        def override():
            db = session_factory()
            try:
                yield db
            finally:
                db.close()

        app.dependency_overrides[get_current_user] = make_user
        app.dependency_overrides[get_access_token] = lambda: "token-abc"
        app.dependency_overrides[get_db] = override

    _install()
    yield _install
    app.dependency_overrides.clear()


def spy_service(monkeypatch, calls: list) -> None:
    """Record (instead of running) the analysis service."""

    def fake_execute(db, *, user, request, access_token, **kwargs):
        calls.append(request)
        return RunResponse(
            run_id="run-boundary",
            title=request.title,
            status="completed",
        )

    monkeypatch.setattr(
        "app.incident_agent.routers.incidents.execute_incident",
        fake_execute,
    )


def spy_authorizer(monkeypatch, calls: list) -> None:
    """Record whether DevAtlas was contacted at all."""

    def fake_init(self, base_url: str, timeout_seconds: float = 20.0):
        calls.append({"base_url": base_url})
        self._client = httpx.Client(
            base_url=base_url.rstrip("/"),
            timeout=httpx.Timeout(timeout_seconds),
            transport=httpx.MockTransport(
                lambda request: httpx.Response(404, json={"detail": "nope"})
            ),
        )

    monkeypatch.setattr(
        authorizer_module.HttpKnowledgeBaseAuthorizer,
        "__init__",
        fake_init,
    )


def payload(**overrides) -> dict:
    body = {
        "title": "订单服务返回 502",
        "content": "网关返回 502，MySQL connection timeout",
        "knowledge_base_id": 3,
    }
    body.update(overrides)
    return body


def field_names(response) -> set[str]:
    """Collect the field names a 422 lists, so the hint points at the right input."""

    detail = response.json()["detail"]
    assert isinstance(detail, list), "字段级错误必须保持列表形状"
    return {
        str(part)
        for error in detail
        for part in error.get("loc", [])
    }


# --------------------------------------------------------------------------
# §16.1 空标题 / 空内容
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "overrides",
    [
        {"title": ""},
        {"title": "   "},
        {"title": "\n\t "},
        {"content": ""},
        {"content": "   "},
        {"content": "\n"},
    ],
)
def test_case_04_blank_input_is_rejected(
    monkeypatch,
    session_factory,
    install_overrides,
    overrides,
):
    calls: list = []
    devatlas_calls: list = []
    spy_service(monkeypatch, calls)
    spy_authorizer(monkeypatch, devatlas_calls)

    response = client.post("/api/v1/incidents/analyze", json=payload(**overrides))

    with session_factory() as db:
        run_count = db.query(AgentRun).count()

    assert response.status_code == 422
    assert field_names(response) & set(overrides)
    # §16.1：不进入模型和工具 —— 服务与 DevAtlas 都不应被触达。
    assert calls == []
    assert devatlas_calls == []
    assert run_count == 0


# --------------------------------------------------------------------------
# §16.1 超长输入
# --------------------------------------------------------------------------


@pytest.mark.parametrize("field", ["title", "content"])
def test_case_04_oversized_input_is_rejected(
    monkeypatch,
    session_factory,
    install_overrides,
    field,
):
    # 超长值在测试体内构造：参数化 ID 会进 PYTEST_CURRENT_TEST 环境变量，
    # Windows 的环境变量上限是 32767 字符，把 20_001 字的载荷放进 parametrize
    # 会让测试在 setup 阶段就报 "environment variable is longer than 32767"。
    value = "标" * 201 if field == "title" else "日" * 20_001
    calls: list = []
    devatlas_calls: list = []
    spy_service(monkeypatch, calls)
    spy_authorizer(monkeypatch, devatlas_calls)

    response = client.post("/api/v1/incidents/analyze", json=payload(**{field: value}))

    with session_factory() as db:
        run_count = db.query(AgentRun).count()

    assert response.status_code == 422
    assert field in field_names(response)
    assert calls == []
    assert devatlas_calls == []
    assert run_count == 0


def test_input_exactly_at_the_documented_limit_is_accepted(
    monkeypatch,
    session_factory,
    install_overrides,
):
    """上限是包含边界：201 被拒不代表 200 也会被拒。"""

    calls: list = []
    spy_service(monkeypatch, calls)

    response = client.post(
        "/api/v1/incidents/analyze",
        json=payload(title="标" * 200, content="日" * 20_000),
    )

    assert response.status_code == 200
    assert len(calls) == 1
    assert len(calls[0].content) == 20_000


# --------------------------------------------------------------------------
# §16.1 非法 knowledge_base_id / 超范围 top_k
# --------------------------------------------------------------------------


@pytest.mark.parametrize("knowledge_base_id", [0, -1])
def test_invalid_knowledge_base_id_is_rejected_before_the_service(
    monkeypatch,
    session_factory,
    install_overrides,
    knowledge_base_id,
):
    calls: list = []
    devatlas_calls: list = []
    spy_service(monkeypatch, calls)
    spy_authorizer(monkeypatch, devatlas_calls)

    response = client.post(
        "/api/v1/incidents/analyze",
        json=payload(knowledge_base_id=knowledge_base_id),
    )

    with session_factory() as db:
        run_count = db.query(AgentRun).count()

    assert response.status_code == 422
    assert "knowledge_base_id" in field_names(response)
    assert calls == []
    assert devatlas_calls == []
    assert run_count == 0


@pytest.mark.parametrize("top_k", [0, -1, 11])
def test_top_k_outside_the_documented_range_is_rejected(
    monkeypatch,
    install_overrides,
    top_k,
):
    calls: list = []
    spy_service(monkeypatch, calls)

    response = client.post("/api/v1/incidents/analyze", json=payload(top_k=top_k))

    assert response.status_code == 422
    assert "top_k" in field_names(response)
    assert calls == []


# --------------------------------------------------------------------------
# §6.1–§6.3 工具参数上限（包含边界 + 统一错误码）
# --------------------------------------------------------------------------


def test_analyze_log_accepts_exactly_the_limit_and_rejects_one_more():
    tool = build_tools(MockRagGateway())[0]

    at_limit = tool.invoke({"log_text": "5" * 20_000})
    over_limit = tool.invoke({"log_text": "5" * 20_001})

    assert at_limit["ok"] is True
    assert over_limit["ok"] is False
    assert over_limit["error_code"] == "INVALID_ARGUMENTS"


def test_analyze_log_reports_a_missing_argument_as_a_langchain_error():
    """缺必填参数在进入工具函数体之前就由 LangChain 的参数 schema 拒绝。

    这是有意记录的行为边界：``ToolNode`` 会把这个异常转成一条错误
    ``ToolMessage``，再由 ``observe`` 归一化成 ``INVALID_TOOL_RESULT``
    （test_tool_result_contract.py 覆盖了整条链路）。工具函数体内的
    ``INVALID_ARGUMENTS`` 只覆盖"参数形状对、取值越界"这一类。
    """

    tool = build_tools(MockRagGateway())[0]

    with pytest.raises(ValidationError):
        tool.invoke({})


def test_search_knowledge_rejects_an_overlong_query():
    tools = build_tools(MockRagGateway())

    at_limit = tools[1].invoke({"query": "q" * 2_000})
    over_limit = tools[1].invoke({"query": "q" * 2_001})

    assert at_limit["ok"] is True
    assert over_limit["ok"] is False
    assert over_limit["error_code"] == "INVALID_ARGUMENTS"


def test_service_status_accepts_the_limit_and_reports_unknown_beyond_it():
    tool = build_tools(MockRagGateway())[2]

    at_limit = tool.invoke({"service_name": "s" * 100})
    over_limit = tool.invoke({"service_name": "s" * 101})

    # 100 个字符仍在契约内，只是名字未登记；101 个字符是契约违规。
    assert at_limit["error_code"] == "UNKNOWN_SERVICE"
    assert over_limit["error_code"] == "INVALID_ARGUMENTS"


@pytest.mark.parametrize(
    ("tool_index", "arguments"),
    [
        (0, {"log_text": "5" * 20_001}),
        (1, {"query": "q" * 2_001}),
        (2, {"service_name": "s" * 101}),
    ],
)
def test_tool_argument_failures_return_a_short_message_without_a_traceback(
    tool_index,
    arguments,
):
    """§16.2：工具异常必须转成统一结果，不能把 Python traceback 交给调用方。"""

    result = build_tools(MockRagGateway())[tool_index].invoke(arguments)

    details = result["data"].get("details", "")
    assert result["error_code"] == "INVALID_ARGUMENTS"
    assert "Traceback" not in details
    assert "site-packages" not in details
    assert len(details) < 400
