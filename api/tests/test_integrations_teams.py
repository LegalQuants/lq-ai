"""Integration tests for M3-D3's teams-bridge persistence endpoint.

Covers ``POST /api/v1/integrations/teams/tenants``:

* Auth — valid bridge bearer → 201; missing → 401; wrong → 401;
  unset operator token on the api → 500.
* Upsert semantics — re-POSTing the same ``tenant_id`` refreshes the
  display name + installer OID + resurrects soft-deleted rows.
* The shared :func:`require_bridge_auth` dep is exercised through the
  same path as Slack (M3-D1) — this test pins that Teams sees identical
  auth behavior.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db.session import get_db
from app.main import app
from app.models.teams_tenant import TeamsTenant

BRIDGE_TOKEN = "bridge-token-fixture-value"


def _override_get_db(db_session: AsyncSession):
    async def _override() -> AsyncIterator[AsyncSession]:
        yield db_session

    return _override


@pytest_asyncio.fixture
async def configured_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LQ_AI_BRIDGE_TOKEN", BRIDGE_TOKEN)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest_asyncio.fixture
async def client(
    db_session: AsyncSession,
    configured_settings: None,
) -> AsyncIterator[AsyncClient]:
    app.dependency_overrides[get_db] = _override_get_db(db_session)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.pop(get_db, None)


@pytest_asyncio.fixture
async def unconfigured_client(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncIterator[AsyncClient]:
    monkeypatch.delenv("LQ_AI_BRIDGE_TOKEN", raising=False)
    get_settings.cache_clear()
    app.dependency_overrides[get_db] = _override_get_db(db_session)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.pop(get_db, None)
    get_settings.cache_clear()


def _tenant_body(**overrides: str) -> dict[str, str]:
    base = {
        "tenant_id": "00000000-0000-0000-0000-aaaaaaaaaaaa",
        "tenant_name": "Acme Legal LLP",
        "installer_oid": "00000000-0000-0000-0000-111111111111",
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_post_tenants_with_valid_bearer_returns_201(client: AsyncClient) -> None:
    res = await client.post(
        "/api/v1/integrations/teams/tenants",
        headers={"Authorization": f"Bearer {BRIDGE_TOKEN}"},
        json=_tenant_body(),
    )
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["tenant_id"] == "00000000-0000-0000-0000-aaaaaaaaaaaa"
    assert body["tenant_name"] == "Acme Legal LLP"
    assert body["installer_oid"] == "00000000-0000-0000-0000-111111111111"


@pytest.mark.integration
async def test_post_tenants_without_bearer_returns_401(client: AsyncClient) -> None:
    res = await client.post(
        "/api/v1/integrations/teams/tenants",
        json=_tenant_body(),
    )
    assert res.status_code == 401


@pytest.mark.integration
async def test_post_tenants_with_wrong_bearer_returns_401(client: AsyncClient) -> None:
    res = await client.post(
        "/api/v1/integrations/teams/tenants",
        headers={"Authorization": "Bearer not-the-real-token"},
        json=_tenant_body(),
    )
    assert res.status_code == 401


@pytest.mark.integration
async def test_post_tenants_when_bridge_token_unset_returns_500(
    unconfigured_client: AsyncClient,
) -> None:
    res = await unconfigured_client.post(
        "/api/v1/integrations/teams/tenants",
        headers={"Authorization": "Bearer anything"},
        json=_tenant_body(),
    )
    assert res.status_code == 500


# ---------------------------------------------------------------------------
# Upsert
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_post_tenants_upserts_on_tenant_id(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    first = await client.post(
        "/api/v1/integrations/teams/tenants",
        headers={"Authorization": f"Bearer {BRIDGE_TOKEN}"},
        json=_tenant_body(),
    )
    assert first.status_code == 201
    first_id = first.json()["id"]

    second = await client.post(
        "/api/v1/integrations/teams/tenants",
        headers={"Authorization": f"Bearer {BRIDGE_TOKEN}"},
        json=_tenant_body(
            tenant_name="Acme Legal LLP (renamed)",
            installer_oid="00000000-0000-0000-0000-222222222222",
        ),
    )
    assert second.status_code == 201
    assert second.json()["id"] == first_id
    assert second.json()["tenant_name"] == "Acme Legal LLP (renamed)"
    assert second.json()["installer_oid"] == "00000000-0000-0000-0000-222222222222"

    rows = (await db_session.execute(select(TeamsTenant))).scalars().all()
    assert len(rows) == 1


@pytest.mark.integration
async def test_post_tenants_resurrects_soft_deleted_row(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    res = await client.post(
        "/api/v1/integrations/teams/tenants",
        headers={"Authorization": f"Bearer {BRIDGE_TOKEN}"},
        json=_tenant_body(),
    )
    assert res.status_code == 201

    row = (
        await db_session.execute(
            select(TeamsTenant).where(
                TeamsTenant.tenant_id == "00000000-0000-0000-0000-aaaaaaaaaaaa"
            )
        )
    ).scalar_one()
    row.deleted_at = datetime.now(tz=UTC)
    await db_session.commit()

    revived = await client.post(
        "/api/v1/integrations/teams/tenants",
        headers={"Authorization": f"Bearer {BRIDGE_TOKEN}"},
        json=_tenant_body(),
    )
    assert revived.status_code == 201

    await db_session.refresh(row)
    assert row.deleted_at is None
