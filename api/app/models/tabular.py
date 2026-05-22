"""Tabular Review ORM models — M3-C2.

Substrate for the Tabular / Multi-Document Review surface
([PRD §3.14](docs/PRD.md#314-tabular--multi-document-review-m3))
landing in M3. Each row is one tabular execution — a row-per-document
by column-per-spec grid run as a LangGraph workflow on the
``arq:m3a6`` queue (Decision C-3 from the Phase C prep doc).

One table (migration ``0036_tabular_executions.py``):

* :class:`TabularExecution` — one row per execution. Status lifecycle
  is ``pending -> running -> completed | failed | cancelled``.
  ``parent_execution_id`` is non-NULL on bulk-op sibling rows
  (Decision C-9; bulk ops spawn siblings rather than mutating the
  original grid).

The CHECK constraint on ``status`` is enforced at the storage layer
(migration 0036) so application bugs can't insert invalid enum values.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Numeric, Text, text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class TabularExecution(Base):
    """One Tabular Review execution — M3-C2.

    Lifecycle (CHECK-constrained per migration 0036):

    * ``pending`` — row written by the POST handler; the ARQ worker
      hasn't picked it up yet.
    * ``running`` — worker is walking the documents x columns grid
      (per-cell Citation-Engine-grounded extraction).
    * ``completed`` — ``results`` JSONB is populated with the
      assembled grid; ``completed_at`` is set.
    * ``failed`` — worker raised mid-flight; ``error_text`` populated;
      ``results`` may be NULL or carry partial output;
      ``completed_at`` is set.
    * ``cancelled`` — operator cancelled via
      ``POST /tabular/executions/{id}/cancel`` before the worker
      finished; ``completed_at`` is set.

    ``document_ids`` is the snapshot of source documents at request
    time; not an FK so a later soft-delete of one of the source files
    doesn't cascade-clear the audit row.

    ``columns`` is the snapshot of the resolved column spec at
    execution start (either the skill's ``lq_ai.columns`` block at
    that moment, or the operator's ad-hoc list). Snapshotting is the
    load-bearing invariant: re-rendering the grid a week later must
    be honest about what was actually run, not what the skill
    currently says.

    ``parent_execution_id`` is non-NULL on bulk-op sibling rows
    (Decision C-9). A "Redline column N" bulk op creates a child row
    pointing at the original execution; the result view renders the
    bulk-op output as a tab next to the original grid.

    Soft delete via ``deleted_at`` matches the
    ``Playbook.deleted_at`` pattern from M3-A6's migration 0034.
    """

    __tablename__ = "tabular_executions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "users.id",
            ondelete="SET NULL",
            name="fk_tabular_executions_user_id",
        ),
        nullable=True,
    )
    parent_execution_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "tabular_executions.id",
            ondelete="SET NULL",
            name="fk_tabular_executions_parent_execution_id",
        ),
        nullable=True,
    )
    skill_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        server_default=text("'pending'"),
    )
    document_ids: Mapped[list[uuid.UUID]] = mapped_column(
        ARRAY(UUID(as_uuid=True)),
        nullable=False,
        server_default=text("'{}'::uuid[]"),
    )
    columns: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'[]'::jsonb"),
    )
    results: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    cost_estimate_usd: Mapped[Decimal | None] = mapped_column(
        Numeric(10, 4),
        nullable=True,
    )
    cost_actual_usd: Mapped[Decimal | None] = mapped_column(
        Numeric(10, 4),
        nullable=True,
    )
    error_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    def __repr__(self) -> str:
        return (
            f"<TabularExecution id={self.id} user_id={self.user_id} "
            f"status={self.status!r} docs={len(self.document_ids)} "
            f"cols={len(self.columns)}>"
        )
