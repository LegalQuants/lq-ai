"""Tests for autonomous authority-fetch → cache write + source threading (WS-E PR1b, Task 4).

Covers:
- After a successful retrieve_authority call, an AuthorityTextCache row exists
  for (source_type, external_ref) with char_length > 0.
- ToolResult.data["authority"]["source"] == params["source"] (the registry name).
- EvidenceItem collected from a retrieve_authority result carries .source AND
  .content_kind (loop-local; P3 unaffected — not persisted).

Reuses the _GovInfoGateway scripted double + _make_user/_make_session helpers
from test_retrieve_authority.py (PR1a).

Object storage is backed by the in-memory fake fixture from
test_authority_substrate.py, patching upload_bytes/stream_download at the
app.citation.authority import point.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from decimal import Decimal
from unittest.mock import AsyncMock, patch

import pytest
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
def _reset_cost_cache() -> None:
    """Reset the process-level provider tier+cost cache before/after each test."""
    from app.tools.governance import _reset_provider_tier_cache_for_tests

    _reset_provider_tier_cache_for_tests()
    yield  # type: ignore[misc]
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
