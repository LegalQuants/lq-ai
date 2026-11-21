# ADR 0045: Zero-pad shorter embeddings at the document database boundary

Status: Accepted by the maintainer on 2026-11-21.

## Context

The local PR #419 walkthrough used Qwen chat and nomic embeddings. Nomic
returned 768-dimensional vectors; the document column and cosine index
require 1,536 dimensions. Writes failed after successful parsing.
ADR 0008 selected the original embedding model and left local embedding
compatibility open. The maintainer selected zero-padding over migration.

## Decision

Keep `document_chunks.embedding vector(1536)` and its existing index.
Zero-pad native vectors with 1–1,536 dimensions at all database boundaries:
eager chunk writes, lazy chunk writes, and vector-search queries. Validate
each complete write batch before updates. Reject empty, oversized, or
non-finite vectors with a typed gateway-response error; never truncate
vectors. Eager validation failures use the existing `embed_failed`/`partial`
document status.

Provider responses and in-memory playbook clustering retain native
dimensions. Chat and embeddings still use the existing gateway; this adds
no provider adapter, dependency, migration, or security-boundary change.

For vectors from the same model, appending zeros preserves dot products
and norms, and therefore cosine similarity and ranking. Both stored and
query vectors use the existing index dimensions.

## Limits and operations

Padding does not make different embedding models compatible. A deployment
must use the same embedding model for stored chunks and queries. Changing
the `embedding` alias requires re-embedding existing documents before
relying on vector retrieval, even when the old and new models have equal
dimensions. This change does not automatically rebuild existing vectors
or support models larger than 1,536 dimensions; those require a separate
storage decision. Native 1,536-dimensional vectors are unchanged.

Token counts remain advisory `cl100k_base` counts, rather than a nomic
tokenizer. The provider retains responsibility for its own input limits.

## Validation

Tests cover cosine preservation, unchanged native provider results,
invalid-vector rejection, eager/lazy writes into real pgvector storage,
and search with an unpadded 768-dimensional query and expected cosine
ordering. Live-corpus evidence is recorded separately.
