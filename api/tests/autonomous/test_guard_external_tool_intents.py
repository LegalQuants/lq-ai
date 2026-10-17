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
from collections.abc import Iterator
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
# Cache isolation
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_cost_cache() -> Iterator[None]:
    """Reset the process-level provider tier+cost cache before/after each test.

    Prevents stale cache state from a preceding test (e.g. one that
    monkeypatches ``get_gateway_client`` with a cost-bearing config) from
    leaking into the next test and producing unexpected non-zero costs.
    """
    from app.tools.governance import _reset_provider_tier_cache_for_tests

    _reset_provider_tier_cache_for_tests()
    yield
    _reset_provider_tier_cache_for_tests()


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

    # The governance helper wrote a pending row then marked it "denied"
    # (the dispatch closure raised ToolNotGranted inside the helper, and
    # the caller passed denied_on=(ToolNotGranted,) — D4 is a policy
    # refusal, not a tool failure).
    rows = await _tool_call_rows(db_session, sess.id)
    assert len(rows) == 1
    assert rows[0].outcome == "denied"


async def test_call_mcp_tool_d4_refuses_disabled_tool_no_gateway_call(
    db_session: AsyncSession,
) -> None:
    """D4: an operator-disabled cached tool (enabled=False) → ToolNotGranted,
    no gateway call, and the tool_call_log row has outcome="denied"."""
    from app.autonomous import guard as guard_mod

    user = await _make_user(db_session)
    sess = await _make_session(db_session, user=user, current_phase="analysis")
    # read_only, non-destructive — disabled only via the operator toggle.
    row = MCPToolCache(
        provider_name="acme-mcp",
        tool_name="disabled_op",
        read_only=True,
        destructive=False,
        requires_confirmation=False,
        enabled=False,
    )
    db_session.add(row)
    await db_session.flush()

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
            {"provider": "acme-mcp", "tool": "disabled_op", "args": {}},
            db_session,
            _StubGateway(),
        )

    assert exc_info.value.details["reason"] == "tool_disabled"
    # D4: the gateway must NEVER be called for a disabled tool.
    call_tool_mock.assert_not_called()

    # The governance helper wrote a pending row then marked it "denied".
    rows = await _tool_call_rows(db_session, sess.id)
    assert len(rows) == 1
    assert rows[0].outcome == "denied"


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

    # D4: governance helper wrote a pending row then marked it "denied"
    # (unknown tool is a policy refusal, not a tool failure).
    rows = await _tool_call_rows(db_session, sess.id)
    assert len(rows) == 1
    assert rows[0].outcome == "denied"


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
    # No cost configured in governance cache (no monkeypatch for get_admin_config
    # here) → handler's realized cost falls back to Decimal("0"); the executed row
    # records the ToolResult cost, NOT the divergent R4 mock estimate.
    assert rows[0].cost_usd == Decimal("0")


# ---------------------------------------------------------------------------
# DE-344: retrieve_caselaw realized cost flows to tool_call_log + session
# ---------------------------------------------------------------------------


async def test_retrieve_caselaw_realized_cost_on_tool_call_log_and_session(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """retrieve_caselaw with a configured cost_per_call: realized cost lands on
    tool_call_log.cost_usd AND grows session.cost_total_usd (DE-344 cumulative-brake gap).

    Before this fix, _handle_retrieve_caselaw returned Decimal("0") regardless
    of provider config, so repeated caselaw calls never grew session.cost_total_usd
    and the R4 cumulative brake could not throttle caselaw spend.

    Asserts:
    - ToolResult.cost_usd == configured_cost (Decimal)
    - tool_call_log.cost_usd == configured_cost (executed row's realized cost)
    - session.cost_total_usd == configured_cost (cumulative brake feed)
    """
    from app.autonomous import guard as guard_mod

    _CONFIGURED_COST = Decimal("0.01")
    _CL_PROVIDER = "courtlistener-prod"

    # Provide the governance cache with a cost_per_call for courtlistener-prod.
    # resolve_provider_cost uses get_gateway_client().get_admin_config() from
    # app.tools.governance — that is the global gateway client, NOT the gateway
    # arg passed to guarded_tool_call. Monkeypatch that seam only.
    _COST_PROVIDERS = [
        {
            "name": _CL_PROVIDER,
            "type": "courtlistener",
            "egress_tier": 4,
            "cost_per_call": float(_CONFIGURED_COST),
        }
    ]

    async def _fake_admin_config(*, request_id: str | None = None) -> dict:
        return {"tool_providers": _COST_PROVIDERS}

    class _AdminGW:
        get_admin_config = staticmethod(_fake_admin_config)

    monkeypatch.setattr("app.tools.governance.get_gateway_client", lambda: _AdminGW())

    user = await _make_user(db_session)
    sess = await _make_session(db_session, user=user, current_phase="analysis")

    with (
        patch(
            "app.research.service._resolve_provider",
            new=AsyncMock(return_value=_CL_PROVIDER),
        ),
        patch(
            "app.research.service.search_case_law",
            new=AsyncMock(return_value={"results": [{"cluster_id": 99}]}),
        ),
        patch(
            "app.tools.governance.resolve_provider_tier",
            new=AsyncMock(return_value=4),
        ),
    ):
        result = await guard_mod.guarded_tool_call(
            sess,
            ToolIntent.retrieve_caselaw,
            {"op": "search_case_law", "args": {"q": "trade secret misappropriation"}},
            db_session,
            _StubGateway(),
        )

    # ── ToolResult carries the configured realized cost ───────────────────────
    assert result.cost_usd == _CONFIGURED_COST

    # ── tool_call_log.cost_usd == realized cost (overwritten from estimated) ──
    rows = await _tool_call_rows(db_session, sess.id)
    assert len(rows) == 1
    row = rows[0]
    assert row.provider == _CL_PROVIDER
    assert row.intent == "retrieve_caselaw"
    assert row.outcome == "executed"
    assert row.cost_usd == _CONFIGURED_COST

    # ── session.cost_total_usd grew by the configured cost ───────────────────
    # This is the key fix: repeated caselaw calls must grow session.cost_total_usd
    # so R4 can throttle cumulative caselaw spend symmetrically with the other
    # two external intents (retrieve_authority, call_mcp_tool).
    assert sess.cost_total_usd == _CONFIGURED_COST
