"""Caselaw quote verification (P1-A1).

Extracts blockquote passages from an assistant answer, locates each verbatim in
a consulted CourtListener opinion's stored plaintext, runs the existing citation
cascade (deterministic stages 1-2), and persists verified rows.
See docs/superpowers/specs/2026-06-24-p1a1-external-caselaw-quote-verification-design.md.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass


def extract_blockquote_passages(answer_text: str) -> list[str]:
    """Return the text of each markdown blockquote in ``answer_text``.

    The case-law-research skill renders each cited passage as a markdown
    blockquote (``> ...``) under a "Relevant passage:" header. Consecutive
    blockquote lines are one passage (wrapped quote); a non-blockquote line
    ends the current passage.
    """
    passages: list[str] = []
    current: list[str] = []
    for line in answer_text.splitlines():
        stripped = line.lstrip()
        if stripped.startswith(">"):
            current.append(stripped[1:].strip())
        elif current:
            joined = " ".join(p for p in current if p).strip()
            if joined:
                passages.append(joined)
            current = []
    if current:
        joined = " ".join(p for p in current if p).strip()
        if joined:
            passages.append(joined)
    return passages


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
