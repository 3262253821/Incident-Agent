"""P1-3-4：owner 隔离与失败分支的回归测试。

这一项只补测试，因为它覆盖的四个场景此前都没有自动化验证：

1. **猜中别人的 run_id**：必须与"这个 ID 根本不存在"完全无法区分（否则 404/403 的
   差别就是一个存在性探针）；
2. **过期 Token**：DevAtlas 说 401 时，三个入口都必须 401，且不能留下任何运行记录；
3. **数据库异常**：写失败与读失败都必须返回安全 500（不含路径/堆栈/SQL），并且
   写失败后留下的 `running` 记录要能被启动回收机制收尾；
4. **失败状态持久化**：`degraded` / `report_validation_failed` 真的落库，并且能通过
   列表的状态过滤与详情接口读回来。
"""

from __future__ import annotations

from datetime import datetime, timedelta

import httpx
import pytest
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage
from sqlalchemy import create_engine, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.incident_agent import dependencies as dependencies_module
from app.incident_agent.db.session import Base, get_db
from app.incident_agent.dependencies import get_access_token, get_current_user
from app.incident_agent.models import AgentRun
from app.incident_agent.schemas.auth import UserPublic
from app.incident_agent.services.auth import DevAtlasAuthClient
from app.incident_agent.services.authorizer import StaticKnowledgeBaseAuthorizer
from app.incident_agent.services.rag_client import MockRagGateway
from app.incident_agent.services.storage import reclaim_stale_runs
from app.main import app

STARTED = datetime(2026, 9, 15, 3, 0, 0)


class FakeModel:
    """Deterministic model double (same shape as the graph tests use)."""

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


def make_user(user_id: int = 1) -> UserPublic:
    return UserPublic(
        id=user_id,
        username=f"user-{user_id}",
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


def _override_db(session_factory):
    def override():
        db = session_factory()
        try:
            yield db
        finally:
            db.close()

    return override


@pytest.fixture
def client(session_factory):
    app.dependency_overrides[get_current_user] = make_user
    app.dependency_overrides[get_access_token] = lambda: "token"
    app.dependency_overrides[get_db] = _override_db(session_factory)
    try:
        # 兜底 handler 生成响应后 Starlette 仍会重新抛出异常，因此这里关闭
        # raise_server_exceptions，才能断言客户端真正收到的那份安全响应。
        yield TestClient(app, raise_server_exceptions=False)
    finally:
        app.dependency_overrides.clear()


def add_run(
    db,
    *,
    run_id: str,
    owner_user_id: int = 1,
    status: str = "completed",
    started_at: datetime = STARTED,
    error: str | None = None,
) -> AgentRun:
    run = AgentRun(
        run_id=run_id,
        owner_user_id=owner_user_id,
        title=f"故障 {run_id}",
        input_content="MySQL connection timeout",
        knowledge_base_id=3,
        status=status,
        model_name="deepseek-chat",
        iteration=1,
        max_iterations=4,
        observations=[],
        report=None,
        error=error,
        started_at=started_at,
    )
    db.add(run)
    db.commit()
    return run


class _OfflineAuthorizer(StaticKnowledgeBaseAuthorizer):
    """静态授权器 + ``close()``。

    路由的 ``finally`` 会关闭它自己构造的授权器，所以替换品必须提供 ``close()``，
    否则测试里看到的是一个和业务无关的 ``AttributeError``（这正是第一次运行时
    暴露出来的问题）。
    """

    def close(self) -> None:
        return None


def patch_authorizer(monkeypatch, mode: str = "allowed"):
    """Keep the pre-flight knowledge-base check deterministic and offline.

    路由层自己构造 `HttpKnowledgeBaseAuthorizer` 并注入 service，所以要 patch
    路由模块里的这个名字（patch service 里的同名符号对 API 路径无效）。
    """

    import app.incident_agent.routers.incidents as incidents_router_module

    monkeypatch.setattr(
        incidents_router_module,
        "HttpKnowledgeBaseAuthorizer",
        lambda *args, **kwargs: _OfflineAuthorizer(mode=mode),
    )


def patch_models(monkeypatch, agent_model, report_model):
    import app.incident_agent.services.incident as incident_module

    monkeypatch.setattr(
        incident_module,
        "create_chat_model",
        lambda settings: agent_model,
    )
    monkeypatch.setattr(
        incident_module,
        "create_report_model",
        lambda settings: report_model,
    )


# --------------------------------------------------------------------------
# 1. owner 隔离与未知 ID
# --------------------------------------------------------------------------


def test_foreign_and_unknown_run_ids_are_indistinguishable(client, session_factory):
    """别人的 run_id 与不存在的 run_id 必须给出完全一样的响应。"""

    with session_factory() as db:
        add_run(db, run_id="someone-elses-run", owner_user_id=2)

    foreign = client.get("/api/v1/runs/someone-elses-run")
    unknown = client.get("/api/v1/runs/definitely-not-a-run")

    assert foreign.status_code == unknown.status_code == 404
    # 除了 request_id（每个请求都不同），其余必须逐字节一致。
    foreign_body = {k: v for k, v in foreign.json().items() if k != "request_id"}
    unknown_body = {k: v for k, v in unknown.json().items() if k != "request_id"}
    assert foreign_body == unknown_body
    assert foreign_body["error_code"] == "NOT_FOUND"


def test_list_filters_and_cursor_never_cross_the_owner_boundary(client, session_factory):
    with session_factory() as db:
        add_run(db, run_id="mine", owner_user_id=1, status="degraded")
        add_run(db, run_id="theirs", owner_user_id=2, status="degraded")

    response = client.get("/api/v1/runs", params={"status": "degraded", "limit": 100})

    assert response.status_code == 200
    assert [item["run_id"] for item in response.json()["items"]] == ["mine"]


def test_analyze_does_not_leave_a_row_when_the_knowledge_base_is_someone_elses(
    client,
    session_factory,
    monkeypatch,
):
    """授权预校验失败（P0-2-1）在 API 层的回归：失败不产生任何运行记录。"""

    patch_authorizer(monkeypatch, mode="denied")

    response = client.post(
        "/api/v1/incidents/analyze",
        json={"title": "t", "content": "c", "knowledge_base_id": 999},
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "知识库不存在或当前用户无权访问"
    with session_factory() as db:
        assert db.scalar(select(AgentRun)) is None


# --------------------------------------------------------------------------
# 2. 过期 Token
# --------------------------------------------------------------------------


def _patch_auth_client(monkeypatch, handler):
    """Make the Agent believe DevAtlas answered ``handler``."""

    def factory(base_url: str, timeout_seconds: float = 20.0):
        client = DevAtlasAuthClient(base_url, timeout_seconds)
        client._client = httpx.Client(
            base_url=base_url,
            timeout=httpx.Timeout(timeout_seconds),
            transport=httpx.MockTransport(handler),
        )
        return client

    monkeypatch.setattr(dependencies_module, "DevAtlasAuthClient", factory)


@pytest.mark.parametrize(
    ("method", "path", "payload"),
    [
        ("get", "/api/v1/runs", None),
        ("get", "/api/v1/runs/whatever", None),
        ("post", "/api/v1/incidents/analyze", {"title": "t", "content": "c", "knowledge_base_id": 3}),
    ],
)
def test_expired_token_is_401_everywhere(
    monkeypatch,
    client,
    method: str,
    path: str,
    payload: dict | None,
):
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.headers.get("Authorization", ""))
        # DevAtlas 对过期/无效令牌的回答
        return httpx.Response(401, json={"detail": "token expired"})

    _patch_auth_client(monkeypatch, handler)
    app.dependency_overrides.clear()

    response = client.request(
        method,
        path,
        json=payload,
        headers={"Authorization": "Bearer expired-token"},
    )

    assert response.status_code == 401
    assert response.headers.get("WWW-Authenticate") == "Bearer"
    assert response.json()["error_code"] == "UNAUTHORIZED"
    assert response.json()["detail"] == "登录状态无效或已过期"
    # Token 必须原样转发给 DevAtlas，Agent 自己不解码、不续期。
    assert seen == ["Bearer expired-token"]


def test_expired_token_does_not_touch_the_database(monkeypatch, client, session_factory):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"detail": "token expired"})

    _patch_auth_client(monkeypatch, handler)
    app.dependency_overrides.clear()

    response = client.post(
        "/api/v1/incidents/analyze",
        headers={"Authorization": "Bearer expired-token"},
        json={"title": "t", "content": "c", "knowledge_base_id": 3},
    )

    assert response.status_code == 401
    with session_factory() as db:
        assert db.scalar(select(AgentRun)) is None


def test_devatlas_outage_is_503_not_401(monkeypatch, client):
    """上游挂了与"你的令牌过期了"必须区分开，否则前端会误登出。"""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={"detail": "down"})

    _patch_auth_client(monkeypatch, handler)
    app.dependency_overrides.clear()

    response = client.get("/api/v1/runs", headers={"Authorization": "Bearer token"})

    assert response.status_code == 503
    assert response.json()["error_code"] == "DEPENDENCY_UNAVAILABLE"


# --------------------------------------------------------------------------
# 3. 数据库异常
# --------------------------------------------------------------------------

_DB_FAILURE_MARKERS = (
    "Traceback",
    "sqlite",
    "OperationalError",
    "SELECT ",
    "INSERT ",
    "E:\\",
    "app/incident_agent",
)


def _assert_safe_500(response: httpx.Response) -> None:
    assert response.status_code == 500
    body = response.json()
    assert body["error_code"] == "AGENT_INTERNAL_ERROR"
    assert body["detail"] == "服务内部错误，请稍后重试"
    for marker in _DB_FAILURE_MARKERS:
        assert marker not in response.text, marker


def test_write_failure_while_creating_the_run_is_a_safe_500(
    client,
    session_factory,
    monkeypatch,
):
    import app.incident_agent.services.incident as incident_module

    def exploding_create_run(*args, **kwargs):
        raise OperationalError("INSERT INTO agent_runs ...", {}, Exception("disk full"))

    patch_authorizer(monkeypatch)
    monkeypatch.setattr(incident_module, "create_run", exploding_create_run)

    response = client.post(
        "/api/v1/incidents/analyze",
        json={"title": "t", "content": "c", "knowledge_base_id": 3},
    )

    _assert_safe_500(response)
    with session_factory() as db:
        assert db.scalar(select(AgentRun)) is None


def test_write_failure_after_the_row_exists_leaves_a_reclaimable_record(
    client,
    session_factory,
    monkeypatch,
):
    """图跑完但收尾写库失败：记录仍必须是可解释、可回收的，而不是永久 running。"""

    import app.incident_agent.services.incident as incident_module

    patch_authorizer(monkeypatch)
    monkeypatch.setattr(
        incident_module,
        "create_chat_model",
        lambda settings: FakeModel([AIMessage(content="没有更多工具需要调用。")]),
    )
    monkeypatch.setattr(
        incident_module,
        "create_report_model",
        lambda settings: FakeModel([AIMessage(content="不是 JSON")]),
    )

    def exploding_finish_run(*args, **kwargs):
        raise OperationalError("UPDATE agent_runs ...", {}, Exception("connection lost"))

    monkeypatch.setattr(incident_module, "finish_run", exploding_finish_run)

    response = client.post(
        "/api/v1/incidents/analyze",
        json={"title": "t", "content": "c", "knowledge_base_id": 3},
    )

    _assert_safe_500(response)

    with session_factory() as db:
        run = db.scalar(select(AgentRun))
        assert run is not None
        # 收尾失败后仍停在 running：这正是启动回收机制存在的理由。
        assert run.status == "running"
        reclaimed = reclaim_stale_runs(db, stale_after=timedelta(seconds=0))
        assert reclaimed == 1

    with session_factory() as db:
        run = db.scalar(select(AgentRun))
        assert run.status == "degraded"
        assert run.interrupted_at is not None

    # 回收之后，接口把它报成 interrupted，且不给一个虚假的耗时（P1-3-2）。
    listed = client.get("/api/v1/runs").json()["items"][0]
    assert listed["interrupted"] is True
    assert listed["duration_ms"] is None


def test_read_failure_on_the_history_endpoint_is_a_safe_500(monkeypatch, session_factory):
    def exploding_db():
        raise OperationalError("SELECT ... FROM agent_runs", {}, Exception("gone away"))

    app.dependency_overrides[get_current_user] = make_user
    app.dependency_overrides[get_access_token] = lambda: "token"
    app.dependency_overrides[get_db] = exploding_db
    try:
        client = TestClient(app, raise_server_exceptions=False)
        response = client.get("/api/v1/runs")
    finally:
        app.dependency_overrides.clear()

    _assert_safe_500(response)


# --------------------------------------------------------------------------
# 4. 失败状态持久化
# --------------------------------------------------------------------------


def test_degraded_run_is_persisted_and_readable(client, session_factory, monkeypatch):
    """工具失败 → degraded：状态、错误与降级摘要都要落库并能从接口读回来。"""

    import app.incident_agent.services.incident as incident_module

    patch_authorizer(monkeypatch)
    patch_models(
        monkeypatch,
        FakeModel(
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
                )
            ]
        ),
        FakeModel([]),
    )
    # 检索网关不可用 → 工具失败 → 图走降级分支
    monkeypatch.setattr(
        incident_module,
        "HttpRagGateway",
        lambda *args, **kwargs: MockRagGateway(mode="unavailable"),
    )

    response = client.post(
        "/api/v1/incidents/analyze",
        json={"title": "订单服务故障", "content": "网关返回 502", "knowledge_base_id": 3},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "degraded"

    with session_factory() as db:
        run = db.scalar(select(AgentRun))
        assert run is not None
        assert run.status == "degraded"
        assert run.error
        assert run.degraded_summary is not None

    listed = client.get("/api/v1/runs", params={"status": "degraded"}).json()["items"]
    assert [item["run_id"] for item in listed] == [run.run_id]

    detail = client.get(f"/api/v1/runs/{run.run_id}").json()
    assert detail["status"] == "degraded"
    assert detail["degraded_summary"]["reason"] == "degraded"
    assert detail["error"] == run.error


def test_report_validation_failed_is_persisted_and_filterable(
    client,
    session_factory,
    monkeypatch,
):
    patch_authorizer(monkeypatch)
    patch_models(
        monkeypatch,
        FakeModel([AIMessage(content="没有更多工具需要调用。")]),
        FakeModel([AIMessage(content="这不是 JSON")]),
    )

    response = client.post(
        "/api/v1/incidents/analyze",
        json={"title": "无法确定原因", "content": "日志没有明显信号", "knowledge_base_id": 3},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "report_validation_failed"

    with session_factory() as db:
        run = db.scalar(select(AgentRun))
        assert run.status == "report_validation_failed"
        assert run.report is None
        assert "不是合法 JSON" in run.error

    listed = client.get(
        "/api/v1/runs",
        params={"status": "report_validation_failed"},
    ).json()["items"]
    assert [item["run_id"] for item in listed] == [run.run_id]
    # 摘要里带上错误文本，详情里有完整错误
    assert listed[0]["error"]
    assert client.get(f"/api/v1/runs/{run.run_id}").json()["error"] == run.error


def _mock_gateway_init(self, *args, **kwargs):
    """Unused placeholder kept out of the way of the real MockRagGateway."""

    self.mode = kwargs.get("mode", "ok")


def test_failed_run_keeps_its_own_timeline(client, session_factory):
    """失败记录同样有时间线：started_at 必须有值，未收尾时没有耗时。"""

    with session_factory() as db:
        add_run(
            db,
            run_id="failed-run",
            owner_user_id=1,
            status="degraded",
            error="工具失败",
        )

    item = client.get("/api/v1/runs").json()["items"][0]

    assert item["status"] == "degraded"
    assert item["started_at"] is not None
    assert item["duration_ms"] is None
