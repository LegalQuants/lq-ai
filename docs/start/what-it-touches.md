# What gets installed and where data goes

Docker Compose starts eight services. These include the website, services that handle requests and AI connections, two background workers, and three storage services.

## Where files and records live

Postgres stores records such as matters, chats, citations, skills, playbooks and the audit log. RustFS — the S3-compatible object store that replaced a bundled MinIO (ADR 0036) — stores uploaded files; `.env` files that still set `MINIO_*` variables keep working, since `docker-compose.yml` falls back to them when the newer `OBJECT_STORE_*` variables aren't set. Redis holds the ingest and background-job queues the two workers consume from, plus other working data (`docker-compose.yml`). The anonymization layer's pseudonym mapping lives in the gateway process's own memory and is never persisted. A recovery plan needs to account for all of these together.

For the full accounting, including what leaves your environment, see the [trust centre's data-boundary page](../trust/what-leaves-my-deployment.md). The shape of it:

| Data | Where | Leaves your environment? |
|---|---|---|
| Accounts, chat history, citations, skills, playbooks, audit log | PostgreSQL | No |
| Uploaded files | RustFS (S3-compatible) | No |
| Anonymization pseudonym mapping | Gateway process memory only, never persisted | No |
| Inference request payload | Travels through the Inference Gateway to the configured provider | Yes, per the routed Inference Tier |

(`docs/architecture.md`, "Where data lives, in detail")

## What may use the internet

Installation may download software and models. A cloud AI service receives the text needed to answer a question — the inference request travels through the Inference Gateway to whichever provider is configured. Which tier it routes at, from air-gapped local (Tier 1) to a consumer or free-tier endpoint (Tier 5), is the operator's own configuration choice. It's shown on each assistant message that carries a routed tier, and recorded in the audit log (README.md, "Inference Tier Awareness"; `docs/architecture.md`).

Document search may also send text to a service that prepares it for meaning-based searches. Beyond inference, the Inference Gateway is also the only path for tool calls — case-law and other research-source lookups, and any operator-approved MCP connector. Those are opt-in and off by default: nothing leaves for a tool call until an operator explicitly enables a `tool_providers` entry (`docs/HONEST-STATE.md` §5.5). Two more paths are off by default and have their own settings: optional SMTP email for Autonomous Layer notifications (`smtp_host`, unset by default; api/app/config.py:418) and OpenTelemetry export (`OTEL_EXPORTER_OTLP_ENDPOINT`, unset by default; docs/architecture.md:204). Neither is the `slack-bridge` / `teams-bridge` integration bridges named below under "Optional services" — there is no email or monitoring bridge service.

No data reaches LegalQuants by default; the deployment emits no telemetry unless you opt in, and what you opt into carries no content (`docs/architecture.md`).

> [!NOTE]
> **Professional duty** — Choosing a tier is a confidentiality decision, not only a configuration one — it decides whether a client's material reaches a third party and on what retention terms. Duties differ by jurisdiction and by engagement; check your own rules and any client outside-counsel or vendor terms. Projects marked `privileged: true` force a minimum tier and mark every chat and audit entry privileged (README.md, "Projects"), and `minimum_inference_tier` on a project or skill makes the gateway refuse weaker routing with HTTP 403 `tier_below_minimum`.

## Who can connect by default

The default service ports accept connections from the computer running Docker, not other computers on the network: each binds to `${*_BIND_ADDR:-127.0.0.1}` by default (`docker-compose.yml`). Check the settings before making the app available more widely. Monitoring is a related but wider story — the api's and gateway's Prometheus `/metrics` endpoints are always on and unauthenticated. With the default Compose bindings they're reachable from the Docker host's own loopback interface and from any other container on the Compose network; reaching them from anywhere else needs the operator to rebind the port or route through a reverse proxy (docs/observability.md, "No telemetry by default").

## Before you install

Have Git and Docker Desktop 4.x+ (or Docker Engine 24+ on Linux) with Compose available. The source install builds its own images; you do not need Python or Node installed on the host. The README suggests roughly 8 GB of free disk and 6 GB of memory available to Docker (README.md, "Quick Start") — these are planning figures, not a measured capacity guarantee; downloads, build files, documents and local models need more room. Named reference configurations for how much a laptop, a small server, or an air-gapped local-inference host can actually carry are on the [hardware sizing](../operate/hardware-sizing.md) page.

Provider API keys (Anthropic, OpenAI, etc.) are optional at install time; the stack starts without one and inference calls return "no provider configured" until you add at least one.

## Services and default ports

The eight default services are `web`, `api`, `gateway`, `ingest-worker`, `arq-worker`, `postgres`, `redis` and `rustfs` (`docker-compose.yml`). The website uses host port 3000, the API 8000 and gateway 8001. Postgres uses 5432, Redis 6379, and RustFS 9000 for file access and 9001 for its console:

```text
WEB_HOST_PORT=3000
API_HOST_PORT=8000
GATEWAY_HOST_PORT=8001
POSTGRES_HOST_PORT=5432
REDIS_HOST_PORT=6379
OBJECT_STORE_API_HOST_PORT=9000
OBJECT_STORE_CONSOLE_HOST_PORT=9001
```

Each can be changed through its corresponding `*_HOST_PORT` setting in `.env`. `POSTGRES_HOST_PORT` is the one that most often collides, typically with a Homebrew Postgres on macOS (README.md "Troubleshooting").

The stack also refuses to start until four secrets are set in `.env` — `POSTGRES_PASSWORD`, `OBJECT_STORE_SECRET_KEY` (accepted under its legacy name `MINIO_ROOT_PASSWORD` too), `LQ_AI_GATEWAY_KEY`, `JWT_SECRET` — each any long random string (README.md "Quick Start").

## Optional services

The local Compose profile (`--profile local`) adds `ollama`, for fully local inference. The slack and teams profiles (`--profile slack`, `--profile teams`) add the corresponding bridges; enabling a profile does not prove the outside service connection works. Those connections need their own setup and testing.

## Replacing identifying details has limits

The optional anonymization feature can miss names and other identifying details. A log saying it ran is not proof that all sensitive information was removed. It is off by default in the example settings (`gateway.yaml.example`). Choose a model and connection suitable for the full text that could be sent, including document passages used to answer the question.

> [!CAUTION]
> **Silent failure** — A missed entity is silent. The Anonymization Layer's recall on legal prose is empirically unmeasured (README.md, "Honest validation posture"; docs/security/anonymization.md §"What's validated vs what's unvalidated"). What you can observe instead: the audit row's `anonymization_applied` flag tells you the middleware ran, not that it caught everything. For matters where that residual risk is unacceptable, route at Tier 1 (local Ollama).
