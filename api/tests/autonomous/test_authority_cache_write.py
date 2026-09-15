"""Tests for autonomous authority-fetch → cache write + source threading (WS-E PR1b, Task 4).

Covers:
- After a successful retrieve_authority call, an AuthorityTextCache row exists
  for (source_type, external_ref) with char_length > 0.
- ToolResult.data["authority"]["source"] == params["source"] (the registry name).
- EvidenceItem collected from a retrieve_authority result carries .source AND
  .content_kind (loop-local; P3 unaffected — not persisted).
- CRITICAL (Task 4 fix): when the cache write raises a real DB-level error
  mid-transaction, the outer begin_nested savepoint rolls back cleanly and the
  AsyncSession remains usable for subsequent DB ops in the same turn (the
  WS-D PR1-C1 poisoned-session class, one level out).

Reuses the _GovInfoGateway scripted double + _make_user/_make_session helpers
from test_retrieve_authority.py (PR1a).

Object storage is backed by the in-memory fake fixture from
test_authority_substrate.py, patching upload_bytes/stream_download at the
app.citation.authority import point.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from decimal import Decimal
from unittest.mock import AsyncMock, patch

import pytest
import sqlalchemy as sa
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.autonomous.enums import ToolIntent
from app.autonomous.guard import ToolResult
from app.models.authority_text_cache import AuthorityTextCache

# Reuse the scripted gateway double + session helpers from PR1a tests.
from tests.autonomous.test_retrieve_authority import (
    _GovInfoGateway,
    _make_session,
    _make_user,
)

pytestmark = pytest.mark.integration

# ---------------------------------------------------------------------------
# Cache isolation (mirrors test_retrieve_authority.py)
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_cost_cache() -> Iterator[None]:
    """Reset the process-level provider tier+cost cache before/after each test."""
    from app.tools.governance import _reset_provider_tier_cache_for_tests

    _reset_provider_tier_cache_for_tests()
    yield
    _reset_provider_tier_cache_for_tests()


# ---------------------------------------------------------------------------
# Object-storage fake (mirrors fake_storage from test_authority_substrate.py,
# patching the authority module's import points).
# ---------------------------------------------------------------------------


@pytest.fixture
def fake_storage(monkeypatch: pytest.MonkeyPatch) -> dict[str, bytes]:
    """In-memory object-store double so store_authority_text.upload_bytes succeeds."""
    store: dict[str, bytes] = {}

    async def _upload(*, storage_path: str, body: bytes, content_type: str) -> None:
        store[storage_path] = body

    class _Reader:
        def __init__(self, data: bytes) -> None:
            self._data = data

        async def __aenter__(self) -> AsyncIterator[bytes]:
            data = self._data

            async def _gen() -> AsyncIterator[bytes]:
                yield data

            return _gen()

        async def __aexit__(self, *a: object) -> bool:
            return False

    def _download(*, storage_path: str) -> _Reader:
        return _Reader(store[storage_path])

    monkeypatch.setattr("app.citation.authority.upload_bytes", _upload)
    monkeypatch.setattr("app.citation.authority.stream_download", _download)
    return store


# ---------------------------------------------------------------------------
# Test 1: cache write + source key in ToolResult
# ---------------------------------------------------------------------------


async def test_retrieve_authority_writes_cache_and_source(
    db_session: AsyncSession,
    fake_storage: dict[str, bytes],
) -> None:
    """After retrieve_authority, an AuthorityTextCache row exists + source is threaded.

    Asserts:
    - ToolResult.data["authority"]["source"] == "govinfo" (registry source name).
    - An AuthorityTextCache row exists with source_type="govinfo",
      external_ref="USCODE-2023-title15", char_length > 0.
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

    # ── source key threaded onto the authority dict ──────────────────────────
    assert result.data is not None
    assert result.data["authority"]["source"] == "govinfo"

    # ── cache row written ────────────────────────────────────────────────────
    cached = (
        await db_session.execute(
            select(AuthorityTextCache).where(
                AuthorityTextCache.external_ref == "USCODE-2023-title15"
            )
        )
    ).scalar_one()
    assert cached.source_type == "govinfo"
    assert cached.char_length > 0


# ---------------------------------------------------------------------------
# Test 2: EvidenceItem carries source + content_kind after collect_evidence
# ---------------------------------------------------------------------------


def test_collect_evidence_authority_carries_source_and_content_kind() -> None:
    """collect_evidence for retrieve_authority threads source + content_kind onto EvidenceItem.

    Loop-local only — P3 unaffected (EvidenceItem is never persisted to audit).
    """
    from app.autonomous.planner import collect_evidence

    res = ToolResult(
        cost_usd=Decimal("0"),
        data={
            "authority": {
                "text": "Every contract ... in restraint of trade ... is illegal.",
                "external_ref": "USCODE-2022-title15",
                "label": "15 U.S.C. § 1",
                "url": "https://api.govinfo.gov/packages/USCODE-2022-title15",
                "content_kind": "statute",
                "source": "govinfo",
            }
        },
    )
    items = collect_evidence(ToolIntent.retrieve_authority, res, start_n=1)
    assert len(items) == 1
    item = items[0]
    assert item.kind == "authority"
    assert item.ref == "USCODE-2022-title15"
    # PR1b additions — source + content_kind must be threaded onto EvidenceItem
    assert item.source == "govinfo"
    assert item.content_kind == "statute"


# ---------------------------------------------------------------------------
# Test 3: DB-level error in cache write must NOT poison the session (Task 4 fix)
# ---------------------------------------------------------------------------


async def test_cache_write_db_error_does_not_poison_session(
    db_session: AsyncSession,
    fake_storage: dict[str, bytes],
) -> None:
    """A real DB-level error inside the cache write leaves the session usable.

    This is the proving test for the Task 4 Critical fix: the guard wraps
    store_authority_text in ``async with db.begin_nested():`` so that any
    PostgreSQL-level error (e.g. a division-by-zero that aborts the Postgres
    backend transaction) is contained in the savepoint and rolled back cleanly,
    without leaving the AsyncSession in InFailedSQLTransaction state.

    Approach:
    - Monkeypatch ``app.citation.authority.store_authority_text`` with a stub
      that executes a genuine Postgres error (SELECT 1/0) via the real
      AsyncSession, faithfully exercising the begin_nested rollback path.
    - Assert guarded_tool_call STILL returns a ToolResult with
      data["authority"] (the fetch itself was not aborted).
    - Assert a follow-up DB op (SELECT 1) SUCCEEDS on the same session —
      session NOT poisoned.
    - Assert NO AuthorityTextCache row was committed for the test ref
      (the savepoint rolled back the cache write).
    """
    from app.autonomous import guard as guard_mod

    _TEST_EXTERNAL_REF = "USCODE-2023-title15-poison-test"

    async def _failing_store(
        db: AsyncSession,
        *,
        source_type: str,
        external_ref: str,
        text: str,
    ) -> None:
        # Execute a real Postgres-level error inside the (soon-to-be) savepoint.
        # asyncpg raises asyncpg.exceptions.DivisionByZeroError which propagates
        # as sqlalchemy.exc.DBAPIError, aborting the server-side transaction.
        # The begin_nested wrapper in guard.py must catch this via its savepoint.
        await db.execute(sa.text("SELECT 1/0"))

    user = await _make_user(db_session)
    sess = await _make_session(db_session, user=user, current_phase="analysis")
    gateway = _GovInfoGateway()

    with (
        patch(
            "app.tools.governance.resolve_provider_tier",
            new=AsyncMock(return_value=2),
        ),
        patch(
            "app.citation.authority.store_authority_text",
            new=_failing_store,
        ),
    ):
        result = await guard_mod.guarded_tool_call(
            sess,
            ToolIntent.retrieve_authority,
            {
                "source": "govinfo",
                "op": "get_authority",
                "args": {"package_id": _TEST_EXTERNAL_REF},
            },
            db_session,
            gateway,
        )

    # ── 1. fetch result was NOT aborted ─────────────────────────────────────
    assert result.data is not None, "guarded_tool_call must return a ToolResult on cache failure"
    assert "authority" in result.data, "data['authority'] must be present despite cache error"

    # ── 2. session is NOT poisoned: a follow-up DB op must succeed ──────────
    follow_up = await db_session.execute(sa.text("SELECT 1"))
    val = follow_up.scalar_one()
    assert val == 1, "db_session must be usable after a cache write DB error"

    # ── 3. no AuthorityTextCache row was committed for this ref ─────────────
    cached = (
        await db_session.execute(
            select(AuthorityTextCache).where(AuthorityTextCache.external_ref == _TEST_EXTERNAL_REF)
        )
    ).scalar_one_or_none()
    assert cached is None, "cache row must NOT be committed when the cache write fails"
