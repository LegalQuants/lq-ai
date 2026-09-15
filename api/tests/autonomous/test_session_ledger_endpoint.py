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


@pytest_asyncio.fixture
async def auditor_user(db_session: AsyncSession) -> User:
    user = User(
        email=f"sl-ep-auditor-{uuid.uuid4().hex[:8]}@example.com",
        hashed_password=hash_password("pw"),
        role="auditor",
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


async def _seed_session_with_ledger(
    db_session: AsyncSession,
    kb_with_one_indexed_file,
    *,
    owner: User,
) -> AutonomousSession:
    """Create + build a session ledger owned by ``owner``; return the session."""
    chunk = (
        await db_session.execute(
            select(DocumentChunk).where(DocumentChunk.id == kb_with_one_indexed_file.chunk_id)
        )
    ).scalar_one()
    quote = chunk.content[:40]
    sess = AutonomousSession(user_id=owner.id, trigger_kind="manual", params={"query": "q"})
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
    return sess


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
    sess = await _seed_session_with_ledger(db_session, kb_with_one_indexed_file, owner=owner_user)

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
    """404 (not 403) when user A requests user B's session ledger, and no
    auditor_audit row is written — a non-privileged non-owner is
    indistinguishable from a missing session.

    Ownership is enforced by ``_load_session_for_reader``; returning 404
    rather than 403 avoids leaking the existence of another user's session.
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

    from sqlalchemy import func

    from app.models.audit import AuditLog

    count = (
        await db_session.execute(
            select(func.count())
            .select_from(AuditLog)
            .where(AuditLog.action == "auditor.session_ledger_viewed")
        )
    ).scalar_one()
    assert count == 0


async def test_session_ledger_endpoint_auditor_cross_user_returns_200_and_audits(
    db_session: AsyncSession,
    client: AsyncClient,
    kb_with_one_indexed_file,
    owner_user: User,
    auditor_user: User,
) -> None:
    """A privileged reader (role=auditor) can read another user's session
    ledger; the read returns 200 and writes exactly one
    ``auditor.session_ledger_viewed`` audit_log row.
    """
    sess = await _seed_session_with_ledger(db_session, kb_with_one_indexed_file, owner=owner_user)

    resp = await client.get(
        f"/api/v1/autonomous/sessions/{sess.id}/ledger",
        headers={"Authorization": _bearer_for(auditor_user)},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "chat_id" in body
    assert len(body["entries"]) >= 1

    from app.models.audit import AuditLog

    row = (
        (
            await db_session.execute(
                select(AuditLog).where(AuditLog.action == "auditor.session_ledger_viewed")
            )
        )
        .scalars()
        .one()
    )
    assert row.user_id == auditor_user.id
    assert row.resource_type == "autonomous_session"
    assert row.resource_id == str(sess.id)
    assert row.details["viewed_user_id"] == str(owner_user.id)


async def test_session_ledger_endpoint_owner_read_not_audited(
    db_session: AsyncSession,
    client: AsyncClient,
    kb_with_one_indexed_file,
    owner_user: User,
) -> None:
    """An owner reading their own session ledger writes no audit_log row."""
    sess = await _seed_session_with_ledger(db_session, kb_with_one_indexed_file, owner=owner_user)

    resp = await client.get(
        f"/api/v1/autonomous/sessions/{sess.id}/ledger",
        headers={"Authorization": _bearer_for(owner_user)},
    )
    assert resp.status_code == 200

    from sqlalchemy import func

    from app.models.audit import AuditLog

    count = (
        await db_session.execute(
            select(func.count())
            .select_from(AuditLog)
            .where(AuditLog.action == "auditor.session_ledger_viewed")
        )
    ).scalar_one()
    assert count == 0
