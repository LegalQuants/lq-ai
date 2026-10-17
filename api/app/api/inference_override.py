"""POST /api/v1/inference/override-tier-floor — Wave D.1 T4.

Admin-only re-run of a refused inference with the tier floor lifted
for this one turn. Looks up the preceding user message, delegates the
gateway re-run to :func:`app.api.chats.run_inference_override`, writes
an ``audit_log`` row carrying the override reason, and returns the new
``kind='ai'`` :class:`Message` plus the routing-log id the gateway
wrote.

M1 binds this surface to the ``is_admin`` role (per the RBAC
simplification in Wave D.1 §7.4 / spec discussion). A per-user
``override_tier_floor`` capability is queued for v1.1+.

The new module exists rather than living in :mod:`app.api.inference`
to keep the override surface independently auditable: a security
reviewer can read the entire admin-bypass code path from one file.
The router carries the same ``/inference`` prefix so the wire URL is
``/api/v1/inference/override-tier-floor``.
"""

from __future__ import annotations

import logging
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.chats import run_inference_override
from app.api.dependencies import AdminUser
from app.audit import audit_action
from app.authz.matters import require_matter
from app.clients.gateway import GatewayClient, get_gateway_client
from app.db.session import get_db
from app.errors import NotFound, ValidationError
from app.models.chat import Chat, Message
from app.schemas.chats import MessageResponse, message_to_response

log = logging.getLogger(__name__)

router = APIRouter(prefix="/inference", tags=["inference"])


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------


class OverrideRequest(BaseModel):
    """``POST /inference/override-tier-floor`` request body.

    ``reason`` is mandatory and persisted to ``audit_log.details.reason``
    — the operator's audit posture relies on the override carrying a
    human-readable justification.
    """

    message_id: uuid.UUID
    """ID of the refusal :class:`Message` the admin is re-running. Must
    resolve to a ``kind='refusal'`` row; any other kind is 404."""

    reason: str = Field(min_length=10, max_length=500)
    """Free-text justification for the override. Captured on the
    ``audit_log`` row's ``details`` payload. Bounded to keep the audit
    row size predictable."""


class OverrideResponse(BaseModel):
    """``POST /inference/override-tier-floor`` response."""

    ai_message: MessageResponse
    routing_log_id: uuid.UUID | None = None
    """Identifier of the ``inference_routing_log`` row the gateway
    wrote for this re-run. Surfaced so the admin UI can deep-link to
    the routing log entry. Null only in test scenarios where the
    gateway is stubbed without a routing-log write."""


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------


@router.post(
    "/override-tier-floor",
    response_model=OverrideResponse,
    summary="Re-run a refused inference with the tier floor lifted (admin only)",
    description=(
        "Wave D.1 T4. Admin-only override that re-runs the original user "
        "prompt with ``tier_floor=None`` for this turn. Writes a new "
        "``kind='ai'`` message, an inference routing log row (via the "
        "gateway, per the B4 invariant), and an audit log row capturing "
        "the override reason."
    ),
)
async def override_tier_floor(
    payload: OverrideRequest,
    request: Request,
    admin: AdminUser,
    db: Annotated[AsyncSession, Depends(get_db)],
    gateway: Annotated[GatewayClient, Depends(get_gateway_client)],
) -> OverrideResponse:
    """Admin override of a tier-floor refusal."""

    refusal = await db.get(Message, payload.message_id)
    if refusal is None or refusal.kind != "refusal":
        raise NotFound(
            "Refusal message not found.",
            details={"message_id": str(payload.message_id)},
        )

    chat = await db.get(Chat, refusal.chat_id)
    if chat is None:  # pragma: no cover — FK guarantees existence
        raise NotFound(
            "Chat not found for refusal message.",
            details={"chat_id": str(refusal.chat_id)},
        )

    if chat.project_id is not None:
        await require_matter(db, chat.project_id, admin, need="write", include_archived=True)

    # Locate the most recent ``kind='user'`` row that precedes the
    # refusal in the same chat. That's the prompt we re-run.
    user_msg_result = await db.execute(
        select(Message)
        .where(Message.chat_id == refusal.chat_id)
        .where(Message.kind == "user")
        .where(Message.created_at < refusal.created_at)
        .order_by(Message.created_at.desc())
        .limit(1)
    )
    user_msg = user_msg_result.scalar_one_or_none()
    if user_msg is None:
        raise ValidationError(
            "No preceding user message found for refusal.",
            details={"refusal_message_id": str(refusal.id)},
        )

    # Delegate to the chat module's helper — same gateway-call shape as
    # the normal send-message path but with the tier floor lifted.
    ai_message, routing_log_id = await run_inference_override(
        db=db,
        gateway=gateway,
        chat=chat,
        user=admin,
        user_msg=user_msg,
        refusal_msg=refusal,
        override_reason=payload.reason,
        request=request,
    )

    await audit_action(
        db,
        user_id=admin.id,
        action="inference.tier_floor_overridden",
        resource_type="message",
        resource_id=str(refusal.id),
        request=request,
        details={
            "reason": payload.reason,
            "chat_id": str(refusal.chat_id),
            "new_message_id": str(ai_message.id),
            "routing_log_id": str(routing_log_id) if routing_log_id else None,
        },
    )
    await db.commit()
    await db.refresh(ai_message)

    return OverrideResponse(
        ai_message=message_to_response(ai_message),
        routing_log_id=routing_log_id,
    )


__all__ = ["router"]
