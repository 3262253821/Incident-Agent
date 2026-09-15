"""Run-history routes with owner isolation."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from ..db.session import get_db
from ..dependencies import get_current_user
from ..schemas.auth import UserPublic
from ..schemas.incident import RunResponse, RunSummary, summarize_error
from ..services.storage import get_run_for_owner, list_run_summaries_for_owner

router = APIRouter(prefix="/api/v1/runs", tags=["runs"])


def _to_summary(row: dict[str, Any]) -> RunSummary:
    """Convert one flat summary row into the public list contract."""

    return RunSummary(
        run_id=row["run_id"],
        title=row["title"],
        status=row["status"],
        knowledge_base_id=row["knowledge_base_id"],
        iteration=row["iteration"],
        max_iterations=row["max_iterations"],
        steps_count=row["steps_count"],
        observations_count=row["observations_count"],
        interrupted=row["interrupted_at"] is not None,
        error=summarize_error(row["error"]),
        started_at=row["started_at"],
        completed_at=row["completed_at"],
    )


def _to_response(run) -> RunResponse:
    """Convert an ORM run and its steps into the public response shape."""

    return RunResponse(
        run_id=run.run_id,
        title=run.title,
        status=run.status,
        started_at=run.started_at,
        completed_at=run.completed_at,
        report=run.report,
        observations=run.observations or [],
        steps=[
            {
                "step_index": step.step_index,
                "iteration": step.iteration,
                "node": step.node,
                "action": step.action,
                "tool_name": step.tool_name,
                "tool_call_id": step.tool_call_id,
                "arguments_summary": step.arguments_summary,
                "result_summary": step.result_summary,
                "status": step.status,
                "error_code": step.error_code,
                "duration_ms": step.duration_ms,
            }
            for step in run.steps
        ],
        error=run.error,
        interrupted=run.interrupted_at is not None,
        degraded_summary=run.degraded_summary,
    )


@router.get("", response_model=list[RunSummary])
def list_runs(
    limit: int = Query(default=20, ge=1, le=100),
    current_user: UserPublic = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[RunSummary]:
    """Return recent runs owned by the authenticated DevAtlas user.

    Summaries only: full observations/steps/report stay behind the detail route,
    so the payload no longer grows with the size of every stored log.
    """

    return [
        _to_summary(row)
        for row in list_run_summaries_for_owner(
            db,
            owner_user_id=current_user.id,
            limit=limit,
        )
    ]


@router.get("/{run_id}", response_model=RunResponse)
def get_run(
    run_id: str,
    current_user: UserPublic = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> RunResponse:
    """Return a run or 404 without revealing whether another user's ID exists."""

    run = get_run_for_owner(
        db,
        run_id=run_id,
        owner_user_id=current_user.id,
    )
    if run is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="运行记录不存在",
        )
    return _to_response(run)

