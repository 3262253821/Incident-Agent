"""Run-history routes with owner isolation, filters and cursor pagination."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from ..core.pagination import decode_cursor
from ..core.statuses import RunStatus
from ..db.session import get_db
from ..dependencies import get_current_user
from ..schemas.auth import UserPublic
from ..schemas.incident import (
    RunResponse,
    RunSummary,
    RunSummaryPage,
    summarize_error,
)
from ..services.storage import (
    RunHistoryFilter,
    get_run_for_owner,
    list_run_summaries_for_owner,
)

router = APIRouter(prefix="/api/v1/runs", tags=["runs"])

# 客户端只能按 API 会返回的状态过滤；拼错的状态应当 422，而不是静默返回空列表。
KNOWN_STATUSES = frozenset(RunStatus.exposed())


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


def _to_naive_utc(value: datetime | None) -> datetime | None:
    """Normalise a filter timestamp to the naive-UTC form used by the columns.

    The API accepts any ISO 8601 input: an aware value is converted, a naive value
    is **read as UTC** (documented in the README) because that is exactly how the
    timestamps are stored and returned.
    """

    if value is None:
        return None
    if value.tzinfo is None:
        return value
    return value.astimezone(UTC).replace(tzinfo=None)


def _normalise_statuses(values: list[str] | None) -> tuple[str, ...]:
    """Validate and de-duplicate the ``?status=`` filter, preserving order."""

    if not values:
        return ()

    cleaned: list[str] = []
    for raw in values:
        candidate = (raw or "").strip()
        if candidate not in KNOWN_STATUSES:
            raise HTTPException(
                # 直接用数字：starlette 的 HTTP_422_UNPROCESSABLE_ENTITY 已弃用，
                # 而不同版本的替代常量名不一致。
                status_code=422,
                detail=(
                    f"不支持的状态过滤：{candidate or '(空)'}；"
                    f"可选值为 {', '.join(sorted(KNOWN_STATUSES))}"
                ),
            )
        if candidate not in cleaned:
            cleaned.append(candidate)
    return tuple(cleaned)


def _parse_cursor(raw: str | None) -> tuple[datetime, int] | None:
    """Turn the opaque page token into a keyset position, or 400."""

    if not raw:
        return None
    try:
        return decode_cursor(raw)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="分页游标无效，请重新加载历史列表",
        ) from exc


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


@router.get("", response_model=RunSummaryPage)
def list_runs(
    limit: int = Query(default=20, ge=1, le=100),
    status_filter: list[str] | None = Query(default=None, alias="status"),
    started_after: datetime | None = Query(default=None),
    started_before: datetime | None = Query(default=None),
    cursor: str | None = Query(default=None),
    current_user: UserPublic = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> RunSummaryPage:
    """Return one page of runs owned by the authenticated DevAtlas user.

    Summaries only: full observations/steps/report stay behind the detail route,
    so the payload no longer grows with the size of every stored log.

    Filters: ``status`` (repeatable), ``started_after`` (inclusive),
    ``started_before`` (exclusive) and the opaque ``cursor`` from the previous
    page. Ordering is always newest first, and the owner filter is applied by the
    storage layer for every branch, so no filter combination can widen the scope.
    """

    statuses = _normalise_statuses(status_filter)
    after = _to_naive_utc(started_after)
    before = _to_naive_utc(started_before)
    if after is not None and before is not None and after > before:
        raise HTTPException(
            status_code=422,
            detail="started_after 不能晚于 started_before",
        )

    filters = RunHistoryFilter(
        owner_user_id=current_user.id,
        limit=limit,
        statuses=statuses,
        started_after=after,
        started_before=before,
        cursor=_parse_cursor(cursor),
    )
    rows, next_cursor = list_run_summaries_for_owner(db, filters=filters)

    return RunSummaryPage(
        items=[_to_summary(row) for row in rows],
        next_cursor=next_cursor,
    )


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

