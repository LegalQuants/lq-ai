"""Unit tests for the plain-text / Markdown parser (``parse_text``).

Deliberately **independent of PyMuPDF** — unlike ``test_pipeline_parsers.py``
there is no ``importorskip("fitz")`` here, because the whole point of the
text branch is that it needs no parsing library. These tests run on a bare
Python + pytest install.

The load-bearing test is :func:`test_offset_fidelity_text`: it runs the full
``parse_text → chunk_document`` path and slices every chunk back against the
canonical text byte-for-byte. That invariant is the Citation Engine's
precondition — for text it holds *exactly*, because the canonical text is the
verbatim decoded upload.
"""

from __future__ import annotations

import pytest

from app.pipeline.chunker import chunk_document
from app.pipeline.parsers import (
    PageSpan,
    ParsedDocument,
    ParserDecodeError,
    ParserError,
    is_text_filename,
    is_text_mime,
    parse_text,
)

# ---------------------------------------------------------------------------
# is_text_mime
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_is_text_mime_accepts_text_and_markdown() -> None:
    assert is_text_mime("text/plain") is True
    assert is_text_mime("text/markdown") is True
    assert is_text_mime("text/x-markdown") is True
    # Charset parameters are common on text uploads; the bare type matches.
    assert is_text_mime("text/plain; charset=utf-8") is True
    assert is_text_mime("TEXT/MARKDOWN; charset=UTF-8") is True


@pytest.mark.unit
def test_is_text_mime_rejects_non_text() -> None:
    assert is_text_mime("application/pdf") is False
    assert is_text_mime("application/octet-stream") is False
    assert (
        is_text_mime("application/vnd.openxmlformats-officedocument.wordprocessingml.document")
        is False
    )
    assert is_text_mime("") is False


@pytest.mark.unit
def test_is_text_filename_extension_fallback() -> None:
    """Browsers/OSes often send .md as application/octet-stream or empty, so the
    extension is the dependable routing signal (parse_text still validates bytes)."""
    assert is_text_filename("notes.md") is True
    assert is_text_filename("NOTES.MD") is True
    assert is_text_filename("spec.markdown") is True
    assert is_text_filename("memo.txt") is True
    assert is_text_filename("/path/to/a.MD") is True
    # Not text extensions:
    assert is_text_filename("contract.pdf") is False
    assert is_text_filename("brief.docx") is False
    assert is_text_filename("archive") is False
    assert is_text_filename("image.md.png") is False


# ---------------------------------------------------------------------------
# parse_text — happy path + verbatim store
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.parametrize(
    "raw, label",
    [
        (b"Plain text. " * 200, "plain"),
        (
            (
                b"# Heading\n\n"
                b"Clause 1. The party **shall** pay within 30 days.\n\n"
                b"| term | value |\n|---|---|\n| fee | 100 |\n"
            )
            * 30,
            "markdown",
        ),
    ],
)
def test_parse_text_stores_verbatim_single_page(raw: bytes, label: str) -> None:
    parsed = parse_text(raw)

    assert isinstance(parsed, ParsedDocument)
    # Verbatim: the canonical text is exactly the decoded upload — no
    # rendering, no normalization. This is what makes exact-match citations
    # resolve against the source the user uploaded.
    assert parsed.canonical_text == raw.decode("utf-8"), f"[{label}] not verbatim"
    assert parsed.parser == "plain-text"
    assert parsed.parser_version == "1"
    assert parsed.structured_content is None
    # Text has no pagination — a single synthetic page over the whole stream.
    assert parsed.page_count == 1
    assert parsed.pages == [
        PageSpan(page_number=1, char_start=0, char_end=len(parsed.canonical_text))
    ]


@pytest.mark.unit
def test_parse_text_drops_utf8_bom() -> None:
    """A leading UTF-8 BOM is an encoding artifact, not content — drop it."""

    parsed = parse_text("﻿hello".encode())
    assert parsed.canonical_text == "hello"
    assert parsed.pages[0].char_end == len("hello")


@pytest.mark.unit
def test_parse_text_unicode_byte_fidelity() -> None:
    """Non-ASCII content round-trips exactly, and the page span covers it."""

    source = "Cláusula — 第4.2条 — café ☕ §4.2"
    parsed = parse_text(source.encode("utf-8"))

    assert parsed.canonical_text == source
    span = parsed.pages[0]
    assert parsed.canonical_text[span.char_start : span.char_end] == source


@pytest.mark.unit
def test_parse_text_empty_yields_no_chunks() -> None:
    """An empty file is honestly empty: ready, zero chunks."""

    parsed = parse_text(b"")
    assert parsed.canonical_text == ""
    assert parsed.page_count == 1
    assert chunk_document(parsed) == []


# ---------------------------------------------------------------------------
# parse_text — failure path: fail loud on non-UTF-8 (never silently mis-decode)
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_parse_text_rejects_non_utf8() -> None:
    """A non-UTF-8 byte stream raises rather than guessing an encoding.

    A silent mis-decode (e.g. latin-1 fallback) would corrupt the canonical
    text a citation later verifies against — the worst possible failure for a
    verification-critical path. ``ParserDecodeError`` is a ``ParserError``, so
    the ingest orchestrator maps it to a terminal ``failed`` row.
    """

    bad = b"valid ascii then a lone continuation byte: \xff\xfe and \x80"
    with pytest.raises(ParserDecodeError):
        parse_text(bad)
    # Subclass relationship the orchestrator relies on.
    assert issubclass(ParserDecodeError, ParserError)


@pytest.mark.unit
def test_parse_text_rejects_nul_byte() -> None:
    """A NUL byte decodes as valid Unicode but PostgreSQL ``text`` cannot store
    it. Reject at parse time so it surfaces as a clean ``decode_error`` rather
    than a DB exception that strands the row mid-ingest. (A NUL almost always
    means a binary/UTF-16 file mislabeled as text.)"""

    with pytest.raises(ParserDecodeError):
        parse_text(b"clause one\x00clause two")


# ---------------------------------------------------------------------------
# THE LOAD-BEARING TEST — offset fidelity through parse_text → chunk_document.
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.parametrize("target, overlap", [(200, 20), (1200, 100)])
def test_offset_fidelity_text(target: int, overlap: int) -> None:
    """Every chunk slices back to its content byte-for-byte (Citation Engine
    precondition). For text this holds exactly: canonical_text is verbatim."""

    source = (
        "# Master Services Agreement\n\n"
        "1. Term. This Agreement commences on the Effective Date and "
        "continues for three (3) years.\n\n"
        "2. Fees. Customer shall pay the fees set out in Exhibit A within "
        "thirty (30) days of invoice.\n\n"
        "Cláusula 3 — Límite de responsabilidad — 第4条.\n\n"
    ) * 25
    parsed = parse_text(source.encode("utf-8"))
    chunks = chunk_document(parsed, target_chars=target, overlap_chars=overlap)

    assert chunks, "chunker produced no chunks for non-empty text"
    for chunk in chunks:
        canonical_slice = parsed.canonical_text[chunk.char_offset_start : chunk.char_offset_end]
        assert canonical_slice == chunk.content, (
            f"chunk {chunk.chunk_index} fidelity broken: "
            f"offsets=[{chunk.char_offset_start}, {chunk.char_offset_end})"
        )
        # Every text chunk lands on the single synthetic page.
        assert chunk.page_start == 1
        assert chunk.page_end == 1


# ---------------------------------------------------------------------------
# ADVERSARIAL INPUT — a .txt/.md is attacker-controlled content that flows
# into the chunker. These lock in that pathological text cannot hang a worker
# (no ReDoS, guaranteed loop advance) and still satisfies offset-fidelity.
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.parametrize(
    "raw, label",
    [
        (b"A" * 300_000, "one-giant-line-no-whitespace"),
        (b".!?" * 100_000, "all-sentence-punctuation-no-spaces"),
        (b"\n" * 200_000, "all-newlines"),
        (b" " * 200_000, "all-whitespace"),
        ("一".encode() * 100_000, "dense-cjk-no-boundaries"),
    ],
)
def test_parse_text_pathological_input_terminates_with_fidelity(raw: bytes, label: str) -> None:
    """Pathological text terminates in linear time and keeps offset-fidelity.

    The chunker's regexes (`[.!?]\\s`, `\\n\\s*\\n`) are backtracking-free and the
    chunk loop is guaranteed to advance, so none of these inputs can hang a
    worker — and every chunk still slices back to its source bytes exactly.
    """

    parsed = parse_text(raw)
    chunks = chunk_document(parsed, target_chars=2000, overlap_chars=200)
    # Whitespace-only inputs are non-empty text but may yield no chunks — both
    # are acceptable; what matters is termination and fidelity where chunks exist.
    for chunk in chunks:
        assert (
            parsed.canonical_text[chunk.char_offset_start : chunk.char_offset_end] == chunk.content
        ), f"[{label}] offset fidelity broken at chunk {chunk.chunk_index}"
