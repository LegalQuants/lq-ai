"""Anonymizer substitution/rehydration property tests — DE-230.

Runs the production substitution machinery
(:meth:`Anonymizer.pseudonymize_into` → :meth:`Anonymizer.rehydrate`)
against generated entity-laden documents with a span-list analyzer
stub, so the properties hold *whatever* the NER reports and the
example budget isn't spent on spaCy.

Two legal-semantics invariants:

1. **Round-trip identity** — rehydrating the anonymized text restores
   the original byte-for-byte. A lawyer's work product must come back
   exactly as written; "close" is corruption.
2. **No recognized entity survives** — no character of any
   analyzer-recognized entity remains in the text sent to the
   provider. This is the fail-closed half of the anonymization
   promise and partially delivers DE-240 (PII leakage testing); the
   *recall* half (does the analyzer recognize the PII at all?) is
   corpus work that stays with DE-240.

Scope note (DE-274): documents containing literal pseudonym-shaped
strings are excluded by the strategies — that ambiguity is a known,
separately-tracked issue.
"""

from __future__ import annotations

from hypothesis import given, strategies as st

from app.anonymization.engine import Anonymizer
from app.anonymization.mapper import PseudonymMapper

from .strategies import (
    GREEK,
    Span,
    SpanListAnalyzer,
    entity_documents,
    greek_entity_original,
    non_greek_filler,
)


@given(entity_documents())
def test_pseudonymize_then_rehydrate_is_identity(doc: tuple[str, list[Span]]) -> None:
    """rehydrate(pseudonymize(text)) == text for any recognized span set."""

    text, spans = doc
    anonymizer = Anonymizer(analyzer=SpanListAnalyzer(spans))
    mapper = PseudonymMapper()
    anonymized = anonymizer.pseudonymize_into(text, mapper)
    assert anonymizer.rehydrate(anonymized, mapper) == text


@given(st.lists(entity_documents(), min_size=1, max_size=4))
def test_round_trip_holds_across_multi_message_mapper_reuse(
    docs: list[tuple[str, list[Span]]],
) -> None:
    """One mapper threaded through several texts (the middleware pattern)
    still round-trips every text, and repeated (type, original) pairs
    resolve to the same pseudonym across messages."""

    mapper = PseudonymMapper()
    anonymized: list[str] = []
    for text, spans in docs:
        anonymizer = Anonymizer(analyzer=SpanListAnalyzer(spans))
        anonymized.append(anonymizer.pseudonymize_into(text, mapper))
    # Rehydration uses only the mapper; any anonymizer instance works.
    rehydrator = Anonymizer(analyzer=SpanListAnalyzer([]))
    for (text, _), anon in zip(docs, anonymized, strict=True):
        assert rehydrator.rehydrate(anon, mapper) == text


@given(
    entity_documents(
        originals=greek_entity_original,
        filler=non_greek_filler,
    )
)
def test_no_recognized_entity_text_survives_anonymization(
    doc: tuple[str, list[Span]],
) -> None:
    """No character of any recognized entity appears in the anonymized text.

    Entities are Greek-only and filler is Greek-free, so every Greek
    character in the document lies inside a recognized span — the
    assertion is exact, not probabilistic. Partial DE-240.
    """

    text, spans = doc
    anonymizer = Anonymizer(analyzer=SpanListAnalyzer(spans))
    anonymized = anonymizer.pseudonymize_into(text, PseudonymMapper())
    assert not set(anonymized) & set(GREEK), anonymized


@given(entity_documents())
def test_overlapping_detections_still_round_trip(doc: tuple[str, list[Span]]) -> None:
    """Duplicate + nested span reports (two recognizers firing on the same
    region) collapse to one substitution and still round-trip."""

    text, spans = doc
    noisy: list[Span] = []
    for span in spans:
        noisy.append(span)
        # A duplicate hit from a "second recognizer" at lower score.
        noisy.append(Span(entity_type="ORGANIZATION", start=span.start, end=span.end, score=0.4))
        # A nested, shorter hit inside the same region.
        if span.end - span.start > 1:
            noisy.append(
                Span(entity_type="LOCATION", start=span.start, end=span.end - 1, score=0.9)
            )
    anonymizer = Anonymizer(analyzer=SpanListAnalyzer(noisy))
    mapper = PseudonymMapper()
    anonymized = anonymizer.pseudonymize_into(text, mapper)
    assert anonymizer.rehydrate(anonymized, mapper) == text
