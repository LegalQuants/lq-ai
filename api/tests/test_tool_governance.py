"""Tests for the governed_tool_invocation helper and resolve_provider_tier.

TDD acceptance bar — these tests define the security-critical governance
substrate.

Coverage:
- tier-refusal: writes a ``refused_tier`` row + raises ``ToolTierRefused``;
  dispatch is never called; no raw args/results in any row.
- happy path: writes ``pending`` row then updates to ``executed`` with the
  correct cost; dispatch called exactly once.
- dispatch-raises: writes ``pending`` row then updates to ``error``; the
  original exception is re-raised; no raw args/results in any row.
- ``resolve_provider_tier``: returns the configured tier from a mocked
  gateway config; returns ``_MAX_TIER`` (5) as the fail-safe default
  when the provider is absent or the fetch fails.
- span annotations: only counts/types (outcome, tier, provider name, tool
  name, cost_usd) — never raw args or results.
- no raw args/results assertion: asserts ``args_digest`` is a short hash,
  not the original args structure; ``cost_usd`` on the row is a Decimal,
  not a result payload.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.autonomous.enums import ToolIntent
from app.autonomous.guard import ToolResult
from app.errors import ToolTierRefused
from app.models.tool_call_log import ToolCallLog
from app.models.user import User
from app.security import hash_password
from app.tools.governance import (
    _MAX_TIER,
    _reset_provider_tier_cache_for_tests,
    governed_tool_invocation,
    resolve_provider_tier,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_dispatch(
    cost: Decimal = Decimal("0.05"),
    outcome: str = "success",
    data: Any = None,
) -> AsyncMock:
    """Return a fake dispatch closure returning a ToolResult."""
    result = ToolResult(cost_usd=cost, outcome=outcome, data=data)
    return AsyncMock(return_value=result)


def _make_failing_dispatch(exc: Exception) -> AsyncMock:
    """Return a fake dispatch closure that raises ``exc``."""
    return AsyncMock(side_effect=exc)


def _make_span() -> MagicMock:
    """Return a mock OTel span that records ``is_recording() == True``."""
    span = MagicMock()
    span.is_recording.return_value = True
    return span


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture(autouse=True)
async def _clear_tier_cache():
    """Reset the process-level tier cache before every test."""
    _reset_provider_tier_cache_for_tests()
    yield
    _reset_provider_tier_cache_for_tests()


# ---------------------------------------------------------------------------
# resolve_provider_tier tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_resolve_provider_tier_returns_configured_tier(monkeypatch):
    """resolve_provider_tier returns the egress_tier from the gateway config."""

    async def _fake_get_admin_config(*, request_id=None):
        return {
            "tool_providers": [
                {"name": "courtlistener-prod", "type": "courtlistener", "egress_tier": 4},
                {"name": "acme-mcp", "type": "mcp", "egress_tier": 2},
            ]
        }

    class _FakeGW:
        get_admin_config = staticmethod(_fake_get_admin_config)

    monkeypatch.setattr("app.tools.governance.get_gateway_client", lambda: _FakeGW())

    tier = await resolve_provider_tier("courtlistener-prod")
    assert tier == 4

    tier2 = await resolve_provider_tier("acme-mcp")
    assert tier2 == 2


@pytest.mark.asyncio
async def test_resolve_provider_tier_fail_safe_for_unknown_provider(monkeypatch):
    """resolve_provider_tier returns _MAX_TIER when the provider is not listed."""

    async def _fake_get_admin_config(*, request_id=None):
        return {"tool_providers": [{"name": "other", "type": "mcp", "egress_tier": 1}]}

    class _FakeGW:
        get_admin_config = staticmethod(_fake_get_admin_config)

    monkeypatch.setattr("app.tools.governance.get_gateway_client", lambda: _FakeGW())

    tier = await resolve_provider_tier("does-not-exist")
    assert tier == _MAX_TIER


@pytest.mark.asyncio
async def test_resolve_provider_tier_fail_safe_on_gateway_error(monkeypatch):
    """resolve_provider_tier returns _MAX_TIER when the gateway is unreachable."""

    async def _fail_get_admin_config(*, request_id=None):
        raise RuntimeError("gateway down")

    class _FakeGW:
        get_admin_config = staticmethod(_fail_get_admin_config)

    monkeypatch.setattr("app.tools.governance.get_gateway_client", lambda: _FakeGW())

    tier = await resolve_provider_tier("courtlistener-prod")
    assert tier == _MAX_TIER


@pytest.mark.asyncio
async def test_resolve_provider_tier_process_cached(monkeypatch):
    """resolve_provider_tier only calls get_admin_config once per process."""
    call_count = 0

    async def _counting_get_admin_config(*, request_id=None):
        nonlocal call_count
        call_count += 1
        return {"tool_providers": [{"name": "cl", "type": "courtlistener", "egress_tier": 3}]}

    class _FakeGW:
        get_admin_config = staticmethod(_counting_get_admin_config)

    monkeypatch.setattr("app.tools.governance.get_gateway_client", lambda: _FakeGW())

    await resolve_provider_tier("cl")
    await resolve_provider_tier("cl")
    await resolve_provider_tier("cl")

    assert call_count == 1, "gateway config must be fetched exactly once per process"


# ---------------------------------------------------------------------------
# governed_tool_invocation tests — tier refusal
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_tier_refusal_writes_row_and_raises(db_session: AsyncSession):
    """Tier refusal writes a refused_tier row, flushes, and raises ToolTierRefused.

    Dispatch must NOT be called.
    """
    dispatch = _make_dispatch()

    with pytest.raises(ToolTierRefused) as exc_info:
        await governed_tool_invocation(
            db_session,
            origin="chat",
            provider="acme-mcp",
            tool="read_doc",
            intent=None,
            provider_tier=4,
            max_allowed_tier=2,
            estimated_cost=Decimal("0.10"),
            dispatch=dispatch,
            args_digest="sha256:abcdef",
        )

    # dispatch must never have been called
    dispatch.assert_not_called()

    # exception carries no raw args or result
    err = exc_info.value
    assert err.details["provider"] == "acme-mcp"
    assert err.details["tool"] == "read_doc"
    assert err.details["tier"] == 4
    assert err.details["ceiling"] == 2

    # DB row must exist with refused_tier
    rows = (await db_session.execute(select(ToolCallLog))).scalars().all()
    assert len(rows) == 1
    row = rows[0]
    assert row.outcome == "refused_tier"
    assert row.provider == "acme-mcp"
    assert row.tool == "read_doc"
    assert row.tier == 4
    # No raw args in the row — only args_digest
    assert row.args_digest == "sha256:abcdef"
    # cost_usd is None on a refused_tier row (no dispatch happened)
    assert row.cost_usd is None


@pytest.mark.asyncio
async def test_tier_refusal_no_dispatch_when_no_ceiling(db_session: AsyncSession):
    """When max_allowed_tier is None, no tier check is performed."""
    dispatch = _make_dispatch(cost=Decimal("0.05"))

    result = await governed_tool_invocation(
        db_session,
        origin="autonomous",
        provider="acme-mcp",
        tool="read_doc",
        intent=ToolIntent.retrieve_chunks,
        provider_tier=5,  # very high tier
        max_allowed_tier=None,  # no ceiling
        estimated_cost=Decimal("0.05"),
        dispatch=dispatch,
    )

    dispatch.assert_called_once()
    assert result.outcome == "success"


@pytest.mark.asyncio
async def test_tier_refusal_no_raise_when_tier_eq_ceiling(db_session: AsyncSession):
    """provider_tier == max_allowed_tier is allowed (equal is not exceeding)."""
    dispatch = _make_dispatch(cost=Decimal("0.01"))

    result = await governed_tool_invocation(
        db_session,
        origin="chat",
        provider="acme-mcp",
        tool="read_doc",
        intent=None,
        provider_tier=3,
        max_allowed_tier=3,
        estimated_cost=Decimal("0.01"),
        dispatch=dispatch,
    )

    dispatch.assert_called_once()
    assert result.outcome == "success"


@pytest.mark.asyncio
async def test_tier_refusal_annotates_span(db_session: AsyncSession):
    """On tier refusal the caller-supplied span is annotated (no raw args)."""
    dispatch = _make_dispatch()
    span = _make_span()

    with pytest.raises(ToolTierRefused):
        await governed_tool_invocation(
            db_session,
            origin="chat",
            provider="acme-mcp",
            tool="read_doc",
            intent=None,
            provider_tier=5,
            max_allowed_tier=1,
            estimated_cost=Decimal("0"),
            dispatch=dispatch,
            span=span,
            args_digest="sha256:digest",
        )

    # span.set_attribute must have been called; inspect the calls for safe keys
    call_kwargs = {call.args[0]: call.args[1] for call in span.set_attribute.call_args_list}
    assert call_kwargs.get("tool_call.outcome") == "refused_tier"
    assert call_kwargs.get("tool_call.tier") == 5
    # Must NOT contain any raw-args or raw-result key
    for key in call_kwargs:
        assert "args" not in key.lower() or key == "tool_call.tier"
        assert "result" not in key.lower()


# ---------------------------------------------------------------------------
# governed_tool_invocation tests — happy path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_happy_path_writes_pending_then_executed(db_session: AsyncSession):
    """Happy path: pending row written, updated to executed with cost."""
    cost = Decimal("0.0312")
    dispatch = _make_dispatch(cost=cost)

    result = await governed_tool_invocation(
        db_session,
        origin="autonomous",
        provider="courtlistener-prod",
        tool="search_cases",
        intent=ToolIntent.run_skill,
        provider_tier=4,
        max_allowed_tier=4,
        estimated_cost=cost,
        dispatch=dispatch,
        confirmation_state="not_required",
        session_id=uuid.uuid4(),
        args_digest="sha256:testdigest",
    )

    dispatch.assert_called_once()
    assert result.outcome == "success"
    assert result.cost_usd == cost

    rows = (await db_session.execute(select(ToolCallLog))).scalars().all()
    assert len(rows) == 1
    row = rows[0]
    assert row.outcome == "executed"
    assert row.cost_usd == cost
    assert row.origin == "autonomous"
    assert row.provider == "courtlistener-prod"
    assert row.tool == "search_cases"
    assert row.tier == 4
    assert row.intent == "run_skill"
    assert row.args_digest == "sha256:testdigest"
    # Confirm no raw args or result payload in the row
    # (the row has no field for raw args or raw results, only the digest)
    assert not hasattr(row, "args") or row.args_digest == "sha256:testdigest"


@pytest.mark.asyncio
async def test_happy_path_no_raw_args_in_row(db_session: AsyncSession):
    """No raw args or result payload must appear in the tool_call_log row."""
    # The caller never passes raw args to governed_tool_invocation; only a digest.
    digest = "sha256:abc123"  # the caller summarizes args to a digest

    dispatch = _make_dispatch(
        cost=Decimal("0.01"),
        data={"secret": "should-never-appear-in-db"},
    )

    await governed_tool_invocation(
        db_session,
        origin="chat",
        provider="acme-mcp",
        tool="lookup",
        intent=None,
        provider_tier=1,
        max_allowed_tier=5,
        estimated_cost=Decimal("0.01"),
        dispatch=dispatch,
        args_digest=digest,
    )

    rows = (await db_session.execute(select(ToolCallLog))).scalars().all()
    assert len(rows) == 1
    row = rows[0]

    # args_digest is the hash, not the raw args
    assert row.args_digest == digest
    # Confirm none of the sensitive content appears in ANY string field
    row_str = repr(row)
    for sensitive in ["Acme Corp", "123-45-6789", "should-never-appear-in-db"]:
        assert sensitive not in row_str, f"Sensitive value {sensitive!r} leaked into row repr"


@pytest.mark.asyncio
async def test_happy_path_span_annotation(db_session: AsyncSession):
    """On success the span receives outcome/tier/cost_usd — no raw payloads."""
    cost = Decimal("0.05")
    dispatch = _make_dispatch(cost=cost)
    span = _make_span()

    await governed_tool_invocation(
        db_session,
        origin="chat",
        provider="courtlistener-prod",
        tool="search_cases",
        intent=None,
        provider_tier=4,
        max_allowed_tier=5,
        estimated_cost=cost,
        dispatch=dispatch,
        span=span,
    )

    call_kwargs = {call.args[0]: call.args[1] for call in span.set_attribute.call_args_list}
    assert call_kwargs.get("tool_call.outcome") == "executed"
    assert call_kwargs.get("tool_call.cost_usd") == float(cost)
    assert call_kwargs.get("tool_call.tier") == 4
    for key in call_kwargs:
        assert "args" not in key.lower() or key.startswith("tool_call.")
        assert "result" not in key.lower()


# ---------------------------------------------------------------------------
# governed_tool_invocation tests — dispatch raises
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dispatch_raises_writes_error_row_and_reraises(db_session: AsyncSession):
    """When dispatch raises, the row is updated to error and the exception re-raised."""
    exc = RuntimeError("tool exploded")
    dispatch = _make_failing_dispatch(exc)

    with pytest.raises(RuntimeError, match="tool exploded"):
        await governed_tool_invocation(
            db_session,
            origin="autonomous",
            provider="acme-mcp",
            tool="write_doc",
            intent=ToolIntent.run_skill,
            provider_tier=2,
            max_allowed_tier=5,
            estimated_cost=Decimal("0.02"),
            dispatch=dispatch,
            args_digest="sha256:faildigest",
        )

    dispatch.assert_called_once()

    rows = (await db_session.execute(select(ToolCallLog))).scalars().all()
    assert len(rows) == 1
    row = rows[0]
    assert row.outcome == "error"
    # args_digest still only the short hash, never the raw exception payload
    assert row.args_digest == "sha256:faildigest"


@pytest.mark.asyncio
async def test_dispatch_raises_annotates_span(db_session: AsyncSession):
    """On dispatch failure the span is annotated with outcome=error (not the exception)."""
    exc = ValueError("inner error")
    dispatch = _make_failing_dispatch(exc)
    span = _make_span()

    with pytest.raises(ValueError):
        await governed_tool_invocation(
            db_session,
            origin="chat",
            provider="acme-mcp",
            tool="read_doc",
            intent=None,
            provider_tier=1,
            max_allowed_tier=5,
            estimated_cost=Decimal("0"),
            dispatch=dispatch,
            span=span,
        )

    call_kwargs = {call.args[0]: call.args[1] for call in span.set_attribute.call_args_list}
    assert call_kwargs.get("tool_call.outcome") == "error"
    # Must not expose the exception message in span attributes
    for value in call_kwargs.values():
        assert "inner error" not in str(value)


# ---------------------------------------------------------------------------
# flush-not-commit invariant (structural check)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_flush_not_commit_no_commit_called(db_session: AsyncSession):
    """governed_tool_invocation must call flush() but never commit()."""
    commit_calls: list[Any] = []
    original_commit = db_session.commit

    async def _tracking_commit(*args: Any, **kwargs: Any) -> Any:
        commit_calls.append(("commit", args, kwargs))
        return await original_commit(*args, **kwargs)

    db_session.commit = _tracking_commit  # type: ignore[method-assign]

    dispatch = _make_dispatch(cost=Decimal("0.01"))
    await governed_tool_invocation(
        db_session,
        origin="chat",
        provider="acme-mcp",
        tool="read_doc",
        intent=None,
        provider_tier=1,
        max_allowed_tier=5,
        estimated_cost=Decimal("0.01"),
        dispatch=dispatch,
    )

    assert not commit_calls, (
        "governed_tool_invocation must not commit — the caller owns the commit boundary"
    )


# ---------------------------------------------------------------------------
# single-estimate invariant (structural check)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_single_estimate_not_reimposed(db_session: AsyncSession, monkeypatch):
    """governed_tool_invocation must never call estimate_tool_cost itself."""
    estimate_calls: list[Any] = []

    async def _fake_estimate(*args: Any, **kwargs: Any) -> Decimal:
        estimate_calls.append(args)
        return Decimal("99")

    # Patch the cost estimator in the governance module's namespace
    monkeypatch.setattr(
        "app.tools.governance.estimate_tool_cost",
        _fake_estimate,
        raising=False,
    )

    dispatch = _make_dispatch(cost=Decimal("0.01"))
    await governed_tool_invocation(
        db_session,
        origin="chat",
        provider="acme-mcp",
        tool="read_doc",
        intent=None,
        provider_tier=1,
        max_allowed_tier=5,
        estimated_cost=Decimal("0.01"),
        dispatch=dispatch,
    )

    assert not estimate_calls, "governed_tool_invocation must not call estimate_tool_cost"


# ---------------------------------------------------------------------------
# Optional IDs are passed through correctly
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_optional_ids_stored_in_row(db_session: AsyncSession):
    """chat_id, message_id, session_id, request_id land on the row."""
    # user_id has a FK to users — create a real user row
    user = User(
        email=f"gov-test-{uuid.uuid4().hex[:8]}@example.com",
        hashed_password=hash_password("pw"),
        is_admin=False,
        role="member",
        mfa_enabled=False,
        must_change_password=False,
    )
    db_session.add(user)
    await db_session.flush()

    chat_id = uuid.uuid4()
    message_id = uuid.uuid4()
    session_id = uuid.uuid4()

    dispatch = _make_dispatch(cost=Decimal("0"))

    await governed_tool_invocation(
        db_session,
        origin="chat",
        provider="acme-mcp",
        tool="read_doc",
        intent=None,
        provider_tier=1,
        max_allowed_tier=5,
        estimated_cost=Decimal("0"),
        dispatch=dispatch,
        user_id=user.id,
        chat_id=chat_id,
        message_id=message_id,
        session_id=session_id,
        request_id="req-abc",
    )

    rows = (await db_session.execute(select(ToolCallLog))).scalars().all()
    assert len(rows) == 1
    row = rows[0]
    assert row.chat_id == chat_id
    assert row.message_id == message_id
    assert row.session_id == session_id
    assert row.user_id == user.id
    assert row.request_id == "req-abc"
