"""Citation extraction from assistant responses — Stage 1 (quote-then-locate).

The model is instructed (in the RAG context-block system message) to
quote source passages verbatim in straight double-quotes followed by
``(Source: [N])`` where ``N`` is the 1-based index of the retrieved
chunk the quote came from. This module parses that shape and resolves
each quote to a byte-precise span in the source document.

Resolution mechanics:

1. Regex over the response text for ``"..."\\s*(Source: [N])``.
2. For each match, look up ``retrieved_chunks[N - 1]``.
3. Locate the quote inside the chunk's content via ``str.find``.
4. Derive the document offsets:
   ``chunk.char_offset_start + match_pos`` … ``+ len(quote)``.
5. Materialize a :class:`CitationCandidate` carrying everything the
   verifier and the persistence layer need.

Quotes that can't be located (the model fabricated the quote or
mis-cited the chunk index) are silently dropped — M2-A2 does not
persist citations without valid offsets, and "the model claimed to
quote but we can't find it" is a separate failure-mode to audit
(future task).

Stage 1 is intentionally strict: smart quotes, whitespace
differences, and paraphrases will not match. Those falls through to
later stages once they ship (M2-B1 / M2-C1).
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol


# A protocol so the extractor accepts any chunk-shaped object — the
# production caller passes ``HybridSearchResult``; tests pass a stub.
class _RetrievedChunk(Protocol):
    document_id: uuid.UUID
    file_id: uuid.UUID
    content: str
    page_start: int | None
    char_offset_start: int
    char_offset_end: int


@dataclass(slots=True)
class CitationCandidate:
    """One extracted citation with byte-precise offsets, awaiting verification.

    All fields map 1-to-1 onto the ``message_citations`` row the
    persistence step will create. The verifier runs against this
    shape and stamps the ``verified`` / method / confidence flags.
    """

    source_file_id: uuid.UUID
    source_document_id: uuid.UUID
    source_offset_start: int
    source_offset_end: int
    source_page: int | None
    source_text: str


# Straight double quote, lazy non-empty body, optional whitespace, then
# ``(Source: [N])``. ``re.DOTALL`` lets the body span line breaks.
# A negative-lookahead inside the body prevents the regex from
# absorbing a closing quote that belongs to a later, different citation.
_CITATION_RE = re.compile(
    r'"(?P<quote>[^"]+?)"\s*\(Source:\s*\[(?P<index>\d+)\]\)',
    flags=re.DOTALL,
)


def extract_citations(
    response_text: str,
    retrieved_chunks: Sequence[_RetrievedChunk],
) -> list[CitationCandidate]:
    """Extract Stage-1-locatable citations from the assistant response.

    Args:
        response_text: The full assistant message content.
        retrieved_chunks: The RAG-retrieved chunks delivered to the
            model in this turn's prompt, in the same order they were
            numbered ``[1], [2], …`` in the context block.

    Returns:
        One :class:`CitationCandidate` per ``"..." (Source: [N])``
        pair whose quote could be located inside its cited chunk.
        Pairs whose quote is unfindable or whose index is out of
        range are dropped silently.
    """

    candidates: list[CitationCandidate] = []

    for match in _CITATION_RE.finditer(response_text):
        quote = match.group("quote")
        index_1based = int(match.group("index"))

        if not (1 <= index_1based <= len(retrieved_chunks)):
            continue

        chunk = retrieved_chunks[index_1based - 1]
        match_pos = chunk.content.find(quote)
        if match_pos < 0:
            # Quote isn't byte-for-byte inside the chunk. Stage 2's
            # tolerant-match will be the right place to handle this;
            # Stage 1 drops it.
            continue

        offset_start = chunk.char_offset_start + match_pos
        offset_end = offset_start + len(quote)

        candidates.append(
            CitationCandidate(
                source_file_id=chunk.file_id,
                source_document_id=chunk.document_id,
                source_offset_start=offset_start,
                source_offset_end=offset_end,
                source_page=chunk.page_start,
                source_text=quote,
            )
        )

    return candidates
