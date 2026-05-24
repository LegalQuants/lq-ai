# Session handoff — 2026-05-23 — M3-E COMPLETE (E1 verify + E2 docs); next is M3-F (OTel)

> **Why this file:** This session opened with M3 Phase D shipped and ran through **all of M3-E** — the pre-tag fresh-install verification (E1) and the three documentation PRs (E2a/E2b/E2c). Six PRs merged (#79–#84). The next phase is **M3-F (OpenTelemetry deepening)** — a code-heavy, sequential three-PR phase. This handoff is written so F can start cold.

## TL;DR for the next session

- **`main` is at `a9dbc85`** (PR #84). Local canonical repo is **`~/Code/lq-ai`** (moved off `~/Desktop/lq-ai` this session to escape the iCloud Finder-dup wave; the Desktop copy is a stale removable fallback).
- **M3-E is done.** E1 (fresh-install verify) found 8 issues → 4 fixed (#80), 8 DEs filed (#81 DE-305..312, #83 DE-313). E2 shipped all docs + 3 Learn-tab playgrounds + architecture-diagram M3 updates.
- **Next: M3-F1 → F2 → F3** (OTel). Sequential. Plan in [`docs/proposals/opentelemetry-deepening.md`](proposals/opentelemetry-deepening.md) + [`docs/M3-IMPLEMENTATION-PLAN.md`](M3-IMPLEMENTATION-PLAN.md) "Phase F". **This is backend code work, not docs** — start with F1.
- **Running stack** (`~/Code/lq-ai`, `docker compose --profile slack --profile teams up`): backend (api/gateway/arq-worker/ingest-worker) is **current** with `main` (rebuilt for #80; no backend code landed in #81–84). The **web container is one PR behind** (#84's playgrounds/how-page) — rebuild `web` if you want to visually smoke the playgrounds. Admin fixture: `admin@lq.ai` / `E1VerifyAdmin!2026`. Postgres host port remapped to **15432** (host Postgres on 5432).

## What shipped this session (PRs #79–#84, all merged)

| PR | What | Type |
|---|---|---|
| #79 | DELETE-204 FastAPI pitfall recipe → CLAUDE.md "Common pitfalls" | docs |
| #80 | **M3-E1 fixes**: F3 version bump, F6 tabular citations, F7 doc-name, F8 OpenAPI export gap + 5 regression tests | **code** |
| #81 | M3-E1 deferred findings → PRD §9 (DE-305..312) | docs |
| #82 | M3-E2a: 4 capability docs (playbooks/word-addin/tabular-review/intake-bridges) + PRD §3 status flips | docs |
| #83 | M3-E2b: quickstart onboarding + README + architecture viz + OpenAPI audit (F1/F3/F4/F6) + db-schema (0036/0037/0038) + sig-lite + DE-313 | docs |
| #84 | M3-E2c: 3 Learn-tab playgrounds (playbook-cascade, tabular-review, word-addin-flow) + system-architecture.html M3 update | docs/web |

### M3-E1 outcome (the fresh-install verification)

All 5 M3 surfaces verified end-to-end on a virgin `~/Code/lq-ai` stack (cold build, all profiles, 10/10 services healthy, alembic 0038). Driven headless via curl+JWT against the API; the operator did the GUI-confirmation pass. **Tabular extraction quality verified excellent** (values matched the 5-NDA corpus variant table exactly).

**Fixed in #80:**
- **F3** — `api/app/__init__.py __version__` was stuck at `0.1.0` (never bumped through v0.2.0); the M3-B8 Word handshake surfaced it as a stale `deployment_version`. Bumped to `0.3.0`.
- **F6** — Tabular cell citations never surfaced through the API. The executor persists grounding chunks as `cited_chunk_ids: list[str]`, but the read-side `CellResult` models `citations: list[Citation]` with no bridge → deserialized empty on every cell. Fixed with a `TabularRow` `model_validator` synthesizing **display-only** `citation_id = uuid5(NS, chunk_id)`. (Real Citation-Engine provenance deferred → DE-309.)
- **F7** — Tabular row `document_name` showed the document UUID, not the filename. The load-documents node now joins `File.filename`.
- **F8** — The M3-C4a `/tabular/executions/{id}/export` endpoint was missing from the OpenAPI sketch.

**Deferred (DE-305..313):** DE-305 (bridge `${VAR:?}` breaks all compose cmds when unset), DE-306 (quickstart port-collision note), DE-307 (File schema page_count/char_count never populate), DE-308 (Easy Playbook clustering over-segments + misses "Standard of Care" axis), DE-309 (real Citation-Engine tabular provenance), DE-310 (per-cell tier/cost telemetry), DE-311 (single-source version), DE-312 (**P1: bridge OAuth E2E never tunnel-tested**), DE-313 (SOC2/ISO27001 alignment docs for M3 boundaries — don't exist yet, counsel-gated).

## IMPORTANT honesty correction made this session

The M3-E1 verbal report initially said "Citation Engine confirmed" for the built-in playbook. **That was imprecise.** Verifying against code (`api/app/playbooks/state.py` docstring + no Citation-Engine import in `api/app/playbooks/`) showed that **both the playbook executor AND the tabular executor anchor answers with verbatim `matched_text` + `cited_chunk_ids` via lexical FTS — NOT the M2 Citation Engine verification cascade** (that integration is deferred for both). The capability docs (#82) + PRD flips document this honestly. **Carry this into F2:** the Citation Engine cascade that F2 instruments (`api/app/citation/verification.py`) is the M2 chat-citation path; the playbook/tabular surfaces do *not* run it.

## Loose ends (not blocking F, but track them)

1. **Pre-existing README dead links** — `docs/playbook-authoring-guide.md` and `docs/deployment-cookbook.md` are linked from README but were never written. Out of E2b scope (pre-existing, untouched lines). Quick follow-up: repoint (e.g., to `docs/skill-authoring-guide.md` / `docs/quickstart.md`) or remove. Not yet filed as a DE.
2. **Playground visual smoke** — rebuild the `web` container, then open `/lq-ai/learn/how` and confirm sections 8–10 render + each playground's controls work (browser step; not yet done).
3. **Word desktop sideload** (M3-E1) — the one E1 surface that needs hands-on Word/M365; never exercised (no automation). Still open.
4. **Bridge OAuth E2E** (DE-312, P1) — Slack/Teams plumbing verified in isolation only; real OAuth round-trip against a public tunnel never done.
5. **v0.3.0 tag** — happens at M3-close, after F. `app.__version__` is already `0.3.0`.

## Next: M3-F — OpenTelemetry deepening

Three sequential PRs. Authoritative spec: [`docs/proposals/opentelemetry-deepening.md`](proposals/opentelemetry-deepening.md) (acceptance criteria in "How we'd know it's done"). Substrate already exists: the **M1 OTel SDK + httpx auto-instrumentation** are in place; no-telemetry-by-default (only initializes when `OTEL_EXPORTER_OTLP_ENDPOINT` is set); OTLP/HTTP transport; per-service `observability.py`.

### F1 — Trace context propagation audit + regression test (~6–8 hr; no deps)
- Verify W3C `traceparent`/`tracestate` propagation across **api → gateway → provider**. Fix any gap the audit finds.
- Regression tests in **both** `api/tests/test_trace_propagation.py` + `gateway/tests/test_trace_propagation.py` asserting a chat-send produces a **single trace ID** across api + gateway (must fail without the fix).
- Update `docs/architecture.md` §OBS to confirm end-to-end correlation in one sentence.
- No regression in existing `api/tests/test_observability.py` + `gateway/tests/test_observability.py`.

### F2 — Domain spans + rich attributes (~14–18 hr; depends on F1)
- Manual instrumentation with documented attributes + child spans + span events:
  - Citation Engine cascade (`api/app/citation/verification.py`) → top-level `citation.verify` span + per-stage children.
  - Anonymization middleware (`gateway/app/anonymization/middleware.py`) → `anonymization.pre` / `.post` spans + skip-reason events.
  - Skill runner → `skill.execute` spans.
  - Gateway inference dispatch (`gateway/app/router.py`) → `{inference.provider,.model,.tier,.outcome,.tokens_in,.tokens_out,.cost_usd}`.
  - Playbook + Tabular executors (`api/app/playbooks/`, `api/app/tabular/`) → `playbook.execute` / `tabular.execute` spans with per-position / per-cell children.
- **ANONYMIZATION-OF-ATTRIBUTES GUARANTEE (critical):** span attributes carry counts + types, **never raw entity values**. Enforced by `gateway/tests/test_anonymization_observability.py`.
- In-memory OTel exporter tests confirm each span/attribute. No measurable p99 chat-send regression.
- New `observability_helpers.py` per service (the `@traced` helper) — must NOT duplicate `opentelemetry-instrumentation-fastapi`'s HTTP automation (it's for explicit domain spans).

### F3 — Deployment recipes + `docs/observability.md` + OTel-eval playground (~16–22 hr; depends on F2)
- `deploy/observability/` with two recipes: Grafana Tempo+Loki+Prometheus, and standalone Collector. Merged-compose `config` must validate.
- `docs/observability.md` operator guide (env-var matrix, per-signal inventory, anonymization-and-telemetry posture, no-telemetry-by-default, DE-299..303 links) + starter Grafana dashboard (tier mix, p99 by route, error rate). Linked from README Quickstart + HONEST-STATE.md §6+§7.
- "No telemetry by default" regression test in `tests/test_observability.py`.
- **OTel-eval Learn-tab playground** (4th new playground, alongside E2c's 3 — same pattern, mirror `web/static/learn/playgrounds/citation-engine-cascade.html`, wire into `learn/how/+page.svelte` as section 11): annotated trace tree for a chat-send + the 5 operator questions (why slow / how much cost / did anonymization run / which provider+model per tier / citation-cascade outcome distribution) + sample TraceQL/LogQL/PromQL + the attrs-that-appear-vs-not side-by-side.

### Decisions to lock at PR-open (from the proposal §"Decisions to lock")
- **Sampler:** `parentbased_always_on` dev / `parentbased_traceidratio` 0.1 prod-ref; document both, don't change code default (operator picks via env).
- **Transport:** stay OTLP/HTTP.
- **Helper location:** per-service `observability_helpers.py` (not a shared lib); the cross-service contract is the *attribute names*.
- **OWUI-fork OTel:** out of scope (DE-D); LQ.AI services are `lq-ai-api` / `lq-ai-gateway`, OWUI stays `open-webui`.

### Related OTel DEs already filed/known (PRD §9, DE-299..303 + the proposal's DE-A..G)
DE-A (SQLAlchemy + ARQ worker instrumentation), DE-B (log-trace correlation), DE-C (MeterProvider/metrics export), DE-D (reconcile OWUI OTel), DE-E (browser RUM — sensitive, opt-in), DE-F (SLO catalog), DE-G (perf-regression tracking). File any newly-surfaced ones during F.

## Working conventions reaffirmed this session

- **Repo at `~/Code/lq-ai`** now (not Desktop). No api bind-mount → rebuild api/arq-worker/ingest-worker together after backend changes; rebuild `web` for frontend changes.
- **DCO sign-off** (`git commit -s`) + **two-remote push** (`git push origin <b> && git push tucuxi <b>`; this session only pushed origin — `tucuxi` mirror NOT pushed, do it if the policy still holds).
- **Branch preservation** — feature branches preserved on origin, not deleted. Handoff branches (like this one) hold the handoff doc only and are not merged to main.
- **Honest framing** — surface deferrals/overclaims as findings; the docs were written aspirationally pre-implementation and several overclaimed (signed-manifest M3-B7, Word feature surface, Slack slash-command, "four playbooks") — all corrected this session.
- **Parallel agents** worked well for independent doc/playground builds (briefed with a template + capability doc + honest-state caveats), but **verify their output** (they caught real things — the `document_names`-not-a-column discrepancy — and also made path/link errors that needed fixing).

---

*Generated 2026-05-23 by Claude Code. Branch `session-handoff-2026-05-23-m3-e-complete` (handoff doc only; not merged). Next session: start M3-F1.*
