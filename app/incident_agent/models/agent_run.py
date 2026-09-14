"""ORM models for Agent execution records."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..db.session import Base


def utc_now() -> datetime:
    """Current UTC time as a naive datetime.

    ``datetime.utcnow()`` is deprecated in Python 3.12+; this is the replacement
    that keeps the same stored representation.

    Why the columns stay timezone-naive instead of ``DateTime(timezone=True)``:

    - MySQL's ``DATETIME`` does not store an offset, so a timezone-aware column
      still comes back naive on a real deployment (measured, not assumed);
    - SQLite (the test database) deserialises back as naive as well, even when
      the column is declared with ``timezone=True``;
    - ``timezone=True`` would only make SQLAlchemy emit offset-bearing literals
      that MySQL then silently truncates.

    So switching the column type would require a migration while changing
    nothing about what is stored, and would make SQLAlchemy's own type contract
    mismatch the database. Timestamps are therefore always written as **naive
    UTC**, and every value that reaches the API is serialised as ISO 8601 with an
    explicit ``+00:00`` / ``Z`` suffix at the schema boundary.
    """

    return datetime.now(UTC).replace(tzinfo=None)


class AgentRun(Base):
    """One complete or incomplete Incident Agent execution."""

    __tablename__ = "agent_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[str] = mapped_column(String(36), unique=True)
    owner_user_id: Mapped[int] = mapped_column(Integer, index=True)
    title: Mapped[str] = mapped_column(String(200))
    input_content: Mapped[str] = mapped_column(Text)
    knowledge_base_id: Mapped[int] = mapped_column(Integer, index=True)
    status: Mapped[str] = mapped_column(String(32), index=True)
    model_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    iteration: Mapped[int] = mapped_column(Integer, default=0)
    max_iterations: Mapped[int] = mapped_column(Integer)
    observations: Mapped[list[dict[str, Any]]] = mapped_column(JSON)
    report: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Deterministic, model-free summary of what a failed run established. Kept in
    # the row so the history view shows the same thing the live response did.
    degraded_summary: Mapped[dict[str, Any] | None] = mapped_column(
        JSON,
        nullable=True,
    )
    started_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=utc_now,
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime,
        nullable=True,
    )
    # Set when the process died mid-run and a later startup reclaimed the row.
    # ``status`` deliberately stays ``completed | degraded | ...`` so the API
    # response shape does not grow a new enum value.
    interrupted_at: Mapped[datetime | None] = mapped_column(
        DateTime,
        nullable=True,
    )

    steps: Mapped[list["AgentStep"]] = relationship(
        back_populates="run",
        cascade="all, delete-orphan",
        order_by="AgentStep.step_index",
    )

    __table_args__ = (
        Index("ix_agent_runs_run_id", "run_id"),
        Index("ix_agent_runs_owner_created", "owner_user_id", "started_at"),
    )


class AgentStep(Base):
    """One node or tool action belonging to an Agent run."""

    __tablename__ = "agent_steps"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[int] = mapped_column(
        ForeignKey("agent_runs.id", ondelete="CASCADE"),
        index=True,
    )
    step_index: Mapped[int] = mapped_column(Integer)
    iteration: Mapped[int] = mapped_column(Integer)
    node: Mapped[str] = mapped_column(String(64))
    action: Mapped[str] = mapped_column(String(64))
    tool_name: Mapped[str | None] = mapped_column(String(64), nullable=True)
    tool_call_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    arguments_summary: Mapped[dict[str, Any] | None] = mapped_column(
        JSON,
        nullable=True,
    )
    result_summary: Mapped[dict[str, Any] | None] = mapped_column(
        JSON,
        nullable=True,
    )
    status: Mapped[str] = mapped_column(String(32))
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=utc_now,
    )

    run: Mapped[AgentRun] = relationship(back_populates="steps")

    __table_args__ = (
        Index("uq_agent_steps_run_index", "run_id", "step_index", unique=True),
    )
