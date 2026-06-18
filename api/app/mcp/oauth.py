"""Per-user MCP OAuth 2.1 + PKCE service (PR4c) — the security-critical heart.

Drives the out-of-band authorization-code flow for ``auth: oauth`` MCP
servers:

1. :func:`build_authorize_url` — mint PKCE state and build the AS authorize
   URL the user is redirected to.
2. :func:`exchange_code` — validate the callback (state single-use + RFC 9207
   ``iss``), swap the code for tokens, Fernet-encrypt them at rest.
3. :func:`get_valid_token` — supply a live access token, refreshing
   transparently when the stored one has expired.
4. :func:`disconnect` — drop a user's stored tokens for a provider.

**No direct external HTTP.**  Every third-party call goes through the gateway
passthrough (ADR 0014; locked D-c6): :meth:`GatewayClient.oauth_discover`
performs AS metadata discovery, :meth:`GatewayClient.oauth_token` relays the
token endpoint.  ``authlib`` is used ONLY for PKCE + high-entropy token
generation — never its HTTP transport.

Security invariants (the review rubric — see ``task-4b-brief.md`` §"Security
invariants"):

* **PKCE S256 mandatory.**  ``code_challenge_method=S256``; the verifier never
  leaves the server except inside the token form (which goes only to the
  gateway passthrough).
* **RFC 9207 ``iss``.**  If the AS advertised the ``iss`` response parameter we
  recorded ``as_iss_supported=True`` at authorize-time; the callback then
  REQUIRES ``iss`` and rejects a mismatch.  A present ``iss`` always must match
  the discovered issuer.
* **RFC 8707 ``resource``.**  Sent on both authorize and token requests when
  discovery provided it.
* **State** is single-use (deleted on success AND on the expired / exchange-
  error paths), TTL-bounded (:data:`STATE_TTL`), high-entropy
  (``generate_token(48)``).
* **Tokens are Fernet-encrypted at rest** under the dedicated MCP master key.
  Plaintext tokens, the authorization code, the PKCE verifier, and the refresh
  token NEVER appear in logs, exception messages, or audit rows.  Exception
  payloads carry only the AS ``error`` string code and the server name.
* Decryption happens only at point-of-use; only :func:`get_valid_token`
  returns a bare access-token string (for the gateway header path).
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import cast
from urllib.parse import urlencode
from uuid import UUID

from authlib.common.security import generate_token
from authlib.oauth2.rfc7636 import create_s256_code_challenge
from sqlalchemy import CursorResult, delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.clients.gateway import get_gateway_client
from app.errors import (
    MCPAuthorizationRequired,
    MCPOAuthExchangeError,
    MCPOAuthNotConfigured,
    MCPOAuthStateError,
)
from app.models.mcp_oauth import MCPOAuthState, MCPOAuthToken
from app.security.encryption import MCPTokenEncryptor

log = logging.getLogger(__name__)

STATE_TTL = timedelta(minutes=10)
"""How long a minted authorize state stays valid before the callback rejects
it.  Short by design — the user redirect round-trip is seconds, not minutes."""

_REFRESH_SKEW = timedelta(seconds=30)
"""Treat a token expiring within this window as already expired, so we refresh
proactively rather than handing the gateway a token that dies mid-flight."""

_VERIFIER_BYTES = 48
"""Entropy for PKCE verifier + state (``generate_token`` count param)."""


# ---------------------------------------------------------------------------
# Typed exceptions — carry NO secret material (only the server name + AS error
# string code).  See module docstring's security invariants.
#
# MCPOAuthNotConfigured, MCPOAuthStateError, MCPOAuthExchangeError are
# LQAIError subclasses defined in app.errors so the global exception handler
# maps them to structured HTTP responses automatically.  Re-exported here so
# call-sites can import from this module without caring about the hierarchy.
# ---------------------------------------------------------------------------

# Re-export so callers can `from app.mcp.oauth import MCPOAuth*`.
__all__ = [
    "MCPAuthorizationRequired",
    "MCPOAuthExchangeError",
    "MCPOAuthNotConfigured",
    "MCPOAuthStateError",
    "build_authorize_url",
    "disconnect",
    "exchange_code",
    "get_status",
    "get_valid_token",
]


# MCPAuthorizationRequired is defined in app.errors (Task 6) and re-exported
# below so callers can ``from app.mcp.oauth import MCPAuthorizationRequired``.

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


async def _resolve_oauth_provider(server: str) -> dict[str, str]:
    """Return the ``{name, server_url, oauth_client_id}`` config for *server*.

    Raises :class:`MCPOAuthNotConfigured` when *server* is not an oauth MCP
    provider in the gateway's sanitised config.
    """
    configs = await get_gateway_client().list_mcp_oauth_config()
    for cfg in configs:
        if cfg["name"] == server:
            return cfg
    raise MCPOAuthNotConfigured(
        message=f"MCP server {server!r} is not configured for OAuth",
        details={"server": server},
    )


def _now() -> datetime:
    return datetime.now(tz=UTC)


# ---------------------------------------------------------------------------
# Public service functions
# ---------------------------------------------------------------------------


async def build_authorize_url(
    db: AsyncSession,
    *,
    user_id: UUID,
    server: str,
    redirect_uri: str,
) -> str:
    """Mint PKCE state and build the AS authorize URL for *server*.

    Persists a single-use, TTL-bounded :class:`MCPOAuthState` row carrying the
    PKCE ``code_verifier``, the discovered issuer / token endpoint / resource,
    and whether the AS supports the RFC 9207 ``iss`` parameter — then returns
    the authorize URL the caller redirects the user to.
    """
    provider = await _resolve_oauth_provider(server)
    gw = get_gateway_client()
    meta = await gw.oauth_discover(server)

    state = generate_token(_VERIFIER_BYTES)
    code_verifier = generate_token(_VERIFIER_BYTES)
    code_challenge = create_s256_code_challenge(code_verifier)

    resource = meta.get("resource")
    scopes = meta.get("scopes_supported") or []

    params: dict[str, str] = {
        "response_type": "code",
        "client_id": provider["oauth_client_id"],
        "redirect_uri": redirect_uri,
        "state": state,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
    }
    scope_value = " ".join(scopes)
    if scope_value:
        params["scope"] = scope_value
    if resource:
        params["resource"] = resource

    authorize_url = f"{meta['authorization_endpoint']}?{urlencode(params)}"

    db.add(
        MCPOAuthState(
            state=state,
            user_id=user_id,
            provider_name=server,
            code_verifier=code_verifier,
            issuer=meta["issuer"],
            resource=resource,
            token_endpoint=meta["token_endpoint"],
            redirect_uri=redirect_uri,
            as_iss_supported=bool(meta.get("authorization_response_iss_parameter_supported")),
            expires_at=_now() + STATE_TTL,
        )
    )
    await db.commit()
    return authorize_url


async def exchange_code(
    db: AsyncSession,
    *,
    state: str,
    code: str,
    iss: str | None,
) -> MCPOAuthToken:
    """Validate the OAuth callback and exchange *code* for encrypted tokens.

    Enforces single-use state (TTL + delete-on-consume) and RFC 9207 ``iss``
    validation, then swaps the code at the token endpoint through the gateway
    passthrough and upserts a Fernet-encrypted :class:`MCPOAuthToken` row.
    """
    row = (
        await db.execute(select(MCPOAuthState).where(MCPOAuthState.state == state))
    ).scalar_one_or_none()
    if row is None:
        raise MCPOAuthStateError("unknown state")

    if row.expires_at < _now():
        await db.execute(delete(MCPOAuthState).where(MCPOAuthState.state == state))
        await db.commit()
        raise MCPOAuthStateError("expired state")

    # RFC 9207 iss validation.
    if row.as_iss_supported and not iss:
        raise MCPOAuthStateError("missing iss")
    if iss is not None and iss != row.issuer:
        raise MCPOAuthStateError("iss mismatch")

    provider = await _resolve_oauth_provider(row.provider_name)
    form: dict[str, str] = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": row.redirect_uri,
        "client_id": provider["oauth_client_id"],
        "code_verifier": row.code_verifier,
    }
    if row.resource:
        form["resource"] = row.resource

    status_code, body = await get_gateway_client().oauth_token(
        row.provider_name,
        token_endpoint=row.token_endpoint,
        form=form,
    )

    if status_code >= 400:
        # Single-use: consume the state even on the AS-error path.
        await db.execute(delete(MCPOAuthState).where(MCPOAuthState.state == state))
        await db.commit()
        _as_code = str(body.get("error") or "unknown")
        raise MCPOAuthExchangeError(
            message=f"OAuth token exchange failed for {row.provider_name!r}: {_as_code}",
            details={"as_error": _as_code, "server": row.provider_name},
        )

    token_row = _persist_token(
        db,
        owner_id=row.user_id,
        provider=row.provider_name,
        body=body,
        issuer=row.issuer,
    )
    if token_row is None:
        # A 2xx without an access_token is contract drift / a broken AS.
        await db.execute(delete(MCPOAuthState).where(MCPOAuthState.state == state))
        await db.commit()
        raise MCPOAuthExchangeError(
            message=f"OAuth token exchange for {row.provider_name!r} returned no access_token",
            details={"as_error": "missing_access_token", "server": row.provider_name},
        )

    # Consume the state on success (single-use).
    await db.execute(delete(MCPOAuthState).where(MCPOAuthState.state == state))
    await db.commit()
    return token_row


def _persist_token(
    db: AsyncSession,
    *,
    owner_id: UUID,
    provider: str,
    body: dict[str, object],
    issuer: str | None = None,
    existing: MCPOAuthToken | None = None,
    keep_refresh: bytes | None = None,
) -> MCPOAuthToken | None:
    """Parse a token response and upsert an encrypted :class:`MCPOAuthToken`.

    Returns ``None`` (without mutating the session) when the body lacks an
    ``access_token`` — the caller treats that as an exchange error.  On
    success the row is added/updated in the session (caller commits).

    ``keep_refresh`` is the existing encrypted refresh token to retain when the
    AS omits a rotated ``refresh_token`` (refresh-token rotation is optional).
    """
    access = body.get("access_token")
    if not isinstance(access, str) or not access:
        return None

    enc = MCPTokenEncryptor.from_environ()
    access_cipher = enc.encrypt(access)

    refresh_plain = body.get("refresh_token")
    if isinstance(refresh_plain, str) and refresh_plain:
        refresh_cipher: bytes | None = enc.encrypt(refresh_plain)
    else:
        refresh_cipher = keep_refresh

    expires_at: datetime | None = None
    expires_in = body.get("expires_in")
    if isinstance(expires_in, int) and not isinstance(expires_in, bool):
        expires_at = _now() + timedelta(seconds=expires_in)

    scope = body.get("scope")
    scopes = scope.split() if isinstance(scope, str) and scope else []

    if existing is not None:
        existing.access_token = access_cipher
        existing.refresh_token = refresh_cipher
        existing.expires_at = expires_at
        existing.scopes = scopes
        existing.updated_at = _now()
        return existing

    row = MCPOAuthToken(
        user_id=owner_id,
        provider_name=provider,
        access_token=access_cipher,
        refresh_token=refresh_cipher,
        expires_at=expires_at,
        scopes=scopes,
        issuer=issuer,
        updated_at=_now(),
    )
    db.add(row)
    return row


async def get_valid_token(
    db: AsyncSession,
    *,
    user_id: UUID,
    server: str,
) -> str | None:
    """Return a live decrypted access token for ``(user_id, server)``.

    Returns ``None`` when there is no stored token, when it is expired and
    cannot be refreshed, or when a refresh attempt is rejected by the AS (the
    stale row is then deleted).  On a successful refresh the rotated tokens are
    re-encrypted and persisted before the new access token is returned.

    The tool-path caller (Task 6) translates a ``None`` into
    :class:`MCPAuthorizationRequired`.
    """
    row = (
        await db.execute(
            select(MCPOAuthToken).where(
                MCPOAuthToken.user_id == user_id,
                MCPOAuthToken.provider_name == server,
            )
        )
    ).scalar_one_or_none()
    if row is None:
        return None

    enc = MCPTokenEncryptor.from_environ()

    if row.expires_at is None or row.expires_at > _now() + _REFRESH_SKEW:
        return enc.decrypt(row.access_token)

    # Expired.  Try a refresh if we have a refresh token; else re-auth needed.
    if row.refresh_token is None:
        return None

    provider = await _resolve_oauth_provider(server)
    gw = get_gateway_client()
    meta = await gw.oauth_discover(server)

    form: dict[str, str] = {
        "grant_type": "refresh_token",
        "refresh_token": enc.decrypt(row.refresh_token),
        "client_id": provider["oauth_client_id"],
    }

    status_code, body = await gw.oauth_token(
        server,
        token_endpoint=meta["token_endpoint"],
        form=form,
    )

    if status_code >= 400:
        # Refresh rejected (likely revoked); drop the dead row.
        await db.execute(
            delete(MCPOAuthToken).where(
                MCPOAuthToken.user_id == user_id,
                MCPOAuthToken.provider_name == server,
            )
        )
        await db.commit()
        return None

    updated = _persist_token(
        db,
        owner_id=user_id,
        provider=server,
        body=body,
        existing=row,
        keep_refresh=row.refresh_token,
    )
    if updated is None:
        # 2xx without an access token — treat as a failed refresh.
        await db.execute(
            delete(MCPOAuthToken).where(
                MCPOAuthToken.user_id == user_id,
                MCPOAuthToken.provider_name == server,
            )
        )
        await db.commit()
        return None

    await db.commit()
    return enc.decrypt(updated.access_token)


async def get_status(
    db: AsyncSession,
    *,
    user_id: UUID,
    server: str,
) -> MCPOAuthToken | None:
    """Return the stored token row for ``(user_id, server)`` or ``None``.

    The REST status endpoint uses this to report ``connected`` state without
    exposing any token bytes.  Callers MUST NOT read ``access_token`` or
    ``refresh_token`` from the returned row — those fields are encrypted
    ciphertext and only :func:`get_valid_token` should decrypt them.
    """
    return (
        await db.execute(
            select(MCPOAuthToken).where(
                MCPOAuthToken.user_id == user_id,
                MCPOAuthToken.provider_name == server,
            )
        )
    ).scalar_one_or_none()


async def disconnect(
    db: AsyncSession,
    *,
    user_id: UUID,
    server: str,
) -> bool:
    """Delete the stored token for ``(user_id, server)``; return whether a row
    was removed.

    AS-side token revocation (RFC 7009) is intentionally NOT called here — see
    DE: "MCP OAuth disconnect could best-effort hit the AS revocation
    endpoint" — v1 just drops the local copy.
    """
    result = await db.execute(
        delete(MCPOAuthToken).where(
            MCPOAuthToken.user_id == user_id,
            MCPOAuthToken.provider_name == server,
        )
    )
    await db.commit()
    # A Core DELETE yields a CursorResult; ``rowcount`` is the deleted count.
    return bool(cast("CursorResult[object]", result).rowcount)
