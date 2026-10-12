"""UserSkill ORM model — Task D8.

Backs the ``user_skills`` table per migration 0013 (ADR 0012). DB-backed
user-scope skills shadow filesystem-canonical built-ins (ADR 0004) on
slug collision when resolved for the owning user's chats; other users
still see the built-in.

The model carries both ``owner_user_id`` and ``owner_team_id`` columns
even though D8 only exercises the user-scope branch. The team-scope
slot is reserved for D8.1; the schema-level CHECK + partial UNIQUE
indexes are in place so D8.1 only needs to add the FK pointing at
``teams.id`` and the corresponding API surface.

``archived_at`` is the soft-delete mechanism — listing/resolution paths
filter to non-archived rows; archived rows free the slug for a new
creation but stay queryable for the user_export GDPR Article 17/20
paths.

Versioning: free-form string the user types (matches the filesystem
``lq_ai.version`` convention). PATCH overwrites in place; the audit
log carries ``user_skill.updated`` rows with ``version_before`` /
``version_after`` in ``details`` so the *fact* of edits is forensically
traceable. Full edit history is out of scope for D8 (DE candidate).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Text, text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class UserSkill(Base):
    """A user-authored skill stored in the DB (D8) or team-authored (D8.1).

    See ``docs/adr/0012-db-backed-user-skills.md`` for the design
    decisions this model reifies — collision shadowing, single-row
    versioning, archived_at soft-delete, deferred team scope.
    """

    __tablename__ = "user_skills"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    scope: Mapped[str] = mapped_column(Text, nullable=False)
    """One of ``'user'`` (D8) or ``'team'`` (D8.1, columns ship now)."""

    owner_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE", name="fk_user_skills_user"),
        nullable=True,
    )
    """Set when ``scope='user'``; NULL otherwise (enforced by CHECK)."""

    owner_team_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        nullable=True,
    )
    """Set when ``scope='team'``; NULL otherwise (enforced by CHECK).

    No FK constraint yet — the ``teams`` target table lands in D8.1.
    Per ADR 0012 the column shape ships now so D8.1 is purely additive.
    """

    slug: Mapped[str] = mapped_column(Text, nullable=False)
    """Stable identifier; matches filesystem skill folder-name conventions.

    Uniqueness scope: per owner among non-archived rows. Built-in
    filesystem skills may share the same slug — that's the shadow case;
    the user's row wins for their chats.
    """

    display_name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    version: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        server_default=text("'1.0.0'"),
    )
    """Free-form, user-set. Matches filesystem ``lq_ai.version`` semantics."""

    tags: Mapped[list[str]] = mapped_column(
        ARRAY(Text),
        nullable=False,
        server_default=text("ARRAY[]::text[]"),
    )

    frontmatter_extra: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
    )
    """Everything else in the skill's ``lq_ai:`` namespace.

    Per ADR 0012: ``jurisdiction``, ``output_format``,
    ``min_inference_tier``, ``use_organization_profile`` and any other
    extension keys ride here so the synthesized Skill payload returned
    to the gateway carries the same shape a filesystem skill would.
    """

    body: Mapped[str] = mapped_column(Text, nullable=False)
    """The Markdown body — becomes the skill chunk during prompt assembly."""

    slash_alias: Mapped[str | None] = mapped_column(Text, nullable=True)
    """Optional ``/slash`` invocation alias. Format ``^/[a-z0-9-]{1,32}$``
    enforced at the DB layer via ``chk_user_skills_slash_alias_format`` and
    at the API layer via the Pydantic create/update schemas (Wave D.2).

    Uniqueness scope: per owner (user *or* team) among non-archived rows
    of the matching scope — mirrors the slug-uniqueness pattern.
    """

    forked_from: Mapped[str | None] = mapped_column(Text, nullable=True)
    """Documentary slug of the source skill if this skill was forked.

    No FK — built-in skills are filesystem-canonical (ADR 0004) so there
    is no target row in the DB to reference. Write-once at create time;
    PATCH must not change it. The audit-log carries the actual lineage.
    """

    installation_provenance: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    """Write-once source/content snapshot; never editable through skill PATCH."""

    archived_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    """Soft-delete timestamp. Listing and resolution paths exclude
    rows with ``archived_at IS NOT NULL``."""

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
        owner = self.owner_user_id if self.scope == "user" else self.owner_team_id
        return (
            f"<UserSkill id={self.id} scope={self.scope} owner={owner} "
            f"slug={self.slug!r} version={self.version!r}>"
        )
