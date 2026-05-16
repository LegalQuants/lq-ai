"""Citation extraction from assistant responses — quote-then-locate.

The model is instructed (via the RAG context-block system message) to
quote source passages in double quotes followed by ``(Source: [N])``
where ``N`` is the 1-based index of the retrieved chunk the quote came
from. This module parses that shape and resolves each quote to a
byte-precise span in the source document.

Resolution mechanics:

1. Regex over the response text matches both straight ``"..."`` and
   curly ``"..."`` quoted spans followed by ``(Source: [N])``.
2. For each match, look up ``retrieved_chunks[N - 1]``.
3. Locate the quote inside the chunk's content:

   * **Fast path:** byte-for-byte substring search via ``str.find``.
   * **Fallback (M2-B1):** when byte-for-byte misses, use
     :func:`rapidfuzz.fuzz.partial_ratio_alignment` to find the
     best-aligned span. Threshold 85 gates extraction — looser than
     the Stage 2 verifier's 95, so a candidate that survives
     extraction may still get rejected by verification. Quotes with
     no real overlap (an unrelated model fabrication) drop here.
4. Materialize a :class:`CitationCandidate` carrying the source
   document id + file id + byte-precise offsets + the model's quote
   verbatim. The verifier cascade (``app.citation.verification.verify``)
   then runs Stage 1 (byte-for-byte at offsets) and, on failure,
   Stage 2 (normalized fuzzy ratio).

Why a permissive extractor + strict verifier?
---------------------------------------------

Earlier M2-A2 extraction was strict (straight quotes + byte-for-byte
only) and dropped smart-quoted or whitespace-divergent citations
silently. With the M2-B1 Stage 2 verifier in place that policy hides
real wins — the verifier was built to forgive exactly those
normalization-only differences, but the candidates never reached it.
M2-B1 loosens extraction so the verifier sees more candidates and
ultimately the model's smart-quote citations land as
``verified=True, method='tolerant_match'``.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from rapidfuzz import fuzz


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


# Regex: matches both straight (``"..."``) and curly (``"..."``)
# double-quote pairs followed by ``(Source: [N])``. Alternation gives
# two named groups; one is non-None per match.
#
# ``re.DOTALL`` lets the body span line breaks. The body uses a lazy
# match (``+?``) so we don't gobble a closing quote that belongs to a
# later, different citation.
_CITATION_RE = re.compile(
    r'"(?P<sq>[^"]+?)"\s*\(Source:\s*\[(?P<sq_index>\d+)\]\)'
    r"|"
    r"“(?P<cq>[^”]+?)”\s*\(Source:\s*\[(?P<cq_index>\d+)\]\)",
    flags=re.DOTALL,
)

# Extraction-level fuzzy threshold. Below this, the quote is considered
# unrelated to the chunk content (model fabricated or mis-cited).
# Above, the candidate proceeds to the verifier cascade — Stage 1
# expects a byte-for-byte hit (rare after fallback fired) and Stage 2
# expects 95 on normalized text. Picking 85 here gives the Stage 2
# verifier a 10-point cushion to absorb meaningful normalization
# differences while filtering out obvious junk.
_ALIGNMENT_THRESHOLD = 85.0


def _locate_in_chunk(quote: str, chunk_content: str) -> tuple[int, int] | None:
    """Find ``quote`` inside ``chunk_content`` — exact, then fuzzy.

    Returns the (start, end) offsets *into the chunk's content string*
    (not the document) when a credible match is found. ``None`` when
    no match survives the fuzzy threshold.
    """

    exact = chunk_content.find(quote)
    if exact >= 0:
        return exact, exact + len(quote)

    if not chunk_content or not quote:
        return None

    alignment = fuzz.partial_ratio_alignment(quote, chunk_content)
    if alignment is None or alignment.score < _ALIGNMENT_THRESHOLD:
        return None

    return alignment.dest_start, alignment.dest_end


def extract_citations(
    response_text: str,
    retrieved_chunks: Sequence[_RetrievedChunk],
) -> list[CitationCandidate]:
    """Extract citations from the assistant response.

    Args:
        response_text: The full assistant message content.
        retrieved_chunks: The RAG-retrieved chunks delivered to the
            model in this turn's prompt, in the same order they were
            numbered ``[1], [2], …`` in the context block.

    Returns:
        One :class:`CitationCandidate` per ``"..." (Source: [N])``
        pair (straight or curly quotes) whose quote could be located
        inside its cited chunk — exactly or via fuzzy alignment
        above the extraction threshold. Pairs whose quote is
        unfindable or whose index is out of range are dropped silently.
    """

    candidates: list[CitationCandidate] = []

    for match in _CITATION_RE.finditer(response_text):
        # Exactly one of the two named branches is populated per match.
        quote = match.group("sq") or match.group("cq")
        index_str = match.group("sq_index") or match.group("cq_index")
        if quote is None or index_str is None:
            continue

        index_1based = int(index_str)
        if not (1 <= index_1based <= len(retrieved_chunks)):
            continue

        chunk = retrieved_chunks[index_1based - 1]
        located = _locate_in_chunk(quote, chunk.content)
        if located is None:
            # Quote is neither a byte-for-byte substring nor a
            # close-enough fuzzy match. The model either fabricated
            # the quote or mis-cited the chunk index.
            continue

        in_chunk_start, in_chunk_end = located
        offset_start = chunk.char_offset_start + in_chunk_start
        offset_end = chunk.char_offset_start + in_chunk_end

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
