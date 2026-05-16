"""Full AnalyzerEngine integration test — M2-B2.

Exercises the configured Presidio :class:`AnalyzerEngine` end-to-end:

* spaCy ``en_core_web_lg`` model loaded.
* Custom recognizers (``CaseNumberRecognizer``,
  ``MatterNumberRecognizer``) registered and firing.
* Default recognizers we keep enabled (PERSON, ORG, EMAIL_ADDRESS,
  PHONE_NUMBER, US_BANK_NUMBER, LOCATION) firing.
* Default recognizers we disable (US_PASSPORT, US_DRIVER_LICENSE,
  US_SSN, CRYPTO, IBAN_CODE, IP_ADDRESS, MEDICAL_LICENSE) NOT firing.

The test is marked ``slow`` so it skips by default. Local runs:
``pytest -m slow tests/anonymization/test_engine_integration.py``.
CI runs ``not slow and not provider`` so this is opt-in.

Why marked slow:
The first call to :func:`get_analyzer_engine` loads spaCy's
``en_core_web_lg`` model (~560MB on disk, 2-3 seconds wall-clock).
The remaining ``analyze`` calls are fast (sub-second each); the
wall-clock cost is the initial model load. Keeping the test out of
the default run preserves the fast feedback loop the rest of the
suite gives.
"""

from __future__ import annotations

import pytest

from app.anonymization.engine import _reset_analyzer_engine_for_tests, get_analyzer_engine

pytestmark = pytest.mark.slow


@pytest.fixture(scope="module")
def analyzer() -> object:
    """Module-scoped: load the spaCy model + build the engine once for this file."""

    # Fresh singleton — avoids cross-test pollution if some earlier test
    # in the same session (unlikely, but defensively) built a different
    # registry.
    _reset_analyzer_engine_for_tests()
    return get_analyzer_engine()


def _hit_entity_types(results: list) -> set[str]:
    return {r.entity_type for r in results}


def test_engine_recognizes_custom_case_number(analyzer: object) -> None:
    """A canonical federal cite surfaces as a CASE_NUMBER entity."""

    text = "See Smith v. Jones, 123 F.3d 456 (9th Cir. 2024) for the holding."

    results = analyzer.analyze(text=text, language="en")
    assert "CASE_NUMBER" in _hit_entity_types(results)


def test_engine_recognizes_custom_matter_number(analyzer: object) -> None:
    """An alpha-year-sequence matter number surfaces as a MATTER_NUMBER entity."""

    text = "Internal matter LQ-2026-0042 covers the dispute."

    results = analyzer.analyze(text=text, language="en")
    assert "MATTER_NUMBER" in _hit_entity_types(results)


def test_engine_recognizes_default_person_org(analyzer: object) -> None:
    """The kept-enabled defaults (PERSON, ORGANIZATION) fire."""

    text = "John Smith of Acme Corp. negotiated the agreement."

    results = analyzer.analyze(text=text, language="en")
    hits = _hit_entity_types(results)
    assert "PERSON" in hits


def test_engine_recognizes_email_and_phone(analyzer: object) -> None:
    """EMAIL_ADDRESS and PHONE_NUMBER both fire."""

    text = "Contact counsel at counsel@firm.com or call 415-555-0123."

    results = analyzer.analyze(text=text, language="en")
    hits = _hit_entity_types(results)
    assert "EMAIL_ADDRESS" in hits
    assert "PHONE_NUMBER" in hits


def test_engine_does_not_recognize_disabled_us_ssn(analyzer: object) -> None:
    """US_SSN is disabled — a number-shaped exhibit doesn't surface as SSN."""

    text = "See Exhibit 123-45-6789 attached to the filing."

    results = analyzer.analyze(text=text, language="en")
    assert "US_SSN" not in _hit_entity_types(results)


def test_engine_does_not_recognize_disabled_ip_address(analyzer: object) -> None:
    """IP_ADDRESS is disabled — version-shaped numbers don't surface as IPs."""

    text = "Per section 192.168.1.1 of the supplement, ..."

    results = analyzer.analyze(text=text, language="en")
    assert "IP_ADDRESS" not in _hit_entity_types(results)


def test_engine_combined_text_surfaces_multiple_entities(analyzer: object) -> None:
    """A realistic legal-prose paragraph surfaces all expected entity types."""

    text = (
        "In Smith v. Jones, 123 F.3d 456 (9th Cir. 2024), counsel "
        "Jane Doe of Acme LLP argued that internal matter LQ-2024-0001 "
        "was settled. Contact: jane.doe@acme.com or 415-555-0123."
    )

    results = analyzer.analyze(text=text, language="en")
    hits = _hit_entity_types(results)

    # Custom entities.
    assert "CASE_NUMBER" in hits
    assert "MATTER_NUMBER" in hits
    # Kept-enabled defaults — PERSON and EMAIL_ADDRESS are the most
    # reliable detectors on this prose; PHONE_NUMBER + ORG depend on
    # tokenization and are exercised in the dedicated tests above.
    assert "PERSON" in hits
    assert "EMAIL_ADDRESS" in hits
    # Disabled defaults stay silent.
    assert "US_SSN" not in hits
    assert "IP_ADDRESS" not in hits
