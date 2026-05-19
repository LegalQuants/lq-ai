"""Embedding generation for ``document_chunks`` (C6 / ADR 0008).

Two surfaces:

* **Eager backfill** — :func:`embed_chunks_for_file` walks every chunk
  belonging to a file with ``embedding IS NULL`` and submits them in
  batches to the gateway's ``/v1/embeddings``. Persists each chunk's
  vector + token count in a single transaction. Invoked by the
  ``embed_chunks_job`` arq job (which is enqueued on KB-attach and on
  ingest-completion in C6+).
* **Lazy embed-on-read** — :func:`ensure_embeddings_for_chunk_ids`
  embeds a small set of chunks synchronously. Used by the KB query
  handler when the vector side returned chunks with ``embedding IS
  NULL`` (which would otherwise be invisible to the vector ranker).

The tokenizer is :mod:`tiktoken`'s ``cl100k_base`` — OpenAI's BPE for
the ``text-embedding-3-*`` family. Stored alongside the embedding in
``document_chunks.tokens`` (closing C5's deferred per-chunk token-
count item).

Per CLAUDE.md the backend cannot hold provider keys; we route through
the gateway's :class:`GatewayClient` for every embedding call. Failures
are translated through :mod:`app.errors` so the caller sees the typed
hierarchy.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.clients.gateway import GatewayClient, get_gateway_client
from app.errors import GatewayInvalidResponse
from app.models.document import DocumentChunk

if TYPE_CHECKING:
    pass

log = logging.getLogger(__name__)


DEFAULT_EMBEDDING_MODEL: Final[str] = "embedding"
"""Alias the backend asks the gateway to dispatch.

Per ADR 0008 the alias resolves (in ``gateway.yaml.example``) to
``openai-prod/text-embedding-3-small``. Operators who repoint the
alias to a different provider/model don't need to change code on
this side."""

EMBEDDING_DIMENSION: Final[int] = 1536
"""Native dim of ``text-embedding-3-small``. Matches C5's
``vector(1536)`` column. If a future ADR repoints the alias to a
different-dim model, a migration alters the column."""

EMBED_BATCH_SIZE: Final[int] = 64
"""Number of chunks to submit per embeddings call.

OpenAI's documented batch ceiling is 2048 inputs per call; we stay
well below that to keep individual call latency bounded and to
make partial-failure recovery practical (a failed batch of 64
re-runs faster than a failed batch of 2048)."""

EMBED_BATCH_INPUT_CHARS: Final[int] = 60_000
"""Soft cap on the *total characters* per batch.

OpenAI's per-call limit is on tokens (8191 for text-embedding-3-*),
which we enforce per-input via tiktoken at the chunker boundary. The
batch-level cap here is a defensive limit on the request body size:
pre-tokenize every batch to roughly 60K chars (~15K tokens worst
case), which leaves headroom even on long-content batches."""


@dataclass(slots=True)
class EmbedFileResult:
    """Outcome of an :func:`embed_chunks_for_file` run."""

    file_id: uuid.UUID
    chunks_embedded: int
    chunks_skipped: int
    """Chunks that already had embeddings (idempotency-safe re-run)."""
    error: str | None = None


# ---------------------------------------------------------------------------
# Tokenization
# ---------------------------------------------------------------------------


_tokenizer_cache: object | None = None


def _get_tokenizer() -> object:
    """Return a process-cached ``tiktoken.Encoding`` for ``cl100k_base``.

    ``tiktoken`` is imported lazily so the import path doesn't fail in
    minimal test environments where the dep isn't installed; production
    runs will have it available per ``api/pyproject.toml``.
    """

    global _tokenizer_cache
    if _tokenizer_cache is not None:
        return _tokenizer_cache

    import tiktoken

    _tokenizer_cache = tiktoken.get_encoding("cl100k_base")
    return _tokenizer_cache


def count_tokens(text_value: str) -> int:
    """Return the BPE token count of ``text_value`` per OpenAI's ``cl100k_base``.

    Used by the embed-on-write path to populate ``document_chunks.tokens``.
    Per ADR 0008 the tokenizer choice tracks the embedding-model choice;
    a future Voyage / local adapter would swap this.

    Falls back to a coarse ``len(text) // 4`` estimate if tiktoken is
    unavailable — this should not happen in production but the test
    environment occasionally lacks the dep, and a coarse count is
    better than a hard failure when token counts are advisory.
    """

    try:
        encoding = _get_tokenizer()
    except ImportError:
        log.warning("tiktoken not installed; using coarse token count estimate")
        return max(1, len(text_value) // 4)

    encoded = encoding.encode(text_value)  # type: ignore[attr-defined]
    return len(encoded)


# ---------------------------------------------------------------------------
# Single-vector embed (used by the query path)
# ---------------------------------------------------------------------------


async def request_embedding_vector(
    text_value: str,
    *,
    model: str = DEFAULT_EMBEDDING_MODEL,
    gateway: GatewayClient | None = None,
    request_id: str | None = None,
) -> list[float]:
    """Return the embedding vector for ``text_value`` via the gateway.

    Wraps :meth:`GatewayClient.embeddings` and pulls out the single
    embedding vector (the request had a single string input). Surfaces
    a :class:`GatewayInvalidResponse` if the gateway returns a payload
    without the expected shape.
    """

    client = gateway if gateway is not None else get_gateway_client()
    payload = await client.embeddings(
        model=model,
        input_=text_value,
        request_id=request_id,
    )
    data = payload.get("data") or []
    if not data:
        raise GatewayInvalidResponse(
            "Gateway embeddings response had no data entries",
            details={"model": model},
        )
    first = data[0]
    if not isinstance(first, dict):
        raise GatewayInvalidResponse(
            "Gateway embeddings response data entry was not a JSON object",
            details={"model": model},
        )
    embedding = first.get("embedding")
    if not isinstance(embedding, list):
        raise GatewayInvalidResponse(
            "Gateway embeddings response missing 'embedding' field",
            details={"model": model},
        )
    return [float(value) for value in embedding]


async def request_embedding_vectors(
    texts: Sequence[str],
    *,
    model: str = DEFAULT_EMBEDDING_MODEL,
    gateway: GatewayClient | None = None,
    request_id: str | None = None,
) -> list[list[float]]:
    """Return embedding vectors for a batch of texts, one per input.

    The gateway accepts either a single string or a list. We always
    submit lists for batches so the wire shape matches the OpenAI
    convention.
    """

    if not texts:
        return []
    client = gateway if gateway is not None else get_gateway_client()
    payload = await client.embeddings(
        model=model,
        input_=list(texts),
        request_id=request_id,
    )
    data = payload.get("data") or []
    if not isinstance(data, list) or len(data) != len(texts):
        raise GatewayInvalidResponse(
            "Gateway embeddings response had unexpected number of entries",
            details={
                "expected": len(texts),
                "received": len(data) if isinstance(data, list) else None,
            },
        )
    # Sort by ``index`` defensively — OpenAI orders, but the spec
    # explicitly says callers must use ``index``.
    sorted_entries = sorted(
        (entry for entry in data if isinstance(entry, dict)),
        key=lambda e: int(e.get("index", 0)) if isinstance(e.get("index", 0), int) else 0,
    )
    vectors: list[list[float]] = []
    for entry in sorted_entries:
        embedding = entry.get("embedding")
        if not isinstance(embedding, list):
            raise GatewayInvalidResponse(
                "Gateway embeddings response data entry missing 'embedding'",
                details={"index": entry.get("index")},
            )
        vectors.append([float(v) for v in embedding])
    return vectors


# ---------------------------------------------------------------------------
# Batched eager-backfill (used by the worker job and by KB-attach)
# ---------------------------------------------------------------------------


def _batched(items: Sequence[DocumentChunk]) -> Iterable[list[DocumentChunk]]:
    """Group chunks into ``EMBED_BATCH_SIZE``-sized batches that respect
    :data:`EMBED_BATCH_INPUT_CHARS` byte cap.

    We pack greedily: take chunks until either the size cap or the
    char cap fires. Keeps the per-call body bounded.
    """

    current: list[DocumentChunk] = []
    current_chars = 0
    for chunk in items:
        clen = len(chunk.content)
        # If a single chunk exceeds the soft cap we still send it
        # solo — better to exceed the soft cap than to skip a chunk.
        if current and (
            len(current) >= EMBED_BATCH_SIZE or current_chars + clen > EMBED_BATCH_INPUT_CHARS
        ):
            yield current
            current = []
            current_chars = 0
        current.append(chunk)
        current_chars += clen
    if current:
        yield current


async def embed_chunks_for_file(
    db: AsyncSession,
    file_id: uuid.UUID,
    *,
    model: str = DEFAULT_EMBEDDING_MODEL,
    gateway: GatewayClient | None = None,
) -> EmbedFileResult:
    """Embed every chunk of ``file_id``'s document where ``embedding IS NULL``.

    Idempotent: chunks that already have embeddings are skipped (the
    SELECT filters them out). Token counts are populated for every
    chunk that gets a fresh vector — closing the C5 deferred
    per-chunk-token item.

    Persists vectors via raw SQL because pgvector's ``vector`` column
    isn't first-class in SQLAlchemy core. We use parameter binding so
    the float-list serialization is dialect-controlled.
    """

    # Fetch chunks needing embedding for this file. The JOIN goes
    # through ``documents`` because chunks live under documents, which
    # live under files.
    stmt = select(DocumentChunk).join_from(DocumentChunk, DocumentChunk.__table__)
    # SQLAlchemy 2.0 idiom for the join we actually want:
    from app.models.document import Document  # local import to avoid cycle

    stmt = (
        select(DocumentChunk)
        .join(Document, DocumentChunk.document_id == Document.id)
        .where(Document.file_id == file_id)
        .where(text("document_chunks.embedding IS NULL"))
        .order_by(DocumentChunk.chunk_index)
    )
    result = await db.execute(stmt)
    chunks_needing_embed = list(result.scalars().all())

    if not chunks_needing_embed:
        log.info(
            "embed_chunks_for_file: no chunks need embedding",
            extra={"event": "embed_no_op", "file_id": str(file_id)},
        )
        return EmbedFileResult(file_id=file_id, chunks_embedded=0, chunks_skipped=0)

    # M3-0.3 / DE-276: total chunks needing embedding before we start,
    # so a mid-batch failure can distinguish "embedded zero" from
    # "embedded some but not all" — the partial case.
    total_to_embed = len(chunks_needing_embed)

    # Run batches.
    embedded_count = 0
    for batch in _batched(chunks_needing_embed):
        texts = [chunk.content for chunk in batch]
        try:
            vectors = await request_embedding_vectors(
                texts,
                model=model,
                gateway=gateway,
            )
        except Exception as exc:
            log.warning(
                "embed_chunks_for_file: batch failed",
                extra={
                    "event": "embed_batch_failed",
                    "file_id": str(file_id),
                    "batch_size": len(batch),
                    "error": str(exc),
                },
            )
            reason = f"{type(exc).__name__}: {exc}"
            # M3-0.3 / DE-276: flip the document-level ingest_status so
            # the operator-visible state matches reality. Zero progress
            # = embed_failed; some progress = partial.
            await _mark_document_embed_failure(
                db, file_id=file_id, reason=reason, partial=embedded_count > 0
            )
            return EmbedFileResult(
                file_id=file_id,
                chunks_embedded=embedded_count,
                chunks_skipped=0,
                error=reason,
            )

        # Persist via raw SQL — pgvector's vector type accepts the
        # textual representation '[v1,v2,...]'. The embed col was
        # declared via raw DDL in C5's migration; we use the same
        # string-form here so the cast is explicit on every write.
        for chunk, vector in zip(batch, vectors, strict=True):
            tokens = count_tokens(chunk.content)
            vector_text = _format_vector(vector)
            await db.execute(
                text(
                    "UPDATE document_chunks "
                    "SET embedding = CAST(:vec AS vector), tokens = :tokens "
                    "WHERE id = :chunk_id"
                ),
                {
                    "vec": vector_text,
                    "tokens": tokens,
                    "chunk_id": str(chunk.id),
                },
            )
            embedded_count += 1

        await db.commit()

    # M3-0.3 / DE-276: every chunk that needed embedding got one. If
    # the document was previously flagged (a prior run partially
    # failed and the operator re-ran), clear the flag back to 'ok' so
    # the admin endpoint and UI reflect the recovered state.
    if embedded_count == total_to_embed and total_to_embed > 0:
        await _clear_document_ingest_status(db, file_id=file_id)

    log.info(
        "embed_chunks_for_file: done",
        extra={
            "event": "embed_done",
            "file_id": str(file_id),
            "embedded": embedded_count,
        },
    )
    return EmbedFileResult(
        file_id=file_id,
        chunks_embedded=embedded_count,
        chunks_skipped=0,
    )


async def _mark_document_embed_failure(
    db: AsyncSession,
    *,
    file_id: uuid.UUID,
    reason: str,
    partial: bool,
) -> None:
    """Flip ``documents.ingest_status`` for ``file_id``'s document on embed failure.

    ``partial=True`` indicates at least one chunk was successfully
    embedded before the batch raised; that signal is worth preserving
    so operators can tell a complete failure (gateway unreachable from
    the start) from a partial run (a transient mid-stream issue).
    """
    await db.execute(
        text(
            "UPDATE documents "
            "SET ingest_status = :status, ingest_failure_reason = :reason "
            "WHERE file_id = :file_id"
        ),
        {
            "status": "partial" if partial else "embed_failed",
            "reason": reason,
            "file_id": str(file_id),
        },
    )
    await db.commit()


async def _clear_document_ingest_status(
    db: AsyncSession,
    *,
    file_id: uuid.UUID,
) -> None:
    """Reset ``documents.ingest_status`` to ``'ok'`` after a successful re-embed.

    Idempotent for already-ok rows; the UPDATE is keyed on file_id and
    overwrites whichever non-ok value may have been set by a prior
    failed run.
    """
    await db.execute(
        text(
            "UPDATE documents "
            "SET ingest_status = 'ok', ingest_failure_reason = NULL "
            "WHERE file_id = :file_id AND ingest_status <> 'ok'"
        ),
        {"file_id": str(file_id)},
    )
    await db.commit()


async def ensure_embeddings_for_chunk_ids(
    db: AsyncSession,
    chunk_ids: Sequence[uuid.UUID],
    *,
    model: str = DEFAULT_EMBEDDING_MODEL,
    gateway: GatewayClient | None = None,
) -> int:
    """Embed-on-read: fill embeddings for any of ``chunk_ids`` that lack one.

    Used by the query handler when the vector-side candidate set
    returned chunks with NULL embeddings (they'd be invisible to the
    cosine ranker otherwise). Synchronous from the request's perspective
    — the caller awaits this before re-running the vector search.

    Returns the count of chunks newly embedded. Failures bubble up;
    the caller is expected to fall through to FTS-only ranking on
    failure (a partial-success here is still useful).
    """

    if not chunk_ids:
        return 0

    stmt = (
        select(DocumentChunk)
        .where(DocumentChunk.id.in_(chunk_ids))
        .where(text("document_chunks.embedding IS NULL"))
    )
    result = await db.execute(stmt)
    chunks = list(result.scalars().all())
    if not chunks:
        return 0

    texts = [chunk.content for chunk in chunks]
    vectors = await request_embedding_vectors(texts, model=model, gateway=gateway)

    embedded = 0
    for chunk, vector in zip(chunks, vectors, strict=True):
        tokens = count_tokens(chunk.content)
        vector_text = _format_vector(vector)
        await db.execute(
            text(
                "UPDATE document_chunks "
                "SET embedding = CAST(:vec AS vector), tokens = :tokens "
                "WHERE id = :chunk_id"
            ),
            {
                "vec": vector_text,
                "tokens": tokens,
                "chunk_id": str(chunk.id),
            },
        )
        embedded += 1

    await db.commit()
    return embedded


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _format_vector(vector: Sequence[float]) -> str:
    """Format a float list as pgvector's textual ``[v1,v2,...]`` form.

    pgvector's parser accepts this representation; using a string
    binding (rather than a binary protocol) keeps the path driver-
    independent and matches how psql / migrations write vectors.
    """

    return "[" + ",".join(repr(float(v)) for v in vector) + "]"
