"""Integration tests for the M4-B2 precedent board + promote-to-Project lifecycle.

Covers:
- propose_precedent chokepoint: fresh observation inserts observed_count=1; a
  recurring (same pattern_kind+summary) call increments; different
  pattern_kind/summary creates a separate row.
- propose_precedent is granted at analysis AND drafting; rejected elsewhere (R6).
- Negative-write: propose_precedent never creates/modifies a projects row.
- GET /precedents: empty, excludes dismissed, ?pattern_kind= filter, pagination
  + clamp, newest-first, isolation, 401.
- dismiss: sets dismissed_at; hides from list; idempotent; cross-user→404; audit; 401.
- promote: creates a proposed proposal; suggested_md derived from summary; does
  NOT modify projects.context_md; cross-user precedent/project→404; audit; 401.
- proposals GET: isolation, state/project filters, pagination.
- accept: appends to context_md; sets accepted; double-accept no double-append;
  cross-user→404; audit; 401.
- reject: sets rejected; does NOT touch context_md; cross-user→404; audit; 401.
- OpenAPI conformance for the 6 new paths + schemas.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.main import app
from app.models.autonomous import (
    AutonomousSession,
    PrecedentEntry,
    ProjectContextProposal,
)
from app.models.project import Project
from app.models.user import User
from app.security import create_access_token, hash_password

# ---------------------------------------------------------------------------
# Fixtures and helpers (mirror test_memory.py)
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


async def _make_user(db: AsyncSession, *, suffix: str = "") -> User:
    user = User(
        email=f"prec-test-{suffix or uuid.uuid4().hex[:8]}@example.com",
        display_name=f"Precedent Test User {suffix}".strip(),
        hashed_password=hash_password("correct-horse-battery-staple"),
        is_admin=False,
        mfa_enabled=False,
        must_change_password=False,
        autonomous_enabled=True,  # M4-C2: mutate endpoints require opt-in
    )
    db.add(user)
    await db.flush()
    return user


@pytest_asyncio.fixture
async def user_a(db_session: AsyncSession) -> User:
    return await _make_user(db_session, suffix="a")


@pytest_asyncio.fixture
async def user_b(db_session: AsyncSession) -> User:
    return await _make_user(db_session, suffix="b")


def _bearer(user: User) -> dict[str, str]:
    token = create_access_token(user.id, user.email, is_admin=user.is_admin)
    return {"Authorization": f"Bearer {token}"}


async def _make_session(
    db: AsyncSession, *, user: User, phase: str = "intake"
) -> AutonomousSession:
    sess = AutonomousSession(
        user_id=user.id,
        trigger_kind="manual",
        halt_state="running",
        status="running",
        current_phase=phase,
    )
    db.add(sess)
    await db.flush()
    await db.refresh(sess)
    return sess


async def _make_precedent(
    db: AsyncSession,
    *,
    user: User,
    pattern_kind: str = "liability_cap",
    summary: str = "12-month liability cap is recurring",
    observed_count: int = 1,
    dismissed: bool = False,
) -> PrecedentEntry:
    prec = PrecedentEntry(
        user_id=user.id,
        pattern_kind=pattern_kind,
        summary=summary,
        observed_count=observed_count,
        dismissed_at=datetime.now(UTC) if dismissed else None,
    )
    db.add(prec)
    await db.flush()
    await db.refresh(prec)
    return prec


async def _make_project(
    db: AsyncSession,
    *,
    user: User,
    name: str = "Acme Deal",
    slug: str | None = None,
    context_md: str | None = None,
) -> Project:
    project = Project(
        owner_id=user.id,
        name=name,
        slug=slug or f"acme-{uuid.uuid4().hex[:8]}",
        context_md=context_md,
    )
    db.add(project)
    await db.flush()
    await db.refresh(project)
    return project


class _StubGateway:
    pass


# ---------------------------------------------------------------------------
# propose_precedent chokepoint — upsert-on-recurrence
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_propose_precedent_fresh_inserts_count_one(
    db_session: AsyncSession,
    user_a: User,
) -> None:
    """A fresh observation inserts a row with observed_count=1."""
    from app.autonomous.enums import ToolIntent
    from app.autonomous.guard import guarded_tool_call

    sess = await _make_session(db_session, user=user_a, phase="analysis")

    result = await guarded_tool_call(
        sess,
        ToolIntent.propose_precedent,
        {"pattern_kind": "liability_cap", "summary": "12-month cap recurs"},
        db_session,
        _StubGateway(),
    )

    assert result.data["observed_count"] == 1
    prec_id = uuid.UUID(result.data["precedent_id"])
    row = (
        await db_session.execute(select(PrecedentEntry).where(PrecedentEntry.id == prec_id))
    ).scalar_one()
    assert row.observed_count == 1
    assert row.source_session_id == sess.id
    assert row.user_id == user_a.id


@pytest.mark.integration
async def test_propose_precedent_recurrence_increments(
    db_session: AsyncSession,
    user_a: User,
) -> None:
    """A second call with the same pattern_kind+summary increments observed_count."""
    from app.autonomous.enums import ToolIntent
    from app.autonomous.guard import guarded_tool_call

    sess = await _make_session(db_session, user=user_a, phase="drafting")
    params = {"pattern_kind": "indemnity", "summary": "uncapped indemnity recurs"}

    first = await guarded_tool_call(
        sess, ToolIntent.propose_precedent, params, db_session, _StubGateway()
    )
    second = await guarded_tool_call(
        sess, ToolIntent.propose_precedent, params, db_session, _StubGateway()
    )

    assert first.data["precedent_id"] == second.data["precedent_id"], (
        "recurrence must upsert the same row, not insert a new one"
    )
    assert first.data["observed_count"] == 1
    assert second.data["observed_count"] == 2

    count = (
        await db_session.execute(
            select(func.count())
            .select_from(PrecedentEntry)
            .where(PrecedentEntry.user_id == user_a.id)
        )
    ).scalar_one()
    assert count == 1


@pytest.mark.integration
async def test_propose_precedent_distinct_pattern_creates_separate_row(
    db_session: AsyncSession,
    user_a: User,
) -> None:
    """A different pattern_kind OR different summary creates a separate row."""
    from app.autonomous.enums import ToolIntent
    from app.autonomous.guard import guarded_tool_call

    sess = await _make_session(db_session, user=user_a, phase="analysis")

    r1 = await guarded_tool_call(
        sess,
        ToolIntent.propose_precedent,
        {"pattern_kind": "liability_cap", "summary": "cap A"},
        db_session,
        _StubGateway(),
    )
    # Different summary, same pattern_kind.
    r2 = await guarded_tool_call(
        sess,
        ToolIntent.propose_precedent,
        {"pattern_kind": "liability_cap", "summary": "cap B"},
        db_session,
        _StubGateway(),
    )
    # Different pattern_kind, same summary as r1.
    r3 = await guarded_tool_call(
        sess,
        ToolIntent.propose_precedent,
        {"pattern_kind": "venue", "summary": "cap A"},
        db_session,
        _StubGateway(),
    )

    ids = {r1.data["precedent_id"], r2.data["precedent_id"], r3.data["precedent_id"]}
    assert len(ids) == 3

    count = (
        await db_session.execute(
            select(func.count())
            .select_from(PrecedentEntry)
            .where(PrecedentEntry.user_id == user_a.id)
        )
    ).scalar_one()
    assert count == 3


@pytest.mark.integration
async def test_propose_precedent_dismissed_row_not_reused(
    db_session: AsyncSession,
    user_a: User,
) -> None:
    """A dismissed row is not upserted; a new observation inserts a fresh row."""
    from app.autonomous.enums import ToolIntent
    from app.autonomous.guard import guarded_tool_call

    dismissed = await _make_precedent(
        db_session,
        user=user_a,
        pattern_kind="liability_cap",
        summary="dismissed cap",
        observed_count=3,
        dismissed=True,
    )

    sess = await _make_session(db_session, user=user_a, phase="analysis")
    result = await guarded_tool_call(
        sess,
        ToolIntent.propose_precedent,
        {"pattern_kind": "liability_cap", "summary": "dismissed cap"},
        db_session,
        _StubGateway(),
    )

    assert result.data["precedent_id"] != str(dismissed.id)
    assert result.data["observed_count"] == 1


@pytest.mark.integration
async def test_propose_precedent_zero_cost(
    db_session: AsyncSession,
    user_a: User,
) -> None:
    """propose_precedent is local/zero-cost — estimate_tool_cost returns 0."""
    from decimal import Decimal

    from app.autonomous.cost import estimate_tool_cost
    from app.autonomous.enums import ToolIntent

    cost = await estimate_tool_cost(
        ToolIntent.propose_precedent,
        {"pattern_kind": "x", "summary": "y"},
        db_session,
    )
    assert cost == Decimal("0")


# ---------------------------------------------------------------------------
# PHASE_GRANTS — propose_precedent at analysis + drafting only
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_propose_precedent_granted_at_analysis_and_drafting() -> None:
    """propose_precedent is granted at BOTH analysis and drafting."""
    from app.autonomous.enums import PHASE_GRANTS, Phase, ToolIntent

    assert ToolIntent.propose_precedent in PHASE_GRANTS[Phase.analysis]
    assert ToolIntent.propose_precedent in PHASE_GRANTS[Phase.drafting]


@pytest.mark.unit
def test_propose_precedent_not_granted_elsewhere() -> None:
    """propose_precedent is NOT granted at intake/ethics_review/delivery."""
    from app.autonomous.enums import PHASE_GRANTS, Phase, ToolIntent

    for phase in (Phase.intake, Phase.ethics_review, Phase.delivery):
        assert ToolIntent.propose_precedent not in PHASE_GRANTS[phase], (
            f"propose_precedent must not be granted at {phase}"
        )


@pytest.mark.integration
@pytest.mark.parametrize("phase", ["intake", "ethics_review", "delivery"])
async def test_propose_precedent_rejected_at_ungranted_phase(
    db_session: AsyncSession,
    user_a: User,
    phase: str,
) -> None:
    """The chokepoint raises ToolNotGranted at a phase that doesn't grant it (R6)."""
    from app.autonomous.enums import ToolIntent
    from app.autonomous.guard import guarded_tool_call
    from app.errors import ToolNotGranted

    sess = await _make_session(db_session, user=user_a, phase=phase)

    with pytest.raises(ToolNotGranted):
        await guarded_tool_call(
            sess,
            ToolIntent.propose_precedent,
            {"pattern_kind": "x", "summary": "y"},
            db_session,
            _StubGateway(),
        )


# ---------------------------------------------------------------------------
# Negative-write: the agent cannot write Project context via propose_precedent
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_propose_precedent_never_touches_projects(
    db_session: AsyncSession,
    user_a: User,
) -> None:
    """propose_precedent must not create or modify any projects row."""
    from app.autonomous.enums import ToolIntent
    from app.autonomous.guard import guarded_tool_call

    project = await _make_project(db_session, user=user_a, context_md="original context")
    before = project.context_md

    projects_before = (
        await db_session.execute(select(func.count()).select_from(Project))
    ).scalar_one()

    sess = await _make_session(db_session, user=user_a, phase="analysis")
    await guarded_tool_call(
        sess,
        ToolIntent.propose_precedent,
        {"pattern_kind": "liability_cap", "summary": "no project write"},
        db_session,
        _StubGateway(),
    )

    projects_after = (
        await db_session.execute(select(func.count()).select_from(Project))
    ).scalar_one()
    assert projects_after == projects_before, "propose_precedent must not create projects rows"

    await db_session.refresh(project)
    assert project.context_md == before, "propose_precedent must not modify context_md"


# ---------------------------------------------------------------------------
# GET /autonomous/precedents
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_list_precedents_empty_for_new_user(
    client: AsyncClient,
    user_a: User,
) -> None:
    resp = await client.get("/api/v1/autonomous/precedents", headers=_bearer(user_a))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["entries"] == []
    assert body["total_count"] == 0
    assert body["limit"] == 50
    assert body["offset"] == 0


@pytest.mark.integration
async def test_list_precedents_excludes_dismissed(
    client: AsyncClient,
    db_session: AsyncSession,
    user_a: User,
) -> None:
    active = await _make_precedent(db_session, user=user_a, summary="active")
    dismissed = await _make_precedent(db_session, user=user_a, summary="gone", dismissed=True)

    resp = await client.get("/api/v1/autonomous/precedents", headers=_bearer(user_a))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    ids = {e["id"] for e in body["entries"]}
    assert str(active.id) in ids
    assert str(dismissed.id) not in ids
    assert body["total_count"] == 1


@pytest.mark.integration
async def test_list_precedents_filter_by_pattern_kind(
    client: AsyncClient,
    db_session: AsyncSession,
    user_a: User,
) -> None:
    cap = await _make_precedent(db_session, user=user_a, pattern_kind="liability_cap")
    venue = await _make_precedent(db_session, user=user_a, pattern_kind="venue")

    resp = await client.get(
        "/api/v1/autonomous/precedents",
        headers=_bearer(user_a),
        params={"pattern_kind": "liability_cap"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    ids = {e["id"] for e in body["entries"]}
    assert str(cap.id) in ids
    assert str(venue.id) not in ids
    assert body["total_count"] == 1


@pytest.mark.integration
async def test_list_precedents_pagination_and_clamp(
    client: AsyncClient,
    db_session: AsyncSession,
    user_a: User,
) -> None:
    for i in range(5):
        await _make_precedent(db_session, user=user_a, summary=f"s{i}")

    resp = await client.get(
        "/api/v1/autonomous/precedents",
        headers=_bearer(user_a),
        params={"limit": 2, "offset": 1},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert len(body["entries"]) == 2
    assert body["total_count"] == 5
    assert body["limit"] == 2
    assert body["offset"] == 1

    resp = await client.get(
        "/api/v1/autonomous/precedents",
        headers=_bearer(user_a),
        params={"limit": 9999},
    )
    assert resp.json()["limit"] == 200


@pytest.mark.integration
async def test_list_precedents_newest_first(
    client: AsyncClient,
    db_session: AsyncSession,
    user_a: User,
) -> None:
    import datetime as _dt

    await _make_precedent(db_session, user=user_a, summary="one")
    await _make_precedent(db_session, user=user_a, summary="two")
    await _make_precedent(db_session, user=user_a, summary="three")

    resp = await client.get("/api/v1/autonomous/precedents", headers=_bearer(user_a))
    body = resp.json()
    created_ats = [_dt.datetime.fromisoformat(e["created_at"]) for e in body["entries"]]
    for i in range(len(created_ats) - 1):
        assert created_ats[i] >= created_ats[i + 1]


@pytest.mark.integration
async def test_list_precedents_isolation(
    client: AsyncClient,
    db_session: AsyncSession,
    user_a: User,
    user_b: User,
) -> None:
    prec_a = await _make_precedent(db_session, user=user_a)
    prec_b = await _make_precedent(db_session, user=user_b)

    resp = await client.get("/api/v1/autonomous/precedents", headers=_bearer(user_a))
    body = resp.json()
    ids = {e["id"] for e in body["entries"]}
    assert str(prec_a.id) in ids
    assert str(prec_b.id) not in ids
    assert body["total_count"] == 1


@pytest.mark.integration
async def test_list_precedents_unauth_returns_401(client: AsyncClient) -> None:
    resp = await client.get("/api/v1/autonomous/precedents")
    assert resp.status_code == 401, resp.text


# ---------------------------------------------------------------------------
# POST /autonomous/precedents/{id}/dismiss
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_dismiss_precedent_sets_dismissed_at(
    client: AsyncClient,
    db_session: AsyncSession,
    user_a: User,
) -> None:
    prec = await _make_precedent(db_session, user=user_a)

    resp = await client.post(
        f"/api/v1/autonomous/precedents/{prec.id}/dismiss",
        headers=_bearer(user_a),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["id"] == str(prec.id)
    assert body["dismissed_at"] is not None

    await db_session.refresh(prec)
    assert prec.dismissed_at is not None


@pytest.mark.integration
async def test_dismiss_precedent_hides_from_list(
    client: AsyncClient,
    db_session: AsyncSession,
    user_a: User,
) -> None:
    prec = await _make_precedent(db_session, user=user_a)
    await client.post(f"/api/v1/autonomous/precedents/{prec.id}/dismiss", headers=_bearer(user_a))

    resp = await client.get("/api/v1/autonomous/precedents", headers=_bearer(user_a))
    body = resp.json()
    assert str(prec.id) not in {e["id"] for e in body["entries"]}
    assert body["total_count"] == 0


@pytest.mark.integration
async def test_dismiss_precedent_idempotent(
    client: AsyncClient,
    db_session: AsyncSession,
    user_a: User,
) -> None:
    import datetime as _dt

    prec = await _make_precedent(db_session, user=user_a)
    resp1 = await client.post(
        f"/api/v1/autonomous/precedents/{prec.id}/dismiss", headers=_bearer(user_a)
    )
    first = _dt.datetime.fromisoformat(resp1.json()["dismissed_at"])

    resp2 = await client.post(
        f"/api/v1/autonomous/precedents/{prec.id}/dismiss", headers=_bearer(user_a)
    )
    assert resp2.status_code == 200, resp2.text
    second = _dt.datetime.fromisoformat(resp2.json()["dismissed_at"])
    assert first == second, "re-dismiss must preserve the original dismissed_at"


@pytest.mark.integration
async def test_dismiss_precedent_cross_user_returns_404(
    client: AsyncClient,
    db_session: AsyncSession,
    user_a: User,
    user_b: User,
) -> None:
    prec_b = await _make_precedent(db_session, user=user_b)
    resp = await client.post(
        f"/api/v1/autonomous/precedents/{prec_b.id}/dismiss",
        headers=_bearer(user_a),
    )
    assert resp.status_code == 404, resp.text


@pytest.mark.integration
async def test_dismiss_precedent_writes_audit_row(
    client: AsyncClient,
    db_session: AsyncSession,
    user_a: User,
) -> None:
    from app.models.audit import AuditLog

    prec = await _make_precedent(db_session, user=user_a)
    await client.post(f"/api/v1/autonomous/precedents/{prec.id}/dismiss", headers=_bearer(user_a))

    rows = (
        (
            await db_session.execute(
                select(AuditLog)
                .where(AuditLog.action == "autonomous_precedent.dismiss")
                .where(AuditLog.resource_id == str(prec.id))
            )
        )
        .scalars()
        .all()
    )
    assert len(rows) == 1


@pytest.mark.integration
async def test_dismiss_precedent_unauth_returns_401(
    client: AsyncClient,
    db_session: AsyncSession,
    user_a: User,
) -> None:
    prec = await _make_precedent(db_session, user=user_a)
    resp = await client.post(f"/api/v1/autonomous/precedents/{prec.id}/dismiss")
    assert resp.status_code == 401, resp.text


# ---------------------------------------------------------------------------
# POST /autonomous/precedents/{id}/promote
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_promote_creates_proposal(
    client: AsyncClient,
    db_session: AsyncSession,
    user_a: User,
) -> None:
    prec = await _make_precedent(
        db_session, user=user_a, pattern_kind="liability_cap", summary="12-month cap"
    )
    project = await _make_project(db_session, user=user_a)

    resp = await client.post(
        f"/api/v1/autonomous/precedents/{prec.id}/promote",
        headers=_bearer(user_a),
        json={"project_id": str(project.id)},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["state"] == "proposed"
    assert body["precedent_id"] == str(prec.id)
    assert body["project_id"] == str(project.id)
    # suggested_md is derived server-side from the precedent's summary.
    assert "liability_cap" in body["suggested_md"]
    assert "12-month cap" in body["suggested_md"]


@pytest.mark.integration
async def test_promote_does_not_modify_context_md(
    client: AsyncClient,
    db_session: AsyncSession,
    user_a: User,
) -> None:
    prec = await _make_precedent(db_session, user=user_a)
    project = await _make_project(db_session, user=user_a, context_md="untouched")

    resp = await client.post(
        f"/api/v1/autonomous/precedents/{prec.id}/promote",
        headers=_bearer(user_a),
        json={"project_id": str(project.id)},
    )
    assert resp.status_code == 201, resp.text

    await db_session.refresh(project)
    assert project.context_md == "untouched", "promote must not write context_md"


@pytest.mark.integration
async def test_promote_unowned_project_returns_404(
    client: AsyncClient,
    db_session: AsyncSession,
    user_a: User,
    user_b: User,
) -> None:
    prec = await _make_precedent(db_session, user=user_a)
    project_b = await _make_project(db_session, user=user_b)

    resp = await client.post(
        f"/api/v1/autonomous/precedents/{prec.id}/promote",
        headers=_bearer(user_a),
        json={"project_id": str(project_b.id)},
    )
    assert resp.status_code == 404, resp.text


@pytest.mark.integration
async def test_promote_cross_user_precedent_returns_404(
    client: AsyncClient,
    db_session: AsyncSession,
    user_a: User,
    user_b: User,
) -> None:
    prec_b = await _make_precedent(db_session, user=user_b)
    project_a = await _make_project(db_session, user=user_a)

    resp = await client.post(
        f"/api/v1/autonomous/precedents/{prec_b.id}/promote",
        headers=_bearer(user_a),
        json={"project_id": str(project_a.id)},
    )
    assert resp.status_code == 404, resp.text


@pytest.mark.integration
async def test_promote_writes_audit_row(
    client: AsyncClient,
    db_session: AsyncSession,
    user_a: User,
) -> None:
    from app.models.audit import AuditLog

    prec = await _make_precedent(db_session, user=user_a)
    project = await _make_project(db_session, user=user_a)
    await client.post(
        f"/api/v1/autonomous/precedents/{prec.id}/promote",
        headers=_bearer(user_a),
        json={"project_id": str(project.id)},
    )

    rows = (
        (
            await db_session.execute(
                select(AuditLog)
                .where(AuditLog.action == "autonomous_precedent.promote")
                .where(AuditLog.resource_id == str(prec.id))
            )
        )
        .scalars()
        .all()
    )
    assert len(rows) == 1


@pytest.mark.integration
async def test_promote_unauth_returns_401(
    client: AsyncClient,
    db_session: AsyncSession,
    user_a: User,
) -> None:
    prec = await _make_precedent(db_session, user=user_a)
    project = await _make_project(db_session, user=user_a)
    resp = await client.post(
        f"/api/v1/autonomous/precedents/{prec.id}/promote",
        json={"project_id": str(project.id)},
    )
    assert resp.status_code == 401, resp.text


# ---------------------------------------------------------------------------
# GET /autonomous/project-context-proposals
# ---------------------------------------------------------------------------


async def _make_proposal(
    db: AsyncSession,
    *,
    user: User,
    project: Project,
    precedent: PrecedentEntry,
    state: str = "proposed",
    suggested_md: str = "- suggested",
) -> ProjectContextProposal:
    proposal = ProjectContextProposal(
        user_id=user.id,
        precedent_id=precedent.id,
        project_id=project.id,
        suggested_md=suggested_md,
        state=state,
    )
    db.add(proposal)
    await db.flush()
    await db.refresh(proposal)
    return proposal


@pytest.mark.integration
async def test_list_proposals_isolation(
    client: AsyncClient,
    db_session: AsyncSession,
    user_a: User,
    user_b: User,
) -> None:
    prec_a = await _make_precedent(db_session, user=user_a)
    proj_a = await _make_project(db_session, user=user_a)
    prop_a = await _make_proposal(db_session, user=user_a, project=proj_a, precedent=prec_a)

    prec_b = await _make_precedent(db_session, user=user_b)
    proj_b = await _make_project(db_session, user=user_b)
    prop_b = await _make_proposal(db_session, user=user_b, project=proj_b, precedent=prec_b)

    resp = await client.get("/api/v1/autonomous/project-context-proposals", headers=_bearer(user_a))
    body = resp.json()
    ids = {p["id"] for p in body["proposals"]}
    assert str(prop_a.id) in ids
    assert str(prop_b.id) not in ids
    assert body["total_count"] == 1


@pytest.mark.integration
async def test_list_proposals_state_and_project_filters(
    client: AsyncClient,
    db_session: AsyncSession,
    user_a: User,
) -> None:
    prec = await _make_precedent(db_session, user=user_a)
    proj1 = await _make_project(db_session, user=user_a, slug="p1")
    proj2 = await _make_project(db_session, user=user_a, slug="p2")

    p_proposed = await _make_proposal(
        db_session, user=user_a, project=proj1, precedent=prec, state="proposed"
    )
    p_accepted = await _make_proposal(
        db_session, user=user_a, project=proj1, precedent=prec, state="accepted"
    )
    p_other_proj = await _make_proposal(
        db_session, user=user_a, project=proj2, precedent=prec, state="proposed"
    )

    # state filter
    resp = await client.get(
        "/api/v1/autonomous/project-context-proposals",
        headers=_bearer(user_a),
        params={"state": "accepted"},
    )
    ids = {p["id"] for p in resp.json()["proposals"]}
    assert ids == {str(p_accepted.id)}

    # project filter
    resp = await client.get(
        "/api/v1/autonomous/project-context-proposals",
        headers=_bearer(user_a),
        params={"project_id": str(proj2.id)},
    )
    ids = {p["id"] for p in resp.json()["proposals"]}
    assert ids == {str(p_other_proj.id)}

    # combined
    resp = await client.get(
        "/api/v1/autonomous/project-context-proposals",
        headers=_bearer(user_a),
        params={"state": "proposed", "project_id": str(proj1.id)},
    )
    ids = {p["id"] for p in resp.json()["proposals"]}
    assert ids == {str(p_proposed.id)}


@pytest.mark.integration
async def test_list_proposals_pagination(
    client: AsyncClient,
    db_session: AsyncSession,
    user_a: User,
) -> None:
    prec = await _make_precedent(db_session, user=user_a)
    proj = await _make_project(db_session, user=user_a)
    for _ in range(4):
        await _make_proposal(db_session, user=user_a, project=proj, precedent=prec)

    resp = await client.get(
        "/api/v1/autonomous/project-context-proposals",
        headers=_bearer(user_a),
        params={"limit": 2, "offset": 1},
    )
    body = resp.json()
    assert len(body["proposals"]) == 2
    assert body["total_count"] == 4
    assert body["limit"] == 2
    assert body["offset"] == 1


@pytest.mark.integration
async def test_list_proposals_unauth_returns_401(client: AsyncClient) -> None:
    resp = await client.get("/api/v1/autonomous/project-context-proposals")
    assert resp.status_code == 401, resp.text


# ---------------------------------------------------------------------------
# POST .../{id}/accept — the user-authorized context_md write
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_accept_appends_to_context_md(
    client: AsyncClient,
    db_session: AsyncSession,
    user_a: User,
) -> None:
    prec = await _make_precedent(db_session, user=user_a)
    project = await _make_project(db_session, user=user_a, context_md="existing")
    proposal = await _make_proposal(
        db_session, user=user_a, project=project, precedent=prec, suggested_md="- new line"
    )

    resp = await client.post(
        f"/api/v1/autonomous/project-context-proposals/{proposal.id}/accept",
        headers=_bearer(user_a),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["state"] == "accepted"
    assert body["accepted_at"] is not None

    await db_session.refresh(project)
    assert project.context_md == "existing\n- new line"


@pytest.mark.integration
async def test_accept_initializes_null_context_md(
    client: AsyncClient,
    db_session: AsyncSession,
    user_a: User,
) -> None:
    prec = await _make_precedent(db_session, user=user_a)
    project = await _make_project(db_session, user=user_a, context_md=None)
    proposal = await _make_proposal(
        db_session, user=user_a, project=project, precedent=prec, suggested_md="- first context"
    )

    resp = await client.post(
        f"/api/v1/autonomous/project-context-proposals/{proposal.id}/accept",
        headers=_bearer(user_a),
    )
    assert resp.status_code == 200, resp.text

    await db_session.refresh(project)
    assert project.context_md == "- first context"


@pytest.mark.integration
async def test_accept_double_does_not_double_append(
    client: AsyncClient,
    db_session: AsyncSession,
    user_a: User,
) -> None:
    prec = await _make_precedent(db_session, user=user_a)
    project = await _make_project(db_session, user=user_a, context_md="base")
    proposal = await _make_proposal(
        db_session, user=user_a, project=project, precedent=prec, suggested_md="- once"
    )

    await client.post(
        f"/api/v1/autonomous/project-context-proposals/{proposal.id}/accept",
        headers=_bearer(user_a),
    )
    resp2 = await client.post(
        f"/api/v1/autonomous/project-context-proposals/{proposal.id}/accept",
        headers=_bearer(user_a),
    )
    assert resp2.status_code == 200, resp2.text

    await db_session.refresh(project)
    assert project.context_md == "base\n- once", "double-accept must not double-append"


@pytest.mark.integration
async def test_accept_reject_accept_does_not_double_append(
    client: AsyncClient,
    db_session: AsyncSession,
    user_a: User,
) -> None:
    """accept→reject→accept must append the suggested_md EXACTLY once.

    Regression for C1: the append was gated on the *current* state
    (``state != 'accepted'``), but reject permits accepted→rejected. So
    accept→reject→accept saw ``state != 'accepted'`` on the second accept
    and re-appended, corrupting projects.context_md (the ADR 0013 D5
    boundary). The fix gates the append on ``accepted_at`` (one-shot per
    proposal lifetime), so a rejected→accepted transition re-records the
    'accepted' state but does NOT re-append.
    """
    prec = await _make_precedent(db_session, user=user_a)
    project = await _make_project(db_session, user=user_a, context_md="base")
    proposal = await _make_proposal(
        db_session, user=user_a, project=project, precedent=prec, suggested_md="- once-only"
    )

    # First accept — appends once.
    resp1 = await client.post(
        f"/api/v1/autonomous/project-context-proposals/{proposal.id}/accept",
        headers=_bearer(user_a),
    )
    assert resp1.status_code == 200, resp1.text
    await db_session.refresh(project)
    assert project.context_md == "base\n- once-only"

    # Reject (accepted → rejected is permitted).
    resp2 = await client.post(
        f"/api/v1/autonomous/project-context-proposals/{proposal.id}/reject",
        headers=_bearer(user_a),
    )
    assert resp2.status_code == 200, resp2.text

    # Accept again — must re-record 'accepted' but NOT re-append.
    resp3 = await client.post(
        f"/api/v1/autonomous/project-context-proposals/{proposal.id}/accept",
        headers=_bearer(user_a),
    )
    assert resp3.status_code == 200, resp3.text
    assert resp3.json()["state"] == "accepted"

    await db_session.refresh(project)
    assert project.context_md.count("- once-only") == 1, (
        "accept→reject→accept must not double-append suggested_md"
    )
    assert project.context_md == "base\n- once-only"


@pytest.mark.integration
async def test_accept_cross_user_returns_404(
    client: AsyncClient,
    db_session: AsyncSession,
    user_a: User,
    user_b: User,
) -> None:
    prec_b = await _make_precedent(db_session, user=user_b)
    proj_b = await _make_project(db_session, user=user_b)
    prop_b = await _make_proposal(db_session, user=user_b, project=proj_b, precedent=prec_b)

    resp = await client.post(
        f"/api/v1/autonomous/project-context-proposals/{prop_b.id}/accept",
        headers=_bearer(user_a),
    )
    assert resp.status_code == 404, resp.text


@pytest.mark.integration
async def test_accept_writes_audit_row(
    client: AsyncClient,
    db_session: AsyncSession,
    user_a: User,
) -> None:
    from app.models.audit import AuditLog

    prec = await _make_precedent(db_session, user=user_a)
    project = await _make_project(db_session, user=user_a)
    proposal = await _make_proposal(db_session, user=user_a, project=project, precedent=prec)

    await client.post(
        f"/api/v1/autonomous/project-context-proposals/{proposal.id}/accept",
        headers=_bearer(user_a),
    )

    rows = (
        (
            await db_session.execute(
                select(AuditLog)
                .where(AuditLog.action == "project_context_proposal.accept")
                .where(AuditLog.resource_id == str(proposal.id))
            )
        )
        .scalars()
        .all()
    )
    assert len(rows) == 1


@pytest.mark.integration
async def test_accept_unauth_returns_401(
    client: AsyncClient,
    db_session: AsyncSession,
    user_a: User,
) -> None:
    prec = await _make_precedent(db_session, user=user_a)
    project = await _make_project(db_session, user=user_a)
    proposal = await _make_proposal(db_session, user=user_a, project=project, precedent=prec)
    resp = await client.post(f"/api/v1/autonomous/project-context-proposals/{proposal.id}/accept")
    assert resp.status_code == 401, resp.text


# ---------------------------------------------------------------------------
# POST .../{id}/reject
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_reject_sets_rejected_and_leaves_context(
    client: AsyncClient,
    db_session: AsyncSession,
    user_a: User,
) -> None:
    prec = await _make_precedent(db_session, user=user_a)
    project = await _make_project(db_session, user=user_a, context_md="keep me")
    proposal = await _make_proposal(
        db_session, user=user_a, project=project, precedent=prec, suggested_md="- ignored"
    )

    resp = await client.post(
        f"/api/v1/autonomous/project-context-proposals/{proposal.id}/reject",
        headers=_bearer(user_a),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["state"] == "rejected"
    assert body["rejected_at"] is not None

    await db_session.refresh(project)
    assert project.context_md == "keep me", "reject must not touch context_md"


@pytest.mark.integration
async def test_reject_cross_user_returns_404(
    client: AsyncClient,
    db_session: AsyncSession,
    user_a: User,
    user_b: User,
) -> None:
    prec_b = await _make_precedent(db_session, user=user_b)
    proj_b = await _make_project(db_session, user=user_b)
    prop_b = await _make_proposal(db_session, user=user_b, project=proj_b, precedent=prec_b)

    resp = await client.post(
        f"/api/v1/autonomous/project-context-proposals/{prop_b.id}/reject",
        headers=_bearer(user_a),
    )
    assert resp.status_code == 404, resp.text


@pytest.mark.integration
async def test_reject_then_accept_appends(
    client: AsyncClient,
    db_session: AsyncSession,
    user_a: User,
) -> None:
    """A rejected proposal MAY be accepted (rejected→accepted) and appends."""
    prec = await _make_precedent(db_session, user=user_a)
    project = await _make_project(db_session, user=user_a, context_md="base")
    proposal = await _make_proposal(
        db_session, user=user_a, project=project, precedent=prec, suggested_md="- revived"
    )

    await client.post(
        f"/api/v1/autonomous/project-context-proposals/{proposal.id}/reject",
        headers=_bearer(user_a),
    )
    resp = await client.post(
        f"/api/v1/autonomous/project-context-proposals/{proposal.id}/accept",
        headers=_bearer(user_a),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["state"] == "accepted"

    await db_session.refresh(project)
    assert project.context_md == "base\n- revived"


@pytest.mark.integration
async def test_reject_writes_audit_row(
    client: AsyncClient,
    db_session: AsyncSession,
    user_a: User,
) -> None:
    from app.models.audit import AuditLog

    prec = await _make_precedent(db_session, user=user_a)
    project = await _make_project(db_session, user=user_a)
    proposal = await _make_proposal(db_session, user=user_a, project=project, precedent=prec)

    await client.post(
        f"/api/v1/autonomous/project-context-proposals/{proposal.id}/reject",
        headers=_bearer(user_a),
    )

    rows = (
        (
            await db_session.execute(
                select(AuditLog)
                .where(AuditLog.action == "project_context_proposal.reject")
                .where(AuditLog.resource_id == str(proposal.id))
            )
        )
        .scalars()
        .all()
    )
    assert len(rows) == 1


@pytest.mark.integration
async def test_reject_unauth_returns_401(
    client: AsyncClient,
    db_session: AsyncSession,
    user_a: User,
) -> None:
    prec = await _make_precedent(db_session, user=user_a)
    project = await _make_project(db_session, user=user_a)
    proposal = await _make_proposal(db_session, user=user_a, project=project, precedent=prec)
    resp = await client.post(f"/api/v1/autonomous/project-context-proposals/{proposal.id}/reject")
    assert resp.status_code == 401, resp.text


# ---------------------------------------------------------------------------
# OpenAPI conformance
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_openapi_precedent_paths_registered() -> None:
    """The six M4-B2 paths are registered in the OpenAPI spec."""
    paths = app.openapi()["paths"]
    assert "/api/v1/autonomous/precedents" in paths
    assert "/api/v1/autonomous/precedents/{precedent_id}/dismiss" in paths
    assert "/api/v1/autonomous/precedents/{precedent_id}/promote" in paths
    assert "/api/v1/autonomous/project-context-proposals" in paths
    assert "/api/v1/autonomous/project-context-proposals/{proposal_id}/accept" in paths
    assert "/api/v1/autonomous/project-context-proposals/{proposal_id}/reject" in paths


@pytest.mark.unit
def test_openapi_precedent_list_response_schema() -> None:
    schema = app.openapi()
    get_op = schema["paths"]["/api/v1/autonomous/precedents"]["get"]
    content = get_op["responses"]["200"]["content"]["application/json"]["schema"]
    ref = content.get("$ref", "")
    assert "PrecedentEntryListResponse" in ref or "entries" in content.get("properties", {})


@pytest.mark.unit
def test_openapi_promote_request_and_response_schema() -> None:
    schema = app.openapi()
    post_op = schema["paths"]["/api/v1/autonomous/precedents/{precedent_id}/promote"]["post"]
    body_ref = post_op["requestBody"]["content"]["application/json"]["schema"].get("$ref", "")
    assert "PromotePrecedentRequest" in body_ref
    resp = post_op["responses"]
    assert "201" in resp
    content = resp["201"]["content"]["application/json"]["schema"]
    assert "ProjectContextProposalRead" in content.get("$ref", "")


@pytest.mark.unit
def test_openapi_proposal_list_filters_documented() -> None:
    schema = app.openapi()
    params = schema["paths"]["/api/v1/autonomous/project-context-proposals"]["get"]["parameters"]
    names = {p["name"] for p in params}
    assert "state" in names
    assert "project_id" in names
    assert "limit" in names
    assert "offset" in names


@pytest.mark.unit
def test_openapi_b2_schemas_in_components() -> None:
    schemas = app.openapi().get("components", {}).get("schemas", {})
    assert "PrecedentEntryRead" in schemas
    assert "PrecedentEntryListResponse" in schemas
    assert "ProjectContextProposalRead" in schemas
    assert "ProjectContextProposalListResponse" in schemas
    assert "PromotePrecedentRequest" in schemas

    prop = schemas["ProjectContextProposalRead"].get("properties", {})
    for field in ("id", "user_id", "precedent_id", "project_id", "suggested_md", "state"):
        assert field in prop
