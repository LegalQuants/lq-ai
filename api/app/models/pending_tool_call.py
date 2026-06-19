"""``pending_tool_call`` — a paused, human-gated chat tool call (PR5b-ii / WS4).

When the chat tool-loop proposes a ``destructive`` / ``requires_confirmation``
tool, the turn ends and one of these rows is written (spec L3 persist-and-resume).
A separate ``POST /chats/{chat_id}/tool-calls/{pending_call_id}`` approves or
denies it and resumes the assistant turn.

The row is **single-use** (deleted when resolved) and **TTL-bounded**
(``expires_at``) — the same discipline as :class:`MCPOAuthState`. The pending
call's arguments + the conversation-so-far resume state are **Fernet-encrypted
at rest** in ``payload_cipher`` (via :class:`app.security.encryption.MCPTokenEncryptor`):
they can carry user content, so — unlike the payload-free ``tool_call_log``
audit row — they never sit in plaintext.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, LargeBinary, Text, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class PendingToolCall(Base):
    """A chat tool call awaiting human approval. Server-side only; single-use."""

    __tablename__ = "pending_tool_call"

    pending_call_id: Mapped[str] = mapped_column(Text, primary_key=True)
    """Opaque URL-safe random token; the handle the client approves/denies."""

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE", name="fk_pending_tool_call_user"),
        nullable=False,
    )
    """Owner of the chat that proposed the call; cascade-deleted with the user."""

    chat_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("chats.id", ondelete="CASCADE", name="fk_pending_tool_call_chat"),
        nullable=False,
    )
    """Chat the pending call belongs to; the resume endpoint re-checks ownership."""

    message_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    """The assistant message id the resumed turn continues."""

    provider: Mapped[str] = mapped_column(Text, nullable=False)
    """Tool provider (matches gateway config name)."""

    tool: Mapped[str] = mapped_column(Text, nullable=False)
    """Tool name within the provider."""

    destructive: Mapped[bool] = mapped_column(nullable=False)
    """Whether the proposed tool is flagged destructive (vs confirm-only)."""

    payload_cipher: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    """Fernet ciphertext of the resume payload JSON: the tool args, the
    tool_call_id, and the conversation-so-far messages. NEVER plaintext — it can
    contain user content (contrast ``tool_call_log``, which is payload-free)."""

    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    """TTL horizon; the resume endpoint rejects expired rows (410)."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
