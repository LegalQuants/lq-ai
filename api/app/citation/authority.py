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

import logging
import re
import uuid
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.authority_text_cache import AuthorityTextCache
from app.models.message_authority_citation import MessageAuthorityCitation
from app.storage import stream_download, upload_bytes

if TYPE_CHECKING:
    from app.chat.tool_loop import ToolSourceRecord

log = logging.getLogger(__name__)

_LoadAuthorityText = Callable[..., Awaitable[str | None]]

# Stable namespace for authority verify targets.
# MUST be distinct from caselaw's _OPINION_NS ("6f9619ff-8b86-d011-b42d-00cf4fc964ff").
_AUTHORITY_NS = uuid.UUID("fa7a7a7a-4e8b-4b5c-9d0e-1f2a3b4c5d6e")

# Allowlist for object-storage key components.  GovInfo ids are alnum + hyphen
# (e.g. "USCODE-2022-title15", "CFR-2023-title40"); permit dots and underscores
# for other sources that may use them.
_SAFE_KEY_RE = re.compile(r"^[A-Za-z0-9._-]+$")


def _validate_storage_key_component(param_name: str, value: str) -> None:
    """Raise ValueError if ``value`` contains chars that could cause path traversal.

    Accepts only ``[A-Za-z0-9._-]+``.  Caller supplies ``param_name`` for the
    error message so callers can tell source_type from external_ref apart.
    """
    if not _SAFE_KEY_RE.fullmatch(value):
        raise ValueError(
            f"Invalid {param_name} {value!r}: must match [A-Za-z0-9._-]+ "
            "(disallowed character or path-traversal sequence detected)"
        )


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
    _validate_storage_key_component("source_type", source_type)
    _validate_storage_key_component("external_ref", external_ref)

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
        await db.flush()
    else:
        new_row = AuthorityTextCache(
            source_type=source_type,
            external_ref=external_ref,
            storage_path=storage_path,
            char_length=len(text),
            retrieved_at=now,
        )
        try:
            async with db.begin_nested():  # SAVEPOINT around the conflict-prone insert
                db.add(new_row)
                await db.flush()
        except IntegrityError:
            # A concurrent call inserted the same (source_type, external_ref) between
            # our SELECT and our INSERT.  Exiting begin_nested() on the exception has
            # already rolled back to the SAVEPOINT — the session is still usable and
            # new_row has been expelled from the identity map.  Re-read the winning row
            # and update it in place so our fresh text/char_length/retrieved_at wins.
            winner = (
                await db.execute(
                    select(AuthorityTextCache).where(
                        AuthorityTextCache.source_type == source_type,
                        AuthorityTextCache.external_ref == external_ref,
                    )
                )
            ).scalar_one_or_none()
            if winner is not None:
                winner.storage_path = storage_path
                winner.char_length = len(text)
                winner.retrieved_at = now
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
    _validate_storage_key_component("source_type", source_type)
    _validate_storage_key_component("external_ref", external_ref)

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


async def verify_and_persist_authority_citations(
    db: AsyncSession,
    *,
    message_id: uuid.UUID,
    assistant_text: str,
    tool_sources: Sequence[ToolSourceRecord],
    load_authority_text: _LoadAuthorityText = load_authority_text,
    gateway: Any = None,
    judge_model: str = "fast",
) -> int:
    """Char-verify verbatim/paraphrase quotes of fetched authority in a chat
    turn's answer, persisting MessageAuthorityCitation rows.

    Level-2 depth (WS-E PR1c): verbatim + paraphrase, PASS/SUPPORTED,
    drop-on-miss.  Unlike the autonomous ledger_bridge.build_authority_citations,
    chat blockquotes are unattributed, so a quote that matches NO fetched body
    is dropped (no row) rather than FAILed — avoiding false-positives on
    uploaded-document or caselaw blockquotes.  Attributed-authority FAIL is
    DE-370.  Best-effort: per-ref/per-passage exceptions are logged and skipped.
    """
    # Only get_authority-sourced refs carry a cached body; filter to authority
    # content kinds with an external_ref.
    refs = [
        r for r in tool_sources if r.source_kind in {"statute", "regulation"} and r.external_ref
    ]
    if not refs:
        return 0

    # Function-local imports break the authority <-> caselaw <-> tool_loop cycle.
    from app.citation.caselaw import extract_blockquote_passages, locate_passage
    from app.citation.verification import verify

    passages = extract_blockquote_passages(assistant_text)
    if not passages:
        return 0

    # Load each distinct authority body once. Carry external_ref alongside
    # source_type/content_kind so a persisted row records the exact package
    # its quote matched (rather than re-deriving it from tool_sources later).
    targets: list[
        tuple[str, str, str, Any]
    ] = []  # (source_type, external_ref, content_kind, target)
    seen: set[tuple[str, str]] = set()
    for r in refs:
        assert r.external_ref is not None  # guaranteed by the `refs` filter above
        key = (r.provider, r.external_ref)
        if key in seen:
            continue
        seen.add(key)
        try:
            body = await load_authority_text(
                db, source_type=r.provider, external_ref=r.external_ref
            )
        except Exception:
            log.warning(
                "authority verify: body load failed, skipping ref",
                extra={
                    "event": "chat_authority_verify_load_failed",
                    "external_ref": r.external_ref,
                },
                exc_info=True,
            )
            continue
        if not body:
            continue
        targets.append(
            (
                r.provider,
                r.external_ref,
                r.source_kind,
                authority_target(r.provider, r.external_ref, body),
            )
        )

    if not targets:
        return 0

    rows: list[MessageAuthorityCitation] = []
    verbatim_matched: set[str] = set()
    for passage in passages:
        for source_type, external_ref, content_kind, target in targets:
            try:
                off = locate_passage(passage, target.normalized_content)
            except Exception:
                continue
            if off is None:
                continue
            start, end = off
            cand = _AuthorityCandidate(
                source_offset_start=start,
                source_offset_end=end,
                source_text=passage,
                source_document_id=target.id,
            )
            try:
                # gateway=None: verbatim-only here. locate_passage is a
                # byte-exact substring finder — verify()'s judge stage is
                # structurally unreachable in this loop (a miss `continue`s
                # before a candidate exists), so passing gateway through
                # would be dishonest. Mirrors caselaw.py's verbatim pass.
                result = await verify(cand, target, gateway=None, judge_model=judge_model)
            except Exception:
                log.warning(
                    "authority verify: verify() failed, skipping passage",
                    extra={"event": "chat_authority_verify_failed"},
                    exc_info=True,
                )
                continue
            if not result.verified:
                # drop-on-miss: not verified against this body — try the next.
                continue
            rows.append(
                MessageAuthorityCitation(
                    message_id=message_id,
                    source_type=source_type,
                    external_ref=external_ref,
                    content_kind=content_kind,
                    source_offset_start=start,
                    source_offset_end=end,
                    source_text=passage,
                    verified=True,
                    verification_method=result.method,
                    verification_confidence=result.confidence,
                    partial=result.partial,
                )
            )
            verbatim_matched.add(passage)
            break  # first matching authority wins

    # --- Pass B: whole-body paraphrase judge (SUPPORTED tier) --------------
    # Passages that missed verbatim matching in every fetched body are
    # judged against each body in full, budget-bounded. Mirrors caselaw.py's
    # "Unattributed: B1b all-opinions SUPPORTED-or-drop" loop.
    if gateway is not None:
        from app.citation.authority_content_judge import (
            AUTHORITY_CONTENT_JUDGE_BUDGET_USD,
            estimate_authority_content_cost_usd,
            judge_authority_content,
        )

        spent: Decimal = Decimal("0")
        for passage in passages:
            if passage in verbatim_matched:
                continue
            for source_type, external_ref, content_kind, target in targets:
                body = target.normalized_content
                est = await estimate_authority_content_cost_usd(
                    db, judge_model=judge_model, authority_text=body
                )
                if spent + est > AUTHORITY_CONTENT_JUDGE_BUDGET_USD:
                    break  # budget reached -> drop remaining judge work
                spent += est
                try:
                    result = await judge_authority_content(
                        passage=passage,
                        authority_text=body,
                        gateway=gateway,
                        judge_model=judge_model,
                    )
                except Exception:
                    log.warning(
                        "authority content judge error, skipping",
                        extra={
                            "event": "chat_authority_judge_error",
                            "external_ref": external_ref,
                        },
                        exc_info=True,
                    )
                    continue
                if not result.verified:
                    continue
                rows.append(
                    MessageAuthorityCitation(
                        message_id=message_id,
                        source_type=source_type,
                        external_ref=external_ref,
                        content_kind=content_kind,
                        source_offset_start=0,
                        source_offset_end=len(body),
                        source_text=passage,
                        verified=True,
                        verification_method="paraphrase_judge",
                        verification_confidence=result.confidence,
                        partial=True,
                    )
                )
                break  # first supporting body wins for this passage

    if rows:
        db.add_all(rows)
        await db.flush()
    return len(rows)
