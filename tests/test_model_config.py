"""Centralised model configuration (P1-2-2).

Model behaviour must be tunable from ``Settings`` / environment variables rather
than literals in ``services/llm.py``, and the report node must be able to use a
different model from the decision node.

设计文档章节：§14 配置设计。
"""

from __future__ import annotations

import pytest
from langchain_core.messages import AIMessage

from app.incident_agent.core.config import Settings, load_settings
from app.incident_agent.services import llm as llm_module
from app.incident_agent.services.authorizer import StaticKnowledgeBaseAuthorizer
from app.incident_agent.services.llm import create_chat_model, create_report_model


def make_settings(**overrides) -> Settings:
    base = {
        "agent_host": "127.0.0.1",
        "agent_port": 8001,
        "model": "decision-model",
        "model_base_url": "https://api.deepseek.com",
        "model_timeout_seconds": 30.0,
        "request_timeout_seconds": 90.0,
        "devatlas_base_url": "http://127.0.0.1:8000",
        "devatlas_timeout_seconds": 20.0,
        "max_iterations": 4,
        "default_top_k": 5,
        "database_url": "sqlite+pysqlite:///:memory:",
        "web_origins": ("http://127.0.0.1:5174",),
    }
    base.update(overrides)
    return Settings(**base)


class CapturingChatOpenAI:
    """Stand-in that records the kwargs the factory passes down."""

    instances: list[dict] = []

    def __init__(self, **kwargs):
        CapturingChatOpenAI.instances.append(kwargs)

    def bind_tools(self, tools):
        return self


@pytest.fixture(autouse=True)
def _capture(monkeypatch):
    CapturingChatOpenAI.instances = []
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    monkeypatch.setattr(llm_module, "ChatOpenAI", CapturingChatOpenAI)
    yield


# --------------------------------------------------------------------------
# Factories
# --------------------------------------------------------------------------


def test_defaults_are_applied_from_settings():
    create_chat_model(make_settings())

    kwargs = CapturingChatOpenAI.instances[-1]
    assert kwargs["model"] == "decision-model"
    assert kwargs["temperature"] == 0.1
    assert kwargs["max_retries"] == 0
    assert kwargs["timeout"] == (5.0, 30.0)
    assert "max_tokens" not in kwargs, "未配置时不应下发 max_tokens"


def test_temperature_and_max_tokens_come_from_settings():
    create_chat_model(
        make_settings(model_temperature=0.7, model_max_tokens=1234)
    )

    kwargs = CapturingChatOpenAI.instances[-1]
    assert kwargs["temperature"] == 0.7
    assert kwargs["max_tokens"] == 1234


def test_max_retries_is_configurable():
    create_chat_model(make_settings(model_max_retries=3))

    assert CapturingChatOpenAI.instances[-1]["max_retries"] == 3


def test_report_model_can_differ_from_the_decision_model():
    settings = make_settings(model="decision-model", report_model="report-model")

    create_chat_model(settings)
    create_report_model(settings)

    decision, report = CapturingChatOpenAI.instances
    assert decision["model"] == "decision-model"
    assert report["model"] == "report-model"
    # 除模型名外，其余参数一致
    assert decision["temperature"] == report["temperature"]
    assert decision["timeout"] == report["timeout"]


def test_report_model_falls_back_to_the_decision_model_name(monkeypatch):
    for name in (
        "INCIDENT_AGENT_MODEL",
        "INCIDENT_AGENT_REPORT_MODEL",
        "INCIDENT_DATABASE_URL",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("INCIDENT_AGENT_MODEL", "only-one-model")

    settings = load_settings()

    assert settings.model == "only-one-model"
    assert settings.report_model == "only-one-model"


def test_api_key_is_required(monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    with pytest.raises(RuntimeError, match="DEEPSEEK_API_KEY"):
        create_chat_model(make_settings())
    with pytest.raises(RuntimeError, match="DEEPSEEK_API_KEY"):
        create_report_model(make_settings())


# --------------------------------------------------------------------------
# Settings parsing
# --------------------------------------------------------------------------


def test_env_overrides_are_read(monkeypatch):
    monkeypatch.setenv("INCIDENT_AGENT_TEMPERATURE", "0.35")
    monkeypatch.setenv("INCIDENT_AGENT_MAX_TOKENS", "2048")
    monkeypatch.setenv("INCIDENT_MODEL_MAX_RETRIES", "1")
    monkeypatch.setenv("INCIDENT_AGENT_REPORT_MODEL", "deepseek-reasoner")
    monkeypatch.setenv("INCIDENT_AGENT_MODEL", "deepseek-chat")

    settings = load_settings()

    assert settings.model_temperature == 0.35
    assert settings.model_max_tokens == 2048
    assert settings.model_max_retries == 1
    assert settings.report_model == "deepseek-reasoner"


def test_blank_max_tokens_means_unlimited(monkeypatch):
    monkeypatch.setenv("INCIDENT_AGENT_MAX_TOKENS", "")

    assert load_settings().model_max_tokens is None


def test_garbage_max_tokens_falls_back_to_none(monkeypatch):
    monkeypatch.setenv("INCIDENT_AGENT_MAX_TOKENS", "not-a-number")

    assert load_settings().model_max_tokens is None


# --------------------------------------------------------------------------
# Wiring: the report node really uses the configured report model
# --------------------------------------------------------------------------


def test_execute_incident_uses_a_separate_report_model(monkeypatch):
    """The production path must build the report model via its own factory.

    Proven by recording which factories the service calls. The report model is
    built *inside* ``execute_incident``'s guarded block, so a failure there is
    absorbed into a controlled degradation rather than propagating -- hence the
    assertion is on the call sequence plus the degraded status.
    """

    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    import app.incident_agent.services.incident as incident_module
    from app.incident_agent.core.statuses import RunStatus
    from app.incident_agent.db.session import Base
    from app.incident_agent.schemas.auth import UserPublic
    from app.incident_agent.schemas.incident import IncidentAnalyzeRequest

    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)

    user = UserPublic(
        id=1,
        username="t",
        role="user",
        is_active=True,
        created_at="2026-09-04T00:00:00Z",
        updated_at="2026-09-04T00:00:00Z",
    )

    created: list[str] = []

    class DecisionModel:
        def bind_tools(self, tools):
            return self

        def invoke(self, messages):
            return AIMessage(content="{}")

    class Gateway:
        def search_knowledge(self, **kwargs):  # pragma: no cover
            raise AssertionError("检索不应被调用")

    def decision_factory(settings):
        created.append("decision")
        return DecisionModel()

    def failing_report_model(settings):
        created.append("report")
        raise RuntimeError("REPORT_MODEL_FACTORY_CALLED")

    monkeypatch.setattr(incident_module, "create_chat_model", decision_factory)
    monkeypatch.setattr(
        incident_module, "create_report_model", failing_report_model
    )

    with Session() as db:
        result = incident_module.execute_incident(
            db,
            user=user,
            request=IncidentAnalyzeRequest(
                title="订单服务故障",
                content="网关返回 502",
                knowledge_base_id=3,
            ),
            access_token="token",
            rag_gateway=Gateway(),
            knowledge_base_authorizer=StaticKnowledgeBaseAuthorizer(),
        )

    # 生产路径先建决策模型、再单独建报告模型
    assert created == ["decision", "report"]
    # 构造失败被吸收为受控降级，而不是把异常抛给调用方
    assert result.status == RunStatus.DEGRADED
    assert result.degraded_summary is not None
