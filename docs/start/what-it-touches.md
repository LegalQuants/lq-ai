# What it touches

Read this before the first `docker compose` command, not after. It answers three questions a technical evaluator asks before installing anything: what has to already be true on the host, what the stack occupies once it's running, and where the data actually ends up.

## Prerequisites

Docker Desktop 4.x+ (or Docker Engine 24+ on Linux) and `git`. No other host tooling — no Python, no Node, no language runtime of your own. Plan for roughly 8 GB of free disk space and 6 GB of RAM available to Docker (README "Quick Start"). Provider API keys (Anthropic, OpenAI, etc.) are optional at install time; the stack starts without one and inference calls return "no provider configured" until you add at least one.

Named reference configurations — how much a laptop, a small server, or an air-gapped local-inference host can actually carry — belong on a hardware-sizing page in Operate once one exists; not documented as of this page's checked commit.

## Services and ports

Eight services are always on: `postgres`, `redis`, `rustfs`, `gateway`, `api`, `ingest-worker`, `arq-worker`, `web` (`docker-compose.yml`). `rustfs` replaced a bundled MinIO as the S3-compatible object store (ADR 0036); existing `.env` files that still set `MINIO_*` variables keep working, since `docker-compose.yml` falls back to them when the newer `OBJECT_STORE_*` variables aren't set. Three more are opt-in Compose profiles: `ollama` (`--profile local`, for fully local inference), `slack-bridge` and `teams-bridge` (`--profile slack` / `--profile teams`). Every host-side port is remappable through a `*_HOST_PORT` variable in `.env` if something on your machine already holds the default, and each binds to `${*_BIND_ADDR:-127.0.0.1}` by default (`docker-compose.yml`):

```text
WEB_HOST_PORT=3000
API_HOST_PORT=8000
GATEWAY_HOST_PORT=8001
POSTGRES_HOST_PORT=5432
REDIS_HOST_PORT=6379
OBJECT_STORE_API_HOST_PORT=9000
OBJECT_STORE_CONSOLE_HOST_PORT=9001
```

`POSTGRES_HOST_PORT` is the one that most often collides, typically with a Homebrew Postgres on macOS (README "Troubleshooting"). The stack also refuses to start until four secrets are set in `.env` — `POSTGRES_PASSWORD`, `OBJECT_STORE_SECRET_KEY` (accepted under its legacy name `MINIO_ROOT_PASSWORD` too), `LQ_AI_GATEWAY_KEY`, `JWT_SECRET` — each any long random string (README.md "Quick Start").

## Where data lives

The full accounting, with the departs-your-environment column for every row, is the trust centre's data-boundary page. The shape of it:

| Data | Where | Leaves your environment? |
|---|---|---|
| Accounts, chat history, citations, skills, playbooks, audit log | PostgreSQL | No |
| Uploaded files | RustFS (S3-compatible) | No |
| Anonymization pseudonym mapping | Gateway process memory only, never persisted | No |
| Inference request payload | Travels through the Inference Gateway to the configured provider | Yes, per the routed Inference Tier |

(`docs/architecture.md` "Where data lives, in detail")

> [!CAUTION]
> **Silent failure** — A missed entity is silent. The Anonymization Layer's recall on legal prose is empirically unmeasured (README.md, "Honest validation posture"; docs/security/anonymization.md §"What's validated vs what's unvalidated"). What you can observe instead: the audit row's `anonymization_applied` flag tells you the middleware ran, not that it caught everything. For matters where that residual risk is unacceptable, route at Tier 1 (local Ollama).

The one row that leaves is the inference call itself, and which tier it routes at — from air-gapped local (Tier 1) to a consumer or free-tier endpoint (Tier 5) — is the operator's own configuration choice, shown on each assistant message that carries a routed tier, and recorded in the audit log (README.md, "Inference Tier Awareness"; docs/architecture.md). No data reaches LegalQuants by default; the deployment emits no telemetry unless you opt into it, and what you opt into carries no content (`docs/architecture.md`).

Beyond inference, the Inference Gateway is also the only path for tool calls — case-law and other research-source lookups, and any operator-approved MCP connector. Those are opt-in and off by default; nothing leaves for a tool call until an operator explicitly enables a `tool_providers` entry (`docs/HONEST-STATE.md` §5.5).

> [!NOTE]
> **Professional duty** — Choosing a tier is a confidentiality decision, not only a configuration one — it decides whether a client's material reaches a third party and on what retention terms. Duties differ by jurisdiction and by engagement; check your own rules and any client outside-counsel or vendor terms. Projects marked `privileged: true` force a minimum tier and mark every chat and audit entry privileged (README.md, "Projects"), and `minimum_inference_tier` on a project or skill makes the gateway refuse weaker routing with HTTP 403 `tier_below_minimum`.
