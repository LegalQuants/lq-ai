# Observability recipe: standalone OpenTelemetry Collector

This recipe adds only an OpenTelemetry Collector to the LQ.AI stack. It does not bundle Grafana, Tempo, Loki, or Prometheus. Use it when you already have a tracing backend — Honeycomb, Datadog, Lightstep, or any OTLP-compatible endpoint — and want to forward LQ.AI's spans there with minimal additional Docker surface.

If you don't have an existing backend and want a self-hosted stack, use [`../grafana-tempo-loki/`](../grafana-tempo-loki/) instead.

---

## Run command

Run from the **repo root**:

```bash
docker compose \
  -f docker-compose.yml \
  -f deploy/observability/otel-collector-standalone/docker-compose.observability.yml \
  up -d
```

Before bringing the stack up, configure your backend in `otel-collector-config.yaml` and set the relevant env vars in your repo-root `.env` (instructions below).

---

## Configuring your backend

Open `deploy/observability/otel-collector-standalone/otel-collector-config.yaml`. The file ships with the `debug` exporter active and all backend-specific exporter blocks commented out. The `debug` exporter logs span summaries to the collector's stdout — useful as a smoke test before wiring your real backend:

```bash
docker compose \
  -f docker-compose.yml \
  -f deploy/observability/otel-collector-standalone/docker-compose.observability.yml \
  logs otel-collector
```

If traces are flowing you will see lines like `Traces #0` with resource and span summaries. Once confirmed, wire your backend using the instructions for your provider below.

---

### Honeycomb

1. **Uncomment** the `otlp/honeycomb` exporter block in `otel-collector-config.yaml`:

   ```yaml
   otlp/honeycomb:
     endpoint: api.honeycomb.io:443
     headers:
       x-honeycomb-team: ${HONEYCOMB_API_KEY}
     tls:
       insecure: false
   ```

2. **Update the pipeline** — change the `traces` pipeline's `exporters` line from `[debug]` to `[otlp/honeycomb]` (or `[debug, otlp/honeycomb]` to keep stdout logging while validating):

   ```yaml
   service:
     pipelines:
       traces:
         receivers: [otlp]
         processors: [batch]
         exporters: [otlp/honeycomb]
   ```

3. **Set the env var** in your repo-root `.env`:

   ```bash
   HONEYCOMB_API_KEY=<your-key>   # obtain at https://ui.honeycomb.io/account
   ```

4. Restart the collector: `docker compose -f docker-compose.yml -f deploy/observability/otel-collector-standalone/docker-compose.observability.yml up -d otel-collector`.

---

### Datadog

1. **Uncomment** the `datadog` exporter block in `otel-collector-config.yaml`:

   ```yaml
   datadog:
     api:
       key: ${DD_API_KEY}
       site: ${DD_SITE:-datadoghq.com}
   ```

2. **Update the pipeline** — change `exporters: [debug]` to `exporters: [datadog]` (or `[debug, datadog]`):

   ```yaml
   service:
     pipelines:
       traces:
         receivers: [otlp]
         processors: [batch]
         exporters: [datadog]
   ```

3. **Set the env vars** in your repo-root `.env`:

   ```bash
   DD_API_KEY=<your-key>
   DD_SITE=datadoghq.com   # other values: datadoghq.eu, us3.datadoghq.com, us5.datadoghq.com
   ```

4. Restart the collector.

The recipe uses the `otel/opentelemetry-collector-contrib` image, which includes the native Datadog exporter — no additional image changes are needed.

---

### Lightstep (ServiceNow Cloud Observability)

1. **Uncomment** the `otlp/lightstep` exporter block in `otel-collector-config.yaml`:

   ```yaml
   otlp/lightstep:
     endpoint: ingest.lightstep.com:443
     headers:
       lightstep-access-token: ${LS_ACCESS_TOKEN}
     tls:
       insecure: false
   ```

2. **Update the pipeline** — change `exporters: [debug]` to `exporters: [otlp/lightstep]` (or `[debug, otlp/lightstep]`):

   ```yaml
   service:
     pipelines:
       traces:
         receivers: [otlp]
         processors: [batch]
         exporters: [otlp/lightstep]
   ```

3. **Set the env var** in your repo-root `.env`:

   ```bash
   LS_ACCESS_TOKEN=<your-token>   # obtain at https://app.lightstep.com/[your-project]/settings/access-tokens
   ```

4. Restart the collector.

---

### Other OTLP-compatible backends

For any backend that accepts standard OTLP/gRPC or OTLP/HTTP, add an `otlp/<name>` exporter block following the same pattern as the Honeycomb and Lightstep blocks above, pointing at your backend's ingest endpoint. Consult your backend's documentation for the exact endpoint, port, and authentication header name.

---

## Sampling

The default sampler is `parentbased_always_on` — every trace is recorded. For production, add the following to your repo-root `.env`:

```bash
OTEL_TRACES_SAMPLER=parentbased_traceidratio
OTEL_TRACES_SAMPLER_ARG=0.1   # ~10% of root traces; complete child spans are always kept
```

Then restart the api and gateway containers for the change to take effect. See [docs/observability.md](../../../docs/observability.md) for guidance on choosing a sampling rate.
