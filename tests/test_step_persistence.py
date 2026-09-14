"""Tests for ``append_steps`` idempotency and concurrency (P0-4-3).

The old implementation computed the next ``step_index`` from ``count(*) + 1`` and
only appended, which collides with ``uq_agent_steps_run_index`` whenever a run is
written twice. These tests pin the replacement contract.
"""

from __future__ import annotations

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.incident_agent.db.session import Base
from app.incident_agent.models import AgentRun, AgentStep
from app.incident_agent.services.storage import append_steps, create_run


def make_session():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


def make_run(db, run_id: str = "run-steps-1") -> AgentRun:
    return create_run(
        db,
        run_id=run_id,
        owner_user_id=1,
        title="订单服务故障",
        input_content="网关返回 502",
        knowledge_base_id=3,
        model_name="deepseek-chat",
        max_iterations=4,
    )


def step(index: int) -> dict:
    return {
        "iteration": 1,
        "node": "agent",
        "action": "model_request",
        "status": "success",
        "tool_call_count": index,
    }


def stored_steps(db, run: AgentRun) -> list[AgentStep]:
    return list(
        db.scalars(
            select(AgentStep)
            .where(AgentStep.run_id == run.id)
            .order_by(AgentStep.step_index)
        )
    )


def test_steps_get_sequential_indices_starting_at_one():
    Session = make_session()

    with Session() as db:
        run = make_run(db)
        append_steps(db, run, [step(1), step(2), step(3)])

        rows = stored_steps(db, run)
        assert [row.step_index for row in rows] == [1, 2, 3]


def test_appending_the_same_state_twice_does_not_duplicate_rows():
    """The core regression: a retry must not double-write the same steps."""

    Session = make_session()

    with Session() as db:
        run = make_run(db)
        append_steps(db, run, [step(1), step(2)])
        append_steps(db, run, [step(1), step(2)])

        rows = stored_steps(db, run)
        assert len(rows) == 2
        assert [row.step_index for row in rows] == [1, 2]


def test_reappending_a_shorter_state_replaces_instead_of_colliding():
    """A shorter second write must not leave stale higher indices behind."""

    Session = make_session()

    with Session() as db:
        run = make_run(db)
        append_steps(db, run, [step(1), step(2), step(3)])
        append_steps(db, run, [step(9)])

        rows = stored_steps(db, run)
        assert len(rows) == 1
        assert rows[0].step_index == 1
        assert rows[0].arguments_summary is None
        assert rows[0].tool_call_id is None


def test_appending_after_a_partial_state_continues_the_sequence():
    """Simulates SSE writing the first steps, then the final state overwriting."""

    Session = make_session()

    with Session() as db:
        run = make_run(db)
        append_steps(db, run, [step(1)])
        append_steps(db, run, [step(1), step(2), step(3)])

        rows = stored_steps(db, run)
        assert [row.step_index for row in rows] == [1, 2, 3]


def test_appending_an_empty_list_clears_previous_steps():
    Session = make_session()

    with Session() as db:
        run = make_run(db)
        append_steps(db, run, [step(1), step(2)])
        append_steps(db, run, [])

        assert stored_steps(db, run) == []


def test_steps_of_two_runs_are_isolated():
    Session = make_session()

    with Session() as db:
        first = make_run(db, "run-a")
        second = make_run(db, "run-b")
        append_steps(db, first, [step(1), step(2)])
        append_steps(db, second, [step(1)])

        assert [row.step_index for row in stored_steps(db, first)] == [1, 2]
        assert [row.step_index for row in stored_steps(db, second)] == [1]


def test_relationship_reflects_the_rewritten_steps():
    """Callers read ``run.steps`` right after persisting; it must be fresh."""

    Session = make_session()

    with Session() as db:
        run = make_run(db)
        append_steps(db, run, [step(1), step(2), step(3)])
        assert len(run.steps) == 3

        append_steps(db, run, [step(1)])
        assert len(run.steps) == 1
        assert run.steps[0].step_index == 1


def test_step_payload_fields_are_persisted():
    Session = make_session()

    with Session() as db:
        run = make_run(db)
        append_steps(
            db,
            run,
            [
                {
                    "iteration": 2,
                    "node": "observe",
                    "action": "observe_tool_result",
                    "tool_name": "search_knowledge",
                    "tool_call_id": "call-1",
                    "arguments_summary": {"query_length": 12},
                    "result_summary": {"source_count": 1},
                    "status": "success",
                    "error_code": None,
                    "duration_ms": 123,
                }
            ],
        )

        row = stored_steps(db, run)[0]
        assert row.iteration == 2
        assert row.node == "observe"
        assert row.tool_name == "search_knowledge"
        assert row.tool_call_id == "call-1"
        assert row.arguments_summary == {"query_length": 12}
        assert row.result_summary == {"source_count": 1}
        assert row.duration_ms == 123


def test_missing_optional_fields_fall_back_to_safe_defaults():
    Session = make_session()

    with Session() as db:
        run = make_run(db)
        append_steps(db, run, [{"tool_name": "analyze_log"}])

        row = stored_steps(db, run)[0]
        assert row.node == "unknown"
        assert row.action == "unknown"
        assert row.status == "unknown"
        assert row.iteration == 0
        assert row.error_code is None
        assert row.duration_ms is None
