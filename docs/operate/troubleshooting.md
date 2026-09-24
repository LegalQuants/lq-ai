# Troubleshooting

Start with the quickstart's own [Troubleshooting](../quickstart.md#troubleshooting) section to compare what happened against the expected setup; for the macOS app, start with [Install on macOS](../INSTALL-MAC.md). This page is the second stop — search by what you're actually seeing, and it points at wherever the fix actually lives, including some symptoms neither of those pages covers. When you do need to report a problem, include the exact command or action, the response you got, and the relevant log messages.

## Settings and addresses

Run `docker compose config --quiet` first — it parses and validates `docker-compose.yml` against your `.env` without starting anything, and fails loudly if a required secret is missing. Then check for ports already in use, and, if the browser and the API are reached at different addresses, that the API's CORS allowlist includes the browser's address.

**Details**
- **A required secret is missing, or `docker compose up` errors with `error while interpolating services...: required variable ... is missing a value`.** As of the checked commit this no longer fires for the Slack/Teams bridge variables on a default install — `SLACK_CLIENT_ID`, `SLACK_SIGNING_SECRET`, `LQ_AI_TEAMS_BRIDGE_PUBLIC_URL`, and the rest all default to empty in `docker-compose.yml`. Seeing it for one of those variables means you're on a stale `docker-compose.yml`; re-pull the version matching your install.
- **`ports are not available: ... bind: address already in use` on `5432`, `6379`, or `9000`/`9001`.** You already run a host Postgres/Redis/RustFS (or MinIO). Remap the host-side port in `.env` — `POSTGRES_HOST_PORT`, `REDIS_HOST_PORT`, `OBJECT_STORE_API_HOST_PORT`, `OBJECT_STORE_CONSOLE_HOST_PORT` — and re-run. The services still talk to each other over the Docker network at the original port; only how you reach it from the host changes.
- **Browser and API served from different addresses.** Set `LQ_AI_CORS_ORIGINS` in `.env` to the browser's origin — comma-separated if there's more than one (`api/app/config.py`). See [Reverse proxy and TLS](reverse-proxy-tls.md) for the full reverse-proxy case.
- **A second checkout of this repo wiped your first deployment's data.** `docker-compose.yml` pins the Compose project name to `lq-ai` regardless of what you name the folder, so two clones reuse the same containers and volumes — including the database and object store — and `docker compose down` in one tears down the other's data too. Set a distinct `COMPOSE_PROJECT_NAME` in each clone's `.env`, or pass `-p <name>` on every command. See [Where your data lives](../../README.md#where-your-data-lives).

## Models and documents

Check what model the chat's alias actually points to and whether that provider has a key configured. For a document problem, work out which stage failed — upload, text extraction, search preparation (embedding), search, or the answer itself — since each stage's logs and fixes are different.

**Details**
- **Chat says "no model configured", or the bottom-of-chat status footer shows "no provider · default".** No provider key is set yet. Add one via `.env` or **Admin/Configure → Provider keys**, and confirm the chat's model alias resolves to a configured provider in `gateway.yaml` — see [Quickstart → Troubleshooting](../quickstart.md#troubleshooting) and, for the macOS app, [Install on macOS → Provider keys (BYOK)](../INSTALL-MAC.md#5-provider-keys-byok).
- **"Tier N not allowed."** Your deployment's `allowed_tiers_global` disallows that tier, or the routed provider doesn't match your policy — see [Quickstart → Troubleshooting](../quickstart.md#troubleshooting).
- **A document sits in `processing` and never finishes.** The first ingestion on a deployment still downloads roughly 700 MB of Docling layout/OCR models (`lq_ai_docling_enabled` defaults to `True`, `api/app/config.py`), and that download can outrun the ingest job's own timeout on a slow connection. The download buys nothing either way: [ADR 0026](../adr/0026-document-ingestion-parser-and-docling.md) (Accepted 2026-08-23) records that Docling has never produced output in this codebase and decides its removal, though the flag still defaults on as of the checked commit — parsing is PyMuPDF-only. Check the `ingest-worker` logs and retry once the download has finished; see [Use AI without an internet connection → Egress inventory](air-gapped.md#egress-inventory).
- **Ingestion completes but knowledge-base search finds nothing relevant.** Check `documents.ingest_status` for `embed_failed` or `partial` — see [Something is wrong → Silent degrade](something-is-wrong.md#silent-degrade).
- **An attached document seems to "disappear" a few turns into the chat.** The chat-history token/message caps evict the oldest turns first, including the attached-document block — see [Something is wrong → Silent degrade](something-is-wrong.md#silent-degrade).

## Find the right next step

For a first-run failure — the stack won't come up, or the admin password never appeared — use the quickstart and, for the macOS app, the install page. For a stuck document, check the ingest worker's logs and the upload status rather than restarting anything. For a failed update, use the upgrade runbook. For a suspected leaked provider key, revoke it with the provider first, then follow the replacement guide. If none of these explain what you're seeing, report the version, the exact step, and a redacted error rather than resetting the whole installation.

**Details**
- **`docker compose up` hangs with no output.** Normal on the very first run — check `docker compose logs -f` for an active image pull or build. [Quickstart → Troubleshooting](../quickstart.md#troubleshooting).
- **"First-run admin password" never appears in the logs.** Reset it without touching data: `docker compose exec api python -m app.cli reset-admin-password` — this works on a fresh install and an established deployment alike ([Quickstart → Troubleshooting](../quickstart.md#troubleshooting)). On the macOS app, the exact command against the bundled compose file is in [Install on macOS → Recover the desktop admin password](../INSTALL-MAC.md#recover-the-desktop-admin-password).
- **"Docker is not running" (macOS app).** Start Docker Desktop, wait for *Running*, then click **Start** in the LQ.AI app. [Install on macOS](../INSTALL-MAC.md).
- **A stuck-looking first start (macOS app).** Normal — the first run downloads the engine and document-processing models; watch the live progress and sign in once it reaches **Running**. [Install on macOS](../INSTALL-MAC.md).
- **Upgrading an existing bundled-store install and the object-store container won't come up.** You likely need the dedicated migration procedure, not an ordinary upgrade — see [Upgrade → Operator-action releases](upgrade.md#operator-action-releases) and the [MinIO to RustFS migration runbook](../runbooks/minio-to-rustfs.md).
- **A failed update, or one that stops partway through.** [Upgrade → If it fails halfway](upgrade.md#if-it-fails-halfway) — `api` is the sole migrator and both workers wait on its health check, so a failed migration shows up as `api` unhealthy, not as a partial, silently degraded stack.
- **A suspected leaked provider key.** Revoke it with the provider immediately, then work through [Replace a leaked API key](rotate-a-leaked-key.md) — nothing in LQ.AI itself can stop a leaked key from being used elsewhere until the provider invalidates it.
- **Nothing above matches.** It isn't documented in the repository as of the checked commit. File a GitHub issue with the `quickstart` label — include your OS and Docker version, `docker compose ps` output, and a log excerpt (see Inspect startup and background work below for the command, and redact anything sensitive before you paste it).

## Read the upload error before retrying

Each `ingestion_error` code on a `failed` file (`files.ingestion_error`) means something different (`api/app/pipeline/ingest.py`) — read it before retrying:

- **`unsupported_type`** — the pipeline only accepts PDF and plain-text/Markdown, by MIME type or, when the browser's MIME is unreliable, by a `.txt`/`.md`/`.markdown` extension. Office formats (DOCX, RTF, and the rest) aren't handled yet.
- **`unsupported_content`** — an encrypted PDF. (An image-only or scanned PDF isn't caught here — there's no OCR step, so it parses to empty text and ingestion completes silently as `ready` with 0 chunks. A verification error against your own upload, rather than the sample NDA, usually means this — confirm the document carries extractable text before assuming anything else is wrong.)
- **`parse_failed`** — a corrupt PDF.
- **`decode_error`** — a text/Markdown upload that isn't valid UTF-8, or that contains a NUL byte.
- **`ingestion_timeout`** — parsing exceeded `LQ_AI_DOCLING_TIMEOUT_SECONDS` (default 300 seconds). On a first run that's usually the Docling model download still in progress rather than a slow document — check the `ingest-worker` logs and retry once it has finished.

## When the provider address stops the gateway starting

The gateway's egress guard refuses plaintext `http` to anything but a small, named allowlist (`gateway/app/providers/base_url_policy.py`) — the exact refusal is `plaintext http base_url is only permitted for local providers (host.docker.internal, localhost, ollama, vllm, or a loopback/private IP); host '<host>' must use https`. The allowlist is literal: a private hostname of your own isn't on it, and the private ranges it accepts are RFC 1918 plus loopback and IPv6 unique-local only — CGNAT (`100.64.0.0/10`, the range Tailscale assigns) is deliberately excluded, so being on a private or tailnet address doesn't by itself exempt it. Point the provider at an `https://` endpoint instead — see the [tailnet-Ollama recipe](../../deploy/tailnet-ollama/README.md) and [Reverse proxy and TLS](reverse-proxy-tls.md).

## A reasoning model gives an empty answer

Check the provider's response and its output budget before assuming the request itself failed — a reasoning model can spend its entire output budget "thinking" and emit zero visible characters, while the request still reports success.

**Details**
- **GPT-5 / o-series and similar reasoning deployments reject `max_tokens` outright and require `max_completion_tokens` instead.** The gateway's OpenAI-family adapter only renames the field when the provider's entry sets `use_max_completion_tokens: true` in `gateway.yaml` — gated per-provider rather than by model name, since Azure deployment IDs are operator-chosen and OpenAI-compatible local servers may not accept `max_completion_tokens` (`gateway/app/providers/openai.py`; `gateway.yaml.example` sets it on the shipped `openai-prod` and `azure-openai` examples). Leave it unset for `gpt-4o`-class models or a local OpenAI-compatible server that only takes `max_tokens`.
- **The output budget includes reasoning tokens, not just visible words.** On the Anthropic adapter it defaults to `DEFAULT_MAX_TOKENS = 16384` when the caller omits it (`gateway/app/providers/anthropic.py`); a larger ceiling makes a silent empty answer less likely but doesn't rule it out.
- **Two separate timeout layers sit on the inference path, and they aren't equal.** The gateway's provider adapters (Anthropic, OpenAI, Ollama) wait up to 600 seconds for the provider; the API's own client to the gateway waits only 60 seconds and that default isn't overridden for streaming. Neither layer's default removes the other.

For the full picture — including the chat-history token budget that can make an attached document "disappear" a few turns in, and which of the two timeouts actually produces a `504` versus which resets on every streamed chunk — see [Something is wrong → Silent degrade](something-is-wrong.md#silent-degrade). The exact numbers move as the defaults change, so treat this page's summary as a pointer rather than the source of truth.

## Inspect startup and background work

Run these from the checkout that owns the deployment — a second checkout with its own `.env` inspects a different Compose project:

```
docker compose ps
docker compose logs --tail=100 api gateway ingest-worker arq-worker
```

Those four services do the actual work — website requests, model routing, and the two background workers — so a service can report healthy while a specific document or chat still fails. These logs can contain sensitive details; redact them before sharing, including in a GitHub issue.
