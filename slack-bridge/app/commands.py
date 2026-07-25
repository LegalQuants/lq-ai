"""``/lq`` slash-command surface — DE-288.

Slack POSTs an ``application/x-www-form-urlencoded`` payload to
``POST /slack/commands`` every time a user invokes ``/lq …`` in a
workspace where the LQ.AI Slack App is installed. This module:

1. **Verifies the request signature** via the existing
   :func:`app.signing.verify_slack_signature` primitive (v0 basestring
   HMAC, 5-minute window, constant-time compare). 401 on failure, with
   no detail about which check failed.
2. **Parses the command text** — HTML-entity unescape (Slack escapes
   ``&``/``<``/``>`` in ``text``), smart-quote normalization (clients
   curly-quote the user's ``"…"``), then a shlex split into a tiny
   subcommand table (``help`` / ``ask``). Parse failures and unknown
   subcommands render the ephemeral usage text — never an exception,
   never silence.
3. **Acks within Slack's 3-second window** — the handler returns an
   immediate ephemeral "working on it" body and defers the real work
   to a Starlette background task (runs after the response is flushed,
   so Slack sees the 200 first). The deferred task calls the LQ.AI
   api's bridge-bearer quick-ask endpoint and delivers exactly ONE
   final message through the payload's ``response_url`` (usable up to
   5 times within 30 minutes; we never stream chunks through it).

Error UX (fail-closed, per the DE-288 research memo):

* Unlinked user (api 404) → ephemeral "account isn't linked" refusal.
* Account-not-ready (api 403) → ephemeral "finish setting up your
  LQ.AI account in the web app" refusal.
* Anything else (api 5xx, timeout, network) → ephemeral generic
  failure with a correlation id; the internal detail goes to the
  bridge log only. Handled failures are always HTTP 200 + ephemeral
  message; non-200 is reserved for the signature check.

Identity note: the bridge sends only ``(team_id, slack_user_id)`` —
it holds no bot token (tokens land in the api's encrypted storage at
OAuth time), so the api resolves the Slack user to an email via
``users.info`` with the stored workspace token and maps the email to
an LQ.AI account itself. The bridge stays a dumb normalizer; all
authority decisions live behind the api.
"""

from __future__ import annotations

import html
import logging
import shlex
import uuid
from dataclasses import dataclass
from typing import Annotated
from urllib.parse import parse_qs

import httpx
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from fastapi.responses import JSONResponse

from .config import Settings, get_settings
from .signing import verify_slack_signature

log = logging.getLogger(__name__)

router = APIRouter(prefix="/slack", tags=["slack-commands"])

# How long the deferred worker waits for the api's quick-ask endpoint.
# The call spans a full LLM round-trip through the gateway, so this is
# deliberately generous; Slack's response_url stays valid for 30 min.
QUICK_ASK_TIMEOUT_SECONDS = 120.0

USAGE_TEXT = (
    "*LQ.AI quick-ask*\n"
    '• `/lq ask "<your question>"` — ask the configured quick-ask '
    "skill and get an answer here (only you see it).\n"
    "• `/lq help` — show this message."
)

# Smart quotes → ASCII quotes so shlex sees the pairing the user
# intended. U+2018/U+2019 (single) and U+201C/U+201D (double).
_SMART_QUOTE_MAP = {
    0x2018: "'",
    0x2019: "'",
    0x201C: '"',
    0x201D: '"',
}


@dataclass(frozen=True)
class ParsedCommand:
    """Outcome of parsing the ``/lq`` command text.

    ``action`` is ``"ask"`` or ``"help"``; ``question`` is non-empty
    exactly when ``action == "ask"``.
    """

    action: str
    question: str = ""


def normalize_command_text(text: str) -> str:
    """Undo Slack's transport-level rewrites of the command text.

    Slack HTML-escapes ``&``/``<``/``>`` in slash-command ``text`` and
    many clients substitute smart quotes for typed ASCII quotes. Both
    must be reversed before a shlex-style parse or quoted questions
    break in confusing ways.
    """

    return html.unescape(text).translate(_SMART_QUOTE_MAP)


def parse_command(text: str) -> ParsedCommand:
    """Parse the (already raw) ``/lq`` argument text.

    Grammar::

        /lq                → help
        /lq help           → help
        /lq ask <question> → ask   (question may be quoted or bare words)
        /lq <anything else>→ help  (unknown subcommand)

    A shlex failure (e.g. an unterminated quote) also falls back to
    help — a friendly usage reply, never a stack trace.
    """

    normalized = normalize_command_text(text).strip()
    if not normalized:
        return ParsedCommand(action="help")

    try:
        tokens = shlex.split(normalized)
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

    # "help" and every unknown subcommand render the same usage text.
    return ParsedCommand(action="help")


def _ephemeral(text: str) -> JSONResponse:
    """Build the immediate ephemeral response body Slack renders."""

    return JSONResponse(content={"response_type": "ephemeral", "text": text})


async def _post_response_url(response_url: str, text: str, correlation_id: str) -> None:
    """Deliver the single final ephemeral message via ``response_url``.

    A delivery failure is logged (with the correlation id) and
    swallowed — there is no further channel to report through.
    """

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            res = await client.post(
                response_url,
                json={"response_type": "ephemeral", "text": text},
            )
        if res.status_code != 200:
            log.warning(
                "slack.commands.response_url_rejected status=%s correlation=%s",
                res.status_code,
                correlation_id,
            )
    except httpx.HTTPError:
        log.exception("slack.commands.response_url_failed correlation=%s", correlation_id)


async def run_quick_ask(
    *,
    settings: Settings,
    question: str,
    slack_user_id: str,
    team_id: str,
    response_url: str,
    correlation_id: str,
) -> None:
    """Deferred worker: call the api's quick-ask endpoint, then deliver
    exactly one final message through ``response_url``.

    All failure paths converge on an ephemeral message — unlinked and
    not-ready refusals are specific; everything else is generic with a
    correlation id (the internal detail lives in the bridge log only).
    """

    api_url = f"{settings.lq_ai_backend_url.rstrip('/')}/api/v1/integrations/quick-ask"
    try:
        async with httpx.AsyncClient(timeout=QUICK_ASK_TIMEOUT_SECONDS) as client:
            res = await client.post(
                api_url,
                headers={"Authorization": f"Bearer {settings.lq_ai_bridge_token}"},
                json={
                    "platform": "slack",
                    "platform_user_id": slack_user_id,
                    "team_ref": team_id,
                    "question": question,
                },
            )
    except httpx.HTTPError:
        log.exception("slack.commands.quick_ask_api_unreachable correlation=%s", correlation_id)
        await _post_response_url(
            response_url,
            f"Sorry — something went wrong reaching LQ.AI. (ref: {correlation_id})",
            correlation_id,
        )
        return

    if res.status_code == 200:
        try:
            payload = res.json()
        except ValueError:
            payload = {}
        answer = str(payload.get("answer_text") or "").strip()
        chat_url = payload.get("chat_url")
        if not answer:
            log.warning(
                "slack.commands.quick_ask_empty_answer correlation=%s",
                correlation_id,
            )
            await _post_response_url(
                response_url,
                f"Sorry — LQ.AI returned no answer. (ref: {correlation_id})",
                correlation_id,
            )
            return
        text = answer
        if isinstance(chat_url, str) and chat_url:
            text = f"{answer}\n\n<{chat_url}|Continue this conversation in LQ.AI>"
        await _post_response_url(response_url, text, correlation_id)
        return

    if res.status_code == 404:
        # Fail-closed identity refusal: the api could not bind this
        # Slack user to an LQ.AI account. Never guess, never answer as
        # a shared identity.
        await _post_response_url(
            response_url,
            (
                "Your Slack account isn't linked to an LQ.AI account on "
                "this deployment. Ask your LQ.AI admin to create an "
                "account with the email on your Slack profile, then try "
                "again."
            ),
            correlation_id,
        )
        return

    if res.status_code == 403:
        await _post_response_url(
            response_url,
            (
                "Your LQ.AI account isn't ready for use yet — sign in to "
                "the LQ.AI web app to finish setup, then try again."
            ),
            correlation_id,
        )
        return

    log.warning(
        "slack.commands.quick_ask_api_error status=%s correlation=%s body=%s",
        res.status_code,
        correlation_id,
        res.text[:200],
    )
    await _post_response_url(
        response_url,
        f"Sorry — something went wrong. (ref: {correlation_id})",
        correlation_id,
    )


@router.post("/commands")
async def slack_commands(
    request: Request,
    background: BackgroundTasks,
    settings: Annotated[Settings, Depends(get_settings)],
) -> JSONResponse:
    """Handle a ``/lq`` slash-command invocation from Slack.

    Signature-verified against the raw body; 401 (with no detail about
    which check failed) on any verification failure. Every verified
    request is answered 200 with an ephemeral body — errors included —
    per Slack's slash-command error guidance.
    """

    body = await request.body()
    timestamp = request.headers.get("X-Slack-Request-Timestamp", "")
    signature = request.headers.get("X-Slack-Signature", "")
    if not verify_slack_signature(
        signing_secret=settings.slack_signing_secret,
        timestamp=timestamp,
        body=body,
        signature=signature,
    ):
        raise HTTPException(status_code=401, detail="invalid Slack signature")

    form = parse_qs(body.decode("utf-8", errors="replace"))
    text = (form.get("text") or [""])[0]
    slack_user_id = (form.get("user_id") or [""])[0]
    team_id = (form.get("team_id") or [""])[0]
    response_url = (form.get("response_url") or [""])[0]

    parsed = parse_command(text)
    if parsed.action == "help":
        return _ephemeral(USAGE_TEXT)

    # ``ask`` needs the identity + follow-up fields; a payload missing
    # them is malformed (Slack always sends them) — refuse gracefully.
    if not (slack_user_id and team_id and response_url):
        log.warning("slack.commands.malformed_payload team=%s", team_id or "?")
        return _ephemeral("Sorry — Slack sent an incomplete request. Please try again.")

    correlation_id = uuid.uuid4().hex[:8]
    log.info(
        "slack.commands.ask_received team=%s user=%s correlation=%s",
        team_id,
        slack_user_id,
        correlation_id,
    )

    # Deferred work runs AFTER this response is flushed (Starlette
    # background task) so Slack gets its 200 well inside the 3 s
    # window; the final answer arrives via response_url.
    background.add_task(
        run_quick_ask,
        settings=settings,
        question=parsed.question,
        slack_user_id=slack_user_id,
        team_id=team_id,
        response_url=response_url,
        correlation_id=correlation_id,
    )
    return _ephemeral("Working on it — I'll post the answer here shortly.")
