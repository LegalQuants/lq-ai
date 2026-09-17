---
title: "Recipe: observability"
description: Wire a traces-and-metrics backend — self-hosted, or forwarding to an existing SaaS collector.
audience: [operator]
status: draft
sources:
  - deploy/observability/README.md
  - deploy/observability/grafana-tempo-loki/README.md
  - deploy/observability/otel-collector-standalone/README.md
sidebar:
  order: 33
---

**Problem.** By default, no telemetry leaves your deployment — the OTel SDK ships in both `api` and `gateway` but never initializes until you set an OTLP endpoint, and `/metrics` is reachable only inside the Compose network. This recipe wires a backend so you can actually see traces and metrics.

**Context.** Two sub-recipes, mutually exclusive at a time (both name their collector service `otel-collector`; run `docker compose down` before switching). Full signal inventory, span names, and sampling guidance live in [Logs and monitoring](../logs-and-monitoring.md) — this page is only the two run paths.

<!-- include: deploy/observability/README.md from="## Choose a recipe" -->

## Steps and verify — self-hosted (Grafana + Tempo + Loki + Prometheus)

Copy this overlay's environment variables into your repo-root `.env` first — see [`deploy/observability/grafana-tempo-loki/README.md`](../../../../deploy/observability/grafana-tempo-loki/README.md) §Environment variables. Then bring it up as an overlay on the base stack, and send one chat message and look for the trace in Grafana:

```bash
docker compose \
  -f docker-compose.yml \
  -f deploy/observability/grafana-tempo-loki/docker-compose.observability.yml \
  up -d
```

**Verify:** open `http://localhost:3001`, log in as `admin` (password from your `.env`; Explore is not available to the anonymous viewer) → Explore → datasource **Tempo** → Search → filter Service Name `lq-ai-gateway` → **Run query**. A trace in the results table, opening into the `lq-ai-api → lq-ai-gateway → provider` span waterfall, confirms the full path. Full walkthrough, environment variables, and the provisioned dashboard: [`deploy/observability/grafana-tempo-loki/README.md`](../../../../deploy/observability/grafana-tempo-loki/README.md).

## Steps and verify — standalone collector (forward to Honeycomb, Datadog, Lightstep, or any OTLP endpoint)

```bash
docker compose \
  -f docker-compose.yml \
  -f deploy/observability/otel-collector-standalone/docker-compose.observability.yml \
  up -d
```

The collector ships with only the `debug` exporter active — span summaries print to its own stdout as a smoke test before you wire a real backend. **Verify the smoke test first:**

```bash
docker compose \
  -f docker-compose.yml \
  -f deploy/observability/otel-collector-standalone/docker-compose.observability.yml \
  logs otel-collector
```

Lines starting `Traces #0` confirm spans are flowing. Then uncomment your backend's exporter block in `otel-collector-config.yaml`, **change the `traces` pipeline's `exporters` line from `[debug]` to your exporter** (or `[debug, <exporter>]` while validating), set its API-key env var, and restart the collector:

```bash
docker compose -f docker-compose.yml -f deploy/observability/otel-collector-standalone/docker-compose.observability.yml up -d otel-collector
```

The per-backend blocks (Honeycomb, Datadog, Lightstep, or any other OTLP-compatible endpoint) are in [`deploy/observability/otel-collector-standalone/README.md`](../../../../deploy/observability/otel-collector-standalone/README.md).

## Refusal errors explained

Neither sub-recipe has a fail-closed refusal of its own — this is additive observability tooling, not a path the gateway's egress guard has an opinion on. If nothing shows up in either verify step, the most common cause named in the sources above is a stack that wasn't already healthy before the overlay was added; confirm the base stack with `docker compose ps` first.

## Next

- [Logs and monitoring](../logs-and-monitoring.md)
- [Architecture](../architecture.md)
- [Recipes](index.md)
