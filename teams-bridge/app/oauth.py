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
import html
import json
import logging
import re
import secrets
import time
import uuid
from collections.abc import Sequence
from typing import Annotated, Any, Final
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
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

# RFC 6749 §4.1.2.1-shaped error codes (``access_denied``, ``invalid_grant``).
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
        f"<title>LQ.AI Teams bridge — {html.escape(title)}</title></head>"
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
    settings: Annotated[Settings, Depends(get_settings)],
    code: Annotated[str | None, Query(description="Authorization code from Microsoft.")] = None,
    state: Annotated[str | None, Query(description="Round-tripped state token (CSRF).")] = None,
    error: Annotated[str | None, Query(description="Error code when consent was declined.")] = None,
    error_description: Annotated[str | None, Query()] = None,
) -> HTMLResponse:
    """Handle the Microsoft identity platform OAuth callback.

    Steps:

    1. Verify ``state`` matches a token we issued (single-use). **This
       runs first**, before the declined-consent branch, so no
       unauthenticated caller can reach a page-rendering branch.
       RFC 6749 §4.1.2.1 requires the provider to round-trip ``state``
       on error redirects too, so a genuine cancellation should still
       carry a valid token; this has not been observed against a live
       Microsoft install (DE-312). If it is ever omitted, the
       cancellation lands on the JSON 400 below — nothing is rendered
       from the request either way.
    2. If ``error`` is set, render the static cancellation page. The
       provider's ``error`` / ``error_description`` are logged, not
       rendered.
    3. POST to the multi-tenant token endpoint with
       ``grant_type=authorization_code`` to exchange ``code`` for an
       ``id_token`` + ``access_token`` + ``refresh_token``.
    4. Decode the id_token (no signature verify needed — TLS + our
       client_secret authenticated us to Microsoft).
    5. Best-effort: call Microsoft Graph ``/organization`` to fetch
       the tenant display name; falls back to ``tid`` if Graph errors.
    6. POST the tenant record to the LQ.AI api with the shared
       ``LQ_AI_BRIDGE_TOKEN`` bearer.

    Every page is static text plus a correlation id; the detail behind a
    failure is in the bridge log under that id (see :func:`_page`).
    """

    correlation = uuid.uuid4().hex[:8]

    _gc_state_store()
    if state is None or _STATE_STORE.pop(state, None) is None:
        log.warning(
            "teams.oauth.invalid_state state=%s correlation=%s", (state or "")[:8], correlation
        )
        raise HTTPException(
            status_code=400,
            detail=("invalid or expired state token — restart the install from the LQ.AI admin UI"),
        )

    if error:
        log.warning(
            "teams.oauth.user_denied correlation=%s error=%s description=%s",
            correlation,
            _log_safe(error),
            _log_safe(error_description or ""),
        )
        return _page(
            "Install cancelled",
            [
                "Microsoft did not complete the install — consent was declined, or Microsoft "
                "reported an error.",
                "No changes were made to this LQ.AI deployment. Restart the install from the "
                "LQ.AI admin UI to try again.",
            ],
            status_code=400,
            correlation=correlation,
        )

    if not code:
        log.warning("teams.oauth.missing_code correlation=%s", correlation)
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
    except httpx.HTTPError:
        log.exception("teams.oauth.token_endpoint_failed correlation=%s", correlation)
        return _page(
            "Install failed",
            [
                "The token exchange with Microsoft failed.",
                "Check the bridge log for the correlation id below.",
            ],
            status_code=502,
            correlation=correlation,
        )

    if tok_res.status_code != 200:
        log.warning(
            "teams.oauth.token_endpoint_rejected correlation=%s status=%s body=%s",
            correlation,
            tok_res.status_code,
            _log_safe(tok_res.text),
        )
        # Surface the RFC 6749 error code if the body carries one; the
        # body itself is never rendered.
        try:
            rejected = tok_res.json()
        except ValueError:
            rejected = None
        error_code = rejected.get("error") if isinstance(rejected, dict) else None
        return _page(
            "Install failed",
            [
                f"Microsoft token endpoint returned HTTP {tok_res.status_code} "
                f"(error code: {_shown_error_code(error_code or 'unknown')}).",
                "Restart the install from the LQ.AI admin UI to try again.",
            ],
            status_code=502,
            correlation=correlation,
        )

    tok_payload = tok_res.json()
    id_token = tok_payload.get("id_token")
    access_token = tok_payload.get("access_token")
    if not id_token or not access_token:
        log.error(
            "teams.oauth.malformed_token_response correlation=%s payload_keys=%s",
            correlation,
            sorted(tok_payload) if isinstance(tok_payload, dict) else type(tok_payload).__name__,
        )
        return _page(
            "Install failed",
            ["Microsoft's response was missing the id_token or access_token."],
            status_code=502,
            correlation=correlation,
        )

    try:
        claims = _decode_id_token_unverified(id_token)
    except ValueError as exc:
        log.error("teams.oauth.id_token_decode_failed correlation=%s error=%s", correlation, exc)
        return _page(
            "Install failed",
            ["The id_token from Microsoft could not be decoded."],
            status_code=502,
            correlation=correlation,
        )

    tenant_id = claims.get("tid")
    installer_oid = claims.get("oid")
    if not tenant_id or not installer_oid:
        log.error(
            "teams.oauth.id_token_missing_claims correlation=%s claims_keys=%s",
            correlation,
            list(claims.keys()),
        )
        return _page(
            "Install failed",
            ["The id_token did not carry the required tid + oid claims."],
            status_code=502,
            correlation=correlation,
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
    except httpx.HTTPError:
        log.exception("teams.oauth.api_persist_failed correlation=%s", correlation)
        return _page(
            "Install failed",
            [
                "Could not persist the tenant record to the LQ.AI backend.",
                "Check that the api is reachable from the bridge, then retry the install.",
            ],
            status_code=502,
            correlation=correlation,
        )

    if persist_res.status_code not in (200, 201, 204):
        log.warning(
            "teams.oauth.api_persist_rejected correlation=%s status=%s body=%s",
            correlation,
            persist_res.status_code,
            _log_safe(persist_res.text),
        )
        return _page(
            "Install failed",
            [f"Backend rejected with HTTP {persist_res.status_code}."],
            status_code=502,
            correlation=correlation,
        )

    log.info(
        "teams.oauth.install_completed correlation=%s tenant_id=%s installer_oid=%s",
        correlation,
        tenant_id,
        installer_oid,
    )

    return _page(
        "Install complete",
        [
            f'Microsoft 365 tenant "{tenant_name}" is now connected to this LQ.AI deployment.',
            "Next step: upload the Teams app manifest (see teams-bridge/manifest.json) to your "
            "Teams Admin Center, then open the LQ.AI admin UI to bind Teams users to LQ.AI "
            "accounts (M3-D4).",
        ],
        status_code=200,
        correlation=correlation,
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
