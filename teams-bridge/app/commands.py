"""``/lq`` command surface for Microsoft Teams — DE-288.

``POST /teams/messages`` is the Bot Framework messaging endpoint the
operator points their Azure Bot resource at. The handler follows the
BotBuilder ``ActivityHandler`` *shape* (per the DE-288 research memo)
without the botbuilder dependency: a single dispatch on
``activity.type`` — ``message`` activities are parsed as ``/lq``
commands; ``conversationUpdate`` posts a welcome/usage message when a
non-bot member joins; every other type is acknowledged and ignored.

Unlike Slack there is no 3-second ack contract, but the inbound HTTP
call still returns 200 promptly: the real work (Connector token,
member-info lookup, api quick-ask, reply activity) runs in a
Starlette background task after the response is flushed. The reply is
delivered as ONE outbound activity POSTed to the activity's
``serviceUrl`` with an app-credentials Connector token.

Identity (fail-closed): the invoker's email comes from the Bot
Connector conversation-member record
(``GET {serviceUrl}/v3/conversations/{id}/members/{userId}``) fetched
with OUR authenticated outbound token — never from inbound-suppliable
activity fields alone. The api then maps email → LQ.AI account and
enforces that user's authority; an unmatched email gets the "account
isn't linked" refusal.

.. warning:: **Inbound-auth limitation (documented honestly).**

   The Bot Connector spec requires a seven-point JWT validation of the
   inbound ``Authorization`` header (issuer, audience = app id,
   signature against the Connector JWKS, serviceUrl claim match, …).
   That requires a JWT library; per the DE-288 memo the
   PyJWT-vs-botbuilder dependency choice is a maintainer fork, and
   this bridge deliberately adds NO new dependency to resolve it
   unilaterally. Until that lands, inbound auth here is:

   * a presence check on the ``Authorization: Bearer`` header (401
     when absent — blocks casual unauthenticated pokes only; it is
     NOT cryptographic validation);
   * a strict host allowlist on ``serviceUrl`` (``*.botframework.com``
     / ``*.smba.trafficmanager.net``) so a forged activity cannot steer our
     authenticated outbound calls to an attacker host;
   * identity derived from the authenticated member-info call plus the
     api's own fail-closed email → account mapping — a forged inbound
     cannot mint authority the mapped user doesn't have, and an
     unmapped identity gets a refusal.

   Operators should additionally restrict network ingress to the
   bridge. Full JWT validation is the highest-priority follow-up for
   this surface and lands via the security-review path.
"""

from __future__ import annotations

import html
import logging
import re
import shlex
import uuid
from dataclasses import dataclass
from typing import Annotated, Any
from urllib.parse import urlsplit

import httpx
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from fastapi.responses import JSONResponse

from .config import Settings, get_settings

log = logging.getLogger(__name__)

router = APIRouter(prefix="/teams", tags=["teams-commands"])

# Microsoft identity platform token endpoint for Bot Framework
# client-credentials tokens (single-tenant `botframework.com` issuer).
CONNECTOR_TOKEN_URL = "https://login.microsoftonline.com/botframework.com/oauth2/v2.0/token"
CONNECTOR_SCOPE = "https://api.botframework.com/.default"

CONNECTOR_TIMEOUT_SECONDS = 15.0
QUICK_ASK_TIMEOUT_SECONDS = 120.0

USAGE_TEXT = (
    "**LQ.AI quick-ask**\n\n"
    '- `/lq ask "<your question>"` — ask the configured quick-ask '
    "skill and get an answer here.\n"
    "- `/lq help` — show this message."
)

# Hosts the bridge will POST Connector calls to. The real Teams
# serviceUrl is https://smba.trafficmanager.net/<region>/; emulators /
# other channels use *.botframework.com. Anything else is treated as a
# forged activity and dropped (see the module-level auth note).
# NOTE: the bare `.trafficmanager.net` apex is deliberately NOT
# allowed — Azure Traffic Manager is a shared, customer-registrable
# namespace, so only the Microsoft-operated Connector host
# `smba.trafficmanager.net` (and subdomains) qualifies. Once inbound
# JWT validation lands, the validated token's `serviceUrl` claim
# supersedes this list entirely.
_ALLOWED_SERVICE_URL_SUFFIXES = (".botframework.com", ".smba.trafficmanager.net")
# The suffixes above match subdomains only; real serviceUrls use the
# exact Connector host (e.g. https://smba.trafficmanager.net/amer/),
# so the bare hosts are allowed explicitly as well.
_ALLOWED_SERVICE_URL_HOSTS = tuple(s.removeprefix(".") for s in _ALLOWED_SERVICE_URL_SUFFIXES)

_MENTION_RE = re.compile(r"<at>.*?</at>", re.DOTALL)

_SMART_QUOTE_MAP = {
    0x2018: "'",
    0x2019: "'",
    0x201C: '"',
    0x201D: '"',
}


@dataclass(frozen=True)
class ParsedCommand:
    """Outcome of parsing the ``/lq`` command text (mirrors slack-bridge)."""

    action: str
    question: str = ""


def strip_mentions(text: str) -> str:
    """Remove ``<at>…</at>`` bot-mention markup Teams injects."""

    return _MENTION_RE.sub("", text).strip()


def normalize_command_text(text: str) -> str:
    """HTML-entity unescape + smart-quote → ASCII normalization."""

    return html.unescape(text).translate(_SMART_QUOTE_MAP)


def parse_lq_text(text: str) -> ParsedCommand | None:
    """Parse a message body into an ``/lq`` command.

    Returns ``None`` when the (mention-stripped) text does not start
    with ``/lq`` — the bot only acts on explicit invocations, mirroring
    the Slack surface. Parse failures and unknown subcommands map to
    ``help`` (friendly usage, never silence or a stack trace).
    """

    cleaned = normalize_command_text(strip_mentions(text)).strip()
    if not cleaned.lower().startswith("/lq"):
        return None
    remainder = cleaned[len("/lq") :].strip()
    if not remainder:
        return ParsedCommand(action="help")

    try:
        tokens = shlex.split(remainder)
    except ValueError:
        return ParsedCommand(action="help")
    if not tokens:
        return ParsedCommand(action="help")

    subcommand = tokens[0].lower()
    if subcommand == "ask":
        question = " ".join(tokens[1:]).strip()
        if not question:
            return ParsedCommand(action="help")
        return ParsedCommand(action="ask", question=question)
    return ParsedCommand(action="help")


def service_url_allowed(service_url: str) -> bool:
    """True when ``serviceUrl`` is an https Bot Connector host.

    Load-bearing while inbound JWT validation is pending: our
    authenticated outbound calls only ever go to Microsoft-operated
    Connector hosts, so a forged activity cannot redirect the bot
    token or the reply to an attacker endpoint.
    """

    try:
        parts = urlsplit(service_url)
    except ValueError:
        return False
    if parts.scheme != "https" or not parts.hostname:
        return False
    hostname = parts.hostname.lower()
    return hostname in _ALLOWED_SERVICE_URL_HOSTS or hostname.endswith(
        _ALLOWED_SERVICE_URL_SUFFIXES
    )


async def _get_connector_token(settings: Settings, correlation_id: str) -> str | None:
    """Fetch a client-credentials Connector token; None on failure."""

    try:
        async with httpx.AsyncClient(timeout=CONNECTOR_TIMEOUT_SECONDS) as client:
            res = await client.post(
                CONNECTOR_TOKEN_URL,
                data={
                    "grant_type": "client_credentials",
                    "client_id": settings.microsoft_app_id,
                    "client_secret": settings.microsoft_app_password,
                    "scope": CONNECTOR_SCOPE,
                },
            )
    except httpx.HTTPError:
        log.exception("teams.commands.token_unreachable correlation=%s", correlation_id)
        return None
    if res.status_code != 200:
        log.warning(
            "teams.commands.token_rejected status=%s correlation=%s",
            res.status_code,
            correlation_id,
        )
        return None
    try:
        token = res.json().get("access_token")
    except ValueError:
        token = None
    if not isinstance(token, str) or not token:
        log.warning("teams.commands.token_malformed correlation=%s", correlation_id)
        return None
    return token


async def _post_reply(
    *,
    token: str,
    service_url: str,
    activity: dict[str, Any],
    text: str,
    correlation_id: str,
) -> None:
    """POST one reply activity to the Connector; failures are logged."""

    conversation = activity.get("conversation") or {}
    conversation_id = str(conversation.get("id") or "")
    if not conversation_id:
        log.warning("teams.commands.reply_no_conversation correlation=%s", correlation_id)
        return

    url = f"{service_url.rstrip('/')}/v3/conversations/{conversation_id}/activities"
    reply: dict[str, Any] = {
        "type": "message",
        "text": text,
        "from": activity.get("recipient") or {},
        "recipient": activity.get("from") or {},
        "conversation": conversation,
    }
    if activity.get("id"):
        reply["replyToId"] = activity["id"]

    try:
        async with httpx.AsyncClient(timeout=CONNECTOR_TIMEOUT_SECONDS) as client:
            res = await client.post(
                url,
                json=reply,
                headers={"Authorization": f"Bearer {token}"},
            )
        if res.status_code not in (200, 201, 202):
            log.warning(
                "teams.commands.reply_rejected status=%s correlation=%s",
                res.status_code,
                correlation_id,
            )
    except httpx.HTTPError:
        log.exception("teams.commands.reply_failed correlation=%s", correlation_id)


async def _resolve_member_email(
    *,
    token: str,
    service_url: str,
    activity: dict[str, Any],
    correlation_id: str,
) -> str | None:
    """Fetch the invoker's email from the Connector member record.

    Teams populates ``email`` / ``userPrincipalName`` on the
    conversation-member record for AAD users. ``None`` on any failure
    — the caller renders the fail-closed "isn't linked" refusal.
    """

    conversation = activity.get("conversation") or {}
    sender = activity.get("from") or {}
    conversation_id = str(conversation.get("id") or "")
    sender_id = str(sender.get("id") or "")
    if not (conversation_id and sender_id):
        log.warning("teams.commands.member_missing_ids correlation=%s", correlation_id)
        return None

    url = f"{service_url.rstrip('/')}/v3/conversations/{conversation_id}/members/{sender_id}"
    try:
        async with httpx.AsyncClient(timeout=CONNECTOR_TIMEOUT_SECONDS) as client:
            res = await client.get(url, headers={"Authorization": f"Bearer {token}"})
    except httpx.HTTPError:
        log.exception("teams.commands.member_unreachable correlation=%s", correlation_id)
        return None
    if res.status_code != 200:
        log.warning(
            "teams.commands.member_rejected status=%s correlation=%s",
            res.status_code,
            correlation_id,
        )
        return None
    try:
        member = res.json()
    except ValueError:
        return None
    if not isinstance(member, dict):
        return None
    email = member.get("email") or member.get("userPrincipalName")
    if not isinstance(email, str) or not email.strip():
        log.warning("teams.commands.member_no_email correlation=%s", correlation_id)
        return None
    return email.strip()


def _tenant_ref(activity: dict[str, Any]) -> str:
    """Extract the AAD tenant id from the activity (two documented homes)."""

    conversation = activity.get("conversation") or {}
    tenant_id = conversation.get("tenantId")
    if isinstance(tenant_id, str) and tenant_id:
        return tenant_id
    channel_data = activity.get("channelData") or {}
    tenant = channel_data.get("tenant") if isinstance(channel_data, dict) else None
    if isinstance(tenant, dict):
        candidate = tenant.get("id")
        if isinstance(candidate, str):
            return candidate
    return ""


async def run_quick_ask(
    *,
    settings: Settings,
    activity: dict[str, Any],
    question: str,
    correlation_id: str,
) -> None:
    """Deferred worker for ``/lq ask``: resolve identity, call the api,
    deliver ONE reply activity. All failure paths converge on a reply
    (or a log line when even replying is impossible)."""

    service_url = str(activity.get("serviceUrl") or "")
    token = await _get_connector_token(settings, correlation_id)
    if token is None:
        # Cannot reach the Connector at all — nothing to reply with.
        return

    async def reply(text: str) -> None:
        await _post_reply(
            token=token,
            service_url=service_url,
            activity=activity,
            text=text,
            correlation_id=correlation_id,
        )

    email = await _resolve_member_email(
        token=token,
        service_url=service_url,
        activity=activity,
        correlation_id=correlation_id,
    )
    tenant_ref = _tenant_ref(activity)
    if email is None or not tenant_ref:
        await reply(
            "Your Teams account couldn't be linked to an LQ.AI account "
            "on this deployment. Ask your LQ.AI admin to create an "
            "account with your work email, then try again."
        )
        return

    api_url = f"{settings.lq_ai_backend_url.rstrip('/')}/api/v1/integrations/quick-ask"
    try:
        async with httpx.AsyncClient(timeout=QUICK_ASK_TIMEOUT_SECONDS) as client:
            res = await client.post(
                api_url,
                headers={"Authorization": f"Bearer {settings.lq_ai_bridge_token}"},
                json={
                    "platform": "teams",
                    "email": email,
                    "team_ref": tenant_ref,
                    "question": question,
                },
            )
    except httpx.HTTPError:
        log.exception("teams.commands.quick_ask_api_unreachable correlation=%s", correlation_id)
        await reply(f"Sorry — something went wrong reaching LQ.AI. (ref: {correlation_id})")
        return

    if res.status_code == 200:
        try:
            payload = res.json()
        except ValueError:
            payload = {}
        answer = str(payload.get("answer_text") or "").strip()
        chat_url = payload.get("chat_url")
        if not answer:
            log.warning("teams.commands.quick_ask_empty_answer correlation=%s", correlation_id)
            await reply(f"Sorry — LQ.AI returned no answer. (ref: {correlation_id})")
            return
        text = answer
        if isinstance(chat_url, str) and chat_url:
            text = f"{answer}\n\n[Continue this conversation in LQ.AI]({chat_url})"
        await reply(text)
        return

    if res.status_code == 404:
        await reply(
            "Your Teams account isn't linked to an LQ.AI account on "
            "this deployment. Ask your LQ.AI admin to create an "
            "account with your work email, then try again."
        )
        return

    if res.status_code == 403:
        await reply(
            "Your LQ.AI account isn't ready for use yet — sign in to "
            "the LQ.AI web app to finish setup, then try again."
        )
        return

    log.warning(
        "teams.commands.quick_ask_api_error status=%s correlation=%s body=%s",
        res.status_code,
        correlation_id,
        res.text[:200],
    )
    await reply(f"Sorry — something went wrong. (ref: {correlation_id})")


async def send_usage_reply(
    *,
    settings: Settings,
    activity: dict[str, Any],
    correlation_id: str,
) -> None:
    """Deferred worker: reply with the usage text (help / welcome)."""

    token = await _get_connector_token(settings, correlation_id)
    if token is None:
        return
    await _post_reply(
        token=token,
        service_url=str(activity.get("serviceUrl") or ""),
        activity=activity,
        text=USAGE_TEXT,
        correlation_id=correlation_id,
    )


def _is_welcome_update(activity: dict[str, Any]) -> bool:
    """True when a conversationUpdate added a non-bot member."""

    recipient = activity.get("recipient") or {}
    bot_id = str(recipient.get("id") or "")
    members_added = activity.get("membersAdded")
    if not isinstance(members_added, list):
        return False
    return any(
        isinstance(m, dict) and str(m.get("id") or "") not in ("", bot_id) for m in members_added
    )


@router.post("/messages")
async def teams_messages(
    request: Request,
    background: BackgroundTasks,
    settings: Annotated[Settings, Depends(get_settings)],
) -> JSONResponse:
    """Bot Framework messaging endpoint (ActivityHandler-shaped dispatch).

    Returns 200 promptly for every accepted activity; replies travel
    as separate authenticated Connector calls from background tasks.
    401 only when the ``Authorization`` bearer is absent (see the
    module-level inbound-auth limitation note).
    """

    authorization = request.headers.get("Authorization", "")
    if not authorization.startswith("Bearer ") or not authorization[len("Bearer ") :].strip():
        # Presence check only — NOT cryptographic validation (see the
        # module docstring). No detail about what was wrong.
        raise HTTPException(status_code=401, detail="unauthorized")

    try:
        activity = await request.json()
    except Exception:
        activity = None
    if not isinstance(activity, dict):
        log.warning("teams.commands.malformed_activity")
        return JSONResponse(content={})

    service_url = str(activity.get("serviceUrl") or "")
    activity_type = str(activity.get("type") or "")
    correlation_id = uuid.uuid4().hex[:8]

    if activity_type not in ("message", "conversationUpdate"):
        # on_unrecognized_activity_type: acknowledge and ignore.
        return JSONResponse(content={})

    if not service_url_allowed(service_url):
        # Forged or non-Teams origin — drop without any outbound call.
        log.warning(
            "teams.commands.service_url_rejected correlation=%s",
            correlation_id,
        )
        return JSONResponse(content={})

    if activity_type == "conversationUpdate":
        if _is_welcome_update(activity):
            background.add_task(
                send_usage_reply,
                settings=settings,
                activity=activity,
                correlation_id=correlation_id,
            )
        return JSONResponse(content={})

    parsed = parse_lq_text(str(activity.get("text") or ""))
    if parsed is None:
        # Not an /lq invocation — the bot only acts on explicit
        # invocations (PRD §3.15 posture: no silent listening).
        return JSONResponse(content={})

    if parsed.action == "help":
        background.add_task(
            send_usage_reply,
            settings=settings,
            activity=activity,
            correlation_id=correlation_id,
        )
        return JSONResponse(content={})

    log.info("teams.commands.ask_received correlation=%s", correlation_id)
    background.add_task(
        run_quick_ask,
        settings=settings,
        activity=activity,
        question=parsed.question,
        correlation_id=correlation_id,
    )
    return JSONResponse(content={})
