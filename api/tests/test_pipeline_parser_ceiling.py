"""Resource-ceiling tests for the PDF parser (decompression-bomb guard).

Pen-test 2026-09-25 finding ingest#F1 (HIGH): the only limit on the parse path
was the 100 MB *upload* cap. A small compressed PDF could expand into a huge
extracted-text string, an oversized normalized_content row, and tens of
thousands of chunk/embedding operations. ``parse_pdf`` now enforces a page-count
and character ceiling and raises :class:`ParserTooLarge`.
"""

from __future__ import annotations

import pytest

from app.pipeline.parsers import ParserTooLarge, parse_pdf

fitz = pytest.importorskip("fitz", reason="PyMuPDF not installed")


def _make_pdf(pages: int, text_per_page: str = "page text") -> bytes:
    doc = fitz.open()
    for _ in range(pages):
        page = doc.new_page()
        page.insert_text((50, 72), text_per_page, fontsize=11)
    out = doc.tobytes()
    doc.close()
    return out


@pytest.mark.unit
def test_page_count_ceiling_refuses() -> None:
    pdf = _make_pdf(6)
    with pytest.raises(ParserTooLarge, match="pages"):
        parse_pdf(pdf, run_docling=False, max_pages=5)


@pytest.mark.unit
def test_char_ceiling_refuses() -> None:
    # A single page with a lot of text, capped by a tiny character ceiling.
    pdf = _make_pdf(1, text_per_page="lorem ipsum dolor sit amet " * 50)
    with pytest.raises(ParserTooLarge, match="characters"):
        parse_pdf(pdf, run_docling=False, max_chars=10)


@pytest.mark.unit
def test_within_limits_parses() -> None:
    pdf = _make_pdf(3)
    parsed = parse_pdf(pdf, run_docling=False, max_pages=5, max_chars=1_000_000)
    assert parsed.page_count == 3
    assert parsed.canonical_text


@pytest.mark.unit
def test_no_limits_preserves_legacy_behavior() -> None:
    # Defaults (None) impose no ceiling — backward compatible.
    pdf = _make_pdf(6)
    parsed = parse_pdf(pdf, run_docling=False)
    assert parsed.page_count == 6
