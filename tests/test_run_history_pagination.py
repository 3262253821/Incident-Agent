"""P1-3-3：历史分页、过滤与保留策略。

三条独立的能力，各有对应证据：

1. **游标分页**：翻页不重不漏，且翻页期间新增记录不会让后续页错位（offset 分页
   会重复或漏行）；
2. **过滤**：状态（可重复）与时间范围，未知状态必须 422 而不是静默返回空列表，
   且任何过滤组合都不能越过 `owner_user_id` 这道边界；
3. **保留策略**：默认不删除；启用后按 `started_at` 删除并连带删除 steps，边界上
   保留 cutoff 当刻的记录。

设计文档章节：§13.3.2 历史分页、过滤与保留策略、§12.1 MVP 记录内容。
"""

from __future__ import annotations

import base64
from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.incident_agent.core.pagination import decode_cursor, encode_cursor
from app.incident_agent.db.session import Base, get_db
from app.incident_agent.dependencies import get_access_token, get_current_user
from app.incident_agent.models import AgentRun, AgentStep
from app.incident_agent.schemas.auth import UserPublic
from app.incident_agent.services.storage import (
    RunHistoryFilter,
    list_run_summaries_for_owner,
    purge_expired_runs,
)
from app.main import app

BASE_TIME = datetime(2026, 9, 15, 3, 0, 0)


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
    owner_user_id: int = 1,
    status: str = "completed",
    steps: int = 0,
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
        started_at=started_at,
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
                status="success",
            )
        )
    db.commit()
    return run


def seed_minutes(
    db: Session,
    count: int,
    *,
    owner_user_id: int = 1,
    prefix: str = "run",
) -> list[str]:
    """Create ``count`` runs, newest first, one minute apart."""

    run_ids = []
    for index in range(count):
        run_id = f"{prefix}-{index:02d}"
        add_run(
            db,
            run_id=run_id,
            started_at=BASE_TIME + timedelta(minutes=count - index),
            owner_user_id=owner_user_id,
        )
        run_ids.append(run_id)
    return run_ids


def page(client: TestClient, **params) -> dict:
    response = client.get("/api/v1/runs", params=params)
    assert response.status_code == 200, response.text
    return response.json()


# --------------------------------------------------------------------------
# 游标分页
# --------------------------------------------------------------------------


def test_cursor_pagination_covers_every_row_exactly_once(client, session_factory):
    with session_factory() as db:
        expected = seed_minutes(db, 5)

    seen: list[str] = []
    cursor: str | None = None
    pages = 0
    while True:
        body = page(client, limit=2, cursor=cursor)
        pages += 1
        seen.extend(item["run_id"] for item in body["items"])
        cursor = body["next_cursor"]
        if cursor is None:
            break
        assert pages < 10, "游标分页没有终止"

    assert pages == 3
    assert seen == expected
    assert len(seen) == len(set(seen))


def test_page_size_is_exactly_limit_and_last_page_is_partial(client, session_factory):
    with session_factory() as db:
        seed_minutes(db, 3)

    first = page(client, limit=2)

    assert len(first["items"]) == 2
    assert first["next_cursor"] is not None

    second = page(client, limit=2, cursor=first["next_cursor"])

    assert len(second["items"]) == 1
    assert second["next_cursor"] is None


def test_paging_is_stable_when_a_new_run_arrives(client, session_factory):
    """这是选游标而不是 offset 的直接理由：新增记录不能挤动后续页。"""

    with session_factory() as db:
        seed_minutes(db, 4)

    first = page(client, limit=2)
    first_ids = [item["run_id"] for item in first["items"]]

    with session_factory() as db:
        add_run(db, run_id="run-brand-new", started_at=BASE_TIME + timedelta(hours=5))

    second = page(client, limit=2, cursor=first["next_cursor"])
    second_ids = [item["run_id"] for item in second["items"]]

    assert first_ids == ["run-00", "run-01"]
    assert second_ids == ["run-02", "run-03"]
    assert not set(first_ids) & set(second_ids)
    # 新记录出现在新的第一页，而不是插进正在翻的窗口里。
    assert page(client, limit=1)["items"][0]["run_id"] == "run-brand-new"


def test_each_page_costs_a_single_statement(client, engine, session_factory):
    """分页不能引入 COUNT(*) 之类的额外查询。"""

    statements: list[str] = []
    event.listen(
        engine,
        "before_cursor_execute",
        lambda conn, cursor, statement, params, context, executemany: statements.append(
            statement
        ),
    )

    with session_factory() as db:
        seed_minutes(db, 5)

    statements.clear()
    first = page(client, limit=2)
    # 一条语句就是全部：没有 COUNT(*) 总数查询，也没有第二条"看看还有没有下一页"。
    assert len(statements) == 1

    statements.clear()
    page(client, limit=2, cursor=first["next_cursor"])
    assert len(statements) == 1


def test_limit_is_validated(client):
    assert client.get("/api/v1/runs", params={"limit": 0}).status_code == 422
    assert client.get("/api/v1/runs", params={"limit": 101}).status_code == 422
    assert client.get("/api/v1/runs", params={"limit": 100}).status_code == 200


def test_invalid_cursor_is_a_400_and_leaks_nothing(client, session_factory):
    with session_factory() as db:
        seed_minutes(db, 2)

    response = client.get("/api/v1/runs", params={"cursor": "not-a-cursor"})

    assert response.status_code == 400
    body = response.json()
    assert body["error_code"] == "BAD_REQUEST"
    assert body["detail"] == "分页游标无效，请重新加载历史列表"
    # 不泄露解码细节、SQL 或路径。
    assert "Traceback" not in response.text
    assert "incident_agent" not in response.text

    # 合法 base64 但内容不对，也必须 400 而不是 500。
    bad = base64.urlsafe_b64encode(b"no-separator").decode()
    assert client.get("/api/v1/runs", params={"cursor": bad}).status_code == 400


def test_cursor_round_trip_and_rejections():
    started_at = datetime(2026, 9, 15, 3, 4, 5, 123456)

    token = encode_cursor(started_at, 42)

    assert "|" not in token  # 不透明：客户端不应该看到分隔符
    assert decode_cursor(token) == (started_at, 42)

    for bad in ("", "   ", "!!!", "Zm9v", "bm8tc2VwYXJhdG9y"):
        with pytest.raises(ValueError):
            decode_cursor(bad)


def test_cursor_from_another_owner_cannot_widen_the_scope(client, session_factory):
    """游标只编码 (时间, 主键)，不编码 owner：它绝不能变成越权的钥匙。"""

    with session_factory() as db:
        seed_minutes(db, 3, owner_user_id=2, prefix="theirs")
        seed_minutes(db, 2, owner_user_id=1)

    app.dependency_overrides[get_current_user] = lambda: make_user(2)
    theirs = page(client, limit=1)
    their_cursor = theirs["next_cursor"]
    app.dependency_overrides[get_current_user] = make_user

    assert their_cursor is not None

    body = page(client, limit=5, cursor=their_cursor)

    # 用自己的身份 + 别人的游标：只能看到自己的记录，且不会因为游标直接 404/500。
    assert [item["run_id"] for item in body["items"]] == ["run-00", "run-01"]


# --------------------------------------------------------------------------
# 过滤
# --------------------------------------------------------------------------


def test_status_filter_returns_only_requested_states(client, session_factory):
    with session_factory() as db:
        add_run(db, run_id="ok", started_at=BASE_TIME + timedelta(minutes=5))
        add_run(
            db,
            run_id="bad",
            started_at=BASE_TIME + timedelta(minutes=4),
            status="degraded",
        )
        add_run(
            db,
            run_id="looping",
            started_at=BASE_TIME + timedelta(minutes=3),
            status="max_iterations",
        )

    degraded = page(client, status="degraded")

    assert [item["run_id"] for item in degraded["items"]] == ["bad"]


def test_repeated_status_filter_is_an_or(client, session_factory):
    with session_factory() as db:
        add_run(db, run_id="ok", started_at=BASE_TIME + timedelta(minutes=5))
        add_run(
            db,
            run_id="bad",
            started_at=BASE_TIME + timedelta(minutes=4),
            status="degraded",
        )
        add_run(
            db,
            run_id="looping",
            started_at=BASE_TIME + timedelta(minutes=3),
            status="max_iterations",
        )

    body = page(client, status=["degraded", "max_iterations"])

    assert [item["run_id"] for item in body["items"]] == ["bad", "looping"]


def test_unknown_status_filter_is_rejected(client, session_factory):
    with session_factory() as db:
        seed_minutes(db, 1)

    response = client.get("/api/v1/runs", params={"status": "exploded"})

    assert response.status_code == 422
    body = response.json()
    assert body["error_code"] == "VALIDATION_ERROR"
    assert "exploded" in body["detail"]
    assert "degraded" in body["detail"]


def test_time_range_is_inclusive_start_and_exclusive_end(client, session_factory):
    with session_factory() as db:
        seed_minutes(db, 5)  # run-00 最新 … run-04 最旧

    body = page(
        client,
        started_after=(BASE_TIME + timedelta(minutes=2)).isoformat(),
        started_before=(BASE_TIME + timedelta(minutes=4)).isoformat(),
    )

    # started_at 分别是 +5/+4/+3/+2/+1 分钟，区间 [2, 4) 命中 +2 与 +3，
    # 按新到旧排列。
    assert [item["run_id"] for item in body["items"]] == ["run-02", "run-03"]


def test_aware_filter_timestamps_are_converted_to_utc(client, session_factory):
    with session_factory() as db:
        seed_minutes(db, 3)  # started_at：+3 / +2 / +1 分钟

    shanghai = timezone(timedelta(hours=8))
    # 本地时间 11:02（+08:00）= UTC 03:02，命中 +3（03:03）与 +2（03:02，含边界）。
    body = page(
        client,
        started_after=datetime(2026, 9, 15, 11, 2, tzinfo=shanghai).isoformat(),
    )

    assert [item["run_id"] for item in body["items"]] == ["run-00", "run-01"]


def test_inverted_time_range_is_rejected(client, session_factory):
    with session_factory() as db:
        seed_minutes(db, 1)

    response = client.get(
        "/api/v1/runs",
        params={
            "started_after": (BASE_TIME + timedelta(days=1)).isoformat(),
            "started_before": BASE_TIME.isoformat(),
        },
    )

    assert response.status_code == 422
    assert response.json()["detail"] == "started_after 不能晚于 started_before"


def test_filters_never_escape_the_owner_scope(client, session_factory):
    """过滤条件加得再多，别人的记录也不能出现。"""

    with session_factory() as db:
        add_run(
            db,
            run_id="mine-degraded",
            started_at=BASE_TIME,
            owner_user_id=1,
            status="degraded",
        )
        add_run(
            db,
            run_id="theirs-degraded",
            started_at=BASE_TIME,
            owner_user_id=2,
            status="degraded",
        )

    body = page(client, status="degraded", started_after=BASE_TIME.isoformat())

    assert [item["run_id"] for item in body["items"]] == ["mine-degraded"]


# --------------------------------------------------------------------------
# 保留策略
# --------------------------------------------------------------------------


def test_purge_deletes_old_runs_and_their_steps(session_factory):
    now = BASE_TIME
    with session_factory() as db:
        add_run(
            db,
            run_id="ancient",
            started_at=now - timedelta(days=40),
            steps=3,
        )
        add_run(db, run_id="recent", started_at=now - timedelta(days=1), steps=2)

        purged = purge_expired_runs(db, retention_days=30, now=now)

        assert purged == 1
        assert db.scalar(select(func.count(AgentRun.id))) == 1
        # 只删主表会留下孤儿步骤：SQLite 默认不开外键级联，必须显式删。
        assert db.scalar(select(func.count(AgentStep.id))) == 2
        assert db.scalar(select(AgentRun.run_id)) == "recent"


def test_purge_keeps_rows_exactly_on_the_cutoff(session_factory):
    now = BASE_TIME
    with session_factory() as db:
        add_run(db, run_id="on-cutoff", started_at=now - timedelta(days=30))
        add_run(
            db,
            run_id="just-over",
            started_at=now - timedelta(days=30, seconds=1),
        )

        purged = purge_expired_runs(db, retention_days=30, now=now)

        assert purged == 1
        assert db.scalar(select(AgentRun.run_id)) == "on-cutoff"


def test_purge_is_disabled_by_default(session_factory):
    now = BASE_TIME
    with session_factory() as db:
        add_run(db, run_id="ancient", started_at=now - timedelta(days=3650))

        assert purge_expired_runs(db, retention_days=0, now=now) == 0
        assert purge_expired_runs(db, retention_days=-5, now=now) == 0
        assert db.scalar(select(func.count(AgentRun.id))) == 1


def test_purge_with_nothing_to_delete_returns_zero(session_factory):
    now = BASE_TIME
    with session_factory() as db:
        add_run(db, run_id="fresh", started_at=now - timedelta(hours=1))

        assert purge_expired_runs(db, retention_days=7, now=now) == 0
        assert db.scalar(select(func.count(AgentRun.id))) == 1


def test_lifespan_applies_the_retention_policy(monkeypatch, session_factory):
    """保留策略必须真的接在启动流程上，而不是只写了一个函数。"""

    import app.main as main_module

    with session_factory() as db:
        add_run(db, run_id="ancient", started_at=BASE_TIME - timedelta(days=90))
        add_run(db, run_id="fresh", started_at=BASE_TIME)

    monkeypatch.setattr(main_module, "SessionLocal", session_factory)
    monkeypatch.setattr(
        main_module,
        "settings",
        replace(main_module.settings, run_retention_days=30),
    )

    with TestClient(app):
        with session_factory() as db:
            remaining = list(db.scalars(select(AgentRun.run_id)))

    assert remaining == ["fresh"]


def test_lifespan_without_retention_keeps_history(monkeypatch, session_factory):
    import app.main as main_module

    with session_factory() as db:
        add_run(db, run_id="ancient", started_at=BASE_TIME - timedelta(days=90))

    monkeypatch.setattr(main_module, "SessionLocal", session_factory)
    monkeypatch.setattr(
        main_module,
        "settings",
        replace(main_module.settings, run_retention_days=0),
    )

    with TestClient(app):
        with session_factory() as db:
            assert db.scalar(select(func.count(AgentRun.id))) == 1


def test_startup_survives_a_failing_purge(monkeypatch):
    """保留策略失败不能让服务起不来。"""

    import app.main as main_module

    def exploding_session():
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(main_module, "SessionLocal", exploding_session)
    monkeypatch.setattr(
        main_module,
        "settings",
        replace(main_module.settings, run_retention_days=30),
    )

    with TestClient(app) as client:
        assert client.get("/health").status_code == 200


# --------------------------------------------------------------------------
# storage 层的过滤对象
# --------------------------------------------------------------------------


def test_filter_object_defaults_are_owner_scoped_and_unfiltered(session_factory):
    with session_factory() as db:
        seed_minutes(db, 3, owner_user_id=1)
        seed_minutes(db, 3, owner_user_id=2, prefix="theirs")

        rows, next_cursor = list_run_summaries_for_owner(
            db,
            filters=RunHistoryFilter(owner_user_id=1, limit=20),
        )

    assert len(rows) == 3
    assert next_cursor is None
    assert all(row["title"].startswith("故障 run-") for row in rows)


def test_utc_is_the_assumed_zone_for_naive_filter_input(client, session_factory):
    """naive 输入按 UTC 解释（README 里写明了这一条）。"""

    with session_factory() as db:
        seed_minutes(db, 2)  # started_at 是 +2 分钟与 +1 分钟

    body = page(client, started_after=datetime(2026, 9, 15, 3, 1, 30).isoformat())

    assert [item["run_id"] for item in body["items"]] == ["run-00"]
