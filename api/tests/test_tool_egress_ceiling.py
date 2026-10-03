"""Tests for the matter-scoped tool-egress ceiling (issue #593, DE-358 item 6 / AG-03).

Coverage:
- settings: ``LQ_AI_TOOL_MAX_EGRESS_TIER`` parsing / range validation.
- ``resolve_tool_egress_ceiling``: ``min()`` composition across the operator
  default, Project column, and orchestration scope; source attribution; a
  dangling ``project_id`` is treated as no Project; a Project-lookup error
  fail-closes with ``(None, "unresolved")``; a scope ceiling of ``0``
  resolves so the API refuses before dispatch (never sent to the gateway).
- ``resolve_resumed_ceiling``: approval executes under
  ``min(original, current)``; current-policy ``"unresolved"`` stays
  fail-closed.
- ``governed_tool_invocation``: the ceiling refuses before dispatch and the
  audit row carries ``max_allowed_tier`` + ``ceiling_source``; unresolved
  policy refuses with a refused row; no raw payloads on any row.
- Project schemas: accept 1-5, reject 0/6, update with explicit null.
- DB CHECK constraints: out-of-range tier and bad ``ceiling_source`` raise.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError as PydanticValidationError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.autonomous.guard import ToolResult
from app.config import Settings, get_settings
from app.errors import ToolTierRefused
from app.models.project import Project
from app.models.tool_call_log import ToolCallLog
from app.models.user import User
from app.schemas.projects import ProjectCreateRequest, ProjectUpdateRequest
from app.tools.governance import (
    governed_tool_invocation,
    resolve_resumed_ceiling,
    resolve_tool_egress_ceiling,
)
from tests.test_tool_call_log_model import _make_user

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@pytest.fixture
def operator_ceiling(monkeypatch):
    """Set/clear LQ_AI_TOOL_MAX_EGRESS_TIER for one test, resetting the cache."""

    def _set(value: int | None) -> None:
        if value is None:
            monkeypatch.delenv("LQ_AI_TOOL_MAX_EGRESS_TIER", raising=False)
        else:
            monkeypatch.setenv("LQ_AI_TOOL_MAX_EGRESS_TIER", str(value))
        get_settings.cache_clear()

    _set(None)
    yield _set
    get_settings.cache_clear()


async def _add_user(db: AsyncSession) -> User:
    user = _make_user()
    db.add(user)
    await db.flush()
    return user


async def _make_project(
    db: AsyncSession,
    user: User,
    *,
    max_egress_tier: int | None = None,
) -> Project:
    project = Project(
        owner_id=user.id,
        name="Ceiling Matter",
        slug=f"ceiling-matter-{uuid.uuid4().hex[:8]}",
        max_egress_tier=max_egress_tier,
    )
    db.add(project)
    await db.flush()
    return project


def _make_dispatch(data: Any = None) -> AsyncMock:
    return AsyncMock(
        return_value=ToolResult(cost_usd=Decimal("0.01"), outcome="success", data=data)
    )


async def _governed(
    db: AsyncSession,
    *,
    provider_tier: int,
    max_allowed_tier: int | None,
    ceiling_source: str | None,
    dispatch: AsyncMock,
) -> ToolCallLog | BaseException:
    try:
        await governed_tool_invocation(
            db,
            origin="chat",
            provider="courtlistener-prod",
            tool="search",
            intent=None,
            provider_tier=provider_tier,
            max_allowed_tier=max_allowed_tier,
            ceiling_source=ceiling_source,
            estimated_cost=Decimal("0.01"),
            dispatch=dispatch,
        )
    except Exception as exc:
        return exc
    rows = (await db.execute(select(ToolCallLog))).scalars().all()
    assert len(rows) == 1
    return rows[0]


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_setting_parses_valid_value(monkeypatch) -> None:
    monkeypatch.setenv("LQ_AI_TOOL_MAX_EGRESS_TIER", "2")
    assert Settings(_env_file=None).tool_max_egress_tier == 2  # type: ignore[call-arg]


@pytest.mark.unit
def test_setting_defaults_to_none(monkeypatch) -> None:
    monkeypatch.delenv("LQ_AI_TOOL_MAX_EGRESS_TIER", raising=False)
    monkeypatch.delenv("TOOL_MAX_EGRESS_TIER", raising=False)
    assert Settings(_env_file=None).tool_max_egress_tier is None  # type: ignore[call-arg]


@pytest.mark.unit
@pytest.mark.parametrize("bad", ["0", "6", "x", "-1"])
def test_setting_rejects_out_of_range(monkeypatch, bad: str) -> None:
    monkeypatch.setenv("LQ_AI_TOOL_MAX_EGRESS_TIER", bad)
    with pytest.raises(PydanticValidationError):
        Settings(_env_file=None)  # type: ignore[call-arg]


@pytest.mark.unit
def test_setting_bare_alias_still_binds(monkeypatch) -> None:
    monkeypatch.delenv("LQ_AI_TOOL_MAX_EGRESS_TIER", raising=False)
    monkeypatch.setenv("TOOL_MAX_EGRESS_TIER", "4")
    assert Settings(_env_file=None).tool_max_egress_tier == 4  # type: ignore[call-arg]


# ---------------------------------------------------------------------------
# resolve_tool_egress_ceiling
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_resolve_nothing_set(db_session: AsyncSession, operator_ceiling) -> None:
    assert await resolve_tool_egress_ceiling(db_session, project_id=None) == (None, None)


@pytest.mark.asyncio
async def test_resolve_operator_default_only(db_session: AsyncSession, operator_ceiling) -> None:
    operator_ceiling(2)
    assert await resolve_tool_egress_ceiling(db_session, project_id=None) == (2, "operator")


@pytest.mark.asyncio
async def test_resolve_project_only(db_session: AsyncSession, operator_ceiling) -> None:
    user = await _add_user(db_session)
    project = await _make_project(db_session, user, max_egress_tier=3)
    assert await resolve_tool_egress_ceiling(db_session, project_id=project.id) == (3, "project")


@pytest.mark.asyncio
async def test_resolve_scope_only(db_session: AsyncSession, operator_ceiling) -> None:
    assert await resolve_tool_egress_ceiling(db_session, project_id=None, scope_ceiling=4) == (
        4,
        "execution_scope",
    )


@pytest.mark.asyncio
async def test_resolve_min_wins_and_reports_source(
    db_session: AsyncSession, operator_ceiling
) -> None:
    operator_ceiling(4)
    user = await _add_user(db_session)
    project = await _make_project(db_session, user, max_egress_tier=2)
    # operator=4, project=2, scope=5 -> project is the binding constraint
    assert await resolve_tool_egress_ceiling(
        db_session, project_id=project.id, scope_ceiling=5
    ) == (2, "project")


@pytest.mark.asyncio
async def test_resolve_operator_can_be_binding(db_session: AsyncSession, operator_ceiling) -> None:
    operator_ceiling(1)
    user = await _add_user(db_session)
    project = await _make_project(db_session, user, max_egress_tier=5)
    assert await resolve_tool_egress_ceiling(
        db_session, project_id=project.id, scope_ceiling=5
    ) == (1, "operator")


@pytest.mark.asyncio
async def test_resolve_project_null_means_no_project_ceiling(
    db_session: AsyncSession, operator_ceiling
) -> None:
    operator_ceiling(3)
    user = await _add_user(db_session)
    project = await _make_project(db_session, user, max_egress_tier=None)
    assert await resolve_tool_egress_ceiling(db_session, project_id=project.id) == (3, "operator")


@pytest.mark.asyncio
async def test_resolve_dangling_project_id_is_not_unresolved(
    db_session: AsyncSession, operator_ceiling
) -> None:
    # A non-null project_id with no matching row is "no Project", not a
    # lookup failure — only the operator/scope values apply.
    operator_ceiling(3)
    assert await resolve_tool_egress_ceiling(
        db_session, project_id=uuid.uuid4(), scope_ceiling=4
    ) == (3, "operator")


@pytest.mark.asyncio
async def test_resolve_project_lookup_error_fail_closed(operator_ceiling) -> None:
    broken = AsyncMock()
    broken.scalar.side_effect = RuntimeError("db gone")
    operator_ceiling(2)
    assert await resolve_tool_egress_ceiling(broken, project_id=uuid.uuid4(), scope_ceiling=5) == (
        None,
        "unresolved",
    )


@pytest.mark.asyncio
async def test_resolve_scope_zero_resolves_for_api_refusal(
    db_session: AsyncSession, operator_ceiling
) -> None:
    # Scope 0 ("no egress") must resolve here so the API tier check refuses
    # before dispatch; governed_tool_invocation never forwards 0 to the gateway.
    assert await resolve_tool_egress_ceiling(db_session, project_id=None, scope_ceiling=0) == (
        0,
        "execution_scope",
    )


# ---------------------------------------------------------------------------
# resolve_resumed_ceiling
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_resumed_current_tighter() -> None:
    assert resolve_resumed_ceiling(3, 2, "operator") == (2, "operator")


@pytest.mark.unit
def test_resumed_original_tighter() -> None:
    assert resolve_resumed_ceiling(2, 5, "project") == (2, "pending_original")


@pytest.mark.unit
def test_resumed_tie_keeps_original_source() -> None:
    assert resolve_resumed_ceiling(3, 3, "operator") == (3, "pending_original")


@pytest.mark.unit
def test_resumed_no_original_uses_current() -> None:
    assert resolve_resumed_ceiling(None, 4, "execution_scope") == (4, "execution_scope")


@pytest.mark.unit
def test_resumed_no_current_keeps_original() -> None:
    assert resolve_resumed_ceiling(3, None, None) == (3, "pending_original")


@pytest.mark.unit
def test_resumed_nothing_set() -> None:
    assert resolve_resumed_ceiling(None, None, None) == (None, None)


@pytest.mark.unit
def test_resumed_unresolved_current_fail_closed() -> None:
    assert resolve_resumed_ceiling(3, None, "unresolved") == (None, "unresolved")
    assert resolve_resumed_ceiling(None, None, "unresolved") == (None, "unresolved")


# ---------------------------------------------------------------------------
# governed_tool_invocation — ceiling enforcement + audit columns
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_governed_ceiling_refuses_and_audits(db_session: AsyncSession) -> None:
    dispatch = _make_dispatch()
    outcome = await _governed(
        db_session,
        provider_tier=3,
        max_allowed_tier=2,
        ceiling_source="project",
        dispatch=dispatch,
    )
    assert isinstance(outcome, ToolTierRefused)
    assert outcome.details["ceiling"] == 2
    assert "ceiling is 2" in str(outcome)
    dispatch.assert_not_called()

    rows = (await db_session.execute(select(ToolCallLog))).scalars().all()
    assert len(rows) == 1
    row = rows[0]
    assert row.outcome == "refused_tier"
    assert row.max_allowed_tier == 2
    assert row.ceiling_source == "project"


@pytest.mark.asyncio
async def test_governed_scope_zero_refuses_before_dispatch(db_session: AsyncSession) -> None:
    dispatch = _make_dispatch()
    outcome = await _governed(
        db_session,
        provider_tier=1,
        max_allowed_tier=0,
        ceiling_source="execution_scope",
        dispatch=dispatch,
    )
    assert isinstance(outcome, ToolTierRefused)
    dispatch.assert_not_called()
    rows = (await db_session.execute(select(ToolCallLog))).scalars().all()
    assert rows[0].max_allowed_tier == 0
    assert rows[0].ceiling_source == "execution_scope"


@pytest.mark.asyncio
async def test_governed_unresolved_policy_refuses_closed(db_session: AsyncSession) -> None:
    dispatch = _make_dispatch()
    outcome = await _governed(
        db_session,
        provider_tier=1,
        max_allowed_tier=None,
        ceiling_source="unresolved",
        dispatch=dispatch,
    )
    assert isinstance(outcome, ToolTierRefused)
    assert "could not be read" in str(outcome)
    dispatch.assert_not_called()
    rows = (await db_session.execute(select(ToolCallLog))).scalars().all()
    assert rows[0].outcome == "refused_tier"
    assert rows[0].max_allowed_tier is None
    assert rows[0].ceiling_source == "unresolved"


@pytest.mark.asyncio
async def test_governed_happy_path_records_ceiling(db_session: AsyncSession) -> None:
    dispatch = _make_dispatch()
    row = await _governed(
        db_session,
        provider_tier=2,
        max_allowed_tier=3,
        ceiling_source="operator",
        dispatch=dispatch,
    )
    assert isinstance(row, ToolCallLog)
    assert row.outcome == "executed"
    assert row.max_allowed_tier == 3
    assert row.ceiling_source == "operator"
    dispatch.assert_called_once()


@pytest.mark.asyncio
async def test_governed_unconstrained_row_has_null_ceiling_columns(
    db_session: AsyncSession,
) -> None:
    dispatch = _make_dispatch()
    row = await _governed(
        db_session,
        provider_tier=5,
        max_allowed_tier=None,
        ceiling_source=None,
        dispatch=dispatch,
    )
    assert isinstance(row, ToolCallLog)
    assert row.max_allowed_tier is None
    assert row.ceiling_source is None


# ---------------------------------------------------------------------------
# Project schemas
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_project_create_accepts_valid_ceiling() -> None:
    req = ProjectCreateRequest(name="M", max_egress_tier=3)
    assert req.max_egress_tier == 3


@pytest.mark.unit
def test_project_create_defaults_ceiling_none() -> None:
    assert ProjectCreateRequest(name="M").max_egress_tier is None


@pytest.mark.unit
@pytest.mark.parametrize("bad", [0, 6, -1])
def test_project_create_rejects_out_of_range(bad: int) -> None:
    with pytest.raises(PydanticValidationError):
        ProjectCreateRequest(name="M", max_egress_tier=bad)


@pytest.mark.unit
def test_project_update_accepts_and_clears_ceiling() -> None:
    assert ProjectUpdateRequest(max_egress_tier=1).max_egress_tier == 1
    cleared = ProjectUpdateRequest(max_egress_tier=None)
    assert cleared.max_egress_tier is None
    assert "max_egress_tier" in cleared.model_fields_set


@pytest.mark.unit
@pytest.mark.parametrize("bad", [0, 6])
def test_project_update_rejects_out_of_range(bad: int) -> None:
    with pytest.raises(PydanticValidationError):
        ProjectUpdateRequest(max_egress_tier=bad)


# ---------------------------------------------------------------------------
# DB CHECK constraints
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_project_check_rejects_out_of_range(db_session: AsyncSession) -> None:
    user = await _add_user(db_session)
    db_session.add(
        Project(
            owner_id=user.id,
            name="Bad ceiling",
            slug=f"bad-ceiling-{uuid.uuid4().hex[:8]}",
            max_egress_tier=9,
        )
    )
    with pytest.raises(IntegrityError):
        await db_session.flush()
    await db_session.rollback()


@pytest.mark.asyncio
async def test_tool_call_log_check_rejects_bad_ceiling_source(
    db_session: AsyncSession,
) -> None:
    user = await _add_user(db_session)
    db_session.add(
        ToolCallLog(
            origin="chat",
            provider="p",
            tool="t",
            intent=None,
            tier=1,
            max_allowed_tier=1,
            ceiling_source="bogus",
            outcome="executed",
            user_id=user.id,
        )
    )
    with pytest.raises(IntegrityError):
        await db_session.flush()
    await db_session.rollback()


@pytest.mark.asyncio
async def test_tool_call_log_check_allows_zero_but_rejects_six(
    db_session: AsyncSession,
) -> None:
    """0 is a legal *audited* ceiling (scope "no egress" refusal); 6 is not."""
    user = await _add_user(db_session)
    db_session.add(
        ToolCallLog(
            origin="chat",
            provider="p",
            tool="t",
            tier=1,
            max_allowed_tier=0,
            ceiling_source="execution_scope",
            outcome="refused_tier",
            user_id=user.id,
        )
    )
    await db_session.flush()
    db_session.add(
        ToolCallLog(
            origin="chat",
            provider="p",
            tool="t",
            tier=1,
            max_allowed_tier=6,
            ceiling_source="operator",
            outcome="refused_tier",
            user_id=user.id,
        )
    )
    with pytest.raises(IntegrityError):
        await db_session.flush()
    await db_session.rollback()


@pytest.mark.asyncio
async def test_project_check_rejects_zero(db_session: AsyncSession) -> None:
    """A *configured* project ceiling of 0 is meaningless — 1-5 only."""
    user = await _add_user(db_session)
    db_session.add(
        Project(
            owner_id=user.id,
            name="Zero ceiling",
            slug=f"zero-ceiling-{uuid.uuid4().hex[:8]}",
            max_egress_tier=0,
        )
    )
    with pytest.raises(IntegrityError):
        await db_session.flush()
    await db_session.rollback()


@pytest.mark.asyncio
async def test_project_model_round_trip(db_session: AsyncSession) -> None:
    user = await _add_user(db_session)
    project = await _make_project(db_session, user, max_egress_tier=4)
    fetched = await db_session.get(Project, project.id)
    assert fetched is not None
    assert fetched.max_egress_tier == 4
