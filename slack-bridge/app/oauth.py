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

import logging
import secrets
import time
import uuid
from typing import Annotated
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Request
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
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
    code: Annotated[str, Query(description="Authorization code from Slack.")],
    state: Annotated[str, Query(description="Round-tripped state token (CSRF).")],
    error: Annotated[str | None, Query()] = None,
) -> HTMLResponse:
    """Handle the Slack OAuth callback.

    Steps:

    1. Verify the ``state`` matches a token we issued (and delete it
       — single-use).
    2. Exchange the ``code`` for a bot token via Slack's
       ``oauth.v2.access`` endpoint.
    3. POST the resulting workspace record (team_id, team_name,
       bot_token, installer_user_id) to the LQ.AI api at
       ``/api/v1/integrations/slack/workspaces`` carrying
       ``LQ_AI_BRIDGE_TOKEN`` as a bearer.
    4. Return a simple HTML success page.

    Any failure path returns an HTML error page rather than raising —
    the operator is in a browser, not curl. The api-side persistence
    failure is the most likely source of trouble (api down, token
    encryption misconfigured); the error page surfaces the failure
    plainly.
    """

    if error:
        log.warning("slack.oauth.user_denied error=%s", error)
        return HTMLResponse(
            f"<h1>Install cancelled</h1><p>Slack returned: {error!r}</p>",
            status_code=400,
        )

    _gc_state_store()
    if _STATE_STORE.pop(state, None) is None:
        log.warning("slack.oauth.invalid_state state=%s", state[:8])
        raise HTTPException(
            status_code=400,
            detail=("invalid or expired state token — restart the install from the LQ.AI admin UI"),
        )

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
    except Exception as exc:
        log.exception("slack.oauth.exchange_failed")
        return HTMLResponse(
            f"<h1>Install failed</h1><p>Token exchange failed: {exc!r}</p>",
            status_code=502,
        )

    if not token_response.get("ok"):
        slack_error = token_response.get("error", "unknown")
        log.warning("slack.oauth.exchange_not_ok error=%s", slack_error)
        return HTMLResponse(
            f"<h1>Install failed</h1><p>Slack returned: {slack_error}</p>",
            status_code=502,
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
        log.error("slack.oauth.malformed_response payload=%s", token_response.data)
        return HTMLResponse(
            "<h1>Install failed</h1><p>Slack response missing required fields.</p>",
            status_code=502,
        )

    # POST the workspace record to the lq-ai api for encrypted persistence.
    try:
        async with httpx.AsyncClient(timeout=10.0) as http:
            res = await http.post(
                f"{settings.lq_ai_backend_url.rstrip('/')}/api/v1/integrations/slack/workspaces",
                headers={"Authorization": f"Bearer {settings.lq_ai_bridge_token}"},
                json=workspace,
            )
    except httpx.HTTPError as exc:
        log.exception("slack.oauth.api_persist_failed")
        return HTMLResponse(
            f"<h1>Install failed</h1><p>Could not persist to the LQ.AI backend: {exc!r}</p>",
            status_code=502,
        )

    if res.status_code not in (200, 201, 204):
        log.warning(
            "slack.oauth.api_persist_rejected status=%s body=%s",
            res.status_code,
            res.text[:200],
        )
        return HTMLResponse(
            f"<h1>Install failed</h1><p>Backend rejected with HTTP {res.status_code}.</p>",
            status_code=502,
        )

    workspace_id = workspace["team_id"]
    log.info(
        "slack.oauth.install_completed team_id=%s installer=%s",
        workspace_id,
        workspace["installer_slack_user_id"],
    )

    # Best-effort: include a correlation id for the operator to
    # reference if they file a support ticket.
    correlation = uuid.uuid4().hex[:8]
    return HTMLResponse(
        content=f"""
        <!doctype html>
        <html lang="en">
        <head><meta charset="utf-8"><title>LQ.AI Slack install complete</title></head>
        <body style="font-family: system-ui; max-width: 32rem; margin: 4rem auto; line-height: 1.5;">
          <h1>Install complete</h1>
          <p>Slack workspace <strong>{workspace["team_name"]}</strong> is now connected to this LQ.AI deployment.</p>
          <p>Next step: open the LQ.AI admin UI to configure bot behavior (M3-D4) and bind Slack users to LQ.AI accounts.</p>
          <p style="color: #888; font-size: 0.875rem;">Correlation: <code>{correlation}</code></p>
        </body>
        </html>
        """,
        status_code=200,
    )
