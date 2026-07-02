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
        return_url: str | None = None,
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

    async def _fake_get_state_return_url(db: Any, *, state: str) -> str | None:
        return None  # no return_url → back-compat 200 JSON path

    async def _fake_exchange_code(
        db: Any,
        *,
        state: str,
        code: str,
        iss: str | None,
    ) -> MCPOAuthToken:
        return token_row

    monkeypatch.setattr("app.api.mcp_oauth.oauth.get_state_return_url", _fake_get_state_return_url)
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

    async def _fake_get_state_return_url(db: Any, *, state: str) -> str | None:
        return None  # state unknown → no return_url → JSON error path

    async def _fake_exchange_code(
        db: Any,
        *,
        state: str,
        code: str,
        iss: str | None,
    ) -> MCPOAuthToken:
        raise MCPOAuthStateError(message="unknown state")

    monkeypatch.setattr("app.api.mcp_oauth.oauth.get_state_return_url", _fake_get_state_return_url)
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

    async def _fake_get_state_return_url(db: Any, *, state: str) -> str | None:
        return None

    async def _fake_exchange_code(
        db: Any,
        *,
        state: str,
        code: str,
        iss: str | None,
    ) -> MCPOAuthToken:
        # Reaches the handler; state is bad → 400 (not 401).
        raise MCPOAuthStateError(message="unknown state")

    monkeypatch.setattr("app.api.mcp_oauth.oauth.get_state_return_url", _fake_get_state_return_url)
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


# ---------------------------------------------------------------------------
# PR4d: is_allowed_return_url unit tests (validator correctness)
# ---------------------------------------------------------------------------


def test_allowed_return_url_matching_origin(monkeypatch: pytest.MonkeyPatch) -> None:
    """A return_url whose origin exactly matches an allowlisted origin → True."""
    from app.config import Settings, is_allowed_return_url

    monkeypatch.setenv("LQ_AI_CORS_ORIGINS", "https://app.example.com")
    s = Settings()
    assert is_allowed_return_url("https://app.example.com/oauth/callback", s) is True


def test_allowed_return_url_different_origin(monkeypatch: pytest.MonkeyPatch) -> None:
    """A return_url whose origin is NOT in the allowlist → False."""
    from app.config import Settings, is_allowed_return_url

    monkeypatch.setenv("LQ_AI_CORS_ORIGINS", "https://app.example.com")
    s = Settings()
    assert is_allowed_return_url("https://evil.example.com/steal", s) is False


def test_allowed_return_url_different_port(monkeypatch: pytest.MonkeyPatch) -> None:
    """Same host but different port is a different origin → False."""
    from app.config import Settings, is_allowed_return_url

    monkeypatch.setenv("LQ_AI_CORS_ORIGINS", "https://app.example.com")
    s = Settings()
    assert is_allowed_return_url("https://app.example.com:9000/callback", s) is False


def test_allowed_return_url_empty_allowlist(monkeypatch: pytest.MonkeyPatch) -> None:
    """Empty lq_ai_cors_origins → always False (fail closed)."""
    from app.config import Settings, is_allowed_return_url

    monkeypatch.setenv("LQ_AI_CORS_ORIGINS", "")
    s = Settings()
    assert is_allowed_return_url("https://app.example.com/callback", s) is False


def test_allowed_return_url_non_http_scheme(monkeypatch: pytest.MonkeyPatch) -> None:
    """Non-http(s) scheme is rejected even if it would otherwise match."""
    from app.config import Settings, is_allowed_return_url

    monkeypatch.setenv("LQ_AI_CORS_ORIGINS", "javascript://app.example.com")
    s = Settings()
    assert is_allowed_return_url("javascript://app.example.com/evil", s) is False


def test_allowed_return_url_http_allowed(monkeypatch: pytest.MonkeyPatch) -> None:
    """http (non-TLS) origin is accepted when the operator explicitly allows it."""
    from app.config import Settings, is_allowed_return_url

    monkeypatch.setenv("LQ_AI_CORS_ORIGINS", "http://localhost:3000")
    s = Settings()
    assert is_allowed_return_url("http://localhost:3000/connect", s) is True


def test_allowed_return_url_userinfo_smuggling(monkeypatch: pytest.MonkeyPatch) -> None:
    """Userinfo-smuggling attack: https://app.example.com@evil.com/steal → False.

    The URL looks like it starts with the allowlisted host but the actual
    authority (netloc) is ``evil.com``.  The validator must reject it.
    """
    from app.config import Settings, is_allowed_return_url

    monkeypatch.setenv("LQ_AI_CORS_ORIGINS", "https://app.example.com")
    s = Settings()
    assert is_allowed_return_url("https://app.example.com@evil.com/steal", s) is False


def test_allowed_return_url_data_scheme_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    """data: URI scheme is rejected — not http(s), so never allowed."""
    from app.config import Settings, is_allowed_return_url

    monkeypatch.setenv("LQ_AI_CORS_ORIGINS", "https://app.example.com")
    s = Settings()
    assert is_allowed_return_url("data:text/html,<script>alert(1)</script>", s) is False


# ---------------------------------------------------------------------------
# PR4d: /authorize with return_url
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_authorize_with_allowed_return_url_stores_on_state_row(
    authed_client: tuple[AsyncClient, str, User],
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Authed /authorize with an allowed return_url → 302 to AS AND state row stores return_url."""
    ac, token, _user = authed_client

    monkeypatch.setenv("LQ_AI_CORS_ORIGINS", "https://frontend.example.com")
    from app.config import get_settings

    get_settings.cache_clear()

    captured_state: dict[str, Any] = {}

    async def _fake_build_authorize_url(
        db: Any,
        *,
        user_id: Any,
        server: str,
        redirect_uri: str,
        return_url: str | None = None,
    ) -> str:
        captured_state["return_url"] = return_url
        return _AUTHORIZE_URL

    monkeypatch.setattr("app.api.mcp_oauth.oauth.build_authorize_url", _fake_build_authorize_url)

    res = await ac.get(
        f"/api/v1/mcp/oauth/{_SERVER}/authorize",
        params={"return_url": "https://frontend.example.com/connect"},
        headers={"Authorization": f"Bearer {token}"},
        follow_redirects=False,
    )
    assert res.status_code == 302, res.text
    assert res.headers["location"] == _AUTHORIZE_URL
    assert captured_state["return_url"] == "https://frontend.example.com/connect"

    get_settings.cache_clear()


@pytest.mark.integration
async def test_authorize_with_disallowed_return_url_returns_400(
    authed_client: tuple[AsyncClient, str, User],
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Disallowed return_url origin → 400, no state row written."""
    ac, token, _user = authed_client

    monkeypatch.setenv("LQ_AI_CORS_ORIGINS", "https://frontend.example.com")
    from app.config import get_settings

    get_settings.cache_clear()

    build_called = {"called": False}

    async def _fake_build_authorize_url(db: Any, **_kwargs: Any) -> str:
        build_called["called"] = True
        return _AUTHORIZE_URL

    monkeypatch.setattr("app.api.mcp_oauth.oauth.build_authorize_url", _fake_build_authorize_url)

    res = await ac.get(
        f"/api/v1/mcp/oauth/{_SERVER}/authorize",
        params={"return_url": "https://evil.example.com/steal"},
        headers={"Authorization": f"Bearer {token}"},
        follow_redirects=False,
    )
    assert res.status_code == 400, res.text
    body = res.json()
    assert body["detail"]["code"] == "validation_error"
    # build_authorize_url must NOT have been called — no state row written.
    assert not build_called["called"]

    get_settings.cache_clear()


@pytest.mark.integration
async def test_authorize_without_return_url_state_row_return_url_is_none(
    authed_client: tuple[AsyncClient, str, User],
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No return_url query param → build_authorize_url called with return_url=None (back-compat)."""
    ac, token, _user = authed_client

    captured: dict[str, Any] = {}

    async def _fake_build_authorize_url(
        db: Any,
        *,
        user_id: Any,
        server: str,
        redirect_uri: str,
        return_url: str | None = None,
    ) -> str:
        captured["return_url"] = return_url
        return _AUTHORIZE_URL

    monkeypatch.setattr("app.api.mcp_oauth.oauth.build_authorize_url", _fake_build_authorize_url)

    res = await ac.get(
        f"/api/v1/mcp/oauth/{_SERVER}/authorize",
        headers={"Authorization": f"Bearer {token}"},
        follow_redirects=False,
    )
    assert res.status_code == 302, res.text
    assert captured["return_url"] is None


# ---------------------------------------------------------------------------
# PR4d: callback with return_url (redirect branching)
# ---------------------------------------------------------------------------

_RETURN_URL = "https://frontend.example.com/connect"


@pytest.mark.integration
async def test_callback_success_with_return_url_redirects(
    authed_client: tuple[AsyncClient, str, User],
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Callback with return_url stored on state → 302 to return_url?mcp_connected=server."""
    ac, _token, user = authed_client

    state_val = "state-with-return-url"

    async def _fake_get_state_return_url(db: Any, *, state: str) -> str | None:
        return _RETURN_URL

    token_row = _make_token_row(user.id)

    async def _fake_exchange_code(
        db: Any,
        *,
        state: str,
        code: str,
        iss: str | None,
    ) -> MCPOAuthToken:
        return token_row

    monkeypatch.setattr("app.api.mcp_oauth.oauth.get_state_return_url", _fake_get_state_return_url)
    monkeypatch.setattr("app.api.mcp_oauth.oauth.exchange_code", _fake_exchange_code)

    res = await ac.get(
        f"/api/v1/mcp/oauth/{_SERVER}/callback",
        params={"code": "auth-code-123", "state": state_val},
        follow_redirects=False,
    )
    assert res.status_code == 302, res.text
    location = res.headers["location"]
    assert location.startswith(_RETURN_URL), f"Location={location!r}"
    assert "mcp_connected=" in location
    assert _SERVER in location

    # Ensure no token/code/state material leaked into the redirect.
    assert "auth-code-123" not in location
    assert state_val not in location

    # Audit row was written.
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


@pytest.mark.integration
async def test_callback_success_without_return_url_returns_200_json(
    authed_client: tuple[AsyncClient, str, User],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Callback with no return_url on state → 200 JSON (back-compat preserved)."""
    ac, _token, user = authed_client

    async def _fake_get_state_return_url(db: Any, *, state: str) -> str | None:
        return None

    token_row = _make_token_row(user.id)

    async def _fake_exchange_code(
        db: Any,
        *,
        state: str,
        code: str,
        iss: str | None,
    ) -> MCPOAuthToken:
        return token_row

    monkeypatch.setattr("app.api.mcp_oauth.oauth.get_state_return_url", _fake_get_state_return_url)
    monkeypatch.setattr("app.api.mcp_oauth.oauth.exchange_code", _fake_exchange_code)

    res = await ac.get(
        f"/api/v1/mcp/oauth/{_SERVER}/callback",
        params={"code": "c", "state": "s"},
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["connected"] is True
    assert body["server"] == _SERVER


@pytest.mark.integration
async def test_callback_exchange_error_with_return_url_redirects_with_error(
    anon_client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Exchange error with return_url → 302 to return_url?mcp_error=...&server=...; no secrets."""
    from app.errors import MCPOAuthExchangeError

    async def _fake_get_state_return_url(db: Any, *, state: str) -> str | None:
        return _RETURN_URL

    async def _fake_exchange_code(
        db: Any,
        *,
        state: str,
        code: str,
        iss: str | None,
    ) -> MCPOAuthToken:
        raise MCPOAuthExchangeError(
            message="OAuth token exchange failed for 'acme-mcp': invalid_client",
            details={"as_error": "invalid_client", "server": _SERVER},
        )

    monkeypatch.setattr("app.api.mcp_oauth.oauth.get_state_return_url", _fake_get_state_return_url)
    monkeypatch.setattr("app.api.mcp_oauth.oauth.exchange_code", _fake_exchange_code)

    res = await anon_client.get(
        f"/api/v1/mcp/oauth/{_SERVER}/callback",
        params={"code": "bad-code", "state": "some-state"},
        follow_redirects=False,
    )
    assert res.status_code == 302, res.text
    location = res.headers["location"]
    assert location.startswith(_RETURN_URL), f"Location={location!r}"
    assert "mcp_error=" in location
    assert "server=" in location
    # Must NOT contain the code, state, or any secret in the redirect.
    assert "bad-code" not in location
    assert "some-state" not in location
    # The error code is the stable slug — check it's present and non-empty.
    assert "mcp_oauth_exchange_error" in location


@pytest.mark.integration
async def test_callback_unknown_state_no_return_url_returns_json_error(
    anon_client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Unknown/expired state (return_url unrecoverable) → JSON error, not a redirect."""
    from app.errors import MCPOAuthStateError

    # State row not found → get_state_return_url returns None.
    async def _fake_get_state_return_url(db: Any, *, state: str) -> str | None:
        return None

    async def _fake_exchange_code(
        db: Any,
        *,
        state: str,
        code: str,
        iss: str | None,
    ) -> MCPOAuthToken:
        raise MCPOAuthStateError(message="unknown state")

    monkeypatch.setattr("app.api.mcp_oauth.oauth.get_state_return_url", _fake_get_state_return_url)
    monkeypatch.setattr("app.api.mcp_oauth.oauth.exchange_code", _fake_exchange_code)

    res = await anon_client.get(
        f"/api/v1/mcp/oauth/{_SERVER}/callback",
        params={"code": "c", "state": "nonexistent"},
    )
    assert res.status_code == 400, res.text
    body = res.json()
    assert body["detail"]["code"] == "mcp_oauth_state_error"


@pytest.mark.integration
async def test_callback_not_configured_with_return_url_redirects_with_error(
    anon_client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """MCPOAuthNotConfigured with a return_url → 302 to return_url?mcp_error=...&server=...

    When the OAuth service raises MCPOAuthNotConfigured (e.g. the server has no
    OAuth config in gateway.yaml), and a return_url was stored on the state row,
    the browser must be redirected to the frontend error URL — not to a JSON
    response from the global error handler.  No token, code, or state value may
    appear in the Location header.
    """
    from app.errors import MCPOAuthNotConfigured

    async def _fake_get_state_return_url(db: Any, *, state: str) -> str | None:
        return _RETURN_URL

    async def _fake_exchange_code(
        db: Any,
        *,
        state: str,
        code: str,
        iss: str | None,
    ) -> MCPOAuthToken:
        raise MCPOAuthNotConfigured(
            message="MCP server 'acme-mcp' has no OAuth configuration",
            details={"server": _SERVER},
        )

    monkeypatch.setattr("app.api.mcp_oauth.oauth.get_state_return_url", _fake_get_state_return_url)
    monkeypatch.setattr("app.api.mcp_oauth.oauth.exchange_code", _fake_exchange_code)

    res = await anon_client.get(
        f"/api/v1/mcp/oauth/{_SERVER}/callback",
        params={"code": "some-code", "state": "some-state"},
        follow_redirects=False,
    )
    assert res.status_code == 302, res.text
    location = res.headers["location"]
    assert location.startswith(_RETURN_URL), f"Location={location!r}"
    assert "mcp_error=" in location
    assert "server=" in location
    # Must NOT contain the auth code, state, or any token material.
    assert "some-code" not in location
    assert "some-state" not in location


# ---------------------------------------------------------------------------
# PR4d Ask 1: GET /api/v1/mcp/oauth — per-user OAuth connections list
# ---------------------------------------------------------------------------

_SERVER2 = "beta-mcp"

_OAUTH_CONFIG = [
    {"name": _SERVER, "server_url": "https://acme.example.com", "oauth_client_id": "client-a"},
    {"name": _SERVER2, "server_url": "https://beta.example.com", "oauth_client_id": "client-b"},
]


@pytest.mark.integration
async def test_list_mcp_oauth_one_connected_one_not(
    authed_client: tuple[AsyncClient, str, User],
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """GET /mcp/oauth authed → lists every configured oauth server.

    One server is connected (token row present), the other is not.
    Response must contain no token bytes.
    """
    ac, token, user = authed_client

    # Seed a token row for _SERVER only (not _SERVER2).
    token_row = _make_token_row(user.id, server=_SERVER)
    db_session.add(token_row)
    await db_session.commit()

    # Patch list_connection_status directly — this is the function the route calls.
    async def _fake_list_connection_status(db: Any, *, user_id: Any) -> list[dict]:
        return [
            {
                "server": _SERVER,
                "connected": True,
                "scopes": ["read", "write"],
                "expires_at": token_row.expires_at,
            },
            {
                "server": _SERVER2,
                "connected": False,
                "scopes": [],
                "expires_at": None,
            },
        ]

    monkeypatch.setattr(
        "app.api.mcp_oauth.oauth.list_connection_status",
        _fake_list_connection_status,
    )

    res = await ac.get(
        "/api/v1/mcp/oauth",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 200, res.text
    body = res.json()
    servers = body["servers"]

    assert len(servers) == 2
    assert servers[0]["server"] == _SERVER
    assert servers[1]["server"] == _SERVER2

    # acme-mcp is connected.
    acme = servers[0]
    assert acme["connected"] is True
    assert "read" in acme["scopes"]
    assert acme["expires_at"] is not None

    # beta-mcp is not connected.
    beta = servers[1]
    assert beta["connected"] is False
    assert beta["scopes"] == []
    assert beta["expires_at"] is None

    # No token bytes in response — access_token / refresh_token must be absent.
    raw_text = res.text
    assert "access_token" not in raw_text
    assert "refresh_token" not in raw_text
    assert "fake-access-token" not in raw_text


@pytest.mark.integration
async def test_list_mcp_oauth_unauthed_returns_401(
    anon_client: AsyncClient,
) -> None:
    """GET /mcp/oauth without auth → 401."""
    res = await anon_client.get("/api/v1/mcp/oauth")
    assert res.status_code == 401, res.text


@pytest.mark.integration
async def test_list_mcp_oauth_empty_when_no_servers_configured(
    authed_client: tuple[AsyncClient, str, User],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """GET /mcp/oauth when gateway has no OAuth servers → empty list."""
    ac, token, _user = authed_client

    async def _fake_list_connection_status(db: Any, *, user_id: Any) -> list[dict]:
        return []

    monkeypatch.setattr(
        "app.api.mcp_oauth.oauth.list_connection_status",
        _fake_list_connection_status,
    )

    res = await ac.get(
        "/api/v1/mcp/oauth",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 200, res.text
    assert res.json()["servers"] == []


# ---------------------------------------------------------------------------
# PR4d robustness: redirect URL composer (_append_query_params regression)
# ---------------------------------------------------------------------------
#
# These tests verify that the callback builds a well-formed Location header
# when the stored return_url already carries a query string or a fragment.
# Both the success path (mcp_connected) and the error path (mcp_error) are
# covered for each case.
#
# They stub the same oauth helpers used by the existing PR4d tests above and
# do NOT hit the database — they run as regular (non-@integration) tests so
# they will always be collected regardless of marks.


_RETURN_URL_WITH_QUERY = "https://frontend.example.com/settings/connections?tab=mcp"
_RETURN_URL_WITH_FRAGMENT = "https://frontend.example.com/settings#mcp"


@pytest.mark.integration
async def test_callback_success_return_url_with_existing_query(
    authed_client: tuple[AsyncClient, str, User],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Success redirect: return_url with existing query → Location merges params, exactly one '?'."""
    ac, _token, user = authed_client

    async def _fake_get_state_return_url(db: Any, *, state: str) -> str | None:
        return _RETURN_URL_WITH_QUERY

    token_row = _make_token_row(user.id)

    async def _fake_exchange_code(
        db: Any, *, state: str, code: str, iss: str | None
    ) -> MCPOAuthToken:
        return token_row

    monkeypatch.setattr("app.api.mcp_oauth.oauth.get_state_return_url", _fake_get_state_return_url)
    monkeypatch.setattr("app.api.mcp_oauth.oauth.exchange_code", _fake_exchange_code)

    res = await ac.get(
        f"/api/v1/mcp/oauth/{_SERVER}/callback",
        params={"code": "c", "state": "s"},
        follow_redirects=False,
    )
    assert res.status_code == 302, res.text
    location = res.headers["location"]

    # Both the original query param AND the new status param must be present.
    assert "tab=mcp" in location, f"existing query param missing: {location!r}"
    assert "mcp_connected=" in location, f"mcp_connected missing: {location!r}"
    assert _SERVER in location

    # Exactly one '?' — no double-query-marker.
    assert location.count("?") == 1, f"malformed URL (multiple '?'): {location!r}"


@pytest.mark.integration
async def test_callback_error_return_url_with_existing_query(
    anon_client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Error redirect: return_url with existing query → Location merges params, exactly one '?'."""
    from app.errors import MCPOAuthExchangeError

    async def _fake_get_state_return_url(db: Any, *, state: str) -> str | None:
        return _RETURN_URL_WITH_QUERY

    async def _fake_exchange_code(
        db: Any, *, state: str, code: str, iss: str | None
    ) -> MCPOAuthToken:
        raise MCPOAuthExchangeError(
            message="token exchange failed",
            details={"as_error": "invalid_client", "server": _SERVER},
        )

    monkeypatch.setattr("app.api.mcp_oauth.oauth.get_state_return_url", _fake_get_state_return_url)
    monkeypatch.setattr("app.api.mcp_oauth.oauth.exchange_code", _fake_exchange_code)

    res = await anon_client.get(
        f"/api/v1/mcp/oauth/{_SERVER}/callback",
        params={"code": "bad", "state": "s"},
        follow_redirects=False,
    )
    assert res.status_code == 302, res.text
    location = res.headers["location"]

    assert "tab=mcp" in location, f"existing query param missing: {location!r}"
    assert "mcp_error=" in location, f"mcp_error missing: {location!r}"
    assert "server=" in location

    assert location.count("?") == 1, f"malformed URL (multiple '?'): {location!r}"


@pytest.mark.integration
async def test_callback_success_return_url_with_fragment(
    authed_client: tuple[AsyncClient, str, User],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Success redirect: return_url with #fragment → status param lands in query, not fragment."""
    ac, _token, user = authed_client

    async def _fake_get_state_return_url(db: Any, *, state: str) -> str | None:
        return _RETURN_URL_WITH_FRAGMENT

    token_row = _make_token_row(user.id)

    async def _fake_exchange_code(
        db: Any, *, state: str, code: str, iss: str | None
    ) -> MCPOAuthToken:
        return token_row

    monkeypatch.setattr("app.api.mcp_oauth.oauth.get_state_return_url", _fake_get_state_return_url)
    monkeypatch.setattr("app.api.mcp_oauth.oauth.exchange_code", _fake_exchange_code)

    res = await ac.get(
        f"/api/v1/mcp/oauth/{_SERVER}/callback",
        params={"code": "c", "state": "s"},
        follow_redirects=False,
    )
    assert res.status_code == 302, res.text
    location = res.headers["location"]

    # Fragment must be preserved at the end.
    assert "#mcp" in location, f"fragment missing: {location!r}"

    # The status param must appear in the query (before the fragment, or at least
    # not inside the fragment text).  The fragment must be the last component.
    fragment_start = location.index("#")
    query_part = location[:fragment_start]
    assert "mcp_connected=" in query_part, (
        f"mcp_connected swallowed into fragment — should be in query: {location!r}"
    )
    assert _SERVER in query_part


@pytest.mark.integration
async def test_callback_error_return_url_with_fragment(
    anon_client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Error redirect: return_url with #fragment → status param lands in query, not fragment."""
    from app.errors import MCPOAuthExchangeError

    async def _fake_get_state_return_url(db: Any, *, state: str) -> str | None:
        return _RETURN_URL_WITH_FRAGMENT

    async def _fake_exchange_code(
        db: Any, *, state: str, code: str, iss: str | None
    ) -> MCPOAuthToken:
        raise MCPOAuthExchangeError(
            message="token exchange failed",
            details={"as_error": "invalid_client", "server": _SERVER},
        )

    monkeypatch.setattr("app.api.mcp_oauth.oauth.get_state_return_url", _fake_get_state_return_url)
    monkeypatch.setattr("app.api.mcp_oauth.oauth.exchange_code", _fake_exchange_code)

    res = await anon_client.get(
        f"/api/v1/mcp/oauth/{_SERVER}/callback",
        params={"code": "bad", "state": "s"},
        follow_redirects=False,
    )
    assert res.status_code == 302, res.text
    location = res.headers["location"]

    assert "#mcp" in location, f"fragment missing: {location!r}"

    fragment_start = location.index("#")
    query_part = location[:fragment_start]
    assert "mcp_error=" in query_part, (
        f"mcp_error swallowed into fragment — should be in query: {location!r}"
    )
    assert "server=" in query_part
