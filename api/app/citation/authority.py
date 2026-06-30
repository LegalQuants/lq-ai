"""Authority verify target + durable text cache (WS-E PR1b).

Provides:
- ``authority_target`` — builds an in-memory verification target that
  duck-types ``_DocumentProtocol`` for use with the shared
  :func:`app.citation.verification.verify` cascade.
- ``_AuthorityCandidate`` — a located quote span that duck-types
  ``_CandidateProtocol``.
- ``store_authority_text`` / ``load_authority_text`` — write/read the
  authority source body through object storage, with a 30-day TTL
  backed by the ``authority_text_cache`` table.

Mirrors the caselaw target/candidate pattern in
:mod:`app.citation.caselaw` but uses a (source_type, external_ref)
key instead of a CourtListener opinion_id.

Object storage follows the same pattern as
:mod:`app.research.service`: raw bytes in object store, metadata
(storage_path, char_length, retrieved_at) in the DB table.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.authority_text_cache import AuthorityTextCache
from app.storage import stream_download, upload_bytes

# Stable namespace for authority verify targets.
# MUST be distinct from caselaw's _OPINION_NS ("6f9619ff-8b86-d011-b42d-00cf4fc964ff").
_AUTHORITY_NS = uuid.UUID("fa7a7a7a-4e8b-4b5c-9d0e-1f2a3b4c5d6e")

# TTL for cached authority source text: 30 days.
AUTHORITY_TEXT_TTL = timedelta(days=30)


@dataclass(slots=True)
class _AuthorityVerificationTarget:
    """Adapts a fetched authority source to the verifier's _DocumentProtocol.

    Duck-types :class:`app.citation.verification._DocumentProtocol`:
    fields ``id``, ``normalized_content``, ``was_ocrd`` are all present.
    """

    id: uuid.UUID
    normalized_content: str
    was_ocrd: bool = False


@dataclass(slots=True)
class _AuthorityCandidate:
    """A located quote span shaped for the verifier's _CandidateProtocol.

    Duck-types :class:`app.citation.verification._CandidateProtocol`:
    fields ``source_offset_start``, ``source_offset_end``,
    ``source_text``, ``source_document_id`` are all present.
    """

    source_offset_start: int
    source_offset_end: int
    source_text: str
    source_document_id: uuid.UUID


def authority_target(
    source_type: str, external_ref: str, text: str
) -> _AuthorityVerificationTarget:
    """Build a deterministic verification target for a fetched authority source.

    The ``id`` is a stable UUID5 derived from ``(source_type, external_ref)``
    so the same authority always maps to the same synthetic document id —
    the same guarantee caselaw's ``opinion_target`` gives for opinion_id.

    ``normalized_content`` receives ``text`` verbatim (raw plaintext from the
    authority source), mirroring ``opinion_target``'s choice: the
    :func:`app.citation.normalization.normalize` call happens inside
    :func:`app.citation.verification.verify_tolerant_match` at comparison
    time, not at target-construction time.  Storing raw text here means
    ``load_authority_text`` can return the body and feed it directly to
    ``authority_target`` for verification.
    """
    return _AuthorityVerificationTarget(
        id=uuid.uuid5(_AUTHORITY_NS, f"{source_type}:{external_ref}"),
        normalized_content=text,
        was_ocrd=False,
    )


async def store_authority_text(
    db: AsyncSession,
    *,
    source_type: str,
    external_ref: str,
    text: str,
) -> None:
    """Persist an authority source body to object storage and upsert the cache row.

    Idempotent: a second call for the same (source_type, external_ref) pair
    updates ``storage_path``, ``char_length``, and ``retrieved_at`` in place.

    The body is stored raw (not normalized) so that ``load_authority_text``
    can return it verbatim for use with ``authority_target``; the verifier
    normalizes the content internally when needed.
    """
    storage_path = f"authority/{source_type}/{external_ref}"
    await upload_bytes(
        storage_path=storage_path,
        body=text.encode("utf-8"),
        content_type="text/plain; charset=utf-8",
    )
    now = datetime.now(UTC)
    existing = (
        await db.execute(
            select(AuthorityTextCache).where(
                AuthorityTextCache.source_type == source_type,
                AuthorityTextCache.external_ref == external_ref,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        existing.storage_path = storage_path
        existing.char_length = len(text)
        existing.retrieved_at = now
    else:
        db.add(
            AuthorityTextCache(
                source_type=source_type,
                external_ref=external_ref,
                storage_path=storage_path,
                char_length=len(text),
                retrieved_at=now,
            )
        )
    await db.flush()


async def load_authority_text(
    db: AsyncSession,
    *,
    source_type: str,
    external_ref: str,
) -> str | None:
    """Return the cached authority source body, or None if absent or stale.

    Stale is defined as ``retrieved_at < now - AUTHORITY_TEXT_TTL`` (30 days).
    A stale row remains in the DB; the caller is expected to re-fetch and
    call ``store_authority_text`` again to refresh it.

    Reads the body from object storage via the same ``stream_download``
    helper that :mod:`app.research.service` uses for opinion bodies.
    """
    row = (
        await db.execute(
            select(AuthorityTextCache).where(
                AuthorityTextCache.source_type == source_type,
                AuthorityTextCache.external_ref == external_ref,
            )
        )
    ).scalar_one_or_none()
    if row is None:
        return None

    retrieved_at: datetime = row.retrieved_at
    # The column is TIMESTAMPTZ so asyncpg returns timezone-aware datetimes;
    # guard against naive timestamps returned by other test backends.
    if retrieved_at.tzinfo is None:
        retrieved_at = retrieved_at.replace(tzinfo=UTC)

    if retrieved_at < datetime.now(UTC) - AUTHORITY_TEXT_TTL:
        return None

    chunks: list[bytes] = []
    async with stream_download(storage_path=row.storage_path) as stream:
        async for chunk in stream:
            chunks.append(chunk)
    return b"".join(chunks).decode("utf-8")
