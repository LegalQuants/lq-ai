"""Private governance records for ADR 0035; no graph continuation cursor.

Migrations 0067 and 0068 are authoritative. Content-bearing snapshots/results stay here,
not in audit details or framework trace payloads. No public route exposes these
tables yet. The store owns short transactions; the eventual adapter owns I/O.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, Numeric, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class OrchestrationRoot(Base):
    __tablename__ = "orchestration_roots"

    session_id: Mapped[UUID] = mapped_column(
        ForeignKey("autonomous_sessions.id", ondelete="CASCADE"), primary_key=True
    )
    owner_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    project_id: Mapped[UUID] = mapped_column(ForeignKey("projects.id", ondelete="RESTRICT"))
    plan_id: Mapped[UUID] = mapped_column(unique=True)
    current_revision: Mapped[int] = mapped_column(Integer)
    admitted_revision: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(Text)
    stop_reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )


class OrchestrationPlan(Base):
    __tablename__ = "orchestration_plans"

    root_id: Mapped[UUID] = mapped_column(
        ForeignKey("orchestration_roots.session_id", ondelete="CASCADE"), primary_key=True
    )
    revision: Mapped[int] = mapped_column(Integer, primary_key=True)
    plan_hash: Mapped[str] = mapped_column(Text)
    snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(Text)
    approval: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )


class OrchestrationAdmission(Base):
    __tablename__ = "orchestration_admissions"

    session_id: Mapped[UUID] = mapped_column(
        ForeignKey("autonomous_sessions.id", ondelete="CASCADE"), primary_key=True
    )
    root_id: Mapped[UUID] = mapped_column(
        ForeignKey("orchestration_roots.session_id", ondelete="CASCADE")
    )
    revision: Mapped[int] = mapped_column(Integer)
    dispatch_id: Mapped[UUID]
    child_order: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )


class OrchestrationAccount(Base):
    """Budget allocation and worker fence for a root or admitted child."""

    __tablename__ = "orchestration_accounts"

    session_id: Mapped[UUID] = mapped_column(
        ForeignKey("autonomous_sessions.id", ondelete="CASCADE"), primary_key=True
    )
    root_id: Mapped[UUID] = mapped_column(
        ForeignKey("orchestration_roots.session_id", ondelete="CASCADE")
    )
    allocation_usd: Mapped[Decimal] = mapped_column(Numeric(10, 4))
    spent_usd: Mapped[Decimal] = mapped_column(Numeric(14, 4), server_default=text("0"))
    reserved_usd: Mapped[Decimal] = mapped_column(Numeric(14, 4), server_default=text("0"))
    generation: Mapped[int] = mapped_column(BigInteger, server_default=text("0"))
    worker_id: Mapped[UUID | None]
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    attempt_deadline: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class OrchestrationEffect(Base):
    """Unique effect identity with conservative in-flight/uncertain reservation."""

    __tablename__ = "orchestration_effects"

    session_id: Mapped[UUID] = mapped_column(
        ForeignKey("orchestration_accounts.session_id", ondelete="CASCADE"), primary_key=True
    )
    effect_key: Mapped[str] = mapped_column(Text, primary_key=True)
    request_hash: Mapped[str] = mapped_column(Text)
    phase: Mapped[str] = mapped_column(Text)
    intent: Mapped[str] = mapped_column(Text)
    generation: Mapped[int] = mapped_column(BigInteger)
    status: Mapped[str] = mapped_column(Text)
    reserved_usd: Mapped[Decimal] = mapped_column(Numeric(10, 4))
    charged_usd: Mapped[Decimal | None] = mapped_column(Numeric(14, 4))
    result: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
