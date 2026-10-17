# ruff: noqa: RUF001 — smart-quote literals are the test subject, not typos
"""Citation-normalization property tests — DE-230.

:func:`app.citation.normalization.normalize` is the canonicalizer both
sides of the Stage-2 tolerant-match comparison run through; the
verifier's docstring relies on idempotence so re-runs are symmetric.
The properties pin:

* canonical-form invariants (no smart quotes, no ``\\r``, single-space
  whitespace only, stripped ends) for both OCR modes;
* idempotence for both the always-on layer (``was_ocrd=False``) and
  the OCR layer (``was_ocrd=True``) — fixed by DE-230;
* comparison-insensitivity to whitespace layout and quote style — the
  differences Stage 2 exists to forgive must never change the
  canonical form.
"""

from __future__ import annotations

from typing import Literal

import pytest
from hypothesis import given, strategies as st

from app.citation.normalization import normalize

# Arbitrary unicode minus surrogates (unencodable), plus a bias toward
# the characters the normalizer actually treats specially.
_special = "‘’“” \t\r\n '\"OolrnmM015"
_SURROGATE_CATEGORY: Literal["Cs"] = "Cs"
any_text = st.text(
    alphabet=st.one_of(
        st.characters(exclude_categories=(_SURROGATE_CATEGORY,)),
        st.sampled_from(_special),
    ),
    max_size=200,
)

_SMART_QUOTES = "‘’“”"


@given(text=any_text, was_ocrd=st.booleans())
def test_normalized_output_is_canonical_form(text: str, was_ocrd: bool) -> None:
    """Output carries no smart quotes, no CR, no runs/tabs/newlines —
    the only whitespace is single ASCII spaces, and ends are stripped."""

    out = normalize(text, was_ocrd=was_ocrd)
    assert not set(out) & set(_SMART_QUOTES)
    assert "\r" not in out
    assert "  " not in out
    for ch in out:
        assert not (ch.isspace() and ch != " "), repr(ch)
    assert out == out.strip()


@given(text=any_text, was_ocrd=st.booleans())
def test_normalization_is_idempotent(text: str, was_ocrd: bool) -> None:
    """normalize(normalize(t)) == normalize(t) for both the always-on
    and the OCR layers, per the module's documented contract.

    This property now covers ``was_ocrd=True`` — the fixed-point loop
    introduced in DE-230 guarantees convergence on the first call.
    """

    once = normalize(text, was_ocrd=was_ocrd)
    assert normalize(once, was_ocrd=was_ocrd) == once


@given(text=any_text)
def test_whitespace_layout_never_changes_canonical_form(text: str) -> None:
    """Doubling spaces / swapping newlines for spaces — the whitespace
    drift Stage 2 must forgive — yields the identical canonical form."""

    assert normalize(text.replace(" ", "  ")) == normalize(text)
    assert normalize(text.replace(" ", "\n")) == normalize(text)


@given(text=any_text)
def test_quote_style_never_changes_canonical_form(text: str) -> None:
    """Typographic vs straight quotes yield the identical canonical form."""

    curled = text.replace("'", "’").replace('"', "“")
    assert normalize(curled) == normalize(text)


@pytest.mark.parametrize(
    ("text", "canonical"),
    [
        # Basic single confusion
        ("Ol5", "015"),
        ("ll5", "115"),
        ("5lO", "510"),
        # Chained confusion — the key case fixed by DE-230
        # Old single-pass: "Oll5" -> "Ol15" -> "O115" (3 passes needed)
        # Fixed: reaches "0115" in one normalize() call
        ("Oll5", "0115"),
        # Negative cases: letters not adjacent to digits are preserved
        ("Ollx", "Ollx"),
        ("Office", "Office"),
        ("liability", "liability"),
    ],
)
def test_ocr_layer_canonical_outputs(text: str, canonical: str) -> None:
    """The OCR layer reaches the fixed-point canonical form in one normalize() call.

    Covers the DE-230 regression: chained OCR confusions (e.g. ``Oll5``) must
    resolve to the fully-substituted form (``0115``) in a single call, not
    require repeated calls.
    """

    assert normalize(text, was_ocrd=True) == canonical
