"""StreamingRehydrator chunk-boundary property tests — DE-230.

The classic streaming bug is a token straddling a chunk boundary. The
properties here split the anonymized stream at *arbitrary* generated
positions — including splits inside pseudonyms, inside multi-byte
originals, and empty chunks — and require the chunked output to equal
the one-shot result.

Two invariants:

1. **Split-invariance (equivalence).** For any text and any mapper,
   ``join(process(chunks)) + flush()`` equals the one-shot
   ``Anonymizer.rehydrate`` of the whole text. Chunking is a transport
   detail; it must never change the rehydrated stream.
2. **Round-trip through the streaming path.** For well-formed
   anonymized documents (the supported corpus, DE-274 shapes
   excluded), the streamed rehydration restores the original text
   exactly.
"""

from __future__ import annotations

from hypothesis import given, strategies as st

from app.anonymization.engine import Anonymizer
from app.anonymization.mapper import PseudonymMapper
from app.anonymization.middleware import StreamingRehydrator

from .strategies import (
    ENTITY_TYPES,
    PSEUDONYM_SHAPE,
    Span,
    SpanListAnalyzer,
    chunk_at,
    entity_documents,
    entity_original,
)

cut_positions = st.lists(st.integers(min_value=0, max_value=200), max_size=24)


def _stream(text: str, cuts: list[int], mapper: PseudonymMapper) -> str:
    anonymizer = Anonymizer(analyzer=SpanListAnalyzer([]))
    rehydrator = StreamingRehydrator(mapper=mapper, anonymizer=anonymizer)
    out = "".join(rehydrator.process(chunk) for chunk in chunk_at(text, cuts))
    return out + rehydrator.flush()


@given(entity_documents(), cut_positions)
def test_streamed_rehydration_restores_original_at_any_split(
    doc: tuple[str, list[Span]], cuts: list[int]
) -> None:
    """Anonymize a document, stream the anonymized text in arbitrary
    chunks, and require the original back byte-for-byte."""

    text, spans = doc
    anonymizer = Anonymizer(analyzer=SpanListAnalyzer(spans))
    mapper = PseudonymMapper()
    anonymized = anonymizer.pseudonymize_into(text, mapper)
    assert _stream(anonymized, cuts, mapper) == text


@given(
    st.text(max_size=120),
    cut_positions,
    st.lists(
        st.tuples(st.sampled_from(ENTITY_TYPES), entity_original),
        max_size=10,
    ),
)
def test_streaming_equals_one_shot_for_arbitrary_text_and_mapper(
    text: str, cuts: list[int], assignments: list[tuple[str, str]]
) -> None:
    """Split-invariance on *arbitrary* input text (not just well-formed
    anonymizer output): chunked processing must equal one-shot
    rehydration even for pseudonym-shaped junk, partial pseudonym
    tails at EOF, and uppercase runs.

    Originals that themselves contain a pseudonym shape are excluded —
    substituting one pseudonym must not fabricate another (DE-274
    territory, out of the supported contract).
    """

    mapper = PseudonymMapper()
    for etype, original in assignments:
        if PSEUDONYM_SHAPE.search(original):
            continue
        mapper.assign(etype, original)

    anonymizer = Anonymizer(analyzer=SpanListAnalyzer([]))
    one_shot = anonymizer.rehydrate(text, mapper)
    assert _stream(text, cuts, mapper) == one_shot


@given(entity_documents())
def test_character_at_a_time_streaming_restores_original(
    doc: tuple[str, list[Span]],
) -> None:
    """The pathological split: every character its own SSE chunk."""

    text, spans = doc
    anonymizer = Anonymizer(analyzer=SpanListAnalyzer(spans))
    mapper = PseudonymMapper()
    anonymized = anonymizer.pseudonymize_into(text, mapper)
    assert _stream(anonymized, list(range(len(anonymized) + 1)), mapper) == text
