"""ORM model for the chat tool-loop confirmation gate persist-and-resume state.

One row per pending destructive-tool call that has been proposed by the
assistant but not yet confirmed (or denied) by the user.  The row id IS
the ``pending_call_id`` carried in the SSE event and the resume route.

Security / data-separation rationale
-------------------------------------
``tool_call_args`` and ``resume_state`` hold the full conversation payload
needed to resume the tool-loop after the user confirms.  They live here —
deliberately NOT on ``tool_call_log`` — to preserve ``tool_call_log``'s
counts/types-only invariant (see PR5a).

``resume_state`` has the same sensitivity class as ``messages.content``
(the existing plaintext conversation store): it contains the conversation
history up to the gate, including any tool results already executed in this
turn.  It MUST NEVER be emitted to logs, tracing spans, or structured audit
fields.  Treat it exactly like a chat message body.

``status`` is single-use: once set to ``resolved`` the row MUST NOT be used
to replay a tool call.

Rows expire at ``expires_at`` (TTL, typically 15 minutes); a background job
or query filter prunes them.  The ``user_id`` and ``chat_id`` FKs cascade so
that deleting a user or a chat removes their pending-call rows (GDPR erasure /
chat deletion paths).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, Text, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class ChatPendingToolCall(Base):
    """Persist-and-resume state for the chat confirmation gate — payloads only.

    See module docstring for the security / data-separation rationale.
    ``tool_call_args`` and ``resume_state`` are NEVER logged.
    """

    __tablename__ = "chat_pending_tool_call"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    """The pending_call_id — this PK is returned to the client in the SSE event."""

    chat_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("chats.id", ondelete="CASCADE", name="fk_chat_pending_tool_call_chat"),
        nullable=False,
    )
    """FK to chats.id — cascades so deleting a chat removes its pending calls."""

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE", name="fk_chat_pending_tool_call_user"),
        nullable=False,
    )
    """FK to users.id — cascades for GDPR erasure."""

    assistant_message_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
    )
    """The in-flight assistant message id allocated up front for this turn."""

    tool_call_log_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "tool_call_log.id",
            ondelete="SET NULL",
            name="fk_chat_pending_tool_call_log",
        ),
        nullable=True,
    )
    """FK to tool_call_log.id — nullable; SET NULL on log-row deletion."""

    function_name: Mapped[str] = mapped_column(Text, nullable=False)
    """Fully-qualified function name as seen in the tool call (e.g. mcp__files__delete_doc)."""

    kind: Mapped[str] = mapped_column(Text, nullable=False)
    """'research' | 'mcp' — which execution pathway owns this tool."""

    provider: Mapped[str] = mapped_column(Text, nullable=False)
    """Logical provider name from gateway config."""

    tool: Mapped[str] = mapped_column(Text, nullable=False)
    """Tool / function name within the provider."""

    destructive: Mapped[bool] = mapped_column(Boolean, nullable=False)
    """True when the tool is flagged destructive in the governance config."""

    tier: Mapped[int] = mapped_column(Integer, nullable=False)
    """Provider egress tier (0-5) at call time."""

    tool_call_args: Mapped[dict] = mapped_column(JSONB, nullable=False)
    """Full args for the pending call — payload class; NEVER logged."""

    resume_state: Mapped[dict] = mapped_column(JSONB, nullable=False)
    """Conversation-so-far: {"messages": [...], "calls_used": int}.
    Same sensitivity as messages.content; NEVER emitted to logs or spans."""

    status: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        server_default=text("'pending'"),
    )
    """'pending' | 'resolved' — single-use gate; once resolved MUST NOT replay."""

    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    """TTL timestamp; background pruner removes rows past this time."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )
    """App-bumped on every state transition (pending → resolved)."""

    def __repr__(self) -> str:
        return (
            f"<ChatPendingToolCall id={self.id}"
            f" chat_id={self.chat_id}"
            f" function_name={self.function_name!r}"
            f" status={self.status!r}>"
        )
