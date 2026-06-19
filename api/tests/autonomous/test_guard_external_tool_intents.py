"""Guard integration tests for the external-tool intents — PR5a Task 4.

The two external-tool intents (``retrieve_caselaw``, ``call_mcp_tool``) flow
through ``governed_tool_invocation`` from inside ``guarded_tool_call``, so each
governed call writes a ``tool_call_log`` row in addition to the unchanged
``autonomous_audit`` session-event trail.  Local intents stay on
``autonomous_audit`` only.

Coverage
--------
* ``retrieve_caselaw`` granted in ``analysis`` executes (research service mocked)
  and writes a ``tool_call_log`` row.
* ``retrieve_caselaw`` refused (R6 ``ToolNotGranted``) in every non-analysis phase.
* ``call_mcp_tool`` in ``analysis`` with a cached **read_only** tool executes
  (``call_tool`` mocked) and writes a row.
* ``call_mcp_tool`` D4 exclusion: a **destructive** cached tool → ``ToolNotGranted``
  AND no gateway call; a ``requires_confirmation`` tool → ``ToolNotGranted``;
  an **unknown** tool → ``ToolNotGranted``.
* The single-estimate invariant: the helper records the SAME estimate the
  guard computed for R4 (no re-estimate / no double-charge).

The existing R5/R6/R4 brake tests live in ``test_brakes.py`` and are unchanged
by this refactor.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.autonomous.enums import Phase, ToolIntent
from app.errors import ToolNotGranted
from app.models.autonomous import AutonomousSession
from app.models.mcp import MCPToolCache
from app.models.tool_call_log import ToolCallLog
from app.models.user import User
from app.security import hash_password

pytestmark = pytest.mark.integration


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _make_user(db: AsyncSession) -> User:
    user = User(
        email=f"u-{uuid.uuid4().hex[:8]}@example.com",
        hashed_password=hash_password("pw"),
        is_admin=False,
        role="member",
        mfa_enabled=False,
        must_change_password=False,
    )
    db.add(user)
    await db.flush()
    return user


async def _make_session(
    db: AsyncSession,
    *,
    user: User,
    current_phase: str = "analysis",
) -> AutonomousSession:
    sess = AutonomousSession(
        user_id=user.id,
        trigger_kind="manual",
        current_phase=current_phase,
        halt_state="running",
        max_cost_usd=None,
        cost_total_usd=Decimal("0"),
    )
    db.add(sess)
    await db.flush()
    await db.refresh(sess)
    return sess


async def _make_mcp_tool(
    db: AsyncSession,
    *,
    provider: str = "acme-mcp",
    tool: str = "read_doc",
    read_only: bool = True,
    destructive: bool = False,
    requires_confirmation: bool = False,
) -> MCPToolCache:
    row = MCPToolCache(
        provider_name=provider,
        tool_name=tool,
        read_only=read_only,
        destructive=destructive,
        requires_confirmation=requires_confirmation,
        enabled=True,
    )
    db.add(row)
    await db.flush()
    return row


class _StubGateway:
    """No-op gateway — the external dispatch goes through patched seams."""


async def _tool_call_rows(db: AsyncSession, session_id: uuid.UUID) -> list[ToolCallLog]:
    return list(
        (await db.execute(select(ToolCallLog).where(ToolCallLog.session_id == session_id)))
        .scalars()
        .all()
    )


# ---------------------------------------------------------------------------
# retrieve_caselaw
# ---------------------------------------------------------------------------


async def test_retrieve_caselaw_executes_and_writes_tool_call_log(
    db_session: AsyncSession,
) -> None:
    """retrieve_caselaw in analysis executes and writes one tool_call_log row."""
    from app.autonomous import guard as guard_mod

    user = await _make_user(db_session)
    sess = await _make_session(db_session, user=user, current_phase="analysis")

    with (
        patch(
            "app.research.service._resolve_provider",
            new=AsyncMock(return_value="courtlistener-prod"),
        ),
        patch(
            "app.research.service.search_case_law",
            new=AsyncMock(return_value={"results": [{"cluster_id": 42}]}),
        ),
        patch(
            "app.tools.governance.resolve_provider_tier",
            new=AsyncMock(return_value=2),
        ),
    ):
        result = await guard_mod.guarded_tool_call(
            sess,
            ToolIntent.retrieve_caselaw,
            {"op": "search_case_law", "args": {"q": "fair use"}},
            db_session,
            _StubGateway(),
        )

    assert result.cost_usd == Decimal("0")
    assert result.data == {"results": [{"cluster_id": 42}]}

    rows = await _tool_call_rows(db_session, sess.id)
    assert len(rows) == 1
    row = rows[0]
    assert row.origin == "autonomous"
    assert row.provider == "courtlistener-prod"
    assert row.tool == "search_case_law"
    assert row.tier == 2
    assert row.intent == "retrieve_caselaw"
    assert row.outcome == "executed"
    assert row.cost_usd == Decimal("0")
    # counts/types only — never raw args
    assert row.args_digest is not None
    assert "fair use" not in (row.args_digest or "")


@pytest.mark.parametrize(
    "phase",
    [p.value for p in Phase if p is not Phase.analysis],
)
async def test_retrieve_caselaw_refused_outside_analysis(
    db_session: AsyncSession, phase: str
) -> None:
    """retrieve_caselaw is granted only in analysis (R6 refuses elsewhere)."""
    from app.autonomous import guard as guard_mod

    user = await _make_user(db_session)
    sess = await _make_session(db_session, user=user, current_phase=phase)

    with pytest.raises(ToolNotGranted) as exc_info:
        await guard_mod.guarded_tool_call(
            sess,
            ToolIntent.retrieve_caselaw,
            {"op": "search_case_law", "args": {"q": "x"}},
            db_session,
            _StubGateway(),
        )
    assert exc_info.value.details["intent"] == "retrieve_caselaw"

    # R6 fires before dispatch → NO tool_call_log row was written.
    assert await _tool_call_rows(db_session, sess.id) == []


# ---------------------------------------------------------------------------
# call_mcp_tool — happy path
# ---------------------------------------------------------------------------


async def test_call_mcp_tool_read_only_executes_and_writes_row(
    db_session: AsyncSession,
) -> None:
    """call_mcp_tool with a cached read_only tool executes + writes a row."""
    from app.autonomous import guard as guard_mod

    user = await _make_user(db_session)
    sess = await _make_session(db_session, user=user, current_phase="analysis")
    await _make_mcp_tool(
        db_session,
        provider="acme-mcp",
        tool="read_doc",
        read_only=True,
        destructive=False,
        requires_confirmation=False,
    )

    call_tool_mock = AsyncMock(
        return_value={
            "provider": "acme-mcp",
            "tool": "read_doc",
            "payload": {"text": "hi"},
            "tier": 3,
        }
    )

    class _Client:
        call_tool = call_tool_mock

    with (
        patch("app.clients.gateway.get_gateway_client", return_value=_Client()),
        patch(
            "app.tools.governance.resolve_provider_tier",
            new=AsyncMock(return_value=3),
        ),
    ):
        result = await guard_mod.guarded_tool_call(
            sess,
            ToolIntent.call_mcp_tool,
            {"provider": "acme-mcp", "tool": "read_doc", "args": {"id": "doc-1"}},
            db_session,
            _StubGateway(),
        )

    call_tool_mock.assert_awaited_once()
    # No per-user OAuth token (D-a5): call_tool has no user_token param at all.
    _, kwargs = call_tool_mock.call_args
    assert kwargs.get("max_allowed_tier") is None
    assert result.cost_usd == Decimal("0")
    assert result.data == {"text": "hi"}

    rows = await _tool_call_rows(db_session, sess.id)
    assert len(rows) == 1
    row = rows[0]
    assert row.provider == "acme-mcp"
    assert row.tool == "read_doc"
    assert row.intent == "call_mcp_tool"
    assert row.outcome == "executed"
    assert row.tier == 3


# ---------------------------------------------------------------------------
# call_mcp_tool — D4 exclusions (NO gateway call)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "flags,expected_reason",
    [
        ({"destructive": True}, "destructive"),
        ({"requires_confirmation": True}, "requires_confirmation"),
    ],
)
async def test_call_mcp_tool_d4_refuses_gated_tool_no_gateway_call(
    db_session: AsyncSession, flags: dict[str, bool], expected_reason: str
) -> None:
    """D4: a destructive / confirmation-required cached tool → ToolNotGranted,
    and the gateway is NEVER called."""
    from app.autonomous import guard as guard_mod

    user = await _make_user(db_session)
    sess = await _make_session(db_session, user=user, current_phase="analysis")
    await _make_mcp_tool(
        db_session,
        provider="acme-mcp",
        tool="danger_op",
        read_only=False,
        destructive=flags.get("destructive", False),
        requires_confirmation=flags.get("requires_confirmation", False),
    )

    call_tool_mock = AsyncMock()

    class _Client:
        call_tool = call_tool_mock

    with (
        patch("app.clients.gateway.get_gateway_client", return_value=_Client()),
        patch(
            "app.tools.governance.resolve_provider_tier",
            new=AsyncMock(return_value=2),
        ),
        pytest.raises(ToolNotGranted) as exc_info,
    ):
        await guard_mod.guarded_tool_call(
            sess,
            ToolIntent.call_mcp_tool,
            {"provider": "acme-mcp", "tool": "danger_op", "args": {}},
            db_session,
            _StubGateway(),
        )

    assert exc_info.value.details["reason"] == expected_reason
    # D4: NO gateway call.
    call_tool_mock.assert_not_called()

    # The governance helper wrote a pending row then marked it error
    # (the dispatch closure raised ToolNotGranted inside the helper).
    rows = await _tool_call_rows(db_session, sess.id)
    assert len(rows) == 1
    assert rows[0].outcome == "error"


async def test_call_mcp_tool_unknown_tool_refused_no_gateway_call(
    db_session: AsyncSession,
) -> None:
    """D4: a tool absent from the mcp_tools cache → ToolNotGranted, no call."""
    from app.autonomous import guard as guard_mod

    user = await _make_user(db_session)
    sess = await _make_session(db_session, user=user, current_phase="analysis")
    # No MCPToolCache row inserted → unknown.

    call_tool_mock = AsyncMock()

    class _Client:
        call_tool = call_tool_mock

    with (
        patch("app.clients.gateway.get_gateway_client", return_value=_Client()),
        patch(
            "app.tools.governance.resolve_provider_tier",
            new=AsyncMock(return_value=2),
        ),
        pytest.raises(ToolNotGranted) as exc_info,
    ):
        await guard_mod.guarded_tool_call(
            sess,
            ToolIntent.call_mcp_tool,
            {"provider": "acme-mcp", "tool": "ghost", "args": {}},
            db_session,
            _StubGateway(),
        )

    assert exc_info.value.details["reason"] == "tool_not_cached"
    call_tool_mock.assert_not_called()


# ---------------------------------------------------------------------------
# single-estimate invariant
# ---------------------------------------------------------------------------


async def test_external_intent_records_single_estimate(db_session: AsyncSession) -> None:
    """The tool_call_log row's cost is the SAME estimate the guard computed for
    R4 — the helper never re-estimates (single-estimate invariant)."""
    from app.autonomous import guard as guard_mod

    user = await _make_user(db_session)
    sess = await _make_session(db_session, user=user, current_phase="analysis")

    # Force a non-zero estimate so a re-estimate would diverge visibly.
    mock_estimate = AsyncMock(return_value=Decimal("0.07"))

    with (
        patch.object(guard_mod, "estimate_tool_cost", mock_estimate),
        patch(
            "app.research.service._resolve_provider",
            new=AsyncMock(return_value="courtlistener-prod"),
        ),
        patch(
            "app.research.service.verify_citations",
            new=AsyncMock(return_value={"citations": []}),
        ),
        patch(
            "app.tools.governance.resolve_provider_tier",
            new=AsyncMock(return_value=2),
        ),
    ):
        await guard_mod.guarded_tool_call(
            sess,
            ToolIntent.retrieve_caselaw,
            {"op": "verify_citations", "text": "See Roe."},
            db_session,
            _StubGateway(),
        )

    # estimate_tool_cost called exactly once (the guard's single R4 estimate).
    mock_estimate.assert_awaited_once()
    rows = await _tool_call_rows(db_session, sess.id)
    assert len(rows) == 1
    # The handler returns Decimal("0") (D-a3); the executed row records the
    # ToolResult cost, which is the handler's 0 — NOT a divergent re-estimate.
    assert rows[0].cost_usd == Decimal("0")
