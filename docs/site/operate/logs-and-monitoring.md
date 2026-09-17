---
title: Logs and monitoring
description: What LQ.AI emits by default, what it takes to turn on tracing and metrics, and the ready-made deployment recipes.
audience: [operator]
status: draft
sources:
  - docs/observability.md
  - deploy/observability/README.md
sidebar:
  order: 21
---

By default, no telemetry leaves your deployment: the OTel SDK ships in both services but never initializes until you set an OTLP endpoint, and Prometheus's `/metrics` is always on but reachable only inside the Compose network. Everything below is what you get once you turn tracing on, and the two ready-made recipes for wiring a backend.

<!-- include: docs/observability.md -->

Both deployment recipes referenced above (`grafana-tempo-loki/` and `otel-collector-standalone/`) are Docker Compose overlays under [`deploy/observability/`](../../../deploy/observability/README.md); switch between them by running `docker compose down` first — both name their collector service `otel-collector`, and running both at once is not a supported configuration.

## Known gaps in what's instrumented

:::caution[Silent failure]
Two labelled things in the metrics and audit surfaces are documented but not actually produced, and neither failure looks like anything at query time — you get zero rows rather than an error. The `lq_ai_gateway_inference_requests_total` metric's `outcome` label lists `refused` as a possible value, but the tier-floor refusal path never increments the counter with it — a dashboard built to alert on refusal spikes would stay silent through a real one. The `autonomous_session.started` audit action is defined the same way: reserved in code, never written. If you're building an alert or a query against either, confirm the code path actually emits it first (`docs/observability.md` §2 names both explicitly), rather than trusting the label list.
:::

Two other things worth knowing before you commit to a production sampling policy: log lines don't yet carry `trace_id`/`span_id`, so pivoting from a trace in Tempo or Honeycomb to the matching logs means matching on timestamp and service name by hand; and the streaming chat path doesn't emit an `inference.dispatch` span the way the non-streaming path does, so cost and token counts on streamed responses won't show up in traces today. For production, start from `OTEL_TRACES_SAMPLER=parentbased_traceidratio` with `OTEL_TRACES_SAMPLER_ARG=0.1` rather than the SDK's sample-everything default — the recommended block is in the include above.

## Next

- [Architecture](architecture.md)
- [Something is wrong](something-is-wrong.md)
- [Rotate a leaked provider key](rotate-a-leaked-key.md)
