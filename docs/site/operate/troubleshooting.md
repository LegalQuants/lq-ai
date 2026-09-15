---
title: Troubleshooting
description: Search by the error you're actually seeing — one index over every recovery step published across this site.
audience: [operator]
status: draft
sources:
  - docs/quickstart.md
  - docs/INSTALL-MAC.md
  - deploy/tailnet-ollama/README.md
  - README.md
  - docker-compose.yml
  - docs/PRD.md
sidebar:
  order: 28
---

The full recovery text for a first run lives on [Quickstart](../start/quickstart.md#troubleshooting); for the macOS app, on [Install on macOS](install-macos.md). Rather than repeat either wholesale, this page is the thing J11 asks for: one place to search by what you're actually seeing, that points at wherever the fix actually lives — including entries neither of those pages covers.

## Install and first run

| You see | Fix |
|---|---|
| `docker compose up` hangs with no output | Normal on the very first run — check `docker compose logs -f` for an active pull. [Quickstart → Troubleshooting](../start/quickstart.md#troubleshooting) |
| `ports are not available: ... bind: address already in use` on `5432`, `6379`, or `9000`/`9001` | You already run a host Postgres/Redis/MinIO. Remap the host-side port (`POSTGRES_HOST_PORT`, etc.) in `.env`. [Quickstart → Troubleshooting](../start/quickstart.md#troubleshooting) |
| "First-run admin password" never appears in the logs | `docker compose exec api python -m app.cli reset-admin-password` on an established deployment; see the fresh-install reset path in [Quickstart](../start/quickstart.md#troubleshooting) |
| `error while interpolating services...: required variable ... is missing a value` for a Slack/Teams variable you never intended to set | Fixed as of the checked commit — you're likely on a stale `docker-compose.yml`; re-pull the version matching your install |
| **A second checkout of this repo wiped your first deployment's data** | Two clones both named `lq-ai/` share the same Compose project name and therefore the same volumes — set a distinct `COMPOSE_PROJECT_NAME` in each `.env`. [Install with Docker Compose](install-docker-compose.md#where-your-data-lives) |
| "Docker is not running" (macOS app) | Start Docker Desktop, wait for *Running*, then click **Start** in the LQ.AI app. [Install on macOS](install-macos.md) |
| Chat says "no model configured" / "no provider · default" | No provider key is set yet. Add one via `.env` or **Admin/Configure → Provider keys** — see [Quickstart → Troubleshooting](../start/quickstart.md#troubleshooting) and [Install on macOS](install-macos.md) |

## Running

| You see | Fix |
|---|---|
| A verification error against your own upload, not the sample NDA | Check the document has extractable text — there is no OCR step; a scanned image parses to nothing. [Quickstart → Troubleshooting](../start/quickstart.md#troubleshooting) |
| "Tier N not allowed" | Your deployment's `allowed_tiers_global` disallows that tier, or the routed provider doesn't match your policy. [Quickstart → Troubleshooting](../start/quickstart.md#troubleshooting) |
| The gateway refuses to start, naming a provider `base_url` | The egress guard refuses plaintext `http` to anything but a small local allowlist — the exact refusal text is `plaintext http base_url is only permitted for local providers (host.docker.internal, localhost, ollama, vllm, or a loopback/private IP); host '<host>' must use https` (`deploy/tailnet-ollama/README.md`). Point the provider at an `https://` endpoint — see the [tailnet-Ollama recipe](recipes/tailnet-ollama.md) and [Reverse proxy and TLS](reverse-proxy-tls.md) |
| A chat returns empty, or seems to "forget" an attached document a few turns in | Not a bug report you need to file first — read [Something is wrong → Silent degrade](something-is-wrong.md#silent-degrade), which names the specific defaults responsible |
| A document sits in `processing` and never finishes | First-ingestion Docling model download (~700 MB) can outrun the ingest job's timeout on a slow connection — see [Air-gapped and local-only inference → Egress inventory](air-gapped.md#egress-inventory) |
| Ingestion completes but knowledge-base search finds nothing relevant | Check `documents.ingest_status` for `embed_failed` / `partial` — see [Something is wrong](something-is-wrong.md#silent-degrade) |
| A stuck-looking first start on the macOS app | Normal — the first run downloads the engine and document-processing models; watch the live progress, sign in once it reaches **Running**. [Install on macOS](install-macos.md) |
| Forgot the admin password (macOS app) | `docker compose ... exec -T api python -m app.cli reset-admin-password` against the bundled compose file — the exact command is in [Install on macOS](install-macos.md) |

## After an upgrade or a security event

Neither of these is a day-zero FAQ item — they're runbooks in their own right: [Upgrade — if it fails halfway](upgrade.md#if-it-fails-halfway) and [Rotate a leaked provider key](rotate-a-leaked-key.md).

## Not here

If your symptom isn't above, it isn't documented in the repository as of the checked commit. `docs/quickstart.md`'s own troubleshooting section ends the same way: file a GitHub issue with the `quickstart` label, including your OS and Docker version, `docker compose ps` output, and the relevant log excerpt.

## Next

- [Something is wrong](something-is-wrong.md)
- [Quickstart](../start/quickstart.md)
- [Install with Docker Compose](install-docker-compose.md)
