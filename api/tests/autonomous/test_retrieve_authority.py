"""Tests for ToolIntent.retrieve_authority — WS-E PR1a.

Governed dispatch of GovInfo authority retrieval through the gateway egress.

Adaptation from brief
---------------------
The brief calls for writing a ``MessageToolSource`` provenance row in the
handler.  In the autonomous context there is no ``message_id`` — the model
requires ``message_id NOT NULL FK → messages.id`` and no migration exists
to relax that constraint (and "NO migration" is a PR1a constraint).  The
retrieve_caselaw handler (the closest existing analog) also does NOT write a
MessageToolSource row in the autonomous context.

Adaptation: provenance is captured in two durable artifacts that ARE
available:

1. ``ToolResult.data["authority"]`` — text, external_ref, label, url,
   content_kind returned to the caller.
2. The ``tool_call_log`` row written by ``governed_tool_invocation`` —
   provider, tool, intent, tier, outcome.

No MessageToolSource row assertion is made; tests verify (1) and (2).

Coverage
--------
(a) Happy path — retrieve_authority in analysis: tool_call_log row written
    (provider=govinfo-prod, tool=get_authority, intent=retrieve_authority),
    ToolResult carries fetched text + external_ref + content_kind.
(b) Unknown/disabled source → ValueError, no tool_call_log row (ValueError
    fires inside _resolve_external_call, before governed_tool_invocation).
(c) Phase grant — retrieve_authority is granted ONLY in analysis; R6
    ToolNotGranted in all other phases; no tool_call_log row on refusal.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.autonomous.enums import Phase, ToolIntent
from app.errors import ToolNotGranted
from app.models.autonomous import AutonomousSession
from app.models.tool_call_log import ToolCallLog
from app.models.user import User
from app.security import hash_password

pytestmark = pytest.mark.integration

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_GOVINFO_PROVIDER_NAME = "govinfo-prod"

# GovInfo get_authority payload (as the gateway returns it)
_GET_AUTHORITY_PAYLOAD: dict[str, str] = {
    "package_id": "USCODE-2023-title15",
    "title": "Commerce and Trade",
    "citation": "15 U.S.C.",
    "url": "https://api.govinfo.gov/packages/USCODE-2023-title15",
    "text": "This title governs commerce and trade regulations.",
}


class _GovInfoGateway:
    """Scripted gateway double for retrieve_authority tests.

    Supports two operations the handler uses:
    - ``list_tool_providers()`` — returns the govinfo provider config, making
      ``resolve_available_sources`` see govinfo as enabled.
    - ``call_tool(provider, op, args)`` — returns the scripted GovInfo
      ``get_authority`` payload.
    """

    def __init__(self, provider_name: str = _GOVINFO_PROVIDER_NAME) -> None:
        self._provider_name = provider_name
        self.list_tool_providers: AsyncMock = AsyncMock(
            return_value=[{"name": provider_name, "type": "govinfo", "egress_tier": 2}]
        )
        self.call_tool: AsyncMock = AsyncMock(return_value=_GET_AUTHORITY_PAYLOAD)


async def _make_user(db: AsyncSession) -> User:
    user = User(
        email=f"u-authority-{uuid.uuid4().hex[:8]}@example.com",
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


async def _tool_call_rows(db: AsyncSession, session_id: uuid.UUID) -> list[ToolCallLog]:
    return list(
        (await db.execute(select(ToolCallLog).where(ToolCallLog.session_id == session_id)))
        .scalars()
        .all()
    )


# ---------------------------------------------------------------------------
# (a) Happy path — executes and writes tool_call_log row
# ---------------------------------------------------------------------------


async def test_retrieve_authority_executes_and_writes_tool_call_log(
    db_session: AsyncSession,
) -> None:
    """retrieve_authority in analysis executes via governed dispatch.

    Asserts:
    - One tool_call_log row: origin=autonomous, provider=govinfo-prod,
      tool=get_authority, intent=retrieve_authority, outcome=executed,
      cost_usd=$0.
    - ToolResult.data["authority"] carries text + external_ref + content_kind
      (statute, from USCODE package_id) + label + url.

    Adaptation: no MessageToolSource row (no message_id in autonomous context;
    MessageToolSource.message_id is NOT NULL FK → messages.id; no migration in
    PR1a). Provenance is in ToolResult.data and the tool_call_log row.
    """
    from app.autonomous import guard as guard_mod

    user = await _make_user(db_session)
    sess = await _make_session(db_session, user=user, current_phase="analysis")
    gateway = _GovInfoGateway()

    with patch(
        "app.tools.governance.resolve_provider_tier",
        new=AsyncMock(return_value=2),
    ):
        result = await guard_mod.guarded_tool_call(
            sess,
            ToolIntent.retrieve_authority,
            {
                "source": "govinfo",
                "op": "get_authority",
                "args": {"package_id": "USCODE-2023-title15"},
            },
            db_session,
            gateway,
        )

    # ── tool_call_log row ────────────────────────────────────────────────────
    rows = await _tool_call_rows(db_session, sess.id)
    assert len(rows) == 1
    row = rows[0]
    assert row.origin == "autonomous"
    assert row.provider == _GOVINFO_PROVIDER_NAME
    assert row.tool == "get_authority"
    assert row.intent == "retrieve_authority"
    assert row.outcome == "executed"
    assert row.cost_usd == Decimal("0")
    # args_digest is counts/types only — never raw args
    assert row.args_digest is not None

    # ── ToolResult carries the authority data ────────────────────────────────
    assert result.cost_usd == Decimal("0")
    assert result.data is not None
    authority = result.data["authority"]
    assert authority["text"] == _GET_AUTHORITY_PAYLOAD["text"]
    assert authority["external_ref"] == "USCODE-2023-title15"
    assert authority["content_kind"] == "statute"  # USCODE → statute (GovInfoAdapter)
    assert authority["label"] == "15 U.S.C."
    assert authority["url"] == _GET_AUTHORITY_PAYLOAD["url"]

    # ── gateway was called exactly once ──────────────────────────────────────
    gateway.call_tool.assert_awaited_once()


# ---------------------------------------------------------------------------
# (b) Unknown / disabled source → ValueError, non-fatal, no provenance row
# ---------------------------------------------------------------------------


async def test_retrieve_authority_disabled_source_raises_clean_ValueError(
    db_session: AsyncSession,
) -> None:
    """A disabled/unknown source raises ValueError before any provenance write.

    The ValueError fires in _resolve_external_call before governed_tool_invocation
    is entered, so no tool_call_log row is written.  The session is left
    unharmed (halt_state unchanged, no DBAPIError / crash).

    Invariant: validation-before-side-effect ordering guarantees the session is
    never poisoned by a bad model-supplied source argument.
    """
    from app.autonomous import guard as guard_mod

    user = await _make_user(db_session)
    sess = await _make_session(db_session, user=user, current_phase="analysis")

    # Gateway has no govinfo provider configured → govinfo AvailableSource.enabled=False
    gw = MagicMock()
    gw.list_tool_providers = AsyncMock(return_value=[])

    with pytest.raises(ValueError):
        await guard_mod.guarded_tool_call(
            sess,
            ToolIntent.retrieve_authority,
            {"source": "govinfo", "op": "get_authority", "args": {}},
            db_session,
            gw,
        )

    # Session is accessible and not poisoned
    await db_session.refresh(sess)
    assert sess.halt_state == "running"

    # No tool_call_log row (ValueError fires before governed_tool_invocation)
    rows = await _tool_call_rows(db_session, sess.id)
    assert len(rows) == 0


async def test_retrieve_authority_unknown_source_type_raises_ValueError(
    db_session: AsyncSession,
) -> None:
    """A source type not in SOURCE_REGISTRY raises ValueError (non-fatal).

    'ghost-source' is not in SOURCE_REGISTRY → resolve_available_sources
    never produces a matching AvailableSource for it → ValueError in
    _resolve_external_call; no tool_call_log row; session unharmed.
    """
    from app.autonomous import guard as guard_mod

    user = await _make_user(db_session)
    sess = await _make_session(db_session, user=user, current_phase="analysis")
    gateway = _GovInfoGateway()  # govinfo enabled, but source="ghost-source"

    with pytest.raises(ValueError):
        await guard_mod.guarded_tool_call(
            sess,
            ToolIntent.retrieve_authority,
            {"source": "ghost-source", "op": "get_authority", "args": {}},
            db_session,
            gateway,
        )

    await db_session.refresh(sess)
    assert sess.halt_state == "running"
    assert len(await _tool_call_rows(db_session, sess.id)) == 0


# ---------------------------------------------------------------------------
# (c) Phase grant — retrieve_authority only in analysis
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "phase",
    [p.value for p in Phase if p is not Phase.analysis],
)
async def test_retrieve_authority_refused_outside_analysis(
    db_session: AsyncSession,
    phase: str,
) -> None:
    """retrieve_authority is granted only in analysis; R6 ToolNotGranted elsewhere.

    R6 fires before dispatch, so no tool_call_log row is written on refusal.
    """
    from app.autonomous import guard as guard_mod

    user = await _make_user(db_session)
    sess = await _make_session(db_session, user=user, current_phase=phase)
    gateway = _GovInfoGateway()

    with pytest.raises(ToolNotGranted) as exc_info:
        await guard_mod.guarded_tool_call(
            sess,
            ToolIntent.retrieve_authority,
            {"source": "govinfo", "op": "get_authority", "args": {}},
            db_session,
            gateway,
        )

    assert exc_info.value.details["intent"] == "retrieve_authority"

    # R6 fires before dispatch → no tool_call_log row
    assert await _tool_call_rows(db_session, sess.id) == []
