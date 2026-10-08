# LQ.AI — Observability Operator Guide

> **Scope:** OpenTelemetry traces, Prometheus metrics, audit actions, and deployment
> recipes for the `api` and `gateway` services. Covers what is shipped as of the M4
> close: the M3-F OTel baseline (M3-F1 trace propagation, M3-F2 domain spans, M3-F3
> recipes and this doc) plus the M4 Autonomous Layer spans and audit actions. What is
> not yet shipped is listed in [§6 — What's not yet shipped](#6-whats-not-yet-shipped)
> with links to the tracking DE entries.
>
> The governed-run spans, the worker tracing and the routing-log purpose labels
> for runs (ADR 0038, proposed) are implemented on an unmerged branch and are
> marked as such where they appear. They are in no release.

For the architectural context see [docs/architecture.md](architecture.md) §OBS and the
"What the diagram doesn't show" section. For the deployment recipes see
[deploy/observability/README.md](../deploy/observability/README.md).

---

## 1. Environment-variable matrix

LQ.AI initializes the OTel SDK **only when at least one of the endpoint variables
below is set.** If none are set, the services start cleanly and spans are silently
dropped — no traces leave the deployment (per [PRD §5.7](PRD.md#57-no-telemetry-by-default)).
Prometheus `/metrics` is always on regardless of OTel configuration.

Transport is OTLP/HTTP for all signals.

| Variable | Meaning | Default |
|---|---|---|
| `OTEL_EXPORTER_OTLP_ENDPOINT` | Master switch. Sets the base URL for all signals (traces + metrics when [DE-301](PRD.md#de-301--otel-meterprovider-for-metrics-export-otel-deepening-de-c) lands). OTel initializes iff this OR a per-signal endpoint is set. Example: `http://otel-collector:4318`. | unset — no OTel |
| `OTEL_EXPORTER_OTLP_TRACES_ENDPOINT` | Per-signal override for traces. Takes precedence over the master endpoint for trace export. Useful when splitting traces and metrics to different backends. | unset |
| `OTEL_EXPORTER_OTLP_METRICS_ENDPOINT` | Per-signal override for metrics (relevant once DE-301 lands). | unset |
| `OTEL_SERVICE_NAME` | Resource attribute `service.name` attached to every span. | `lq-ai-api` (api service), `lq-ai-gateway` (gateway service). On the ADR 0038 branch the Compose files and both recipes also set `lq-ai-arq-worker` for the `arq-worker` service; see [Governed runs](#orchestrationjob--orchestrationrun--orchestrationeffect). |
| `OTEL_RESOURCE_ATTRIBUTES` | Arbitrary `key=value,key=value` pairs appended to the resource. Use for deployment environment, region, or cluster tags. Example: `deployment.environment=production,k8s.cluster.name=prod-east`. | unset |
| `OTEL_TRACES_SAMPLER` | Sampler name per the OTel SDK. The SDK default is `parentbased_always_on` (sample everything). For production, use `parentbased_traceidratio` and set `OTEL_TRACES_SAMPLER_ARG=0.1` (10% head sampling). | `parentbased_always_on` |
| `OTEL_TRACES_SAMPLER_ARG` | Sampler argument. For `parentbased_traceidratio`, the sampling ratio (0.0–1.0). | `1.0` |

**Recommended production configuration:**

```env
OTEL_EXPORTER_OTLP_ENDPOINT=http://otel-collector:4318
OTEL_SERVICE_NAME=lq-ai-api          # or lq-ai-gateway per service
OTEL_TRACES_SAMPLER=parentbased_traceidratio
OTEL_TRACES_SAMPLER_ARG=0.1
OTEL_RESOURCE_ATTRIBUTES=deployment.environment=production
```

---

## 2. What's in each signal

### Traces

W3C `traceparent` propagates across the full `api → gateway → provider` call chain
(M3-F1). A single chat-send surfaces as **one end-to-end trace**, not three separate
traces — verified by `test_trace_propagation.py` in both `api/` and `gateway/`.

Beyond HTTP auto-instrumentation (FastAPI + httpx), the services emit **domain spans**
for the high-value LQ.AI operations. These spans are no-ops when OTel is disabled.

---

#### `citation.verify`

Wraps the full Citation Engine cascade for one citation candidate. Child spans cover
each stage that runs.

| Child span | Emitted when |
|---|---|
| `citation.stage.exact_match` | Always (stage 1) |
| `citation.stage.tolerant_match` | Stage 1 misses |
| `citation.stage.paraphrase_judge` | Stage 2 misses (single-judge path) |
| `citation.stage.ensemble` | Ensemble path active (replaces paraphrase_judge) |

**Attributes on each `citation.stage.*` child span:**

| Attribute | Description |
|---|---|
| `citation.stage.verified` | Boolean; whether this stage verified the candidate |
| `citation.stage.confidence` | Float 0.0–1.0; this stage's confidence for the candidate |

**Attributes on `citation.verify`:**

| Attribute | Description |
|---|---|
| `citation.method` | Winning stage: `exact_match`, `tolerant_match`, `paraphrase_judge`, `ensemble_strict`, or `ensemble_majority` |
| `citation.confidence` | Float 0.0–1.0; maps to stage confidence (0.90/0.70/0.50 for the judge stages) |
| `citation.partial` | Boolean; `true` when the source partially supports the claim |
| `citation.tier_envelope` | Inference tier used for judge calls |
| `document.id` | ID of the cited source document |

**Additional attributes on `citation.stage.ensemble`:**

| Attribute | Description |
|---|---|
| `citation.ensemble.n_judges` | Number of parallel judge calls |
| `citation.ensemble.rule` | Aggregation rule: `strict` or `majority` |

**Span events:**

| Event | Meaning |
|---|---|
| `exact_match.hit` | Stage 1 short-circuit (no further stages run) |
| `tolerant_match.hit` | Stage 2 short-circuit |
| `ensemble.budget_fallback` | Pre-flight budget check tripped; ensemble skipped |

---

#### `anonymization.pre` / `anonymization.post`

Emitted by the gateway anonymization middleware (`gateway/app/anonymization/middleware.py`).
`anonymization.pre` wraps the entity-detection + pseudonymization pass before the
model call; `anonymization.post` wraps the rehydration pass on the response.

**The domain attributes below are recorded on `anonymization.pre` only.**
`anonymization.post` is created by the `@traced("anonymization.post")` decorator and
carries no domain attributes — it exists to time the rehydration pass and capture an
exception if one is raised, nothing more. (The per-entity rehydration count is not
recorded; capturing it on the post span is a future enhancement, not a shipped claim.)

**Attributes on `anonymization.pre`:**

| Attribute | Description |
|---|---|
| `anonymization.enabled` | Boolean; mirrors the gateway anonymization config `enabled` flag |
| `anonymization.tier` | Inference tier at the time of the anonymization decision (recorded on every `pre` span) |
| `anonymization.skip_reason` | Present when the pass is skipped; one of `disabled` (config off), `tier_floor` (routed tier not in `apply_at_tiers`), `privileged` (privileged matter), `request_opt_out` (`anonymize=false` on the request) |
| `anonymization.entity_count` | Integer count of entities detected (`0` when skipped) |
| `anonymization.entity_types` | Sorted list of entity type labels (e.g., `PERSON,MATTER_NUMBER`). **Never raw entity values** — see [§4](#4-anonymization-and-telemetry). Recorded only when the pass actually runs (not on the skip path). |

**Span event on `anonymization.pre`:**

| Event | Meaning |
|---|---|
| `anonymization.skip.{reason}` | Emitted on the skip path, where `{reason}` is the `skip_reason` value above (e.g., `anonymization.skip.disabled`) |

**Span events:**

| Event | Meaning |
|---|---|
| `anonymization.skip.{skip_reason}` | Emitted when anonymization is skipped; the suffix is the `skip_reason` value (`disabled`, `tier_floor`, `privileged`, or `request_opt_out`) |

---

#### `skill.execute`

One span per skill applied to the request.

| Attribute | Description |
|---|---|
| `skill.slug` | Skill identifier (e.g., `nda-review`) |
| `skill.version` | Skill semver |
| `skill.author` | Skill author field from `SKILL.md` frontmatter (may be `null` for built-ins until [DE-316](PRD.md#de-316--promote-skill-author-to-the-skill--skillsummary-wire-shape-otel-deepening-skill-spans) lands) |
| `project.id` | Matter-scoped project UUID |
| `project.privileged` | Boolean; `true` for privileged matters |
| `chat.id` | Chat session UUID |

---

#### `inference.dispatch`

Emitted by the gateway on the **non-streaming** `chat_completions` path. Carries the
post-dispatch cost and outcome data. **Note:** the streaming path does not yet emit
this span — tracked at [DE-317](PRD.md#de-317--inferencedispatch-span-on-the-streaming-path-otel-deepening).

| Attribute | Description |
|---|---|
| `inference.provider` | Provider name: `anthropic`, `openai`, `azure_openai`, `ollama` |
| `inference.model` | Model ID as sent to the provider |
| `inference.tier` | Routed inference tier (1–5) |
| `inference.outcome` | `success`, `provider_error`, `network_error`, or `unavailable` (the last when no adapter could be instantiated). The `provider_error` / `network_error` labels come from `outcome_label_from_error` in `gateway/app/router.py`; `unavailable` is set on the `NoAdapterAvailableError` path in `gateway/app/api/inference.py`. |
| `inference.tokens_in` | Prompt token count (omitted when the provider returns no usage) |
| `inference.tokens_out` | Completion token count (omitted when the provider returns no usage) |
| `inference.cost_usd` | Computed cost in USD at configured per-model rates |

On the `unavailable` path (no adapter could be instantiated for the resolved target), only `inference.provider` and `inference.outcome` are set — `inference.model`, `inference.tier`, `inference.tokens_in`/`inference.tokens_out`, and `inference.cost_usd` are absent, because no native model or tier was resolved.

---

#### `playbook.execute` / `tabular.execute`

Top-level spans wrapping a full Playbook or Tabular Review execution.

**`playbook.execute`** attributes (`api/app/playbooks/executor.py`): `playbook.id`,
`playbook.contract_type`, `position.count`, `document.id`. Has per-position child
spans (`playbook.position`) carrying `playbook.position.id` and
`playbook.position.order` (`api/app/playbooks/nodes.py`).

**`tabular.execute`** attributes (`api/app/tabular/executor.py`):
`tabular.document_count`, `tabular.column_count`. Has per-cell child spans
(`tabular.cell`) carrying `tabular.document.id` and `tabular.column.name`
(`api/app/tabular/nodes.py`).

**Note on `playbook.position` coverage:** child spans are emitted in the `classify`
node but not yet in the `redline` node — tracked at
[DE-318](PRD.md#de-318--playbookposition-child-spans-on-the-redline-node-otel-deepening).

---

#### `autonomous.execute` / `autonomous.tool_call`

Emitted by the M4 Autonomous Layer. `autonomous.execute`
(`api/app/autonomous/executor.py`) wraps a full autonomous-session graph
invocation; `autonomous.tool_call` (`api/app/autonomous/guard.py`) wraps the
per-tool chokepoint that enforces the autonomy brakes (halt, phase-grant, cost
cap) and dispatches the tool. Both record **counts, type labels, IDs, and enum
values only — never raw parameters or document text.**

**Attributes on `autonomous.execute`:**

| Attribute | Description |
|---|---|
| `autonomous.session_id` | Session UUID |
| `autonomous.trigger_kind` | What initiated the session (e.g., watch / schedule / manual trigger kind) |
| `autonomous.halt_state` | Halt-state latch value at execution start |

**Attributes on `autonomous.tool_call`:**

| Attribute | Description |
|---|---|
| `autonomous.session_id` | Session UUID |
| `autonomous.phase` | Current session phase |
| `autonomous.tool` | The tool *intent* label (never the params) |
| `autonomous.halt_state` | Halt-state latch value at the tool boundary |
| `autonomous.outcome` | Set on every exit path: `external_halt` (R5 halt latch), `tool_not_granted` (R6 phase-grant miss), `cost_cap_reached` (R4 cap), or — on the dispatch path — the `ToolResult.outcome` from the executed tool |
| `autonomous.cost_usd` | Tool cost in USD; recorded only on the successful dispatch path |

The autonomous spans also write audit rows — see [§2.4 — Audit actions](#audit-actions).

---

#### `orchestration.job` / `orchestration.run` / `orchestration.effect`

**ADR 0038 D2, proposed; implemented on an unmerged branch and in no release.** A
governed run executes on the arq worker, not in the API request that accepted or
approved it. These spans put the worker's part of a run in the same trace as that
request. Attributes are **identifiers and labels only — never prompt, document or
answer text.** `autonomous.tool_call`, above, still wraps the chokepoint beneath
each `orchestration.effect`.

| Span | Emitted by | Wraps |
|---|---|---|
| `orchestration.job` | `api/app/workers/orchestration_worker.py` | One arq job for one session of a run. It continues the trace carried in the job (below). |
| `orchestration.run` | `api/app/autonomous/orchestration/executor.py` | One claimed execution of one session: the planning call, one task, or the combined answer. A child of `orchestration.job`. |
| `orchestration.effect` | `api/app/autonomous/orchestration/effects.py` | One durable effect: a model call, a document read, or a working-note read or write, each sent through the chokepoint. A tool call the application refuses is a step too: it has an effect span with `orchestration.intent` `refused` and `orchestration.step_kind` `tool_refused`, and no `autonomous.tool_call` beneath it, because nothing runs. It also leaves a zero-cost effect row, a step shown to the owner and an `orchestration.tool_refused` audit row. |

| Attribute | On | Description |
|---|---|---|
| `orchestration.root_id` | all three | UUID of the run's root session |
| `orchestration.session_id` | all three | UUID of the session the span acts for (the root, or one task) |
| `orchestration.outcome` | job, run | What the invocation ended as. On `orchestration.run`: `completed`, `waiting_children`, `busy` or `stopped`; not set when the run span fails. On `orchestration.job`: one of those, or `disabled` (the run's profile is switched off) or `interrupted` (an error ended the invocation; the recovery sweep resumes from stored state). Every job that opens a span records one. A job that arrives when no profile is enabled at all returns `disabled` before any span opens. |
| `error.type` | all three, and `autonomous.tool_call` | Set only when the span failed: the exception's class name, which is also the status description. These spans record no exception event and no exception message, because a message can quote SQL parameters, a provider's reply or document text (`quiet_span` in `api/app/observability_helpers.py`). |
| `orchestration.profile` | run | Registry profile identifier, for example `model_demo_v1` |
| `orchestration.role` | run | `root` or `child` |
| `orchestration.stage` | run | `planning` before a plan exists, `execution` after |
| `orchestration.phase` | effect | Autonomous phase the effect ran in |
| `orchestration.intent` | effect | The tool intent label, never its parameters |
| `orchestration.skill` | effect | Name of the pinned skill the session applies |
| `orchestration.step_kind` | effect | The step label shown to the owner, such as `model_turn` or `document_read`; empty when the effect has none |

**How a run's trace is connected.**

1. The API request that accepts a run (`POST /api/v1/chats/{chat_id}/runs`) or
   approves it is traced like any other request.
2. When the API queues the worker job it puts the request's W3C trace context in the
   job (`enqueue_orchestration_job` in `api/app/workers/queue.py`). `orchestration.job`
   continues that context, so the worker's spans share the request's trace. A job
   queued from inside a worker job, such as the wake-up of a run's tasks, carries that
   job's context the same way. The carrier is empty when tracing is not configured. A
   job woken by the recovery sweep, which runs outside any request, has nothing to
   continue and starts its own trace. So does a job whose carrier is malformed: the
   carrier is data from the queue, it grants nothing, and it cannot fail the job.
3. Inside the worker, `orchestration.run` wraps each claimed session and
   `orchestration.effect` wraps each effect. A model call leaves the worker through the
   same gateway client code the API uses, so its context continues to the gateway's
   spans.
4. **The arq worker must have `OTEL_EXPORTER_OTLP_ENDPOINT` set.** The worker
   initializes tracing from the same variables as the API; without an endpoint its
   spans are dropped and a run's trace ends at the API request. `docker-compose.yml`
   and `docker-compose.release.yml` pass `OTEL_EXPORTER_OTLP_ENDPOINT` (empty by default)
   and `OTEL_SERVICE_NAME` (default `lq-ai-arq-worker`, overridden by
   `LQ_AI_ARQ_WORKER_OTEL_SERVICE_NAME`) to `arq-worker`. Both recipes under
   `deploy/observability/` set `arq-worker` to `http://otel-collector:4318` with service
   name `lq-ai-arq-worker` and the same sampler default as the API.

**What was checked.** The plan's
[Implementation status](plans/issue-662-c1-governed-runs-in-chat.md#implementation-status)
lists `test_runs_in_chat.py` and `test_run_tracing.py` as the evidence for these spans and
for the trace context carried through queued jobs. It also lists no full Docker stack
smoke, so a run's trace through a Collector on a running Compose stack with these recipes
has not been observed.

---

### Metrics

Prometheus metrics are served by the api (`:8000/metrics`) and gateway
(`:8001/metrics`). These endpoints are always on but are reachable only inside the
Compose network (or wherever the operator's reverse proxy routes them) — they are
not exposed on a public interface by default.

| Metric | Type | Labels | Description |
|---|---|---|---|
| `lq_ai_api_http_requests_total` | Counter | `method`, `route`, `status` | Total HTTP requests handled by the api service |
| `lq_ai_api_http_request_duration_seconds` | Histogram | `method`, `route`, `status` | Request latency distribution on the api service |
| `lq_ai_gateway_http_requests_total` | Counter | `method`, `route`, `status` | Total HTTP requests handled by the gateway service |
| `lq_ai_gateway_http_request_duration_seconds` | Histogram | `method`, `route`, `status` | Request latency distribution on the gateway service |
| `lq_ai_gateway_inference_requests_total` | Counter | `provider`, `tier`, `outcome` | Inference dispatches by provider, tier, and outcome. Incremented by `_record_inference_outcome` in `gateway/app/router.py`, which emits `success`, `provider_error`, or `network_error`. See the note below on the `refused` label. |

**Known gap — the `refused` outcome label is never emitted.** The
`INFERENCE_REQUESTS_TOTAL` docstring in `gateway/app/observability.py` lists
`refused` as a possible `outcome` value, but no code path passes it:
`_record_inference_outcome` is called only with `success` or the two
`outcome_label_from_error` values (`provider_error` / `network_error`). The
tier-floor refusal path (`_write_refusal` in `gateway/app/api/inference.py`) returns
a `tier_below_minimum` gateway error **without** incrementing this counter. Treat
`refused` as documentation-only until a refusal counter increment is wired up.

---

### Audit actions

The M4 Autonomous Layer writes structured audit rows to the `audit_log` table for
every session lifecycle event, distinct from OTel spans. All autonomous-session
writes flow through `autonomous_audit` (`api/app/autonomous/audit.py`), which
stamps a canonical `autonomous_session.<event>` action and gates the `details`
dict to counts, type labels, IDs, costs, and enums — **never raw entity values**.

The `details` dict carries only structured scalars (e.g., `to_phase`, `reason`,
`tool`, `outcome`, `cost_total_usd`, `findings_count`, `artifacts_count`,
`projected_usd`).

| Audit action | Emitted by | When |
|---|---|---|
| `autonomous_session.phase_transition` | `api/app/autonomous/phases.py` | On each session phase transition (`details.to_phase`) |
| `autonomous_session.tool_call` | `api/app/autonomous/guard.py` | At the tool chokepoint — `outcome` ∈ `started`, the executed tool's outcome, or `tool_not_granted` |
| `autonomous_session.halted` | `api/app/autonomous/guard.py` (external halt), `api/app/workers/autonomous_worker.py` (idle timeout) | On a halt (`details.reason` = `external_halt` or `idle_timeout`) |
| `autonomous_session.cost_cap_reached` | `api/app/autonomous/guard.py` | When projected cost would exceed the session cap (`details.projected_usd`) |
| `autonomous_session.completed` | `api/app/autonomous/nodes.py` | On normal session completion (`details.cost_total_usd`, `findings_count`, `artifacts_count`) |
| `autonomous_session.halt_requested` | `api/app/api/autonomous.py` | On `POST /sessions/{id}/halt` — the API-layer request that precedes the executor's `halted` event |

**Known gap — `autonomous_session.started` is defined but never emitted.** The
closed-action set `_ACTIONS` in `api/app/autonomous/audit.py` includes `started`,
and the module docstring shows it as an example, but no production code path writes
it (the only `"started"` string in the executor is the `outcome="started"` *detail*
on a `tool_call` row, a different field). Session creation does not currently write
a `started` audit row. Treat `started` as a reserved-but-unused action until a
creation-time write is wired up.

**Governed-run audit rows.** Governed runs (ADR 0035) write `orchestration.<event>`
rows through the run store (`api/app/autonomous/orchestration/store.py`), with
`resource_type = autonomous_session` and the run's root session as `resource_id`.
`details` hold identifiers, counts, labels and amounts, never prompt, document or answer
text. The ADR 0038 branch (proposed, unmerged) adds `orchestration.tool_refused` (a call
the application refused: the registry tool name or `unregistered`, and a code, never the
model's own text) and `orchestration.run_closed` (an owner closed an uncertain run: the
number of effects closed and the amount charged). For a run hosted in a chat,
`orchestration.root_delivered` carries the chat and message identifiers. For a profile
whose answers are checked against documents it also records `verification`
(`citations_checked` or `unverified`), the counts of quotations verified, unverified and
unresolved, the number of quoted passages that carry no source marker and so were not
checked (`citations_unmarked`), and the fiduciary-gate status. If the checks themselves fail, the answer is
still delivered and the row records `verification: unverified` and `checks: failed`. The
chat receipts feed reads the `orchestration.*` rows through the run message's link to its
root session, so they appear in the chat's receipts drawer. Attaching a chat attachment to
the matter for a run writes `project.file_attached` with `source: run_selection`; that row
is keyed to the matter, so it is in the admin audit log and not in the chat's receipts.

---

### Routing log

The gateway writes one `inference_routing_log` row for every inference request: provider,
model, tier, tokens, latency, cost and whether anonymization ran. Two things tie a row to
what caused it. `chat_id` and `message_id` come from the `lq_ai_chat_id` and
`lq_ai_message_id` fields the backend sends. `purpose` is a label for the kind of
traffic, from the request's `lq_ai_purpose` field (`embedding` on the embeddings path).
The gateway keeps a closed set of labels. A request with no label records `chat`, and so
does a label outside the set. The column is `varchar(32)`, so a label must fit it.

| `purpose` | Recorded for |
|---|---|
| `chat` | Ordinary chat completions; also the fallback for no label or an unknown one |
| `embedding` | Embeddings calls |
| `judge_paraphrase` | Citation Engine paraphrase and ensemble judge calls |
| `judge_case_content` | Citation Engine whole-opinion judge for case law |
| `judge_authority_content` | The same judge for other authority sources |
| `judge_treatment` | Case-law treatment-layer judge |
| `tabular_extraction` | Tabular Review cell extraction |
| `playbook_executor` | Playbook executor |
| `playbook_easy_extract` | Easy Playbook extraction |
| `autonomous_executor` | A legacy single autonomous session's model calls |
| `orchestration_run` | A governed run's model calls: planning, tasks and the combined answer |

**Proposed, unmerged (ADR 0038 D2).** Only `chat`, `embedding` and `judge_paraphrase` were
in the set before. The other labels were already sent by the backend and recorded as
`chat`; recording them as themselves, and the chat and message identifiers on a run's
model calls, are implemented on the branch. Two Easy Playbook assembly labels,
`playbook_easy_assemble_describe_position` and `playbook_easy_assemble_describe_tier`,
are longer than the column and are not in the set, so those rows still record `chat`. The
set is `_KNOWN_PURPOSES` in `gateway/app/api/inference.py`. Chat and message identifiers
are also passed on `tool_call_log` rows, but that table records only calls to external
tool providers and neither shipped run profile grants one, so a run writes none.

---

### Logs

Structured logs are emitted by both services. **Log-trace correlation (injecting
`trace_id` / `span_id` into log lines) is not yet shipped** — tracked at
[DE-300](PRD.md#de-300--log-trace-correlation-via-structured-logger-trace_id--span_id-injection-otel-deepening-de-b).
Until DE-300 lands, pivoting from a span in Tempo or Honeycomb to the logs for that
request requires matching on timestamp + `service.name` manually.

---

## 3. Deployment recipes

Two ready-made Docker Compose overlays are in [`deploy/observability/`](../deploy/observability/).
Read [`deploy/observability/README.md`](../deploy/observability/README.md) first — it explains
how to switch between them and what each adds to the base stack.

### Self-hosted: Grafana + Tempo + Loki + Prometheus

**Recipe:** [`deploy/observability/grafana-tempo-loki/`](../deploy/observability/grafana-tempo-loki/)

Use this when you are starting fresh and want a self-contained observability stack
with no third-party SaaS accounts. The overlay adds Grafana, Tempo (traces),
Loki (logs), Prometheus (metrics), and an OTel Collector — all running alongside
the main LQ.AI Compose stack. The OTel Collector is the collection point; api and
gateway send spans to it over OTLP/HTTP; it fans out to Tempo. Prometheus scrapes
`/metrics` directly.

Time-to-first-trace once the overlay is running: under 15 minutes with the bundled
Grafana dashboard.

### Existing backend: OTel Collector standalone

**Recipe:** [`deploy/observability/otel-collector-standalone/`](../deploy/observability/otel-collector-standalone/)

Use this when you already run Honeycomb, Datadog, Lightstep, Splunk, or any other
OTLP-compatible backend and you do not want Grafana or Tempo locally. The overlay
adds only an OTel Collector configured to forward spans to your backend. You supply
the backend endpoint and API key via environment variables in the Collector config;
the api and gateway are wired to the local Collector, which handles batching and
export.

---

## 4. Anonymization and telemetry

The Anonymization Layer (Inference Gateway; [docs/security/anonymization.md](security/anonymization.md))
pseudonymizes sensitive entities — names, matter numbers, organization names, contact
details — before they reach a cloud inference provider. The same posture extends to
telemetry: **span attributes carry entity counts and type labels only, never raw
entity values.**

Concretely: if a request triggers anonymization of three person names and one matter
number, the `anonymization.entity_count` attribute is `4` and
`anonymization.entity_types` is the sorted array `["MATTER_NUMBER", "PERSON"]`. The actual names and the
matter number do not appear in any span attribute, span event, or metric label.

This invariant is enforced by `gateway/tests/test_anonymization_observability.py`.

Operators forwarding trace data to a third-party backend (Honeycomb, Datadog,
Lightstep) receive the same guarantee: the telemetry side-channel cannot leak what
the Anonymization Layer is designed to protect.

---

## 5. No telemetry by default

Per [PRD §5.7](PRD.md#57-no-telemetry-by-default): until `OTEL_EXPORTER_OTLP_ENDPOINT`
or a per-signal endpoint is set, **no traces leave the deployment.** The OTel SDK is
present in the service images but the TracerProvider is never initialized, and spans
are silently dropped.

Prometheus `/metrics` is always on. It is served on the internal Docker network only
(`:8000` for api, `:8001` for gateway); the operator's reverse proxy or a scrape
configuration inside the Compose network is required to reach it. The metrics
endpoint does not emit data to any external destination — it is a pull surface, not
a push surface.

This behavior is pinned by `tests/test_observability.py` (cross-cutting integration
test, added alongside this doc in M3-F3).

---

## 6. What's not yet shipped

The items below are honestly deferred. Each links to its PRD §9 tracking entry with
the acceptance criteria and contributor profile.

**OTel Deepening DEs (PRD §9, added at M3-F close):**

| DE | Title | Notes |
|---|---|---|
| [DE-299](PRD.md#de-299--otel-instrumentation-for-sqlalchemy--arq-workers-otel-deepening-de-a) | OTel instrumentation for SQLAlchemy + ARQ workers | DB query and background-job latency are blind spots today. The ADR 0038 branch (proposed, unmerged) gives the governed-run job path its own `orchestration.job` span, which is not general arq instrumentation. |
| [DE-300](PRD.md#de-300--log-trace-correlation-via-structured-logger-trace_id--span_id-injection-otel-deepening-de-b) | Log-trace correlation via structured-logger trace_id / span_id injection | Pivoting from a span to its logs requires manual timestamp correlation until this lands |
| [DE-301](PRD.md#de-301--otel-meterprovider-for-metrics-export-otel-deepening-de-c) | OTel MeterProvider for metrics export | Metrics today go only to Prometheus; OTel-native metrics export (Honeycomb-only, Datadog APM-only) is additive |
| [DE-302](PRD.md#de-302--reconcile-otel-with-the-openwebui-forks-inherited-telemetry-otel-deepening-de-d) | Reconcile OTel with the OpenWebUI fork's inherited telemetry | The OWUI-inherited layer runs as a parallel `service.name`; alignment or disable decision pending |
| [DE-303](PRD.md#de-303--browser-rum-via-opentelemetry-sdk-otel-deepening-de-e) | Browser RUM via OpenTelemetry SDK | Frontend spans not yet emitted; opt-in env var + CSP review required |

**Streaming coverage gaps:**

| DE | Title | Notes |
|---|---|---|
| [DE-315](PRD.md#de-315--streaming-rehydration-per-chunk-spans-otel-deepening-anonymization) | Streaming-rehydration per-chunk spans | `StreamingRehydrator` path not yet instrumented |
| [DE-317](PRD.md#de-317--inferencedispatch-span-on-the-streaming-path-otel-deepening) | `inference.dispatch` span on the streaming path | Non-streaming path only today |

**Playbook coverage gap:**

| DE | Title | Notes |
|---|---|---|
| [DE-318](PRD.md#de-318--playbookposition-child-spans-on-the-redline-node-otel-deepening) | `playbook.position` child spans on the redline node | Classify-node positions are spanned; redline-node positions are not |

**LLM-specific tracing sink (Langfuse) — not implemented.** [PRD §5.4](PRD.md#54-observability)
describes an optional self-hosted Langfuse sink for LLM-specific tracing. Nothing in `api/`
or `gateway/` implements it. The `telemetry:` block in `gateway.yaml.example`, with its
`opentelemetry` and `langfuse` entries, is accepted by the gateway's configuration loader
and read by no code. The `LANGFUSE_*` variables in `.env.example` and the Compose files
are read by no code either, so setting them has no effect. Trace export is controlled only
by the `OTEL_*` variables in [§1](#1-environment-variable-matrix). Spans, audit rows and
routing-log rows carry identifiers, counts and labels, not prompt or document text.

**SLO + RUM catalog (from [`docs/proposals/opentelemetry-deepening.md`](proposals/opentelemetry-deepening.md)):**
DE-E (Browser RUM, same as DE-303 above), DE-F (Published SLO catalog), and DE-G
(Performance regression tracking) are downstream of the shipped M3-F signals and are
deferred to whichever milestone first makes the signal inventory stable enough to
define meaningful targets.

---

*Maintained by the maintainer team. Updates land alongside observability changes. If
a claim in this doc doesn't match the code, the code is canonical — please
[open an issue](https://github.com/LegalQuants/lq-ai/issues).*
