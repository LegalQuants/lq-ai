"""Microsoft OAuth admin-consent + callback handlers (M3-D3).

The flow:

1. **Operator initiates install** by clicking a button in the LQ.AI
   admin UI (M3-D4 work) which opens ``GET /teams/oauth/install`` on
   the bridge.
2. **Bridge redirects to Microsoft identity platform** with the Azure
   AD app's ``client_id``, the scopes the bridge declares (``openid``,
   ``profile``, ``email``, ``offline_access``, plus
   ``https://graph.microsoft.com/User.Read`` so the bridge can fetch
   the tenant display name from Graph), a randomly-generated ``state``
   token (CSRF), the redirect_uri pointing back at this bridge, and
   ``prompt=admin_consent`` so the tenant admin grants consent for
   the whole tenant in one flow.
3. **Admin consents in Microsoft**, Microsoft redirects to
   ``GET /teams/oauth/callback?code=...&state=...``.
4. **Bridge verifies the state**, exchanges the code for tokens via
   the multi-tenant ``/common/oauth2/v2.0/token`` endpoint, decodes
   the id_token's ``tid`` (tenant id) + ``oid`` (admin's object id)
   claims, optionally calls Microsoft Graph ``/organization`` to
   fetch the tenant display name, and POSTs the resulting tenant
   record to the LQ.AI api at
   ``POST /api/v1/integrations/teams/tenants``.
5. **Bridge returns a simple success page** so the operator sees
   confirmation in their browser.

Decision M3-D3-3 (raw httpx, no botbuilder SDK): both the token
exchange and the optional Graph display-name lookup are plain HTTP
calls. The official ``botbuilder-core`` SDK adds ~15 transitive deps
we don't need for plumbing.

Decision M3-D3-4 (multi-tenant): the authorize/token endpoints use
the ``/common/`` tenant placeholder so any Microsoft 365 tenant's
admin can install the app under the operator's single Azure AD
multi-tenant app registration.

State tokens live in-memory in the bridge with a 10-minute TTL.
Single-instance per deployment so an in-memory store is sufficient
(matches the slack-bridge posture; same DE candidate).
"""

from __future__ import annotations

import base64
import json
import logging
import secrets
import time
import uuid
from typing import Annotated, Any
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from .config import Settings, get_settings

log = logging.getLogger(__name__)

router = APIRouter(prefix="/teams", tags=["teams-oauth"])


_STATE_STORE: dict[str, float] = {}
_STATE_TTL_SECONDS = 600  # 10 minutes


def _gc_state_store() -> None:
    """Best-effort cleanup of expired state tokens."""

    now = time.time()
    expired = [k for k, ts in _STATE_STORE.items() if now - ts > _STATE_TTL_SECONDS]
    for k in expired:
        _STATE_STORE.pop(k, None)


# Scopes the bridge requests during admin consent. ``User.Read`` is the
# narrowest scope that returns an access_token usable against Microsoft
# Graph, which the bridge calls (best-effort) to fetch the tenant
# display name for the persisted record. ``offline_access`` keeps
# refresh-token plumbing alive for future M4 on-behalf-of flows.
SCOPES = [
    "openid",
    "profile",
    "email",
    "offline_access",
    "https://graph.microsoft.com/User.Read",
]


def _decode_id_token_unverified(id_token: str) -> dict[str, Any]:
    """Base64-decode the id_token payload without signature verification.

    Safe in this context because the token arrived over TLS from the
    Microsoft token endpoint via our client_secret-authenticated POST.
    The bridge doesn't grant any LQ.AI-side permissions based on
    these claims — they're only used to identify which tenant + admin
    completed the install.
    """

    try:
        _header, payload, _sig = id_token.split(".")
    except ValueError as exc:
        raise ValueError("id_token is not a JWT (expected three dot-separated segments)") from exc
    # JWT base64url has no padding; rfill with '='s before decode.
    pad = "=" * (-len(payload) % 4)
    decoded = base64.urlsafe_b64decode(payload + pad)
    parsed = json.loads(decoded)
    if not isinstance(parsed, dict):
        raise ValueError("id_token payload did not decode to a JSON object")
    return parsed


@router.get("/oauth/install")
async def oauth_install(
    settings: Annotated[Settings, Depends(get_settings)],
) -> RedirectResponse:
    """Redirect the operator to Microsoft's admin-consent page."""

    _gc_state_store()
    state = secrets.token_urlsafe(32)
    _STATE_STORE[state] = time.time()

    redirect_uri = f"{settings.lq_ai_teams_bridge_public_url.rstrip('/')}/teams/oauth/callback"
    params = {
        "client_id": settings.microsoft_app_id,
        "response_type": "code",
        "redirect_uri": redirect_uri,
        "response_mode": "query",
        "scope": " ".join(SCOPES),
        "state": state,
        "prompt": "admin_consent",
    }
    consent_url = (
        f"https://login.microsoftonline.com/common/oauth2/v2.0/authorize?{urlencode(params)}"
    )

    log.info("teams.oauth.install_started state=%s", state[:8])
    return RedirectResponse(url=consent_url, status_code=302)


@router.get("/oauth/callback")
async def oauth_callback(
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
    code: Annotated[str | None, Query(description="Authorization code from Microsoft.")] = None,
    state: Annotated[str | None, Query(description="Round-tripped state token (CSRF).")] = None,
    error: Annotated[str | None, Query()] = None,
    error_description: Annotated[str | None, Query()] = None,
) -> HTMLResponse:
    """Handle the Microsoft identity platform OAuth callback.

    Steps:

    1. If ``error`` is set, render the cancellation page (admin
       declined consent).
    2. Verify ``state`` matches a token we issued (single-use).
    3. POST to the multi-tenant token endpoint with
       ``grant_type=authorization_code`` to exchange ``code`` for an
       ``id_token`` + ``access_token`` + ``refresh_token``.
    4. Decode the id_token (no signature verify needed — TLS + our
       client_secret authenticated us to Microsoft).
    5. Best-effort: call Microsoft Graph ``/organization`` to fetch
       the tenant display name; falls back to ``tid`` if Graph errors.
    6. POST the tenant record to the LQ.AI api with the shared
       ``LQ_AI_BRIDGE_TOKEN`` bearer.
    """

    if error:
        log.warning("teams.oauth.user_denied error=%s description=%s", error, error_description)
        return HTMLResponse(
            f"<h1>Install cancelled</h1><p>Microsoft returned: {error!r}</p>"
            f"<p>{error_description or ''}</p>",
            status_code=400,
        )

    _gc_state_store()
    if state is None or _STATE_STORE.pop(state, None) is None:
        log.warning("teams.oauth.invalid_state state=%s", (state or "")[:8])
        raise HTTPException(
            status_code=400,
            detail=("invalid or expired state token — restart the install from the LQ.AI admin UI"),
        )

    if not code:
        log.warning("teams.oauth.missing_code")
        raise HTTPException(status_code=400, detail="missing authorization code from Microsoft")

    redirect_uri = f"{settings.lq_ai_teams_bridge_public_url.rstrip('/')}/teams/oauth/callback"

    token_url = "https://login.microsoftonline.com/common/oauth2/v2.0/token"
    token_body = {
        "client_id": settings.microsoft_app_id,
        "client_secret": settings.microsoft_app_password,
        "code": code,
        "grant_type": "authorization_code",
        "redirect_uri": redirect_uri,
        "scope": " ".join(SCOPES),
    }

    try:
        async with httpx.AsyncClient(timeout=10.0) as http:
            tok_res = await http.post(
                token_url,
                data=token_body,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
    except httpx.HTTPError as exc:
        log.exception("teams.oauth.token_endpoint_failed")
        return HTMLResponse(
            f"<h1>Install failed</h1><p>Token exchange failed: {exc!r}</p>",
            status_code=502,
        )

    if tok_res.status_code != 200:
        log.warning(
            "teams.oauth.token_endpoint_rejected status=%s body=%s",
            tok_res.status_code,
            tok_res.text[:300],
        )
        return HTMLResponse(
            f"<h1>Install failed</h1>"
            f"<p>Microsoft token endpoint returned HTTP {tok_res.status_code}.</p>"
            f"<pre>{tok_res.text[:500]}</pre>",
            status_code=502,
        )

    tok_payload = tok_res.json()
    id_token = tok_payload.get("id_token")
    access_token = tok_payload.get("access_token")
    if not id_token or not access_token:
        log.error("teams.oauth.malformed_token_response payload=%s", tok_payload)
        return HTMLResponse(
            "<h1>Install failed</h1><p>Microsoft response missing id_token or access_token.</p>",
            status_code=502,
        )

    try:
        claims = _decode_id_token_unverified(id_token)
    except ValueError as exc:
        log.error("teams.oauth.id_token_decode_failed error=%s", exc)
        return HTMLResponse(
            f"<h1>Install failed</h1><p>id_token decode failed: {exc!r}</p>",
            status_code=502,
        )

    tenant_id = claims.get("tid")
    installer_oid = claims.get("oid")
    if not tenant_id or not installer_oid:
        log.error("teams.oauth.id_token_missing_claims claims_keys=%s", list(claims.keys()))
        return HTMLResponse(
            "<h1>Install failed</h1><p>id_token did not carry the required tid + oid claims.</p>",
            status_code=502,
        )

    # Best-effort tenant display name via Microsoft Graph. Falls back
    # to the tenant id if Graph errors — we'd rather persist with a
    # placeholder name than fail the whole install on a Graph hiccup.
    tenant_name = await _fetch_tenant_display_name(access_token) or str(tenant_id)

    tenant_record = {
        "tenant_id": str(tenant_id),
        "tenant_name": tenant_name,
        "installer_oid": str(installer_oid),
    }

    try:
        async with httpx.AsyncClient(timeout=10.0) as http:
            persist_res = await http.post(
                f"{settings.lq_ai_backend_url.rstrip('/')}/api/v1/integrations/teams/tenants",
                headers={"Authorization": f"Bearer {settings.lq_ai_bridge_token}"},
                json=tenant_record,
            )
    except httpx.HTTPError as exc:
        log.exception("teams.oauth.api_persist_failed")
        return HTMLResponse(
            f"<h1>Install failed</h1><p>Could not persist to the LQ.AI backend: {exc!r}</p>",
            status_code=502,
        )

    if persist_res.status_code not in (200, 201, 204):
        log.warning(
            "teams.oauth.api_persist_rejected status=%s body=%s",
            persist_res.status_code,
            persist_res.text[:200],
        )
        return HTMLResponse(
            f"<h1>Install failed</h1><p>Backend rejected with HTTP {persist_res.status_code}.</p>",
            status_code=502,
        )

    log.info(
        "teams.oauth.install_completed tenant_id=%s installer_oid=%s",
        tenant_id,
        installer_oid,
    )

    correlation = uuid.uuid4().hex[:8]
    body_style = "font-family: system-ui; max-width: 32rem; margin: 4rem auto; line-height: 1.5;"
    connected_line = (
        f"<p>Microsoft 365 tenant <strong>{tenant_name}</strong> "
        f"is now connected to this LQ.AI deployment.</p>"
    )
    next_step_line = (
        "<p>Next step: upload the Teams app manifest "
        "(see <code>teams-bridge/manifest.json</code>) to your Teams "
        "Admin Center, then open the LQ.AI admin UI to bind Teams "
        "users to LQ.AI accounts (M3-D4).</p>"
    )
    return HTMLResponse(
        content=f"""
        <!doctype html>
        <html lang="en">
        <head><meta charset="utf-8"><title>LQ.AI Teams install complete</title></head>
        <body style="{body_style}">
          <h1>Install complete</h1>
          {connected_line}
          {next_step_line}
          <p style="color: #888; font-size: 0.875rem;">Correlation: <code>{correlation}</code></p>
        </body>
        </html>
        """,
        status_code=200,
    )


async def _fetch_tenant_display_name(access_token: str) -> str | None:
    """Best-effort Microsoft Graph lookup for the tenant displayName.

    Returns ``None`` on any failure path — the caller falls back to
    the tenant id rather than failing the whole install.
    """

    try:
        async with httpx.AsyncClient(timeout=5.0) as http:
            res = await http.get(
                "https://graph.microsoft.com/v1.0/organization",
                headers={"Authorization": f"Bearer {access_token}"},
            )
    except httpx.HTTPError as exc:
        log.info("teams.oauth.graph_org_lookup_failed error=%s", exc)
        return None

    if res.status_code != 200:
        log.info(
            "teams.oauth.graph_org_lookup_rejected status=%s body=%s",
            res.status_code,
            res.text[:200],
        )
        return None

    try:
        body = res.json()
        orgs = body.get("value") or []
        if orgs and isinstance(orgs, list):
            name = orgs[0].get("displayName")
            if isinstance(name, str) and name.strip():
                return name.strip()
    except (ValueError, KeyError, TypeError):
        return None
    return None
