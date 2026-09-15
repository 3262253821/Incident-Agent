"""Unified error responses and upstream error classification (P1-2-4).

Two halves:

- ``app_errors.py``: every error response has one shape
  (``detail`` + ``error_code`` + ``request_id``), leaks nothing, and the server
  log can be correlated by ``request_id``;
- ``services/auth.py``: upstream 422 / 429 / 5xx / timeout are no longer all
  collapsed into 502.

设计文档章节：§13.3 API 状态码、§11.4 超时和重试、§16.2 工具异常。
"""

from __future__ import annotations

import io

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.incident_agent.app_errors import (
    REQUEST_ID_HEADER,
    error_code_for,
    message_for,
)
from app.incident_agent.core.logging import configure_logging
from app.incident_agent.db.session import Base, get_db
from app.incident_agent.dependencies import get_access_token, get_current_user
from app.incident_agent.schemas.auth import LoginRequest, UserPublic
from app.incident_agent.services.auth import (
    DevAtlasAuthClient,
    DevAtlasAuthError,
)
from app.main import app

SECRET = "sk-should-never-leak"
LEAK_MARKERS = ["Traceback", 'File "', "E:\\", "site-packages", "sqlalchemy", SECRET]


def capture_logs() -> io.StringIO:
    buffer = io.StringIO()
    logger = configure_logging()
    for handler in logger.handlers:
        handler.stream = buffer
    return buffer


def make_user() -> UserPublic:
    return UserPublic(
        id=1,
        username="t",
        role="user",
        is_active=True,
        created_at="2026-09-04T00:00:00Z",
        updated_at="2026-09-04T00:00:00Z",
    )


@pytest.fixture
def client():
    probe_path = "/_probe/boom"

    @app.get(probe_path)
    def _boom():  # pragma: no cover - 只在通过异常处理器时被调用
        raise RuntimeError(f"internal detail {SECRET} at E:\\secret\\file.py")

    # 这个 fixture 必须自给自足：`/api/v1/runs/{run_id}` 会真的查库，而开发机上的
    # .env 指向真实 MySQL，于是"本地通过"其实依赖了那台机器上已经建好的表。
    # 2026-09-15 在无 .env 的干净检出里复现 CI 时这里先炸：SQLite 内存库没有表 →
    # "no such table: agent_runs" → 本应是 404 的用例变成 500。
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)

    def override_db():
        db = Session()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_current_user] = make_user
    app.dependency_overrides[get_access_token] = lambda: "token"
    app.dependency_overrides[get_db] = override_db
    yield TestClient(app, raise_server_exceptions=False)
    app.dependency_overrides.clear()
    engine.dispose()


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("status_code", "expected_code"),
    [
        (400, "BAD_REQUEST"),
        (401, "UNAUTHORIZED"),
        (403, "FORBIDDEN"),
        (404, "NOT_FOUND"),
        (422, "VALIDATION_ERROR"),
        (429, "RATE_LIMITED"),
        (500, "AGENT_INTERNAL_ERROR"),
        (502, "UPSTREAM_ERROR"),
        (503, "DEPENDENCY_UNAVAILABLE"),
        (418, "HTTP_418"),  # 未登记的状态码也要有稳定可读的编码
    ],
)
def test_error_codes_are_stable(status_code: int, expected_code: str):
    assert error_code_for(status_code) == expected_code


def test_message_for_passes_lists_through_unchanged():
    """Field-level validation details must survive the response builder."""

    field_errors = [{"loc": ["body", "top_k"], "msg": "must be <= 10"}]

    assert message_for(422, field_errors) is field_errors


def test_message_for_uses_supplied_text_then_a_fixed_fallback():
    assert message_for(404, "运行记录不存在") == "运行记录不存在"
    assert message_for(404, None) == "请求的资源不存在"
    assert message_for(404, {"weird": True}) == "请求的资源不存在"
    assert message_for(512, None) == "请求失败"


# --------------------------------------------------------------------------
# Unhandled exceptions
# --------------------------------------------------------------------------


def test_unhandled_exception_returns_a_safe_500(client):
    response = client.get("/_probe/boom")

    assert response.status_code == 500
    body = response.json()
    assert body["error_code"] == "AGENT_INTERNAL_ERROR"
    assert body["detail"] == "服务内部错误，请稍后重试"
    assert body["request_id"]


def test_unhandled_exception_leaks_nothing(client):
    response = client.get("/_probe/boom")

    for marker in LEAK_MARKERS:
        assert marker not in response.text, f"响应泄露了 {marker}"
    assert "RuntimeError" not in response.text


def test_unhandled_exception_is_correlatable_in_the_log(client):
    buffer = capture_logs()

    response = client.get("/_probe/boom")
    request_id = response.headers[REQUEST_ID_HEADER]
    logs = buffer.getvalue()

    assert request_id in logs, "日志必须能按 request_id 关联到本次响应"
    assert "RuntimeError" in logs, "服务端应记录异常类名"
    assert SECRET not in logs, "异常文本里的敏感内容不得进日志"
    assert "E:\\secret" not in logs


def test_request_id_is_generated_and_echoed(client):
    response = client.get("/health")

    request_id = response.headers.get(REQUEST_ID_HEADER)
    assert request_id
    assert len(request_id) == 32  # uuid4().hex


def test_incoming_request_id_is_reused(client):
    response = client.get("/health", headers={REQUEST_ID_HEADER: "trace-abc-123"})

    assert response.headers[REQUEST_ID_HEADER] == "trace-abc-123"


# --------------------------------------------------------------------------
# HTTPException and validation paths
# --------------------------------------------------------------------------


def test_http_exception_keeps_detail_and_adds_metadata(client):
    response = client.get("/api/v1/runs/does-not-exist")

    assert response.status_code == 404
    body = response.json()
    assert body["detail"] == "运行记录不存在"
    assert body["error_code"] == "NOT_FOUND"
    assert body["request_id"] == response.headers[REQUEST_ID_HEADER]


def test_missing_token_returns_401_with_challenge(client):
    app.dependency_overrides.clear()

    response = client.get("/api/v1/runs")

    assert response.status_code == 401
    assert response.headers.get("WWW-Authenticate") == "Bearer"
    assert response.json()["error_code"] == "UNAUTHORIZED"


def test_validation_failure_keeps_field_level_detail_as_a_list(client):
    """The frontend branches on Array.isArray(detail); it must stay a list."""

    response = client.post(
        "/api/v1/incidents/analyze",
        json={"title": "t", "content": "c", "knowledge_base_id": 1, "top_k": 99},
    )

    assert response.status_code == 422
    body = response.json()
    assert isinstance(body["detail"], list)
    assert body["error_code"] == "VALIDATION_ERROR"
    assert any(
        "top_k" in [str(part) for part in item.get("loc", ())]
        for item in body["detail"]
    )


def test_validation_failure_does_not_echo_the_submitted_value(client):
    """A rejected value can contain a secret; it must not be logged or returned."""

    buffer = capture_logs()

    response = client.post(
        "/api/v1/incidents/analyze",
        json={"title": "t", "content": SECRET, "knowledge_base_id": 1, "top_k": 99},
    )

    assert response.status_code == 422
    assert SECRET not in response.text
    assert SECRET not in buffer.getvalue()
    # 日志只记字段路径
    assert "body.top_k" in buffer.getvalue()


def test_health_endpoints_are_unaffected(client):
    assert client.get("/health").json() == {
        "status": "ok",
        "service": "incident-agent-api",
    }
    db_health = client.get("/health/db")
    assert db_health.status_code in (200, 503)
    assert db_health.json()["service"] == "incident-agent-db"


# --------------------------------------------------------------------------
# Upstream error classification in the auth proxy
# --------------------------------------------------------------------------


def make_auth_client(handler) -> DevAtlasAuthClient:
    client = DevAtlasAuthClient("http://devatlas.invalid", timeout_seconds=1.0)
    client._client = httpx.Client(
        base_url="http://devatlas.invalid",
        timeout=httpx.Timeout(1.0),
        transport=httpx.MockTransport(handler),
    )
    return client


LOGIN = LoginRequest(username="alice", password="whatever")


@pytest.mark.parametrize(
    ("upstream_status", "expected_status", "expected_fragment"),
    [
        (401, 401, "用户名或密码错误"),
        (403, 403, "用户已被禁用"),
        (422, 422, "不符合 DevAtlas 要求"),
        (429, 429, "过于频繁"),
        (500, 503, "暂不可用"),
        (502, 503, "暂不可用"),
        (400, 502, "返回错误"),
    ],
)
def test_login_maps_upstream_status_codes(
    upstream_status: int,
    expected_status: int,
    expected_fragment: str,
):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(upstream_status, json={"detail": "upstream"})

    with pytest.raises(DevAtlasAuthError) as excinfo:
        make_auth_client(handler).login(LOGIN)

    assert excinfo.value.status_code == expected_status
    assert expected_fragment in excinfo.value.message


@pytest.mark.parametrize("upstream_status", [429, 500, 503])
def test_current_user_maps_rate_limit_and_outage(upstream_status: int):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(upstream_status, json={"detail": "upstream"})

    with pytest.raises(DevAtlasAuthError) as excinfo:
        make_auth_client(handler).current_user("token")

    expected = 429 if upstream_status == 429 else 503
    assert excinfo.value.status_code == expected


def test_login_timeout_and_connection_error_are_service_unavailable():
    def timeout_handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=request)

    with pytest.raises(DevAtlasAuthError) as excinfo:
        make_auth_client(timeout_handler).login(LOGIN)
    assert excinfo.value.status_code == 503
    assert "超时" in excinfo.value.message

    def refused_handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    with pytest.raises(DevAtlasAuthError) as excinfo2:
        make_auth_client(refused_handler).login(LOGIN)
    assert excinfo2.value.status_code == 503
    assert "无法连接" in excinfo2.value.message


def test_upstream_422_reaches_the_client_as_422_not_502(client):
    """A client mistake must not be reported as an upstream failure."""

    app.dependency_overrides.clear()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(422, json={"detail": "bad payload"})

    import app.incident_agent.routers.auth as auth_router_module

    original = auth_router_module.DevAtlasAuthClient

    def factory(base_url: str, timeout_seconds: float = 20.0):
        return make_auth_client(handler)

    auth_router_module.DevAtlasAuthClient = factory
    try:
        response = client.post(
            "/api/v1/auth/login",
            json={"username": "alice", "password": "whatever"},
        )
    finally:
        auth_router_module.DevAtlasAuthClient = original

    assert response.status_code == 422
    assert response.json()["error_code"] == "VALIDATION_ERROR"
