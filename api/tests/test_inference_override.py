"""Integration tests for ``POST /api/v1/inference/override-tier-floor``.

Wave D.1 T4 — admin-only re-run of a refused inference. Mirrors the
gateway-mock pattern used by ``test_chats_send_message.py`` (respx +
in-process ``GatewayClient`` injected via :func:`set_gateway_client`).

Test cases:
* Admin happy path — refusal + preceding user message exist; gateway
  returns a successful completion; backend persists a new
  ``kind='ai'`` row and writes an audit row carrying the reason.
* Member (non-admin) — 403 forbidden at the dependency gate before
  any state change.
* Audit row carries the override reason verbatim.
* Override against a non-refusal message — 404.
* Reason shorter than 10 chars — 422 (Pydantic field validation
  translates to a 400 via the project's global ``LQAIError`` handler;
  we accept either as evidence the schema-validation gate fires).
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Callable

import httpx
import pytest
import pytest_asyncio
import respx
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.clients.gateway import GatewayClient, set_gateway_client
from app.db.session import get_db
from app.main import app
from app.models.audit import AuditLog
from app.models.chat import Chat, Message
from app.models.user import User
from app.security import create_access_token, hash_password

pytestmark = pytest.mark.integration

GATEWAY_BASE = "http://test-gateway"
GATEWAY_KEY = "test-gw-key"


def _override_get_db(db_session: AsyncSession) -> Callable[[], AsyncIterator[AsyncSession]]:
    async def _override() -> AsyncIterator[AsyncSession]:
        yield db_session

    return _override


@pytest_asyncio.fixture
async def client(db_session: AsyncSession) -> AsyncIterator[AsyncClient]:
    """In-process AsyncClient with the GatewayClient stubbed for respx.

    Same shape as the chats-send-message fixture.
    """

    app.dependency_overrides[get_db] = _override_get_db(db_session)
    gw = GatewayClient(base_url=GATEWAY_BASE, gateway_key=GATEWAY_KEY)
    set_gateway_client(gw)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    set_gateway_client(None)
    await gw.aclose()
    app.dependency_overrides.pop(get_db, None)


@pytest_asyncio.fixture
async def admin_user(db_session: AsyncSession) -> User:
    user = User(
        email=f"admin-override-{uuid.uuid4().hex[:8]}@example.com",
        display_name="Override Admin",
        hashed_password=hash_password("correct-horse-battery-staple"),
        is_admin=True,
        role="admin",
        mfa_enabled=False,
        must_change_password=False,
    )
    db_session.add(user)
    await db_session.flush()
    return user


@pytest_asyncio.fixture
async def member_user(db_session: AsyncSession) -> User:
    user = User(
        email=f"member-override-{uuid.uuid4().hex[:8]}@example.com",
        display_name="Override Member",
        hashed_password=hash_password("correct-horse-battery-staple"),
        is_admin=False,
        role="member",
        mfa_enabled=False,
        must_change_password=False,
    )
    db_session.add(user)
    await db_session.flush()
    return user


def _bearer(user: User) -> str:
    return create_access_token(user.id, user.email, is_admin=user.is_admin)


def _h(user: User) -> dict[str, str]:
    return {"Authorization": f"Bearer {_bearer(user)}"}


@pytest_asyncio.fixture
async def sample_refusal_message(db_session: AsyncSession, admin_user: User) -> Message:
    """Create a chat with a preceding user message + a refusal row.

    The override path needs both: a ``kind='user'`` row to re-run, and
    a ``kind='refusal'`` row that the admin is overriding. We set
    explicit timestamps so the ``created_at`` ordering in the lookup
    SELECT resolves deterministically (in production the user row is
    flushed in a separate transaction before the gateway round-trip,
    so ``now()`` advances between the two).
    """

    from datetime import UTC, datetime, timedelta

    base = datetime.now(tz=UTC)

    chat = Chat(owner_id=admin_user.id, title="Refused exchange")
    db_session.add(chat)
    await db_session.flush()

    user_msg = Message(
        chat_id=chat.id,
        role="user",
        kind="user",
        content="Summarize this NDA in plain English.",
        applied_skills=[],
        created_at=base - timedelta(seconds=10),
    )
    db_session.add(user_msg)
    await db_session.flush()

    refusal = Message(
        chat_id=chat.id,
        role="assistant",
        kind="refusal",
        content="Refused: routed tier 4 is weaker than the project floor of tier 3.",
        applied_skills=[],
        error_code="tier_below_minimum",
        created_at=base,
    )
    db_session.add(refusal)
    await db_session.flush()
    return refusal


@pytest_asyncio.fixture
async def sample_ai_message(db_session: AsyncSession, admin_user: User) -> Message:
    """A normal ``kind='ai'`` assistant row — overriding this must 404."""

    chat = Chat(owner_id=admin_user.id, title="Normal exchange")
    db_session.add(chat)
    await db_session.flush()

    user_msg = Message(
        chat_id=chat.id,
        role="user",
        kind="user",
        content="Hello.",
        applied_skills=[],
    )
    db_session.add(user_msg)

    ai = Message(
        chat_id=chat.id,
        role="assistant",
        kind="ai",
        content="Hi back.",
        applied_skills=[],
    )
    db_session.add(ai)
    await db_session.flush()
    return ai


def _success_payload(content: str = "Re-run completed.") -> dict[str, object]:
    return {
        "id": "chatcmpl-override-1",
        "object": "chat.completion",
        "created": 1_700_000_000,
        "model": "claude-sonnet-4-6",
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 7, "completion_tokens": 5, "total_tokens": 12},
        "routed_inference_tier": 4,
        "routed_provider": "openai-prod",
        "cost_estimate": 0.00033,
    }


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


@respx.mock
async def test_override_admin_succeeds_creates_ai_message(
    client: AsyncClient,
    admin_user: User,
    sample_refusal_message: Message,
) -> None:
    """Admin override of a refusal returns a new ``kind='ai'`` message."""

    route = respx.post(f"{GATEWAY_BASE}/v1/chat/completions").mock(
        return_value=httpx.Response(200, json=_success_payload("Override worked."))
    )

    response = await client.post(
        "/api/v1/inference/override-tier-floor",
        json={
            "message_id": str(sample_refusal_message.id),
            "reason": "Urgent client request — risk-accepted by partner",
        },
        headers=_h(admin_user),
    )

    assert response.status_code == 200, response.text
    assert route.called

    # The gateway request must NOT carry a project floor or a per-call
    # minimum — both surfaces are nulled for the override turn.
    sent_body = route.calls[0].request.content.decode()
    assert "lq_ai_project_minimum_inference_tier" not in sent_body
    assert "minimum_inference_tier" not in sent_body

    body = response.json()
    assert body["ai_message"]["kind"] == "ai"
    assert body["ai_message"]["chat_id"] == str(sample_refusal_message.chat_id)
    assert body["ai_message"]["content"] == "Override worked."
    assert body["ai_message"]["routed_inference_tier"] == 4
    assert "routing_log_id" in body


# ---------------------------------------------------------------------------
# Authorization
# ---------------------------------------------------------------------------


async def test_override_member_returns_403(
    client: AsyncClient,
    member_user: User,
    sample_refusal_message: Message,
) -> None:
    """Non-admin role hits the ``AdminUser`` dependency gate."""

    response = await client.post(
        "/api/v1/inference/override-tier-floor",
        json={
            "message_id": str(sample_refusal_message.id),
            "reason": "Trying as a non-admin member account",
        },
        headers=_h(member_user),
    )

    assert response.status_code == 403


# ---------------------------------------------------------------------------
# Audit row
# ---------------------------------------------------------------------------


@respx.mock
async def test_override_writes_audit_row_with_reason(
    client: AsyncClient,
    admin_user: User,
    sample_refusal_message: Message,
    db_session: AsyncSession,
) -> None:
    """The override audit row carries the operator-supplied reason verbatim."""

    respx.post(f"{GATEWAY_BASE}/v1/chat/completions").mock(
        return_value=httpx.Response(200, json=_success_payload())
    )
    reason = "Urgent client request — risk-accepted by partner"

    response = await client.post(
        "/api/v1/inference/override-tier-floor",
        json={"message_id": str(sample_refusal_message.id), "reason": reason},
        headers=_h(admin_user),
    )
    assert response.status_code == 200, response.text

    audit = await db_session.execute(
        select(AuditLog).where(
            AuditLog.action == "inference.tier_floor_overridden",
            AuditLog.user_id == admin_user.id,
        )
    )
    row = audit.scalar_one_or_none()
    assert row is not None
    assert row.resource_type == "message"
    assert row.resource_id == str(sample_refusal_message.id)
    assert row.details is not None
    assert row.details["reason"] == reason
    assert row.details["chat_id"] == str(sample_refusal_message.chat_id)


# ---------------------------------------------------------------------------
# Wrong-kind target
# ---------------------------------------------------------------------------


async def test_override_non_refusal_message_returns_404(
    client: AsyncClient,
    admin_user: User,
    sample_ai_message: Message,
) -> None:
    """Overriding a ``kind='ai'`` row (or anything not ``refusal``) is 404."""

    response = await client.post(
        "/api/v1/inference/override-tier-floor",
        json={
            "message_id": str(sample_ai_message.id),
            "reason": "Test reason long enough to pass validation",
        },
        headers=_h(admin_user),
    )

    assert response.status_code == 404


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


async def test_override_short_reason_returns_validation_error(
    client: AsyncClient,
    admin_user: User,
    sample_refusal_message: Message,
) -> None:
    """``reason`` shorter than 10 chars is rejected at schema validation.

    The project's global ``LQAIError`` handler translates Pydantic
    validation errors to HTTP 400 (see :mod:`app.errors`); we accept
    400 or 422 here so the test doesn't lock the exact handler shape.
    """

    response = await client.post(
        "/api/v1/inference/override-tier-floor",
        json={
            "message_id": str(sample_refusal_message.id),
            "reason": "short",
        },
        headers=_h(admin_user),
    )

    assert response.status_code in (400, 422), response.text
