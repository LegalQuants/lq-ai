"""Integration tests for the matter roster — /api/v1/projects/{id}/members.

Mirrors ``test_teams.py``'s coverage, because the surface deliberately
mirrors ``teams.py``: CRUD round-trip, 409 on duplicate, 422 on an unknown
role, 403 for a non-lead, the users join on the roster, and an audit row on
every mutation with before/after on a role change.

Adds what teams has no analogue for:

* a screen (``role='blocked'``) hides the matter from someone who could
  otherwise reach it firm-wide, and the removal that lifts it says so in
  the audit row;
* the owner's row is immovable — their access does not flow from it, so a
  demotion or removal would only make the roster lie;
* a colleague can read a shared matter's threads but cannot post into one.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.main import app
from app.models.audit import AuditLog
from app.models.chat import Chat
from app.models.project import Project
from app.models.project_member import ProjectMember
from app.models.user import User
from app.security import create_access_token, hash_password

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _override_get_db(db_session: AsyncSession):
    async def _override() -> AsyncIterator[AsyncSession]:
        yield db_session

    return _override


def _bearer(user: User) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {create_access_token(user.id, user.email, is_admin=user.is_admin)}"
    }


async def _mk_user(db: AsyncSession, *, is_admin: bool = False, role: str = "member") -> User:
    user = User(
        email=f"u-{uuid.uuid4().hex[:10]}@example.com",
        display_name="Test User",
        hashed_password=hash_password("s3cr3t-battery-staple"),
        is_admin=is_admin,
        role=role,
        mfa_enabled=False,
        must_change_password=False,
    )
    db.add(user)
    await db.flush()
    return user


async def _mk_project(db: AsyncSession, owner: User, *, share_scope: str = "personal") -> Project:
    project = Project(
        owner_id=owner.id,
        name="Acme MSA renewal",
        slug=f"acme-{uuid.uuid4().hex[:8]}",
        share_scope=share_scope,
    )
    db.add(project)
    await db.flush()
    db.add(
        ProjectMember(
            project_id=project.id,
            user_id=owner.id,
            role="lead",
            added_by_user_id=owner.id,
        )
    )
    await db.flush()
    return project


@pytest_asyncio.fixture
async def client(db_session: AsyncSession) -> AsyncIterator[AsyncClient]:
    app.dependency_overrides[get_db] = _override_get_db(db_session)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.pop(get_db, None)


@pytest_asyncio.fixture
async def owner(db_session: AsyncSession) -> User:
    return await _mk_user(db_session)


@pytest_asyncio.fixture
async def colleague(db_session: AsyncSession) -> User:
    return await _mk_user(db_session)


@pytest_asyncio.fixture
async def stranger(db_session: AsyncSession) -> User:
    return await _mk_user(db_session)


@pytest_asyncio.fixture
async def matter(db_session: AsyncSession, owner: User) -> Project:
    return await _mk_project(db_session, owner)


# ---------------------------------------------------------------------------
# Roster CRUD
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_new_matter_lists_its_owner_as_lead(
    client: AsyncClient, owner: User, matter: Project
) -> None:
    resp = await client.get(f"/api/v1/projects/{matter.id}/members", headers=_bearer(owner))
    assert resp.status_code == 200, resp.text
    rows = resp.json()
    assert len(rows) == 1
    assert rows[0]["user_id"] == str(owner.id)
    assert rows[0]["role"] == "lead"
    assert rows[0]["is_owner"] is True
    assert rows[0]["email"] == owner.email


@pytest.mark.asyncio
async def test_add_member_round_trips(
    client: AsyncClient, owner: User, colleague: User, matter: Project
) -> None:
    resp = await client.post(
        f"/api/v1/projects/{matter.id}/members",
        json={"user_id": str(colleague.id), "role": "contributor"},
        headers=_bearer(owner),
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["role"] == "contributor"
    assert body["added_by_user_id"] == str(owner.id)
    assert body["is_owner"] is False

    listed = await client.get(f"/api/v1/projects/{matter.id}/members", headers=_bearer(owner))
    assert {r["user_id"] for r in listed.json()} == {str(owner.id), str(colleague.id)}


@pytest.mark.asyncio
async def test_added_member_sees_the_matter(
    client: AsyncClient, owner: User, colleague: User, matter: Project
) -> None:
    # Before: invisible.
    before = await client.get(f"/api/v1/projects/{matter.id}", headers=_bearer(colleague))
    assert before.status_code == 404

    await client.post(
        f"/api/v1/projects/{matter.id}/members",
        json={"user_id": str(colleague.id), "role": "contributor"},
        headers=_bearer(owner),
    )

    after = await client.get(f"/api/v1/projects/{matter.id}", headers=_bearer(colleague))
    assert after.status_code == 200, after.text
    assert after.json()["caller_access"] == "write"
    assert after.json()["caller_access_basis"] == "member"

    listed = await client.get("/api/v1/projects", headers=_bearer(colleague))
    assert str(matter.id) in {row["id"] for row in listed.json()}


@pytest.mark.asyncio
async def test_add_duplicate_member_409(
    client: AsyncClient, owner: User, colleague: User, matter: Project
) -> None:
    payload = {"user_id": str(colleague.id), "role": "reader"}
    first = await client.post(
        f"/api/v1/projects/{matter.id}/members", json=payload, headers=_bearer(owner)
    )
    assert first.status_code == 201
    second = await client.post(
        f"/api/v1/projects/{matter.id}/members", json=payload, headers=_bearer(owner)
    )
    assert second.status_code == 409, second.text


@pytest.mark.asyncio
async def test_add_member_unknown_role_422(
    client: AsyncClient, owner: User, colleague: User, matter: Project
) -> None:
    resp = await client.post(
        f"/api/v1/projects/{matter.id}/members",
        json={"user_id": str(colleague.id), "role": "partner"},
        headers=_bearer(owner),
    )
    assert resp.status_code == 422, resp.text


@pytest.mark.asyncio
async def test_add_member_unknown_user_404(
    client: AsyncClient, owner: User, matter: Project
) -> None:
    resp = await client.post(
        f"/api/v1/projects/{matter.id}/members",
        json={"user_id": str(uuid.uuid4()), "role": "reader"},
        headers=_bearer(owner),
    )
    assert resp.status_code == 404, resp.text


@pytest.mark.asyncio
async def test_non_lead_cannot_manage_the_roster(
    client: AsyncClient, owner: User, colleague: User, stranger: User, matter: Project
) -> None:
    await client.post(
        f"/api/v1/projects/{matter.id}/members",
        json={"user_id": str(colleague.id), "role": "contributor"},
        headers=_bearer(owner),
    )
    resp = await client.post(
        f"/api/v1/projects/{matter.id}/members",
        json={"user_id": str(stranger.id), "role": "reader"},
        headers=_bearer(colleague),
    )
    assert resp.status_code == 403, resp.text


@pytest.mark.asyncio
async def test_stranger_managing_the_roster_gets_404(
    client: AsyncClient, colleague: User, stranger: User, matter: Project
) -> None:
    """Existence-safe: someone with no path to the matter learns nothing."""
    resp = await client.post(
        f"/api/v1/projects/{matter.id}/members",
        json={"user_id": str(colleague.id), "role": "reader"},
        headers=_bearer(stranger),
    )
    assert resp.status_code == 404, resp.text


@pytest.mark.asyncio
async def test_role_change_round_trips(
    client: AsyncClient, owner: User, colleague: User, matter: Project
) -> None:
    await client.post(
        f"/api/v1/projects/{matter.id}/members",
        json={"user_id": str(colleague.id), "role": "reader"},
        headers=_bearer(owner),
    )
    resp = await client.patch(
        f"/api/v1/projects/{matter.id}/members/{colleague.id}",
        json={"role": "lead"},
        headers=_bearer(owner),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["role"] == "lead"

    # A promoted lead can now staff the matter themselves.
    onward = await client.get(f"/api/v1/projects/{matter.id}/access", headers=_bearer(colleague))
    assert onward.json()["caller_access"] == "lead"


@pytest.mark.asyncio
async def test_remove_member_revokes_access(
    client: AsyncClient, owner: User, colleague: User, matter: Project
) -> None:
    await client.post(
        f"/api/v1/projects/{matter.id}/members",
        json={"user_id": str(colleague.id), "role": "contributor"},
        headers=_bearer(owner),
    )
    resp = await client.delete(
        f"/api/v1/projects/{matter.id}/members/{colleague.id}", headers=_bearer(owner)
    )
    assert resp.status_code == 204, resp.text
    assert resp.content == b""

    gone = await client.get(f"/api/v1/projects/{matter.id}", headers=_bearer(colleague))
    assert gone.status_code == 404


@pytest.mark.asyncio
async def test_owner_row_cannot_be_demoted_or_removed(
    client: AsyncClient, owner: User, matter: Project
) -> None:
    demote = await client.patch(
        f"/api/v1/projects/{matter.id}/members/{owner.id}",
        json={"role": "reader"},
        headers=_bearer(owner),
    )
    assert demote.status_code == 409, demote.text

    remove = await client.delete(
        f"/api/v1/projects/{matter.id}/members/{owner.id}", headers=_bearer(owner)
    )
    assert remove.status_code == 409, remove.text


# ---------------------------------------------------------------------------
# Screens
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_screen_hides_a_firm_wide_matter(
    db_session: AsyncSession, client: AsyncClient, owner: User, colleague: User
) -> None:
    matter = await _mk_project(db_session, owner, share_scope="org")

    seen = await client.get(f"/api/v1/projects/{matter.id}", headers=_bearer(colleague))
    assert seen.status_code == 200
    assert seen.json()["caller_access_basis"] == "org"

    screened = await client.post(
        f"/api/v1/projects/{matter.id}/members",
        json={"user_id": str(colleague.id), "role": "blocked"},
        headers=_bearer(owner),
    )
    assert screened.status_code == 201, screened.text

    hidden = await client.get(f"/api/v1/projects/{matter.id}", headers=_bearer(colleague))
    assert hidden.status_code == 404

    listed = await client.get("/api/v1/projects", headers=_bearer(colleague))
    assert str(matter.id) not in {row["id"] for row in listed.json()}


@pytest.mark.asyncio
async def test_lifting_a_screen_is_recorded_as_such(
    db_session: AsyncSession, client: AsyncClient, owner: User, colleague: User
) -> None:
    matter = await _mk_project(db_session, owner, share_scope="org")
    await client.post(
        f"/api/v1/projects/{matter.id}/members",
        json={"user_id": str(colleague.id), "role": "blocked"},
        headers=_bearer(owner),
    )
    resp = await client.delete(
        f"/api/v1/projects/{matter.id}/members/{colleague.id}", headers=_bearer(owner)
    )
    assert resp.status_code == 204

    entry = (
        await db_session.execute(
            select(AuditLog).where(
                AuditLog.action == "matter.member_removed",
                AuditLog.resource_id == str(matter.id),
            )
        )
    ).scalar_one()
    assert entry.details is not None
    assert entry.details["role_at_removal"] == "blocked"
    assert entry.details["lifted_screen"] is True

    back = await client.get(f"/api/v1/projects/{matter.id}", headers=_bearer(colleague))
    assert back.status_code == 200


# ---------------------------------------------------------------------------
# Audit
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_member_added_writes_an_audit_row(
    db_session: AsyncSession, client: AsyncClient, owner: User, colleague: User, matter: Project
) -> None:
    await client.post(
        f"/api/v1/projects/{matter.id}/members",
        json={"user_id": str(colleague.id), "role": "contributor"},
        headers=_bearer(owner),
    )
    entry = (
        await db_session.execute(
            select(AuditLog).where(
                AuditLog.action == "matter.member_added",
                AuditLog.resource_id == str(matter.id),
            )
        )
    ).scalar_one()
    assert entry.user_id == owner.id
    assert entry.resource_type == "project"
    assert entry.details is not None
    assert entry.details["user_email"] == colleague.email
    assert entry.details["role"] == "contributor"


@pytest.mark.asyncio
async def test_role_change_records_before_and_after(
    db_session: AsyncSession, client: AsyncClient, owner: User, colleague: User, matter: Project
) -> None:
    await client.post(
        f"/api/v1/projects/{matter.id}/members",
        json={"user_id": str(colleague.id), "role": "reader"},
        headers=_bearer(owner),
    )
    await client.patch(
        f"/api/v1/projects/{matter.id}/members/{colleague.id}",
        json={"role": "blocked"},
        headers=_bearer(owner),
    )
    entry = (
        await db_session.execute(
            select(AuditLog).where(
                AuditLog.action == "matter.member_role_updated",
                AuditLog.resource_id == str(matter.id),
            )
        )
    ).scalar_one()
    assert entry.details is not None
    assert entry.details["before"] == {"role": "reader"}
    assert entry.details["after"] == {"role": "blocked"}


@pytest.mark.asyncio
async def test_idempotent_role_change_writes_no_audit_row(
    db_session: AsyncSession, client: AsyncClient, owner: User, colleague: User, matter: Project
) -> None:
    await client.post(
        f"/api/v1/projects/{matter.id}/members",
        json={"user_id": str(colleague.id), "role": "reader"},
        headers=_bearer(owner),
    )
    resp = await client.patch(
        f"/api/v1/projects/{matter.id}/members/{colleague.id}",
        json={"role": "reader"},
        headers=_bearer(owner),
    )
    assert resp.status_code == 200
    rows = (
        (
            await db_session.execute(
                select(AuditLog).where(AuditLog.action == "matter.member_role_updated")
            )
        )
        .scalars()
        .all()
    )
    assert rows == []


# ---------------------------------------------------------------------------
# share_scope is a lead-only lever
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_contributor_cannot_change_share_scope(
    client: AsyncClient, owner: User, colleague: User, matter: Project
) -> None:
    await client.post(
        f"/api/v1/projects/{matter.id}/members",
        json={"user_id": str(colleague.id), "role": "contributor"},
        headers=_bearer(owner),
    )
    # They can edit the matter...
    edit = await client.patch(
        f"/api/v1/projects/{matter.id}",
        json={"context_md": "counterparty is Acme"},
        headers=_bearer(colleague),
    )
    assert edit.status_code == 200, edit.text

    # ...but not decide who else can see it.
    widen = await client.patch(
        f"/api/v1/projects/{matter.id}",
        json={"share_scope": "org"},
        headers=_bearer(colleague),
    )
    assert widen.status_code == 403, widen.text


@pytest.mark.asyncio
async def test_contributor_cannot_clear_privileged_or_archive(
    client: AsyncClient, db_session: AsyncSession, owner: User, colleague: User
) -> None:
    matter = await _mk_project(db_session, owner)
    matter.privileged = True
    matter.minimum_inference_tier = 1
    await db_session.flush()

    await client.post(
        f"/api/v1/projects/{matter.id}/members",
        json={"user_id": str(colleague.id), "role": "contributor"},
        headers=_bearer(owner),
    )
    for body in ({"privileged": False}, {"minimum_inference_tier": 5}, {"archived": True}):
        resp = await client.patch(
            f"/api/v1/projects/{matter.id}", json=body, headers=_bearer(colleague)
        )
        assert resp.status_code == 403, f"{body} -> {resp.status_code} {resp.text}"


@pytest.mark.asyncio
async def test_lead_can_widen_share_scope(
    client: AsyncClient, owner: User, matter: Project
) -> None:
    resp = await client.patch(
        f"/api/v1/projects/{matter.id}",
        json={"share_scope": "org"},
        headers=_bearer(owner),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["share_scope"] == "org"


# ---------------------------------------------------------------------------
# Chats: read the matter's threads, but write only your own
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_member_reads_a_colleagues_thread_but_cannot_post_into_it(
    db_session: AsyncSession, client: AsyncClient, owner: User, colleague: User, matter: Project
) -> None:
    chat = Chat(owner_id=owner.id, project_id=matter.id, title="Assignment clause")
    db_session.add(chat)
    await db_session.flush()

    await client.post(
        f"/api/v1/projects/{matter.id}/members",
        json={"user_id": str(colleague.id), "role": "contributor"},
        headers=_bearer(owner),
    )

    # Readable — the whole point of sharing the matter.
    read = await client.get(f"/api/v1/chats/{chat.id}", headers=_bearer(colleague))
    assert read.status_code == 200, read.text
    assert read.json()["owner_id"] == str(owner.id)

    messages = await client.get(f"/api/v1/chats/{chat.id}/messages", headers=_bearer(colleague))
    assert messages.status_code == 200

    # Not writable — two lawyers interleaving turns in one thread would make
    # work_product_attribution ambiguous about who directed which output.
    rename = await client.patch(
        f"/api/v1/chats/{chat.id}", json={"title": "mine now"}, headers=_bearer(colleague)
    )
    assert rename.status_code == 404, rename.text


@pytest.mark.asyncio
async def test_matter_chat_list_shows_every_members_threads(
    db_session: AsyncSession, client: AsyncClient, owner: User, colleague: User, matter: Project
) -> None:
    owner_chat = Chat(owner_id=owner.id, project_id=matter.id, title="Owner thread")
    db_session.add(owner_chat)
    await db_session.flush()

    await client.post(
        f"/api/v1/projects/{matter.id}/members",
        json={"user_id": str(colleague.id), "role": "contributor"},
        headers=_bearer(owner),
    )

    scoped = await client.get(f"/api/v1/chats?project_id={matter.id}", headers=_bearer(colleague))
    assert scoped.status_code == 200, scoped.text
    assert str(owner_chat.id) in {c["id"] for c in scoped.json()["items"]}

    # The unfiltered sidebar stays personal — a shared matter must not flood
    # a colleague's chat list.
    unscoped = await client.get("/api/v1/chats", headers=_bearer(colleague))
    assert str(owner_chat.id) not in {c["id"] for c in unscoped.json()["items"]}


@pytest.mark.asyncio
async def test_screened_member_loses_thread_access(
    db_session: AsyncSession, client: AsyncClient, owner: User, colleague: User
) -> None:
    matter = await _mk_project(db_session, owner, share_scope="org")
    chat = Chat(owner_id=owner.id, project_id=matter.id, title="Privileged analysis")
    db_session.add(chat)
    await db_session.flush()

    before = await client.get(f"/api/v1/chats/{chat.id}", headers=_bearer(colleague))
    assert before.status_code == 200

    await client.post(
        f"/api/v1/projects/{matter.id}/members",
        json={"user_id": str(colleague.id), "role": "blocked"},
        headers=_bearer(owner),
    )

    after = await client.get(f"/api/v1/chats/{chat.id}", headers=_bearer(colleague))
    assert after.status_code == 404, after.text
