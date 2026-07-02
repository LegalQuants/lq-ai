"""Model + migration tests for mcp_oauth_tokens + mcp_oauth_state (PR4c / 0051).

Verifies:

* Both tables exist with the expected columns and primary keys after the 0051
  migration runs.
* FK cascade: deleting the user removes owned ``mcp_oauth_tokens`` rows.
* FK cascade: deleting the user removes owned ``mcp_oauth_state`` rows.
* ``access_token`` (LargeBinary / bytea) round-trips ciphertext faithfully.
* ``refresh_token`` is nullable (some AS omit it).
* ``mcp_oauth_state.expires_at`` is NOT NULL; ``mcp_oauth_tokens.expires_at``
  is nullable.

Tests use the session-scoped migrated DB + per-test rollback from conftest.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.mcp_oauth import MCPOAuthState, MCPOAuthToken
from app.models.user import User
from app.security.passwords import hash_password

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_user() -> User:
    """Return an unsaved User with a unique email."""
    return User(
        email=f"mcp-oauth-{uuid.uuid4().hex[:8]}@example.com",
        hashed_password=hash_password("test-pass"),
        is_admin=False,
        mfa_enabled=False,
    )


def _fake_ciphertext(tag: str = "at") -> bytes:
    """Return synthetic Fernet-shaped bytes (not real Fernet; just bytea round-trip)."""
    return f"FERNET:{tag}:{uuid.uuid4().hex}".encode()


# ---------------------------------------------------------------------------
# Column / schema tests (unit — no DB required)
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_mcp_oauth_token_columns() -> None:
    cols = MCPOAuthToken.__table__.columns.keys()
    assert set(cols) >= {
        "user_id",
        "provider_name",
        "access_token",
        "refresh_token",
        "expires_at",
        "scopes",
        "issuer",
        "created_at",
        "updated_at",
    }


@pytest.mark.unit
def test_mcp_oauth_token_primary_key() -> None:
    pk = {c.name for c in MCPOAuthToken.__table__.primary_key.columns}
    assert pk == {"user_id", "provider_name"}


@pytest.mark.unit
def test_mcp_oauth_state_columns() -> None:
    cols = MCPOAuthState.__table__.columns.keys()
    assert set(cols) >= {
        "state",
        "user_id",
        "provider_name",
        "code_verifier",
        "issuer",
        "resource",
        "token_endpoint",
        "redirect_uri",
        "as_iss_supported",
        "created_at",
        "expires_at",
    }


@pytest.mark.unit
def test_mcp_oauth_state_primary_key() -> None:
    pk = {c.name for c in MCPOAuthState.__table__.primary_key.columns}
    assert pk == {"state"}


# ---------------------------------------------------------------------------
# Integration tests (require migrated DB via conftest)
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_mcp_oauth_token_row_roundtrips(db_session: AsyncSession) -> None:
    """A token row persists and reads back with bytea ciphertext intact."""
    user = _make_user()
    db_session.add(user)
    await db_session.flush()

    at_cipher = _fake_ciphertext("at")
    rt_cipher = _fake_ciphertext("rt")
    token = MCPOAuthToken(
        user_id=user.id,
        provider_name="court-listener",
        access_token=at_cipher,
        refresh_token=rt_cipher,
        scopes=["read", "write"],
        issuer="https://example-as.test",
    )
    db_session.add(token)
    await db_session.flush()

    result = await db_session.execute(
        select(MCPOAuthToken).where(
            MCPOAuthToken.user_id == user.id,
            MCPOAuthToken.provider_name == "court-listener",
        )
    )
    row = result.scalar_one()
    assert row.access_token == at_cipher
    assert row.refresh_token == rt_cipher
    assert row.scopes == ["read", "write"]
    assert row.issuer == "https://example-as.test"
    assert row.expires_at is None  # nullable


@pytest.mark.integration
async def test_mcp_oauth_token_refresh_token_nullable(db_session: AsyncSession) -> None:
    """refresh_token is nullable (some AS omit it)."""
    user = _make_user()
    db_session.add(user)
    await db_session.flush()

    token = MCPOAuthToken(
        user_id=user.id,
        provider_name="no-refresh",
        access_token=_fake_ciphertext("at"),
        refresh_token=None,
    )
    db_session.add(token)
    await db_session.flush()

    result = await db_session.execute(
        select(MCPOAuthToken).where(
            MCPOAuthToken.user_id == user.id,
            MCPOAuthToken.provider_name == "no-refresh",
        )
    )
    row = result.scalar_one()
    assert row.refresh_token is None


@pytest.mark.integration
async def test_mcp_oauth_token_cascade_delete(db_session: AsyncSession) -> None:
    """Deleting a user CASCADE-deletes their mcp_oauth_tokens rows."""
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    user_id = user.id

    token = MCPOAuthToken(
        user_id=user_id,
        provider_name="cascade-provider",
        access_token=_fake_ciphertext("at"),
    )
    db_session.add(token)
    await db_session.flush()

    # Delete via raw SQL to bypass ORM relationship-load; the FK ON DELETE
    # CASCADE happens at the DB level.
    await db_session.execute(text("DELETE FROM users WHERE id = :uid"), {"uid": user_id})
    await db_session.flush()

    result = await db_session.execute(select(MCPOAuthToken).where(MCPOAuthToken.user_id == user_id))
    assert result.scalars().all() == []


@pytest.mark.integration
async def test_mcp_oauth_state_row_roundtrips(db_session: AsyncSession) -> None:
    """A state row persists and reads back with all required fields."""
    user = _make_user()
    db_session.add(user)
    await db_session.flush()

    expires = datetime.now(UTC) + timedelta(minutes=10)
    state_row = MCPOAuthState(
        state="csrf-state-abc123",
        user_id=user.id,
        provider_name="court-listener",
        code_verifier="dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk",
        issuer="https://example-as.test",
        resource="https://api.courtlistener.com/",
        token_endpoint="https://example-as.test/token",
        redirect_uri="https://lq-ai.local/api/v1/oauth/court-listener/callback",
        as_iss_supported=True,
        expires_at=expires,
    )
    db_session.add(state_row)
    await db_session.flush()

    result = await db_session.execute(
        select(MCPOAuthState).where(MCPOAuthState.state == "csrf-state-abc123")
    )
    row = result.scalar_one()
    assert row.user_id == user.id
    assert row.provider_name == "court-listener"
    assert row.code_verifier == "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk"
    assert row.issuer == "https://example-as.test"
    assert row.resource == "https://api.courtlistener.com/"
    assert row.token_endpoint == "https://example-as.test/token"
    assert row.redirect_uri == "https://lq-ai.local/api/v1/oauth/court-listener/callback"
    # expires_at is the only NOT NULL / no-server-default column; confirm it
    # round-trips faithfully.  asyncpg normalises to UTC-aware datetimes, so
    # we compare with a 1-second tolerance to absorb any sub-second clock drift.
    assert row.expires_at is not None
    assert abs((row.expires_at.replace(tzinfo=UTC) - expires).total_seconds()) < 1


@pytest.mark.integration
async def test_mcp_oauth_state_resource_nullable(db_session: AsyncSession) -> None:
    """resource is nullable (RFC 8707 resource indicator is optional)."""
    user = _make_user()
    db_session.add(user)
    await db_session.flush()

    expires = datetime.now(UTC) + timedelta(minutes=10)
    state_row = MCPOAuthState(
        state=f"state-no-resource-{uuid.uuid4().hex[:6]}",
        user_id=user.id,
        provider_name="no-resource-provider",
        code_verifier="verifier-xyz",
        issuer="https://issuer.test",
        resource=None,
        token_endpoint="https://issuer.test/token",
        redirect_uri="https://lq-ai.local/api/v1/oauth/no-resource-provider/callback",
        as_iss_supported=False,
        expires_at=expires,
    )
    db_session.add(state_row)
    await db_session.flush()

    result = await db_session.execute(
        select(MCPOAuthState).where(MCPOAuthState.state == state_row.state)
    )
    row = result.scalar_one()
    assert row.resource is None


@pytest.mark.integration
async def test_mcp_oauth_state_cascade_delete(db_session: AsyncSession) -> None:
    """Deleting a user CASCADE-deletes their mcp_oauth_state rows."""
    user = _make_user()
    db_session.add(user)
    await db_session.flush()
    user_id = user.id

    expires = datetime.now(UTC) + timedelta(minutes=10)
    state_row = MCPOAuthState(
        state=f"state-cascade-{uuid.uuid4().hex[:6]}",
        user_id=user_id,
        provider_name="cascade-provider",
        code_verifier="verifier-cascade",
        issuer="https://issuer.test",
        token_endpoint="https://issuer.test/token",
        redirect_uri="https://lq-ai.local/api/v1/oauth/cascade-provider/callback",
        as_iss_supported=False,
        expires_at=expires,
    )
    db_session.add(state_row)
    await db_session.flush()
    state_key = state_row.state

    await db_session.execute(text("DELETE FROM users WHERE id = :uid"), {"uid": user_id})
    await db_session.flush()

    result = await db_session.execute(select(MCPOAuthState).where(MCPOAuthState.state == state_key))
    assert result.scalars().all() == []
