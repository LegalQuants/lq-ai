# Troubleshooting

The full recovery text for a first run lives on [Quickstart](../quickstart.md#troubleshooting); for the macOS app, on [Install on macOS](../INSTALL-MAC.md). Rather than repeat either wholesale, this page is one place to search by what you're actually seeing, that points at wherever the fix actually lives — including entries neither of those pages covers.

## Install and first run

| You see | Fix |
|---|---|
| `docker compose up` hangs with no output | Normal on the very first run — check `docker compose logs -f` for an active pull. [Quickstart → Troubleshooting](../quickstart.md#troubleshooting) |
| `ports are not available: ... bind: address already in use` on `5432`, `6379`, or `9000`/`9001` | You already run a host Postgres/Redis/RustFS (or MinIO). Remap the host-side port (`POSTGRES_HOST_PORT`, `OBJECT_STORE_API_HOST_PORT`, etc.) in `.env`. [Quickstart → Troubleshooting](../quickstart.md#troubleshooting) |
| "First-run admin password" never appears in the logs | `docker compose exec api python -m app.cli reset-admin-password` on an established deployment; see the fresh-install reset path in [Quickstart](../quickstart.md#troubleshooting) |
| `error while interpolating services...: required variable ... is missing a value` for a Slack/Teams variable you never intended to set | Fixed as of the checked commit — you're likely on a stale `docker-compose.yml`; re-pull the version matching your install |
| **A second checkout of this repo wiped your first deployment's data** | Two clones both named `lq-ai/` share the same Compose project name and therefore the same volumes — set a distinct `COMPOSE_PROJECT_NAME` in each `.env`. [Install with Docker Compose](../../README.md#where-your-data-lives) |
| "Docker is not running" (macOS app) | Start Docker Desktop, wait for *Running*, then click **Start** in the LQ.AI app. [Install on macOS](../INSTALL-MAC.md) |
| Chat says "no model configured" / "no provider · default" | No provider key is set yet. Add one via `.env` or **Admin/Configure → Provider keys** — see [Quickstart → Troubleshooting](../quickstart.md#troubleshooting) and [Install on macOS](../INSTALL-MAC.md) |
| Upgrading an existing bundled-store install and the object-store container won't come up | You likely need the dedicated migration procedure, not an ordinary upgrade — see [Upgrade → Operator-action releases](upgrade.md#operator-action-releases) and the [MinIO to RustFS migration runbook](../runbooks/minio-to-rustfs.md) |

## Running

| You see | Fix |
|---|---|
| A verification error against your own upload, not the sample NDA | Check the document has extractable text — there is no OCR step; a scanned image parses to nothing. [Quickstart → Troubleshooting](../quickstart.md#troubleshooting) |
| An upload lands in `failed` and its `ingestion_error` names a code | Read the code before retrying — each means a different thing (`api/app/pipeline/ingest.py`). `unsupported_type`: only PDF and plain-text/Markdown are accepted, by MIME or, when the browser's MIME is unreliable, by a `.txt`/`.md`/`.markdown` extension; office formats are not. `unsupported_content`: an encrypted PDF (an image-only/scanned PDF isn't caught here — see the row above; it parses to empty text and ingestion completes silently as `ready` with 0 chunks). `parse_failed`: a corrupt PDF. `decode_error`: a text/Markdown upload that isn't valid UTF-8 or contains a NUL byte. `ingestion_timeout`: parsing exceeded `LQ_AI_DOCLING_TIMEOUT_SECONDS` (default 300 s) — on a first run that is usually the Docling model download still in progress; check the `ingest-worker` logs and retry once it has finished |
| "Tier N not allowed" | Your deployment's `allowed_tiers_global` disallows that tier, or the routed provider doesn't match your policy. [Quickstart → Troubleshooting](../quickstart.md#troubleshooting) |
| The gateway refuses to start, naming a provider `base_url` | The egress guard refuses plaintext `http` to anything but a small local allowlist — the exact refusal text is `plaintext http base_url is only permitted for local providers (host.docker.internal, localhost, ollama, vllm, or a loopback/private IP); host '<host>' must use https` (`deploy/tailnet-ollama/README.md`). The allowlist is literal (`gateway/app/providers/base_url_policy.py`): a private hostname of your own isn't on it, and the private ranges it accepts are RFC 1918 plus loopback and IPv6 unique-local only — CGNAT (`100.64.0.0/10`, the range Tailscale assigns) is deliberately excluded, so being on a private network doesn't exempt the address. Point the provider at an `https://` endpoint — see the [tailnet-Ollama recipe](../../deploy/tailnet-ollama/README.md) and [Reverse proxy and TLS](reverse-proxy-tls.md) |
| A chat returns empty, or seems to "forget" an attached document a few turns in | Not a bug report you need to file first — read [Something is wrong → Silent degrade](something-is-wrong.md#silent-degrade), which names the specific defaults responsible |
| A document sits in `processing` and never finishes | The first ingestion still downloads ~700 MB of Docling models (`lq_ai_docling_enabled` defaults to `True` in `api/app/config.py`), and that download can outrun the ingest job's timeout on a slow connection. The download buys nothing: [ADR 0026](../adr/0026-document-ingestion-parser-and-docling.md) (Accepted 2026-08-23) records that Docling has never produced output in this codebase and decides its removal, though the flag still defaults on as of the checked commit; parsing is PyMuPDF-only. See [Air-gapped and local-only inference → Egress inventory](air-gapped.md#egress-inventory) |
| Ingestion completes but knowledge-base search finds nothing relevant | Check `documents.ingest_status` for `embed_failed` / `partial` — see [Something is wrong](something-is-wrong.md#silent-degrade) |
| A stuck-looking first start on the macOS app | Normal — the first run downloads the engine and document-processing models; watch the live progress, sign in once it reaches **Running**. [Install on macOS](../INSTALL-MAC.md) |
| Forgot the admin password (macOS app) | `docker compose ... exec -T api python -m app.cli reset-admin-password` against the bundled compose file — the exact command is in [Install on macOS](../INSTALL-MAC.md) |

## After an upgrade or a security event

Neither of these is a day-zero FAQ item — they're runbooks in their own right: [Upgrade — if it fails halfway](upgrade.md#if-it-fails-halfway) and [Rotate a leaked provider key](rotate-a-leaked-key.md).

## Not here

If your symptom isn't above, it isn't documented in the repository as of the checked commit. `docs/quickstart.md`'s own troubleshooting section ends the same way: file a GitHub issue with the `quickstart` label, including your OS and Docker version, `docker compose ps` output, and the relevant log excerpt. `docker compose logs --tail=100 api gateway ingest-worker arq-worker`, run from the checkout that owns the deployment, collects the four services that do the work — read the excerpt before you paste it, since these logs can contain sensitive details.
