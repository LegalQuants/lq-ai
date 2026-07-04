"""Integration tests for the backend admin tool-provider proxy (Donna #3).

The backend's ``/api/v1/admin/tool-providers*`` proxies the gateway's
``/admin/v1/tool-providers`` surface (runtime authority-source
enable/disable + key rotation). Unlike the provider-keys proxy
(``test_admin_provider_keys.py``), these endpoints ALSO write an
``audit_log`` row on every write (D1) — the gateway client here is a
fake (``AsyncMock``) injected via ``set_gateway_client`` so tests can
assert both the proxied response shape and the audit-row side effect
against the real test-DB session.

Covers:

* The is_admin gate (non-admin -> 403) on all four verbs
* GET shape: reshaped rows carry only the public contract fields
* POST enable -> 200 + exactly one ``tool_provider.enabled`` audit row
* PATCH -> 200 + exactly one ``tool_provider.updated`` audit row
* DELETE -> 204 empty body + exactly one ``tool_provider.disabled`` audit row
* 404 on an unknown type is short-circuited BEFORE the gateway is called
  (registry pre-check), on POST/PATCH/DELETE
* No secret ever appears in a response body
* Proxy call-through proof for hot-apply plumbing (see docstring on
  ``test_post_enable_calls_gateway_with_expected_body``)
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.clients.gateway import set_gateway_client
from app.db.session import get_db
from app.main import app
from app.models.audit import AuditLog
from app.models.user import User
from app.security import create_access_token, hash_password


def _override_get_db(db_session: AsyncSession):
    async def _override() -> AsyncIterator[AsyncSession]:
        yield db_session

    return _override


@pytest_asyncio.fixture
async def admin_user(db_session: AsyncSession) -> User:
    user = User(
        email=f"admin-{uuid.uuid4().hex[:8]}@example.com",
        display_name="Admin",
        hashed_password=hash_password("correct-horse-battery-staple"),
        is_admin=True,
        mfa_enabled=False,
        must_change_password=False,
    )
    db_session.add(user)
    await db_session.flush()
    return user


@pytest_asyncio.fixture
async def regular_user(db_session: AsyncSession) -> User:
    user = User(
        email=f"user-{uuid.uuid4().hex[:8]}@example.com",
        display_name="Regular",
        hashed_password=hash_password("correct-horse-battery-staple"),
        is_admin=False,
        mfa_enabled=False,
        must_change_password=False,
    )
    db_session.add(user)
    await db_session.flush()
    return user


def _bearer_for(user: User) -> str:
    return create_access_token(user.id, user.email, is_admin=user.is_admin)


@pytest.fixture
def admin_headers(admin_user: User) -> dict[str, str]:
    return {"Authorization": f"Bearer {_bearer_for(admin_user)}"}


@pytest.fixture
def non_admin_token(regular_user: User) -> str:
    return _bearer_for(regular_user)


@pytest.fixture
def fake_gateway() -> AsyncMock:
    """A fake GatewayClient — AsyncMock methods return canned secret-safe rows.

    Injected in place of the real ``GatewayClient`` via ``set_gateway_client``
    so these tests can assert on call args (proxy correctness) without a real
    gateway process, and so a gateway 4xx/hot-apply round trip is exercised
    at the gateway/GatewayClient layers instead (T2/T3 suites already cover
    those).
    """

    mock_gw = AsyncMock()
    mock_gw.list_tool_providers_admin.return_value = {"tool_providers": []}
    return mock_gw


@pytest_asyncio.fixture
async def client(db_session: AsyncSession, fake_gateway: AsyncMock) -> AsyncIterator[AsyncClient]:
    app.dependency_overrides[get_db] = _override_get_db(db_session)
    set_gateway_client(fake_gateway)  # type: ignore[arg-type]
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    set_gateway_client(None)
    app.dependency_overrides.pop(get_db, None)


# A canned secret-safe status row per the gateway contract:
# {type, name, enabled, has_key, key_required, egress_tier, source}
_EDGAR_ROW = {
    "type": "edgar",
    "name": "edgar-prod",
    "enabled": True,
    "has_key": False,
    "key_required": False,
    "egress_tier": 4,
    "source": "runtime",
}


def _assert_no_secret(body: object) -> None:
    """The status payload must never carry a full key / token field."""

    text = repr(body)
    for forbidden in ("api_key", "api_key_encrypted", "sk-", "plaintext", "cl-secret-token"):
        assert forbidden not in text, f"secret-like field {forbidden!r} leaked: {text}"


# ---------------------------------------------------------------------------
# Auth + admin gate
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_tool_providers_requires_auth(client: AsyncClient) -> None:
    res = await client.get("/api/v1/admin/tool-providers")
    assert res.status_code == 401


@pytest.mark.unit
async def test_get_requires_admin(client: AsyncClient, non_admin_token: str) -> None:
    r = await client.get(
        "/api/v1/admin/tool-providers",
        headers={"Authorization": f"Bearer {non_admin_token}"},
    )
    assert r.status_code == 403
    assert r.json()["detail"]["code"] == "forbidden"


@pytest.mark.unit
async def test_post_requires_admin(client: AsyncClient, non_admin_token: str) -> None:
    r = await client.post(
        "/api/v1/admin/tool-providers",
        json={"type": "edgar"},
        headers={"Authorization": f"Bearer {non_admin_token}"},
    )
    assert r.status_code == 403


@pytest.mark.unit
async def test_patch_requires_admin(client: AsyncClient, non_admin_token: str) -> None:
    r = await client.patch(
        "/api/v1/admin/tool-providers/edgar",
        json={"enabled": False},
        headers={"Authorization": f"Bearer {non_admin_token}"},
    )
    assert r.status_code == 403


@pytest.mark.unit
async def test_delete_requires_admin(client: AsyncClient, non_admin_token: str) -> None:
    r = await client.delete(
        "/api/v1/admin/tool-providers/edgar",
        headers={"Authorization": f"Bearer {non_admin_token}"},
    )
    assert r.status_code == 403


# ---------------------------------------------------------------------------
# GET — list shape
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_list_tool_providers_reshapes_rows(
    client: AsyncClient, admin_headers: dict[str, str], fake_gateway: AsyncMock
) -> None:
    fake_gateway.list_tool_providers_admin.return_value = {
        "tool_providers": [
            {**_EDGAR_ROW, "source": "runtime"},
        ]
    }
    r = await client.get("/api/v1/admin/tool-providers", headers=admin_headers)
    assert r.status_code == 200
    body = r.json()
    row = body["tool_providers"][0]
    assert row == {
        "type": "edgar",
        "enabled": True,
        "name": "edgar-prod",
        "has_key": False,
        "key_required": False,
        "egress_tier": 4,
    }
    assert "source" not in row
    _assert_no_secret(body)


# ---------------------------------------------------------------------------
# POST — enable + audit
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_post_unknown_type_is_404_without_calling_gateway(
    client: AsyncClient, admin_headers: dict[str, str], fake_gateway: AsyncMock
) -> None:
    r = await client.post(
        "/api/v1/admin/tool-providers", json={"type": "westlaw"}, headers=admin_headers
    )
    assert r.status_code == 404
    assert not fake_gateway.set_tool_provider.called


@pytest.mark.unit
async def test_post_enable_writes_audit_row(
    client: AsyncClient,
    admin_headers: dict[str, str],
    db_session: AsyncSession,
    fake_gateway: AsyncMock,
) -> None:
    fake_gateway.set_tool_provider.return_value = dict(_EDGAR_ROW)
    r = await client.post(
        "/api/v1/admin/tool-providers", json={"type": "edgar"}, headers=admin_headers
    )
    assert r.status_code == 200
    _assert_no_secret(r.json())
    rows = (
        (
            await db_session.execute(
                select(AuditLog).where(AuditLog.action == "tool_provider.enabled")
            )
        )
        .scalars()
        .all()
    )
    assert len(rows) == 1
    assert rows[0].resource_id == "edgar"
    assert rows[0].resource_type == "tool_provider"


@pytest.mark.unit
async def test_post_enable_calls_gateway_with_expected_body(
    client: AsyncClient, admin_headers: dict[str, str], fake_gateway: AsyncMock
) -> None:
    """Proxy call-through proof of hot-apply plumbing.

    The gateway's real ``POST /admin/v1/tool-providers`` write persists the
    entry to ``gateway.yaml`` and hot-applies the rebuilt adapter — that
    round trip is proven at the gateway boundary (T2 Step 6: gateway suite
    hot-apply integration test) and at the GatewayClient layer (T3). What
    THIS layer owns is faithfully forwarding the admin's request body to the
    gateway unchanged, which is what this test asserts.
    """

    fake_gateway.set_tool_provider.return_value = {
        "type": "courtlistener",
        "name": "courtlistener-prod",
        "enabled": True,
        "has_key": True,
        "key_required": True,
        "egress_tier": 3,
        "source": "runtime",
    }
    r = await client.post(
        "/api/v1/admin/tool-providers",
        json={"type": "courtlistener", "api_key": "cl-secret-token"},
        headers=admin_headers,
    )
    assert r.status_code == 200
    _assert_no_secret(r.json())
    fake_gateway.set_tool_provider.assert_awaited_once_with(
        {"type": "courtlistener", "api_key": "cl-secret-token"}
    )


# ---------------------------------------------------------------------------
# PATCH — update + audit
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_patch_unknown_type_is_404_without_calling_gateway(
    client: AsyncClient, admin_headers: dict[str, str], fake_gateway: AsyncMock
) -> None:
    r = await client.patch(
        "/api/v1/admin/tool-providers/westlaw", json={"enabled": False}, headers=admin_headers
    )
    assert r.status_code == 404
    assert not fake_gateway.patch_tool_provider.called


@pytest.mark.unit
async def test_patch_writes_audit_row(
    client: AsyncClient,
    admin_headers: dict[str, str],
    db_session: AsyncSession,
    fake_gateway: AsyncMock,
) -> None:
    fake_gateway.patch_tool_provider.return_value = {**_EDGAR_ROW, "enabled": False}
    r = await client.patch(
        "/api/v1/admin/tool-providers/edgar", json={"enabled": False}, headers=admin_headers
    )
    assert r.status_code == 200
    body = r.json()
    assert body["enabled"] is False
    _assert_no_secret(body)
    rows = (
        (
            await db_session.execute(
                select(AuditLog).where(AuditLog.action == "tool_provider.updated")
            )
        )
        .scalars()
        .all()
    )
    assert len(rows) == 1
    assert rows[0].resource_id == "edgar"
    fake_gateway.patch_tool_provider.assert_awaited_once_with("edgar", {"enabled": False})


# ---------------------------------------------------------------------------
# DELETE — disable + audit + 204
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_delete_unknown_type_is_404_without_calling_gateway(
    client: AsyncClient, admin_headers: dict[str, str], fake_gateway: AsyncMock
) -> None:
    r = await client.delete("/api/v1/admin/tool-providers/westlaw", headers=admin_headers)
    assert r.status_code == 404
    assert not fake_gateway.delete_tool_provider.called


@pytest.mark.unit
async def test_delete_is_204_empty(
    client: AsyncClient, admin_headers: dict[str, str], fake_gateway: AsyncMock
) -> None:
    r = await client.delete("/api/v1/admin/tool-providers/edgar", headers=admin_headers)
    assert r.status_code == 204
    assert r.content == b""


@pytest.mark.unit
async def test_delete_writes_audit_row(
    client: AsyncClient,
    admin_headers: dict[str, str],
    db_session: AsyncSession,
    fake_gateway: AsyncMock,
) -> None:
    r = await client.delete("/api/v1/admin/tool-providers/edgar", headers=admin_headers)
    assert r.status_code == 204
    rows = (
        (
            await db_session.execute(
                select(AuditLog).where(AuditLog.action == "tool_provider.disabled")
            )
        )
        .scalars()
        .all()
    )
    assert len(rows) == 1
    assert rows[0].resource_id == "edgar"
    fake_gateway.delete_tool_provider.assert_awaited_once_with("edgar")
