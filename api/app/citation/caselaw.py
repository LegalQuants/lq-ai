"""Caselaw quote verification (P1-A1).

Extracts blockquote passages from an assistant answer, locates each verbatim in
a consulted CourtListener opinion's stored plaintext, runs the existing citation
cascade (deterministic stages 1-2), and persists verified rows.
See docs/superpowers/specs/2026-06-24-p1a1-external-caselaw-quote-verification-design.md.
"""

from __future__ import annotations


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
