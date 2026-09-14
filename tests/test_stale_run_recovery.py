"""Tests for reclaiming abandoned ``running`` records (P0-4-2).

``create_run`` commits a ``running`` row before the graph starts, so a killed or
reloaded process leaves rows that stay ``running`` forever. The fix marks only
genuinely stale rows, and only at startup.
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.incident_agent.core.statuses import RunStatus
from app.incident_agent.db.session import Base, get_db
from app.incident_agent.dependencies import get_access_token, get_current_user
from app.incident_agent.models import AgentRun
from app.incident_agent.schemas.auth import UserPublic
from app.incident_agent.services.storage import (
    STALE_RUN_AFTER,
    create_run,
    reclaim_stale_runs,
)
from app.main import app


def make_engine():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return engine


def make_user() -> UserPublic:
    return UserPublic(
        id=1,
        username="test-user",
        role="user",
        is_active=True,
        created_at="2026-09-04T00:00:00Z",
        updated_at="2026-09-04T00:00:00Z",
    )


def add_run(db, *, run_id: str, status: str, started_at: datetime) -> AgentRun:
    run = create_run(
        db,
        run_id=run_id,
        owner_user_id=1,
        title="订单服务故障",
        input_content="网关返回 502",
        knowledge_base_id=3,
        model_name="deepseek-chat",
        max_iterations=4,
    )
    run.status = status
    run.started_at = started_at
    db.commit()
    db.refresh(run)
    return run


def naive_now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


# --------------------------------------------------------------------------
# Reclamation rules
# --------------------------------------------------------------------------


def test_stale_running_run_is_marked_interrupted():
    engine = make_engine()
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    stale_start = naive_now() - STALE_RUN_AFTER - timedelta(minutes=5)

    with Session() as db:
        add_run(db, run_id="stale-1", status=RunStatus.RUNNING, started_at=stale_start)

        reclaimed = reclaim_stale_runs(db)

        run = db.scalar(select(AgentRun).where(AgentRun.run_id == "stale-1"))
        assert reclaimed == 1
        assert run.status == RunStatus.DEGRADED
        assert run.interrupted_at is not None
        assert run.completed_at is not None
        assert "中断" in run.error


def test_recent_running_run_is_left_alone():
    """A run that is still plausibly executing must not be reclaimed."""

    engine = make_engine()
    Session = sessionmaker(bind=engine, expire_on_commit=False)

    with Session() as db:
        add_run(
            db,
            run_id="fresh-1",
            status=RunStatus.RUNNING,
            started_at=naive_now() - timedelta(seconds=30),
        )

        reclaimed = reclaim_stale_runs(db)

        run = db.scalar(select(AgentRun).where(AgentRun.run_id == "fresh-1"))
        assert reclaimed == 0
        assert run.status == RunStatus.RUNNING
        assert run.interrupted_at is None
        assert run.completed_at is None


def test_finished_runs_are_never_touched():
    engine = make_engine()
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    old = naive_now() - timedelta(days=3)

    with Session() as db:
        for index, status in enumerate(
            [
                RunStatus.COMPLETED,
                RunStatus.DEGRADED,
                RunStatus.MAX_ITERATIONS,
                RunStatus.REPORT_VALIDATION_FAILED,
                RunStatus.INSUFFICIENT_EVIDENCE,
            ]
        ):
            add_run(db, run_id=f"done-{index}", status=status, started_at=old)

        reclaimed = reclaim_stale_runs(db)

        assert reclaimed == 0
        for index in range(5):
            run = db.scalar(select(AgentRun).where(AgentRun.run_id == f"done-{index}"))
            assert run.interrupted_at is None


def test_boundary_just_inside_and_just_outside_the_window():
    engine = make_engine()
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    now = naive_now()

    with Session() as db:
        add_run(
            db,
            run_id="just-inside",
            status=RunStatus.RUNNING,
            started_at=now - STALE_RUN_AFTER + timedelta(seconds=30),
        )
        add_run(
            db,
            run_id="just-outside",
            status=RunStatus.RUNNING,
            started_at=now - STALE_RUN_AFTER - timedelta(seconds=30),
        )

        reclaimed = reclaim_stale_runs(db)

        assert reclaimed == 1
        inside = db.scalar(select(AgentRun).where(AgentRun.run_id == "just-inside"))
        outside = db.scalar(select(AgentRun).where(AgentRun.run_id == "just-outside"))
        assert inside.interrupted_at is None
        assert outside.interrupted_at is not None


def test_reclamation_is_idempotent():
    engine = make_engine()
    Session = sessionmaker(bind=engine, expire_on_commit=False)

    with Session() as db:
        add_run(
            db,
            run_id="stale-2",
            status=RunStatus.RUNNING,
            started_at=naive_now() - STALE_RUN_AFTER - timedelta(minutes=1),
        )

        assert reclaim_stale_runs(db) == 1
        first = db.scalar(select(AgentRun).where(AgentRun.run_id == "stale-2"))
        first_seen = first.interrupted_at

        assert reclaim_stale_runs(db) == 0
        db.refresh(first)
        assert first.interrupted_at == first_seen


def test_reclamation_reports_every_affected_run():
    engine = make_engine()
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    old = naive_now() - STALE_RUN_AFTER - timedelta(minutes=10)

    with Session() as db:
        for index in range(3):
            add_run(
                db,
                run_id=f"stale-{index}",
                status=RunStatus.RUNNING,
                started_at=old,
            )

        assert reclaim_stale_runs(db) == 3


# --------------------------------------------------------------------------
# Startup wiring
# --------------------------------------------------------------------------


def test_lifespan_reclaims_stale_runs_on_startup(monkeypatch):
    """Entering the app lifespan must run the cleanup."""

    engine = make_engine()
    Session = sessionmaker(bind=engine, expire_on_commit=False)

    with Session() as db:
        add_run(
            db,
            run_id="startup-stale",
            status=RunStatus.RUNNING,
            started_at=naive_now() - STALE_RUN_AFTER - timedelta(minutes=2),
        )

    import app.main as main_module

    monkeypatch.setattr(main_module, "SessionLocal", Session)

    with TestClient(app):
        with Session() as db:
            run = db.scalar(select(AgentRun).where(AgentRun.run_id == "startup-stale"))
            assert run.interrupted_at is not None
            assert run.status == RunStatus.DEGRADED


def test_startup_survives_a_failing_cleanup(monkeypatch):
    """A broken database must not stop the service from starting."""

    import app.main as main_module

    def exploding_session():
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(main_module, "SessionLocal", exploding_session)

    with TestClient(app) as client:
        assert client.get("/health").status_code == 200


# --------------------------------------------------------------------------
# API surface
# --------------------------------------------------------------------------


def test_runs_endpoint_reports_the_interrupted_flag():
    engine = make_engine()
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    client = TestClient(app)

    def override_db():
        db = Session()
        try:
            yield db
        finally:
            db.close()

    with Session() as db:
        add_run(
            db,
            run_id="interrupted-run",
            status=RunStatus.RUNNING,
            started_at=naive_now() - STALE_RUN_AFTER - timedelta(minutes=1),
        )
        add_run(
            db,
            run_id="normal-run",
            status=RunStatus.COMPLETED,
            started_at=naive_now(),
        )
        reclaim_stale_runs(db)

    app.dependency_overrides[get_current_user] = make_user
    app.dependency_overrides[get_access_token] = lambda: "token"
    app.dependency_overrides[get_db] = override_db

    try:
        response = client.get("/api/v1/runs")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    by_id = {item["run_id"]: item for item in response.json()}
    assert by_id["interrupted-run"]["interrupted"] is True
    assert by_id["interrupted-run"]["status"] == RunStatus.DEGRADED
    assert by_id["normal-run"]["interrupted"] is False
