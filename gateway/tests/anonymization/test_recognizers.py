"""Custom legal recognizer tests — M2-B2.

Two recognizers extend Presidio's :class:`PatternRecognizer`:

* :class:`CaseNumberRecognizer` for case citations — federal reporter
  cites, state cites, and docket-number forms.
* :class:`MatterNumberRecognizer` for internal matter numbers —
  alpha-year-sequence, dotted, all-numeric.

Tests call ``recognizer.analyze(text, entities=[...])`` directly so
they don't depend on the AnalyzerEngine or its spaCy backbone. The
full-engine integration test lives separately in
``test_engine_integration.py`` (marked ``slow``).

Conservative posture: the plan §M2-B2 calls out a target false-
positive rate ≤ 5% on the M2-F2 acceptance corpus. We ship only
patterns with a recognizable reporter/docket/numbering structure;
bare case captions ("Smith v. Jones" without reporter) are not
matched because of the prose false-positive surface. The operator
guide documents how to add a deployment-specific recognizer when
captions matter for a particular matter type.
"""

from __future__ import annotations

import pytest
from presidio_analyzer import RecognizerResult

from app.anonymization.recognizers.case_number import CaseNumberRecognizer
from app.anonymization.recognizers.matter_number import MatterNumberRecognizer

# ---------------------------------------------------------------------------
# CaseNumberRecognizer — federal + state cites + docket numbers
# ---------------------------------------------------------------------------


def _entities(results: list[RecognizerResult]) -> list[str]:
    return [text_at(r) for r in results]


def text_at(result: RecognizerResult) -> str:
    # RecognizerResult doesn't carry the matched text — the caller has
    # to slice. Tests just check (start, end, score, entity_type).
    return f"[{result.start}:{result.end} score={result.score:.2f}]"


@pytest.fixture(scope="module")
def case_recognizer() -> CaseNumberRecognizer:
    return CaseNumberRecognizer()


# --- canonical federal cite ----------------------------------------------


@pytest.mark.unit
def test_case_recognizer_matches_canonical_federal_cite(
    case_recognizer: CaseNumberRecognizer,
) -> None:
    """Standard federal citation with court abbreviation and year."""

    text = "See Smith v. Jones, 123 F.3d 456 (9th Cir. 2024) for the holding."

    results = case_recognizer.analyze(text, entities=["CASE_NUMBER"])

    assert len(results) == 1
    match = results[0]
    assert match.entity_type == "CASE_NUMBER"
    assert match.score >= 0.85
    matched = text[match.start : match.end]
    assert "Smith v. Jones" in matched
    assert "123 F.3d 456" in matched
    assert "9th Cir. 2024" in matched


@pytest.mark.unit
def test_case_recognizer_matches_federal_cite_without_court(
    case_recognizer: CaseNumberRecognizer,
) -> None:
    """Federal cite with year-only parenthetical (no court abbreviation)."""

    text = "Per Smith v. Jones, 123 F.3d 456 (2024), the rule applies."

    results = case_recognizer.analyze(text, entities=["CASE_NUMBER"])
    assert len(results) >= 1


@pytest.mark.unit
def test_case_recognizer_matches_in_re_form(
    case_recognizer: CaseNumberRecognizer,
) -> None:
    """``In re X, vol Reporter page (Court Year)`` — the bankruptcy / probate idiom."""

    text = "In re Smith, 567 F.Supp.2d 890 (S.D.N.Y. 2023) is on point."

    results = case_recognizer.analyze(text, entities=["CASE_NUMBER"])
    assert len(results) >= 1


@pytest.mark.unit
def test_case_recognizer_matches_united_states_v(
    case_recognizer: CaseNumberRecognizer,
) -> None:
    """``United States v. X`` — common government-party caption."""

    text = "See United States v. Smith, 999 U.S. 100 (2023)."

    results = case_recognizer.analyze(text, entities=["CASE_NUMBER"])
    assert len(results) >= 1


# --- multiple reporters in one passage -----------------------------------


@pytest.mark.unit
def test_case_recognizer_matches_each_cite_in_passage(
    case_recognizer: CaseNumberRecognizer,
) -> None:
    text = (
        "First, see Smith v. Jones, 123 F.3d 456 (9th Cir. 2024). "
        "Then compare Doe v. Roe, 567 F.Supp.2d 890 (S.D.N.Y. 2023)."
    )

    results = case_recognizer.analyze(text, entities=["CASE_NUMBER"])
    assert len(results) == 2


# --- docket-number form --------------------------------------------------


@pytest.mark.unit
def test_case_recognizer_matches_federal_docket_number(
    case_recognizer: CaseNumberRecognizer,
) -> None:
    """``Case No. 1:24-cv-00123`` — federal-court docket form."""

    text = "Filed under Case No. 1:24-cv-00123 in the Southern District."

    results = case_recognizer.analyze(text, entities=["CASE_NUMBER"])
    assert len(results) >= 1
    match = results[0]
    matched = text[match.start : match.end]
    assert "1:24-cv-00123" in matched


@pytest.mark.unit
def test_case_recognizer_matches_short_docket(
    case_recognizer: CaseNumberRecognizer,
) -> None:
    """Shorter docket form: ``No. 24-1234`` (appellate)."""

    text = "On appeal, see No. 24-1234, pending review."

    results = case_recognizer.analyze(text, entities=["CASE_NUMBER"])
    assert len(results) >= 1


# --- negatives -----------------------------------------------------------


@pytest.mark.unit
def test_case_recognizer_does_not_match_bare_v_separator(
    case_recognizer: CaseNumberRecognizer,
) -> None:
    """No reporter or docket structure → no match (false-positive guard)."""

    text = "The dispute pits John v. the system in colloquial terms."

    results = case_recognizer.analyze(text, entities=["CASE_NUMBER"])
    assert results == []


@pytest.mark.unit
def test_case_recognizer_does_not_match_random_numbers(
    case_recognizer: CaseNumberRecognizer,
) -> None:
    """Numbers that look like ``volume page`` but lack reporter context."""

    text = "Pages 123 456 are missing from the exhibit binder."

    results = case_recognizer.analyze(text, entities=["CASE_NUMBER"])
    assert results == []


@pytest.mark.unit
def test_case_recognizer_does_not_match_ordinary_prose(
    case_recognizer: CaseNumberRecognizer,
) -> None:
    """A paragraph of plain prose has no false positives."""

    text = (
        "This Agreement memorializes the parties' understanding regarding "
        "the project, including timing, deliverables, and payment terms."
    )

    results = case_recognizer.analyze(text, entities=["CASE_NUMBER"])
    assert results == []


# ---------------------------------------------------------------------------
# MatterNumberRecognizer — internal matter numbering conventions
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def matter_recognizer() -> MatterNumberRecognizer:
    return MatterNumberRecognizer()


# --- alpha-year-sequence -------------------------------------------------


@pytest.mark.unit
def test_matter_recognizer_matches_alpha_year_sequence(
    matter_recognizer: MatterNumberRecognizer,
) -> None:
    """``LQ-2026-0042`` — alpha prefix + year + zero-padded sequence."""

    text = "Internal matter LQ-2026-0042 covers the dispute."

    results = matter_recognizer.analyze(text, entities=["MATTER_NUMBER"])
    assert len(results) >= 1
    match = results[0]
    matched = text[match.start : match.end]
    assert "LQ-2026-0042" in matched


@pytest.mark.unit
def test_matter_recognizer_matches_multi_letter_prefix(
    matter_recognizer: MatterNumberRecognizer,
) -> None:
    text = "Per matter ABCD-2024-1, the engagement closed."

    results = matter_recognizer.analyze(text, entities=["MATTER_NUMBER"])
    assert len(results) >= 1


# --- dotted form ---------------------------------------------------------


@pytest.mark.unit
def test_matter_recognizer_matches_dotted_year_sequence(
    matter_recognizer: MatterNumberRecognizer,
) -> None:
    """``2026.0042`` — dotted year-sequence form."""

    text = "Matter 2026.0042 is currently active."

    results = matter_recognizer.analyze(text, entities=["MATTER_NUMBER"])
    assert len(results) >= 1
    matched = text[results[0].start : results[0].end]
    assert "2026.0042" in matched


# --- negatives -----------------------------------------------------------


@pytest.mark.unit
def test_matter_recognizer_does_not_match_iso_date(
    matter_recognizer: MatterNumberRecognizer,
) -> None:
    """An ISO date (``2024-05-16``) is not a matter number."""

    text = "On 2024-05-16, the parties met."

    results = matter_recognizer.analyze(text, entities=["MATTER_NUMBER"])
    assert results == []


@pytest.mark.unit
def test_matter_recognizer_does_not_match_phone(
    matter_recognizer: MatterNumberRecognizer,
) -> None:
    """A phone-shaped number is not a matter number."""

    text = "Contact 555-1234 for status."

    results = matter_recognizer.analyze(text, entities=["MATTER_NUMBER"])
    assert results == []


@pytest.mark.unit
def test_matter_recognizer_does_not_match_zip_plus_four(
    matter_recognizer: MatterNumberRecognizer,
) -> None:
    """ZIP+4 is not a matter number."""

    text = "Mailing address: 90210-1234."

    results = matter_recognizer.analyze(text, entities=["MATTER_NUMBER"])
    assert results == []


@pytest.mark.unit
def test_matter_recognizer_does_not_match_currency(
    matter_recognizer: MatterNumberRecognizer,
) -> None:
    """A dollar amount is not a matter number."""

    text = "The settlement was $1,200,000.00 net."

    results = matter_recognizer.analyze(text, entities=["MATTER_NUMBER"])
    assert results == []
