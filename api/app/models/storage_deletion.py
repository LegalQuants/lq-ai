"""Durable object-erasure work, committed with the deletion it follows."""

from datetime import datetime

from sqlalchemy import DateTime, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class StorageDeletion(Base):
    __tablename__ = "storage_deletion_queue"
    storage_path: Mapped[str] = mapped_column(Text, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
