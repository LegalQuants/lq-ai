"""Tests for citation/authority.py substrate (WS-E PR1b).

Covers:
- authority_target determinism + _DocumentProtocol duck-type.
- store_authority_text + load_authority_text round-trip.
- load returns None when absent.
- load returns None when the cached row is stale (past AUTHORITY_TEXT_TTL).
- _AuthorityCandidate duck-types _CandidateProtocol; verify() passes stage 1/2.
- encode_external_ref_key/decode_external_ref_key (DE-375): reversible key
  encoding for treaty/corrigendum CELEX refs, identity for safe refs,
  fail-closed on traversal/reserved sequences; store/load round-trip for
  '/' and '()' shapes under the encoded storage key.

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
    _SAFE_KEY_RE,
    AUTHORITY_TEXT_TTL,
    _AuthorityCandidate,
    authority_target,
    decode_external_ref_key,
    encode_external_ref_key,
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


# ---------------------------------------------------------------------------
# Storage-key encoding for treaty/corrigendum external_refs (DE-375)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw",
    [
        "12016E/TXT",  # treaty full text
        "12012P/TXT",  # Charter full text
        "32016R0679R(01)",  # corrigendum
        "12016M/PRO/02",  # multiple slashes stay reversible
        "32016R0679",  # already-safe id (identity)
    ],
)
def test_encode_decode_external_ref_round_trips(raw: str) -> None:
    encoded = encode_external_ref_key(raw)
    assert decode_external_ref_key(encoded) == raw
    # Encoded form always lands in the safe key charset — no '/' survives.
    assert _SAFE_KEY_RE.fullmatch(encoded)
    assert "/" not in encoded


@pytest.mark.parametrize(
    "safe_ref",
    [
        "32016R0679",  # CELEX regulation
        "USCODE-2022-title15",  # GovInfo package id
        "0001193125-15-118890",  # EDGAR accession number
        "CFR-2023-title40",
    ],
)
def test_encode_is_identity_for_safe_refs(safe_ref: str) -> None:
    """Pre-DE-375 cache rows keep their storage keys: encoding must be the
    identity for every ref already inside the safe charset."""
    assert encode_external_ref_key(safe_ref) == safe_ref


@pytest.mark.parametrize(
    "hostile",
    [
        "../../etc/passwd",  # traversal — must never become storable via encoding
        "a..b",  # bare traversal sequence
        "a.SL.b",  # reserved encoding triple — would break reversibility
        "a.OP.b",
        "a.CP.b",
    ],
)
def test_encode_rejects_traversal_and_reserved_sequences(hostile: str) -> None:
    with pytest.raises(ValueError, match="external_ref"):
        encode_external_ref_key(hostile)


@pytest.mark.asyncio
async def test_store_then_load_round_trips_treaty_celex(db_session, fake_storage) -> None:
    """A treaty CELEX ('/' shape, DE-375) stores under the encoded key and
    loads back by its raw external_ref; the object-store key stays inside
    authority/<source_type>/ with no extra path segment."""
    body = "The Union shall be founded on the present Treaty."
    await store_authority_text(
        db_session, source_type="eurlex-prod", external_ref="12016E/TXT", text=body
    )
    assert list(fake_storage) == ["authority/eurlex-prod/12016E.SL.TXT"]
    got = await load_authority_text(
        db_session, source_type="eurlex-prod", external_ref="12016E/TXT"
    )
    assert got == body


@pytest.mark.asyncio
async def test_store_then_load_round_trips_corrigendum_celex(db_session, fake_storage) -> None:
    """A corrigendum CELEX ('()' shape, DE-375) round-trips the same way."""
    body = "Corrigendum to Regulation (EU) 2016/679."
    await store_authority_text(
        db_session, source_type="eurlex-prod", external_ref="32016R0679R(01)", text=body
    )
    assert list(fake_storage) == ["authority/eurlex-prod/32016R0679R.OP.01.CP."]
    got = await load_authority_text(
        db_session, source_type="eurlex-prod", external_ref="32016R0679R(01)"
    )
    assert got == body


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
