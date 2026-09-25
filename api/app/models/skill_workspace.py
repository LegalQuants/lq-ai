"""Optional owner/skill storage, independent of any invocation's lifetime."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, Integer, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class SkillWorkspace(Base):
    __tablename__ = "skill_workspaces"
    __table_args__ = (
        UniqueConstraint(
            "owner_id",
            "project_id",
            "skill_key",
            "format_version",
            name="uq_skill_workspace_scope",
            postgresql_nulls_not_distinct=True,
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    owner_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    project_id: Mapped[UUID | None] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    skill_key: Mapped[str] = mapped_column(Text)
    skill_name: Mapped[str] = mapped_column(Text)
    format_version: Mapped[int] = mapped_column(Integer)


class SkillWorkspaceFile(Base):
    __tablename__ = "skill_workspace_files"

    workspace_id: Mapped[UUID] = mapped_column(
        ForeignKey("skill_workspaces.id", ondelete="CASCADE"), primary_key=True
    )
    name: Mapped[str] = mapped_column(Text, primary_key=True)
    content: Mapped[str] = mapped_column(Text)
    revision: Mapped[UUID] = mapped_column()
    size_bytes: Mapped[int] = mapped_column(Integer)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
