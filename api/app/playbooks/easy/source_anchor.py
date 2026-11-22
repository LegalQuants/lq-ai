"""Locate a contiguous quotation and retain original document coordinates."""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class SourceMatch:
    text: str
    start: int
    end: int


def _normalized(text: str) -> tuple[str, list[int]]:
    # Collapse PDF whitespace, including a wrap after an existing hyphen.
    # Never remove words/punctuation or stitch non-adjacent list items.
    chars: list[str] = []
    offsets: list[int] = []
    for match in re.finditer(r"\s+|\S", text):
        token = match.group()
        if token.isspace():
            if chars and chars[-1] != "-":
                chars.append(" ")
                offsets.append(match.start())
        else:
            chars.append(token)
            offsets.append(match.start())
    return "".join(chars).rstrip(), offsets


def anchor_quote(
    source: str, quote: str, *, require_clause_boundaries: bool = True
) -> SourceMatch | None:
    """Find the first complete contiguous match, allowing only layout changes.

    Returned text is the actual source slice, not the model's reconstruction.
    Model-supplied offsets are deliberately not used as evidence.
    """
    normalized_source, offsets = _normalized(source)
    normalized_quote, _ = _normalized(quote)
    if not normalized_quote:
        return None
    start = normalized_source.find(normalized_quote)
    while start >= 0:
        end = start + len(normalized_quote)
        source_start, source_end = offsets[start], offsets[end - 1] + 1
        before = source[:source_start]
        after = source[source_end:].lstrip()
        begins_clause = not before.strip() or re.search(
            r"""(?:[.;:]["\u201d\u2019']*\s*(?:(?:and|or)\s+)?|\n\s*|\([a-zA-Z0-9]+\)\s*)$""",
            before,
        )
        ends_clause = (
            not after
            or source[:source_end].rstrip("\"\u201d\u2019'")[-1:] in (".", ";", ":")
            or after[0] in ".;:"
        )
        if not require_clause_boundaries or (begins_clause and ends_clause):
            return SourceMatch(source[source_start:source_end], source_start, source_end)
        start = normalized_source.find(normalized_quote, start + 1)
    return None


def repair_context(source: str, quote: str) -> str | None:
    """Offer complete source context to the repair model, never accept it unseen.

    A located fragment can omit a subject, qualifier, or negation. Include the
    whole surrounding sentence in the repair request so the model can copy it.
    The returned repair still passes the normal boundary and identity checks.
    """
    match = anchor_quote(source, quote, require_clause_boundaries=False)
    if match is None:
        return None
    start = max(source.rfind(".", 0, match.start), source.rfind(";", 0, match.start)) + 1
    while start < match.start and source[start] in "\"\u201d\u2019'":
        start += 1
    endings = [p for mark in ".;" if (p := source.find(mark, match.end)) >= 0]
    end = min(endings) + 1 if endings else len(source)
    if source[match.end - 1 : match.end] in (".", ";"):
        end = match.end
    return source[start:end].strip()
