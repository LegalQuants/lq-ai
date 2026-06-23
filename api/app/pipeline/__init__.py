"""Document pipeline package — Task C5.

This package contains the pieces of the document-pipeline service:

* :mod:`app.pipeline.parsers` — Docling and PyMuPDF adapter functions
  that translate PDF bytes into a canonical character stream and a
  structured representation.
* :mod:`app.pipeline.chunker` — character-precise sliding-window chunker
  that produces ``Chunk`` records whose offsets slice the canonical
  text byte-for-byte.
* :mod:`app.pipeline.ingest` — orchestration: pull bytes from MinIO,
  parse, chunk, persist to the DB, flip ``files.ingestion_status``.

The orchestration is invoked by :mod:`app.workers.document_pipeline`,
which is the ``arq``-backed worker process declared in
``docker-compose.yml`` as the ``ingest-worker`` service. See
:doc:`docs/adr/0006-document-pipeline-architecture.md` for the
architectural decisions behind this layout.
"""

from app.pipeline.chunker import Chunk, chunk_document
from app.pipeline.parsers import (
    ParsedDocument,
    ParserDecodeError,
    ParserError,
    ParserUnsupported,
    parse_pdf,
    parse_text,
)

__all__ = [
    "Chunk",
    "ParsedDocument",
    "ParserDecodeError",
    "ParserError",
    "ParserUnsupported",
    "chunk_document",
    "parse_pdf",
    "parse_text",
]
