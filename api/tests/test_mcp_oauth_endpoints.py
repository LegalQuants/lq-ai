"""Integration tests for PR4c's /api/v1/mcp/oauth per-user OAuth surface.

Covers:

* ``GET /api/v1/mcp/oauth/{server}/authorize``
  - authed → 302 with a Location to the AS authorize URL
  - unauthed → 401

* ``GET /api/v1/mcp/oauth/{server}/callback``
  - valid state → 200 ``{connected: true, ...}`` and an audit row written
  - bad/expired state → 400
  - no bearer required — an unauthenticated request still reaches the handler

* ``GET /api/v1/mcp/oauth/{server}/status``
  - connected → ``{connected: true, scopes, expires_at}``
  - not connected → ``{connected: false, scopes: [], expires_at: null}``
  - unauthed → 401

* ``DELETE /api/v1/mcp/oauth/{server}``
  - 204 and the row gone (+ audit)
  - disconnect when nothing connected → still 204 (idempotent)
  - unauthed → 401
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.main import app
from app.models.audit import AuditLog
from app.models.mcp_oauth import MCPOAuthState, MCPOAuthToken
from app.models.user import User
from app.security import create_access_token, hash_password
from app.security.encryption import MCP_MASTER_KEY_ENV, MCPTokenEncryptor, generate_master_key

# ---------------------------------------------------------------------------
# Session-level MCP master key so MCPTokenEncryptor.from_environ() works.
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def mcp_master_key(monkeypatch: pytest.MonkeyPatch) -> str:
    """Bind a fresh MCP master key for every test in this module."""
    key = generate_master_key()
    monkeypatch.setenv(MCP_MASTER_KEY_ENV, key)
    return key


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_SERVER = "acme-mcp"
_AUTHORIZE_URL = "https://as.example.com/authorize?response_type=code&..."
_TOKEN_ENDPOINT = "https://as.example.com/token"
_ISSUER = "https://as.example.com"


def _override_get_db(db_session: AsyncSession):
    async def _override() -> AsyncIterator[AsyncSession]:
        yield db_session

    return _override


async def _make_user(
    db_session: AsyncSession,
    *,
    email: str,
    is_admin: bool = False,
) -> tuple[User, str]:
    """Insert a user and return the user + a bearer token."""
    user = User(
        id=uuid.uuid4(),
        email=email,
        hashed_password=hash_password("test-password-123"),
        is_admin=is_admin,
        must_change_password=False,
    )
    db_session.add(user)
    await db_session.commit()
    token = create_access_token(user_id=user.id, email=user.email, is_admin=user.is_admin)
    return user, token


def _make_state_row(
    user_id: uuid.UUID,
    *,
    state: str = "test-state-value",
    server: str = _SERVER,
    expired: bool = False,
) -> MCPOAuthState:
    """Build an MCPOAuthState row for tests."""
    now = datetime.now(tz=UTC)
    return MCPOAuthState(
        state=state,
        user_id=user_id,
        provider_name=server,
        code_verifier="test-code-verifier-abc123",
        issuer=_ISSUER,
        resource=None,
        token_endpoint=_TOKEN_ENDPOINT,
        redirect_uri=f"http://test/api/v1/mcp/oauth/{server}/callback",
        as_iss_supported=False,
        expires_at=now - timedelta(minutes=1) if expired else now + timedelta(minutes=10),
    )


def _make_token_row(user_id: uuid.UUID, *, server: str = _SERVER) -> MCPOAuthToken:
    """Build an encrypted MCPOAuthToken row for tests."""
    enc = MCPTokenEncryptor.from_environ()
    return MCPOAuthToken(
        user_id=user_id,
        provider_name=server,
        access_token=enc.encrypt("fake-access-token"),
        refresh_token=None,
        expires_at=datetime.now(tz=UTC) + timedelta(hours=1),
        scopes=["read", "write"],
        issuer=_ISSUER,
        updated_at=datetime.now(tz=UTC),
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def authed_client(
    db_session: AsyncSession,
) -> AsyncIterator[tuple[AsyncClient, str, User]]:
    """Async HTTP client + bearer token + user for the authenticated caller."""
    user, token = await _make_user(db_session, email="oauth-user@example.com")
    app.dependency_overrides[get_db] = _override_get_db(db_session)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac, token, user
    app.dependency_overrides.pop(get_db, None)


@pytest_asyncio.fixture
async def anon_client(
    db_session: AsyncSession,
) -> AsyncIterator[AsyncClient]:
    """Async HTTP client without any auth (for callback + unauthed checks)."""
    app.dependency_overrides[get_db] = _override_get_db(db_session)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.pop(get_db, None)


# ---------------------------------------------------------------------------
# GET /mcp/oauth/{server}/authorize
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_authorize_authed_returns_302(
    authed_client: tuple[AsyncClient, str, User],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Authed call to /authorize → 302 with a Location to the AS."""
    ac, token, _user = authed_client

    async def _fake_build_authorize_url(
        db: Any,
        *,
        user_id: Any,
        server: str,
        redirect_uri: str,
    ) -> str:
        return _AUTHORIZE_URL

    monkeypatch.setattr("app.api.mcp_oauth.oauth.build_authorize_url", _fake_build_authorize_url)

    res = await ac.get(
        f"/api/v1/mcp/oauth/{_SERVER}/authorize",
        headers={"Authorization": f"Bearer {token}"},
        follow_redirects=False,
    )
    assert res.status_code == 302, res.text
    assert res.headers["location"] == _AUTHORIZE_URL


@pytest.mark.integration
async def test_authorize_unauthed_returns_401(
    anon_client: AsyncClient,
) -> None:
    """No bearer token → 401 on /authorize."""
    res = await anon_client.get(
        f"/api/v1/mcp/oauth/{_SERVER}/authorize",
        follow_redirects=False,
    )
    assert res.status_code == 401, res.text


# ---------------------------------------------------------------------------
# GET /mcp/oauth/{server}/callback
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_callback_valid_state_returns_200_and_audit(
    authed_client: tuple[AsyncClient, str, User],
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Valid callback → 200 with connected=true and an audit row."""
    ac, _token, user = authed_client

    # Seed a state row.
    state_val = "valid-state-abc"
    db_session.add(_make_state_row(user.id, state=state_val))
    await db_session.commit()

    # Build the token row that exchange_code will return.
    token_row = _make_token_row(user.id)

    async def _fake_exchange_code(
        db: Any,
        *,
        state: str,
        code: str,
        iss: str | None,
    ) -> MCPOAuthToken:
        return token_row

    monkeypatch.setattr("app.api.mcp_oauth.oauth.exchange_code", _fake_exchange_code)

    res = await ac.get(
        f"/api/v1/mcp/oauth/{_SERVER}/callback",
        params={"code": "auth-code-123", "state": state_val},
        # No Authorization header — the callback is public.
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["connected"] is True
    assert body["server"] == _SERVER
    assert "read" in body["scopes"]

    # Audit row written.
    await db_session.rollback()
    audit_rows = (
        (
            await db_session.execute(
                select(AuditLog).where(
                    AuditLog.action == "mcp.oauth_connected",
                    AuditLog.resource_id == _SERVER,
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(audit_rows) == 1
    assert audit_rows[0].resource_type == "mcp_server"
    assert audit_rows[0].details["scope_count"] == 2


@pytest.mark.integration
async def test_callback_bad_state_returns_400(
    anon_client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Unknown/expired state → 400 (MCPOAuthStateError maps to 400)."""
    from app.errors import MCPOAuthStateError

    async def _fake_exchange_code(
        db: Any,
        *,
        state: str,
        code: str,
        iss: str | None,
    ) -> MCPOAuthToken:
        raise MCPOAuthStateError(message="unknown state")

    monkeypatch.setattr("app.api.mcp_oauth.oauth.exchange_code", _fake_exchange_code)

    res = await anon_client.get(
        f"/api/v1/mcp/oauth/{_SERVER}/callback",
        params={"code": "bad-code", "state": "nonexistent-state"},
    )
    assert res.status_code == 400, res.text
    body = res.json()
    assert body["detail"]["code"] == "mcp_oauth_state_error"


@pytest.mark.integration
async def test_callback_no_bearer_reaches_handler(
    anon_client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A request without a bearer token is judged by state, not auth — public endpoint."""
    from app.errors import MCPOAuthStateError

    async def _fake_exchange_code(
        db: Any,
        *,
        state: str,
        code: str,
        iss: str | None,
    ) -> MCPOAuthToken:
        # Reaches the handler; state is bad → 400 (not 401).
        raise MCPOAuthStateError(message="unknown state")

    monkeypatch.setattr("app.api.mcp_oauth.oauth.exchange_code", _fake_exchange_code)

    res = await anon_client.get(
        f"/api/v1/mcp/oauth/{_SERVER}/callback",
        params={"code": "c", "state": "s"},
    )
    # Must NOT be 401 — the endpoint is public.
    assert res.status_code != 401
    assert res.status_code == 400, res.text


# ---------------------------------------------------------------------------
# GET /mcp/oauth/{server}/status
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_status_connected(
    authed_client: tuple[AsyncClient, str, User],
    db_session: AsyncSession,
) -> None:
    """User has a token row → connected=true with scopes and expires_at."""
    ac, token, user = authed_client
    db_session.add(_make_token_row(user.id))
    await db_session.commit()

    res = await ac.get(
        f"/api/v1/mcp/oauth/{_SERVER}/status",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["connected"] is True
    assert "read" in body["scopes"]
    assert body["expires_at"] is not None


@pytest.mark.integration
async def test_status_not_connected(
    authed_client: tuple[AsyncClient, str, User],
) -> None:
    """User has no token row → connected=false, empty scopes, null expires_at."""
    ac, token, _user = authed_client

    res = await ac.get(
        f"/api/v1/mcp/oauth/{_SERVER}/status",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["connected"] is False
    assert body["scopes"] == []
    assert body["expires_at"] is None


@pytest.mark.integration
async def test_status_unauthed_returns_401(
    anon_client: AsyncClient,
) -> None:
    """No bearer token → 401 on /status."""
    res = await anon_client.get(f"/api/v1/mcp/oauth/{_SERVER}/status")
    assert res.status_code == 401, res.text


# ---------------------------------------------------------------------------
# DELETE /mcp/oauth/{server}
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_disconnect_removes_row_and_audits(
    authed_client: tuple[AsyncClient, str, User],
    db_session: AsyncSession,
) -> None:
    """DELETE with a stored token → 204, row gone, audit row written."""
    ac, token, user = authed_client
    db_session.add(_make_token_row(user.id))
    await db_session.commit()

    res = await ac.delete(
        f"/api/v1/mcp/oauth/{_SERVER}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 204, res.text

    # Row is gone.
    await db_session.rollback()
    row = (
        await db_session.execute(
            select(MCPOAuthToken).where(
                MCPOAuthToken.user_id == user.id,
                MCPOAuthToken.provider_name == _SERVER,
            )
        )
    ).scalar_one_or_none()
    assert row is None

    # Audit row written.
    audit_rows = (
        (
            await db_session.execute(
                select(AuditLog).where(
                    AuditLog.action == "mcp.oauth_disconnected",
                    AuditLog.resource_id == _SERVER,
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(audit_rows) == 1
    assert audit_rows[0].resource_type == "mcp_server"


@pytest.mark.integration
async def test_disconnect_idempotent_no_row(
    authed_client: tuple[AsyncClient, str, User],
    db_session: AsyncSession,
) -> None:
    """DELETE when no token is stored → still 204 (idempotent). No audit row."""
    ac, token, _user = authed_client

    res = await ac.delete(
        f"/api/v1/mcp/oauth/{_SERVER}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 204, res.text

    # No audit row because nothing was deleted.
    await db_session.rollback()
    audit_rows = (
        (
            await db_session.execute(
                select(AuditLog).where(
                    AuditLog.action == "mcp.oauth_disconnected",
                    AuditLog.resource_id == _SERVER,
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(audit_rows) == 0


@pytest.mark.integration
async def test_disconnect_unauthed_returns_401(
    anon_client: AsyncClient,
) -> None:
    """No bearer token → 401 on DELETE."""
    res = await anon_client.delete(f"/api/v1/mcp/oauth/{_SERVER}")
    assert res.status_code == 401, res.text
