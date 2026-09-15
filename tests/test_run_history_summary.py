"""P1-3-1：历史列表必须是一次查询，并且只返回摘要。

三条独立的断言，分别对应审计里的三个证据：

1. 列表响应不再包含 ``observations`` / ``steps`` / ``report`` 这些会把日志
   全文带出去的大字段；
2. 列表的 SQL 语句数与 run 条数无关（原来 5 条 run 会变成 1 + 5 条查询）；
3. 详情接口仍然返回完整轨迹，并显式预加载 steps。
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.dialects import mysql, sqlite
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.incident_agent.db.session import Base, get_db
from app.incident_agent.dependencies import get_access_token, get_current_user
from app.incident_agent.models import AgentRun, AgentStep
from app.incident_agent.schemas.auth import UserPublic
from app.incident_agent.schemas.incident import (
    ERROR_SUMMARY_MAX_LENGTH,
    RunSummary,
    iso_utc,
    summarize_error,
)
from app.incident_agent.services.storage import build_run_summary_statement
from app.main import app


def make_user(user_id: int = 1) -> UserPublic:
    return UserPublic(
        id=user_id,
        username=f"user-{user_id}",
        role="user",
        is_active=True,
        created_at="2026-09-04T00:00:00Z",
        updated_at="2026-09-04T00:00:00Z",
    )


class StatementCounter:
    """Count the SQL statements one request issues, without touching the code."""

    def __init__(self, engine):
        self.statements: list[str] = []
        event.listen(engine, "before_cursor_execute", self._record)

    def _record(self, conn, cursor, statement, parameters, context, executemany):
        self.statements.append(statement)

    def reset(self) -> None:
        self.statements.clear()

    @property
    def count(self) -> int:
        return len(self.statements)


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
def client(session_factory):
    def override_db():
        db = session_factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_current_user] = make_user
    app.dependency_overrides[get_access_token] = lambda: "token"
    app.dependency_overrides[get_db] = override_db
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def add_run(
    db: Session,
    *,
    run_id: str,
    owner_user_id: int = 1,
    title: str = "订单服务返回 502",
    status: str = "completed",
    steps: int = 0,
    observations: list[dict] | None = None,
    report: dict | None = None,
    error: str | None = None,
    started_at: datetime | None = None,
) -> AgentRun:
    run = AgentRun(
        run_id=run_id,
        owner_user_id=owner_user_id,
        title=title,
        input_content="MySQL connection timeout",
        knowledge_base_id=3,
        status=status,
        model_name="deepseek-chat",
        iteration=1,
        max_iterations=4,
        observations=observations if observations is not None else [],
        report=report,
        error=error,
        started_at=started_at or datetime.now(UTC).replace(tzinfo=None),
    )
    db.add(run)
    db.commit()
    for index in range(steps):
        db.add(
            AgentStep(
                run_id=run.id,
                step_index=index + 1,
                iteration=1,
                node="agent",
                action="tool",
                tool_name="analyze_log",
                status="ok",
                duration_ms=12,
            )
        )
    db.commit()
    return run


# --------------------------------------------------------------------------
# Response shape: summary only
# --------------------------------------------------------------------------


def test_list_returns_only_the_summary_fields(client, session_factory):
    with session_factory() as db:
        add_run(
            db,
            run_id="run-summary-1",
            steps=2,
            observations=[{"iteration": 1}, {"iteration": 2}, {"iteration": 3}],
            report={"summary": "s"},
        )

    response = client.get("/api/v1/runs")

    assert response.status_code == 200
    payload = response.json()
    assert len(payload) == 1
    item = payload[0]

    # 契约就是 RunSummary 本身：多一个字段（例如轨迹）都算回归。
    assert set(item) == set(RunSummary.model_fields)
    assert item["run_id"] == "run-summary-1"
    assert item["title"] == "订单服务返回 502"
    assert item["status"] == "completed"
    assert item["knowledge_base_id"] == 3
    assert item["steps_count"] == 2
    assert item["observations_count"] == 3
    assert item["interrupted"] is False
    assert item["error"] is None
    assert item["started_at"].endswith("+00:00")
    assert item["completed_at"] is None

    for omitted in ("observations", "steps", "report", "degraded_summary"):
        assert omitted not in item


def test_summary_sql_never_selects_the_json_payloads():
    """The list must not read observations/report 全文，只做计数。"""

    sqlite_sql = str(
        build_run_summary_statement(
            dialect_name="sqlite",
            owner_user_id=1,
            limit=20,
        ).compile(dialect=sqlite.dialect())
    )
    mysql_sql = str(
        build_run_summary_statement(
            dialect_name="mysql",
            owner_user_id=1,
            limit=20,
        ).compile(dialect=mysql.dialect())
    )

    # 两个方言各自用能就地统计 JSON 数组的函数。
    assert "json_array_length(agent_runs.observations)" in sqlite_sql
    assert "json_length(agent_runs.observations)" in mysql_sql

    for sql in (sqlite_sql, mysql_sql):
        assert "agent_runs.observations," not in sql
        assert "agent_runs.report" not in sql
        assert "agent_runs.degraded_summary" not in sql
        assert "agent_steps" in sql


def test_list_query_count_does_not_grow_with_the_number_of_runs(
    client,
    engine,
    session_factory,
):
    """反 N+1：审计实测 5 条 run 各 3 个 step 会产生 5 条额外查询。"""

    counter = StatementCounter(engine)

    with session_factory() as db:
        add_run(db, run_id="run-one", steps=3)

    counter.reset()
    assert client.get("/api/v1/runs").status_code == 200
    one_run_queries = counter.count

    with session_factory() as db:
        for index in range(4):
            add_run(db, run_id=f"run-more-{index}", steps=3)

    counter.reset()
    response = client.get("/api/v1/runs")
    five_run_queries = counter.count

    assert response.status_code == 200
    assert len(response.json()) == 5
    assert one_run_queries == 1
    assert five_run_queries == one_run_queries


def test_detail_query_count_does_not_grow_with_the_number_of_steps(
    client,
    engine,
    session_factory,
):
    counter = StatementCounter(engine)

    with session_factory() as db:
        add_run(db, run_id="run-few-steps", steps=2)
        add_run(db, run_id="run-many-steps", steps=40)

    counter.reset()
    few = client.get("/api/v1/runs/run-few-steps")
    few_queries = counter.count

    counter.reset()
    many = client.get("/api/v1/runs/run-many-steps")
    many_queries = counter.count
    step_statement = counter.statements[-1]

    assert few.status_code == many.status_code == 200
    # 预加载：1 条主表 + 1 条批量 steps，与步数无关。
    assert few_queries == 2
    assert many_queries == 2
    assert len(many.json()["steps"]) == 40
    # 批量形态（IN）而不是每条 run 一次懒加载（= ?），这是 selectinload 的证据。
    assert " IN (" in step_statement
    assert "agent_steps" in step_statement


# --------------------------------------------------------------------------
# Detail contract
# --------------------------------------------------------------------------


def test_detail_still_returns_the_full_trajectory(client, session_factory):
    with session_factory() as db:
        add_run(
            db,
            run_id="run-detail",
            steps=2,
            observations=[{"iteration": 1, "tool_name": "analyze_log"}],
            report={
                "summary": "订单服务 502。",
                "category": "database",
                "evidence": [
                    {
                        "source": "knowledge_base",
                        "detail": "连接池耗尽会导致 502。",
                    }
                ],
                "possible_causes": ["连接池耗尽"],
                "troubleshooting_steps": ["检查连接池"],
                "references": [],
                "confidence": "medium",
            },
        )

    response = client.get("/api/v1/runs/run-detail")

    assert response.status_code == 200
    body = response.json()
    assert len(body["steps"]) == 2
    assert len(body["observations"]) == 1
    assert body["report"]["summary"] == "订单服务 502。"
    assert body["degraded_summary"] is None
    assert "steps_count" not in body


def test_missing_run_is_still_404(client):
    response = client.get("/api/v1/runs/not-a-real-run")

    assert response.status_code == 404
    assert response.json()["detail"] == "运行记录不存在"


# --------------------------------------------------------------------------
# Error summary
# --------------------------------------------------------------------------


def test_long_error_is_truncated_in_the_list_and_full_in_the_detail(
    client,
    session_factory,
):
    long_error = "模型调用超时：" + "x" * 1000

    with session_factory() as db:
        add_run(db, run_id="run-long-error", status="degraded", error=long_error)

    listed = client.get("/api/v1/runs").json()[0]
    detail = client.get("/api/v1/runs/run-long-error").json()

    assert len(listed["error"]) <= ERROR_SUMMARY_MAX_LENGTH
    assert listed["error"].endswith("…")
    assert long_error.startswith(listed["error"][:-1])
    assert detail["error"] == long_error


def test_summarize_error_keeps_short_text_and_marks_truncation():
    assert summarize_error(None) is None
    assert summarize_error("  数据库连接失败  ") == "数据库连接失败"

    exact = "y" * ERROR_SUMMARY_MAX_LENGTH
    assert summarize_error(exact) == exact

    truncated = summarize_error("y" * (ERROR_SUMMARY_MAX_LENGTH + 10))
    assert len(truncated) == ERROR_SUMMARY_MAX_LENGTH
    assert truncated.endswith("…")


def test_iso_utc_marks_naive_storage_values_as_utc():
    naive = datetime(2026, 9, 15, 3, 4, 5)
    aware = naive.replace(tzinfo=UTC)
    shanghai = naive.replace(tzinfo=timezone(timedelta(hours=8)))

    assert iso_utc(None) is None
    assert iso_utc(naive) == "2026-09-15T03:04:05+00:00"
    assert iso_utc(aware) == "2026-09-15T03:04:05+00:00"
    # 带偏移的输入会被换算成 UTC，而不是原样输出本地墙上时间。
    assert iso_utc(shanghai) == "2026-09-14T19:04:05+00:00"


# --------------------------------------------------------------------------
# Owner isolation
# --------------------------------------------------------------------------


def test_list_only_returns_runs_of_the_authenticated_owner(
    client,
    session_factory,
):
    with session_factory() as db:
        add_run(db, run_id="run-mine", owner_user_id=1)
        add_run(db, run_id="run-someone-else", owner_user_id=2)

    listed = client.get("/api/v1/runs").json()
    assert [item["run_id"] for item in listed] == ["run-mine"]

    # 猜中别人的 run_id 也只能得到 404。
    assert client.get("/api/v1/runs/run-someone-else").status_code == 404


# --------------------------------------------------------------------------
# Ordering
# --------------------------------------------------------------------------


def test_runs_with_the_same_timestamp_still_have_a_stable_order(
    client,
    session_factory,
):
    same_moment = datetime(2026, 9, 15, 3, 0, 0)

    with session_factory() as db:
        add_run(db, run_id="run-first", started_at=same_moment)
        add_run(db, run_id="run-second", started_at=same_moment)

    listed = client.get("/api/v1/runs").json()

    assert [item["run_id"] for item in listed] == ["run-second", "run-first"]
