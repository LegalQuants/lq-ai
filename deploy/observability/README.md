# LQ.AI — Observability Deployment Recipes

LQ.AI emits OTLP traces from the API and Gateway services and exposes Prometheus metrics on `/metrics`. By default, no telemetry leaves the deployment — the services start cleanly without a collector, and span data is silently dropped until you wire a backend (per [PRD §5.7](../../docs/PRD.md#57-no-telemetry-by-default)). These recipes wire that backend. If you prefer to configure a collector yourself, setting `OTEL_EXPORTER_OTLP_ENDPOINT` in your `.env` is sufficient; the recipes here are for operators who want a ready-made setup.

For the full operator guide — signal inventory, span names, attribute schema, sampling guidance, and dashboard reference — see [docs/observability.md](../../docs/observability.md) (note: this file is added in the M3-F3 release alongside these recipes).

---

## Choose a recipe

| Situation | Recipe |
|---|---|
| You are starting fresh and want a self-hosted observability stack with no third-party SaaS. You want traces in Tempo, logs in Loki, metrics in Prometheus, and a Grafana dashboard — all running alongside the main stack in Docker. | [`grafana-tempo-loki/`](grafana-tempo-loki/) |
| You already run Honeycomb, Datadog, Lightstep, Splunk, or any other OTLP-compatible backend, and you just need a collector that forwards LQ.AI's spans to it. You don't want Grafana or Tempo locally. | [`otel-collector-standalone/`](otel-collector-standalone/) |

Both recipes are Docker Compose overlays. They add services and set `OTEL_EXPORTER_OTLP_ENDPOINT=http://otel-collector:4318` on the api and gateway containers. The base stack (`docker-compose.yml` in the repo root) is unchanged; the overlay is merged at startup with the `-f` flag.

---

## Switching between recipes

Run `docker compose down` before switching overlays; the collector service name is the same (`otel-collector`) in both recipes, and having both active simultaneously is not a supported configuration.
