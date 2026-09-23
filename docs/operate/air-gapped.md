# Air-gapped and local-only inference

Mode 2 — local inference via Ollama — is the deployment the project calls
air-gap-capable: nothing in the *chat* inference path needs to reach the internet
once the images and models are on the host. This page is the install step plus an
honest account of what's actually been verified about that claim.

> [!CAUTION]
> **Silent failure** — Chat and document search have separate model settings. Text
> extraction and chunking run locally in `ingest-worker` — plain text and Markdown
> need no model at all, PDF goes through PyMuPDF (`api/app/pipeline/parsers.py`) —
> and the file reports `ready` as soon as that step finishes
> (`api/app/pipeline/ingest.py`). Embedding is a separate job queued afterwards
> (`api/app/workers/document_pipeline.py`) that goes through the gateway's
> `embedding` alias, which `gateway.yaml.example` points at OpenAI
> `text-embedding-3-small`. The Ollama adapter's `embeddings` method raises
> `ProviderUnsupportedError` (`gateway/app/providers/ollama.py`), so no local
> embedding path ships as of the checked commit (PRD DE-355). With no OpenAI key
> reachable, a `ready` file has no vectors: the vector side of hybrid search can't
> see it, but search doesn't come up empty — the KB query API and chat RAG both
> catch the query-embedding failure and fall back to full-text (keyword) search
> (`api/app/api/knowledge_bases.py:756-774`, `api/app/api/chats.py:1119-1136`), and
> Postgres FTS matches a chunk whether or not it has a vector
> (`api/app/knowledge/retrieval.py:231-246`). What's lost is semantic ranking, not
> search itself. The upload's own status doesn't reflect the embed failure either;
> it's recorded on the document's `ingest_status` (`embed_failed`, or `partial`) in
> the knowledge-base document listing (`api/app/knowledge/embed.py`,
> `api/app/schemas/knowledge.py`). Repointing the alias at a local model needs an
> embedding-capable adapter, a model whose dimension matches the 1536-wide
> `document_chunks.embedding` column (or a column migration), and re-embedding
> whatever was ingested before the change — only
> chunks with no vector are ever embedded (`api/app/knowledge/embed.py`). Otherwise,
> accept chat-only operation.

> [!NOTE]
> **Professional duty** — Choosing Mode 2 for a matter is a confidentiality decision,
> not only a performance one — it's the configuration where nothing in a prompt
> leaves your infrastructure. [PRD §1.5](../PRD.md#15-deployment-modes-and-the-inference-choice-spectrum)
> treats air-gap as the strictest inference tier and lets a Project's declared
> minimum tier force it for privileged work. That's a call for whoever is
> responsible for the matter, not a default the software should make silently on
> your behalf.

## Bring it up

```bash
docker compose --profile local up -d
```

Only one service is added by `--profile local`: the `ollama` sidecar. An earlier
`paddleocr` sidecar for scanned-PDF OCR was sketched into the same profile and never
implemented — its image was never published, so `docker compose --profile local up`
would attempt the missing pull and abort the whole profile, including `ollama`
(recorded directly in `docker-compose.yml`'s comments as issue #99). The placeholder
has been removed; scanned-PDF OCR itself remains unbuilt (tracked as DE-320) rather
than silently claimed.

`--profile local` starts an empty Ollama. Pull a model into it once, while you still
have network:

```bash
docker compose exec ollama ollama pull qwen3.5:9b
```

`gateway.yaml.example` ships `local-fast` (`qwen3.5:4b-nvfp4`) and `local-thinking`
(`qwen3.5:9b`) aliases routed at `http://ollama:11434`; repoint either alias and pull
the matching tag if you want a different model ([`docs/quickstart.md`](../quickstart.md)).
`docker compose exec ollama ollama list` shows what the sidecar already holds —
compare the tags against the aliases in your `gateway.yaml`. Both local aliases ship
with `fallback: []`; keep it that way for any alias an air-gapped deployment routes
to, so a missing local model fails visibly instead of falling through to a cloud
target.

## Egress inventory

> [!CAUTION]
> **Silent failure** — No CI job in this repository measures what "Mode 2 makes zero
> outbound calls" actually does on the wire. A mini-PRD
> ([`docs/contribute/mini-prds/air-gap-install-verification.md`](../contribute/mini-prds/air-gap-install-verification.md))
> proposes exactly that — a deny-all-egress network policy plus a packet capture
> asserting zero non-private-destination traffic during a driven chat — and it is
> **open for contribution** as of the checked commit; no such workflow exists under
> `.github/workflows/`. [PRD §6.4](../PRD.md#64-air-gapped-deployment) states "No
> outbound calls in Mode 2 (verified by integration test)" as a property of
> air-gapped deployment; that verification has not been built. If your deployment
> needs zero outbound calls as a *proven* property rather than a documented intent,
> this repository does not yet give you that proof — you would need to run your own
> network capture against the stack, or contribute the mini-PRD's CI job yourself.

There are two concrete gaps worth planning around directly. First: the first
document you upload still triggers Docling to download roughly 700 MB of layout and
OCR models from Hugging Face, unless they're already cached in the `ingest-hf-cache`
/ `ingest-easyocr-cache` volumes (`docker-compose.yml`) — a download that produces
nothing, since [ADR 0026](../adr/0026-document-ingestion-parser-and-docling.md)
records that Docling has never returned output in this codebase and decides its
removal; until that removal lands, `lq_ai_docling_enabled` (`api/app/config.py`)
still defaults to `True`. On a fresh install that download can outrun the parse
budget — `LQ_AI_DOCLING_TIMEOUT_SECONDS`, 300 s by default (`api/app/config.py`,
`docker-compose.yml`). [PRD §9, DE-351](../PRD.md#de-351--first-run-document-ingestion-times-out-on-the-docling-model-download-and-the-file-is-left-stuck-in-processing)
records the original defect, a file left in `processing` with no error; as of the
checked commit the parse runs under a soft timeout that marks the file `failed` with
`ingestion_error` set to `ingestion_timeout` and says to retry once the models are
cached (`api/app/pipeline/ingest.py`), and the download carries on in the
background, so the retry succeeds. Only PDFs take this path: plain text and Markdown
uploads skip the parser thread entirely (`api/app/pipeline/ingest.py`), so a `.md`
upload warms nothing. Setting `LQ_AI_DOCLING_ENABLED=false` on `ingest-worker`
(`docker-compose.yml` passes it through; recreate the worker after changing it)
skips the Docling pass and its download at no cost, since ADR 0026 records the pass
never produced output — PyMuPDF still needs extractable text, and this adds no OCR:
scanned and encrypted PDFs remain unsupported (`api/app/pipeline/parsers.py`).
Second: `--profile local` brings up an empty `ollama` container — the model pull
(several GB, [`docs/quickstart.md`](../quickstart.md)) is the operator's own
responsibility and is not part of any image or volume this repository ships. If
you're building a genuinely offline install, ingest at least one PDF (if you leave
Docling enabled) and pull your Ollama model while you still have network access —
before you cut the connection — so both are cached, and budget for both downloads in
whatever image-mirroring plan you're using to get the container images onto the
isolated network in the first place.

## Related: a remote GPU host is not the same as air-gapped

If your Tier-1 inference runs on separate hardware reached over your own network,
rather than on the same host, that keeps inference inside infrastructure you control
— but it isn't air-gapped in the "no route to the internet" sense above. See the
[tailnet-Ollama recipe](../../deploy/tailnet-ollama/README.md) for that shape.

## Next

- [Install with Docker Compose](../../README.md#quick-start)
- [What leaves my deployment](../trust/what-leaves-my-deployment.md)
- [Hardware sizing](hardware-sizing.md)
