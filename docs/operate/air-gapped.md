# Use AI without an internet connection

LQ.AI can be configured to use models on computers you control instead of a cloud
provider. The project calls this **Mode 2** — local inference via Ollama — because
nothing in the *chat* inference path needs to reach the internet once the images and
models are already on the host. To work without the internet at all, you also need
the software, models and document-processing files downloaded in advance, and every
enabled feature — not only chat — configured to stay within your network. This page
is the install step plus an honest account of what's actually been verified about
that claim.

> [!NOTE]
> **Professional duty** — Choosing Mode 2 for a matter is a confidentiality decision,
> not only a performance one — it's the configuration where nothing in a prompt
> leaves your infrastructure. [PRD §1.5](../PRD.md#15-deployment-modes-and-the-inference-choice-spectrum)
> treats air-gap as the strictest inference tier and lets a Project's declared
> minimum tier force it for privileged work. That's a call for whoever is
> responsible for the matter, not a default the software should make silently on
> your behalf.

## Download what you'll need

Before disconnecting, collect the Docker images, software packages, AI models and
document-processing files. Turn off cloud models, cloud backup choices, external
tools and other connections you won't use.

If you're building a genuinely offline install, ingest at least one PDF (if you
leave Docling enabled — see "Prepare document processing before disconnecting"
below) and pull your Ollama model (see "Choose a model you have installed" below)
while you still have network access — before you cut the connection — so both are
cached, and budget for both downloads in whatever image-mirroring plan you're using
to get the container images onto the isolated network in the first place.

## Choose a model you have installed

The example maps `local` and `local-thinking` to `qwen3.5:9b`, and `local-fast` to
`qwen3.5:4b-nvfp4`. Pulling one model file covers both `local` and `local-thinking`;
it does not install `local-fast`'s tag. Check both the working `gateway.yaml` file
and Ollama's list of installed models.

Start the stack with the local profile to add the Ollama sidecar:

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

`gateway.yaml.example` ships three Tier-1 aliases routed at `http://ollama:11434`:
`local` and `local-thinking` (both `qwen3.5:9b`), and `local-fast`
(`qwen3.5:4b-nvfp4`); repoint any of them and pull the matching tag if you want a
different model ([`docs/quickstart.md`](../quickstart.md)). All three local aliases
ship with `fallback: []`; keep it that way for any alias an air-gapped deployment
routes to, so a missing local model fails visibly instead of falling through to a
cloud target.

## Check chat and document search separately

Document search uses its own model to turn text into numbers that can be compared by
meaning — these are called embeddings. For offline use, that model must run locally
too. A `ready` upload only confirms text extraction; it doesn't confirm that search
is working.

> [!CAUTION]
> **Silent failure** — Text extraction and chunking run locally in `ingest-worker` —
> plain text and Markdown need no model at all, PDF goes through PyMuPDF
> (`api/app/pipeline/parsers.py`) — and the file reports `ready` as soon as that step
> finishes (`api/app/pipeline/ingest.py`). Embedding is a separate job queued
> afterwards (`api/app/workers/document_pipeline.py`) that goes through the
> gateway's `embedding` alias, which `gateway.yaml.example` points at OpenAI
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
> whatever was ingested before the change — only chunks with no vector are ever
> embedded (`api/app/knowledge/embed.py`). Otherwise, accept chat-only operation.

## Try it while disconnected

Test the tasks you expect to use with outside network access actually blocked, not
just configured for it.

## Egress inventory

Check model providers and their fallback choices, document-search models, research
tools and other connectors, email, monitoring destinations and automatic downloads.
A local chat model changes only one part of that list. Prepare required model caches
before disconnecting, and test with outside access actually blocked.

> [!CAUTION]
> **Silent failure** — No CI job in this repository measures what "Mode 2 makes zero
> outbound calls" actually does on the wire. [PRD §6.4](../PRD.md#64-air-gapped-deployment)
> states "No outbound calls in Mode 2 (verified by integration test)" as a property
> of air-gapped deployment; that verification has not been built, tracked as
> [PRD §9 DE-032](../PRD.md#de-032--air-gap-install-verification) /
> [DE-233](../PRD.md#de-233--air-gap-install-verification-ci-test) (design sketched
> in [`docs/contribute/mini-prds/air-gap-install-verification.md`](../contribute/mini-prds/air-gap-install-verification.md)).
> If your deployment needs zero outbound calls as a *proven* property rather than a
> documented intent, this repository does not yet give you that proof — you would
> need to run your own network capture against the stack.

There are two concrete gaps worth planning around directly. First: the first
document you upload still triggers Docling to download roughly 700 MB of layout and
OCR models from Hugging Face, unless they're already cached in the `ingest-hf-cache`
/ `ingest-easyocr-cache` volumes (`docker-compose.yml`) — a download that produces
nothing, since [ADR 0026](../adr/0026-document-ingestion-parser-and-docling.md)
records that Docling has never returned output in this codebase and decides its
removal; until that removal lands, `lq_ai_docling_enabled` (`api/app/config.py`)
still defaults to `True`. See "Prepare document processing before disconnecting"
below for how to avoid or shorten that download. Second: `--profile local` brings up
an empty `ollama` container — the model pull (several GB,
[`docs/quickstart.md`](../quickstart.md)) is the operator's own responsibility and
is not part of any image or volume this repository ships (see "Choose a model you
have installed" above).

## A separate GPU computer is a different choice

You can reach Ollama on another computer through a private network, as the
tailnet-Ollama recipe describes. That still uses a network, and depends on that
network's own DNS, certificates and coordination services — the
[tailnet-Ollama recipe](../../deploy/tailnet-ollama/README.md) requires Tailscale's
MagicDNS and HTTPS Certificates features, for example. It is not evidence that the
installation works with no internet connection: if your Tier-1 inference runs on
separate hardware reached over your own network, rather than on the same host, that
keeps inference inside infrastructure you control, but it isn't air-gapped in the
"no route to the internet" sense above.

## Prepare document processing before disconnecting

The PDF path requires extractable text from PyMuPDF and can also run Docling, which
may download model files. `LQ_AI_DOCLING_ENABLED=false` skips that optional pass at
no cost — [ADR 0026](../adr/0026-document-ingestion-parser-and-docling.md) records
that the pass has never produced output in this codebase. Compose passes this
setting to `ingest-worker` (`docker-compose.yml`); recreate that worker after
changing it. This does not add OCR or make scanned or encrypted PDFs readable
(`api/app/pipeline/parsers.py`). Plain UTF-8 text and Markdown avoid these
PDF-processing downloads entirely — they skip the parser thread altogether
(`api/app/pipeline/ingest.py`), so a `.md` or `.txt` upload warms nothing.

On a fresh install, the Docling download can outrun the parse budget —
`LQ_AI_DOCLING_TIMEOUT_SECONDS`, 300 seconds by default (`api/app/config.py`,
`docker-compose.yml`). [PRD §9, DE-351](../PRD.md#de-351--first-run-document-ingestion-times-out-on-the-docling-model-download-and-the-file-is-left-stuck-in-processing)
records the original defect, a file left in `processing` with no error; as of the
checked commit the parse runs under a soft timeout that marks the file `failed` with
`ingestion_error` set to `ingestion_timeout` and says to retry once the models are
cached (`api/app/pipeline/ingest.py`) — the download itself carries on in the
background, so the retry succeeds.

## Check the embedding alias as well

The embedding alias in the working `gateway.yaml` must point to an installed local
model suitable for document search. An installed chat model is not automatically an
embedding model. Check that every selected local alias has the intended provider and
no cloud fallback before blocking outside access. A successful model-list request
checks availability, not answer quality or a complete offline workflow. See "Check
chat and document search separately" above for what breaks — and what doesn't —
while the embedding alias still points at a cloud model, and "Choose a model you
have installed" above for why local aliases ship with `fallback: []`.

## List models already installed in the Compose Ollama service

For a source install that uses the local profile, this shows what's already pulled
without downloading a model or sending a prompt:

```bash
docker compose exec ollama ollama list
```

Compare the names against the aliases and fallbacks in your working `gateway.yaml`.
If you run Ollama on the host instead of in the Compose stack, run `ollama list` on
that host and point `OLLAMA_BASE_URL` at it ([`docs/quickstart.md`](../quickstart.md)).

## Next

- [Install with Docker Compose](../../README.md#quick-start)
- [What leaves my deployment](../trust/what-leaves-my-deployment.md)
- [Hardware sizing](hardware-sizing.md)
