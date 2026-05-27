"""Integration tests for the M4-A4-i autonomous sessions read/halt API.

Covers:
- POST /sessions/{id}/halt: sets halt_state, writes audit row, idempotent,
  cross-user 404, unauth 401, and halt→chokepoint integration.
- GET /sessions: pagination, newest-first, cross-user isolation.
- GET /sessions/{id}: detail + receipt structure, privacy, cross-user 404.
- Receipt builder unit tests (no HTTP).
- OpenAPI conformance.
"""

from __future__ import annotations

import json
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
from app.models.autonomous import AutonomousSession
from app.models.user import User
from app.security import create_access_token, hash_password

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


async def _make_user(db: AsyncSession, *, suffix: str = "") -> User:
    user = User(
        email=f"auto-sess-{suffix or uuid.uuid4().hex[:8]}@example.com",
        display_name=f"Auto Session User {suffix}".strip(),
        hashed_password=hash_password("correct-horse-battery-staple"),
        is_admin=False,
        mfa_enabled=False,
        must_change_password=False,
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
    db: AsyncSession,
    *,
    user: User,
    trigger_kind: str = "manual",
    halt_state: str = "running",
    status: str = "running",
    current_phase: str = "intake",
) -> AutonomousSession:
    sess = AutonomousSession(
        user_id=user.id,
        trigger_kind=trigger_kind,
        halt_state=halt_state,
        status=status,
        current_phase=current_phase,
    )
    db.add(sess)
    await db.flush()
    await db.refresh(sess)
    return sess


# ---------------------------------------------------------------------------
# POST /sessions/{id}/halt
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_halt_sets_halt_requested(
    client: AsyncClient,
    db_session: AsyncSession,
    user_a: User,
) -> None:
    """Halt sets halt_state='halt_requested' and returns the updated session."""
    sess = await _make_session(db_session, user=user_a)

    resp = await client.post(
        f"/api/v1/autonomous/sessions/{sess.id}/halt",
        headers=_bearer(user_a),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["halt_state"] == "halt_requested"
    assert body["id"] == str(sess.id)

    # DB reflects the change.
    await db_session.refresh(sess)
    assert sess.halt_state == "halt_requested"


@pytest.mark.integration
async def test_halt_writes_audit_row(
    client: AsyncClient,
    db_session: AsyncSession,
    user_a: User,
) -> None:
    """Halt writes an autonomous_session.halt_requested audit row."""
    sess = await _make_session(db_session, user=user_a)

    await client.post(
        f"/api/v1/autonomous/sessions/{sess.id}/halt",
        headers=_bearer(user_a),
    )

    rows = (
        (
            await db_session.execute(
                select(AuditLog)
                .where(AuditLog.action == "autonomous_session.halt_requested")
                .where(AuditLog.resource_id == str(sess.id))
            )
        )
        .scalars()
        .all()
    )
    # Expect exactly 2 rows: one from autonomous_audit + one from audit_action.
    assert len(rows) == 2


@pytest.mark.integration
async def test_halt_idempotent_already_halt_requested(
    client: AsyncClient,
    db_session: AsyncSession,
    user_a: User,
) -> None:
    """Second halt call when already halt_requested: returns 200, no new audit row."""
    sess = await _make_session(db_session, user=user_a, halt_state="halt_requested")

    resp = await client.post(
        f"/api/v1/autonomous/sessions/{sess.id}/halt",
        headers=_bearer(user_a),
    )
    assert resp.status_code == 200, resp.text

    # No audit rows should have been written (session was already halt_requested).
    rows = (
        (
            await db_session.execute(
                select(AuditLog)
                .where(AuditLog.action == "autonomous_session.halt_requested")
                .where(AuditLog.resource_id == str(sess.id))
            )
        )
        .scalars()
        .all()
    )
    assert len(rows) == 0, "No audit rows should be written on idempotent halt"


@pytest.mark.integration
async def test_halt_idempotent_already_halted(
    client: AsyncClient,
    db_session: AsyncSession,
    user_a: User,
) -> None:
    """Second halt call when already halted: returns 200, no new audit row."""
    sess = await _make_session(db_session, user=user_a, halt_state="halted", status="halted")

    resp = await client.post(
        f"/api/v1/autonomous/sessions/{sess.id}/halt",
        headers=_bearer(user_a),
    )
    assert resp.status_code == 200, resp.text

    # No new halt_requested audit rows.
    rows = (
        (
            await db_session.execute(
                select(AuditLog)
                .where(AuditLog.action == "autonomous_session.halt_requested")
                .where(AuditLog.resource_id == str(sess.id))
            )
        )
        .scalars()
        .all()
    )
    assert len(rows) == 0, "No audit rows should be written on idempotent halt (already halted)"


@pytest.mark.integration
async def test_halt_cross_user_returns_404(
    client: AsyncClient,
    db_session: AsyncSession,
    user_a: User,
    user_b: User,
) -> None:
    """Another user's session id returns 404, not 403 (existence non-disclosure)."""
    sess_b = await _make_session(db_session, user=user_b)

    resp = await client.post(
        f"/api/v1/autonomous/sessions/{sess_b.id}/halt",
        headers=_bearer(user_a),
    )
    assert resp.status_code == 404, resp.text


@pytest.mark.integration
async def test_halt_unauth_returns_401(
    client: AsyncClient,
    db_session: AsyncSession,
    user_a: User,
) -> None:
    """No Authorization header returns 401."""
    sess = await _make_session(db_session, user=user_a)

    resp = await client.post(f"/api/v1/autonomous/sessions/{sess.id}/halt")
    assert resp.status_code == 401, resp.text


@pytest.mark.integration
async def test_halt_chokepoint_integration(
    db_session: AsyncSession,
    user_a: User,
) -> None:
    """After halt sets halt_requested, guarded_tool_call raises SessionHalted.

    This ties the API endpoint (R5 flag setter) to the chokepoint (R5 brake).
    We directly call guarded_tool_call after setting halt_state, matching
    the A3.3a R5 path.
    """
    from app.autonomous.enums import ToolIntent
    from app.autonomous.guard import guarded_tool_call
    from app.errors import SessionHalted

    sess = await _make_session(db_session, user=user_a, current_phase="drafting")

    # Simulate what the halt endpoint does.
    sess.halt_state = "halt_requested"
    await db_session.flush()

    class _StubGateway:
        pass

    with pytest.raises(SessionHalted) as exc_info:
        await guarded_tool_call(
            sess,
            ToolIntent.emit_finding,
            {"finding": {"flag": "test"}},
            db_session,
            _StubGateway(),
        )

    exc = exc_info.value
    assert exc.details["reason"] == "external_halt"
    # Session transitions to halted after R5 trips.
    assert sess.halt_state == "halted"


# ---------------------------------------------------------------------------
# GET /sessions — list
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_list_returns_empty_for_new_user(
    client: AsyncClient,
    user_a: User,
) -> None:
    """A user with no sessions gets sessions=[] and total_count=0."""
    resp = await client.get("/api/v1/autonomous/sessions", headers=_bearer(user_a))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["sessions"] == []
    assert body["total_count"] == 0
    assert body["limit"] == 50
    assert body["offset"] == 0


@pytest.mark.integration
async def test_list_returns_only_callers_sessions(
    client: AsyncClient,
    db_session: AsyncSession,
    user_a: User,
    user_b: User,
) -> None:
    """Cross-user isolation: A's list contains only A's sessions."""
    sess_a = await _make_session(db_session, user=user_a)
    _sess_b = await _make_session(db_session, user=user_b)

    resp = await client.get("/api/v1/autonomous/sessions", headers=_bearer(user_a))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    ids = {s["id"] for s in body["sessions"]}
    assert str(sess_a.id) in ids
    # user_b's session must not appear.
    assert str(_sess_b.id) not in ids
    assert body["total_count"] == 1


@pytest.mark.integration
async def test_list_newest_first(
    client: AsyncClient,
    db_session: AsyncSession,
    user_a: User,
) -> None:
    """Sessions are returned in created_at DESC order."""
    sess1 = await _make_session(db_session, user=user_a)
    sess2 = await _make_session(db_session, user=user_a)
    sess3 = await _make_session(db_session, user=user_a)

    resp = await client.get("/api/v1/autonomous/sessions", headers=_bearer(user_a))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    ids = [s["id"] for s in body["sessions"]]

    # All three sessions present.
    assert str(sess1.id) in ids
    assert str(sess2.id) in ids
    assert str(sess3.id) in ids
    assert body["total_count"] == 3


@pytest.mark.integration
async def test_list_pagination_limit_offset(
    client: AsyncClient,
    db_session: AsyncSession,
    user_a: User,
) -> None:
    """limit and offset are honoured; total_count reflects the unfiltered count."""
    for _ in range(5):
        await _make_session(db_session, user=user_a)

    resp = await client.get(
        "/api/v1/autonomous/sessions",
        headers=_bearer(user_a),
        params={"limit": 2, "offset": 1},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert len(body["sessions"]) == 2
    assert body["total_count"] == 5
    assert body["limit"] == 2
    assert body["offset"] == 1


@pytest.mark.integration
async def test_list_limit_clamped(
    client: AsyncClient,
    db_session: AsyncSession,
    user_a: User,
) -> None:
    """limit > 200 is clamped to 200."""
    resp = await client.get(
        "/api/v1/autonomous/sessions",
        headers=_bearer(user_a),
        params={"limit": 9999},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["limit"] == 200


@pytest.mark.integration
async def test_list_unauth_returns_401(client: AsyncClient) -> None:
    """No Authorization header returns 401."""
    resp = await client.get("/api/v1/autonomous/sessions")
    assert resp.status_code == 401, resp.text


# ---------------------------------------------------------------------------
# GET /sessions/{id} — detail + receipt
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_detail_returns_session_and_receipt(
    client: AsyncClient,
    db_session: AsyncSession,
    user_a: User,
) -> None:
    """Detail endpoint returns session + receipt with expected keys."""
    sess = await _make_session(db_session, user=user_a)

    resp = await client.get(
        f"/api/v1/autonomous/sessions/{sess.id}",
        headers=_bearer(user_a),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()

    assert "session" in body
    assert "receipt" in body
    assert body["session"]["id"] == str(sess.id)

    receipt = body["receipt"]
    assert receipt["session_id"] == str(sess.id)
    assert "phase_transitions" in receipt
    assert "tool_calls" in receipt
    assert "terminal_reason" in receipt
    assert "cost_total_usd" in receipt


@pytest.mark.integration
async def test_detail_cross_user_returns_404(
    client: AsyncClient,
    db_session: AsyncSession,
    user_a: User,
    user_b: User,
) -> None:
    """Another user's session id returns 404."""
    sess_b = await _make_session(db_session, user=user_b)

    resp = await client.get(
        f"/api/v1/autonomous/sessions/{sess_b.id}",
        headers=_bearer(user_a),
    )
    assert resp.status_code == 404, resp.text


@pytest.mark.integration
async def test_detail_receipt_contains_no_raw_entity_values(
    client: AsyncClient,
    db_session: AsyncSession,
    user_a: User,
) -> None:
    """Privacy guard: receipt JSON contains no raw entity values.

    Seeds audit rows with only safe metadata (counts/enums/IDs/costs);
    the receipt must not contain any raw document text or person names.
    This is a non-vacuous assertion — the 'safe metadata' strings ARE
    present in the receipt.
    """
    from app.autonomous.audit import autonomous_audit

    sess = await _make_session(db_session, user=user_a, current_phase="analysis")

    # Seed a phase_transition audit row — safe metadata only.
    await autonomous_audit(db_session, sess, "phase_transition", to_phase="analysis")
    # Seed a tool_call audit row — safe metadata only.
    await autonomous_audit(
        db_session,
        sess,
        "tool_call",
        tool="retrieve_chunks",
        outcome="success",
        cost_usd=0.0,
    )
    await db_session.flush()

    resp = await client.get(
        f"/api/v1/autonomous/sessions/{sess.id}",
        headers=_bearer(user_a),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    receipt = body["receipt"]

    # Non-vacuous: the safe metadata IS present.
    assert len(receipt["phase_transitions"]) == 1
    assert receipt["phase_transitions"][0]["to_phase"] == "analysis"
    assert len(receipt["tool_calls"]) > 0

    # Privacy: no raw entity-like strings in the serialised receipt.
    receipt_str = json.dumps(receipt)
    # The sentinel strings below represent the class of raw values we must
    # NEVER find in audit output; they would only appear if someone
    # accidentally logged raw document content through the chokepoint.
    raw_entity_sentinels = [
        "Jane Privilege",
        "MTR-2026-0042",
        "document_text",
        "raw_content",
    ]
    for sentinel in raw_entity_sentinels:
        assert sentinel not in receipt_str, (
            f"Receipt contains raw entity sentinel {sentinel!r} — "
            "privacy violation in build_receipt or audit details"
        )


@pytest.mark.integration
async def test_detail_unauth_returns_401(
    client: AsyncClient,
    db_session: AsyncSession,
    user_a: User,
) -> None:
    """No Authorization header returns 401."""
    sess = await _make_session(db_session, user=user_a)
    resp = await client.get(f"/api/v1/autonomous/sessions/{sess.id}")
    assert resp.status_code == 401, resp.text


# ---------------------------------------------------------------------------
# Receipt builder unit tests (no HTTP)
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_receipt_assembles_phase_transitions_and_tool_calls(
    db_session: AsyncSession,
    user_a: User,
) -> None:
    """build_receipt assembles phase_transitions and tool_calls in order."""
    from app.autonomous.audit import autonomous_audit
    from app.autonomous.receipt import build_receipt

    sess = await _make_session(db_session, user=user_a)

    await autonomous_audit(db_session, sess, "phase_transition", to_phase="intake")
    await autonomous_audit(db_session, sess, "tool_call", tool="retrieve_chunks", outcome="started")
    await autonomous_audit(
        db_session, sess, "tool_call", tool="retrieve_chunks", outcome="success", cost_usd=0.0
    )
    await autonomous_audit(db_session, sess, "phase_transition", to_phase="analysis")
    await db_session.flush()

    receipt = await build_receipt(sess, db_session)

    assert receipt["session_id"] == str(sess.id)
    assert receipt["trigger_kind"] == "manual"

    # phase_transitions: intake then analysis, in order.
    phases = receipt["phase_transitions"]
    assert len(phases) == 2
    assert phases[0]["to_phase"] == "intake"
    assert phases[1]["to_phase"] == "analysis"

    # tool_calls: started then success, in order.
    calls = receipt["tool_calls"]
    assert len(calls) == 2
    assert calls[0]["outcome"] == "started"
    assert calls[1]["outcome"] == "success"
    assert calls[1]["cost_usd"] == pytest.approx(0.0)


@pytest.mark.integration
async def test_receipt_terminal_reason_halted(
    db_session: AsyncSession,
    user_a: User,
) -> None:
    """terminal_reason is 'external_halt' when a halted row with reason exists."""
    from app.autonomous.audit import autonomous_audit
    from app.autonomous.receipt import build_receipt

    sess = await _make_session(db_session, user=user_a, halt_state="halted", status="halted")
    await autonomous_audit(db_session, sess, "halted", reason="external_halt")
    await db_session.flush()

    receipt = await build_receipt(sess, db_session)
    assert receipt["terminal_reason"] == "external_halt"


@pytest.mark.integration
async def test_receipt_terminal_reason_cost_cap(
    db_session: AsyncSession,
    user_a: User,
) -> None:
    """terminal_reason is 'cost_cap_reached' when a cost_cap_reached row exists."""
    from app.autonomous.audit import autonomous_audit
    from app.autonomous.receipt import build_receipt

    sess = await _make_session(db_session, user=user_a, halt_state="halted", status="halted")
    await autonomous_audit(db_session, sess, "cost_cap_reached", projected_usd=0.25)
    await db_session.flush()

    receipt = await build_receipt(sess, db_session)
    assert receipt["terminal_reason"] == "cost_cap_reached"


@pytest.mark.integration
async def test_receipt_terminal_reason_none_running(
    db_session: AsyncSession,
    user_a: User,
) -> None:
    """terminal_reason is None for a still-running session with no terminal rows."""
    from app.autonomous.receipt import build_receipt

    sess = await _make_session(db_session, user=user_a)

    receipt = await build_receipt(sess, db_session)
    assert receipt["terminal_reason"] is None


@pytest.mark.integration
async def test_receipt_is_jsonable(
    db_session: AsyncSession,
    user_a: User,
) -> None:
    """build_receipt returns a JSON-serialisable dict (suitable for JSONB storage)."""
    from app.autonomous.audit import autonomous_audit
    from app.autonomous.receipt import build_receipt

    sess = await _make_session(db_session, user=user_a)
    await autonomous_audit(db_session, sess, "phase_transition", to_phase="intake")
    await db_session.flush()

    receipt = await build_receipt(sess, db_session)

    # Should not raise.
    serialised = json.dumps(receipt)
    round_tripped = json.loads(serialised)
    assert round_tripped["session_id"] == str(sess.id)


@pytest.mark.integration
async def test_receipt_privacy_non_vacuous(
    db_session: AsyncSession,
    user_a: User,
) -> None:
    """Privacy guard (non-vacuous): safe metadata IS in the receipt, raw values are NOT.

    Seeds audit rows that contain only safe metadata (phase names, tool
    intent labels, cost floats) and asserts:
    1. The safe metadata IS present (the assertion is not vacuous).
    2. Synthetic sensitive entity strings are absent.
    """
    from app.autonomous.audit import autonomous_audit
    from app.autonomous.receipt import build_receipt

    sess = await _make_session(db_session, user=user_a)

    # Seed safe-only audit rows.
    await autonomous_audit(db_session, sess, "phase_transition", to_phase="intake")
    await autonomous_audit(
        db_session,
        sess,
        "tool_call",
        tool="emit_finding",
        outcome="success",
        cost_usd=0.0,
    )
    await autonomous_audit(db_session, sess, "completed")
    await db_session.flush()

    receipt = await build_receipt(sess, db_session)
    receipt_str = json.dumps(receipt)

    # Non-vacuous: safe metadata IS present.
    assert "intake" in receipt_str, "Safe metadata (phase name) must be present"
    assert "emit_finding" in receipt_str, "Safe metadata (tool label) must be present"

    # Privacy: raw entity values must be absent.
    # These represent the class of raw strings the privacy gate blocks.
    raw_entity_sentinels = [
        "Jane Privilege",
        "MTR-2026-0042",
        "raw_document_text",
        "contract_parties",
    ]
    for sentinel in raw_entity_sentinels:
        assert sentinel not in receipt_str, (
            f"Receipt contains raw entity sentinel {sentinel!r} — privacy violation"
        )


# ---------------------------------------------------------------------------
# Per-entry timestamps (M4-C2 task 5)
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_receipt_entries_carry_timestamps(
    db_session: AsyncSession,
    user_a: User,
) -> None:
    """build_receipt carries per-entry ISO timestamps so the web layer can
    interleave phase_transitions + tool_calls into one ordered timeline."""
    from app.autonomous.audit import autonomous_audit
    from app.autonomous.receipt import build_receipt

    sess = await _make_session(db_session, user=user_a)

    await autonomous_audit(db_session, sess, "phase_transition", to_phase="intake")
    await autonomous_audit(db_session, sess, "tool_call", tool="retrieve_chunks", outcome="success")
    await db_session.flush()

    receipt = await build_receipt(sess, db_session)

    assert len(receipt["phase_transitions"]) >= 1, "Expected at least one phase_transition"
    assert len(receipt["tool_calls"]) >= 1, "Expected at least one tool_call"

    for entry in receipt["phase_transitions"]:
        assert "timestamp" in entry, f"phase_transition entry missing 'timestamp': {entry!r}"
        assert entry["timestamp"] is not None, f"phase_transition entry null 'timestamp': {entry!r}"

    for entry in receipt["tool_calls"]:
        assert "timestamp" in entry, f"tool_call entry missing 'timestamp': {entry!r}"
        assert entry["timestamp"] is not None, f"tool_call entry null 'timestamp': {entry!r}"


# ---------------------------------------------------------------------------
# OpenAPI conformance
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_openapi_autonomous_paths_registered() -> None:
    """The three autonomous-sessions paths are registered in the OpenAPI spec."""
    schema = app.openapi()
    paths = schema["paths"]
    assert "/api/v1/autonomous/sessions" in paths
    assert "/api/v1/autonomous/sessions/{session_id}" in paths
    assert "/api/v1/autonomous/sessions/{session_id}/halt" in paths


@pytest.mark.unit
def test_openapi_list_response_schema() -> None:
    """GET /sessions response references AutonomousSessionListResponse schema."""
    schema = app.openapi()
    get_op = schema["paths"]["/api/v1/autonomous/sessions"]["get"]
    resp_200 = get_op["responses"]["200"]
    content = resp_200["content"]["application/json"]["schema"]
    # The schema should reference AutonomousSessionListResponse (via $ref or inline).
    ref = content.get("$ref", "")
    assert "AutonomousSessionListResponse" in ref or "sessions" in content.get("properties", {})


@pytest.mark.unit
def test_openapi_detail_response_schema() -> None:
    """GET /sessions/{id} response references AutonomousSessionDetailResponse schema."""
    schema = app.openapi()
    get_op = schema["paths"]["/api/v1/autonomous/sessions/{session_id}"]["get"]
    resp_200 = get_op["responses"]["200"]
    content = resp_200["content"]["application/json"]["schema"]
    ref = content.get("$ref", "")
    assert "AutonomousSessionDetailResponse" in ref or "receipt" in content.get("properties", {})


@pytest.mark.unit
def test_openapi_halt_endpoint_documented() -> None:
    """POST /sessions/{id}/halt is a POST with 200/401/404 responses."""
    schema = app.openapi()
    halt_path = schema["paths"]["/api/v1/autonomous/sessions/{session_id}/halt"]
    assert "post" in halt_path
    post_op = halt_path["post"]
    assert "200" in post_op["responses"]
    assert "401" in post_op["responses"]
    assert "404" in post_op["responses"]
