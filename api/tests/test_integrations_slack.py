"""Integration tests for M3-D1's slack-bridge persistence endpoint.

Covers ``POST /api/v1/integrations/slack/workspaces``:

* Auth — valid bridge bearer → 201; missing → 401; wrong → 401;
  unset operator token on the api → 500.
* Upsert semantics — re-POSTing the same ``team_id`` replaces the
  encrypted bot token + scope + installer; resurrects soft-deleted
  rows; does NOT move ``installed_at``.
* Encryption roundtrip — the persisted ``bot_token_encrypted`` value
  decrypts under the configured master key and is NOT the plaintext.
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
from app.models.slack_workspace import SlackWorkspace
from app.security.encryption import BridgeTokenEncryptor, generate_master_key

BRIDGE_TOKEN = "bridge-token-fixture-value"


def _override_get_db(db_session: AsyncSession):
    async def _override() -> AsyncIterator[AsyncSession]:
        yield db_session

    return _override


@pytest_asyncio.fixture
async def configured_settings(monkeypatch: pytest.MonkeyPatch) -> str:
    """Set both bridge env vars + clear the Settings cache for the test."""
    master_key = generate_master_key()
    monkeypatch.setenv("LQ_AI_BRIDGE_TOKEN", BRIDGE_TOKEN)
    monkeypatch.setenv("LQ_AI_BRIDGE_MASTER_KEY", master_key)
    get_settings.cache_clear()
    yield master_key
    get_settings.cache_clear()


@pytest_asyncio.fixture
async def client(
    db_session: AsyncSession,
    configured_settings: str,
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
    """Client where the operator has NOT set ``LQ_AI_BRIDGE_TOKEN``."""
    monkeypatch.delenv("LQ_AI_BRIDGE_TOKEN", raising=False)
    monkeypatch.delenv("LQ_AI_BRIDGE_MASTER_KEY", raising=False)
    get_settings.cache_clear()
    app.dependency_overrides[get_db] = _override_get_db(db_session)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.pop(get_db, None)
    get_settings.cache_clear()


def _workspace_body(**overrides: str) -> dict[str, str]:
    base = {
        "team_id": "T01234567",
        "team_name": "Acme Legal",
        "bot_token": "xoxb-fixture-bot-token",
        "bot_user_id": "U99999999",
        "installer_slack_user_id": "U11111111",
        "scope": "commands,chat:write",
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_post_workspaces_with_valid_bearer_returns_201(
    client: AsyncClient,
) -> None:
    res = await client.post(
        "/api/v1/integrations/slack/workspaces",
        headers={"Authorization": f"Bearer {BRIDGE_TOKEN}"},
        json=_workspace_body(),
    )
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["team_id"] == "T01234567"
    assert body["team_name"] == "Acme Legal"
    assert body["bot_user_id"] == "U99999999"
    assert body["installer_slack_user_id"] == "U11111111"
    assert body["scope"] == "commands,chat:write"
    assert "bot_token" not in body  # response omits ciphertext + plaintext


@pytest.mark.integration
async def test_post_workspaces_without_bearer_returns_401(
    client: AsyncClient,
) -> None:
    res = await client.post(
        "/api/v1/integrations/slack/workspaces",
        json=_workspace_body(),
    )
    assert res.status_code == 401


@pytest.mark.integration
async def test_post_workspaces_with_wrong_bearer_returns_401(
    client: AsyncClient,
) -> None:
    res = await client.post(
        "/api/v1/integrations/slack/workspaces",
        headers={"Authorization": "Bearer not-the-real-token"},
        json=_workspace_body(),
    )
    assert res.status_code == 401


@pytest.mark.integration
async def test_post_workspaces_when_bridge_token_unset_returns_500(
    unconfigured_client: AsyncClient,
) -> None:
    """Operator misconfiguration — refuse traffic rather than running open."""
    res = await unconfigured_client.post(
        "/api/v1/integrations/slack/workspaces",
        headers={"Authorization": "Bearer anything"},
        json=_workspace_body(),
    )
    assert res.status_code == 500


@pytest.mark.integration
async def test_post_workspaces_with_malformed_authorization_header_returns_401(
    client: AsyncClient,
) -> None:
    """``Authorization: bridge-token`` (no Bearer prefix) is rejected."""
    res = await client.post(
        "/api/v1/integrations/slack/workspaces",
        headers={"Authorization": BRIDGE_TOKEN},
        json=_workspace_body(),
    )
    assert res.status_code == 401


# ---------------------------------------------------------------------------
# Upsert
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_post_workspaces_upserts_on_team_id(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """Re-POSTing the same team_id replaces token + scope + installer."""
    first = await client.post(
        "/api/v1/integrations/slack/workspaces",
        headers={"Authorization": f"Bearer {BRIDGE_TOKEN}"},
        json=_workspace_body(),
    )
    assert first.status_code == 201
    first_id = first.json()["id"]

    second = await client.post(
        "/api/v1/integrations/slack/workspaces",
        headers={"Authorization": f"Bearer {BRIDGE_TOKEN}"},
        json=_workspace_body(
            team_name="Acme Legal (renamed)",
            bot_token="xoxb-rotated-fixture-token",
            installer_slack_user_id="U22222222",
            scope="commands,chat:write,channels:read",
        ),
    )
    assert second.status_code == 201
    assert second.json()["id"] == first_id  # same row
    assert second.json()["team_name"] == "Acme Legal (renamed)"
    assert second.json()["installer_slack_user_id"] == "U22222222"
    assert second.json()["scope"] == "commands,chat:write,channels:read"

    rows = (await db_session.execute(select(SlackWorkspace))).scalars().all()
    assert len(rows) == 1


@pytest.mark.integration
async def test_post_workspaces_resurrects_soft_deleted_row(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    res = await client.post(
        "/api/v1/integrations/slack/workspaces",
        headers={"Authorization": f"Bearer {BRIDGE_TOKEN}"},
        json=_workspace_body(),
    )
    assert res.status_code == 201

    row = (
        await db_session.execute(
            select(SlackWorkspace).where(SlackWorkspace.team_id == "T01234567")
        )
    ).scalar_one()
    row.deleted_at = datetime.now(tz=UTC)
    await db_session.commit()

    revived = await client.post(
        "/api/v1/integrations/slack/workspaces",
        headers={"Authorization": f"Bearer {BRIDGE_TOKEN}"},
        json=_workspace_body(bot_token="xoxb-after-reinstall"),
    )
    assert revived.status_code == 201

    await db_session.refresh(row)
    assert row.deleted_at is None


# ---------------------------------------------------------------------------
# Encryption roundtrip
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_persisted_bot_token_is_encrypted_and_decrypts(
    client: AsyncClient,
    db_session: AsyncSession,
    configured_settings: str,
) -> None:
    res = await client.post(
        "/api/v1/integrations/slack/workspaces",
        headers={"Authorization": f"Bearer {BRIDGE_TOKEN}"},
        json=_workspace_body(),
    )
    assert res.status_code == 201

    row = (
        await db_session.execute(
            select(SlackWorkspace).where(SlackWorkspace.team_id == "T01234567")
        )
    ).scalar_one()

    assert isinstance(row.bot_token_encrypted, bytes)
    assert b"xoxb-fixture-bot-token" not in row.bot_token_encrypted
    decrypted = BridgeTokenEncryptor(master_key=configured_settings).decrypt(
        row.bot_token_encrypted
    )
    assert decrypted == "xoxb-fixture-bot-token"
