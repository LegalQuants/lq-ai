"""Slack OAuth install + callback handlers (M3-D1).

The flow:

1. **Operator initiates install** by clicking a button in the LQ.AI
   admin UI (M3-D4 work) which opens ``GET /slack/oauth/install``
   on the bridge.
2. **Bridge redirects to Slack** with the App's client_id, the
   scopes the bridge declares (``commands``, ``chat:write``), a
   randomly-generated ``state`` token (CSRF), and the redirect_uri
   pointing back at this bridge.
3. **User consents in Slack**, Slack redirects to
   ``GET /slack/oauth/callback?code=...&state=...``.
4. **Bridge verifies the state**, exchanges the code for a bot
   token via ``oauth.v2.access``, and POSTs the resulting workspace
   record to the LQ.AI api at
   ``POST /api/v1/integrations/slack/workspaces``.
5. **Bridge returns a simple success page** so the operator sees
   confirmation in the browser they were redirected back to. (A
   future polish PR can return a richer page or redirect back into
   the LQ.AI admin UI.)

State tokens live in-memory in the bridge with a 10-minute TTL. The
bridge is single-instance per deployment so an in-memory store is
sufficient; if the bridge restarts between install initiation and
callback, the operator restarts the install. (DE candidate: persist
state tokens in the api so install survives bridge restarts. Filing
implicit — surfaces if an operator hits this.)
"""

from __future__ import annotations

import html
import logging
import re
import secrets
import time
import uuid
from collections.abc import Sequence
from typing import Annotated, Final
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import HTMLResponse, RedirectResponse

from .config import Settings, get_settings

log = logging.getLogger(__name__)

router = APIRouter(prefix="/slack", tags=["slack-oauth"])


# In-memory state token store. Keys are the random state tokens; values
# are creation timestamps. A token is consumed (deleted) on first read
# in the callback handler — replay protection.
_STATE_STORE: dict[str, float] = {}
_STATE_TTL_SECONDS = 600  # 10 minutes


def _gc_state_store() -> None:
    """Best-effort cleanup of expired state tokens.

    Called inside the install + callback handlers; keeps the store
    bounded without needing a background task. The store is small
    (one entry per concurrent install flow, which is typically zero
    or one in a given 10-minute window).
    """

    now = time.time()
    expired = [k for k, ts in _STATE_STORE.items() if now - ts > _STATE_TTL_SECONDS]
    for k in expired:
        _STATE_STORE.pop(k, None)


# Scopes the bridge requests during OAuth install. Kept narrow on
# purpose: ``commands`` for the future slash-command surface and
# ``chat:write`` so the bot can post replies in channels it's invited
# to. No ``channels:read`` / ``groups:read`` / ``im:read`` — the bot
# does NOT read silent channels.
SCOPES = ["commands", "chat:write"]


# ---------------------------------------------------------------------------
# HTML rendering
# ---------------------------------------------------------------------------
#
# Every page the bridge serves goes through :func:`_page`, so that (a) every
# dynamic value is HTML-escaped by construction — callers pass plain text,
# never markup, and there is no way to opt out — and (b) every response
# carries a Content-Security-Policy that forbids script execution outright.
# The bridge's HTML surface is a handful of static status pages; nothing on
# them needs JavaScript.
#
# Detail that helps an operator debug a failed install (exception reprs,
# upstream response bodies, provider error strings) goes to the server log
# keyed by a short correlation id that IS rendered, rather than being
# reflected into the page. Reflecting provider- and attacker-controlled
# strings into these pages was the vector for the reflected-XSS report on
# the OAuth callbacks (2026-08); see the regression tests in
# ``tests/test_oauth.py``.

_CONTENT_SECURITY_POLICY: Final[str] = (
    "default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; "
    "form-action 'none'; frame-ancestors 'none'"
)
# ``style-src 'unsafe-inline'`` keeps the two inline ``style=`` attributes
# working (a hash source does not cover style *attributes*); scripts of any
# origin, including inline, are blocked by ``default-src 'none'``.
_PAGE_HEADERS: Final[dict[str, str]] = {
    "Content-Security-Policy": _CONTENT_SECURITY_POLICY,
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "Cache-Control": "no-store",
}
_BODY_STYLE: Final[str] = (
    "font-family: system-ui; max-width: 32rem; margin: 4rem auto; line-height: 1.5;"
)

# RFC 6749 §4.1.2.1-shaped error codes (``access_denied``, ``invalid_code``).
# A provider error string is rendered only when it matches this; anything
# else is logged and shown as ``unknown``.
_ERROR_CODE_RE: Final[re.Pattern[str]] = re.compile(r"[A-Za-z0-9_.-]{1,64}")

_LOG_MAX_CHARS: Final[int] = 200


def _page(
    title: str,
    lines: Sequence[str],
    *,
    status_code: int,
    correlation: str,
) -> HTMLResponse:
    """Render a status page from **plain-text** strings.

    ``title`` and every entry in ``lines`` are passed through
    :func:`html.escape` (quotes included) before they touch the response
    body. Do not pass markup — it will be shown literally.
    """

    paragraphs = "".join(f"<p>{html.escape(line)}</p>" for line in lines)
    body = (
        "<!doctype html>"
        '<html lang="en"><head><meta charset="utf-8">'
        f"<title>LQ.AI Slack bridge — {html.escape(title)}</title></head>"
        f'<body style="{_BODY_STYLE}">'
        f"<h1>{html.escape(title)}</h1>{paragraphs}"
        '<p style="color: #888; font-size: 0.875rem;">Correlation: '
        f"<code>{html.escape(correlation)}</code></p>"
        "</body></html>"
    )
    return HTMLResponse(body, status_code=status_code, headers=dict(_PAGE_HEADERS))


def _log_safe(value: object) -> str:
    """Bound and ``repr`` a caller- or upstream-controlled value for a log line."""

    return repr(str(value)[:_LOG_MAX_CHARS])


def _shown_error_code(value: object) -> str:
    """Return a provider error code if it is token-shaped, else ``"unknown"``."""

    text = str(value)
    return text if _ERROR_CODE_RE.fullmatch(text) else "unknown"


@router.get("/oauth/install")
async def oauth_install(
    settings: Annotated[Settings, Depends(get_settings)],
) -> RedirectResponse:
    """Redirect the operator to Slack's OAuth consent screen.

    Generates a fresh state token (CSRF), stores it in the bridge's
    in-memory store, and builds the consent URL. Slack will redirect
    the operator back to ``/slack/oauth/callback`` after they consent.
    """

    _gc_state_store()
    state = secrets.token_urlsafe(32)
    _STATE_STORE[state] = time.time()

    redirect_uri = f"{settings.lq_ai_bridge_public_url.rstrip('/')}/slack/oauth/callback"
    params = {
        "client_id": settings.slack_client_id,
        "scope": ",".join(SCOPES),
        "redirect_uri": redirect_uri,
        "state": state,
    }
    consent_url = f"https://slack.com/oauth/v2/authorize?{urlencode(params)}"

    log.info("slack.oauth.install_started state=%s", state[:8])
    return RedirectResponse(url=consent_url, status_code=302)


@router.get("/oauth/callback")
async def oauth_callback(
    settings: Annotated[Settings, Depends(get_settings)],
    code: Annotated[str | None, Query(description="Authorization code from Slack.")] = None,
    state: Annotated[str | None, Query(description="Round-tripped state token (CSRF).")] = None,
    error: Annotated[str | None, Query(description="Error code when the user declined.")] = None,
) -> HTMLResponse:
    """Handle the Slack OAuth callback.

    Steps:

    1. Verify the ``state`` matches a token we issued (and delete it
       — single-use). **This runs first**, before the user-declined
       branch, so no unauthenticated caller can reach a page-rendering
       branch. RFC 6749 §4.1.2.1 requires the provider to round-trip
       ``state`` on error redirects too, so a genuine cancellation
       should still carry a valid token; this has not been observed
       against a live Slack install (DE-312). If Slack ever omits it,
       the cancellation lands on the JSON 400 below — nothing is
       rendered from the request either way.
    2. If ``error`` is set, render the static cancellation page. The
       provider's error string is logged, not rendered.
    3. Exchange the ``code`` for a bot token via Slack's
       ``oauth.v2.access`` endpoint. ``code`` is optional at the schema
       level only because a cancellation redirect carries none; a
       missing code on the success path is a 400.
    4. POST the resulting workspace record (team_id, team_name,
       bot_token, installer_user_id) to the LQ.AI api at
       ``/api/v1/integrations/slack/workspaces`` carrying
       ``LQ_AI_BRIDGE_TOKEN`` as a bearer.
    5. Return a simple HTML success page.

    Any failure path returns an HTML error page rather than raising —
    the operator is in a browser, not curl. Every page is static text
    plus a correlation id; the detail behind a failure is in the bridge
    log under that id (see :func:`_page`).
    """

    correlation = uuid.uuid4().hex[:8]

    _gc_state_store()
    if state is None or _STATE_STORE.pop(state, None) is None:
        log.warning(
            "slack.oauth.invalid_state state=%s correlation=%s", (state or "")[:8], correlation
        )
        raise HTTPException(
            status_code=400,
            detail=("invalid or expired state token — restart the install from the LQ.AI admin UI"),
        )

    if error:
        log.warning(
            "slack.oauth.user_denied correlation=%s error=%s", correlation, _log_safe(error)
        )
        return _page(
            "Install cancelled",
            [
                "Slack did not complete the install — the request was declined, or Slack "
                "reported an error.",
                "No changes were made to this LQ.AI deployment. Restart the install from the "
                "LQ.AI admin UI to try again.",
            ],
            status_code=400,
            correlation=correlation,
        )

    if not code:
        log.warning("slack.oauth.missing_code correlation=%s", correlation)
        raise HTTPException(status_code=400, detail="missing authorization code from Slack")

    redirect_uri = f"{settings.lq_ai_bridge_public_url.rstrip('/')}/slack/oauth/callback"

    # Lazy import slack_sdk to keep the import-cost off the bridge's
    # hot path. The SDK pulls a few transitive deps.
    from slack_sdk.web.async_client import AsyncWebClient

    client = AsyncWebClient()
    try:
        token_response = await client.oauth_v2_access(
            client_id=settings.slack_client_id,
            client_secret=settings.slack_client_secret,
            code=code,
            redirect_uri=redirect_uri,
        )
    except Exception:
        log.exception("slack.oauth.exchange_failed correlation=%s", correlation)
        return _page(
            "Install failed",
            [
                "The token exchange with Slack failed.",
                "Check the bridge log for the correlation id below.",
            ],
            status_code=502,
            correlation=correlation,
        )

    if not token_response.get("ok"):
        slack_error = token_response.get("error", "unknown")
        log.warning(
            "slack.oauth.exchange_not_ok correlation=%s error=%s",
            correlation,
            _log_safe(slack_error),
        )
        return _page(
            "Install failed",
            [
                f"Slack rejected the token exchange (error code: {_shown_error_code(slack_error)}).",
                "Restart the install from the LQ.AI admin UI to try again.",
            ],
            status_code=502,
            correlation=correlation,
        )

    team = token_response.get("team") or {}
    authed_user = token_response.get("authed_user") or {}
    workspace = {
        "team_id": team.get("id"),
        "team_name": team.get("name"),
        "bot_token": token_response.get("access_token"),
        "bot_user_id": token_response.get("bot_user_id"),
        "installer_slack_user_id": authed_user.get("id"),
        "scope": token_response.get("scope"),
    }

    if not workspace["team_id"] or not workspace["bot_token"]:
        log.error(
            "slack.oauth.malformed_response correlation=%s payload=%s",
            correlation,
            _log_safe(token_response.data),
        )
        return _page(
            "Install failed",
            ["Slack's response was missing required fields."],
            status_code=502,
            correlation=correlation,
        )

    # POST the workspace record to the lq-ai api for encrypted persistence.
    try:
        async with httpx.AsyncClient(timeout=10.0) as http:
            res = await http.post(
                f"{settings.lq_ai_backend_url.rstrip('/')}/api/v1/integrations/slack/workspaces",
                headers={"Authorization": f"Bearer {settings.lq_ai_bridge_token}"},
                json=workspace,
            )
    except httpx.HTTPError:
        log.exception("slack.oauth.api_persist_failed correlation=%s", correlation)
        return _page(
            "Install failed",
            [
                "Could not persist the workspace record to the LQ.AI backend.",
                "Check that the api is reachable from the bridge, then retry the install.",
            ],
            status_code=502,
            correlation=correlation,
        )

    if res.status_code not in (200, 201, 204):
        log.warning(
            "slack.oauth.api_persist_rejected correlation=%s status=%s body=%s",
            correlation,
            res.status_code,
            _log_safe(res.text),
        )
        return _page(
            "Install failed",
            [f"Backend rejected with HTTP {res.status_code}."],
            status_code=502,
            correlation=correlation,
        )

    workspace_id = workspace["team_id"]
    log.info(
        "slack.oauth.install_completed correlation=%s team_id=%s installer=%s",
        correlation,
        workspace_id,
        workspace["installer_slack_user_id"],
    )

    team_name = str(workspace["team_name"] or workspace_id)
    return _page(
        "Install complete",
        [
            f'Slack workspace "{team_name}" is now connected to this LQ.AI deployment.',
            "Next step: open the LQ.AI admin UI to configure bot behavior (M3-D4) and bind "
            "Slack users to LQ.AI accounts.",
        ],
        status_code=200,
        correlation=correlation,
    )
