# Mini-PRD: OpenTelemetry Deepening — Trace Correlation, Domain Spans, Deployment Recipes

> **Status:** Open for contribution
> **Effort:** M (split across 3 PRs of S/S/M; can be claimed independently)
> **Contributor profile:** Mid-level backend or platform engineer. Familiar with OpenTelemetry concepts (traces, spans, context propagation, samplers, the OTel Collector), at least one OTel-compatible backend (Grafana Tempo, Honeycomb, Datadog APM, Jaeger), Python (FastAPI + httpx) and Docker Compose. Each PR is ~1–3 focused days.
> **Mentor:** Maintainer (via PR review)

## What this is

LQ.AI ships OpenTelemetry **today at M1** — both `api/` and `gateway/` initialize a TracerProvider + OTLP/HTTP exporter when the operator sets `OTEL_EXPORTER_OTLP_ENDPOINT`, with FastAPI-auto-instrumentation, httpx-auto-instrumentation, Prometheus `/metrics` always on, and HTTP middleware that records per-route latency and status with bounded label cardinality. See [`api/app/observability.py`](../../api/app/observability.py), [`gateway/app/observability.py`](../../gateway/app/observability.py), [PRD §5.4](../PRD.md#54-observability), and the architecture diagram entry at [`docs/architecture.md`](../architecture.md).

What's *missing* is the work that turns the existing instrumentation from "two disconnected services emit spans" into a complete operator-facing observability story:

1. **End-to-end trace correlation** — confirm and harden W3C tracecontext propagation across the `api → gateway → provider` call chain so a single chat-send shows as one trace, not three.
2. **Domain spans + rich attributes** — manual instrumentation of the four high-value LQ.AI-specific operations (Citation Engine 4-stage cascade, Anonymization middleware, skill runner, playbook + tabular workflows) with attributes operators actually want (provider, model, tier, tokens in/out, cost, citation-method outcome, anonymization-applied, privileged flag).
3. **Deployment recipes + a single observability operator-guide** so a new operator can go from "I want OTel" to "I see traces in Grafana Tempo" in 15 minutes.

The remaining items (browser RUM, OTel MeterProvider for metrics, SQLAlchemy / ARQ instrumentation, sampling policy, SLO catalog, OWUI-fork OTel reconciliation) are **scoped separately** at the bottom of this doc as DE-XXX candidates so a contributor can claim any one without depending on the others.

This mini-PRD frames the three high-leverage items as a single coherent work package, naturally splittable into three PRs.

## Why it matters

[PRD §5.4 Observability](../PRD.md#54-observability) and [PRD §5.9 Reliability Engineering](../PRD.md#59-reliability-engineering) commit to operator-grade observability — and [HONEST-STATE.md §7](../HONEST-STATE.md#7-operational-state) is explicit that the SLO catalog, runbooks, and deployment recipes are still deferred. The OTel SDK shipped at M1; the surfaces that make it *useful* for an operator's on-call rotation did not.

Three concrete operator-side outcomes the work unlocks:

- **One trace per chat-send.** Today an operator sees an `api` span and a `gateway` span as siblings under separate trace IDs (depending on httpx-instrumentation context propagation, which needs verification). With #1 done, an operator in Tempo can click any chat request and see the full path including the Citation Engine cascade decisions and the provider dispatch — the answer to "why was this slow" lives one click away.
- **Domain attributes on the inference span.** Today the inference span (when it exists) is the auto-instrumented FastAPI span — no provider, no tier, no token counts, no anonymization-applied flag. With #2 done, "show me all Tier 3 paraphrase-judge requests that took > 5s and cost > $0.10" is a single query in the operator's tracing UI. That joins what Prometheus has (the dispatch counter at `lq_ai_gateway_inference_requests_total`) with the per-request causal context that makes the metrics actionable.
- **15-minute time-to-first-trace.** Today an operator has to read source to know what env vars wire up which exporter, what sampler is default, how to deploy Tempo + Grafana alongside the LQ.AI compose stack. The deployment recipe + `docs/observability.md` closes the "what does production OTel look like for LQ.AI?" question with a copy-paste-and-go path.

These three together convert "we ship OTel" from a checkbox into the operational substrate the project's reliability promises depend on.

## What we'd ship

The work splits into three PRs naturally; each is independently mergeable.

### PR 1 — Trace context propagation audit + fix (S, ~1 day)

**Scope:**

- Verify the W3C `traceparent` / `tracestate` headers flow correctly across every internal hop:
  - Browser → `api` (browser RUM is out of scope here, but the entry header from the SvelteKit SSR layer if present should propagate).
  - `api` → `gateway` (the LQ.AI-internal call chain for every chat send, skill execution, playbook execution, tabular execution).
  - `gateway` → provider adapters (httpx outbound — already instrumented in principle; verify the trace context is on the request).
  - `api` → Postgres / `gateway` → Postgres (out of scope for PR 1; see DE-A below).
  - `api` → ARQ worker jobs (out of scope for PR 1; see DE-B below).
- Add a regression test in `tests/test_trace_propagation.py` (one in each service) that mocks an OTLP collector and asserts that a `POST /api/v1/chats/{id}/messages` produces a single trace ID across api + gateway spans.
- If the audit surfaces a gap (e.g., the inter-service call drops the context, or the gateway starts a fresh root span instead of joining), fix it in the smallest possible patch.
- Update [`docs/architecture.md`](../architecture.md) §OBS with a sentence confirming end-to-end trace correlation is verified.

**Files touched:**
- `api/app/observability.py`, `gateway/app/observability.py` (probably no logic change, but the `init_otel()` paths may need a `set_global_textmap(TraceContextTextMapPropagator())` if not already present).
- `api/tests/test_trace_propagation.py` (NEW), `gateway/tests/test_trace_propagation.py` (NEW).
- `docs/architecture.md` (one-paragraph update).

### PR 2 — Domain spans + rich attributes (S→M, ~2–3 days)

**Scope:**

Add manual instrumentation to the four high-value LQ.AI-specific operations. Each gets a top-level span with explicit attributes, child spans per sub-operation, and span events for notable transitions.

**Citation Engine cascade** ([`api/app/citation/verification.py`](../../api/app/citation/verification.py)):
- Top-level span: `citation.verify` with attributes `{citation.method, citation.confidence, citation.partial, citation.tier_envelope, document.id}`.
- Child spans per stage: `citation.stage.exact_match`, `citation.stage.tolerant_match`, `citation.stage.paraphrase_judge`, `citation.stage.ensemble`.
- Span event when the cascade short-circuits (e.g., `exact_match.hit`).
- Span event when ensemble's pre-flight cost-budget check forces fallback to Stage 3.

**Anonymization middleware** ([`gateway/app/anonymization/middleware.py`](../../gateway/app/anonymization/middleware.py)):
- Top-level span: `anonymization.pre` / `anonymization.post` with attributes `{anonymization.enabled, anonymization.skip_reason (if skipped), anonymization.entity_count, anonymization.tier}`.
- Span event for each skip condition that fires (privileged, tier-floor, per-request opt-out, per-message opt-out).
- For the streaming rehydration path: a span around `StreamingRehydrator.feed()` so an operator can see anonymization overhead per chunk.

**Skill runner** ([`api/app/skills/`](../../api/app/skills/) and [`api/app/api/chats.py`](../../api/app/api/chats.py) skill-dispatch path):
- Top-level span: `skill.execute` with attributes `{skill.slug, skill.version, skill.author, project.id, project.privileged, chat.id}`.

**Inference dispatch** ([`gateway/app/router.py`](../../gateway/app/router.py)):
- Add attributes to the existing FastAPI-auto span (or wrap in a dedicated `inference.dispatch` span) — `{inference.provider, inference.model, inference.tier, inference.outcome, inference.tokens_in, inference.tokens_out, inference.cost_usd}`. This is the join key that lets operators correlate cost / tier / outcome with the upstream trace.

**Playbook + tabular workflows** ([`api/app/playbooks/executor.py`](../../api/app/playbooks/executor.py) and `api/app/tabular/executor.py` once shipped in M3-C):
- Top-level span: `playbook.execute` / `tabular.execute` with `{playbook.id, playbook.contract_type, position.count, document.id}` and `{tabular.skill_id, tabular.document_count, tabular.column_count}` respectively.
- Per-position / per-cell child spans so a 30-position playbook surfaces as a 30-child tree.

**Files touched:**
- `api/app/citation/verification.py` — wrap each stage in a span.
- `gateway/app/anonymization/middleware.py` — wrap pre/post in spans.
- `api/app/skills/` (executor module) — `skill.execute` span.
- `gateway/app/router.py` — inference attributes.
- `api/app/playbooks/executor.py` — `playbook.execute` span + per-position children.
- `api/app/tabular/executor.py` if M3-C has merged by the time this PR opens; otherwise scope the tabular spans out and file as a sub-DE.
- New helper module `api/app/observability_helpers.py` and `gateway/app/observability_helpers.py` with `@traced` decorator + `record_attributes(span, **kwargs)` utility so the pattern is uniform across the codebase and isolated for testing.
- Unit tests in each touched module confirm the spans + attributes are emitted (using OTel's in-memory test exporter).

**Anonymization-of-attributes guarantee:** The span attributes added by this PR must respect the same anonymization carve-out logic the gateway already enforces — i.e., no raw entity values (PERSON names, MATTER_NUMBERs) appear in span attributes; only metadata (entity counts, types, tiers). The operator sends trace data to a third-party backend (Honeycomb, Datadog); we must not regress the anonymization promise via the telemetry side-channel. A regression test in `gateway/tests/test_anonymization_observability.py` asserts that the `anonymization.entity_count` attribute is an int, never a list of names.

### PR 3 — Deployment recipes + `docs/observability.md` (M, ~2 days)

**Scope:**

A new subtree under `deploy/observability/`:

```
deploy/
└── observability/                                   # NEW
    ├── README.md                                    # NEW — overview, when to choose which recipe
    ├── grafana-tempo-loki/
    │   ├── README.md                                # NEW — when to use, env, smoke verification
    │   ├── docker-compose.observability.yml         # NEW — Tempo + Loki + Grafana + OTel Collector
    │   ├── otel-collector-config.yaml               # NEW — receives OTLP, exports to Tempo + Loki + Prom
    │   ├── tempo.yaml                               # NEW
    │   ├── loki.yaml                                # NEW
    │   ├── grafana/
    │   │   ├── provisioning/datasources/lq-ai.yaml  # NEW — Tempo + Loki + Prom datasources
    │   │   └── provisioning/dashboards/lq-ai.json   # NEW — starter dashboard (gateway tier mix, p99 by route, error rate)
    │   └── .env.example                             # NEW
    └── otel-collector-standalone/
        ├── README.md                                # NEW — for operators who already have a backend
        ├── docker-compose.observability.yml         # NEW — Collector only
        ├── otel-collector-config.yaml               # NEW — operator points the exporter at their backend
        └── .env.example                             # NEW
```

And a new operator-facing guide:

```
docs/
└── observability.md                                 # NEW — operator-facing guide
```

**`docs/observability.md`** covers:

- **What ships at M1** — the env-var matrix (`OTEL_EXPORTER_OTLP_ENDPOINT`, `OTEL_SERVICE_NAME`, `OTEL_RESOURCE_ATTRIBUTES`, per-signal endpoint overrides), the metrics surface (`/metrics` per service), the sampler default (operator-set via `OTEL_TRACES_SAMPLER` — defaults to `parentbased_always_on` from the OTel SDK; document the recommended `parentbased_traceidratio` with 0.1 for production volume).
- **What's in each signal** — for traces: the list of domain spans added by PR 2 with the attributes operators can filter by. For metrics: the existing Prometheus metric inventory (`lq_ai_gateway_http_requests_total`, `lq_ai_gateway_http_request_duration_seconds`, `lq_ai_gateway_inference_requests_total`, `lq_ai_api_http_requests_total`, `lq_ai_api_http_request_duration_seconds`) with a one-line description of each. For logs: how to get trace-correlation working (link forward to DE-C below).
- **Two reference recipes** — when to choose `grafana-tempo-loki` (operators starting fresh, want a self-hosted stack) vs `otel-collector-standalone` (operators with an existing Honeycomb / Datadog / Lightstep / Splunk backend).
- **Anonymization + telemetry** — a section calling out that span attributes do not contain raw PII (per the PR 2 guarantee), with a pointer to [`docs/security/anonymization.md`](../security/anonymization.md) for the full anonymization story. Operators sending trace data to a third-party backend get the same anonymization-aware posture as inference requests.
- **The "no telemetry by default" promise** — restate PRD §5.7 explicitly: until `OTEL_EXPORTER_OTLP_ENDPOINT` is set, no traces leave the deployment. The `/metrics` endpoint is on but only reachable from within the compose network (or wherever the operator's reverse proxy routes it).
- **What's not yet shipped** — link to the DE entries at the bottom of this doc (browser RUM, OTel-native metrics export, SQLAlchemy + ARQ instrumentation, log correlation, SLO catalog).

**Per-recipe `README.md`** — when to use this recipe; prerequisites; how to run it (`docker compose -f docker-compose.yml -f deploy/observability/<recipe>/docker-compose.observability.yml up -d`); how to verify traces are flowing (a `curl` against a chat-send endpoint plus a "go to Grafana → Explore → Tempo → search by trace ID" walkthrough); how to switch to a different backend.

**Per-recipe `docker-compose.observability.yml`** — overlay file that adds the observability services and sets `OTEL_EXPORTER_OTLP_ENDPOINT=http://otel-collector:4318` on the `api` and `gateway` services via the overlay's environment block. The overlay composes with the base [`docker-compose.yml`](../../docker-compose.yml).

**Per-recipe `otel-collector-config.yaml`** — receives OTLP/HTTP on port 4318, applies a `batch` processor, and either routes to local Tempo + Loki + Prometheus (recipe 1) or forwards to the operator's chosen backend (recipe 2).

**Starter Grafana dashboard** — three panels at v1: gateway tier mix (Tier 1 vs 3 vs 5), p99 HTTP latency by route, error rate by service. Operators extend; we ship the substrate.

## How we'd know it's done

### PR 1 acceptance

- [ ] `tests/test_trace_propagation.py` exists in both `api/` and `gateway/` and asserts that a chat-send produces a single trace ID across both services.
- [ ] If the audit found a propagation gap, the patch lands in the same PR and the regression test would fail without it.
- [ ] [`docs/architecture.md`](../architecture.md) §OBS confirms end-to-end trace correlation in a single sentence.
- [ ] No regression in existing observability tests (`api/tests/test_observability.py`, `gateway/tests/test_observability.py`).

### PR 2 acceptance

- [ ] Citation Engine cascade emits a top-level `citation.verify` span with the documented attributes and child spans per stage.
- [ ] Anonymization middleware emits `anonymization.pre` / `anonymization.post` spans with the documented attributes and skip-reason events.
- [ ] Skill runner emits `skill.execute` spans.
- [ ] Gateway inference dispatch carries `{inference.provider, .model, .tier, .outcome, .tokens_in, .tokens_out, .cost_usd}` attributes.
- [ ] Playbook (and tabular if M3-C has merged) executors emit `playbook.execute` / `tabular.execute` spans with per-position / per-cell children.
- [ ] `gateway/tests/test_anonymization_observability.py` asserts no raw entity values appear in span attributes — only counts and types.
- [ ] In-memory OTel exporter test confirms each documented span + attribute is emitted under expected code paths.
- [ ] Reviewer (maintainer) confirms the `@traced` helper does not duplicate `opentelemetry-instrumentation-fastapi`'s work — the helper is for explicit domain spans, not for HTTP automation.
- [ ] No measurable regression in p99 chat-send latency (verify with the existing pytest microbenchmark or a one-shot timing comparison documented in the PR description).

### PR 3 acceptance

- [ ] `deploy/observability/` exists with the two subdirectories above.
- [ ] `docker compose -f docker-compose.yml -f deploy/observability/grafana-tempo-loki/docker-compose.observability.yml config` produces a valid merged config.
- [ ] A non-maintainer following `deploy/observability/grafana-tempo-loki/README.md` brings up the stack and sees a chat-send trace in Grafana Tempo within 15 minutes of starting.
- [ ] The starter Grafana dashboard loads, shows live data from a test chat-send, and renders the three documented panels.
- [ ] `docs/observability.md` covers all six sections above and is linked from [`README.md`](../../README.md) Quickstart's "next steps" section and from [`docs/HONEST-STATE.md` §6 + §7](../HONEST-STATE.md).
- [ ] The "no telemetry by default" promise is restated in the operator guide and pinned by a brief test in `tests/test_observability.py` that the SDK does not initialize unless `OTEL_EXPORTER_OTLP_ENDPOINT` is set (regression test — the behavior already exists).
- [ ] The standalone-Collector recipe README covers how to point the exporter at Honeycomb, Datadog, and Lightstep specifically (the three most common operator destinations).

## Decisions to lock at PR-open time

These are the architectural choices the contributor takes (or that the maintainer locks in PR review). Documented here so the contributor doesn't get blocked on them.

- **Sampler default.** Recommend `parentbased_always_on` for development (matches the SDK default; full visibility), `parentbased_traceidratio` at 0.1 for the production reference deployment. Document both in `docs/observability.md`; do not change the code default — the operator picks via env.
- **OTLP transport.** Stay on OTLP/HTTP. Already pinned in `pyproject.toml`. OTLP/gRPC adds a second dep tree without operator-side benefit at the volumes the reference deployment runs at.
- **Domain-span helper location.** New `observability_helpers.py` in each service rather than a shared library. Same pattern as the existing per-service `observability.py`. Cross-service contract is the *attribute names*, not the helper code.
- **OWUI-fork OTel.** Out of scope for this PR. Filed below as DE-D. PR 2's `service.name` for the LQ.AI services is `lq-ai-api` and `lq-ai-gateway`; the OWUI-inherited service stays `open-webui` for now and operators see two products in their tracing UI until DE-D lands.

## Related deferred enhancements (file separately as DE-XXX in PRD §9 if not already)

A contributor can claim any one of these independently. They are the rest of the OTel surface area that doesn't fit cleanly inside the three-PR work package above.

**DE-A — SQLAlchemy + ARQ worker instrumentation.** Pin `opentelemetry-instrumentation-sqlalchemy` and add ARQ span wrapping. DB latency and background-job latency (KB ingest, user export/deletion, document pipeline) are blind spots today. ~0.5–1 day. Junior-friendly.

**DE-B — Log-trace correlation.** Inject `trace_id` / `span_id` into the structured logger so Loki / Datadog can pivot from a span to its logs. ~0.5 day. Junior-friendly.

**DE-C — OTel MeterProvider for metrics export.** Current code wires the TracerProvider only; metrics go to Prometheus. Add an OTLPMetricExporter + MeterProvider so operators who want OTel-native metrics (Honeycomb-only or Datadog-APM-only deployments) don't have to scrape Prometheus separately. ~1 day. Mid-level.

**DE-D — Reconcile with the OpenWebUI fork's inherited OTel.** Upstream OWUI has its own telemetry layer at [`web/backend/open_webui/utils/telemetry/`](../../web/backend/open_webui/utils/telemetry/). Today that's a parallel `service.name` namespace. Decide: align resource attributes so the OWUI backend reports as part of the LQ.AI system, *or* disable the upstream OTel and rely only on LQ.AI-emitted spans. ~0.5d decision + ~1d execution.

**DE-E — Browser RUM.** `@opentelemetry/sdk-trace-web` + auto-instrumentations for `fetch` + `document-load`, exporting to the operator's OTel Collector. Needs an explicit opt-in env var mirroring the backend "no telemetry by default" posture, plus a CSP review for the Collector endpoint. ~2–3 days. Mid-to-senior. Sensitive — file as DE and gate behind operator opt-in.

**DE-F — Published SLO catalog.** Already on the deferred list in [PRD §9 — Published SLOs / SLIs](../PRD.md#9-deferred-enhancements-and-identified-future-work). Builds on the OTel signals this mini-PRD ships. The catalog names which metric / span attribute feeds each SLI and publishes the targets (API availability 99.9% monthly; p99 latency by capability per PRD §3; inference-fallback success rate; audit-log durability). ~1–2 days. Best done after PR 2 lands so the span inventory is stable.

**DE-G — Performance regression tracking.** Already on the deferred list in [PRD §9 — Performance regression](../PRD.md#9-deferred-enhancements-and-identified-future-work). Builds on the OTel signals this mini-PRD ships. Per-PR latency benchmarks (p50, p95, p99) for the conversational core, Citation Engine, gateway routing, and skill execution; results committed to a benchmark history; regressions merge-block. ~3–4 days. Senior.

## Risk register

| Risk | Likelihood | Mitigation |
|---|---|---|
| Auto-instrumentation already handles context propagation correctly; PR 1 finds nothing to fix | medium | The regression test still ships as the contract. PR 1 closes by pinning the behavior, which has value even without a code fix. |
| Domain spans add measurable latency to the chat-send path | low | OTel spans cost ~microseconds when sampled out; ~10s of microseconds when sampled in. Pin a microbenchmark in PR 2's acceptance criteria. |
| Span attributes leak PII through the telemetry side-channel | medium | The PR 2 acceptance gate is explicit: a test asserts `anonymization.entity_count` is an int. Maintainer signs off as a CODEOWNERS-required reviewer for any `gateway/app/anonymization/**` change. |
| Operator's existing observability backend doesn't speak OTLP/HTTP | low | The OTel Collector recipe is exactly the adapter for this case — Collector receives OTLP and exports to anything (Jaeger, Zipkin, X-Ray, Splunk, etc.). The standalone-Collector recipe README covers the three most common destinations. |
| The starter Grafana dashboard ages out as new spans land | medium | Ship as JSON in source; updates land as part of the same PR that adds the upstream signal change. Dashboard is the canonical "what does each signal look like" reference. |

## Out of scope

- **Web frontend (browser) OTel.** Filed as DE-E above. The frontend opt-in posture needs a separate scope conversation.
- **Switching the metrics surface from Prometheus to OTel.** Prometheus stays as the always-on metrics surface; OTel metrics export is additive (DE-C).
- **The OpenWebUI fork's inherited telemetry.** Filed as DE-D above.
- **SLO catalog + performance regression tracking.** Filed as DE-F / DE-G above. Both are downstream of the work this mini-PRD ships, not prerequisites for it.
- **Migrating the existing observability tests to a shared in-memory exporter fixture.** Useful refactor; not in this PR's path.

## References

- [PRD §5.4 Observability](../PRD.md#54-observability)
- [PRD §5.7 No telemetry by default](../PRD.md#57-no-telemetry-by-default)
- [PRD §5.9 Reliability Engineering](../PRD.md#59-reliability-engineering)
- [PRD §9 Deferred Enhancements](../PRD.md#9-deferred-enhancements-and-identified-future-work) — DE entries for SLOs, performance regression, and the items filed as DE-A through DE-G above
- [HONEST-STATE.md §6 Engineering-discipline state](../HONEST-STATE.md#6-engineering-discipline-state) — current observability status
- [HONEST-STATE.md §7 Operational state](../HONEST-STATE.md#7-operational-state) — deployment-recipe context
- [`api/app/observability.py`](../../api/app/observability.py) — what's already shipped
- [`gateway/app/observability.py`](../../gateway/app/observability.py) — what's already shipped
- [`docs/architecture.md`](../architecture.md) §OBS — diagrammed observability surface
- [`docs/security/anonymization.md`](../security/anonymization.md) — the anonymization carve-out that the PR 2 attribute design must respect
