"""Run-history routes with owner isolation."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from ..db.session import get_db
from ..dependencies import get_current_user
from ..schemas.auth import UserPublic
from ..schemas.incident import RunResponse
from ..services.storage import get_run_for_owner, list_runs_for_owner

router = APIRouter(prefix="/api/v1/runs", tags=["runs"])


def _to_response(run) -> RunResponse:
    """Convert an ORM run and its steps into the public response shape."""

    return RunResponse(
        run_id=run.run_id,
        status=run.status,
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


@router.get("", response_model=list[RunResponse])
def list_runs(
    limit: int = Query(default=20, ge=1, le=100),
    current_user: UserPublic = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[RunResponse]:
    """Return recent runs owned by the authenticated DevAtlas user."""

    return [
        _to_response(run)
        for run in list_runs_for_owner(
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

