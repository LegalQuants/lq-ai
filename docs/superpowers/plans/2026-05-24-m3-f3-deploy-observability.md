# M3-F3 — Deployment Recipes + `docs/observability.md` + OTel-eval Playground Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Give operators a copy-paste path from zero to "I can see a chat-send trace in Grafana" — two `deploy/observability/` recipes (self-hosted Tempo+Loki+Grafana, and standalone Collector→your-backend), an operator guide `docs/observability.md`, a "no telemetry by default" regression test, and a 4th Learn playground that visualizes the F2 trace tree.

**Architecture:** The base `docker-compose.yml` already declares `OTEL_EXPORTER_OTLP_ENDPOINT: ${OTEL_EXPORTER_OTLP_ENDPOINT:-}` (empty → off) on `api`/`gateway`. Each recipe is a compose **overlay** (`docker-compose.observability.yml`) that (a) adds the observability services and (b) sets that env var to the in-network collector, composed via `docker compose -f docker-compose.yml -f deploy/observability/<recipe>/docker-compose.observability.yml`. Transport is OTLP/HTTP (port 4318), per the locked decision. No code changes to api/gateway — F3 is config + docs + one test + one playground.

**Tech Stack:** Docker Compose overlays, OpenTelemetry Collector (`otel/opentelemetry-collector-contrib`), Grafana Tempo, Grafana Loki, Grafana, Prometheus, Grafana provisioning YAML + dashboard JSON, a self-contained HTML playground (mirrors `web/static/learn/playgrounds/citation-engine-cascade.html`), pytest in the repo-root `tests/`.

---

## Decisions locked (carry into every task)

1. **Transport:** OTLP/HTTP, collector on `:4318`. (Locked F1/F2.)
2. **Sampler:** document `parentbased_always_on` (dev) + `parentbased_traceidratio` 0.1 (prod-ref) via `OTEL_TRACES_SAMPLER` env; **do not change any code default**.
3. **Overlay sets the endpoint:** the recipe overlay sets `OTEL_EXPORTER_OTLP_ENDPOINT=http://otel-collector:4318` on `api`+`gateway` (and bridges if trivial). Base compose stays no-telemetry-by-default.
4. **OWUI out of scope (DE-D):** do NOT touch `web/docker-compose.otel.yaml` (the OpenWebUI-fork OTel overlay) or the `open-webui` service name. LQ.AI services are `lq-ai-api`/`lq-ai-gateway`.
5. **No live-stack disruption during build:** the live bring-up validation (recipe 1 → see a trace in Grafana) is the real acceptance bar but bounces api/gateway with OTel ON. It is deferred to an explicit validation pass / M3-close fresh-install, NOT run silently during the build. Static `docker compose ... config` validation IS run per task.
6. **Honesty:** `docs/observability.md` documents only what's shipped; everything not-yet (browser RUM, OTel-native metrics export, SQLAlchemy/ARQ instrumentation, log-trace correlation, SLO catalog) links to the DE entries (DE-299..303, DE-A..G, DE-315/317/318).

---

## File structure (all NEW unless noted)

```
deploy/observability/
├── README.md                                         # which recipe, when
├── grafana-tempo-loki/
│   ├── README.md
│   ├── docker-compose.observability.yml              # Collector + Tempo + Loki + Prometheus + Grafana; sets OTEL endpoint on api/gateway
│   ├── otel-collector-config.yaml                    # OTLP/HTTP :4318 → Tempo (traces) + Prom (metrics scrape) ; logs path noted
│   ├── tempo.yaml
│   ├── loki.yaml
│   ├── prometheus.yaml
│   ├── grafana/provisioning/datasources/lq-ai.yaml   # Tempo + Loki + Prometheus datasources
│   ├── grafana/provisioning/dashboards/dashboards.yaml  # provider file
│   ├── grafana/provisioning/dashboards/lq-ai.json    # starter dashboard (tier mix, p99 by route, error rate)
│   └── .env.example
└── otel-collector-standalone/
    ├── README.md                                     # Honeycomb / Datadog / Lightstep specifics
    ├── docker-compose.observability.yml              # Collector only; sets OTEL endpoint on api/gateway
    ├── otel-collector-config.yaml                    # OTLP/HTTP in → operator backend (commented exporters)
    └── .env.example

docs/observability.md                                 # operator guide (6 sections)
tests/test_observability.py                           # NEW — no-telemetry-by-default contract
web/static/learn/playgrounds/otel-eval.html           # NEW — 4th playground
```

**Modify:** `README.md` (link observability.md in Documentation section ~L462; fix stale "Six interactive playgrounds" → "Eleven"), `docs/HONEST-STATE.md` (§7 link), `web/src/routes/lq-ai/learn/how/+page.svelte` (add §11 section).

---

### Task 1: `grafana-tempo-loki` recipe (config files + overlay)

**Files:** all under `deploy/observability/grafana-tempo-loki/` (see structure). 

- [ ] **Step 1:** Write `docker-compose.observability.yml` — an overlay adding: `otel-collector` (`otel/opentelemetry-collector-contrib:0.x`, mounts `otel-collector-config.yaml`, ports 4318), `tempo` (`grafana/tempo`, mounts `tempo.yaml`), `loki` (`grafana/loki`, mounts `loki.yaml`), `prometheus` (`prom/prometheus`, mounts `prometheus.yaml`, scrapes api+gateway `/metrics`), `grafana` (`grafana/grafana`, mounts provisioning, port 3001:3000). Add an `environment:` override block on `api` and `gateway` setting `OTEL_EXPORTER_OTLP_ENDPOINT: http://otel-collector:4318` and `OTEL_SERVICE_NAME` (`lq-ai-api`/`lq-ai-gateway`). All services on the default `lq-ai` network. Use named volumes for tempo/loki/grafana data.
- [ ] **Step 2:** Write `otel-collector-config.yaml` — `receivers.otlp.protocols.http` on `:4318`; `processors.batch`; `exporters`: `otlp/tempo` (to `tempo:4317`, tls insecure) for traces, and document that metrics come via Prometheus scrape of `/metrics` (collector need not handle metrics in recipe 1). `service.pipelines.traces` wires otlp→batch→otlp/tempo.
- [ ] **Step 3:** Write `tempo.yaml` (minimal single-binary: local storage, otlp receiver on 4317), `loki.yaml` (minimal single-binary), `prometheus.yaml` (scrape_configs for `api:8000/metrics` + `gateway:8001/metrics`).
- [ ] **Step 4:** Write `grafana/provisioning/datasources/lq-ai.yaml` (Tempo @ `http://tempo:3200`, Loki @ `http://loki:3100`, Prometheus @ `http://prometheus:9090`), `grafana/provisioning/dashboards/dashboards.yaml` (file provider → `/etc/grafana/provisioning/dashboards`), and `grafana/provisioning/dashboards/lq-ai.json` — 3 panels: (a) gateway tier mix = `sum by (tier) (rate(lq_ai_gateway_inference_requests_total[5m]))`; (b) p99 HTTP latency by route = `histogram_quantile(0.99, sum by (le,route) (rate(lq_ai_gateway_http_request_duration_seconds_bucket[5m])))`; (c) error rate by service = ratio of `status=~"5.."` over total from `lq_ai_*_http_requests_total`.
- [ ] **Step 5:** Write `.env.example` (e.g., `GF_SECURITY_ADMIN_PASSWORD`, `OTEL_TRACES_SAMPLER` default note).
- [ ] **Step 6: VALIDATE** the merged config:
  `cd ~/Code/lq-ai && docker compose -f docker-compose.yml -f deploy/observability/grafana-tempo-loki/docker-compose.observability.yml config >/dev/null && echo CONFIG_OK`
  Expected: `CONFIG_OK` (no YAML/merge errors). Fix any merge errors (env-required vars like LQ_AI_GATEWAY_KEY/JWT_SECRET must be present — source the repo `.env` or pass placeholders for the `config` check).
- [ ] **Step 7: Commit** `feat(m3-f3): grafana-tempo-loki observability recipe (Collector+Tempo+Loki+Prometheus+Grafana)`.

> README for this recipe is Task 3 (grouped with the overview README).

---

### Task 2: `otel-collector-standalone` recipe

**Files:** under `deploy/observability/otel-collector-standalone/`.

- [ ] **Step 1:** `docker-compose.observability.yml` — overlay adding only `otel-collector` (ports 4318) + the `OTEL_EXPORTER_OTLP_ENDPOINT`/`OTEL_SERVICE_NAME` overrides on api/gateway.
- [ ] **Step 2:** `otel-collector-config.yaml` — OTLP/HTTP receiver on 4318, batch processor, and a `service.pipelines.traces` with the exporter left as a clearly-commented placeholder plus three commented-out exporter blocks: **Honeycomb** (`otlp` exporter to `api.honeycomb.io:443` with `x-honeycomb-team` header), **Datadog** (`datadog` exporter with `api.key`), **Lightstep** (`otlp` to `ingest.lightstep.com:443` with `lightstep-access-token`). One active no-op `debug` exporter so the config validates out of the box.
- [ ] **Step 3:** `.env.example` (operator's backend keys, commented).
- [ ] **Step 4: VALIDATE:** `docker compose -f docker-compose.yml -f deploy/observability/otel-collector-standalone/docker-compose.observability.yml config >/dev/null && echo CONFIG_OK`.
- [ ] **Step 5: Commit** `feat(m3-f3): standalone OTel Collector recipe (forward to Honeycomb/Datadog/Lightstep)`.

---

### Task 3: `deploy/observability/README.md` + per-recipe READMEs

- [ ] **Step 1:** `deploy/observability/README.md` — overview + a decision table: choose `grafana-tempo-loki` (fresh, want a self-hosted stack) vs `otel-collector-standalone` (already have Honeycomb/Datadog/etc). Link `docs/observability.md`.
- [ ] **Step 2:** `grafana-tempo-loki/README.md` — prerequisites; the exact `docker compose -f ... -f ... up -d` command; the 15-min "verify a trace" walkthrough (`curl` a chat-send → Grafana `http://localhost:3001` → Explore → Tempo → search by trace ID); how to switch sampler via `OTEL_TRACES_SAMPLER`.
- [ ] **Step 3:** `otel-collector-standalone/README.md` — when to use; uncomment-your-backend instructions for Honeycomb, Datadog, Lightstep specifically; the run command.
- [ ] **Step 4: Commit** `docs(m3-f3): observability recipe READMEs + decision guide`.

---

### Task 4: `docs/observability.md` operator guide + links

- [ ] **Step 1:** Write `docs/observability.md` covering the six required sections:
  1. **Env-var matrix** — `OTEL_EXPORTER_OTLP_ENDPOINT`, `OTEL_SERVICE_NAME`, `OTEL_RESOURCE_ATTRIBUTES`, per-signal `OTEL_EXPORTER_OTLP_{TRACES,METRICS}_ENDPOINT`, `OTEL_TRACES_SAMPLER` (+ default `parentbased_always_on`, recommended prod `parentbased_traceidratio`=0.1). Note the trigger: OTel initializes iff one of the endpoint vars is set.
  2. **Per-signal inventory** — Traces: the F2 domain spans (`citation.verify`+stages, `anonymization.pre/.post`, `skill.execute`, `inference.dispatch`, `playbook.execute`/`tabular.execute`+children) with the filterable attributes. Metrics: `lq_ai_api_http_requests_total`, `lq_ai_api_http_request_duration_seconds`, `lq_ai_gateway_http_requests_total`, `lq_ai_gateway_http_request_duration_seconds`, `lq_ai_gateway_inference_requests_total` (one line each + labels). Logs: link forward to DE (log-trace correlation not yet shipped).
  3. **Two reference recipes** — when to choose each; link the recipe dirs.
  4. **Anonymization + telemetry** — span attributes carry counts/types only, never raw PII (the F2 guarantee); link `docs/security/anonymization.md`. Same anonymization posture for trace data sent to third-party backends.
  5. **No telemetry by default** — restate PRD §5.7; `/metrics` is on but only reachable inside the compose network.
  6. **What's not yet shipped** — link DE-299..303, DE-315/317/318, and the proposal's DE-A..G (browser RUM, OTel-native metrics, SQLAlchemy/ARQ, log correlation, SLO catalog).
- [ ] **Step 2:** Link `docs/observability.md` from `README.md` Documentation section (~L462) AND fix the stale "Six interactive playgrounds" → "Eleven" in "First steps after login".
- [ ] **Step 3:** Link it from `docs/HONEST-STATE.md` §7 (Operational state) — add an "Observability / OpenTelemetry" row or sentence pointing at the guide + recipes.
- [ ] **Step 4: Commit** `docs(m3-f3): docs/observability.md operator guide + README/HONEST-STATE links`.

---

### Task 5: "No telemetry by default" regression test

**Files:** Create `tests/test_observability.py` (repo-root cross-cutting tests).

- [ ] **Step 1: Write the test** — mirror `tests/test_error_code_contract.py`'s sys.path module-loading pattern to import BOTH `api/app/observability.py` and `gateway/app/observability.py`, then assert the contract:

```python
@pytest.mark.unit
def test_no_telemetry_by_default_api(api_observability) -> None:
    assert api_observability._otel_enabled(env={}) is False

@pytest.mark.unit
def test_no_telemetry_by_default_gateway(gateway_observability) -> None:
    assert gateway_observability._otel_enabled(env={}) is False

@pytest.mark.unit
@pytest.mark.parametrize("var", [
    "OTEL_EXPORTER_OTLP_ENDPOINT",
    "OTEL_EXPORTER_OTLP_TRACES_ENDPOINT",
    "OTEL_EXPORTER_OTLP_METRICS_ENDPOINT",
])
def test_any_otlp_endpoint_enables(api_observability, gateway_observability, var) -> None:
    assert api_observability._otel_enabled(env={var: "http://collector:4318"}) is True
    assert gateway_observability._otel_enabled(env={var: "http://collector:4318"}) is True
```

(Use module-scoped fixtures loading each `app.observability` via importlib + sys.path, like `test_error_code_contract.py`. Confirm `_otel_enabled` accepts an `env` kwarg — it does in both modules.)

- [ ] **Step 2: Run** (from repo root, with the api venv which has pytest):
  `cd ~/Code/lq-ai && api/.venv/bin/python -m pytest tests/test_observability.py -q` — expect green. (If sys.path loading needs both `api` and `gateway` importable, follow exactly what `test_error_code_contract.py` does.)
- [ ] **Step 3: Note** in the PR description that CI does not currently run the repo-root `tests/` dir (only api/gateway/web) — flag whether to add a CI job as a follow-up DE (CI changes are CODEOWNERS-gated).
- [ ] **Step 4: Commit** `test(m3-f3): pin no-telemetry-by-default across api + gateway`.

---

### Task 6: OTel-eval Learn playground + page wiring

**Files:** Create `web/static/learn/playgrounds/otel-eval.html`; modify `web/src/routes/lq-ai/learn/how/+page.svelte`.

- [ ] **Step 1: Build `otel-eval.html`** — a self-contained single HTML file MIRRORING `citation-engine-cascade.html`'s shell (same `:root` CSS variables / dark theme / two-column controls+preview layout / header with source links; copy that file's `<style>` scaffold and adapt). Content: an **annotated trace tree** for one chat-send showing the real F2 span hierarchy — root HTTP span → `inference.dispatch` (with provider/model/tier/tokens/cost/outcome attrs) → `citation.verify` → `citation.stage.*` children; plus `anonymization.pre/.post`, `skill.execute`, and (toggle) `playbook.execute`/`tabular.execute` with per-position/cell children. Controls let the user toggle scenarios (cache hit vs ensemble; anonymization on/off; playbook vs chat) and the tree + attribute panels update. Include the **5 operator questions** answered by the trace (why slow / how much did it cost / did anonymization run / which provider+model per tier / citation-cascade outcome distribution), each pointing at the span+attribute that answers it. Include sample **TraceQL / LogQL / PromQL** snippets and a side-by-side "attributes that appear vs. attributes that never appear (raw PII)" panel reinforcing the anonymization guarantee. All client-side; no network calls.
- [ ] **Step 2: Wire §11** into `+page.svelte` after the word-addin section (~L543), mirroring the section template exactly: `<section ... data-testid="lq-ai-learn-how-section-otel-eval">`, `<h2>11. Seeing it all at once: the observability trace</h2>`, a 2–3 sentence description, the `<iframe src="/learn/playgrounds/otel-eval.html" ... height:900px>`, and the `lq-playground-foot` with Open-full-screen + source links (`docs/observability.md`, `api/app/observability_helpers.py`).
- [ ] **Step 3: Verify** the web bundle builds (don't break the page): `cd web && <pkg-mgr> run check` or the project's svelte-check/lint if quick; otherwise confirm the iframe path + static file exist and the +page.svelte parses (no Svelte syntax error). Note in the PR that a visual smoke (rebuild `web`, open `/lq-ai/learn/how` §11) is pending.
- [ ] **Step 4: Commit** `feat(m3-f3): OTel-eval Learn playground (§11) — annotated trace tree + operator questions`.

---

### Task 7: Final validation + verification

- [ ] **Step 1:** Re-run BOTH recipe `docker compose ... config` validations (Task 1 Step 6, Task 2 Step 4) from a clean shell with repo `.env` sourced → both `CONFIG_OK`.
- [ ] **Step 2:** `cd ~/Code/lq-ai && api/.venv/bin/python -m pytest tests/test_observability.py -q` → green.
- [ ] **Step 3:** Confirm no api/gateway code changed in F3 (`git diff --stat origin/main...HEAD` should show only `deploy/`, `docs/`, `tests/`, `web/`, and the plan) — F3 is config/docs/test/web only.
- [ ] **Step 4: Live bring-up (DEFERRED — operator/maintainer decision):** Document in the PR that the "bring up recipe 1, send a chat, see the trace in Grafana within 15 min" acceptance check + the dashboard "shows live data" check are pending a live validation pass (they require running api/gateway with OTel ON, which bounces the dev stack). Recommend running them at M3-close fresh-install verification. Do NOT run silently.
- [ ] **Step 5:** Open PR (PR-3 of the OTel phase). Rebase onto main first if #86 (F2) has merged.

---

## Self-review

**Spec coverage (proposal PR-3 acceptance):**
- `deploy/observability/` with both subdirs → Tasks 1–3. ✓
- Merged `docker compose ... config` validates → Task 1 Step 6 + Task 2 Step 4 + Task 7. ✓
- `docs/observability.md` six sections + README + HONEST-STATE links → Task 4. ✓
- "No telemetry by default" test in `tests/test_observability.py` → Task 5. ✓
- Starter Grafana dashboard (3 panels) → Task 1 Step 4. ✓
- Standalone recipe covers Honeycomb/Datadog/Lightstep → Task 2 Step 2 + Task 3 Step 3. ✓
- 4th OTel-eval playground + §11 wiring (handoff addition) → Task 6. ✓
- "see a trace in 15 min" + "dashboard shows live data" → **deferred live validation, Task 7 Step 4** (honest: needs OTel-on bring-up; not run silently). ⚠ documented.

**Decisions explicit:** transport, sampler, overlay-sets-endpoint, OWUI-out-of-scope, no-live-disruption, honesty-links — all in the Decisions section.

**Risks:** (1) Grafana dashboard PromQL must match the real metric/label names (Task 1 Step 4 uses the confirmed names). (2) Collector/Tempo/Loki image versions — pin to recent stable tags; `config` validation only checks compose syntax, not image pulls. (3) The root `tests/` dir isn't in CI — flagged in Task 5 Step 3.
