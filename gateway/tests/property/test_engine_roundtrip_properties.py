"""Real-Presidio anonymization property tests — DE-230.

Same invariants as ``test_anonymizer_roundtrip_properties.py`` but
against the **production** AnalyzerEngine (spaCy NER + pattern
recognizers + the custom legal recognizers), so span math is exercised
with whatever the real analyzer emits — overlapping hits, unexpected
boundaries, zero hits — instead of a stub's tidy span list.

The round-trip identity is detection-agnostic: whatever set of spans
the analyzer flags, rehydration must restore the original text exactly.
That makes the property stable across Presidio/spaCy versions even
though the detections themselves are not.

Marked ``slow`` (same convention as ``tests/anonymization/``): the
first example pays the spaCy ``en_core_web_lg`` load; the module-scoped
fixture amortizes it across every example and test in the file.
"""

from __future__ import annotations

import pytest
from hypothesis import HealthCheck, given, settings, strategies as st

from app.anonymization.engine import (
    Anonymizer,
    _reset_analyzer_engine_for_tests,
    get_analyzer_engine,
)
from app.anonymization.mapper import PseudonymMapper

from .strategies import PSEUDONYM_SHAPE

pytestmark = pytest.mark.slow

# Entity-bearing fragments the enabled recognizers plausibly fire on —
# names, orgs, emails, phones, case + matter numbers. Realistic
# fragments (not raw unicode noise) because NER needs prose-shaped
# input to fire at all; the *invariant* still holds for any input.
_NAMES = ("John Smith", "Jane Doe", "Maria Garcia", "Wei Chen", "François Dubois")
_ORGS = ("Acme LLP", "Initech Corporation", "Globex Inc.")
_CONNECTORS = (
    " met with ",
    " signed on behalf of ",
    ", counsel for ",
    " emailed ",
    " called ",
    ". See ",
    ";\nwhereas ",
    "   ",  # noqa: RUF001 — non-breaking space, a deliberate whitespace edge case
    " — ",
)

_email_locals = st.text(alphabet="abcdefghijklmnopqrstuvwxyz.", min_size=1, max_size=12).filter(
    lambda s: not s.startswith(".") and not s.endswith(".") and ".." not in s
)
_email = st.builds(
    "{}@{}.{}".format,
    _email_locals,
    st.text(alphabet="abcdefghijklmnopqrstuvwxyz", min_size=2, max_size=10),
    st.sampled_from(["com", "org", "net"]),
)
_phone = st.builds(
    "415-555-{:04d}".format,
    st.integers(min_value=0, max_value=9999),
)
_case_number = st.builds(
    "{} v. {}, {} F.3d {} (9th Cir. 2024)".format,
    st.sampled_from(("Smith", "Jones", "Doe")),
    st.sampled_from(("Jones", "Acme", "Roe")),
    st.integers(min_value=1, max_value=999),
    st.integers(min_value=1, max_value=999),
)

_fragment = st.one_of(
    st.sampled_from(_NAMES),
    st.sampled_from(_ORGS),
    _email,
    _phone,
    _case_number,
    st.sampled_from(_CONNECTORS),
    # Free-text filler with unicode + whitespace edge cases. Uppercase
    # ASCII is excluded so the filler cannot assemble a pseudonym-shaped
    # or entity-looking token by accident (DE-274 exclusion documented
    # in strategies.py); the curated fragments above supply the
    # entity-laden content.
    st.text(
        alphabet=st.characters(
            exclude_categories=("Cs",),
            exclude_characters="".join(chr(c) for c in range(ord("A"), ord("Z") + 1)),
        ),
        max_size=20,
    ),
)

entity_laden_text = st.lists(_fragment, min_size=1, max_size=8).map("".join)


@pytest.fixture(scope="module")
def production_anonymizer() -> Anonymizer:
    """Real-Presidio anonymizer; spaCy loads once per module."""

    _reset_analyzer_engine_for_tests()
    return Anonymizer(analyzer=get_analyzer_engine())


@given(text=entity_laden_text)
@settings(suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_real_engine_round_trip_is_identity(production_anonymizer: Anonymizer, text: str) -> None:
    """rehydrate(pseudonymize(text)) == text under the real analyzer.

    Health-check note: ``production_anonymizer`` is module-scoped and
    read-only (pytest wraps it in a function-scoped request, which is
    what trips the check), so sharing it across examples is sound.
    """

    if PSEUDONYM_SHAPE.search(text):  # DE-274 exclusion; see strategies.py
        return
    mapper = PseudonymMapper()
    anonymized = production_anonymizer.pseudonymize_into(text, mapper)
    assert production_anonymizer.rehydrate(anonymized, mapper) == text


@given(email=_email)
@settings(suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_real_engine_never_forwards_a_generated_email(
    production_anonymizer: Anonymizer, email: str
) -> None:
    """No generated email address survives anonymization (partial DE-240).

    Presidio's EmailRecognizer is deterministic (regex-based), so unlike
    NER-recall assertions this is stable: every well-formed address must
    be pseudonymized out of the provider-bound text.
    """

    text = f"Please contact opposing counsel at {email} before the hearing."
    anonymized = production_anonymizer.pseudonymize_into(text, PseudonymMapper())
    assert email not in anonymized, anonymized
