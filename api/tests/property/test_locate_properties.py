"""Citation-locator offset property tests — DE-230.

Two locators feed verified citations:

* :func:`app.citation.extraction.locate_in_chunk` — RAG citations;
  offsets into the chunk content string.
* :func:`app.citation.caselaw.locate_passage` — caselaw blockquotes;
  offsets into the opinion text.

Offsets become highlight spans and audit-trail evidence, so the
contract under test is: whenever a locator returns ``(start, end)``,
the offsets are in-bounds, and — for the verbatim paths — the text at
those offsets IS the quote. A locator that returns plausible-but-wrong
offsets would attach a lawyer's citation to the wrong passage while
still "verifying" it.
"""

from __future__ import annotations

from hypothesis import assume, given, strategies as st

from app.citation.caselaw import locate_passage
from app.citation.extraction import locate_in_chunk

any_text = st.text(
    alphabet=st.characters(exclude_categories=("Cs",)),
    max_size=300,
)


@st.composite
def text_with_substring(draw: st.DrawFn) -> tuple[str, str]:
    """A document plus a (non-empty, non-whitespace) substring of it."""

    text = draw(any_text.filter(lambda t: t.strip() != ""))
    start = draw(st.integers(min_value=0, max_value=len(text) - 1))
    end = draw(st.integers(min_value=start + 1, max_value=len(text)))
    quote = text[start:end]
    assume(quote.strip() != "")
    return text, quote


@given(text_with_substring())
def test_locate_passage_offsets_return_the_passage(case: tuple[str, str]) -> None:
    """A passage genuinely present is found, and text[start:end] is the
    (stripped) passage — never an off-by-N span."""

    text, passage = case
    located = locate_passage(passage, text)
    assert located is not None
    start, end = located
    assert 0 <= start < end <= len(text)
    assert text[start:end] == passage.strip()


@given(
    text_with_substring(),
    st.text(alphabet=" \t\n", max_size=4),
    st.text(alphabet=" \t\n", max_size=4),
)
def test_locate_passage_ignores_surrounding_whitespace(
    case: tuple[str, str], leading: str, trailing: str
) -> None:
    """Whitespace padding around the model's quoted passage (markdown
    artifacts) never changes the located span."""

    text, passage = case
    assert locate_passage(leading + passage + trailing, text) == locate_passage(passage, text)


@given(passage=any_text, text=any_text)
def test_locate_passage_never_fabricates_a_span(passage: str, text: str) -> None:
    """Either the stripped passage is verbatim at the returned offsets,
    or the result is None. (Fail-closed: no fuzzy fallback here.)"""

    located = locate_passage(passage, text)
    if located is None:
        assert passage.strip() == "" or passage.strip() not in text
    else:
        start, end = located
        assert text[start:end] == passage.strip()


@given(text_with_substring())
def test_locate_in_chunk_exact_path_returns_the_quote(case: tuple[str, str]) -> None:
    """A quote lifted verbatim from the chunk locates to offsets whose
    slice equals the quote."""

    chunk, quote = case
    located = locate_in_chunk(quote, chunk)
    assert located is not None
    start, end = located
    assert 0 <= start < end <= len(chunk)
    assert chunk[start:end] == quote


@given(quote=any_text, chunk=any_text)
def test_locate_in_chunk_offsets_are_always_in_bounds(quote: str, chunk: str) -> None:
    """Exact or fuzzy, a non-None result is a valid span into the chunk.

    The fuzzy path (rapidfuzz partial-ratio alignment) may legitimately
    return offsets whose slice differs from the quote — that's Stage 2's
    job to score — but out-of-range offsets would crash or mis-highlight
    downstream consumers unconditionally.
    """

    located = locate_in_chunk(quote, chunk)
    if located is not None:
        start, end = located
        assert 0 <= start <= end <= len(chunk)
