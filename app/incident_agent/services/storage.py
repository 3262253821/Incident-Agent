"""Persistence helpers for Agent runs and execution steps."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session, selectinload

from ..core.statuses import RunStatus
from ..models import AgentRun, AgentStep
from ..models.agent_run import utc_now

# 一条 running 记录超过这个时长仍停留在 running，就认为执行它的进程已经中断。
STALE_RUN_AFTER = timedelta(minutes=15)


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
        status=RunStatus.RUNNING,
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
    degraded_summary: dict[str, Any] | None = None,
) -> AgentRun:
    """Persist the final graph state."""

    run.status = status
    run.iteration = iteration
    run.observations = observations
    run.report = report
    run.error = error
    run.degraded_summary = degraded_summary
    run.completed_at = utc_now()
    db.commit()
    db.refresh(run)
    return run


def _supports_row_locks(db: Session) -> bool:
    """SQLite (used by the test suite) does not support ``SELECT ... FOR UPDATE``."""

    return db.get_bind().dialect.name != "sqlite"


def append_steps(
    db: Session,
    run: AgentRun,
    steps: list[dict[str, Any]],
) -> None:
    """Persist sanitized step records for one run, replacing any previous set.

    The old implementation derived the next ``step_index`` from ``count(*) + 1``
    and only ever appended. That collides with the unique constraint
    ``uq_agent_steps_run_index(run_id, step_index)`` as soon as a run is written
    twice (a retry, SSE partial writes, or two workers on the same run).

    This version is idempotent by construction:

    - every ``step_index`` is written for the same ``run_id`` in one transaction;
    - previously persisted steps for that run are removed first, so re-running
      the same state cannot duplicate rows;
    - the run row is locked on MySQL so two workers cannot interleave the
      delete-then-insert and collide on the unique index.
    """

    # 锁定该 run 行（MySQL），使同一 run 的并发追加串行化。
    lock_statement = select(AgentRun.id).where(AgentRun.id == run.id)
    if _supports_row_locks(db):
        lock_statement = lock_statement.with_for_update()
    db.execute(lock_statement).scalar()

    # 先让 run.steps 过期：如果调用方之前读过该关系，旧的 AgentStep 对象仍留在
    # session 的 identity map 里；删除后用 SQLite 会复用自增主键，flush 新对象时
    # 就会撞上这些残留身份，触发 "Identity map already had an identity" 警告。
    db.expire(run, ["steps"])

    db.execute(
        AgentStep.__table__.delete()
        .where(AgentStep.run_id == run.id)
        .execution_options(synchronize_session=False)
    )

    for index, step in enumerate(steps, start=1):
        db.add(
            AgentStep(
                run_id=run.id,
                step_index=index,
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
    # 让调用方读到本次写入的结果，而不是删除前的缓存对象。
    db.expire(run, ["steps"])


def get_run_for_owner(
    db: Session,
    *,
    run_id: str,
    owner_user_id: int,
) -> AgentRun | None:
    """Get one run only when it belongs to the authenticated user.

    ``selectinload`` fetches the steps in a second, batched statement instead of
    leaving the relationship lazy: the detail endpoint serialises the whole
    trajectory, so an explicit eager load keeps it at two queries in total
    regardless of how many steps the run has.
    """

    return db.scalar(
        select(AgentRun)
        .where(
            AgentRun.run_id == run_id,
            AgentRun.owner_user_id == owner_user_id,
        )
        .options(selectinload(AgentRun.steps))
    )


def _observations_count_expression(dialect_name: str):
    """Count stored observations in SQL, without loading the JSON payload.

    Both supported dialects can measure a JSON array in place: MySQL has
    ``JSON_LENGTH`` and SQLite ships JSON1 as ``json_array_length`` (available in
    the 3.45 runtime this project uses). Neither needs the blob itself, which is
    what keeps the list payload small.
    """

    if dialect_name == "sqlite":
        return func.json_array_length(AgentRun.observations)
    return func.json_length(AgentRun.observations)


def build_run_summary_statement(
    *,
    dialect_name: str,
    owner_user_id: int,
    limit: int,
):
    """Build the single summary query for one owner.

    Split out from ``list_run_summaries_for_owner`` so the dialect-dependent JSON
    count can be compiled and asserted without a live database connection.
    """

    step_counts = (
        select(
            AgentStep.run_id.label("run_id"),
            func.count(AgentStep.id).label("steps_count"),
        )
        .group_by(AgentStep.run_id)
        .subquery()
    )

    return (
        select(
            AgentRun.run_id,
            AgentRun.title,
            AgentRun.status,
            AgentRun.knowledge_base_id,
            AgentRun.iteration,
            AgentRun.max_iterations,
            AgentRun.error,
            AgentRun.started_at,
            AgentRun.completed_at,
            AgentRun.interrupted_at,
            func.coalesce(
                _observations_count_expression(dialect_name),
                0,
            ).label("observations_count"),
            func.coalesce(step_counts.c.steps_count, 0).label("steps_count"),
        )
        .outerjoin(step_counts, step_counts.c.run_id == AgentRun.id)
        .where(AgentRun.owner_user_id == owner_user_id)
        # ``id`` breaks ties: two runs created in the same microsecond must still
        # come back in a stable order, otherwise paging later would repeat rows.
        .order_by(AgentRun.started_at.desc(), AgentRun.id.desc())
        .limit(limit)
    )


def list_run_summaries_for_owner(
    db: Session,
    *,
    owner_user_id: int,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """List recent runs as flat summary rows, using one query for any N.

    Two measured costs are removed here:

    - the list used to return ``AgentRun`` entities and the caller then read
      ``run.steps`` per row, which lazy-loaded one extra statement per run (the
      N+1 the audit measured: 5 runs -> 5 statements);
    - the entities carried the full ``observations`` and ``report`` JSON blobs,
      so list size grew with the log volume even though the drawer only renders
      identity, outcome and counts.

    The step count is aggregated in a subquery and both counts stay in SQL, so no
    JSON column travels to the application for this endpoint.
    """

    statement = build_run_summary_statement(
        dialect_name=db.get_bind().dialect.name,
        owner_user_id=owner_user_id,
        limit=limit,
    )
    return [dict(row) for row in db.execute(statement).mappings()]


def reclaim_stale_runs(
    db: Session,
    *,
    stale_after: timedelta = STALE_RUN_AFTER,
    now: datetime | None = None,
) -> int:
    """Mark abandoned ``running`` rows as interrupted and return how many.

    ``create_run`` commits a ``running`` row before the graph starts. If the
    process is killed, OOM-killed or reloaded in between, that row stays
    ``running`` forever and the UI shows a run that will never finish.

    The status is intentionally **not** changed to a new value: ``interrupted_at``
    is set while ``status`` becomes ``degraded``, so the API keeps its existing
    status vocabulary and the frontend can still tell an interrupted run apart.

    Returns the number of rows changed, so the caller can log it.
    """

    current = now or datetime.now(UTC).replace(tzinfo=None)
    cutoff = current - stale_after

    # MySQL：行锁保证多个 worker 同时启动时只有一个实例回收同一批记录。
    # SQLite（测试环境）不支持 FOR UPDATE，且测试是单连接的，因此跳过加锁。
    statement = (
        select(AgentRun.id)
        .where(
            AgentRun.status == RunStatus.RUNNING,
            AgentRun.started_at < cutoff,
        )
        .order_by(AgentRun.started_at)
        # 不在 SQL 里设置 limit：MySQL 会拒绝 `FOR UPDATE` 与 `LIMIT` 的组合。
    )
    if db.get_bind().dialect.name != "sqlite":
        statement = statement.with_for_update()

    stale_ids = list(db.scalars(statement))

    if not stale_ids:
        return 0

    db.execute(
        update(AgentRun)
        .where(AgentRun.id.in_(stale_ids))
        .values(
            status=RunStatus.DEGRADED,
            interrupted_at=current,
            completed_at=current,
            error="运行进程已中断，未生成结果（启动时自动回收）",
        )
    )
    db.commit()
    return len(stale_ids)
