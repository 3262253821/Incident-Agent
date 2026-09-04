"""Persistence helpers for Agent runs and execution steps."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import AgentRun, AgentStep


def create_run(
    db: Session,
    *,
    run_id: str,
    owner_user_id: int,
    title: str,
    input_content: str,
    knowledge_base_id: int,
    model_name: str,
    max_iterations: int,
) -> AgentRun:
    """Create a running record before invoking the graph."""

    run = AgentRun(
        run_id=run_id,
        owner_user_id=owner_user_id,
        title=title.strip(),
        input_content=input_content.strip(),
        knowledge_base_id=knowledge_base_id,
        status="running",
        model_name=model_name,
        iteration=0,
        max_iterations=max_iterations,
        observations=[],
        report=None,
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    return run


def finish_run(
    db: Session,
    run: AgentRun,
    *,
    status: str,
    iteration: int,
    observations: list[dict[str, Any]],
    report: dict[str, Any] | None,
    error: str | None,
) -> AgentRun:
    """Persist the final graph state."""

    run.status = status
    run.iteration = iteration
    run.observations = observations
    run.report = report
    run.error = error
    run.completed_at = datetime.utcnow()
    db.commit()
    db.refresh(run)
    return run


def append_steps(
    db: Session,
    run: AgentRun,
    steps: list[dict[str, Any]],
) -> None:
    """Persist sanitized step records for one run."""

    existing_count = db.scalar(
        select(func.count())
        .select_from(AgentStep)
        .where(AgentStep.run_id == run.id)
    ) or 0
    next_index = existing_count + 1

    for offset, step in enumerate(steps):
        db.add(
            AgentStep(
                run_id=run.id,
                step_index=next_index + offset,
                iteration=int(step.get("iteration", 0)),
                node=str(step.get("node", "unknown")),
                action=str(step.get("action", "unknown")),
                tool_name=step.get("tool_name"),
                tool_call_id=step.get("tool_call_id"),
                arguments_summary=step.get("arguments_summary"),
                result_summary=step.get("result_summary"),
                status=str(step.get("status", "unknown")),
                error_code=step.get("error_code"),
                duration_ms=step.get("duration_ms"),
            )
        )

    db.commit()


def get_run_for_owner(
    db: Session,
    *,
    run_id: str,
    owner_user_id: int,
) -> AgentRun | None:
    """Get one run only when it belongs to the authenticated user."""

    return db.scalar(
        select(AgentRun).where(
            AgentRun.run_id == run_id,
            AgentRun.owner_user_id == owner_user_id,
        )
    )


def list_runs_for_owner(
    db: Session,
    *,
    owner_user_id: int,
    limit: int = 20,
) -> list[AgentRun]:
    """List recent runs for one authenticated user."""

    return list(
        db.scalars(
            select(AgentRun)
            .where(AgentRun.owner_user_id == owner_user_id)
            .order_by(AgentRun.started_at.desc())
            .limit(limit)
        )
    )
