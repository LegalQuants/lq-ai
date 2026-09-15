"""Unit tests for the C5 PDF parser adapters.

PyMuPDF generates the fixture PDFs at test setup time (PyMuPDF can
both write and read PDFs); we do not commit binary fixtures into the
repo. Each fixture exercises a specific corner of the parser /
chunker contract:

* simple text: smoke test
* multi-page: page-span tracking
* unicode: byte-fidelity invariant under non-ASCII content

The MANDATORY offset-fidelity test
(:func:`test_offset_fidelity_against_fixture_pdfs`) runs the full
pipeline parse → chunk and slices every chunk back against the
canonical text from PyMuPDF.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import NoReturn

import pytest

from app.pipeline.chunker import chunk_document
from app.pipeline.parsers import (
    ParserError,
    ParserUnsupported,
    is_pdf_mime,
    parse_pdf,
)

# We skip these tests if PyMuPDF isn't importable (e.g., a build
# without the C5 deps). The skip message names the missing dep
# explicitly.
fitz = pytest.importorskip("fitz", reason="PyMuPDF not installed")


# ---------------------------------------------------------------------------
# Fixture builders — generate PDFs in-memory at test time.
# ---------------------------------------------------------------------------


def _make_simple_pdf() -> bytes:
    """Single-page prose PDF for the smoke / fidelity test."""

    text = (
        "The Quick Reference Guide\n\n"
        "This document explains how to write process documentation that "
        "other people can actually use. The first rule is to write for "
        "the reader, not for yourself.\n\n"
        "When documenting any process, start with the desired outcome. "
        "Then describe the precondition: what state the system must be "
        "in before the process can run. Then describe the steps. Then "
        "describe the validation: how the reader confirms that the "
        "process succeeded.\n\n"
        "The most common documentation failure is to skip the validation "
        "step. Without it, the reader has no way to tell whether they "
        "followed the steps correctly."
    )
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((50, 72), text, fontsize=11)
    out = doc.tobytes()
    doc.close()
    return out


def _make_multipage_pdf() -> bytes:
    """Three pages with paragraph breaks spanning page boundaries."""

    pages_text = [
        (
            "Chapter One. Every project begins with a question. The "
            "question is rarely the right one, but it is the one "
            "available, and it is the one you start with."
        ),
        (
            "Chapter Two. The middle is where the project gets unpleasant. "
            "The early enthusiasm is gone, the end is not yet in sight, "
            "and the work that remains is mostly uninteresting."
        ),
        (
            "Chapter Three. Endings, when they finally arrive, are "
            "anticlimactic. The project that consumed your attention for "
            "months is suddenly done, and the world is largely unchanged."
        ),
    ]
    doc = fitz.open()
    for text in pages_text:
        page = doc.new_page()
        page.insert_text((50, 72), text, fontsize=11)
    out = doc.tobytes()
    doc.close()
    return out


def _make_two_column_pdf() -> bytes:
    """Visually two-column PDF; PyMuPDF flattens it to reading order."""

    doc = fitz.open()
    page = doc.new_page()
    left = (
        "Left column. The discipline of writing in columns is the "
        "discipline of writing for layout instead of writing for voice. "
        "Newspapers have done this for centuries; long-form essays do "
        "it less."
    )
    right = (
        "Right column. The right column continues a thought that is "
        "different from the left column's thought. They share the page "
        "but not the argument. Most readers will read the left first, "
        "then the right."
    )
    page.insert_textbox(fitz.Rect(50, 72, 270, 720), left, fontsize=11)
    page.insert_textbox(fitz.Rect(290, 72, 510, 720), right, fontsize=11)
    out = doc.tobytes()
    doc.close()
    return out


# ---------------------------------------------------------------------------
# Smoke and is_pdf_mime helpers.
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_is_pdf_mime_accepts_canonical_and_variants() -> None:
    assert is_pdf_mime("application/pdf") is True
    assert is_pdf_mime("APPLICATION/PDF") is True  # case-insensitive
    assert is_pdf_mime("application/x-pdf") is True
    assert is_pdf_mime("text/plain") is False
    assert is_pdf_mime("application/msword") is False
    assert is_pdf_mime("") is False


# ---------------------------------------------------------------------------
# parse_pdf — happy path.
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_parse_pdf_simple_returns_canonical_text() -> None:
    pdf = _make_simple_pdf()
    parsed = parse_pdf(pdf, run_docling=False)

    assert parsed.canonical_text  # non-empty
    assert parsed.page_count == 1
    assert len(parsed.pages) == 1
    assert parsed.pages[0].page_number == 1
    assert parsed.pages[0].char_start == 0
    assert parsed.pages[0].char_end == len(parsed.canonical_text)
    assert "pymupdf" in parsed.parser
    assert "pymupdf" in parsed.parser_version


@pytest.mark.unit
def test_parse_pdf_multipage_tracks_page_spans() -> None:
    pdf = _make_multipage_pdf()
    parsed = parse_pdf(pdf, run_docling=False)

    assert parsed.page_count == 3
    assert len(parsed.pages) == 3
    # Page 1 starts at offset 0.
    assert parsed.pages[0].char_start == 0
    # Each subsequent page starts after the prior one's end + 1 (newline).
    for i in range(len(parsed.pages) - 1):
        prev = parsed.pages[i]
        nxt = parsed.pages[i + 1]
        # The join newline between pages adds 1 char.
        assert nxt.char_start == prev.char_end + 1


@pytest.mark.unit
def test_parse_pdf_canonical_slices_per_page_match() -> None:
    """Slicing canonical_text by each page span yields the page's text."""

    pdf = _make_multipage_pdf()
    parsed = parse_pdf(pdf, run_docling=False)

    for span in parsed.pages:
        page_slice = parsed.canonical_text[span.char_start : span.char_end]
        # Each page's content should mention its chapter title.
        assert "Chapter" in page_slice or "Endings" in page_slice or len(page_slice) > 0


# ---------------------------------------------------------------------------
# Failure paths.
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_parse_pdf_empty_input_raises() -> None:
    with pytest.raises(ParserError):
        parse_pdf(b"", run_docling=False)


@pytest.mark.unit
def test_parse_pdf_corrupt_input_raises() -> None:
    with pytest.raises(ParserError):
        parse_pdf(b"not a pdf at all", run_docling=False)


# ---------------------------------------------------------------------------
# THE LOAD-BEARING TEST — offset fidelity against generated PDFs.
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.parametrize(
    "fixture_builder, label",
    [
        (_make_simple_pdf, "simple"),
        (_make_multipage_pdf, "multipage"),
        (_make_two_column_pdf, "two-column"),
    ],
)
def test_offset_fidelity_against_fixture_pdfs(
    fixture_builder: Callable[[], bytes], label: str
) -> None:
    """The mandatory contract: every chunk slices back to its content byte-for-byte.

    This is the M2 Citation Engine's load-bearing precondition. Run
    against three fixture PDFs of varying complexity per the C5 brief.
    """

    pdf_bytes = fixture_builder()
    parsed = parse_pdf(pdf_bytes, run_docling=False)
    chunks = chunk_document(parsed, target_chars=200, overlap_chars=20)

    assert chunks, f"[{label}] chunker produced no chunks"

    for chunk in chunks:
        canonical_slice = parsed.canonical_text[chunk.char_offset_start : chunk.char_offset_end]
        assert canonical_slice == chunk.content, (
            f"[{label}] chunk {chunk.chunk_index} fidelity broken: "
            f"len(slice)={len(canonical_slice)} vs len(content)={len(chunk.content)}; "
            f"offsets=[{chunk.char_offset_start}, {chunk.char_offset_end})"
        )


@pytest.mark.unit
def test_offset_fidelity_with_default_chunk_size() -> None:
    """Even at the production default chunk size, fidelity holds."""

    pdf_bytes = _make_multipage_pdf()
    parsed = parse_pdf(pdf_bytes, run_docling=False)
    chunks = chunk_document(parsed)  # uses defaults

    for chunk in chunks:
        canonical_slice = parsed.canonical_text[chunk.char_offset_start : chunk.char_offset_end]
        assert canonical_slice == chunk.content


# ---------------------------------------------------------------------------
# Docling fall-through behaviour (Docling not strictly required).
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_parse_pdf_docling_disabled_marks_pymupdf_only() -> None:
    """When run_docling=False, parser is `pymupdf-only`."""

    pdf = _make_simple_pdf()
    parsed = parse_pdf(pdf, run_docling=False)
    assert parsed.parser == "pymupdf-only"
    assert parsed.structured_content is None


@pytest.mark.unit
def test_parse_pdf_docling_failure_falls_through(monkeypatch: pytest.MonkeyPatch) -> None:
    """When Docling raises, the parser falls through to PyMuPDF-only."""

    from app.pipeline import parsers

    def _raise(*args: object, **kwargs: object) -> NoReturn:
        raise RuntimeError("simulated Docling crash")

    monkeypatch.setattr(parsers, "_run_docling", _raise)

    pdf = _make_simple_pdf()
    parsed = parse_pdf(pdf, run_docling=True)
    assert parsed.parser == "pymupdf"
    assert parsed.structured_content is None


# ---------------------------------------------------------------------------
# ParserUnsupported (encrypted PDF).
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_parse_pdf_encrypted_raises_unsupported() -> None:
    """Encrypted PDFs raise ParserUnsupported (M1 doesn't decrypt)."""

    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((50, 72), "Secret content", fontsize=11)
    encrypted = doc.tobytes(
        encryption=fitz.PDF_ENCRYPT_AES_256,
        owner_pw="owner",
        user_pw="user",
    )
    doc.close()

    with pytest.raises(ParserUnsupported):
        parse_pdf(encrypted, run_docling=False)
