"""Tests for citation/authority.py substrate (WS-E PR1b).

Covers:
- authority_target determinism + _DocumentProtocol duck-type.
- store_authority_text + load_authority_text round-trip.
- load returns None when absent.
- load returns None when the cached row is stale (past AUTHORITY_TEXT_TTL).
- _AuthorityCandidate duck-types _CandidateProtocol; verify() passes stage 1/2.

Object-storage is backed by the same in-memory fake fixture pattern used in
tests/test_research_service.py, patching upload_bytes/stream_download at the
app.citation.authority import point.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import pytest

from app.citation.authority import (
    AUTHORITY_TEXT_TTL,
    _AuthorityCandidate,
    authority_target,
    load_authority_text,
    store_authority_text,
)
from app.citation.caselaw import locate_passage
from app.citation.verification import verify

# ---------------------------------------------------------------------------
# Object-storage fake (mirrors fake_storage from test_research_service.py,
# but patches the authority module's import points).
# ---------------------------------------------------------------------------


@pytest.fixture
def fake_storage(monkeypatch: pytest.MonkeyPatch) -> dict[str, bytes]:
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
# Tests
# ---------------------------------------------------------------------------


def test_authority_target_is_deterministic_and_duck_types_document() -> None:
    t1 = authority_target("govinfo", "USCODE-2022-title15", "Every contract ... illegal.")
    t2 = authority_target("govinfo", "USCODE-2022-title15", "Every contract ... illegal.")
    assert t1.id == t2.id and isinstance(t1.id, uuid.UUID)
    assert t1.normalized_content and t1.was_ocrd is False


@pytest.mark.asyncio
async def test_store_then_load_round_trips(db_session, fake_storage) -> None:
    body = "Every contract, combination ... in restraint of trade ... is declared to be illegal."
    await store_authority_text(
        db_session, source_type="govinfo", external_ref="USCODE-2022-title15", text=body
    )
    got = await load_authority_text(
        db_session, source_type="govinfo", external_ref="USCODE-2022-title15"
    )
    assert got == body


@pytest.mark.asyncio
async def test_load_returns_none_when_absent(db_session, fake_storage) -> None:
    assert (
        await load_authority_text(db_session, source_type="govinfo", external_ref="missing") is None
    )


@pytest.mark.asyncio
async def test_load_returns_none_when_stale(db_session, fake_storage) -> None:
    await store_authority_text(
        db_session, source_type="govinfo", external_ref="USCODE-old", text="old body"
    )
    # Age the cached row past the TTL via a bulk UPDATE (bypasses ORM identity map).
    from sqlalchemy import update

    from app.models.authority_text_cache import AuthorityTextCache

    stale = datetime.now(UTC) - AUTHORITY_TEXT_TTL - timedelta(days=1)
    await db_session.execute(
        update(AuthorityTextCache)
        .where(AuthorityTextCache.external_ref == "USCODE-old")
        .values(retrieved_at=stale)
    )
    await db_session.flush()
    # Session identity map may hold the old object — expire it so the next
    # select re-fetches from the DB and sees the stale retrieved_at.
    db_session.expire_all()
    assert (
        await load_authority_text(db_session, source_type="govinfo", external_ref="USCODE-old")
        is None
    )


@pytest.mark.asyncio
async def test_store_rejects_path_traversal_external_ref(db_session, fake_storage) -> None:
    """Malicious external_ref containing path-traversal chars raises ValueError.

    The resulting storage key must never start with anything outside
    'authority/<source_type>/' — validated by confirming the exception fires
    before any upload attempt.
    """
    with pytest.raises(ValueError, match="external_ref"):
        await store_authority_text(
            db_session,
            source_type="govinfo",
            external_ref="../../etc/passwd",
            text="malicious",
        )


@pytest.mark.asyncio
async def test_store_rejects_path_traversal_source_type(db_session, fake_storage) -> None:
    """Malicious source_type also raises ValueError (load path consistent)."""
    with pytest.raises(ValueError, match="source_type"):
        await store_authority_text(
            db_session,
            source_type="gov/../../etc",
            external_ref="USCODE-2022-title15",
            text="malicious",
        )


@pytest.mark.asyncio
async def test_store_second_call_updates_not_raises(db_session, fake_storage) -> None:
    """A second store for the same key updates the row, not raises IntegrityError.

    Simulates the concurrent-insert scenario by pre-inserting a row (first store)
    and then calling store again — asserts idempotent update rather than exception.
    """
    body1 = "Original statutory text"
    body2 = "Refreshed statutory text"
    await store_authority_text(
        db_session, source_type="govinfo", external_ref="USCODE-dup", text=body1
    )
    # Second call must update, not raise.
    await store_authority_text(
        db_session, source_type="govinfo", external_ref="USCODE-dup", text=body2
    )
    got = await load_authority_text(db_session, source_type="govinfo", external_ref="USCODE-dup")
    assert got == body2


@pytest.mark.asyncio
async def test_verify_exact_match_against_authority_target(db_session, fake_storage) -> None:
    body = "Every contract ... in restraint of trade ... is declared to be illegal."
    target = authority_target("govinfo", "USCODE-2022-title15", body)
    quote = "in restraint of trade"
    off = locate_passage(quote, target.normalized_content)
    assert off is not None
    cand = _AuthorityCandidate(
        source_offset_start=off[0],
        source_offset_end=off[1],
        source_text=quote,
        source_document_id=target.id,
    )
    result = await verify(cand, target, gateway=None)
    assert result.verified and result.method in {"exact_match", "tolerant_match"}
