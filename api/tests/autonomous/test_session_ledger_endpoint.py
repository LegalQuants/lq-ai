"""Integration tests for GET /autonomous/sessions/{id}/ledger (WS-D PR2 Task 8).

Covers:
- Happy path: a session with a manufactured ledger (via build_session_ledger)
  returns 200 with entries + gates (identical shape to chat ledger endpoint).
- 404 when the session has no manufactured chat (no ledger built yet).
- 404 (not 403) when a different authenticated user requests another user's
  session ledger (ownership enforcement, no existence leak).
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.autonomous.ledger_bridge import build_session_ledger
from app.db.session import get_db
from app.main import app
from app.models.autonomous import AutonomousSession
from app.models.document import DocumentChunk
from app.models.user import User
from app.security import create_access_token, hash_password

pytestmark = [pytest.mark.asyncio, pytest.mark.integration]


# ---------------------------------------------------------------------------
# Fixtures and helpers
# ---------------------------------------------------------------------------


def _override_get_db(db_session: AsyncSession):
    async def _override() -> AsyncIterator[AsyncSession]:
        yield db_session

    return _override


@pytest_asyncio.fixture
async def client(db_session: AsyncSession) -> AsyncIterator[AsyncClient]:
    app.dependency_overrides[get_db] = _override_get_db(db_session)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.pop(get_db, None)


@pytest_asyncio.fixture
async def owner_user(db_session: AsyncSession) -> User:
    user = User(
        email=f"sl-ep-{uuid.uuid4().hex[:8]}@example.com",
        hashed_password=hash_password("pw"),
        role="member",
        is_admin=False,
        mfa_enabled=False,
        must_change_password=False,
    )
    db_session.add(user)
    await db_session.flush()
    return user


@pytest_asyncio.fixture
async def other_user(db_session: AsyncSession) -> User:
    user = User(
        email=f"sl-ep-other-{uuid.uuid4().hex[:8]}@example.com",
        hashed_password=hash_password("pw"),
        role="member",
        is_admin=False,
        mfa_enabled=False,
        must_change_password=False,
    )
    db_session.add(user)
    await db_session.flush()
    return user


def _bearer_for(user: User) -> str:
    token = create_access_token(user.id, user.email, is_admin=user.is_admin)
    return f"Bearer {token}"


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


async def test_session_ledger_endpoint_returns_entries(
    db_session: AsyncSession,
    client: AsyncClient,
    kb_with_one_indexed_file,
    owner_user: User,
) -> None:
    """200 + entries + gate when the session has a built ledger."""
    chunk = (
        await db_session.execute(
            select(DocumentChunk).where(DocumentChunk.id == kb_with_one_indexed_file.chunk_id)
        )
    ).scalar_one()
    quote = chunk.content[:40]
    sess = AutonomousSession(user_id=owner_user.id, trigger_kind="manual", params={"query": "q"})
    db_session.add(sess)
    await db_session.flush()
    await build_session_ledger(
        db_session,
        session=sess,
        work_product_text="wp",
        findings=[
            {
                "title": "T",
                "summary": "S",
                "severity": "info",
                "citations": [{"quote": quote, "source": 1}],
            }
        ],
        evidence=[
            {
                "n": 1,
                "kind": "kb",
                "ref": str(kb_with_one_indexed_file.chunk_id),
                "content": chunk.content,
                "display": "nda.pdf",
            }
        ],
        gateway=None,
    )
    await db_session.commit()

    resp = await client.get(
        f"/api/v1/autonomous/sessions/{sess.id}/ledger",
        headers={"Authorization": _bearer_for(owner_user)},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "chat_id" in body
    assert body["gates"][0]["gate_status"] in {"fiduciary_grade", "supported_only", "flagged"}
    assert len(body["entries"]) >= 1


async def test_session_ledger_endpoint_404_without_ledger(
    db_session: AsyncSession,
    client: AsyncClient,
    owner_user: User,
) -> None:
    """404 when the session exists but has no manufactured chat (no ledger)."""
    sess = AutonomousSession(user_id=owner_user.id, trigger_kind="manual", params={})
    db_session.add(sess)
    await db_session.commit()
    resp = await client.get(
        f"/api/v1/autonomous/sessions/{sess.id}/ledger",
        headers={"Authorization": _bearer_for(owner_user)},
    )
    assert resp.status_code == 404


async def test_session_ledger_endpoint_cross_user_returns_404(
    db_session: AsyncSession,
    client: AsyncClient,
    owner_user: User,
    other_user: User,
) -> None:
    """404 (not 403) when user A requests user B's session ledger.

    Ownership is enforced by ``_load_owned_session``; returning 404 rather
    than 403 avoids leaking the existence of another user's session.
    """
    # Create a session owned by other_user (user B).
    sess_b = AutonomousSession(user_id=other_user.id, trigger_kind="manual", params={})
    db_session.add(sess_b)
    await db_session.commit()

    # Request as owner_user (user A) — must get 404, not 403.
    resp = await client.get(
        f"/api/v1/autonomous/sessions/{sess_b.id}/ledger",
        headers={"Authorization": _bearer_for(owner_user)},
    )
    assert resp.status_code == 404
