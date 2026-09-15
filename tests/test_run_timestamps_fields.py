"""P1-3-2：时间、耗时和标题必须能从列表与详情两个接口读出来。

对应设计文档 15.3「总耗时大致是多少？」——这一项之前完全无法回答：两个接口都
没有时间字段，前端只能显示 run_id 和状态。
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.incident_agent.db.session import Base, get_db
from app.incident_agent.dependencies import get_access_token, get_current_user
from app.incident_agent.models import AgentRun
from app.incident_agent.schemas.auth import UserPublic
from app.incident_agent.schemas.incident import RunResponse, RunSummary, elapsed_ms
from app.main import app

STARTED = datetime(2026, 9, 15, 3, 0, 0)


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
    started_at: datetime,
    completed_at: datetime | None,
    interrupted_at: datetime | None = None,
    title: str = "订单服务返回 502",
    status: str = "completed",
) -> AgentRun:
    run = AgentRun(
        run_id=run_id,
        owner_user_id=1,
        title=title,
        input_content="MySQL connection timeout",
        knowledge_base_id=3,
        status=status,
        model_name="deepseek-chat",
        iteration=1,
        max_iterations=4,
        observations=[],
        report=None,
        started_at=started_at,
        completed_at=completed_at,
        interrupted_at=interrupted_at,
    )
    db.add(run)
    db.commit()
    return run


# --------------------------------------------------------------------------
# elapsed_ms：派生耗时的语义
# --------------------------------------------------------------------------


def test_elapsed_ms_returns_the_wall_clock_duration():
    assert elapsed_ms(STARTED, STARTED + timedelta(seconds=8, milliseconds=400)) == 8400
    assert elapsed_ms(STARTED, STARTED) == 0


def test_elapsed_ms_is_none_while_the_run_has_not_finished():
    assert elapsed_ms(STARTED, None) is None
    assert elapsed_ms(None, STARTED) is None


def test_interrupted_run_reports_no_duration():
    """被回收的 run 的 completed_at 是「下一次启动发现它」的时刻。

    用它减 started_at 得到的是进程死了多久，不是分析耗时，所以必须返回 None。
    """

    reclaimed_at = STARTED + timedelta(hours=3)
    assert (
        elapsed_ms(STARTED, reclaimed_at, interrupted=True) is None
    )


def test_elapsed_ms_never_returns_a_negative_value():
    """客户端/数据库时钟回拨时宁可没有耗时，也不显示负数。"""

    assert elapsed_ms(STARTED, STARTED - timedelta(seconds=5)) is None


# --------------------------------------------------------------------------
# 列表接口
# --------------------------------------------------------------------------


def test_list_returns_title_time_and_duration(client, session_factory):
    with session_factory() as db:
        add_run(
            db,
            run_id="run-timed",
            started_at=STARTED,
            completed_at=STARTED + timedelta(seconds=12, milliseconds=500),
            title="支付超时排查",
        )

    item = client.get("/api/v1/runs").json()["items"][0]

    assert item["title"] == "支付超时排查"
    assert item["started_at"] == "2026-09-15T03:00:00+00:00"
    assert item["completed_at"] == "2026-09-15T03:00:12.500000+00:00"
    assert item["duration_ms"] == 12500


def test_list_duration_is_null_for_running_and_interrupted_runs(
    client,
    session_factory,
):
    with session_factory() as db:
        add_run(
            db,
            run_id="run-running",
            started_at=STARTED,
            completed_at=None,
            status="running",
        )
        add_run(
            db,
            run_id="run-interrupted",
            started_at=STARTED,
            completed_at=STARTED + timedelta(hours=2),
            interrupted_at=STARTED + timedelta(hours=2),
            status="degraded",
        )

    by_id = {
        item["run_id"]: item for item in client.get("/api/v1/runs").json()["items"]
    }

    assert by_id["run-running"]["duration_ms"] is None
    assert by_id["run-interrupted"]["duration_ms"] is None
    assert by_id["run-interrupted"]["interrupted"] is True


def test_summary_contract_includes_duration_ms():
    """契约变更要显式：duration_ms 是派生的计算字段，必须在返回体里。"""

    fields = set(RunSummary.model_fields) | set(RunSummary.model_computed_fields)
    assert "duration_ms" in fields
    assert {"title", "started_at", "completed_at"} <= fields


# --------------------------------------------------------------------------
# 详情接口
# --------------------------------------------------------------------------


def test_detail_returns_title_time_and_duration(client, session_factory):
    with session_factory() as db:
        add_run(
            db,
            run_id="run-detail-timed",
            started_at=STARTED,
            completed_at=STARTED + timedelta(minutes=1, seconds=5),
            title="订单服务返回 502",
        )

    body = client.get("/api/v1/runs/run-detail-timed").json()

    assert body["title"] == "订单服务返回 502"
    assert body["started_at"] == "2026-09-15T03:00:00+00:00"
    assert body["completed_at"] == "2026-09-15T03:01:05+00:00"
    assert body["duration_ms"] == 65000
    # 详情仍然返回完整轨迹字段
    assert {"observations", "steps", "report"} <= set(body)
    assert {"duration_ms", "title", "started_at", "completed_at"} <= set(
        RunResponse.model_fields
    ) | set(RunResponse.model_computed_fields)


def test_response_from_state_takes_timestamps_from_the_persisted_row():
    """POST /analyze 的响应也必须回答耗时，且用的是落库后的行值。"""

    from app.incident_agent.services.incident import _response_from_state

    run = AgentRun(
        run_id="run-from-state",
        owner_user_id=1,
        title="订单服务返回 502",
        input_content="c",
        knowledge_base_id=3,
        status="completed",
        model_name="m",
        iteration=1,
        max_iterations=4,
        observations=[],
        report=None,
        started_at=STARTED,
        completed_at=STARTED + timedelta(seconds=3),
    )
    state = {
        "run_id": "run-from-state",
        "title": "订单服务返回 502",
        "status": "completed",
        "observations": [],
        "steps": [],
        "error": None,
        "report": None,
    }

    response = _response_from_state(state, run)

    assert response.title == "订单服务返回 502"
    assert response.started_at == STARTED
    assert response.completed_at == STARTED + timedelta(seconds=3)
    assert response.duration_ms == 3000


def test_response_from_state_without_a_row_still_builds():
    """图执行失败等场景下没有落库行时，响应不能因为缺字段而崩。"""

    from app.incident_agent.services.incident import _response_from_state

    state = {
        "run_id": "run-no-row",
        "title": "订单服务返回 502",
        "status": "degraded",
        "observations": [],
        "steps": [],
        "error": "模型超时",
        "report": None,
    }

    response = _response_from_state(state)

    assert response.started_at is None
    assert response.duration_ms is None
    assert response.status == "degraded"


def test_utc_timestamps_are_not_rendered_as_local_wall_clock():
    """naive UTC 必须带 +00:00 输出，否则前端会把 UTC 当成本地时间。"""

    naive = datetime(2026, 9, 15, 3, 0, 0)

    class _Row:
        run_id = "r"
        title = "t"
        status = "completed"
        started_at = naive
        completed_at = naive + timedelta(seconds=1)
        interrupted_at = None
        report = None
        observations = []
        steps = []
        error = None
        degraded_summary = None

    from app.incident_agent.routers.runs import _to_response

    payload = _to_response(_Row()).model_dump(mode="json")

    assert payload["started_at"].endswith("+00:00")
    assert payload["duration_ms"] == 1000


def test_aware_utc_input_is_converted_consistently():
    """即使调用方传进来的是 aware datetime，序列化结果也一致。"""

    aware_start = datetime(2026, 9, 15, 3, 0, tzinfo=UTC)
    summary = RunSummary(
        run_id="r",
        title="t",
        status="completed",
        knowledge_base_id=3,
        iteration=1,
        max_iterations=4,
        steps_count=0,
        observations_count=0,
        started_at=aware_start,
        completed_at=aware_start + timedelta(milliseconds=250),
    )

    payload = summary.model_dump(mode="json")

    assert payload["started_at"] == "2026-09-15T03:00:00+00:00"
    assert payload["duration_ms"] == 250
