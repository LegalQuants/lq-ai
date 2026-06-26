"""Caselaw quote verification (P1-A1, P1-B1b).

Extracts blockquote passages from an assistant answer, locates each verbatim in
a consulted CourtListener opinion's stored plaintext, runs the existing citation
cascade (deterministic stages 1-2), and persists verified rows.

P1-B1b adds a SUPPORTED judge pass: passages that did not match verbatim are
judged against the whole opinion text (cost-gated). A judge-accepted passage
persists a paraphrase_judge row (gate -> supported_only). Additive-only: no
FAIL/unverified rows are ever written here.

See docs/superpowers/specs/2026-06-24-p1a1-external-caselaw-quote-verification-design.md.
"""

from __future__ import annotations

import logging
import re
import uuid
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.chat.tool_loop import ToolSourceRecord
from app.citation.case_content_judge import (
    CASE_CONTENT_JUDGE_BUDGET_USD,
    estimate_case_content_cost_usd,
    judge_case_content,
)
from app.citation.verification import _JudgeGatewayProtocol, verify
from app.models.message_caselaw_citation import MessageCaselawCitation
from app.models.research import ResearchOpinionMetadata
from app.research.service import read_opinion


@dataclass(slots=True)
class AttributedPassage:
    """A blockquote passage paired with the case name of its nearest ``### `` heading.

    ``case_name`` is the text of the most recent ``### `` heading above the
    blockquote, taken up to the first comma (the case-law-research skill renders
    headings as ``### [Case Name], [Court], [Year] ([Citation])``). ``None`` when
    no ``### `` heading precedes the blockquote — the attribution false-positive
    guard: an unattributed passage never produces a FAIL row.
    """

    passage: str
    case_name: str | None


def attribute_passages(answer_text: str) -> list[AttributedPassage]:
    """Return each markdown blockquote paired with its nearest ``### `` case heading.

    Consecutive blockquote lines (``> ...``) join into one passage; a
    non-blockquote line ends the current passage. Each closed passage is paired
    with the case name parsed from the most recent ``### `` heading seen so far.
    """
    result: list[AttributedPassage] = []
    current: list[str] = []
    current_case: str | None = None

    def _flush() -> None:
        nonlocal current
        joined = " ".join(p for p in current if p).strip()
        if joined:
            result.append(AttributedPassage(passage=joined, case_name=current_case))
        current = []

    for line in answer_text.splitlines():
        stripped = line.lstrip()
        if stripped.startswith(">"):
            current.append(stripped[1:].strip())
            continue
        if current:
            _flush()
        # Only level-3 (``### ``) headings carry case attribution. ``##``/``#``
        # (and ``####``) do not — guard with an exact "### " prefix that is not
        # also "#### ".
        if stripped.startswith("### ") and not stripped.startswith("#### "):
            heading = stripped[4:].strip()
            current_case = heading.split(",", 1)[0].strip() or None
    if current:
        _flush()
    return result


def normalize_case_name(name: str) -> str:
    """Normalize a case name for attribution matching.

    Lowercases, strips a trailing ``(...)`` citation parenthetical, strips
    trailing punctuation/whitespace, and collapses internal whitespace runs to
    single spaces. Conservative: only a normalized-exact match attributes.
    """
    text = name.strip()
    # Drop a trailing parenthetical citation, e.g. "(410 U.S. 113)".
    text = re.sub(r"\s*\([^()]*\)\s*$", "", text)
    text = text.lower()
    text = re.sub(r"\s+", " ", text)
    return text.strip().rstrip(",;: ")


def match_case_name(parsed: str, clusters: Sequence[tuple[int, str]]) -> int | None:
    """Return the cluster_id iff exactly one cluster's case_name matches ``parsed``.

    Normalized-exact, single-match only (the false-positive guard). Zero matches,
    two-or-more matches, or clusters with an empty case_name → ``None`` →
    the passage stays on the B1b path (never produces a FAIL row).
    """
    target = normalize_case_name(parsed)
    if not target:
        return None
    matches = [cid for cid, name in clusters if name and normalize_case_name(name) == target]
    return matches[0] if len(matches) == 1 else None


def extract_blockquote_passages(answer_text: str) -> list[str]:
    """Return the text of each markdown blockquote in ``answer_text`` (flat list).

    Retained for existing callers/tests; equivalent to the passages produced by
    :func:`attribute_passages`.
    """
    return [a.passage for a in attribute_passages(answer_text)]


# Stable namespace so a given opinion_id maps to a deterministic synthetic id.
_OPINION_NS = uuid.UUID("6f9619ff-8b86-d011-b42d-00cf4fc964ff")


@dataclass(slots=True)
class _OpinionVerificationTarget:
    """Adapts a stored opinion to the verifier's document protocol (no DB row)."""

    id: uuid.UUID
    normalized_content: str
    was_ocrd: bool = False


@dataclass(slots=True)
class _CaselawCandidate:
    """A located quote span, shaped for the verifier's candidate protocol."""

    source_offset_start: int
    source_offset_end: int
    source_text: str
    source_document_id: uuid.UUID


def opinion_target(opinion_id: int, text: str) -> _OpinionVerificationTarget:
    return _OpinionVerificationTarget(
        id=uuid.uuid5(_OPINION_NS, str(opinion_id)),
        normalized_content=text,
        was_ocrd=False,
    )


def locate_passage(passage: str, opinion_text: str) -> tuple[int, int] | None:
    """Exact-substring offsets of ``passage`` in ``opinion_text``, or None.

    v1 locates verbatim spans only; the cascade confirms them as ``exact_match``.
    A whitespace-tolerant locator (feeding stage-2) is a noted follow-on.
    """
    needle = passage.strip()
    if not needle:
        return None
    idx = opinion_text.find(needle)
    if idx < 0:
        return None
    return idx, idx + len(needle)


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

log = logging.getLogger(__name__)

_LoadOpinionText = Callable[[AsyncSession, int], Awaitable[str]]


async def _default_load_opinion_text(db: AsyncSession, opinion_id: int) -> str:
    result: dict[str, Any] = await read_opinion(db, opinion_id=opinion_id)
    return result["text"]


async def verify_and_persist_caselaw_citations(
    db: AsyncSession,
    *,
    message_id: uuid.UUID,
    assistant_text: str,
    tool_sources: Sequence[ToolSourceRecord],
    load_opinion_text: _LoadOpinionText = _default_load_opinion_text,
    gateway: _JudgeGatewayProtocol | None = None,
    judge_model: str = "fast",
) -> int:
    """Verify caselaw quotes in ``assistant_text`` and persist verified rows.

    Stage 1: verbatim locate + deterministic cascade (stages 1-2). Stage 2
    (P1-B1b, SUPPORTED): passages that produced no verbatim row are judged
    against the whole opinion text (cost-gated, additive-only).

    ``gateway=None`` (default) runs the verbatim path only — behaviour is
    byte-for-byte identical to the pre-P1-B1b implementation.

    Returns the total row count. Never raises on a per-opinion failure
    (conservative posture): a load miss is logged and skipped, and the turn
    proceeds with whatever verified.
    """
    cluster_ids = {
        int(r.external_ref)
        for r in tool_sources
        if r.source_kind == "caselaw" and r.external_ref and r.external_ref.isdigit()
    }
    if not cluster_ids:
        return 0
    passages = extract_blockquote_passages(assistant_text)
    if not passages:
        return 0
    opinions = (
        (
            await db.execute(
                select(ResearchOpinionMetadata).where(
                    ResearchOpinionMetadata.cluster_id.in_(cluster_ids)
                )
            )
        )
        .scalars()
        .all()
    )
    if not opinions:
        return 0

    # Read each consulted opinion's text once (skip unreadable).
    texts: list[tuple[ResearchOpinionMetadata, str]] = []
    for op in opinions:
        try:
            texts.append((op, await load_opinion_text(db, op.opinion_id)))
        except Exception as exc:  # storage miss / not-fetched — never fatal
            log.warning("caselaw verify: could not load opinion %s: %r", op.opinion_id, exc)

    rows: list[MessageCaselawCitation] = []

    # --- Verbatim loop (stages 1-2) ----------------------------------------
    # Track which passages were resolved verbatim so the judge pass can skip them.
    verbatim_matched: set[str] = set()
    for passage in passages:
        for op, text in texts:
            loc = locate_passage(passage, text)
            if loc is None:
                continue
            start, end = loc
            target = opinion_target(op.opinion_id, text)
            candidate = _CaselawCandidate(
                source_offset_start=start,
                source_offset_end=end,
                source_text=passage,
                source_document_id=target.id,
            )
            result = await verify(candidate, target, gateway=None)
            if not result.verified:
                continue
            rows.append(
                MessageCaselawCitation(
                    message_id=message_id,
                    opinion_id=op.opinion_id,
                    cluster_id=op.cluster_id,
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
            break  # one verified row per passage (first matching opinion wins)

    # --- SUPPORTED judge pass (P1-B1b, additive-only) -----------------------
    # Only runs when a gateway is supplied. Passages that got a verbatim row
    # are skipped. Per-turn budget stops the whole pass when exceeded.
    if gateway is not None:
        spent: Decimal = Decimal("0")
        budget_exhausted = False
        for passage in passages:
            if budget_exhausted:
                break
            if passage in verbatim_matched:
                continue  # already have a verbatim row — skip
            for op, text in texts:
                est = await estimate_case_content_cost_usd(
                    db, judge_model=judge_model, opinion_text=text
                )
                if spent + est > CASE_CONTENT_JUDGE_BUDGET_USD:
                    log.info(
                        "case-content judge: per-turn budget reached; stopping judge pass",
                        extra={"event": "caselaw_judge_budget_reached"},
                    )
                    budget_exhausted = True
                    break  # stop the whole judge pass for this turn
                spent += est
                # Defense-in-depth: judge_case_content is contractually non-raising
                # (all errors resolve to _MISS), but the guard protects against a
                # future refactor that inadvertently breaks that contract.
                try:
                    result = await judge_case_content(
                        passage=passage,
                        opinion_text=text,
                        gateway=gateway,
                        judge_model=judge_model,
                    )
                except Exception as exc:
                    log.warning(
                        "case-content judge error on opinion %s: %r",
                        op.opinion_id,
                        exc,
                    )
                    continue  # per-opinion error — try next opinion
                if not result.verified:
                    continue  # this opinion's judge rejected — try next opinion
                # Judge accepted — write one SUPPORTED row and move to next passage.
                rows.append(
                    MessageCaselawCitation(
                        message_id=message_id,
                        opinion_id=op.opinion_id,
                        cluster_id=op.cluster_id,
                        source_offset_start=0,
                        source_offset_end=len(text),
                        source_text=passage,
                        verified=True,
                        verification_method="paraphrase_judge",
                        verification_confidence=result.confidence,
                        partial=True,
                    )
                )
                break  # one SUPPORTED row per passage; first accepting opinion wins

    # --- Persist (single add_all / flush) -----------------------------------
    if rows:
        db.add_all(rows)
        await db.flush()
    return len(rows)
