# ruff: noqa: RUF001 — smart-quote literals are the test subject, not typos
"""Citation-normalization property tests — DE-230.

:func:`app.citation.normalization.normalize` is the canonicalizer both
sides of the Stage-2 tolerant-match comparison run through; the
verifier's docstring relies on idempotence so re-runs are symmetric.
The properties pin:

* canonical-form invariants (no smart quotes, no ``\\r``, single-space
  whitespace only, stripped ends) for both OCR modes;
* idempotence for the always-on layer (``was_ocrd=False``);
* comparison-insensitivity to whitespace layout and quote style — the
  differences Stage 2 exists to forgive must never change the
  canonical form.

KNOWN BUG (found by this suite; deliberately NOT fixed here): the
OCR layer (``was_ocrd=True``) violates the module's documented
idempotence contract — see
:func:`test_ocr_layer_idempotence_violation_is_pinned` below.
"""

from __future__ import annotations

import pytest
from hypothesis import given, strategies as st

from app.citation.normalization import normalize

# Arbitrary unicode minus surrogates (unencodable), plus a bias toward
# the characters the normalizer actually treats specially.
_special = "‘’“” \t\r\n '\"OolrnmM015"
any_text = st.text(
    alphabet=st.one_of(
        st.characters(exclude_categories=("Cs",)),
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


@given(text=any_text)
def test_always_on_layer_is_idempotent(text: str) -> None:
    """normalize(normalize(t)) == normalize(t) for the non-OCR path,
    per the module's documented contract."""

    once = normalize(text)
    assert normalize(once) == once


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


@pytest.mark.xfail(
    strict=True,
    reason=(
        "DE-230 property-test finding: the OCR layer is NOT idempotent, "
        "contradicting the module docstring ('The function is idempotent "
        "... for every input') that the Stage-2 verifier relies on. The "
        "l→1 and O→0 substitutions run in one pass each; a substitution "
        "can create a *new* digit adjacency that only the next pass "
        "rewrites: normalize('Ol5', was_ocrd=True) == 'O15' but "
        "normalize('O15', was_ocrd=True) == '015'. Left unfixed "
        "deliberately — fixing (e.g. iterating the OCR rules to a fixed "
        "point, or applying digit-adjacency rules right-to-left) changes "
        "verifier-visible canonical forms and needs a maintainer call on "
        "the desired semantics."
    ),
)
@pytest.mark.parametrize("text", ["Ol5", "ll5", "5lO", "Oll5"])
def test_ocr_layer_idempotence_violation_is_pinned(text: str) -> None:
    """Pinned counterexamples for the OCR-layer idempotence violation.

    strict xfail: if this ever XPASSes, the bug was fixed — delete this
    test and extend :func:`test_always_on_layer_is_idempotent` to cover
    ``was_ocrd=True``.
    """

    once = normalize(text, was_ocrd=True)
    assert normalize(once, was_ocrd=True) == once
