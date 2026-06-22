"""Document parser adapters — PyMuPDF/Docling for PDF, a stdlib decode for text.

Plain text and Markdown (:func:`parse_text`) need no parsing library: the
decoded bytes are themselves the canonical character stream, stored verbatim
so citations resolve byte-for-byte. PDF needs real extraction, per ADR 0006:

* **PyMuPDF** is the source of truth for the canonical character
  stream. Every chunk's ``content`` slices the PyMuPDF output by
  ``[char_offset_start:char_offset_end]`` byte-for-byte.
* **Docling** produces a structured representation (titles,
  paragraphs, tables) that is stashed for M2 consumption. M1's
  chunker does not consume Docling's offsets — they are not
  character-precise against the original PDF.

This module exposes a single high-level entry point :func:`parse_pdf`
that runs the cascade: PyMuPDF first (mandatory — without it we
can't produce offsets), Docling second (optional — failures
degrade gracefully). The returned :class:`ParsedDocument` carries
the canonical text, page boundaries, and Docling's structured
output (or ``None`` on Docling failure).

Both PyMuPDF and Docling are sync libraries. The orchestrator runs
them via :func:`asyncio.to_thread` so the worker event-loop is not
blocked. Imports are deferred until first call so the module
imports cleanly in environments where the libraries aren't
installed (e.g. CI runners without the worker dependencies).

Library versions are pinned via :mod:`api/pyproject.toml`. The
``parser_version`` returned by this module records the actually-loaded
library version at ingest time so re-ingest decisions can be made
against version drift.
"""

from __future__ import annotations

import contextlib
import logging
from dataclasses import dataclass, field

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class ParserError(Exception):
    """Base class for parser errors raised inside the pipeline.

    Distinct from :class:`app.errors.LQAIError` because parser errors
    are internal to the pipeline — the orchestrator translates them
    into ``files.ingestion_error`` strings and ``ingestion_status =
    'failed'`` rather than HTTP responses.
    """


class ParserUnsupported(ParserError):
    """The file type or content is not supported by any installed parser.

    Currently raised for non-PDF MIME types (DOCX, RTF — M2) and for
    encrypted PDFs (the M1 pipeline does not unlock them).
    """


class ParserDecodeError(ParserError):
    """A text/markdown upload could not be decoded as UTF-8.

    Distinct from :class:`ParserUnsupported`: the MIME *is* a supported
    text type, but the bytes are not valid UTF-8. We fail loud rather
    than guess an encoding — a silent mis-decode would corrupt the
    canonical text a citation later verifies against. The orchestrator
    maps this to ``ingestion_error='decode_error'``.
    """


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class PageSpan:
    """A page's span within the canonical character stream.

    Half-open interval ``[start, end)`` — slicing
    ``canonical_text[start:end]`` returns the page's text.
    """

    page_number: int  # 1-based, matches PDF page numbering convention
    char_start: int
    char_end: int


@dataclass(slots=True)
class ParsedDocument:
    """The canonical view of a parsed PDF.

    Attributes:
        canonical_text: The full, concatenated, character-precise text
            of the PDF as produced by PyMuPDF. This is the load-bearing
            artifact: every chunk's ``[char_offset_start:char_offset_end]``
            slice of this string equals the chunk's ``content``.
        pages: One :class:`PageSpan` per page; ``pages[i].page_number``
            is 1-based.
        page_count: Total page count; equals ``len(pages)``.
        parser: Which parser cascade produced this result —
            ``'docling+pymupdf'`` (both succeeded), ``'pymupdf'``
            (Docling fell through), or ``'pymupdf-only'``
            (Docling not attempted, e.g., disabled by config).
        parser_version: Library version string of the canonical
            parser (``fitz.__doc__`` for PyMuPDF, plus Docling
            version when applicable).
        structured_content: Docling's structured representation —
            ``None`` if Docling failed or wasn't attempted. M1 stashes
            this in ``documents.structured_content`` for M2 consumption;
            the chunker does not consume it.
    """

    canonical_text: str
    pages: list[PageSpan]
    page_count: int
    parser: str
    parser_version: str
    structured_content: dict[str, object] | None = field(default=None)


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

# Sentinel MIME types we accept for PDFs. DOCX/RTF still stay at
# ``ingestion_status='failed'`` with ``unsupported_type``; plain
# text / Markdown are handled by the :func:`parse_text` branch below.
SUPPORTED_PDF_MIMES = frozenset(
    {
        "application/pdf",
        "application/x-pdf",
        "application/acrobat",
        "applications/vnd.pdf",
        "text/pdf",
        "text/x-pdf",
    }
)

# Plain-text and Markdown uploads. These need no parsing library — the
# decoded bytes are themselves the canonical character stream — so they
# take the :func:`parse_text` branch rather than the PyMuPDF/Docling
# cascade.
SUPPORTED_TEXT_MIMES = frozenset(
    {
        "text/plain",
        "text/markdown",
        "text/x-markdown",
    }
)


def is_pdf_mime(mime_type: str) -> bool:
    """Return True if the MIME indicates a PDF the pipeline can handle.

    Some uploaders emit non-canonical MIME strings; we accept the
    common variants.
    """

    return mime_type.lower() in SUPPORTED_PDF_MIMES


def is_text_mime(mime_type: str) -> bool:
    """Return True if the MIME indicates plain text or Markdown.

    Text uploads commonly carry a charset parameter
    (``text/plain; charset=utf-8``), so we match on the bare type and
    ignore parameters. The charset is *not* honoured for decoding —
    :func:`parse_text` always decodes strict UTF-8 (see its docstring).
    """

    base = mime_type.split(";", 1)[0].strip().lower()
    return base in SUPPORTED_TEXT_MIMES


# Filename extensions treated as text when the browser-supplied MIME is
# unreliable. Browsers and operating systems disagree on the MIME for ``.md``
# (frequently ``application/octet-stream`` or empty), so the extension is the
# dependable signal. This only *routes* the upload to :func:`parse_text`, which
# still validates the bytes (strict UTF-8, no NUL) — so a binary file with a
# ``.md`` name fails cleanly as ``decode_error`` rather than being trusted.
TEXT_EXTENSIONS = (".md", ".markdown", ".txt")


def is_text_filename(filename: str) -> bool:
    """Return True if the filename has a known text/Markdown extension.

    The fallback for generic-MIME uploads (e.g. ``application/octet-stream``),
    which is what many browsers send for ``.md``.
    """

    return filename.lower().endswith(TEXT_EXTENSIONS)


def parse_text(raw_bytes: bytes) -> ParsedDocument:
    """Build a canonical :class:`ParsedDocument` from a text/Markdown upload.

    Unlike PDF, plain text needs no parsing library: the decoded bytes
    *are* the canonical character stream. Storing them verbatim makes the
    offset-fidelity contract
    (``canonical_text[char_offset_start:char_offset_end] == chunk.content``)
    hold exactly, so the Citation Engine re-reads byte-for-byte and the
    strongest (exact-match) citation tier resolves for every text document.

    Markdown is stored **verbatim, never rendered** — a citation must
    resolve against the source the user uploaded, not a derived rendering,
    and rendering would also add a non-deterministic dependency.

    Decoding is strict UTF-8 (``utf-8-sig`` transparently drops an optional
    BOM). A non-UTF-8 byte stream raises :class:`ParserDecodeError` rather
    than guessing an encoding — a silent mis-decode would corrupt the text a
    citation later verifies against. This is a pure, deterministic function:
    same bytes in, same canonical text out, with no model, OCR, or network.

    A NUL byte (``0x00``) is also rejected: it decodes as valid Unicode but
    PostgreSQL ``text`` columns cannot store it, so ``normalized_content``
    would fail to persist downstream. A NUL almost always means the upload is
    binary (or UTF-16) mislabeled as text — failing loud here is correct, and
    keeps the failure a clean ``decode_error`` rather than a DB exception that
    strands the row mid-ingest.
    """

    try:
        text = raw_bytes.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ParserDecodeError(
            f"upload is not valid UTF-8 text (offset {exc.start}): {exc.reason}. "
            "Save the file as UTF-8 (not UTF-16 / ANSI / Latin-1) and retry."
        ) from exc

    if "\x00" in text:
        raise ParserDecodeError(
            "upload contains a NUL byte (0x00); this is not a valid text "
            "document (likely a binary or UTF-16 file mislabeled as text)."
        )

    # Single synthetic page over the whole stream — text has no pagination;
    # this mirrors the autonomous-artifact construction in
    # ``app.autonomous.guard`` and keeps the chunker's page lookup happy.
    return ParsedDocument(
        canonical_text=text,
        pages=[PageSpan(page_number=1, char_start=0, char_end=len(text))],
        page_count=1,
        parser="plain-text",
        parser_version="1",
        structured_content=None,
    )


def parse_pdf(pdf_bytes: bytes, *, run_docling: bool = True) -> ParsedDocument:
    """Run the parser cascade on a PDF byte string.

    PyMuPDF is run first and is mandatory — without it we cannot
    produce the canonical character stream. If PyMuPDF raises, this
    function re-raises as :class:`ParserError`.

    Docling is run second and is optional; on Docling failure we log
    a WARNING and proceed with PyMuPDF-only results.

    The function is sync so the worker can wrap it via
    :func:`asyncio.to_thread`. Both libraries are sync internally.

    Args:
        pdf_bytes: Raw PDF byte string. Empty input raises
            :class:`ParserError`.
        run_docling: When False, skip the Docling pass entirely.
            Useful in tests where Docling is mocked or unavailable.

    Returns:
        :class:`ParsedDocument` with the canonical text, page spans,
        parser metadata, and Docling's structured content if
        successful.
    """

    if not pdf_bytes:
        raise ParserError("PDF input is empty")

    # PyMuPDF is the canonical parser — without it, no offsets, no
    # ingestion. We import it lazily so this module imports cleanly
    # in environments where it isn't installed (test stubs, etc.).
    canonical_text, pages, pymupdf_version = _run_pymupdf(pdf_bytes)

    # Docling is best-effort. Skip if disabled or unavailable.
    structured_content: dict[str, object] | None = None
    docling_version: str | None = None
    docling_succeeded = False

    if run_docling:
        try:
            structured_content, docling_version = _run_docling(pdf_bytes)
            docling_succeeded = True
        except Exception as exc:
            # Docling failures are recoverable — we degrade to
            # PyMuPDF-only and log so operators see the drift.
            log.warning(
                "Docling parser failed; falling back to PyMuPDF-only",
                extra={
                    "event": "pipeline_docling_fallback",
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                },
            )

    if docling_succeeded:
        parser_label = "docling+pymupdf"
        version_label = f"pymupdf={pymupdf_version}; docling={docling_version}"
    elif run_docling:
        parser_label = "pymupdf"
        version_label = f"pymupdf={pymupdf_version}; docling=fallback"
    else:
        parser_label = "pymupdf-only"
        version_label = f"pymupdf={pymupdf_version}"

    return ParsedDocument(
        canonical_text=canonical_text,
        pages=pages,
        page_count=len(pages),
        parser=parser_label,
        parser_version=version_label,
        structured_content=structured_content,
    )


# ---------------------------------------------------------------------------
# PyMuPDF adapter
# ---------------------------------------------------------------------------


def _run_pymupdf(pdf_bytes: bytes) -> tuple[str, list[PageSpan], str]:
    """Extract canonical text + page spans + library version via PyMuPDF.

    The canonical text is built by concatenating every page's
    extracted text in document order. Page boundaries are recorded as
    offsets into this concatenated string so the chunker (and M2's
    citation engine) can map an offset back to a page.

    PyMuPDF's ``page.get_text()`` returns a string per page. We use
    this directly: the canonical text is exactly what PyMuPDF says it
    is, with the same character ordering and the same byte content.
    Slicing the canonical text by ``[start:end]`` is therefore
    equivalent to slicing the per-page output PyMuPDF returns —
    that's what makes the offsets character-precise.

    Page joining: pages are joined with ``\n`` (a single newline). The
    chunker treats the newline as a regular character; offsets count
    it like any other.

    Raises:
        :class:`ParserError`: PyMuPDF failed to open or read the PDF
            (corrupt file, encrypted document we can't unlock, etc.).
    """

    try:
        import fitz  # PyMuPDF
    except ImportError as exc:  # pragma: no cover — install-time error
        raise ParserError("PyMuPDF (fitz) is not installed; document pipeline cannot run") from exc

    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    except Exception as exc:
        raise ParserError(f"PyMuPDF could not open the PDF: {exc}") from exc

    try:
        if doc.is_encrypted:
            raise ParserUnsupported(
                "Encrypted PDFs are not supported in M1 (no OCR / no decryption)"
            )

        page_texts: list[str] = []
        pages: list[PageSpan] = []
        running_offset = 0
        page_count = doc.page_count

        for page_idx in range(page_count):
            page = doc.load_page(page_idx)
            try:
                text = page.get_text()
            except Exception as exc:
                raise ParserError(
                    f"PyMuPDF failed extracting text from page {page_idx + 1}: {exc}"
                ) from exc

            # Track this page's span before appending the join character.
            page_span = PageSpan(
                page_number=page_idx + 1,
                char_start=running_offset,
                char_end=running_offset + len(text),
            )
            pages.append(page_span)
            page_texts.append(text)
            running_offset += len(text)

            # Add a single newline between pages — except after the last.
            if page_idx < page_count - 1:
                running_offset += 1  # account for the join newline

        canonical_text = "\n".join(page_texts)

        # Sanity: the running offset must match the canonical text length
        # exactly. If it doesn't, our offset-tracking has a bug and the
        # chunker downstream will produce wrong slices.
        if running_offset != len(canonical_text):  # pragma: no cover — defensive
            raise ParserError(
                "PyMuPDF offset accounting drift: "
                f"running_offset={running_offset}, "
                f"canonical_text_len={len(canonical_text)}"
            )

        version = _safe_pymupdf_version()
        return canonical_text, pages, version
    finally:
        with contextlib.suppress(Exception):
            doc.close()  # pragma: no cover — closing is best-effort


def _safe_pymupdf_version() -> str:
    """Return the loaded PyMuPDF version string, defensively.

    PyMuPDF exposes ``fitz.version`` as a tuple in newer releases and
    ``fitz.__doc__`` in older ones; fall back to ``"unknown"`` if the
    attribute isn't where we expect.
    """

    try:
        import fitz

        version = getattr(fitz, "version", None)
        if version is not None:
            return str(version[0]) if isinstance(version, tuple) else str(version)
        return getattr(fitz, "__version__", "unknown")
    except Exception:  # pragma: no cover — defensive
        return "unknown"


# ---------------------------------------------------------------------------
# Docling adapter
# ---------------------------------------------------------------------------


def _run_docling(pdf_bytes: bytes) -> tuple[dict[str, object], str]:
    """Run Docling against the PDF; return its structured representation.

    Docling's API surface (as of v1.x) accepts an in-memory document
    via its converter. We use the ``DocumentConverter`` entry point
    and store the produced document's serialised ``model_dump()`` so
    M2 readers can deserialise it back into Docling objects.

    Raises:
        Any exception Docling raises. Caller catches and falls back to
        PyMuPDF-only.
    """

    try:
        from docling.datamodel.base_models import DocumentStream
        from docling.document_converter import DocumentConverter
    except ImportError as exc:
        raise ParserError(
            "Docling is not installed; document pipeline cannot run Docling pass"
        ) from exc

    import io

    converter = DocumentConverter()
    stream = DocumentStream(name="upload.pdf", stream=io.BytesIO(pdf_bytes))
    result = converter.convert(stream)

    # Newer Docling exposes the result on .document; older on .output.
    doc = getattr(result, "document", None) or getattr(result, "output", None)
    if doc is None:
        raise ParserError("Docling returned no document on conversion result")

    # Serialise via model_dump if Pydantic-backed; otherwise best-effort
    # (older Docling versions return a custom object — coerce to dict).
    structured = doc.model_dump() if hasattr(doc, "model_dump") else {"raw": str(doc)}

    version = _safe_docling_version()
    return structured, version


def _safe_docling_version() -> str:
    """Return Docling's installed version, defensively."""

    try:
        import docling

        return getattr(docling, "__version__", "unknown")
    except Exception:  # pragma: no cover — defensive
        return "unknown"
