"""Persist-and-resume store for human-gated chat tool calls (PR5b-ii / WS4).

Backs the confirmation gate (spec L3): when the tool-loop proposes a
``destructive`` / ``requires_confirmation`` tool, :func:`create_pending_tool_call`
stores an encrypted, TTL-bounded, single-use row; the approve/deny endpoint
calls :func:`consume_pending_tool_call` to atomically claim + decrypt it.

The resume payload (tool args + the conversation-so-far) is Fernet-encrypted
via :class:`app.security.encryption.MCPTokenEncryptor` — it can carry user
content, so it is never stored in plaintext (contrast the payload-free
``tool_call_log`` audit row).
"""

from __future__ import annotations

import json
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.pending_tool_call import PendingToolCall
from app.schemas.gateway import ChatCompletionMessage
from app.security.encryption import MCPTokenEncryptor

PENDING_TTL = timedelta(minutes=15)
"""How long an unresolved pending call stays claimable before it is rejected."""


class PendingToolCallUnavailable(Exception):
    """Pending call is unknown, not owned by the caller, already resolved, or
    expired. The endpoint maps this to HTTP 410 Gone (id-probing-safe: the same
    error for every not-resolvable reason)."""


def _now() -> datetime:
    return datetime.now(tz=UTC)


@dataclass
class ResumePayload:
    """Everything the resume path needs to continue the assistant turn."""

    provider: str
    tool: str
    destructive: bool
    args: dict[str, Any]
    tool_call_id: str
    messages: list[ChatCompletionMessage]
    max_allowed_tier: int | None


async def create_pending_tool_call(
    db: AsyncSession,
    *,
    user_id: UUID,
    chat_id: UUID,
    message_id: UUID,
    provider: str,
    tool: str,
    destructive: bool,
    args: dict[str, Any],
    tool_call_id: str,
    messages: list[ChatCompletionMessage],
    max_allowed_tier: int | None,
) -> str:
    """Persist an encrypted pending tool call; return its opaque handle.

    Flushes (does not commit) — the caller owns the transaction boundary, like
    the rest of the chat send path.
    """

    token = secrets.token_urlsafe(32)
    payload = {
        "args": args,
        "tool_call_id": tool_call_id,
        "messages": [m.model_dump(mode="json") for m in messages],
        "max_allowed_tier": max_allowed_tier,
    }
    cipher = MCPTokenEncryptor.from_environ().encrypt(json.dumps(payload))
    db.add(
        PendingToolCall(
            pending_call_id=token,
            user_id=user_id,
            chat_id=chat_id,
            message_id=message_id,
            provider=provider,
            tool=tool,
            destructive=destructive,
            payload_cipher=cipher,
            expires_at=_now() + PENDING_TTL,
        )
    )
    await db.flush()
    return token


async def consume_pending_tool_call(
    db: AsyncSession,
    *,
    pending_call_id: str,
    chat_id: UUID,
    user_id: UUID,
) -> ResumePayload:
    """Atomically claim a pending call: validate owner, delete (single-use),
    check TTL, decrypt. Raises :class:`PendingToolCallUnavailable` for any
    unknown / foreign / already-consumed / expired row (→ 410).

    Single-use is enforced by deleting the row *before* the expiry check, so a
    replay of the same handle always finds nothing.
    """

    row = (
        await db.execute(
            select(PendingToolCall).where(PendingToolCall.pending_call_id == pending_call_id)
        )
    ).scalar_one_or_none()
    if row is None or row.chat_id != chat_id or row.user_id != user_id:
        raise PendingToolCallUnavailable("pending tool call not found")

    # Single-use: claim by deletion before doing anything else.
    await db.execute(
        delete(PendingToolCall).where(PendingToolCall.pending_call_id == pending_call_id)
    )

    if row.expires_at < _now():
        raise PendingToolCallUnavailable("pending tool call expired")

    data = json.loads(MCPTokenEncryptor.from_environ().decrypt(row.payload_cipher))
    return ResumePayload(
        provider=row.provider,
        tool=row.tool,
        destructive=row.destructive,
        args=data["args"],
        tool_call_id=data["tool_call_id"],
        messages=[ChatCompletionMessage.model_validate(m) for m in data["messages"]],
        max_allowed_tier=data.get("max_allowed_tier"),
    )
