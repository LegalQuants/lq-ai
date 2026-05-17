"""Chat + Message ORM models — per docs/db-schema.md and migration 0006.

A Chat is an owner-scoped conversation with optional Project scoping.
Messages are the per-turn rows: a single ``POST /api/v1/chats/{id}/messages``
exchange writes a ``user`` row and one ``assistant`` row.

Lifecycle (M1):

* Created on `POST /api/v1/chats` (Task C3).
* Updated on `PATCH /api/v1/chats/{id}` (title, archived flag).
* Soft-deleted on `DELETE /api/v1/chats/{id}` — flips ``archived_at``;
  hard-delete is D6 territory (per-user export+delete).
* Renamed automatically from ``"New chat"`` to the first 80 chars of
  the first user message; never overwrites a user-set title.

Per ADR 0007 we persist ``messages.applied_skills`` as a denormalized
``text[]`` rather than a join table — skills are filesystem-canonical,
audit reads are write-light, and the array column is cheaper than a
join for the read patterns we see (single-message detail; full chat
history scan).

Cost is persisted as ``cost_estimate_micros`` (integer USD micros) so
the audit-log value cannot drift due to float-precision rounding when
the row round-trips through different toolchains. The gateway emits
USD as a float; the chats handler does ``round(usd * 1_000_000)`` on
persist. ``docs/db-schema.md`` documents the unit.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    SmallInteger,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Chat(Base):
    """An owner-scoped chat per PRD §3.13.

    ``project_id`` is nullable — chats can be standalone or scoped to a
    project. ``title`` is NOT NULL with a DB default of ``"New chat"``;
    the API layer auto-renames the chat from the first user message's
    first 80 chars on the first ``POST /messages`` call. Subsequent
    messages do NOT rename (so a user-set title is never clobbered).

    ``archived_at`` is the soft-delete column — set on ``DELETE``,
    NULL means active.
    """

    __tablename__ = "chats"
    __table_args__ = (
        CheckConstraint(
            "char_length(title) > 0 AND char_length(title) <= 200",
            name="chk_chats_title_len",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    owner_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT", name="fk_chats_owner_id"),
        nullable=False,
    )
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="SET NULL", name="fk_chats_project_id"),
        nullable=True,
    )
    title: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        server_default=text("'New chat'"),
    )
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
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

    def __repr__(self) -> str:
        return (
            f"<Chat id={self.id} owner_id={self.owner_id} "
            f"title={self.title!r} archived={self.archived_at is not None}>"
        )


class Message(Base):
    """A single message inside a chat.

    ``role`` is CHECK-constrained at the DB to ``{user, assistant,
    system, tool}``. ``applied_skills`` is a ``text[]`` per ADR 0007 —
    skills are filesystem-canonical (no SQL ``skills`` table), and
    denormalizing the audit trail into the message row keeps reads
    join-free.

    Routing metadata is set on assistant messages from the gateway's
    response (B4 / C2). User / system / tool messages leave them NULL.

    ``cost_estimate_micros`` stores the per-message cost as an integer
    USD micros (1 micro = $1e-6). The gateway emits USD as a float;
    the API layer does ``round(usd * 1_000_000)`` before persist. See
    ``docs/db-schema.md`` for the unit.

    ``error_code`` is populated when the assistant message failed mid
    stream or the gateway raised a typed error during the exchange. It
    carries the canonical ``app.errors`` code.

    ``citations`` is a ``jsonb`` column initialized to ``'[]'``; M2's
    citation engine populates the structured shape.
    """

    __tablename__ = "messages"
    __table_args__ = (
        CheckConstraint(
            "role IN ('user', 'assistant', 'system', 'tool')",
            name="chk_messages_role",
        ),
        CheckConstraint(
            "kind IN ('user', 'ai', 'refusal', 'system')",
            name="chk_messages_kind",
        ),
        CheckConstraint(
            "routed_inference_tier IS NULL OR (routed_inference_tier BETWEEN 1 AND 5)",
            name="chk_messages_tier_range",
        ),
        CheckConstraint(
            "prompt_tokens IS NULL OR prompt_tokens >= 0",
            name="chk_messages_prompt_tokens_nonneg",
        ),
        CheckConstraint(
            "completion_tokens IS NULL OR completion_tokens >= 0",
            name="chk_messages_completion_tokens_nonneg",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    chat_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("chats.id", ondelete="CASCADE", name="fk_messages_chat_id"),
        nullable=False,
    )
    role: Mapped[str] = mapped_column(Text, nullable=False)
    kind: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        server_default=text("'user'"),
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    applied_skills: Mapped[list[str]] = mapped_column(
        ARRAY(Text),
        nullable=False,
        server_default=text("'{}'::text[]"),
    )
    routed_inference_tier: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    routed_provider: Mapped[str | None] = mapped_column(Text, nullable=True)
    routed_model: Mapped[str | None] = mapped_column(Text, nullable=True)
    requested_model: Mapped[str | None] = mapped_column(Text, nullable=True)
    """The ``model`` value the client originally sent (alias or
    ``provider/model``). ADR 0011 follow-on: ``routed_*`` records what
    actually ran; this records what the user asked for. Differ when an
    alias was used."""
    prompt_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    completion_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cost_estimate_micros: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    error_code: Mapped[str | None] = mapped_column(Text, nullable=True)
    citations: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'[]'::jsonb"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )

    def __repr__(self) -> str:
        return (
            f"<Message id={self.id} chat_id={self.chat_id} "
            f"role={self.role!r} tier={self.routed_inference_tier} "
            f"error={self.error_code!r}>"
        )


class MessageCitation(Base):
    """One model-emitted citation, verified against its source document.

    The M2 Citation Engine extracts citations from assistant responses
    (M2-A2 ships Stage 1: exact-match against retrieved-chunk content)
    and writes one row here per emitted citation. ``source_offset_start``
    and ``source_offset_end`` are byte-precise into
    ``documents.normalized_content`` — the same span the verifier
    re-reads when checking that the model quoted the source verbatim.

    ``verification_method`` enumerates which verification stage passed:

    * ``'exact_match'`` — Stage 1, byte-for-byte (M2-A2; lands here).
    * ``'tolerant_match'`` — Stage 2, normalized-whitespace + OCR
      artefacts (M2-B1).
    * ``'paraphrase_judge'`` — Stage 3, paraphrase judge (M2-C1).
    * ``'llm_judge'`` — reserved for future LLM-based verification
      stages (semantic match, claim decomposition); ``'paraphrase_judge'``
      is the tighter label for the M2-C1 paraphrase-only path.
    * ``'ensemble_strict'`` — Stage 4 with strict aggregation: every
      configured judge model verdict'd ``"yes"`` (M2-D1).
    * ``'ensemble_majority'`` — Stage 4 with majority aggregation:
      the verdict that won the majority is the persisted outcome
      (M2-D1). Disagreement persists with ``partial=true`` so the UI
      can flag it (per M2-D1 §UI rendering).
    * ``'failed'`` — every stage rejected; rendered as unverified in
      the UI (M2-C2).

    ``verification_confidence`` is the stage's reported confidence in
    ``[0, 1]``; exact-match writes ``1.0``, tolerant-match writes a
    similarity-based score, the paraphrase judge writes its own
    high/medium/low → 0.90/0.70/0.50 mapping.

    ``partial`` (M2-C1) distinguishes "judge says the source supports
    the claim" from "judge says the source supports it *partially*".
    Both persist with ``verified=true``; the partial flag drives the
    M2-C2 UI's visually-distinct "verified with caveats" rendering.

    ``tier_envelope`` (M2-D1) records the privacy envelope of the
    ensemble that verified this citation — the maximum (weakest)
    inference tier across the judge models that ran. NULL for non-
    ensemble methods (Stages 1-3 are single-tier by construction);
    1-5 for ensemble rows per PRD §1.5.2. Audit-only column: no
    behavior gates on it, but operators can query to surface chats
    whose verification reached weaker tiers than their primary
    inference.
    """

    __tablename__ = "message_citations"
    __table_args__ = (
        CheckConstraint(
            "source_offset_start >= 0",
            name="chk_message_citations_offset_start_nonneg",
        ),
        CheckConstraint(
            "source_offset_end > source_offset_start",
            name="chk_message_citations_offset_end_gt_start",
        ),
        CheckConstraint(
            "verification_method IS NULL OR verification_method IN "
            "('exact_match', 'tolerant_match', 'llm_judge', "
            "'paraphrase_judge', 'ensemble_strict', 'ensemble_majority', "
            "'failed')",
            name="chk_message_citations_method_values",
        ),
        CheckConstraint(
            "verification_confidence IS NULL OR "
            "(verification_confidence >= 0 AND verification_confidence <= 1)",
            name="chk_message_citations_confidence_range",
        ),
        CheckConstraint(
            "(verified = false) OR (verification_method IS NOT NULL)",
            name="chk_message_citations_verified_has_method",
        ),
        CheckConstraint(
            "tier_envelope IS NULL OR (tier_envelope BETWEEN 1 AND 5)",
            name="chk_message_citations_tier_envelope_range",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    message_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "messages.id",
            ondelete="CASCADE",
            name="fk_message_citations_message_id",
        ),
        nullable=False,
    )
    source_file_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "files.id",
            ondelete="CASCADE",
            name="fk_message_citations_source_file_id",
        ),
        nullable=False,
    )
    source_offset_start: Mapped[int] = mapped_column(Integer, nullable=False)
    source_offset_end: Mapped[int] = mapped_column(Integer, nullable=False)
    source_page: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source_text: Mapped[str] = mapped_column(Text, nullable=False)
    verified: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=text("false"),
    )
    verification_method: Mapped[str | None] = mapped_column(Text, nullable=True)
    verification_confidence: Mapped[Decimal | None] = mapped_column(
        Numeric(3, 2),
        nullable=True,
    )
    partial: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=text("false"),
    )
    tier_envelope: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )

    def __repr__(self) -> str:
        return (
            f"<MessageCitation id={self.id} message_id={self.message_id} "
            f"source_file={self.source_file_id} "
            f"offsets=[{self.source_offset_start},{self.source_offset_end}) "
            f"verified={self.verified} method={self.verification_method!r}>"
        )
