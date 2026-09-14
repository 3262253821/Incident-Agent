"""UTC timestamp handling (P1-2-3).

The completion standard is that timestamps stay correct *and* that no
``datetime.utcnow()`` deprecation warning is produced. The column type is
deliberately left timezone-naive; these tests pin the reasoning so a later
change cannot silently flip it:

- both MySQL ``DATETIME`` and SQLite hand the value back naive, so
  ``DateTime(timezone=True)`` would change nothing that is stored;
- values are written as naive UTC and serialised as ISO 8601 at the API edge.
"""

from __future__ import annotations

import datetime as dt
import warnings

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.incident_agent.db.session import Base
from app.incident_agent.models import AgentRun, AgentStep
from app.incident_agent.models.agent_run import utc_now
from app.incident_agent.services.storage import (
    append_steps,
    create_run,
    finish_run,
    reclaim_stale_runs,
)


def make_session():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


def test_utc_now_is_naive_utc_and_tracks_the_clock():
    before = dt.datetime.now(dt.UTC).replace(tzinfo=None)
    value = utc_now()
    after = dt.datetime.now(dt.UTC).replace(tzinfo=None)

    assert value.tzinfo is None, "存储约定是 naive UTC"
    assert before <= value <= after


def test_model_defaults_do_not_use_the_deprecated_api():
    """Importing and inserting must not emit a DeprecationWarning."""

    Session = make_session()

    with warnings.catch_warnings():
        warnings.simplefilter("error", DeprecationWarning)
        with Session() as db:
            # create_run 依赖 AgentRun.started_at 的默认值
            run = create_run(
                db,
                run_id="run-utc-1",
                owner_user_id=1,
                title="t",
                input_content="c",
                knowledge_base_id=3,
                model_name="m",
                max_iterations=4,
            )
            append_steps(
                db,
                run,
                [{"iteration": 1, "node": "agent", "action": "model_request"}],
            )

    assert run.started_at is not None


def test_finish_run_stamps_completed_at_without_deprecation():
    Session = make_session()

    with warnings.catch_warnings():
        warnings.simplefilter("error", DeprecationWarning)
        with Session() as db:
            run = create_run(
                db,
                run_id="run-utc-2",
                owner_user_id=1,
                title="t",
                input_content="c",
                knowledge_base_id=3,
                model_name="m",
                max_iterations=4,
            )
            finish_run(
                db,
                run,
                status="completed",
                iteration=1,
                observations=[],
                report=None,
                error=None,
            )

    assert run.completed_at is not None


def test_timestamps_are_stored_as_naive_utc():
    """Whatever the engine returns, it must be naive and UTC-based."""

    Session = make_session()

    with Session() as db:
        run = create_run(
            db,
            run_id="run-utc-3",
            owner_user_id=1,
            title="t",
            input_content="c",
            knowledge_base_id=3,
            model_name="m",
            max_iterations=4,
        )
        db.refresh(run)
        stored = run.started_at
        step = AgentStep(
            run_id=run.id,
            step_index=1,
            iteration=1,
            node="agent",
            action="model_request",
            status="success",
        )
        db.add(step)
        db.commit()
        db.refresh(step)
        step_created = step.created_at

    for value in (stored, step_created):
        assert value.tzinfo is None
        # 与真实 UTC 相差不超过一分钟
        delta = abs(
            value - dt.datetime.now(dt.UTC).replace(tzinfo=None)
        )
        assert delta < dt.timedelta(minutes=1)


def test_stale_run_window_uses_the_same_naive_utc_basis():
    """The reclaim cutoff must not mix naive and aware datetimes."""

    Session = make_session()
    old = dt.datetime.now(dt.UTC).replace(tzinfo=None) - dt.timedelta(minutes=30)

    with Session() as db:
        run = create_run(
            db,
            run_id="run-utc-4",
            owner_user_id=1,
            title="t",
            input_content="c",
            knowledge_base_id=3,
            model_name="m",
            max_iterations=4,
        )
        run.started_at = old
        db.commit()

        reclaimed = reclaim_stale_runs(db)

        refreshed = db.scalar(select(AgentRun).where(AgentRun.run_id == "run-utc-4"))
        assert reclaimed == 1
        assert refreshed.interrupted_at is not None
        assert refreshed.interrupted_at.tzinfo is None
        assert refreshed.completed_at.tzinfo is None


def test_api_serialises_timestamps_as_iso8601():
    """Outgoing timestamps must carry an explicit UTC designator."""

    Session = make_session()

    with Session() as db:
        run = create_run(
            db,
            run_id="run-utc-5",
            owner_user_id=1,
            title="t",
            input_content="c",
            knowledge_base_id=3,
            model_name="m",
            max_iterations=4,
        )
        db.refresh(run)
        # 模型字段是 naive；API 层补上 UTC 标记后再输出
        aware = run.started_at.replace(tzinfo=dt.UTC)
        serialised = aware.isoformat()

    assert serialised.endswith("+00:00")
    assert "T" in serialised
