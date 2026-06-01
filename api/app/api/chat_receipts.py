"""GET /api/v1/chats/{chat_id}/receipts — replay-at-read event log.

Wave D.1 T5 (spec §7.6). Merges chronological events from four source
tables into a single timestamp-ordered stream:

* ``messages`` (one event per row; ``kind='message'``)
* ``messages.applied_skills`` (one event per skill name; ``kind='skill'``)
* ``inference_routing_log`` (``kind='inference'`` or ``kind='error'``
  if ``refused=True``)
* ``audit_log`` (``kind='audit'`` or ``kind='retrieval'`` if
  ``action='inference.kb_chunks_retrieved'``)

Replay-at-read for M1 — chats are bounded (<100 events typical), so
re-merging on each request is cheap. No new materialized table.
A materialized ``chat_receipts`` projection is a v1.1+ candidate if
latency degrades under longer chats.

Owner-of-the-chat OR admin can read; everyone else gets 404 on the
chat lookup (no information leak about chat existence).

Filter via ``?event_kinds=message,inference`` (comma-separated subset
of ``message``, ``inference``, ``audit``, ``skill``, ``retrieval``,
``error``). Unknown kinds are silently ignored — the filter is
``requested ∩ allowed``, so a bad token degrades to the safe default
rather than 400.
"""

from __future__ import annotations

import json as _json
import uuid
from datetime import datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import ActiveUser
from app.db.session import get_db
from app.errors import Forbidden, NotFound
from app.models.audit import AuditLog
from app.models.chat import Chat, Message
from app.models.inference import InferenceRoutingLog

router = APIRouter(prefix="/chats", tags=["chats"])

EventKind = Literal["message", "inference", "audit", "skill", "retrieval", "error"]
_ALL_KINDS: frozenset[str] = frozenset(
    {"message", "inference", "audit", "skill", "retrieval", "error"}
)


class ReceiptEvent(BaseModel):
    """One row in the merged event stream.

    ``detail`` is a kind-specific dict (no fixed schema across kinds —
    the UI dispatches on ``kind`` to render the right shape).
    """

    ts: datetime
    kind: EventKind
    detail: dict[str, Any]


@router.get(
    "/{chat_id}/receipts",
    response_model=list[ReceiptEvent],
    summary="Chronological event log for a chat (replay-at-read)",
    description=(
        "Wave D.1 T5 (spec §7.6). Merges chronological events from "
        "``messages`` (+ denorm ``applied_skills``), "
        "``inference_routing_log``, and ``audit_log`` into one "
        "timestamp-ordered stream. Owner-of-chat or admin only. "
        "Filter with ``?event_kinds=message,audit`` etc. "
        "Inference/error event ``detail`` includes ``anonymization_applied`` "
        "(bool — the source of truth for the UI's anonymization indicator) and "
        "``message_id`` (the assistant message the indicator pins to; may be null)."
    ),
)
async def get_chat_receipts(
    chat_id: uuid.UUID,
    user: ActiveUser,
    db: Annotated[AsyncSession, Depends(get_db)],
    event_kinds: Annotated[
        str | None,
        Query(
            description=(
                "Comma-separated subset of: message, inference, audit, "
                "skill, retrieval, error. Omit for all kinds."
            )
        ),
    ] = None,
) -> list[ReceiptEvent]:
    chat = await db.get(Chat, chat_id)
    if chat is None:
        raise NotFound(
            "Chat not found.",
            details={"chat_id": str(chat_id)},
        )
    if chat.owner_id != user.id and not user.is_admin:
        raise Forbidden(
            "You do not own this chat.",
            details={"chat_id": str(chat_id)},
        )

    requested: frozenset[str] = (
        frozenset(k.strip() for k in event_kinds.split(",") if k.strip()) & _ALL_KINDS
        if event_kinds
        else _ALL_KINDS
    )

    events: list[ReceiptEvent] = []

    # messages + denorm skill events
    if "message" in requested or "skill" in requested:
        msgs_result = await db.execute(
            select(Message).where(Message.chat_id == chat_id).order_by(Message.created_at)
        )
        msgs = list(msgs_result.scalars())

        # Wave D.2 — pre-fetch per-message attachment provenance from
        # the ``chat.message_sent`` audit row keyed by ``user_message_id``
        # (added 2026-05-13). Lets us enrich ``kind='skill'`` events with
        # the source surface (slash / picker / wizard-tryout / tryit-tab)
        # the user originally invoked the skill from. Audit row may be
        # missing for very old chats (pre-D.2) or for messages where no
        # attachment carried provenance — falls back to ``source: None``.
        skill_sources: dict[str, dict[str, str | None]] = {}
        if "skill" in requested and msgs:
            user_msg_ids = [str(m.id) for m in msgs if m.role == "user"]
            if user_msg_ids:
                provenance_rows = await db.execute(
                    select(AuditLog).where(
                        AuditLog.action == "chat.message_sent",
                        AuditLog.resource_type == "message",
                    )
                )
                for row in provenance_rows.scalars():
                    details = row.details or {}
                    user_msg_id = details.get("user_message_id")
                    if not isinstance(user_msg_id, str) or user_msg_id not in user_msg_ids:
                        continue
                    attached = details.get("attached_skills") or []
                    skill_sources[user_msg_id] = {
                        e["name"]: e.get("source")
                        for e in attached
                        if isinstance(e, dict) and e.get("name")
                    }

        for m in msgs:
            if "message" in requested:
                events.append(
                    ReceiptEvent(
                        ts=m.created_at,
                        kind="message",
                        detail={
                            "message_id": str(m.id),
                            "message_kind": m.kind,
                            "role": m.role,
                            "prompt_tokens": m.prompt_tokens,
                            "completion_tokens": m.completion_tokens,
                        },
                    )
                )
            if "skill" in requested and m.applied_skills:
                msg_sources = skill_sources.get(str(m.id), {})
                for skill_name in m.applied_skills:
                    events.append(
                        ReceiptEvent(
                            ts=m.created_at,
                            kind="skill",
                            detail={
                                "skill_name": skill_name,
                                "message_id": str(m.id),
                                "source": msg_sources.get(skill_name),
                            },
                        )
                    )

    # inference + error
    if "inference" in requested or "error" in requested:
        logs_result = await db.execute(
            select(InferenceRoutingLog)
            .where(InferenceRoutingLog.chat_id == chat_id)
            .order_by(InferenceRoutingLog.timestamp)
        )
        for log in logs_result.scalars():
            kind: EventKind = "error" if log.refused else "inference"
            if kind in requested:
                events.append(
                    ReceiptEvent(
                        ts=log.timestamp,
                        kind=kind,
                        detail={
                            "provider": log.routed_provider,
                            "model": log.routed_model,
                            "tier": log.routed_inference_tier,
                            "tokens_in": log.tokens_in,
                            "tokens_out": log.tokens_out,
                            "latency_ms": log.latency_ms,
                            "refused": log.refused,
                            "refusal_reason": log.refusal_reason,
                            # anonymization_applied is the source of truth for the
                            # UI's anonymization indicator; message_id pins the
                            # indicator to the right assistant message bubble.
                            "anonymization_applied": log.anonymization_applied,
                            "message_id": str(log.message_id) if log.message_id else None,
                        },
                    )
                )

    # audit + retrieval (retrieval is the T7-bound action
    # `inference.kb_chunks_retrieved` rendered as its own kind so the UI
    # can show a retrieval-specific affordance).
    if "audit" in requested or "retrieval" in requested:
        audits_result = await db.execute(
            select(AuditLog)
            .where(AuditLog.resource_type == "chat")
            .where(AuditLog.resource_id == str(chat_id))
            .order_by(AuditLog.timestamp)
        )
        for a in audits_result.scalars():
            kind = "retrieval" if a.action == "inference.kb_chunks_retrieved" else "audit"
            if kind in requested:
                events.append(
                    ReceiptEvent(
                        ts=a.timestamp,
                        kind=kind,
                        detail={
                            "action": a.action,
                            "actor_user_id": (str(a.user_id) if a.user_id else None),
                            "details": a.details,
                        },
                    )
                )

    events.sort(key=lambda e: e.ts)
    return events


@router.get(
    "/{chat_id}/receipts/export.jsonl",
    summary="Export receipts as JSONL (one event per line)",
    response_class=Response,
)
async def export_chat_receipts(
    chat_id: uuid.UUID,
    user: ActiveUser,
    db: Annotated[AsyncSession, Depends(get_db)],
    event_kinds: Annotated[str | None, Query()] = None,
) -> Response:
    """Same payload as the JSON receipts endpoint, serialized as JSONL.

    ``Content-Type: application/jsonl`` + ``Content-Disposition: attachment;
    filename="chat-{id}-receipts.jsonl"`` so browsers trigger a download.
    """
    events = await get_chat_receipts(
        chat_id=chat_id,
        user=user,
        db=db,
        event_kinds=event_kinds,
    )
    body = "\n".join(_json.dumps(e.model_dump(mode="json")) for e in events)
    return Response(
        content=body,
        media_type="application/jsonl",
        headers={
            "Content-Disposition": (f'attachment; filename="chat-{chat_id}-receipts.jsonl"'),
        },
    )


__all__ = ["router"]
