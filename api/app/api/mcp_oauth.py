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
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response, status
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import ActiveUser
from app.audit import audit_action
from app.db.session import get_db
from app.mcp import oauth
from app.schemas.mcp_oauth import MCPOAuthCallbackResponse, MCPOAuthStatusResponse

router = APIRouter(prefix="/mcp/oauth", tags=["mcp-oauth"])


@router.get("/{server}/authorize", status_code=status.HTTP_302_FOUND)
async def authorize_mcp_oauth(
    server: str,
    user: ActiveUser,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> RedirectResponse:
    """GET /api/v1/mcp/oauth/{server}/authorize — start the OAuth flow.

    Builds the PKCE authorize URL for *server* and redirects the user's browser
    to the authorization server.  Audit happens on successful callback, not here.
    """
    redirect_uri = str(request.url_for("mcp_oauth_callback", server=server))
    url = await oauth.build_authorize_url(
        db, user_id=user.id, server=server, redirect_uri=redirect_uri
    )
    return RedirectResponse(url, status_code=status.HTTP_302_FOUND)


@router.get(
    "/{server}/callback",
    response_model=MCPOAuthCallbackResponse,
    name="mcp_oauth_callback",
)
async def mcp_oauth_callback(
    server: str,
    code: str,
    state: str,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    iss: str | None = None,
) -> MCPOAuthCallbackResponse:
    """GET /api/v1/mcp/oauth/{server}/callback — receive the AS redirect.

    PUBLIC — no bearer auth.  The user is bound to the exchange via the
    single-use, TTL-bounded mcp_oauth_state row inside exchange_code.
    On success, writes a mcp.oauth_connected audit row and returns 200.
    """
    token = await oauth.exchange_code(db, state=state, code=code, iss=iss)
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
