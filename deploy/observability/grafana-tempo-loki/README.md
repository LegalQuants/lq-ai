# Observability recipe: Grafana + Tempo + Loki + Prometheus

This recipe adds a self-hosted observability backend alongside the main LQ.AI stack. It provisions:

- **OpenTelemetry Collector** — receives OTLP traces from the api and gateway; forwards to Tempo.
- **Grafana Tempo** — trace storage and query backend.
- **Grafana Loki** — log aggregation (ready for future log-shipping; not auto-populated today).
- **Prometheus** — scrapes `/metrics` from api (`:8000`) and gateway (`:8001`).
- **Grafana** — unified query and dashboard UI on host port `3001`.

## When to use this recipe

Use this recipe when you want a complete, self-hosted observability stack with no third-party SaaS dependency. If you already have Honeycomb, Datadog, or Lightstep, use [`../otel-collector-standalone/`](../otel-collector-standalone/) instead.

## Prerequisites

- Docker Desktop (or Docker Engine 24+) installed and running.
- The base LQ.AI stack able to start: `docker compose up -d` from the repo root should reach a healthy state before you add this overlay. See [docs/quickstart.md](../../../docs/quickstart.md) for the base-stack setup walkthrough.

> **First-run image pull:** bringing this overlay up for the first time pulls the Collector, Tempo, Loki, Prometheus, and Grafana images. Combined, these are several hundred MB. On a reasonable connection this adds 2–5 minutes to the first startup. Subsequent runs reuse cached images and add seconds.

---

## Run command

Run from the **repo root**:

```bash
docker compose \
  -f docker-compose.yml \
  -f deploy/observability/grafana-tempo-loki/docker-compose.observability.yml \
  up -d
```

### Environment variables

Copy the relevant variables from `.env.example` into your repo-root `.env` before bringing the stack up:

```bash
# Grafana admin password — change this before exposing Grafana outside localhost.
GF_SECURITY_ADMIN_PASSWORD=admin

# Host port for Grafana. Default 3001 avoids collision with the web service on 3000.
GRAFANA_HOST_PORT=3001
```

The overlay reads these from the repo-root `.env` via Compose's standard env-file loading. You do not need to copy the `.env.example` file itself — copy only the variable lines you want to override.

---

## 15-minute "verify a trace" walkthrough

### Step 1 — Confirm the stack is up

```bash
docker compose \
  -f docker-compose.yml \
  -f deploy/observability/grafana-tempo-loki/docker-compose.observability.yml \
  ps
```

All services should show `running`. The `otel-collector`, `tempo`, `loki`, `prometheus`, and `grafana` services are new; `api` and `gateway` are the base-stack services with OTLP export now enabled.

### Step 2 — Send a request to generate a trace

The easiest path is to open the web UI at `http://localhost:3000`, log in, and send a chat message. Any chat-send request causes the api to call the gateway, which calls the configured provider — that round-trip produces the `api → gateway → provider` span tree that includes the M3-F domain spans (`inference.dispatch`, `skill.execute`, etc.).

Alternatively, use the API directly. The chat-send endpoint requires a valid JWT. Obtain a token by following the authentication steps in [docs/quickstart.md](../../../docs/quickstart.md), then:

```bash
curl -s -X POST http://localhost:8000/api/v1/chats/{chat_id}/messages \
  -H "Authorization: Bearer <your-token>" \
  -H "Content-Type: application/json" \
  -d '{"content": "Summarize the key obligations in this NDA.", "model": "smart"}'
```

Replace `{chat_id}` with an existing chat ID from your session and `<your-token>` with the JWT from the quickstart auth flow. Do not fabricate tokens — the endpoint will reject them with `401`.

### Step 3 — Open Grafana and find the trace

1. Navigate to `http://localhost:3001`.
2. Anonymous viewer access is enabled; you can browse dashboards without logging in. To use Explore or change settings, log in as `admin` with the password from your `.env` (default: `admin`).
3. In the left sidebar, click **Explore**.
4. In the datasource dropdown at the top, select **Tempo**.
5. Switch to the **Search** tab.
6. Filter by **Service Name**: `lq-ai-gateway` (or `lq-ai-api`).
7. Optionally filter by **Span Name**: `inference.dispatch` to isolate the gateway's per-call dispatch span.
8. Click **Run query**. Recent traces appear in the results table.
9. Click a trace ID to open the span waterfall. You should see the `lq-ai-api → lq-ai-gateway → provider` tree with the F2 domain spans as children.

### Step 4 — Check the metrics dashboard

In the left sidebar, click **Dashboards**. The provisioned **LQ.AI** dashboard is pre-loaded and shows the Prometheus-scraped metric panels (request rate, latency percentiles, error rate) for the api and gateway services.

---

## Sampling

The default sampler is `parentbased_always_on` — every trace is recorded. This is appropriate for development and low-traffic staging.

For production, set the following in your repo-root `.env`:

```bash
OTEL_TRACES_SAMPLER=parentbased_traceidratio
OTEL_TRACES_SAMPLER_ARG=0.1   # ~10% of root traces; complete child spans are always kept
```

Then restart the api and gateway containers (`docker compose up -d api gateway`) for the change to take effect.

---

## Switching to an external backend

If you later move to Honeycomb, Datadog, or another managed backend, bring this stack down and switch to the standalone collector recipe:

```bash
docker compose \
  -f docker-compose.yml \
  -f deploy/observability/grafana-tempo-loki/docker-compose.observability.yml \
  down

# Then follow the instructions in:
# deploy/observability/otel-collector-standalone/README.md
```

Named volumes (`tempo-data`, `loki-data`, `prom-data`, `grafana-data`) persist across restarts but are removed by `docker compose down -v`. Historical trace data does not migrate to a new backend.
