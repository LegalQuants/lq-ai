"""Integration tests for Wave B endpoints — PRD §3.13 + §5.5 + §1.7.

* GET /inference/current-tier — looks up tier from gateway /v1/models.
* GET /inference/tier-config — proxies gateway tier-config.
* GET /admin/tier-policy + PATCH /admin/tier-policy — admin proxy with audit.
* GET /admin/usage — aggregates inference_routing_log.
* GET /chats/search — FTS over chats.title_tsv + messages.content_tsv.

Gateway calls are mocked via AsyncMock; the FTS query runs against the
real Postgres SAVEPOINT-scoped DB so the generated columns + GIN
indexes get exercised end-to-end.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Callable
from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.clients.gateway import GatewayClient, get_gateway_client
from app.db.session import get_db
from app.main import app
from app.models import AuditLog, User
from app.models.chat import Chat, Message
from app.models.inference import InferenceRoutingLog
from app.security import create_access_token, hash_password


def _override_get_db(db_session: AsyncSession) -> Callable[[], AsyncIterator[AsyncSession]]:
    async def _override() -> AsyncIterator[AsyncSession]:
        yield db_session

    return _override


@pytest_asyncio.fixture
async def admin_user(db_session: AsyncSession) -> User:
    user = User(
        email=f"waveb-admin-{uuid.uuid4().hex[:8]}@example.com",
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
async def caller(db_session: AsyncSession) -> User:
    user = User(
        email=f"waveb-{uuid.uuid4().hex[:8]}@example.com",
        display_name="Caller",
        hashed_password=hash_password("correct-horse-battery-staple"),
        is_admin=False,
        mfa_enabled=False,
        must_change_password=False,
    )
    db_session.add(user)
    await db_session.flush()
    return user


def _bearer(user: User) -> dict[str, str]:
    token = create_access_token(user.id, user.email, is_admin=user.is_admin)
    return {"Authorization": f"Bearer {token}"}


def _client_with(*, db_session: AsyncSession, gateway_mock: AsyncMock | None = None) -> AsyncClient:
    app.dependency_overrides[get_db] = _override_get_db(db_session)
    if gateway_mock is not None:
        app.dependency_overrides[get_gateway_client] = lambda: gateway_mock
    transport = ASGITransport(app=app)
    return AsyncClient(transport=transport, base_url="http://test")


def _cleanup() -> None:
    app.dependency_overrides.pop(get_db, None)
    app.dependency_overrides.pop(get_gateway_client, None)


# ---------------------------------------------------------------------------
# /inference/current-tier
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_current_tier_returns_matching_entry(db_session: AsyncSession, caller: User) -> None:
    gateway = AsyncMock(spec=GatewayClient)
    gateway.list_models.return_value = {
        "object": "list",
        "data": [
            {
                "id": "anthropic-prod/claude-sonnet-4-6",
                "owned_by": "anthropic-prod",
                "provider_type": "anthropic",
                "lq_ai_kind": "provider_native",
                "routed_inference_tier": 3,
            },
            {
                "id": "openai-prod/gpt-4o-mini",
                "owned_by": "openai-prod",
                "provider_type": "openai",
                "lq_ai_kind": "provider_native",
                "routed_inference_tier": 4,
            },
            {
                "id": "fast",
                "lq_ai_kind": "alias",
                "lq_ai_resolves_to": "anthropic-prod/claude-sonnet-4-6",
                "routed_inference_tier": 3,
            },
        ],
    }

    try:
        async with _client_with(db_session=db_session, gateway_mock=gateway) as client:
            resp = await client.get(
                "/api/v1/inference/current-tier",
                params={"provider": "openai-prod", "model": "gpt-4o-mini"},
                headers=_bearer(caller),
            )
    finally:
        _cleanup()

    assert resp.status_code == 200
    body = resp.json()
    assert body["routed_inference_tier"] == 4
    assert body["routed_provider_type"] == "openai"
    assert "openai-prod" in body["explanation"]


@pytest.mark.integration
async def test_current_tier_unknown_pair_returns_404(
    db_session: AsyncSession, caller: User
) -> None:
    gateway = AsyncMock(spec=GatewayClient)
    gateway.list_models.return_value = {"object": "list", "data": []}

    try:
        async with _client_with(db_session=db_session, gateway_mock=gateway) as client:
            resp = await client.get(
                "/api/v1/inference/current-tier",
                params={"provider": "unknown", "model": "ghost"},
                headers=_bearer(caller),
            )
    finally:
        _cleanup()

    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# /inference/tier-config
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_tier_config_returns_policy(db_session: AsyncSession, caller: User) -> None:
    gateway = AsyncMock(spec=GatewayClient)
    gateway.get_tier_config.return_value = {
        "tier_policy": {
            "allowed_tiers_global": [1, 2, 3],
            "default_minimum_tier": 3,
            "privileged_minimum_tier": 2,
            "warn_on_tiers": [4, 5],
        }
    }

    try:
        async with _client_with(db_session=db_session, gateway_mock=gateway) as client:
            resp = await client.get("/api/v1/inference/tier-config", headers=_bearer(caller))
    finally:
        _cleanup()

    assert resp.status_code == 200
    body = resp.json()
    assert body["allowed_tiers_global"] == [1, 2, 3]
    assert body["default_minimum_tier"] == 3


# ---------------------------------------------------------------------------
# /admin/tier-policy
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_admin_tier_policy_requires_admin(db_session: AsyncSession, caller: User) -> None:
    gateway = AsyncMock(spec=GatewayClient)
    try:
        async with _client_with(db_session=db_session, gateway_mock=gateway) as client:
            resp = await client.get("/api/v1/admin/tier-policy", headers=_bearer(caller))
    finally:
        _cleanup()
    assert resp.status_code == 403


@pytest.mark.integration
async def test_admin_tier_policy_patch_writes_audit(
    db_session: AsyncSession, admin_user: User
) -> None:
    gateway = AsyncMock(spec=GatewayClient)
    gateway.get_tier_config.return_value = {
        "tier_policy": {
            "allowed_tiers_global": [1, 2, 3, 4],
            "default_minimum_tier": 4,
            "privileged_minimum_tier": 3,
            "warn_on_tiers": [4, 5],
        }
    }
    gateway.patch_tier_config.return_value = {
        "tier_policy": {
            "allowed_tiers_global": [1, 2, 3],
            "default_minimum_tier": 3,
            "privileged_minimum_tier": 3,
            "warn_on_tiers": [4, 5],
        }
    }

    try:
        async with _client_with(db_session=db_session, gateway_mock=gateway) as client:
            resp = await client.patch(
                "/api/v1/admin/tier-policy",
                headers=_bearer(admin_user),
                json={
                    "allowed_tiers_global": [1, 2, 3],
                    "default_minimum_tier": 3,
                },
            )
    finally:
        _cleanup()

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["allowed_tiers_global"] == [1, 2, 3]
    assert body["default_minimum_tier"] == 3

    audit = (
        await db_session.execute(select(AuditLog).where(AuditLog.action == "tier_policy.updated"))
    ).scalar_one()
    assert audit.details is not None
    assert audit.details["before"]["default_minimum_tier"] == 4
    assert audit.details["after"]["default_minimum_tier"] == 3


@pytest.mark.integration
async def test_admin_tier_policy_patch_noop_skips_audit(
    db_session: AsyncSession, admin_user: User
) -> None:
    """Empty PATCH body returns the current state without an audit row."""

    gateway = AsyncMock(spec=GatewayClient)
    gateway.get_tier_config.return_value = {
        "tier_policy": {
            "allowed_tiers_global": [1, 2, 3, 4],
            "default_minimum_tier": 4,
            "privileged_minimum_tier": 3,
            "warn_on_tiers": [4, 5],
        }
    }

    try:
        async with _client_with(db_session=db_session, gateway_mock=gateway) as client:
            resp = await client.patch(
                "/api/v1/admin/tier-policy",
                headers=_bearer(admin_user),
                json={},
            )
    finally:
        _cleanup()

    assert resp.status_code == 200
    # patch_tier_config should NOT have been called.
    gateway.patch_tier_config.assert_not_called()
    audit = (
        (await db_session.execute(select(AuditLog).where(AuditLog.action == "tier_policy.updated")))
        .scalars()
        .all()
    )
    assert audit == []


# ---------------------------------------------------------------------------
# /admin/usage
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_admin_usage_aggregates_by_provider(
    db_session: AsyncSession, admin_user: User
) -> None:
    """Three log rows across two providers; group_by=provider returns 2 rows."""

    for provider, tokens_in, tokens_out, cost in [
        ("anthropic-prod", 100, 50, Decimal("0.0050")),
        ("anthropic-prod", 200, 80, Decimal("0.0100")),
        ("openai-prod", 150, 75, Decimal("0.0030")),
    ]:
        db_session.add(
            InferenceRoutingLog(
                user_id=admin_user.id,
                routed_provider=provider,
                routed_model="m",
                routed_inference_tier=3,
                tokens_in=tokens_in,
                tokens_out=tokens_out,
                cost_estimate=cost,
            )
        )
    await db_session.flush()

    try:
        async with _client_with(db_session=db_session) as client:
            resp = await client.get(
                "/api/v1/admin/usage",
                headers=_bearer(admin_user),
                params={"group_by": "provider"},
            )
    finally:
        _cleanup()

    assert resp.status_code == 200, resp.text
    body = resp.json()
    by_group = {row["group_key"]: row for row in body["rows"]}
    assert by_group["anthropic-prod"]["request_count"] == 2
    assert by_group["anthropic-prod"]["tokens_in_sum"] == 300
    assert by_group["anthropic-prod"]["tokens_out_sum"] == 130
    assert by_group["openai-prod"]["request_count"] == 1
    assert body["total_request_count"] == 3
    assert body["total_tokens_in"] == 450


@pytest.mark.integration
async def test_admin_usage_excludes_refused(db_session: AsyncSession, admin_user: User) -> None:
    db_session.add(
        InferenceRoutingLog(
            user_id=admin_user.id,
            routed_provider="anthropic-prod",
            routed_model="m",
            routed_inference_tier=3,
            tokens_in=10,
            tokens_out=5,
            refused=True,
            refusal_reason="tier_below_minimum",
        )
    )
    db_session.add(
        InferenceRoutingLog(
            user_id=admin_user.id,
            routed_provider="anthropic-prod",
            routed_model="m",
            routed_inference_tier=3,
            tokens_in=10,
            tokens_out=5,
        )
    )
    await db_session.flush()

    try:
        async with _client_with(db_session=db_session) as client:
            resp = await client.get("/api/v1/admin/usage", headers=_bearer(admin_user))
    finally:
        _cleanup()

    assert resp.status_code == 200
    assert resp.json()["total_request_count"] == 1


@pytest.mark.integration
async def test_admin_usage_invalid_group_by_returns_422(
    db_session: AsyncSession, admin_user: User
) -> None:
    try:
        async with _client_with(db_session=db_session) as client:
            resp = await client.get(
                "/api/v1/admin/usage",
                headers=_bearer(admin_user),
                params={"group_by": "made-up"},
            )
    finally:
        _cleanup()
    assert resp.status_code == 422


@pytest.mark.integration
async def test_admin_usage_requires_admin(db_session: AsyncSession, caller: User) -> None:
    try:
        async with _client_with(db_session=db_session) as client:
            resp = await client.get("/api/v1/admin/usage", headers=_bearer(caller))
    finally:
        _cleanup()
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# /chats/search
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_chats_search_title_and_message_hits(db_session: AsyncSession, caller: User) -> None:
    """A title hit + a message hit both return. The message gets a snippet."""

    title_chat = Chat(owner_id=caller.id, title="Onboarding the contractor")
    db_session.add(title_chat)
    msg_chat = Chat(owner_id=caller.id, title="Random conversation")
    db_session.add(msg_chat)
    await db_session.flush()
    db_session.add(
        Message(
            chat_id=msg_chat.id,
            role="user",
            content="What's the latest update on the contractor onboarding flow?",
        )
    )
    await db_session.flush()

    try:
        async with _client_with(db_session=db_session) as client:
            resp = await client.get(
                "/api/v1/chats/search",
                params={"q": "contractor onboarding"},
                headers=_bearer(caller),
            )
    finally:
        _cleanup()

    assert resp.status_code == 200, resp.text
    body = resp.json()
    sources = {hit["match_source"] for hit in body["items"]}
    assert sources == {"title", "message"}
    message_hit = next(h for h in body["items"] if h["match_source"] == "message")
    # ts_headline wraps matches in <b>...</b> by default.
    assert "<b>" in message_hit["snippet"]


@pytest.mark.integration
async def test_chats_search_excludes_archived(db_session: AsyncSession, caller: User) -> None:
    chat = Chat(
        owner_id=caller.id,
        title="Archived NDA discussion",
        archived_at=datetime.now(UTC),
    )
    db_session.add(chat)
    await db_session.flush()

    try:
        async with _client_with(db_session=db_session) as client:
            resp = await client.get(
                "/api/v1/chats/search",
                params={"q": "NDA"},
                headers=_bearer(caller),
            )
    finally:
        _cleanup()

    assert resp.status_code == 200
    assert resp.json()["items"] == []


@pytest.mark.integration
async def test_chats_search_owner_scoped(db_session: AsyncSession, caller: User) -> None:
    """Other user's chats should never appear in the caller's results."""

    other = User(
        email=f"other-{uuid.uuid4().hex[:8]}@example.com",
        display_name="Other",
        hashed_password=hash_password("correct-horse-battery-staple"),
        is_admin=False,
    )
    db_session.add(other)
    await db_session.flush()
    other_chat = Chat(owner_id=other.id, title="Cross-user secret NDA stuff")
    db_session.add(other_chat)
    await db_session.flush()

    try:
        async with _client_with(db_session=db_session) as client:
            resp = await client.get(
                "/api/v1/chats/search",
                params={"q": "secret"},
                headers=_bearer(caller),
            )
    finally:
        _cleanup()

    assert resp.status_code == 200
    assert resp.json()["items"] == []
