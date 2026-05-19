"""Playbook ORM models — M3-A1.

Substrate for the Playbook engine ([PRD §3.7](docs/PRD.md#37-playbooks))
landing in M3. A playbook codifies an organization's standard positions
and fallback positions on common contract issues. The LangGraph
executor (M3-A2) walks each position against a target contract and
produces a per-position assessment.

Three tables (migration ``0031_playbooks.py``):

* :class:`Playbook` — header row per playbook. Positions live in a
  child table; ``positions`` relationship loads them in
  ``position_order``.
* :class:`PlaybookPosition` — one row per issue. ``fallback_tiers``
  is JSONB carrying the ranked list of acceptable alternatives.
* :class:`PlaybookExecution` — one row per run of a playbook against
  a target document. ``status`` lifecycle is
  ``pending → running → completed | error``.

The CHECK constraints on ``severity_if_missing`` and ``status`` are
enforced at the storage layer (see migration 0031) so application
bugs can't insert invalid enum values.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Integer, Text, text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class Playbook(Base):
    """Header row per playbook — name, contract type, version, author.

    ``contract_type`` is a free-form string per PRD §3.7
    (``"NDA"``, ``"MSA-SaaS"``, ``"MSA-Commercial"``, ``"DPA"``, ...) so
    new contract types don't require a migration. ``version`` is a
    semver-like string the operator owns; built-in playbooks ship at
    ``'1.0.0'`` per the seed migrations in M3-A3 / M3-A5.

    ``created_by`` is nullable + ``ON DELETE SET NULL`` so a deleted
    operator's playbook stays available to the rest of the team
    (matches the project/skill ownership model — the playbook outlives
    the individual author).
    """

    __tablename__ = "playbooks"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    contract_type: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    version: Mapped[str] = mapped_column(Text, nullable=False, server_default="1.0.0")
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL", name="fk_playbooks_created_by"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )

    positions: Mapped[list[PlaybookPosition]] = relationship(
        "PlaybookPosition",
        back_populates="playbook",
        cascade="all, delete-orphan",
        order_by="PlaybookPosition.position_order",
    )

    def __repr__(self) -> str:
        return (
            f"<Playbook id={self.id} name={self.name!r} "
            f"contract_type={self.contract_type!r} version={self.version!r}>"
        )


class PlaybookPosition(Base):
    """One issue in a playbook — the org's standard + fallbacks for a clause.

    ``fallback_tiers`` is a JSONB array of ``FallbackTier`` shapes
    (rank / description / language) — the per-position list is small
    (typically 2-3 alternatives), fetched together with the position,
    and modelled as a single unit in the Pydantic wire shape.
    Normalizing to a third table would add a join on every read with
    no upside.

    ``detection_keywords`` and ``detection_examples`` feed the M3-A2
    executor's retrieval step — the executor uses both the keywords
    (for lexical match) and the examples (for embedding-based match)
    to locate the position's clause(s) in the target contract.
    """

    __tablename__ = "playbook_positions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    playbook_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("playbooks.id", ondelete="CASCADE", name="fk_playbook_positions_playbook_id"),
        nullable=False,
    )
    issue: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    standard_language: Mapped[str] = mapped_column(Text, nullable=False)
    fallback_tiers: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'[]'::jsonb"),
    )
    redline_strategy: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    severity_if_missing: Mapped[str] = mapped_column(Text, nullable=False)
    detection_keywords: Mapped[list[str]] = mapped_column(
        ARRAY(Text),
        nullable=False,
        server_default=text("'{}'::text[]"),
    )
    detection_examples: Mapped[list[str]] = mapped_column(
        ARRAY(Text),
        nullable=False,
        server_default=text("'{}'::text[]"),
    )
    position_order: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")

    playbook: Mapped[Playbook] = relationship("Playbook", back_populates="positions")

    def __repr__(self) -> str:
        return (
            f"<PlaybookPosition id={self.id} playbook_id={self.playbook_id} "
            f"issue={self.issue!r} severity={self.severity_if_missing!r} "
            f"order={self.position_order}>"
        )


class PlaybookExecution(Base):
    """One execution of a playbook against a target document.

    Status lifecycle (CHECK-constrained at the storage layer):

    * ``pending`` — execution row written, executor not yet picked it up.
    * ``running`` — executor walking positions.
    * ``completed`` — every position has a verdict in ``results``;
      ``completed_at`` set.
    * ``error`` — executor raised mid-flight; ``error`` text populated;
      ``results`` may carry partial output for whichever positions
      completed before the failure.

    ``results`` is JSONB shaped per the M3-A2 executor; this row
    pre-allocates the column so the executor implementation does not
    require another migration. ``user_id`` and ``project_id`` are both
    ``ON DELETE SET NULL`` — historical executions survive operator or
    project deletion so audit trails stay intact.
    """

    __tablename__ = "playbook_executions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    playbook_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "playbooks.id",
            ondelete="CASCADE",
            name="fk_playbook_executions_playbook_id",
        ),
        nullable=False,
    )
    target_document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "documents.id",
            ondelete="CASCADE",
            name="fk_playbook_executions_target_document_id",
        ),
        nullable=False,
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL", name="fk_playbook_executions_user_id"),
        nullable=True,
    )
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "projects.id",
            ondelete="SET NULL",
            name="fk_playbook_executions_project_id",
        ),
        nullable=True,
    )
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'pending'"))
    results: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    def __repr__(self) -> str:
        return (
            f"<PlaybookExecution id={self.id} playbook_id={self.playbook_id} "
            f"target_document_id={self.target_document_id} status={self.status!r}>"
        )
