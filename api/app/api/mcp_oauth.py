"""/api/v1/mcp/oauth — per-user MCP OAuth authorize / callback / status / disconnect.

PR4c Task 5.  Four routes expose the OAuth service (app.mcp.oauth) over REST.

Auth posture (LOCKED, decided 2026-06-18 — do NOT re-litigate):
  * GET /mcp/oauth/{server}/authorize   — ActiveUser (bearer).  302 redirect.
  * GET /mcp/oauth/{server}/callback    — PUBLIC.  The user arrives from the AS
    redirect; no bearer header is possible.  The user is recovered from the
    single-use, TTL'd mcp_oauth_state row inside exchange_code — the ``state``
    parameter IS the binding.
  * GET /mcp/oauth/{server}/status      — ActiveUser (bearer).  200 JSON.
  * DELETE /mcp/oauth/{server}          — ActiveUser (bearer).  204 no body.

The router is registered WITHOUT a router-level dependency so the callback
stays public.  The three authenticated handlers take ActiveUser explicitly.

PR4d: ``/authorize`` accepts an optional ``return_url`` (validated against
``lq_ai_cors_origins``; stored server-side on the state row).  After callback
the browser is 302-redirected to ``{return_url}?mcp_connected={server}`` on
success, or ``{return_url}?mcp_error={code}&server={server}`` on an exchange
error.  When no ``return_url`` was supplied the callback returns 200 JSON
(back-compat).  The callback NEVER reads a redirect target from its own query
string — origin-validated, state-bound only.
"""

from __future__ import annotations

from typing import Annotated
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Request, Response, status
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import ActiveUser
from app.audit import audit_action
from app.config import get_settings, is_allowed_return_url
from app.db.session import get_db
from app.errors import (
    MCPOAuthExchangeError,
    MCPOAuthNotConfigured,
    MCPOAuthStateError,
    ValidationError,
)
from app.mcp import oauth
from app.schemas.mcp_oauth import MCPOAuthCallbackResponse, MCPOAuthStatusResponse

router = APIRouter(prefix="/mcp/oauth", tags=["mcp-oauth"])


@router.get("/{server}/authorize", status_code=status.HTTP_302_FOUND)
async def authorize_mcp_oauth(
    server: str,
    user: ActiveUser,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    return_url: str | None = None,
) -> RedirectResponse:
    """GET /api/v1/mcp/oauth/{server}/authorize — start the OAuth flow.

    Builds the PKCE authorize URL for *server* and redirects the user's browser
    to the authorization server.  Audit happens on successful callback, not here.

    ``return_url`` (optional) is an operator-allowlisted frontend URL.  When
    supplied, the callback 302-redirects the browser back to that URL on
    completion (success or exchange error).  The origin of *return_url* MUST be
    in ``lq_ai_cors_origins``; unrecognised origins are rejected with 400 (no
    open redirect).
    """
    if return_url is not None and not is_allowed_return_url(return_url, get_settings()):
        raise ValidationError(
            message="return_url origin not allowed",
            details={"return_url": return_url},
        )

    redirect_uri = str(request.url_for("mcp_oauth_callback", server=server))
    url = await oauth.build_authorize_url(
        db,
        user_id=user.id,
        server=server,
        redirect_uri=redirect_uri,
        return_url=return_url,
    )
    return RedirectResponse(url, status_code=status.HTTP_302_FOUND)


@router.get(
    "/{server}/callback",
    response_model=None,
    name="mcp_oauth_callback",
    responses={
        200: {"model": MCPOAuthCallbackResponse, "description": "Token exchanged (no return_url)"},
        302: {"description": "Browser redirected to return_url (return_url was supplied)"},
    },
)
async def mcp_oauth_callback(
    server: str,
    code: str,
    state: str,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    iss: str | None = None,
) -> MCPOAuthCallbackResponse | RedirectResponse:
    """GET /api/v1/mcp/oauth/{server}/callback — receive the AS redirect.

    PUBLIC — no bearer auth.  The user is bound to the exchange via the
    single-use, TTL-bounded mcp_oauth_state row inside exchange_code.

    When a ``return_url`` was stored on the state row (set at authorize-time):
    * Success → 302 to ``{return_url}?mcp_connected={server}``
    * Exchange error → 302 to ``{return_url}?mcp_error={code}&server={server}``

    When no ``return_url`` was stored (back-compat):
    * Success → 200 ``MCPOAuthCallbackResponse``
    * Exchange error → raises the exception (existing JSON-error behaviour)

    The callback NEVER reads a redirect target from its own query string.  The
    only trusted ``return_url`` is the one read from the state row (validated
    + stored at authorize-time).  If the state row is unknown, ``return_url``
    is None and we fall back to JSON error (fail safe — no trusted target).
    """
    # Peek at return_url BEFORE consuming the state row.  get_state_return_url
    # is a read-only select; exchange_code does the consume (single-use delete).
    return_url = await oauth.get_state_return_url(db, state=state)

    try:
        token = await oauth.exchange_code(db, state=state, code=code, iss=iss)
    except (MCPOAuthStateError, MCPOAuthExchangeError, MCPOAuthNotConfigured) as exc:
        if return_url is not None:
            # Redirect to frontend with a non-secret error slug; never include
            # the code, state, verifier, or any token value in the redirect.
            qs = urlencode({"mcp_error": exc.effective_code, "server": server})
            return RedirectResponse(
                f"{return_url}?{qs}",
                status_code=status.HTTP_302_FOUND,
            )
        raise  # back-compat: re-raise → global handler returns JSON error

    await audit_action(
        db,
        user_id=token.user_id,
        action="mcp.oauth_connected",
        resource_type="mcp_server",
        resource_id=server,
        request=request,
        details={"scope_count": len(token.scopes)},
    )
    await db.commit()

    if return_url is not None:
        qs = urlencode({"mcp_connected": server})
        return RedirectResponse(
            f"{return_url}?{qs}",
            status_code=status.HTTP_302_FOUND,
        )

    return MCPOAuthCallbackResponse(
        connected=True,
        server=server,
        scopes=token.scopes,
        expires_at=token.expires_at,
    )


@router.get("/{server}/status", response_model=MCPOAuthStatusResponse)
async def status_mcp_oauth(
    server: str,
    user: ActiveUser,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> MCPOAuthStatusResponse:
    """GET /api/v1/mcp/oauth/{server}/status — check connection state.

    Returns whether the calling user has a stored token for *server*, plus
    the granted scopes and expiry.  Token bytes are NEVER returned.
    """
    row = await oauth.get_status(db, user_id=user.id, server=server)
    if row is None:
        return MCPOAuthStatusResponse(connected=False, scopes=[], expires_at=None)
    return MCPOAuthStatusResponse(
        connected=True,
        scopes=row.scopes,
        expires_at=row.expires_at,
    )


@router.delete(
    "/{server}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
async def disconnect_mcp_oauth(
    server: str,
    user: ActiveUser,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Response:
    """DELETE /api/v1/mcp/oauth/{server} — revoke stored tokens (local only).

    Idempotent: deleting when no token is stored still returns 204.
    Audit row written only when a row was actually removed.
    """
    deleted = await oauth.disconnect(db, user_id=user.id, server=server)
    if deleted:
        await audit_action(
            db,
            user_id=user.id,
            action="mcp.oauth_disconnected",
            resource_type="mcp_server",
            resource_id=server,
            request=request,
        )
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
