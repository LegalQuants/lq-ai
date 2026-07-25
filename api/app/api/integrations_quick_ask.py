"""Bridge quick-ask surface — DE-288 (``/lq ask`` on Slack + Teams).

``POST /api/v1/integrations/quick-ask`` is called by the slack-bridge
and teams-bridge with the shared ``LQ_AI_BRIDGE_TOKEN`` bearer (same
posture as the workspace/tenant persistence endpoints). The bearer
authenticates *the bridge*, never the user — this handler re-derives
the acting user from the bridge-supplied platform identity and runs
the turn under that user's authority (matterbridge's channel-level
trust is the explicit anti-pattern per the DE-288 research memo).

Identity resolution (fail-closed — never guess, never answer as a
shared identity):

* **Slack** — the bridge sends ``(team_ref=team_id, platform_user_id)``.
  The bridge holds no bot token (tokens land here encrypted at OAuth
  time), so this handler decrypts the workspace's stored bot token and
  resolves the invoker's profile email via Slack ``users.info``
  (requires the ``users:read`` + ``users:read.email`` scopes the
  DE-288 manifest adds; pre-DE-288 installs fail closed until
  re-installed). Platform egress note: this is chat-transport egress
  to slack.com, categorically separate from inference egress — the
  gateway remains the only holder of provider keys. This module is an
  audited exception to the backend no-direct-egress invariant; the
  decision (api-side call beats handing decrypted bot tokens back to
  the bridge) is recorded in ADR 0025 and enforced via the
  ``_EGRESS_ALLOWLIST`` entry in ``test_transparency_invariants.py``.
* **Teams** — the bridge resolves the invoker's email itself from the
  Bot Connector conversation-member record (it holds the app-level
  bot credentials) and sends ``(team_ref=tenant_id, email)``. The
  handler still verifies the tenant is a live registered install.

The resolved email is matched case-insensitively against live LQ.AI
accounts. Every resolution failure — unknown workspace/tenant, token
missing scope, Slack API unreachable, no matching account — collapses
to 404 ``user_not_linked`` so the bridge renders one "account isn't
linked" refusal without leaking which step failed. An account that
exists but has not cleared the password-change / mandatory-MFA gates
gets 403 ``forbidden`` ("finish setup in the web app").

The turn itself runs through the NORMAL chat-send path
(:func:`app.api.chats.send_message`) — history, KB retrieval, skill
assembly, citation persistence, audit, and cost attribution all behave
exactly as a web-UI send by that user. Provenance is tagged with a
``bridge.quick_ask`` audit row (``details.source`` = slack/teams) and
a ``bridge-{platform}-…`` request id that flows into the gateway's
routing/cost log.
"""

from __future__ import annotations

import json
import logging
import uuid
from typing import Annotated, Any

import httpx
from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request as StarletteRequest

from app.api.dependencies import require_bridge_auth
from app.audit import audit_action
from app.clients.gateway import GatewayClient, get_gateway_client
from app.config import Settings, get_settings
from app.db.session import get_db
from app.errors import Forbidden, InternalError, NotFound
from app.models.chat import Chat
from app.models.slack_workspace import SlackWorkspace
from app.models.teams_tenant import TeamsTenant
from app.models.user import User
from app.schemas.quick_ask import QuickAskRequest, QuickAskResponse
from app.security.encryption import BridgeTokenEncryptor

log = logging.getLogger(__name__)

router = APIRouter(prefix="/integrations", tags=["integrations-quick-ask"])

SLACK_USERS_INFO_URL = "https://slack.com/api/users.info"
SLACK_API_TIMEOUT_SECONDS = 10.0


def _not_linked(reason: str, *, platform: str, team_ref: str) -> NotFound:
    """Uniform fail-closed refusal for every identity-resolution failure.

    The *reason* goes to the log only; the response carries a single
    stable ``user_not_linked`` code so the bridge (and anyone probing
    with a stolen bridge bearer) cannot distinguish which step failed.
    """

    log.warning(
        "quick_ask.not_linked platform=%s team_ref=%s reason=%s",
        platform,
        team_ref,
        reason,
    )
    return NotFound(
        message=(
            "This platform account could not be linked to an LQ.AI account on this deployment."
        ),
        code="user_not_linked",
        details={"platform": platform},
    )


async def _resolve_slack_email(
    db: AsyncSession,
    settings: Settings,
    *,
    team_ref: str,
    slack_user_id: str,
) -> str:
    """Resolve a Slack user's profile email via ``users.info``.

    Uses the workspace's stored (encrypted) bot token. Any failure —
    unknown/disconnected workspace, decryption failure, missing scope,
    Slack unreachable, no email on the profile — raises the uniform
    ``user_not_linked`` refusal.
    """

    workspace = (
        await db.execute(
            select(SlackWorkspace).where(
                SlackWorkspace.team_id == team_ref,
                SlackWorkspace.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if workspace is None:
        raise _not_linked("unknown or disconnected workspace", platform="slack", team_ref=team_ref)

    encryptor = BridgeTokenEncryptor(master_key=settings.lq_ai_bridge_master_key or None)
    try:
        bot_token = encryptor.decrypt(workspace.bot_token_encrypted)
    except Exception:
        # Operator misconfiguration (wrong master key) — not an
        # identity problem, so don't masquerade as "not linked".
        log.exception("quick_ask.bot_token_decrypt_failed team_ref=%s", team_ref)
        raise InternalError(
            message="Bridge token decryption failed; check LQ_AI_BRIDGE_MASTER_KEY.",
        ) from None

    try:
        async with httpx.AsyncClient(timeout=SLACK_API_TIMEOUT_SECONDS) as client:
            res = await client.get(
                SLACK_USERS_INFO_URL,
                params={"user": slack_user_id},
                headers={"Authorization": f"Bearer {bot_token}"},
            )
        payload: dict[str, Any] = res.json() if res.status_code == 200 else {}
    except (httpx.HTTPError, ValueError) as exc:
        raise _not_linked(
            "slack users.info unreachable", platform="slack", team_ref=team_ref
        ) from exc

    if not payload.get("ok"):
        raise _not_linked(
            f"slack users.info error={payload.get('error', 'unknown')!r}",
            platform="slack",
            team_ref=team_ref,
        )

    profile: dict[str, Any] = {}
    user_obj = payload.get("user")
    if isinstance(user_obj, dict):
        profile = user_obj.get("profile") or {}
    email = str(profile.get("email") or "").strip()
    if not email:
        raise _not_linked("no email on slack profile", platform="slack", team_ref=team_ref)
    return email


async def _resolve_lq_user(
    db: AsyncSession,
    settings: Settings,
    *,
    email: str,
    platform: str,
    team_ref: str,
) -> User:
    """Map a resolved platform email onto a live LQ.AI account.

    Fail-closed: no match → ``user_not_linked``. A matched account
    that has not cleared the password-change / mandatory-MFA gates
    → 403 (mirrors :func:`app.api.dependencies.get_active_user` so a
    bridge invocation can never do more than a web login could).
    """

    user = (
        await db.execute(
            select(User).where(
                func.lower(User.email) == email.lower(),
                User.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if user is None:
        raise _not_linked(
            "no LQ.AI account matches the platform email",
            platform=platform,
            team_ref=team_ref,
        )

    if user.must_change_password or (settings.mfa_mandatory and not user.mfa_enabled):
        raise Forbidden(
            message=(
                "This LQ.AI account has not finished setup. Sign in to "
                "the LQ.AI web app to complete it, then try again."
            ),
        )
    return user


def _synthetic_send_request(
    inbound: Request,
    *,
    chat_id: uuid.UUID,
    body: dict[str, Any],
    request_id: str,
) -> StarletteRequest:
    """Build an in-process Request carrying ``body`` as its JSON payload.

    :func:`app.api.chats.send_message` reads its payload from the
    Request object (it accepts a union body shape), so reusing the
    normal chat-send path verbatim means synthesizing the Request the
    handler would have seen. The scope reuses the real inbound app
    reference (skill-registry lookups go through ``request.app.state``)
    and carries no client address — the audit path treats that as an
    internal call.
    """

    raw = json.dumps(body).encode("utf-8")
    path = f"/api/v1/chats/{chat_id}/messages"
    scope: dict[str, Any] = {
        "type": "http",
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": path,
        "raw_path": path.encode("ascii"),
        "root_path": "",
        "query_string": b"",
        "headers": [
            (b"content-type", b"application/json"),
            (b"x-request-id", request_id.encode("ascii")),
        ],
        "client": None,
        "server": ("bridge-internal", 0),
        "app": inbound.app,
    }

    sent = False

    async def receive() -> dict[str, Any]:
        nonlocal sent
        if sent:
            return {"type": "http.disconnect"}
        sent = True
        return {"type": "http.request", "body": raw, "more_body": False}

    return StarletteRequest(scope, receive)


@router.post(
    "/quick-ask",
    response_model=QuickAskResponse,
    dependencies=[Depends(require_bridge_auth)],
)
async def quick_ask(
    body: QuickAskRequest,
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
    db: Annotated[AsyncSession, Depends(get_db)],
    gateway: Annotated[GatewayClient, Depends(get_gateway_client)],
) -> QuickAskResponse:
    """Run a bridge-initiated quick-ask turn as the resolved user.

    Creates a fresh chat owned by the resolved user (auto-titled from
    the question by the send path), attaches the operator-configured
    quick-ask skill when set, and returns the assistant's answer plus
    a web deep link. Non-streaming by design: the bridge delivers one
    final message, never chunks.
    """

    if body.platform == "slack":
        email = await _resolve_slack_email(
            db,
            settings,
            team_ref=body.team_ref,
            slack_user_id=(body.platform_user_id or "").strip(),
        )
    else:
        tenant = (
            await db.execute(
                select(TeamsTenant).where(
                    TeamsTenant.tenant_id == body.team_ref,
                    TeamsTenant.deleted_at.is_(None),
                )
            )
        ).scalar_one_or_none()
        if tenant is None:
            raise _not_linked(
                "unknown or disconnected tenant", platform="teams", team_ref=body.team_ref
            )
        email = (body.email or "").strip()

    user = await _resolve_lq_user(
        db,
        settings,
        email=email,
        platform=body.platform,
        team_ref=body.team_ref,
    )

    chat = Chat(owner_id=user.id, title="New chat")
    db.add(chat)
    await db.flush()
    await db.commit()
    await db.refresh(chat)

    request_id = f"bridge-{body.platform}-{uuid.uuid4().hex[:12]}"
    quick_ask_skill = settings.lq_ai_bridge_quick_ask_skill.strip()

    # Provenance tag — committed on its own boundary BEFORE dispatch so
    # Receipts records the bridge-initiated turn (and its source
    # platform) even if the gateway call fails. The question text is
    # deliberately NOT recorded here (details must stay PII-safe); it
    # lives in the chat's message rows like any other turn.
    await audit_action(
        db,
        user_id=user.id,
        action="bridge.quick_ask",
        resource_type="chat",
        resource_id=str(chat.id),
        request=request,
        details={
            "source": body.platform,
            "team_ref": body.team_ref,
            "skill": quick_ask_skill or None,
            "request_id": request_id,
        },
    )
    await db.commit()

    send_body: dict[str, Any] = {
        "content": body.question,
        "model": "smart",
        "stream": False,
    }
    if quick_ask_skill:
        send_body["skills"] = [quick_ask_skill]

    # Local import: chats.py is a large module and importing it at
    # call time keeps this service-to-service module's import cost off
    # the app-startup path (mirrors the internal.py pattern).
    from app.api.chats import send_message

    synthetic = _synthetic_send_request(
        request,
        chat_id=chat.id,
        body=send_body,
        request_id=request_id,
    )
    response = await send_message(
        chat_id=str(chat.id),
        request=synthetic,
        user=user,
        db=db,
        gateway=gateway,
    )
    if not isinstance(response, JSONResponse):
        # stream=False makes this unreachable; guard it anyway so a
        # future send-path change cannot silently hand the bridge an
        # SSE stream.
        log.error("quick_ask.unexpected_streaming_response request_id=%s", request_id)
        raise InternalError(message="Chat send returned an unexpected response type.")

    try:
        payload: dict[str, Any] = json.loads(bytes(response.body))
    except (ValueError, TypeError):
        log.error("quick_ask.unparseable_send_response request_id=%s", request_id)
        raise InternalError(message="Chat send returned an unparseable response.") from None

    answer_text = str(((payload.get("message") or {}).get("content")) or "")

    web_base = settings.lq_ai_web_public_url.strip().rstrip("/")
    chat_url = f"{web_base}/lq-ai/chats?id={chat.id}" if web_base else None

    log.info(
        "quick_ask.completed platform=%s chat_id=%s request_id=%s answer_chars=%d",
        body.platform,
        chat.id,
        request_id,
        len(answer_text),
    )
    return QuickAskResponse(answer_text=answer_text, chat_id=chat.id, chat_url=chat_url)


__all__ = ["router"]
