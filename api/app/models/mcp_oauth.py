"""ORM models for PR4c per-user MCP OAuth persistence.

Two tables:

* ``mcp_oauth_tokens`` — Fernet-encrypted access/refresh tokens, one row
  per ``(user_id, provider_name)``.  Composite PK; no surrogate key needed
  because the pair is globally unique and the row is looked up directly by
  both halves.

* ``mcp_oauth_state`` — short-lived CSRF/PKCE state that bridges the
  ``/authorize`` redirect to the ``/callback`` handler.  Single-use (deleted
  on successful callback) with an app-enforced TTL column.  A dedicated DB
  table rather than a cache entry (Redis/memcached) was chosen by the PR4c
  controller for multi-worker safety and restart resilience.  See
  docs/adr/0015 for the rationale.

Encrypted-token columns use ``LargeBinary`` (→ Postgres ``bytea``) to hold
Fernet ciphertext produced by ``app.security.encryption.MCPTokenEncryptor``.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, LargeBinary, Text, text
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class MCPOAuthToken(Base):
    """Fernet-encrypted OAuth tokens for a user ↔ MCP provider pair.

    Composite PK: ``(user_id, provider_name)``.  Upserted at callback time;
    the refresh path overwrites ``access_token``, ``refresh_token``, and
    ``expires_at`` in place while ``created_at`` stays frozen.
    ``updated_at`` is bumped by the app on every write (no trigger needed
    for this small, targeted table).
    """

    __tablename__ = "mcp_oauth_tokens"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE", name="fk_mcp_oauth_tokens_user"),
        primary_key=True,
    )
    provider_name: Mapped[str] = mapped_column(Text, primary_key=True)
    access_token: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    """Fernet ciphertext produced by MCPTokenEncryptor."""
    refresh_token: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    """Fernet ciphertext; nullable — some authorization servers omit it."""
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    """AS-issued expiry; nullable — some AS omit ``expires_in``."""
    scopes: Mapped[list[str]] = mapped_column(
        ARRAY(Text),
        nullable=False,
        server_default=text("ARRAY[]::text[]"),
    )
    """Granted scopes as reported by the AS at token exchange."""
    issuer: Mapped[str | None] = mapped_column(Text, nullable=True)
    """Recorded AS issuer (RFC 9207); used for iss-validation on refresh."""
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )
    # NOTE: no DB trigger — the app must set updated_at explicitly on every
    # write (upsert + refresh path).  Omitting it silently leaves a stale value.

    def __repr__(self) -> str:
        return f"<MCPOAuthToken user_id={self.user_id} provider={self.provider_name!r}>"


class MCPOAuthState(Base):
    """Short-lived CSRF/PKCE state bridging /authorize → /callback.

    PK is the opaque ``state`` token itself (URL-safe random string generated
    by the authorize handler).  Deleted on successful callback; the app
    rejects rows whose ``expires_at`` has passed.  Never returned to the
    client — server-side only.
    """

    __tablename__ = "mcp_oauth_state"

    state: Mapped[str] = mapped_column(Text, primary_key=True)
    """Opaque random CSRF state value; also the OAuth ``state`` param."""
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE", name="fk_mcp_oauth_state_user"),
        nullable=False,
    )
    """Who initiated the authorize flow; cascade-deleted if user is removed."""
    provider_name: Mapped[str] = mapped_column(Text, nullable=False)
    """MCP provider being authorized (matches gateway config name)."""
    code_verifier: Mapped[str] = mapped_column(Text, nullable=False)
    """PKCE code_verifier — ephemeral, single-use, TTL-protected server-side
    state; left plaintext (standard practice for server-side OAuth state
    stores).  See task-3-report.md §code_verifier for the trade-off note."""
    issuer: Mapped[str] = mapped_column(Text, nullable=False)
    """AS issuer captured at authorize-time; callback validates the returned
    ``iss`` claim against this value (RFC 9207 §4)."""
    resource: Mapped[str | None] = mapped_column(Text, nullable=True)
    """Canonical resource URI (RFC 8707); captured at authorize-time."""
    token_endpoint: Mapped[str] = mapped_column(Text, nullable=False)
    """Discovered token endpoint, replayed to the gateway at callback."""
    redirect_uri: Mapped[str] = mapped_column(Text, nullable=False)
    """The callback redirect_uri used in the authorize request; must match
    at token exchange."""
    as_iss_supported: Mapped[bool] = mapped_column(Boolean, nullable=False)
    """Whether the AS advertised the RFC 9207
    ``authorization_response_iss_parameter_supported`` flag at authorize-time.
    Captured from discovery so the callback can enforce "iss is REQUIRED when
    the AS supports it" (RFC 9207 §3) — not just "iss must match when present".
    No server_default: the app always sets it from discovery metadata."""
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    """Short TTL set by the app (e.g. now + 10 min); app rejects expired state."""

    def __repr__(self) -> str:
        return (
            f"<MCPOAuthState state={self.state!r} user_id={self.user_id}"
            f" provider={self.provider_name!r}>"
        )
