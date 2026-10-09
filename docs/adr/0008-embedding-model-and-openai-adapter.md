# ADR 0008 — Embedding model selection and OpenAI provider adapter

**Status:** Accepted (2026-05-08)
**Decision-makers:** Kevin Keller (initial maintainer)
**Affected components:** `gateway/`, `api/`
**Related:** [Task C6](../M1-IMPLEMENTATION-ORDER.md#task-c6--knowledge-service-hybrid-retrieval--embedding-generation), [ADR 0006 §3 — embeddings deferral](0006-document-pipeline-architecture.md), [ADR 0003 — error handling](0003-error-handling.md), [PRD §4 — Inference Gateway](../PRD.md#4-the-lq-ai-inference-gateway), [PRD §3 — Knowledge Bases](../PRD.md#3-capability-specifications)

**Accepted revision (2026-10-04):** [ADR 0033](0033-document-pipeline-honesty-and-ocr.md)
decision 5 adds an opt-in local (Ollama) path to the `embedding` alias. This ADR's
1536-dimension constraint and its SBOM objection still hold and constrain that path;
the assumption that an operator holds an OpenAI key is what changed.

---

## Context

Task C6 (Knowledge Service: hybrid retrieval) absorbs the embedding-generation work that C5 deferred per ADR 0006 §3. The gateway must serve a real `POST /v1/embeddings`; the worker must embed-on-write any pre-C6 chunks where `embedding IS NULL`; the query path must embed-on-read on miss.

C5 sized `document_chunks.embedding` as `vector(1536)` — chosen for OpenAI's `text-embedding-3-small` and `-large` (both default to 1536-dim outputs; `-large` can be reshaped down). ADR 0006 §3 explicitly deferred the embedding-model choice to C6.

Anthropic — the only provider adapter shipped today (B3) — does **not** offer an embeddings API. The router can resolve an `embedding` alias, but no adapter can service it. Some adapter must land before C6 can produce non-NULL embeddings.

The candidates (per the C6 brief):

| Option | Dim | New SBOM | Operator setup | Mode-2 (air-gapped) | Notes |
|---|---|---|---|---|---|
| **A. OpenAI adapter** | 1536 (small/large) | None (hand-rolled httpx, matching B3) | OpenAI key | No | Most natural fit for "operator-owned-keys"; partial-B6 closure as a side effect |
| **B. Voyage AI** | 1024 / 1536 | None (httpx) | Voyage key | No | Anthropic's recommended embedding partner; smaller operator base |
| **C. Local sentence-transformers** | 384 / 1024 | `sentence-transformers` | None (model download) | Yes | torch already a transitive (Docling); +500MB-2GB models; dimension mismatch |
| **D. Ollama embedding endpoint** | varies | None | Ollama running | Yes | Aligns with Mode 2 PRD vision; not all operators run Ollama |

## Decision

**Pick (A) — OpenAI adapter.** The gateway grows an `OpenAIAdapter` that handles **embeddings today and chat completions on contact (B6 partial closure)**. Default embedding model: `text-embedding-3-small` (1536-dim, the column shape C5 already chose). Operators may select `text-embedding-3-large` via `gateway.yaml` without a code change.

### Why (A) over (C)

The local sentence-transformers route is appealing for "no provider key required," but:

1. **Dimension mismatch.** Most local models default to 384 (MiniLM family) or 768 (mpnet) — re-sizing `vector(1536)` is a **destructive ALTER** (drop + re-add the column), and pgvector indexes require a fixed dimension. ADR 0006 §3 already records the cost of changing this; we minimize it by picking a 1536-dim path.
2. **SBOM weight.** `sentence-transformers` itself is small but its model artifacts are 100MB-2GB and download from HuggingFace at first run. PRD §1519 already documents Docling's transformer footprint; piling another model load onto the worker container's startup path doubles the container's first-run latency.
3. **Operator inconsistency.** Operators who already hold an OpenAI key (overwhelmingly likely for a self-hosted legal-AI deployment that wants the option of routing chat through OpenAI as fallback) get one less moving piece. Operators who don't get the option of switching the alias to a future Voyage / local adapter without changing any application code.

### Why (A) over (B) (Voyage AI)

Voyage is technically excellent (1024- or 1536-dim options; legal-domain `voyage-law-2` is the strongest known choice for our use case) and Anthropic recommends it as the embedding partner. We acknowledge this and **explicitly preserve the option** — the `embedding` alias in `gateway.yaml.example` can be repointed at a Voyage adapter when one ships. We pick OpenAI for M1 because:

- Most operators evaluating LQ.AI already have an OpenAI key; fewer have a Voyage key.
- The OpenAI adapter is also the foundation for the future B6 chat-completions adapter — building it once for both serves two purposes.
- Voyage's `voyage-law-2` is 1024-dim, which would force the destructive ALTER described above.

A Voyage adapter is a **deferred enhancement** (DE-XXX in PRD §9 once we update the deferred-enhancements list); it lands when an operator forces the question.

### Why (A) over (D) (Ollama)

Mode 2 / Ollama embeddings are a **complementary** option, not a substitute. The configured `embedding` alias in `gateway.yaml.example` can be repointed at an Ollama adapter when B6's Ollama work lands. Picking OpenAI for the *first* embedding adapter doesn't preclude Ollama; picking Ollama as the first one would force every operator who isn't running Ollama to install it for KB indexing.

### Tokenizer

`tiktoken` is the **only** sane way to get OpenAI-compatible token counts. It's small (BSD-3, no transitive dependencies beyond `regex`), explicitly supports OpenAI's `cl100k_base` and `o200k_base` BPEs, and is what every OpenAI-compat library uses under the hood. We add it to `api/`'s runtime deps as the per-chunk token counter for the embed-on-write path. This populates `document_chunks.tokens` (the C5-deferred per-chunk token count) — closing that deferral as a side effect.

`tiktoken`'s license, package size, and supply-chain footprint are all small enough to clear CLAUDE.md's "is this dep justified" bar — the alternative is hand-rolling a BPE tokenizer for OpenAI's specific vocabulary, which would be a hundreds-of-lines diff with the same SBOM cost.

`tiktoken` is **not** added to gateway/'s deps. The gateway delegates token counting to its upstream adapters' usage reports; per-chunk token counts are an api/-side concern (chunks are owned by api/, the embedding-write path is a worker-side concern).

### Adapter scope: embeddings now, chat completions stubbed

The OpenAI adapter ships in C6 with `embeddings()` fully implemented and `chat_completion()` raising `ProviderUnsupportedError("OpenAI chat-completions are not yet implemented; lands with B6")`. This **partially closes B6** — the adapter framing, the auth-header wiring, the streaming SSE plumbing infrastructure, and the error-translation matrix are all in place. B6 (when it runs) only adds the chat-completion translation surface, not a fresh adapter.

This split keeps C6 narrowly scoped (don't expand to a full second chat adapter) while leaving the door open for B6 to land on top of the OpenAI base without rebuilding it.

### `gateway.yaml.example`: the alias is already there

`gateway.yaml.example` already declares an `embedding` alias pointing at `openai-prod/text-embedding-3-small` (committed in B3). C6 makes this alias **functional**: the gateway will dispatch `embedding`-aliased requests to a real OpenAI adapter when the operator's `OPENAI_API_KEY` is set. Operators with no OpenAI key see the gateway's structured `provider_unavailable` envelope (the same shape as the existing `anthropic-prod` no-key path); the embed-on-read fallback in the KB query handler logs the failure and returns the matched chunks at their lower un-embedded recall.

### Backfill mechanism

Reuse the existing `arq` ingest worker — add a new job function `embed_chunks_job(file_id)` that walks `document_chunks.embedding IS NULL` for the file's document and submits batches to `/v1/embeddings`. Register the job in `WorkerSettings.functions`. **Why one worker, not two:** a separate `embed-worker` would duplicate the Redis pool + DB engine + arq plumbing for no gain — embedding generation is light I/O work, not a separate concurrency profile from ingestion.

Triggers:

1. **On KB attachment** — `POST /api/v1/knowledge-bases/{id}/files` enqueues `embed_chunks_job(file_id)` if any chunks for that file have NULL embeddings.
2. **On ingest completion** — for forward compatibility, the C5 ingest pipeline gains an "after persist" hook that enqueues `embed_chunks_job` automatically. Pre-C6 chunks (NULL embeddings persisted before C6 lands) are picked up by the on-attachment trigger; post-C6 chunks get embedded as part of normal ingestion.
3. **Lazy at query time** — if any retrieved chunk has `embedding IS NULL` after the vector search side returns nothing useful, the query handler synchronously embeds those chunks and persists. This guards against "user queries before backfill completes."

### Hybrid score combination

**Min-max normalization, then linear combine.** For each query:

1. Run the vector search: `SELECT id, embedding <=> :q AS distance FROM document_chunks WHERE ... ORDER BY distance LIMIT 4*top_k`. Convert distance to similarity: `vector_score = 1 - distance` (cosine distance is in [0, 2] for normalized embeddings; we clamp to [0, 1] in code). Note: some chunks won't appear in this set (their embedding may be NULL or just not in top-4k).
2. Run the FTS search: `SELECT id, ts_rank_cd(content_tsv, plainto_tsquery('english', :q)) AS rank FROM document_chunks WHERE ... ORDER BY rank DESC LIMIT 4*top_k`.
3. Union the two candidate sets. For chunks present in only one side, the missing score is treated as the side's minimum (effectively zero contribution from that side).
4. Min-max normalize each side's scores to [0, 1] across the union.
5. `hybrid_score = (1 - alpha) * vector_norm + alpha * fts_norm`. `alpha=0` → vector-only; `alpha=1` → FTS-only; `alpha=0.5` → equal weight.
6. Return top-k by `hybrid_score`.

**Why min-max not z-score:** z-score requires a non-trivial standard deviation (which fails on small candidate sets — common at M1 scale where a KB might have 100 chunks total). Min-max is robust at any scale, gives values in [0, 1] that are intuitive to operators, and the formula is reversible (operators can read the score and know roughly where it sits in the range).

The formula is documented in code (`api/app/knowledge/retrieval.py` docstring) and in `docs/db-schema.md` (where the `document_chunks` indexes are documented).

### Vector index: keep ivfflat (don't switch to HNSW)

C5's migration already created `idx_chunks_embedding` as `ivfflat (embedding vector_cosine_ops) WITH (lists = 100)`. We keep it. HNSW would give better recall on larger corpora, but at M1 scale (a KB has at most a few thousand chunks) the differential is invisible. Switching to HNSW is a tightly-scoped follow-up if a deployment ever hits the scale where it matters.

## Consequences

### Positive

- **Schema unchanged:** `vector(1536)` already matches OpenAI's default. No destructive ALTER.
- **Partial B6 closure:** the adapter framing, auth path, error translation, and httpx pool are all built once.
- **`tiktoken` closes the C5 token-count deferral** as a side effect.
- **Operator-friendly:** most operators already hold an OpenAI key.
- **Reversible:** the `embedding` alias is a config field; operators can swap the backing provider without touching code (once Voyage / local adapters exist).
- **Mode-2 path preserved:** Operators running fully air-gapped can repoint the alias at a future Ollama / local adapter; the alias indirection means application code never names a provider directly.

### Negative

- **OpenAI dependency for embeddings.** Operators with no OpenAI key cannot land embeddings until they configure one (or until a Voyage/local adapter lands). The KB still returns FTS-only results in that state — degraded but functional.
- **Privacy posture.** OpenAI's standard API does not commit to zero-data-retention by default. Operators with stricter posture should swap to a ZDR contract or a local model. Documented in `gateway.yaml.example` (the existing `embedding` alias's tier reflects this).
- **Cost.** `text-embedding-3-small` is $0.02 / million tokens — negligible at M1 scale (a 100-chunk KB at 500 tokens/chunk = $0.001), but the cost-tracking code path exercises this.

### Neutral

- **No `openai` Python SDK.** Per PRD §4 / B3's posture, the adapter hand-rolls httpx. The OpenAI Embeddings wire format is small enough that this is a 100-line surface, not a 1000-line one.
- **B6 reduced scope.** When B6 lands, OpenAI chat completions are an addition to the existing OpenAI adapter, not a fresh subclass. Vertex/Bedrock/Ollama still need their own adapters.

## Companion artifacts

- `gateway/app/providers/openai.py` — OpenAI adapter (embeddings + chat-completion stub).
- `gateway/app/api/inference.py` — real `/v1/embeddings` handler.
- `api/app/knowledge/` — KB ORM, schemas, retrieval, embedding service.
- `api/app/api/knowledge_bases.py` — CRUD + query handlers.
- `api/alembic/versions/0007_create_knowledge_bases.py` — migration.
- `docs/db-schema.md` — KB table doc; hybrid-score formula.
- `docs/api/{backend,gateway}-openapi.yaml` — real shapes.
- `gateway.yaml.example` — `embedding` alias documentation refresh.
- Token-counting code paths in `api/app/knowledge/embed.py`.

## Alternatives considered

### Voyage AI as the first adapter

Voyage's `voyage-law-2` is the best legal-domain embedder we could pick. Rejected for M1 because the operator base for Voyage is smaller than for OpenAI; we want to ship the highest-coverage default. Voyage adapter remains a tracked deferred enhancement.

### Local sentence-transformers

Rejected because of dimension mismatch (forces destructive `vector(1536)` ALTER) and because the multi-GB model artifacts compound the C5-era SBOM weight. The path remains open via the `embedding` alias.

### Ollama embedding endpoint

Rejected as the *first* path for the reason that not all operators run Ollama. Ollama embeddings remain compatible — when the B6 Ollama adapter lands, operators can repoint the `embedding` alias.

### Skip the gateway and call OpenAI directly from the worker

Rejected on the same grounds as ADR 0006 §3 rejected it for C5: bypassing the gateway introduces a parallel auth path, parallel cost-tracking, and parallel anonymization. The gateway is the security boundary; the worker stays inside the boundary.

### Use `cl100k_base` for everything via `tiktoken`

Adopted in part. We use `cl100k_base` for `text-embedding-3-*` (OpenAI's default for the 3-series). For non-OpenAI embedding paths (when they land), the tokenizer is whatever that adapter recommends; `tiktoken`'s mapping is OpenAI-specific.

### Wait for B6 to ship the OpenAI adapter first

Rejected because B6 is currently optional (per `docs/M1-PROGRESS.md` "B6 — additional provider adapters (optional)"). Sequencing the embeddings work behind it would block C6 indefinitely. The compromise: C6 ships the OpenAI adapter with embeddings only; B6 (when it runs) extends it with chat completions.
