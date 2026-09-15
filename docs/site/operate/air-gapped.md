---
title: Air-gapped and local-only inference
description: Run LQ.AI with local-only inference, and what the repository can — and cannot yet — prove about its network behavior.
audience: [operator, evaluator]
status: draft
sources:
  - README.md
  - docs/PRD.md
  - docker-compose.yml
  - docs/contribute/mini-prds/air-gap-install-verification.md
  - docs/HONEST-STATE.md
  - gateway.yaml.example
  - docs/quickstart.md
sidebar:
  order: 14
---

Mode 2 — local inference via Ollama — is the deployment the project calls air-gap-capable: nothing in the *chat* inference path needs to reach the internet once the images and models are on the host. This page is the install step plus an honest account of what's actually been verified about that claim.

:::caution[Silent failure]
Document ingestion and knowledge-base search do not run locally. The default `embedding` alias in `gateway.yaml.example` points at OpenAI `text-embedding-3-small`; with no OpenAI key reachable, embedding calls fail and ingestion/search break with no in-app signal (PRD DE-355). Repoint the `embedding` alias at a local model whose dimension matches the `document_chunks.embedding` column, or accept chat-only operation.
:::

:::note[Professional duty]
Choosing Mode 2 for a matter is a confidentiality decision, not only a performance one — it's the configuration where nothing in a prompt leaves your infrastructure. [PRD §1.5](../../PRD.md#15-deployment-modes-and-the-inference-choice-spectrum) treats air-gap as the strictest inference tier and lets a Project's declared minimum tier force it for privileged work. That's a call for whoever is responsible for the matter, not a default the software should make silently on your behalf.
:::

## Bring it up

<!-- include: README.md from="### Providers and air-gapped deployments" to="### Troubleshooting" -->

Only one service is added by `--profile local`: the `ollama` sidecar. An earlier `paddleocr` sidecar for scanned-PDF OCR was sketched into the same profile and never implemented — its image was never published, so `docker compose --profile local up` would attempt the missing pull and abort the whole profile, including `ollama` (recorded directly in `docker-compose.yml`'s comments as issue #99). The placeholder has been removed; scanned-PDF OCR itself remains unbuilt (tracked as DE-320) rather than silently claimed.

`--profile local` starts an empty Ollama. Pull a model into it once, while you still have network:

```bash
docker compose exec ollama ollama pull qwen3.5:9b
```

`gateway.yaml.example` ships `local-fast` (Qwen 3.5 4B) and `local-thinking` (Qwen 3.5 9B) aliases routed at `http://ollama:11434`; repoint either alias and pull the matching tag if you want a different model (`docs/quickstart.md`).

## Egress inventory

:::caution[Silent failure]
No CI job in this repository measures what "Mode 2 makes zero outbound calls" actually does on the wire. A mini-PRD (`docs/contribute/mini-prds/air-gap-install-verification.md`) proposes exactly that — a deny-all-egress network policy plus a packet capture asserting zero non-private-destination traffic during a driven chat — and it is **open for contribution** as of the checked commit; no such workflow exists under `.github/workflows/`. [PRD §6.4](../../PRD.md#64-air-gapped-deployment) states "No outbound calls in Mode 2 (verified by integration test)" as a property of air-gapped deployment; that verification has not been built. If your deployment needs zero outbound calls as a *proven* property rather than a documented intent, this repository does not yet give you that proof — you would need to run your own network capture against the stack, or contribute the mini-PRD's CI job yourself.
:::

There are two concrete gaps worth planning around directly. First: the first document you upload triggers Docling to download roughly 700 MB of layout and OCR models from Hugging Face, unless they're already cached in the `ingest-hf-cache` / `ingest-easyocr-cache` volumes (`docker-compose.yml`). On a fresh install that download can outrun the ingestion job's five-minute timeout, leaving the file stuck in `processing` with no visible error ([PRD §9, DE-351](../../PRD.md#de-351--first-run-document-ingestion-times-out-on-the-docling-model-download-and-the-file-is-left-stuck-in-processing)). Second: `--profile local` brings up an empty `ollama` container — the model pull (several GB, `docs/quickstart.md`) is the operator's own responsibility and is not part of any image or volume this repository ships. If you're building a genuinely offline install, ingest at least one document and pull your Ollama model while you still have network access — before you cut the connection — so both are cached, and budget for both downloads in whatever image-mirroring plan you're using to get the container images onto the isolated network in the first place.

## Related: a remote GPU host is not the same as air-gapped

If your Tier-1 inference runs on separate hardware reached over your own network, rather than on the same host, that keeps inference inside infrastructure you control — but it isn't air-gapped in the "no route to the internet" sense above. See the [tailnet-Ollama recipe](recipes/tailnet-ollama.md) for that shape.

## Next

- [Install with Docker Compose](install-docker-compose.md)
- [Trust centre](../trust/index.md)
- [Hardware sizing](hardware-sizing.md)
