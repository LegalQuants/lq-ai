# Set up monitoring

Use logs and service measurements to follow activity and investigate failures. If you send monitoring information to an outside service, review what will be shared.

## Read the measurements

The API and gateway provide `/metrics`. Their default ports make this information available to the computer running Docker. Check the web-server configuration before making it available elsewhere.

**Details.** The api serves `/metrics` on `:8000` and the gateway on `:8001`; under Compose's default port bindings both are published on the Docker host's loopback interface (`127.0.0.1:8000`, `127.0.0.1:8001`), not only inside the Compose network, and neither endpoint carries authentication. LQ.AI also emits OTLP traces from both services, but by default no telemetry leaves the deployment — the services start cleanly without a collector, and span data is silently dropped until you set an OTLP endpoint (per [PRD §5.7](../../docs/PRD.md#57-no-telemetry-by-default)). You don't need either recipe below just to read `/metrics`; if you already run a collector, setting `OTEL_EXPORTER_OTLP_ENDPOINT` in your `.env` is sufficient on its own — the recipes here are for operators who want a ready-made backend instead. For the full signal inventory, span names, attribute schema, sampling guidance, and dashboard reference — including what `/metrics` does and doesn't expose — see [docs/observability.md §Metrics](../../docs/observability.md#metrics).

## Try the complete setup

The measurements above work with no extra setup. For traces and a dashboard, deploy one of the two recipes below, then use its verify step to confirm data actually arrived — a dashboard loading is not the same as a trace showing up in it.

## Choose one overlay

The self-hosted option adds Grafana, Tempo, Loki, Prometheus and a collector. The standalone option adds a collector for an existing monitoring backend — Honeycomb, Datadog, Lightstep, Splunk, or any other OTLP-compatible backend. Both use the service name `otel-collector`; do not start both overlays together — run `docker compose down` before switching from one to the other. Read each recipe's own README for its environment settings before starting it:

- Self-hosted: [`grafana-tempo-loki/`](grafana-tempo-loki/)
- Forwarding: [`otel-collector-standalone/`](otel-collector-standalone/)

**Details.** Both overlays are Docker Compose files that add services and set `OTEL_EXPORTER_OTLP_ENDPOINT=http://otel-collector:4318` on the api and gateway containers. The base stack (`docker-compose.yml` in the repo root) is unchanged; each overlay is merged at startup with an extra `-f` flag.

## Verify the self-hosted option

After configuring its environment values, start the base Compose file with the grafana-tempo-loki overlay. The recipe exposes Grafana on port 3001. Sign in with the configured admin password and use Explore with the Tempo data source to look for an actual request trace. Seeing the dashboard alone does not establish that traces arrived.

## Verify the forwarding option

The standalone collector starts with a debug exporter that prints trace summaries to its logs. First check that traces reach it. Then configure the intended backend's exporter and credentials, add that exporter to the traces pipeline, and restart the collector if its environment changed. Check receipt at the destination.

## Self-hosted monitoring

Set the environment values in [`grafana-tempo-loki/`](grafana-tempo-loki/) first. Use only one monitoring overlay at a time.

```
docker compose -f docker-compose.yml -f deploy/observability/grafana-tempo-loki/docker-compose.observability.yml up -d
```

## Forwarding collector

This is the alternative overlay. Inspect debug-exporter output before configuring an outside destination — see [`otel-collector-standalone/`](otel-collector-standalone/) for the per-backend exporter blocks (Honeycomb, Datadog, Lightstep, or any other OTLP-compatible endpoint).

```
docker compose -f docker-compose.yml -f deploy/observability/otel-collector-standalone/docker-compose.observability.yml up -d
docker compose -f docker-compose.yml -f deploy/observability/otel-collector-standalone/docker-compose.observability.yml logs otel-collector
```
