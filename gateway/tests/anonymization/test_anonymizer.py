"""Anonymizer.pseudonymize + Anonymizer.rehydrate — M2-B3.

The Anonymizer façade is the entry point the gateway middleware uses
for the request-path substitution (pseudonymize) and the response-path
restoration (rehydrate). M2-A3 shipped the class shape with stubs;
M2-B2 made the AnalyzerEngine singleton available; M2-B3 (this task)
fills in the methods.

These tests cover pure-logic invariants that don't require the spaCy
backbone:

* ``rehydrate`` is pure string substitution against the mapper's
  reverse() table — it never calls the analyzer.
* ``pseudonymize`` *does* call the analyzer; the tests in this file
  that exercise pseudonymize use a stub analyzer (a callable that
  returns canned ``RecognizerResult`` tuples) so the spaCy load stays
  off the fast-feedback path. The full end-to-end check (analyzer +
  pseudonymize + rehydrate) lives in ``test_engine_integration.py``
  under the ``slow`` marker.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from app.anonymization.engine import Anonymizer
from app.anonymization.mapper import PseudonymMapper

# ---------------------------------------------------------------------------
# Test doubles — a stub analyzer that mimics ``AnalyzerEngine.analyze``.
#
# Presidio's :class:`AnalyzerEngine` returns a list of
# :class:`RecognizerResult` instances with ``entity_type``, ``start``,
# ``end``, ``score``. We don't need the real engine in these unit tests —
# the substitution logic is what we're exercising. A stub keeps spaCy off
# the fast feedback path. End-to-end coverage with the real analyzer lives
# in ``test_engine_integration.py`` under the ``slow`` marker.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _Span:
    """Mimics ``presidio_analyzer.RecognizerResult`` for what we read."""

    entity_type: str
    start: int
    end: int
    score: float = 0.85


class _StubAnalyzer:
    """Returns a canned list of spans regardless of input text.

    Tests construct one per scenario with the spans they want surfaced.
    The ``analyze`` signature matches Presidio's: ``analyze(text, language=...)``.
    """

    def __init__(self, spans: list[_Span]) -> None:
        self._spans = spans

    def analyze(self, *, text: str, language: str = "en", **_kwargs: object) -> list[_Span]:
        return list(self._spans)


# ---------------------------------------------------------------------------
# rehydrate — pure string substitution. No analyzer involved.
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_rehydrate_substitutes_single_pseudonym() -> None:
    """A pseudonym in the text is replaced with its mapped original."""

    mapper = PseudonymMapper()
    mapper.assign("PERSON", "John Smith")  # → PERSON_0001

    out = Anonymizer().rehydrate("PERSON_0001 signed the agreement.", mapper)

    assert out == "John Smith signed the agreement."


@pytest.mark.unit
def test_rehydrate_substitutes_multiple_distinct_pseudonyms() -> None:
    """Every pseudonym in the text gets its own substitution."""

    mapper = PseudonymMapper()
    mapper.assign("PERSON", "John Smith")  # PERSON_0001
    mapper.assign("PERSON", "Jane Doe")  # PERSON_0002
    mapper.assign("ORGANIZATION", "Acme LLP")  # ORGANIZATION_0001

    text = "PERSON_0001 and PERSON_0002 of ORGANIZATION_0001 signed the deal."
    out = Anonymizer().rehydrate(text, mapper)

    assert out == "John Smith and Jane Doe of Acme LLP signed the deal."


@pytest.mark.unit
def test_rehydrate_handles_repeated_pseudonym() -> None:
    """The same pseudonym appearing twice is replaced both times."""

    mapper = PseudonymMapper()
    mapper.assign("PERSON", "John Smith")

    out = Anonymizer().rehydrate("PERSON_0001 emailed PERSON_0001 to confirm.", mapper)

    assert out == "John Smith emailed John Smith to confirm."


@pytest.mark.unit
def test_rehydrate_handles_prefix_collision() -> None:
    """``PERSON_00010`` must not be matched-then-broken by ``PERSON_0001``.

    Without length-ordered substitution, replacing ``PERSON_0001`` first
    would mangle ``PERSON_00010`` into ``John Smith0``. The rehydrator
    must substitute longer pseudonyms before shorter ones.
    """

    mapper = PseudonymMapper()
    # Force the assignments so we get specific pseudonyms regardless of
    # internal counter behavior. We use the mapper's public assign() API
    # and verify the contract holds for whatever pseudonyms it produces.
    p1 = mapper.assign("PERSON", "John Smith")  # PERSON_0001
    # Cheat: directly extend the mapping to inject a longer pseudonym
    # that would collide on prefix. This mirrors what would happen at
    # counter overflow past 9999.
    mapper._assignments[("PERSON", "Janet Doe")] = "PERSON_00010"

    text = "PERSON_0001 and PERSON_00010 met."
    out = Anonymizer().rehydrate(text, mapper)

    # Both substitutions correct, neither mangled.
    assert out == "John Smith and Janet Doe met."
    # Sanity check the assigned pseudonym above is what we think.
    assert p1 == "PERSON_0001"


@pytest.mark.unit
def test_rehydrate_text_with_no_pseudonyms_is_identity() -> None:
    """Text containing no pseudonyms passes through unchanged."""

    mapper = PseudonymMapper()
    mapper.assign("PERSON", "John Smith")

    text = "The agreement was signed yesterday."
    assert Anonymizer().rehydrate(text, mapper) == text


@pytest.mark.unit
def test_rehydrate_empty_mapper_is_identity() -> None:
    """An empty mapper has no substitutions to make; text is identical."""

    text = "PERSON_0001 is a pseudonym that has no mapping."
    assert Anonymizer().rehydrate(text, PseudonymMapper()) == text


@pytest.mark.unit
def test_rehydrate_empty_text_is_empty() -> None:
    """Empty text returns empty regardless of mapper state."""

    mapper = PseudonymMapper()
    mapper.assign("PERSON", "John Smith")

    assert Anonymizer().rehydrate("", mapper) == ""


# ---------------------------------------------------------------------------
# pseudonymize_into — extend an existing mapper with substitutions from text.
# Tests use a stub analyzer (see top of file) so spaCy stays off the fast path.
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_pseudonymize_into_substitutes_single_span() -> None:
    """A single PERSON span is substituted with the mapper's pseudonym."""

    analyzer = _StubAnalyzer([_Span("PERSON", 0, 10)])  # "John Smith"
    mapper = PseudonymMapper()

    out = Anonymizer(analyzer=analyzer).pseudonymize_into(
        "John Smith signed the agreement.", mapper
    )

    assert out == "PERSON_0001 signed the agreement."
    assert mapper.reverse() == {"PERSON_0001": "John Smith"}


@pytest.mark.unit
def test_pseudonymize_into_multiple_distinct_entities() -> None:
    """Distinct PERSON spans get distinct pseudonyms; counter increments."""

    text = "John Smith and Jane Doe met."
    spans = [
        _Span("PERSON", 0, 10),  # John Smith
        _Span("PERSON", 15, 23),  # Jane Doe
    ]
    mapper = PseudonymMapper()

    out = Anonymizer(analyzer=_StubAnalyzer(spans)).pseudonymize_into(text, mapper)

    assert out == "PERSON_0001 and PERSON_0002 met."
    assert mapper.reverse() == {"PERSON_0001": "John Smith", "PERSON_0002": "Jane Doe"}


@pytest.mark.unit
def test_pseudonymize_into_same_name_twice_stable_pseudonym() -> None:
    """The same name appearing twice in one text resolves to one pseudonym."""

    text = "John Smith emailed John Smith to confirm."
    spans = [
        _Span("PERSON", 0, 10),  # John Smith (first)
        _Span("PERSON", 19, 29),  # John Smith (second)
    ]
    mapper = PseudonymMapper()

    out = Anonymizer(analyzer=_StubAnalyzer(spans)).pseudonymize_into(text, mapper)

    assert out == "PERSON_0001 emailed PERSON_0001 to confirm."
    # Mapper has one assignment, not two.
    assert mapper.reverse() == {"PERSON_0001": "John Smith"}


@pytest.mark.unit
def test_pseudonymize_into_per_type_counter_independence() -> None:
    """PERSON and ORGANIZATION counters increment independently."""

    text = "John Smith of Acme Corp signed."
    spans = [
        _Span("PERSON", 0, 10),  # John Smith
        _Span("ORGANIZATION", 14, 23),  # Acme Corp
    ]
    mapper = PseudonymMapper()

    out = Anonymizer(analyzer=_StubAnalyzer(spans)).pseudonymize_into(text, mapper)

    assert out == "PERSON_0001 of ORGANIZATION_0001 signed."


@pytest.mark.unit
def test_pseudonymize_into_extends_existing_mapper() -> None:
    """An existing mapper is extended; pre-existing assignments are reused."""

    mapper = PseudonymMapper()
    # Pre-populate as if a previous message had been pseudonymized.
    mapper.assign("PERSON", "John Smith")  # PERSON_0001

    text = "John Smith and Jane Doe attended."
    spans = [
        _Span("PERSON", 0, 10),  # John Smith — should reuse PERSON_0001
        _Span("PERSON", 15, 23),  # Jane Doe — new, gets PERSON_0002
    ]
    out = Anonymizer(analyzer=_StubAnalyzer(spans)).pseudonymize_into(text, mapper)

    assert out == "PERSON_0001 and PERSON_0002 attended."


@pytest.mark.unit
def test_pseudonymize_into_no_spans_is_identity() -> None:
    """Analyzer returning no spans leaves text and mapper untouched."""

    mapper = PseudonymMapper()
    text = "The agreement was signed yesterday."

    out = Anonymizer(analyzer=_StubAnalyzer([])).pseudonymize_into(text, mapper)

    assert out == text
    assert mapper.reverse() == {}


@pytest.mark.unit
def test_pseudonymize_into_empty_text_is_empty() -> None:
    """Empty text returns empty; analyzer never called with substance."""

    mapper = PseudonymMapper()
    out = Anonymizer(analyzer=_StubAnalyzer([])).pseudonymize_into("", mapper)

    assert out == ""
    assert mapper.reverse() == {}


@pytest.mark.unit
def test_pseudonymize_into_resolves_overlapping_spans() -> None:
    """Overlapping detections collapse to one substitution (longest span wins).

    Presidio's analyzer may surface multiple recognizers for the same
    span — e.g. a name that's also a US_BANK_NUMBER false positive. The
    substitution must collapse cleanly without trying to substitute
    inside a substitution.
    """

    text = "John Smith signed the agreement."
    # Two overlapping spans on "John Smith": one PERSON (full name),
    # one shorter that overlaps. The longer span wins.
    spans = [
        _Span("PERSON", 0, 10, score=0.95),  # John Smith
        _Span("PERSON", 0, 4, score=0.6),  # John (shorter overlap)
    ]
    mapper = PseudonymMapper()
    out = Anonymizer(analyzer=_StubAnalyzer(spans)).pseudonymize_into(text, mapper)

    # The longer span is the one substituted; "John" alone is not also
    # substituted into the middle of "PERSON_0001".
    assert out == "PERSON_0001 signed the agreement."
    assert mapper.reverse() == {"PERSON_0001": "John Smith"}


# ---------------------------------------------------------------------------
# pseudonymize — one-shot convenience: fresh mapper per call.
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_pseudonymize_returns_result_with_fresh_mapper() -> None:
    """One-shot pseudonymize wraps a fresh mapper in AnonymizationResult."""

    spans = [_Span("PERSON", 0, 10)]
    result = Anonymizer(analyzer=_StubAnalyzer(spans)).pseudonymize("John Smith signed.")

    assert result.text == "PERSON_0001 signed."
    assert result.mapper.reverse() == {"PERSON_0001": "John Smith"}
