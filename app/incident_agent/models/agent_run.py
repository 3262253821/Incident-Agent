"""ORM models for Agent execution records."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..db.session import Base


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
    started_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
    )
    completed_at: Mapped[datetime | None] = mapped_column(
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
        default=datetime.utcnow,
    )

    run: Mapped[AgentRun] = relationship(back_populates="steps")

    __table_args__ = (
        Index("uq_agent_steps_run_index", "run_id", "step_index", unique=True),
    )
