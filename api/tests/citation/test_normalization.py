# ruff: noqa: RUF001
"""Citation Engine — normalize() tests for Stage 2 tolerant-match.

``normalize(text, *, was_ocrd=False)`` is the comparison-time
normalization the Stage 2 verifier applies to both source-at-offsets
and the model's quoted text before computing a fuzzy-ratio.

Two layers:

* **Always-on:** whitespace collapse, ``\\r\\n`` → ``\\n``, leading/
  trailing strip, smart-quote → straight-quote (for both double and
  single).
* **OCR-conditional** (``was_ocrd=True`` only): replace common OCR
  confusions (``rn`` → ``m`` mid-word, ``cl`` → ``d`` in word
  contexts, ``O`` ↔ ``0`` / ``l`` ↔ ``1`` adjacent to digits).

The OCR substitutions are conservative — applied only when the source
went through OCR (``documents.was_ocrd``). Documents with reliable
PyMuPDF extraction skip them so the function doesn't introduce
false-positive matches against clean text.
"""

from __future__ import annotations

import pytest

from app.citation.normalization import normalize

# ---------------------------------------------------------------------------
# Always-on rules: whitespace + smart-quote normalization
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_normalize_collapses_runs_of_whitespace() -> None:
    assert normalize("the  quick   brown\tfox") == "the quick brown fox"


@pytest.mark.unit
def test_normalize_translates_crlf_to_lf() -> None:
    # Newlines themselves are whitespace and collapse to a single space —
    # the load-bearing claim is just that we don't double-substitute on
    # CRLF (which would leave a stray ``\\r`` behind).
    assert normalize("first line\r\nsecond line") == "first line second line"


@pytest.mark.unit
def test_normalize_strips_leading_and_trailing_whitespace() -> None:
    assert normalize("   the agreement  ") == "the agreement"


@pytest.mark.unit
def test_normalize_translates_smart_double_quotes_to_straight() -> None:
    # Both opening and closing curly double quotes map to ``"``.
    assert normalize("“the agreement”") == '"the agreement"'


@pytest.mark.unit
def test_normalize_translates_smart_single_quotes_to_straight() -> None:
    # Both opening and closing curly single quotes map to ``'``.
    assert normalize("‘party A’") == "'party A'"


@pytest.mark.unit
def test_normalize_idempotent() -> None:
    """Running twice yields the same string — the verifier relies on this."""

    text = "the  quick “brown” fox  "
    once = normalize(text)
    twice = normalize(once)
    assert once == twice


# ---------------------------------------------------------------------------
# OCR-conditional rules: applied only when was_ocrd=True
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_normalize_leaves_ocr_artefacts_when_was_ocrd_false() -> None:
    """Clean-extraction documents never see OCR substitutions."""

    # 'modern' is sometimes OCR'd as 'modem' or 'modern' → no substitution
    # when the document didn't go through OCR.
    assert normalize("the modern agreement", was_ocrd=False) == "the modern agreement"


@pytest.mark.unit
def test_normalize_rn_to_m_mid_word_when_was_ocrd_true() -> None:
    """``rn`` is a known OCR confusion for ``m`` — collapse mid-word only."""

    # mid-word: 'modem' OCR'd as 'modern'? Actual common confusion is the
    # other direction (``m`` mis-OCR'd as ``rn``). We canonicalize ``rn``
    # → ``m`` so the verifier matches either spelling against the chunk.
    assert normalize("modern agreement", was_ocrd=True) == "modem agreement"


@pytest.mark.unit
def test_normalize_rn_to_m_skips_word_start() -> None:
    """``rn`` at word START is preserved — no real OCR confusion there."""

    assert normalize("rnage agreement", was_ocrd=True) == "rnage agreement"


@pytest.mark.unit
def test_normalize_rn_to_m_substitutes_word_final() -> None:
    """Canonical OCR case: word-final ``rn`` (preceded by word char) → ``m``.

    Accepts false positives like ``turn`` → ``tum`` to catch the common
    ``modern`` ↔ ``modem`` family. The verifier's 95-threshold absorbs
    single-token noise.
    """

    assert normalize("the burning ship turn", was_ocrd=True) == "the buming ship tum"


@pytest.mark.unit
def test_normalize_O_to_0_adjacent_to_digits_when_was_ocrd_true() -> None:
    """``O`` ↔ ``0`` confusion: substitute only when adjacent to a digit."""

    assert normalize("section O5", was_ocrd=True) == "section 05"
    assert normalize("amount $1O0", was_ocrd=True) == "amount $100"


@pytest.mark.unit
def test_normalize_O_not_substituted_in_pure_text() -> None:
    """Conservative: O in pure text (no adjacent digit) is preserved."""

    assert normalize("Office of the Counsel", was_ocrd=True) == "Office of the Counsel"


@pytest.mark.unit
def test_normalize_l_to_1_adjacent_to_digits_when_was_ocrd_true() -> None:
    """``l`` ↔ ``1`` confusion: substitute only when adjacent to a digit."""

    assert normalize("section l5", was_ocrd=True) == "section 15"
    assert normalize("section 5l", was_ocrd=True) == "section 51"


@pytest.mark.unit
def test_normalize_l_not_substituted_in_pure_text() -> None:
    """Conservative: l in pure text (no adjacent digit) is preserved."""

    assert normalize("clause of liability", was_ocrd=True) == "clause of liability"


@pytest.mark.unit
def test_normalize_combined_rules() -> None:
    """A realistic citation with smart quotes + whitespace + OCR artefacts."""

    raw = "  “The modern   provision” is in section l0  "
    expected = '"The modem provision" is in section 10'
    assert normalize(raw, was_ocrd=True) == expected
