"""User-export job ORM model — Task D6.

Backs the GDPR Article 20 export endpoint pair (``POST /users/me/export``
+ ``GET /users/me/export/{job_id}``). The :class:`UserExportJob` row
tracks one async export from queued → processing → completed/failed.
The actual ZIP bytes live in object storage under the ``storage_key`` the
worker writes; ``GET`` returns a presigned URL for the bytes.

See docs/db-schema.md §`user_export_jobs` and migration 0009 for the
authoritative DDL.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Text, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class UserExportJob(Base):
    """A queued/in-progress/completed per-user data export.

    One row per ``POST /users/me/export`` invocation. Status progresses
    monotonically; ``failed`` is terminal. The worker fills ``started_at``,
    ``completed_at``, ``storage_key``, ``error_message``, and ``expires_at``
    as it runs. The export-GC cron clears ``storage_key`` once
    ``expires_at`` passes (the row is kept for audit / status history).
    """

    __tablename__ = "user_export_jobs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE", name="fk_user_export_jobs_user_id"),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    storage_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    def __repr__(self) -> str:
        return f"<UserExportJob id={self.id} user_id={self.user_id} status={self.status}>"
