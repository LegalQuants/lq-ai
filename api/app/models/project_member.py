"""ProjectMember ORM model — matter-scoped collaboration.

Backs the ``project_members`` table per migration 0067. A matter is a
``projects`` row (ADR 0020 D3 — there is no separate ``Matter`` model),
so membership of a matter is membership of a project.

The shape mirrors ``team_members`` (:mod:`app.models.team`) deliberately:
composite primary key, CASCADE on both ends so membership never outlives
its referents, and an ``added_by_user_id`` column with RESTRICT so
"who let X onto matter Y?" survives in audit-log forensics until the
membership row itself is gone.

One value has no analogue in the team model: ``blocked``. It is a
**negative** grant — an ethical screen or conflict wall — and
:func:`app.authz.matters.matter_access` evaluates it before every allow,
including operator-admin. A wall an admin can walk through is not a wall,
and in a small firm the operator-admin is usually also a practising
lawyer.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, PrimaryKeyConstraint, Text, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

MemberRole = Literal["lead", "contributor", "reader", "blocked"]

#: Roles that confer some level of access, most-privileged first. ``blocked``
#: is deliberately absent — it is a denial, not a grant.
GRANTING_ROLES: frozenset[str] = frozenset({"lead", "contributor", "reader"})

#: The full closed set, including the negative grant. Mirrors the DB CHECK.
MEMBER_ROLES: frozenset[str] = GRANTING_ROLES | {"blocked"}


class ProjectMember(Base):
    """Membership of one user in one matter, with role.

    Composite primary key on ``(project_id, user_id)`` — a user holds at
    most one role on a matter, so a grant and a screen can never coexist
    and "is this person screened off?" has exactly one answer.
    """

    __tablename__ = "project_members"
    __table_args__ = (
        PrimaryKeyConstraint("project_id", "user_id", name="pk_project_members"),
        CheckConstraint(
            "role IN ('lead', 'contributor', 'reader', 'blocked')",
            name="ck_project_members_role_enum",
        ),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE", name="fk_project_members_project"),
        nullable=False,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE", name="fk_project_members_user"),
        nullable=False,
    )
    role: Mapped[str] = mapped_column(Text, nullable=False)
    """One of ``'lead'`` (manage members, share scope, and matter settings),
    ``'contributor'`` (read + write the matter and its attachments),
    ``'reader'`` (read only), or ``'blocked'`` (an ethical screen — denies
    access that any other rule would otherwise grant)."""

    added_by_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT", name="fk_project_members_added_by"),
        nullable=False,
    )
    """The user who created this membership row. RESTRICT so the trail
    survives user deletion until the membership row itself is gone."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )

    def __repr__(self) -> str:
        return (
            f"<ProjectMember project_id={self.project_id} "
            f"user_id={self.user_id} role={self.role!r}>"
        )
