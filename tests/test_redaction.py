"""Credential redaction tests (P0-2-2).

The completion standard for this item is a negative assertion: after a run with
credential-shaped incident input, the raw secrets must not be findable in the
persisted rows or in the API response. ``RAW_SECRETS`` below is asserted against
the whole serialized payload, not just a couple of fields.
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from langchain_core.messages import AIMessage

from app.incident_agent.core.redaction import (
    MASK,
    redact_for_model,
    redact_payload,
    redact_text,
)
from app.incident_agent.db.session import Base, get_db
from app.incident_agent.dependencies import get_access_token, get_current_user
from app.incident_agent.graph.workflow import build_graph
from app.incident_agent.models import AgentRun, AgentStep
from app.incident_agent.schemas.auth import UserPublic
from app.incident_agent.schemas.incident import IncidentAnalyzeRequest
from app.incident_agent.services import authorizer as authorizer_module
from app.incident_agent.services.authorizer import StaticKnowledgeBaseAuthorizer
from app.incident_agent.services.incident import execute_incident
from app.incident_agent.services.rag_client import MockRagGateway
from app.incident_agent.services.tools import build_tools
from app.main import app

# Realistic incident log: credentials plus identifiers that must survive.
INCIDENT_LOG = (
    "2026-09-14 10:00 ERROR order-service\n"
    "Authorization: Bearer eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0.abc123def\n"
    "dsn=mysql+pymysql://root:YOUR_MYSQL_PASSWORD@127.0.0.1:3306/dev_atlas\n"
    "password=devpass123 traceback follows\n"
    "api_key: sk-abcdefghijklmnop\n"
    "手机号：13800138000\n"
    "order_id=15020304567 查询超时，HTTP 502 Bad Gateway after 30000ms"
)

RAW_SECRETS = [
    "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0.abc123def",
    "YOUR_MYSQL_PASSWORD",
    "devpass123",
    "sk-abcdefghijklmnop",
    "13800138000",
]

STORED_SIGNALS = ["order_id=15020304567", "502 Bad Gateway", "30000ms"]

VALID_REPORT = (
    '{"summary":"订单服务 502，疑似数据库连接超时。","category":"database",'
    '"evidence":[{"source":"fault_log","detail":"命中 502 与超时。"}],'
    '"possible_causes":["数据库连接超时"],'
    '"troubleshooting_steps":["检查数据库连接池"],'
    '"references":[],"confidence":"medium"}'
)


class FakeModel:
    def __init__(self, responses):
        self.responses = list(responses)
        self.seen_messages: list = []

    def bind_tools(self, tools):
        return self

    def invoke(self, messages):
        self.seen_messages.extend(messages)
        if not self.responses:
            raise AssertionError("FakeModel 没有预置更多响应")
        return self.responses.pop(0)


def make_user() -> UserPublic:
    return UserPublic(
        id=1,
        username="test-user",
        role="user",
        is_active=True,
        created_at="2026-09-04T00:00:00Z",
        updated_at="2026-09-04T00:00:00Z",
    )


def make_session():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


def assert_no_raw_secrets(payload: object) -> None:
    """Fail loudly listing which secret leaked, not just that one did."""

    import json

    blob = json.dumps(payload, ensure_ascii=False, default=str)
    leaked = [secret for secret in RAW_SECRETS if secret in blob]
    assert leaked == [], f"以下凭据未被脱敏就落库/返回：{leaked}"


def assert_contains_mask(payload: object) -> None:
    import json

    blob = json.dumps(payload, ensure_ascii=False, default=str)
    assert MASK in blob, "脱敏标记缺失，说明脱敏根本没有执行"


# --------------------------------------------------------------------------
# Unit level: the pattern rules themselves
# --------------------------------------------------------------------------


def test_bearer_header_is_masked():
    assert redact_text("Authorization: Bearer eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0.abc") == (
        f"Authorization: Bearer {MASK}"
    )


def test_connection_uri_keeps_host_and_database_visible():
    """Host and db are needed for troubleshooting; only userinfo is a secret."""

    result = redact_text(
        "dsn=mysql+pymysql://root:YOUR_MYSQL_PASSWORD@127.0.0.1:3306/dev_atlas"
    )

    assert "YOUR_MYSQL_PASSWORD" not in result
    assert "root" not in result
    assert "127.0.0.1:3306/dev_atlas" in result


def test_short_password_value_is_still_masked():
    """A credential-shaped key is enough signal, even for a weak value."""

    assert redact_text("password=dev") == f"password={MASK}"


def test_secret_key_variants_are_masked():
    for sample in (
        "JWT_SECRET_KEY=super-secret-value",
        "api-key: sk-live-123456",
        '{"token": "abcd1234"}',
        "TOKEN=abc",
    ):
        assert MASK in redact_text(sample), sample


def test_phone_and_id_card_need_an_explicit_label():
    assert "13800138000" not in redact_text("手机号：13800138000，请联系值班同学")
    assert "11010519491231002X" not in redact_text("身份证号 11010519491231002X 需核对")


def test_normal_log_content_is_not_mangled():
    """The whole point: redaction must not damage the evidence."""

    result = redact_text(INCIDENT_LOG)

    for signal in STORED_SIGNALS:
        assert signal in result, f"正常信号被误删：{signal}"
    assert MASK in result
    assert "127.0.0.1:3306/dev_atlas" in result


def test_redaction_is_idempotent():
    once = redact_text(INCIDENT_LOG)
    assert redact_text(once) == once


def test_connection_uri_without_credentials_is_untouched():
    """A normal URL must not be mangled into a partially masked mess."""

    assert redact_text("see https://user@example.com/docs") == (
        "see https://user@example.com/docs"
    )


def test_redact_for_model_clips_with_a_visible_marker():
    result = redact_for_model("x" * 50, max_length=10)

    assert result.startswith("x" * 10)
    assert "已截断" in result
    assert "50" in result


def test_redact_payload_walks_nested_structures():
    jwt = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0.abc123def"
    payload = {
        "items": [
            {"error": "password=devpass123"},
            ("Bearer", jwt),
            {"token_header": f"Bearer {jwt}"},
        ],
        "count": 3,
        "ok": True,
    }

    result = redact_payload(payload)

    assert result["items"][0]["error"] == f"password={MASK}"
    assert result["items"][1][1] == MASK  # JWT 形状本身就是凭据
    assert result["items"][2]["token_header"] == f"Bearer {MASK}"
    assert result["count"] == 3
    assert result["ok"] is True


# --------------------------------------------------------------------------
# Graph level: tool results and the report must be masked before persistence
# --------------------------------------------------------------------------


def test_tool_observation_is_masked_before_it_is_stored_in_state():
    agent_model = FakeModel(
        [
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "analyze_log",
                        "args": {"log_text": INCIDENT_LOG},
                        "id": "call-log",
                    }
                ],
            ),
            AIMessage(content="证据已足够。"),
        ]
    )
    graph = build_graph(
        model=agent_model,
        report_model=FakeModel([AIMessage(content=VALID_REPORT)]),
        tools=build_tools(MockRagGateway()),
    )

    state = {
        "run_id": "run-redact-1",
        "owner_user_id": 1,
        "title": "订单服务故障",
        "input_content": redact_for_model(INCIDENT_LOG),
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

    result = graph.invoke(state)

    assert result["status"] == "completed"
    assert_no_raw_secrets(result["observations"])
    # 工具确实执行了，因此 observations 非空；凭据必须在工具边界就被脱掉。
    assert result["observations"], "应至少有一条工具观察"
    assert result["observations"][0]["result"]["ok"] is True


def test_report_free_text_is_masked_before_it_is_returned():
    leaking_report = (
        '{"summary":"根因确认：password=devpass123 导致连接失败。",'
        '"category":"database",'
        '"evidence":[{"source":"tool_error","detail":"api_key: sk-abcdefghijklmnop"}],'
        '"possible_causes":["dsn=mysql+pymysql://root:YOUR_MYSQL_PASSWORD@127.0.0.1:3306/dev_atlas"],'
        '"troubleshooting_steps":["Bearer eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0.abc123def 已过期"],'
        '"references":["手机号：13800138000"],"confidence":"low"}'
    )
    graph = build_graph(
        model=FakeModel([AIMessage(content="无需工具。")]),
        report_model=FakeModel([AIMessage(content=leaking_report)]),
        tools=build_tools(MockRagGateway()),
    )

    result = graph.invoke(
        {
            "run_id": "run-redact-2",
            "owner_user_id": 1,
            "title": "t",
            "input_content": "c",
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
    )

    # 这个用例没有调用任何工具，因此 P0-3-1 之后状态是
    # insufficient_evidence；报告本身仍必须存在且已完成脱敏。
    assert result["status"] == "insufficient_evidence"
    assert result["report"] is not None
    assert_no_raw_secrets(result["report"])
    assert_contains_mask(result["report"])


# --------------------------------------------------------------------------
# Service level: nothing raw may reach MySQL
# --------------------------------------------------------------------------


def test_persisted_run_contains_no_raw_credentials():
    Session = make_session()
    gateway = MockRagGateway()
    model = FakeModel(
        [
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "search_knowledge",
                        "args": {"query": "订单服务 502"},
                        "id": "call-search",
                    }
                ],
            ),
            AIMessage(content="证据已足够。"),
            AIMessage(content=VALID_REPORT),
        ]
    )

    with Session() as db:
        result = execute_incident(
            db,
            user=make_user(),
            request=IncidentAnalyzeRequest(
                title="订单服务故障 password=devpass123",
                content=INCIDENT_LOG,
                knowledge_base_id=3,
            ),
            access_token="Bearer redaction-test-token",
            model=model,
            rag_gateway=gateway,
            knowledge_base_authorizer=StaticKnowledgeBaseAuthorizer(),
        )

        run = db.scalar(select(AgentRun))
        steps = list(db.scalars(select(AgentStep)))

        assert run is not None
        assert_no_raw_secrets(run.input_content)
        assert_no_raw_secrets(run.title)
        assert_no_raw_secrets(run.observations)
        assert_no_raw_secrets(run.report)
        assert_contains_mask(run.input_content)
        assert run.input_content != INCIDENT_LOG
        # 证据本身不能被脱敏毁掉。
        for signal in STORED_SIGNALS:
            assert signal in run.input_content
        assert steps, "步骤轨迹不应为空"

    assert_no_raw_secrets(result.model_dump())


def test_model_context_never_contains_the_raw_secret():
    """Redaction happens before the model, not only before the database."""

    Session = make_session()
    model = FakeModel(
        [
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "analyze_log",
                        "args": {"log_text": "password=devpass123"},
                        "id": "call-log",
                    }
                ],
            ),
            AIMessage(content="证据已足够。"),
            AIMessage(content=VALID_REPORT),
        ]
    )

    with Session() as db:
        execute_incident(
            db,
            user=make_user(),
            request=IncidentAnalyzeRequest(
                title="订单服务故障",
                content=INCIDENT_LOG,
                knowledge_base_id=3,
            ),
            access_token="token",
            model=model,
            rag_gateway=MockRagGateway(),
            knowledge_base_authorizer=StaticKnowledgeBaseAuthorizer(),
        )

    assert model.seen_messages, "模型应该被调用过"
    assert_no_raw_secrets([str(message.content) for message in model.seen_messages])
    assert_contains_mask([str(message.content) for message in model.seen_messages])


# --------------------------------------------------------------------------
# API level: the /runs history endpoint must not echo secrets back
# --------------------------------------------------------------------------


def test_runs_endpoint_does_not_return_raw_credentials(monkeypatch):
    # FastAPI runs sync dependencies in a threadpool, so the in-memory SQLite
    # connection must be shareable across threads (StaticPool + no
    # check_same_thread) or the history request would see an empty database.
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    client = TestClient(app)

    def override_db():
        Base.metadata.create_all(engine)
        db = Session()
        try:
            yield db
        finally:
            db.close()

    def fake_authorizer_init(self, base_url: str, timeout_seconds: float = 20.0):
        import httpx

        self._client = httpx.Client(
            base_url=base_url.rstrip("/"),
            transport=httpx.MockTransport(
                lambda request: httpx.Response(
                    200,
                    json={"id": 3, "owner_id": 1, "name": "订单服务手册"},
                )
            ),
        )

    # 第一轮调用 analyze_log，之后不再调用工具直到生成报告。
    def fake_model_completion(messages):
        tool_used = any(
            getattr(message, "type", "") == "tool" for message in messages
        )
        if not tool_used:
            return AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "analyze_log",
                        "args": {"log_text": INCIDENT_LOG},
                        "id": "call-log",
                    }
                ],
            )
        return AIMessage(content=VALID_REPORT)

    monkeypatch.setattr(
        authorizer_module.HttpKnowledgeBaseAuthorizer,
        "__init__",
        fake_authorizer_init,
    )
    app.dependency_overrides[get_current_user] = make_user
    app.dependency_overrides[get_access_token] = lambda: "token"
    app.dependency_overrides[get_db] = override_db

    import app.incident_agent.services.incident as incident_module

    class PatchedModel(FakeModel):
        def invoke(self, messages):
            return fake_model_completion(messages)

    monkeypatch.setattr(
        incident_module,
        "create_chat_model",
        lambda settings: PatchedModel([]),
    )

    try:
        response = client.post(
            "/api/v1/incidents/analyze",
            json={
                "title": "订单服务故障",
                "content": INCIDENT_LOG,
                "knowledge_base_id": 3,
            },
        )
        history = client.get("/api/v1/runs")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert history.status_code == 200

    assert_no_raw_secrets(response.json())
    assert_no_raw_secrets(history.json())
    assert history.json(), "历史接口应返回刚创建的 run"

    # 数据库里存的必须是脱敏文本：凭据没了，取证需要的信号还在。
    with Session() as db:
        run = db.scalar(select(AgentRun))
        assert run is not None
        assert_no_raw_secrets(run.input_content)
        assert MASK in run.input_content
        for signal in STORED_SIGNALS:
            assert signal in run.input_content
