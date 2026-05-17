"""Project ORM models — per docs/db-schema.md §`projects` and PRD §3.11.

A Project is a user-curated container that scopes a set of files,
skills, and a free-form context document around a single matter
(deal, counterparty, regulatory question, policy refresh). Chats
inside a Project (C3) inherit the Project's attached files and skills;
Projects in M1 are file/skill containers with a context document and
the privileged-tier constraint.

Lifecycle (M1):

* Created on `POST /api/v1/projects` (Task C7).
* Files attached/detached via `POST/DELETE /api/v1/projects/{id}/files`.
* Skills attached/detached via `POST/DELETE /api/v1/projects/{id}/skills`.
  Skills are referenced by name (text) — there is no `skills` SQL
  table per ADR 0004 (skills are filesystem-canonical).
* Soft-deleted via `DELETE /api/v1/projects/{id}` — flips
  `archived_at` from NULL to `now()`. Hard-delete is D6 territory
  (per-user export+delete).

`privileged` and `minimum_inference_tier` carry a CHECK constraint at
the DB level (`chk_projects_privileged_implies_tier`) enforcing that
`privileged=true` implies a non-NULL `minimum_inference_tier`. The API
also validates this; defense-in-depth.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    PrimaryKeyConstraint,
    SmallInteger,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Project(Base):
    """A matter-scoped container per PRD §3.11.

    `slug` is unique-per-owner within the active set (an archived
    project's slug can be reused). The DB enforces uniqueness via a
    partial UNIQUE index `idx_projects_slug_owner_active`.

    `context_md` is the free-form Markdown context document the user
    edits to capture matter knowledge ("we are the customer; counterparty
    is Acme; their counsel is Smith Crowell; we agreed to a 12-month
    liability cap last round").

    `archived_at` is the soft-delete column — set on `DELETE`, NULL
    means active.
    """

    __tablename__ = "projects"
    __table_args__ = (
        CheckConstraint(
            "minimum_inference_tier IS NULL OR (minimum_inference_tier BETWEEN 1 AND 5)",
            name="chk_projects_tier_range",
        ),
        CheckConstraint(
            "(privileged = false) OR (minimum_inference_tier IS NOT NULL)",
            name="chk_projects_privileged_implies_tier",
        ),
        CheckConstraint(
            "char_length(name) > 0 AND char_length(name) <= 200",
            name="chk_projects_name_len",
        ),
        CheckConstraint(
            "char_length(slug) > 0 AND char_length(slug) <= 80",
            name="chk_projects_slug_len",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    owner_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT", name="fk_projects_owner_id"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    slug: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    context_md: Mapped[str | None] = mapped_column(Text, nullable=True)
    privileged: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    minimum_inference_tier: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    is_sandbox: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=text("false"),
        default=False,
    )
    ensemble_verification: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=text("false"),
        default=False,
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
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    def __repr__(self) -> str:
        return (
            f"<Project id={self.id} owner_id={self.owner_id} "
            f"name={self.name!r} slug={self.slug!r} "
            f"privileged={self.privileged} archived={self.archived_at is not None}>"
        )


class ProjectFile(Base):
    """Many-to-many join: project ↔ file.

    Both ends `ON DELETE CASCADE` — dropping a project removes its
    attachments; dropping a file removes the join rows referencing it.
    The composite (project_id, file_id) is the primary key.
    """

    __tablename__ = "project_files"
    __table_args__ = (PrimaryKeyConstraint("project_id", "file_id", name="pk_project_files"),)

    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE", name="fk_project_files_project_id"),
        nullable=False,
    )
    file_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("files.id", ondelete="CASCADE", name="fk_project_files_file_id"),
        nullable=False,
    )
    attached_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )

    def __repr__(self) -> str:
        return f"<ProjectFile project_id={self.project_id} file_id={self.file_id}>"


class ProjectSkill(Base):
    """Many-to-many join: project ↔ skill name.

    `skill_name` is text, not a FK — skills are filesystem-canonical
    per ADR 0004 (no `skills` SQL table). The handler validates the
    name exists in the in-memory registry before insert.
    """

    __tablename__ = "project_skills"
    __table_args__ = (
        PrimaryKeyConstraint("project_id", "skill_name", name="pk_project_skills"),
        CheckConstraint(
            "char_length(skill_name) > 0 AND char_length(skill_name) <= 200",
            name="chk_project_skills_name_len",
        ),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE", name="fk_project_skills_project_id"),
        nullable=False,
    )
    skill_name: Mapped[str] = mapped_column(String, nullable=False)
    attached_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )

    def __repr__(self) -> str:
        return f"<ProjectSkill project_id={self.project_id} skill_name={self.skill_name!r}>"
