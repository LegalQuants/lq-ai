"""Account-link acceptance through HTTP with real PostgreSQL transactions."""

from __future__ import annotations

import asyncio
import hashlib
import io
import json
import uuid
import zipfile
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock
from urllib.parse import parse_qs, urlsplit

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient, Response
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.api import slack_accounts
from app.config import get_settings
from app.db.session import get_db
from app.main import app
from app.models.audit import AuditLog
from app.models.slack_account import SlackAccountLink, SlackLinkRequest
from app.models.slack_workspace import SlackWorkspace
from app.models.user import User
from app.security import create_access_token
from app.workers.user_export import build_export_zip_for_test

pytestmark = pytest.mark.integration
BASE = "/api/v1/integrations/slack"
SERVICE = {"Authorization": "Bearer command-fixture"}
Linking = tuple[AsyncClient, dict[str, str], dict[str, str], SlackWorkspace]


@pytest_asyncio.fixture
async def linking(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> AsyncIterator[Linking]:
    monkeypatch.setenv("LQ_AI_SLACK_COMMAND_TOKEN", "command-fixture")
    monkeypatch.setenv("LQ_AI_BRIDGE_TOKEN", "installation-fixture")
    monkeypatch.setenv("LQ_AI_WEB_PUBLIC_URL", "https://lq.test")
    get_settings.cache_clear()
    users = [
        User(
            id=uuid.uuid4(),
            email=f"{n}@example.com",
            hashed_password="unused",
            role="admin",
            is_admin=True,
        )
        for n in ("alice", "bob")
    ]
    workspace = SlackWorkspace(
        team_id="T0123",
        team_name="Test Legal",
        bot_token_encrypted=b"encrypted",
        bot_user_id="U0123",
        installer_slack_user_id="U456",
        scope="commands",
    )
    db_session.add_all([*users, workspace])
    await db_session.commit()
    headers = [
        {
            "Authorization": f"Bearer {create_access_token(user_id=u.id, email=u.email, is_admin=True)}"
        }
        for u in users
    ]

    async def db_override() -> AsyncIterator[AsyncSession]:
        yield db_session

    app.dependency_overrides[get_db] = db_override
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="https://api.test"
        ) as client:
            yield client, headers[0], headers[1], workspace
    finally:
        app.dependency_overrides.pop(get_db, None)
        get_settings.cache_clear()


async def issue(client: AsyncClient, user: str = "U111", team: str = "T0123") -> str:
    response = await client.post(
        f"{BASE}/link-requests", headers=SERVICE, json={"team_id": team, "slack_user_id": user}
    )
    assert response.status_code == 201, response.text
    assert response.headers["cache-control"] == "no-store"
    url = urlsplit(response.json()["url"])
    assert (url.scheme, url.netloc, url.path, url.query) == (
        "https",
        "lq.test",
        "/lq-ai/slack/link",
        "",
    )
    return parse_qs(url.fragment)["token"][0]


async def test_link_preview_confirm_list_unlink_acceptance(
    linking: Linking, db_session: AsyncSession
) -> None:
    client, alice, bob, _ = linking
    token = await issue(client)
    stored = await db_session.scalar(select(SlackLinkRequest))
    assert stored is not None
    assert stored.token_hash == hashlib.sha256(token.encode()).hexdigest()
    for _ in range(2):
        result = await client.post(
            f"{BASE}/link-requests/preview", headers=alice, json={"token": token}
        )
        assert result.status_code == 200
        assert result.json()["slack_user_id"] == "U111"
        assert result.headers["cache-control"] == "no-store"
    # Crawlers/GETs and previews never bind or consume.
    assert (await client.get(f"{BASE}/link-requests/confirm", headers=alice)).status_code == 405
    assert (await client.get(f"{BASE}/account-links", headers=alice)).json() == []
    result = await client.post(
        f"{BASE}/link-requests/confirm", headers=alice, json={"token": token}
    )
    assert result.status_code == 200, result.text
    link_id = result.json()["id"]
    assert len((await client.get(f"{BASE}/account-links", headers=alice)).json()) == 1
    assert (await client.get(f"{BASE}/account-links", headers=bob)).json() == []
    assert (
        await client.post(f"{BASE}/link-requests/confirm", headers=bob, json={"token": token})
    ).status_code == 404
    assert (await client.delete(f"{BASE}/account-links/{link_id}", headers=bob)).status_code == 404
    # Issued before unlink, this request must also be revoked.
    pending = await issue(client)
    assert (
        await client.delete(f"{BASE}/account-links/{link_id}", headers=alice)
    ).status_code == 204
    assert (
        await client.post(f"{BASE}/link-requests/confirm", headers=bob, json={"token": pending})
    ).status_code == 404
    assert (await client.get(f"{BASE}/account-links", headers=alice)).json() == []
    fresh = await issue(client)
    assert (
        await client.post(f"{BASE}/link-requests/confirm", headers=alice, json={"token": fresh})
    ).status_code == 200
    audits = list(
        (await db_session.scalars(select(AuditLog).where(AuditLog.action.like("slack.%")))).all()
    )
    assert [a.action for a in audits].count("slack.account.link") == 2
    assert [a.action for a in audits].count("slack.account.unlink") == 1
    assert all(token not in str(a.details) and pending not in str(a.details) for a in audits)


async def test_expiry_replacement_conflict_and_workspace_isolation(
    linking: Linking, db_session: AsyncSession
) -> None:
    client, alice, bob, _ = linking
    old = await issue(client)
    token = await issue(client)
    assert (
        await client.post(f"{BASE}/link-requests/preview", headers=alice, json={"token": old})
    ).status_code == 404
    row = await db_session.scalar(select(SlackLinkRequest))
    assert row is not None
    row.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    await db_session.commit()
    assert (
        await client.post(f"{BASE}/link-requests/confirm", headers=alice, json={"token": token})
    ).status_code == 404
    token = await issue(client)
    assert (
        await client.post(f"{BASE}/link-requests/confirm", headers=alice, json={"token": token})
    ).status_code == 200
    token = await issue(client)
    assert (
        await client.post(f"{BASE}/link-requests/confirm", headers=bob, json={"token": token})
    ).status_code == 409
    other = SlackWorkspace(
        team_id="TOTHER",
        team_name="Other",
        bot_token_encrypted=b"encrypted",
        bot_user_id="UBOT",
        installer_slack_user_id="UINS",
        scope="commands",
    )
    db_session.add(other)
    await db_session.commit()
    token = await issue(client, team="TOTHER")
    assert (
        await client.post(f"{BASE}/link-requests/confirm", headers=bob, json={"token": token})
    ).status_code == 200


async def test_authority_is_scoped_and_extra_identity_is_rejected(
    linking: Linking, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, alice, _, _ = linking
    body = {"team_id": "T0123", "slack_user_id": "U111"}
    for headers in (
        {},
        alice,
        {"Authorization": "Bearer installation-fixture"},
        {"Authorization": "command-fixture"},
    ):
        assert (
            await client.post(f"{BASE}/link-requests", headers=headers, json=body)
        ).status_code == 401
    for extra in ({"user_id": str(uuid.uuid4())}, {"email": "alice@example.com"}):
        assert (
            await client.post(f"{BASE}/link-requests", headers=SERVICE, json=body | extra)
        ).status_code == 400
    token = await issue(client)
    for endpoint in ("preview", "confirm"):
        assert (
            await client.post(
                f"{BASE}/link-requests/{endpoint}", headers=SERVICE, json={"token": token}
            )
        ).status_code == 401
    monkeypatch.setenv("LQ_AI_SLACK_COMMAND_TOKEN", "")
    get_settings.cache_clear()
    assert (
        await client.post(f"{BASE}/link-requests", headers=SERVICE, json=body)
    ).status_code == 500


async def test_active_user_gate_and_unsafe_web_origin(
    linking: Linking, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, alice, _, _ = linking
    token = await issue(client)
    user = await db_session.scalar(select(User).where(User.email == "alice@example.com"))
    assert user is not None
    user.must_change_password = True
    await db_session.commit()
    for endpoint in ("preview", "confirm"):
        assert (
            await client.post(
                f"{BASE}/link-requests/{endpoint}", headers=alice, json={"token": token}
            )
        ).status_code == 403
    assert (await client.get(f"{BASE}/account-links", headers=alice)).status_code == 403
    for origin in ("", "http://evil.test", "https://lq.test?redirect=evil", "https://u:p@lq.test"):
        monkeypatch.setenv("LQ_AI_WEB_PUBLIC_URL", origin)
        get_settings.cache_clear()
        assert (
            await client.post(
                f"{BASE}/link-requests",
                headers=SERVICE,
                json={"team_id": "T0123", "slack_user_id": "U111"},
            )
        ).status_code == 500


async def test_invalid_inputs_do_not_echo_capabilities(linking: Linking) -> None:
    client, alice, _, _ = linking
    for token in ("sensitive-invalid-token", "a" * 10000, {"token": "sensitive-nested-token"}):
        result = await client.post(
            f"{BASE}/link-requests/confirm", headers=alice, json={"token": token}
        )
        assert result.status_code == 400
        assert "sensitive" not in result.text
        assert "a" * 100 not in result.text


async def test_mandatory_mfa_is_required(linking: Linking, monkeypatch: pytest.MonkeyPatch) -> None:
    client, alice, _, _ = linking
    token = await issue(client)
    monkeypatch.setenv("MFA_MANDATORY", "true")
    get_settings.cache_clear()
    for endpoint in ("preview", "confirm"):
        result = await client.post(
            f"{BASE}/link-requests/{endpoint}", headers=alice, json={"token": token}
        )
        assert result.status_code == 403
        assert result.json()["detail"]["code"] == "mfa_enrollment_required"


async def test_user_export_and_delete_cover_linked_accounts(
    linking: Linking, db_session: AsyncSession
) -> None:
    client, alice, bob, _ = linking
    for headers, slack_user in ((alice, "U111"), (bob, "U222")):
        token = await issue(client, user=slack_user)
        assert (
            await client.post(
                f"{BASE}/link-requests/confirm", headers=headers, json={"token": token}
            )
        ).status_code == 200
    user = await db_session.scalar(select(User).where(User.email == "alice@example.com"))
    assert user is not None
    archive = zipfile.ZipFile(io.BytesIO(await build_export_zip_for_test(db_session, user)))
    exported = json.loads(archive.read("slack_accounts.json"))
    assert len(exported) == 1
    assert exported[0]["slack_user_id"] == "U111"
    assert set(exported[0]) == {"id", "team_id", "team_name", "slack_user_id", "created_at"}
    await db_session.delete(user)
    await db_session.commit()
    remaining = (await db_session.scalars(select(SlackAccountLink.slack_user_id))).all()
    assert remaining == ["U222"]


async def test_disconnect_revokes_links_and_challenges_after_reinstall(
    linking: Linking, db_session: AsyncSession
) -> None:
    client, alice, _, workspace = linking
    token = await issue(client)
    assert (
        await client.post(f"{BASE}/link-requests/confirm", headers=alice, json={"token": token})
    ).status_code == 200
    pending = await issue(client)
    assert (
        await client.delete(f"/api/v1/admin/intake-bridges/slack/{workspace.id}", headers=alice)
    ).status_code == 204
    assert await db_session.scalar(select(func.count()).select_from(SlackAccountLink)) == 0
    assert (
        await client.post(
            f"{BASE}/link-requests",
            headers=SERVICE,
            json={"team_id": "T0123", "slack_user_id": "U111"},
        )
    ).status_code == 404
    # Simulate reviving the same install row. Old capabilities stay revoked.
    workspace.deleted_at = None
    await db_session.commit()
    assert (
        await client.post(f"{BASE}/link-requests/confirm", headers=alice, json={"token": pending})
    ).status_code == 404
    assert (await client.get(f"{BASE}/account-links", headers=alice)).json() == []


async def test_audit_failure_rolls_back_binding_and_consumption(
    linking: Linking, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, alice, _, _ = linking
    token = await issue(client)
    monkeypatch.setattr(
        slack_accounts, "audit_action", AsyncMock(side_effect=RuntimeError("audit unavailable"))
    )
    with pytest.raises(RuntimeError, match="audit unavailable"):
        await client.post(f"{BASE}/link-requests/confirm", headers=alice, json={"token": token})
    await db_session.rollback()
    assert await db_session.scalar(select(func.count()).select_from(SlackAccountLink)) == 0
    assert await db_session.scalar(select(func.count()).select_from(SlackLinkRequest)) == 1


async def test_concurrent_redemptions_one_winner(
    isolated_db_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Independent DB connections exercise locks and uniqueness, not one shared fixture session."""
    monkeypatch.setenv("LQ_AI_SLACK_COMMAND_TOKEN", "command-fixture")
    monkeypatch.setenv("LQ_AI_WEB_PUBLIC_URL", "https://lq.test")
    get_settings.cache_clear()
    engine = create_async_engine(isolated_db_url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)

    async def override() -> AsyncIterator[AsyncSession]:
        async with sessions() as db:
            yield db

    app.dependency_overrides[get_db] = override
    try:
        async with sessions() as db:
            user = User(id=uuid.uuid4(), email="race@example.com", hashed_password="unused")
            db.add_all(
                [
                    user,
                    SlackWorkspace(
                        team_id="T0123",
                        team_name="Test",
                        bot_token_encrypted=b"e",
                        bot_user_id="UBOT",
                        installer_slack_user_id="UINS",
                        scope="commands",
                    ),
                ]
            )
            await db.commit()
            headers = {
                "Authorization": f"Bearer {create_access_token(user_id=user.id, email=user.email, is_admin=False)}"
            }
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="https://api.test"
        ) as client:
            token = await issue(client)

            async def redeem() -> Response:
                return await client.post(
                    f"{BASE}/link-requests/confirm", headers=headers, json={"token": token}
                )

            results = await asyncio.gather(redeem(), redeem())
            assert sorted(r.status_code for r in results) == [200, 404]
        async with sessions() as db:
            assert await db.scalar(select(func.count()).select_from(SlackAccountLink)) == 1
            assert (
                await db.scalar(
                    select(func.count())
                    .select_from(AuditLog)
                    .where(AuditLog.action == "slack.account.link")
                )
                == 1
            )
    finally:
        app.dependency_overrides.pop(get_db, None)
        await engine.dispose()
        get_settings.cache_clear()
