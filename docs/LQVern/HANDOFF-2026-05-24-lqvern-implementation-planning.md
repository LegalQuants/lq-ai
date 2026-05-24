# Handoff — M4 / LQVern: write the implementation plan + Learn-tab viz spec

> **For:** the next Claude Code session, on the **`feat/lqvern-m4-autonomous`** branch in **`~/Code/lq-ai`**.
> **Your job:** produce (1) the **M4 implementation plan** and (2) the **Learn-tab visualization spec** for the Autonomous Layer. The *design* is done and **approved by Kevin** — you are turning it into an executable plan, not re-deciding it.
> **Process:** this is the `writing-plans` step that follows a completed brainstorm. Invoke the **`superpowers:writing-plans`** skill for the implementation plan. Do **not** re-open the design unless you find a genuine contradiction.

---

## 0. Start here (orientation, in order)

1. `CLAUDE.md` — project orientation + decision-routing + conventions (read first if unfamiliar).
2. **`docs/adr/0013-autonomous-layer-design-influences.md`** — THE design. Pins every decision (D1–D6) + lists the remaining implementation-level open questions.
3. **`docs/PRD.md §3.10 Autonomous Layer`** — the built-out capability spec (data model, API surface, functional reqs, the alignment contract).
4. **`docs/LQVern/agentic-flow-alignment-guide.md`** — the contributor how-to with the `guarded_tool_call` chokepoint pseudo-code, backend-leverage table, and OTel attribute-hygiene rules. Your plan implements exactly this shape.
5. `docs/LQVern/README.md` — folder guide (and the note that `de265.patch` is **superseded** — do not apply it).
6. `docs/HONEST-STATE.md` — what's shipped vs deferred (sanity check before claiming anything).

Then read the **patterns to mirror** (these are the canonical implementations your plan copies):
- `api/app/playbooks/{executor,nodes,state}.py` — the LangGraph + Pydantic-typed-state executor the autonomous executor mirrors. **This is your closest analog — read it carefully.**
- `api/app/observability_helpers.py` — `get_tracer` / `record_attributes` / `@traced` (no-op when OTel off).
- `api/app/citation/cost.py` — the M2-E2 rolling-average cost estimator (for the R4 cap).
- The `audit_log` write pattern (`audit_action(...)`) in `api/app/api/*.py`.
- `api/app/workers/` + the arq/Redis settings — the durable queue + cron the executor runs on.
- `gateway/tests/test_anonymization_observability.py` — the privacy-guard test to mirror for autonomous spans.
- `api/app/api/playbooks.py` + `api/tests/` — endpoint + test house style.

---

## 1. Status (as of 2026-05-24)

- **v0.3.0 is shipped + tagged** (M3 complete). `main` HEAD `d54df6b`. Release workflow green (images + SBOM + cosign signatures). v0.3.0 GitHub Release published + Latest.
- **M4/LQVern design phase: COMPLETE + APPROVED.** The 3 design docs above are committed on `feat/lqvern-m4-autonomous` (pushed to **both** origin and tucuxi).
- **This handoff exists because** the design session ran very long (M3-close + tag + Tucuxi mirror + DE-305 fix were all in it); the implementation plan deserves a fresh context window.

## 2. The approved design — decisions you must honor (do not re-litigate)

From ADR 0013:
- **D1 — single-agent v1**, designed to extend. One agent per `autonomous_session`. **DE-294 (cross-agent handoff validation) stays deferred** — do NOT plan multi-agent orchestration.
- **D2 — executor in `api/app/autonomous/`** on the **arq-worker**, a LangGraph state machine mirroring `api/app/playbooks/`. Inference goes through the **gateway** (never a direct provider call) — that's what gives autonomous flows anonymization + tier enforcement + cost accounting for free. The gateway stays the stateless key-holding boundary. (This supersedes §3.10's old "OpenWebUI Pipelines" wording.)
- **D3 — the brakes (DE-293), adopted from Clawern's shape:** R4 per-session `max_cost_usd` (deployment default $5 in `gateway.yaml`), R5 `halt_state` enum + `POST …/halt` + 5-min idle auto-halt, R6 phase-gated tool grants (`intake→analysis→drafting→ethics_review→delivery`). **Checked before every tool call, at one chokepoint.**
- **D4 — memory = *system-proposes, user-owns*.** Agent observes + proposes; user views/edits/deletes/keeps; no silent writes.
- **D5 — precedent board absorbed**, distinct from Project context (user-authored, per-matter) and per-user memory (patterns about the *user*). Precedent board = patterns about the *documents/clauses across matters*, read-mostly, user-dismissable, per-user isolated.
- **D6 — the alignment contract is non-optional:** every flow emits `autonomous.session` + `autonomous.tool_call` OTel spans (counts/types/IDs/costs only — **never raw entity values**), a closed-enum audit trail, and a human-readable per-session receipt. New code without these is not done.

**The four v1 primitives:** Watches (KB-arrival trigger), Scheduled tasks (cron), Per-user memory, Precedent board.

## 3. Deliverable 1 — the M4 implementation plan (`writing-plans`)

Produce a phased plan (suggest writing it to `docs/M4-IMPLEMENTATION-PLAN.md`, mirroring `docs/M3-IMPLEMENTATION-PLAN.md` house style). It must cover at least:

- **Data model + Alembic migration(s):** `autonomous_sessions` (with `max_cost_usd`, `cost_total_usd`, `halt_state` enum, `current_phase`, `idle_halt_minutes`, `cost_cap_reached`), `autonomous_schedules`, `autonomous_watches`, `autonomous_memory`, `precedent_entries`. All per-user, hard-isolated. Update `docs/db-schema.md`. (Heed the migration-rebuild-all-workers rule in memory.)
- **The executor** (`api/app/autonomous/{executor,nodes,state}.py`): the LangGraph state machine + the single `guarded_tool_call` chokepoint enforcing R4/R5/R6 (per the alignment guide's pseudo-code), the closed `ToolIntent` enum, the `PHASE_GRANTS` map, OTel spans, audit writes.
- **The four primitives:** watch-trigger plumbing (resolve ADR 0013 open-Q1: likely direct arq-enqueue from the ingest pipeline), the cron scheduler on arq, the memory propose/keep flow, the precedent-board write/read.
- **API surface** (per PRD §3.10): `/autonomous/memory`, `/schedules`, `/watches`, `GET /sessions[/{id}]`, `POST /sessions/{id}/halt`, `/precedents`. Unit + integration + OpenAPI-conformance tests; update `docs/api/backend-openapi.yaml`.
- **Notifications:** email + in-app (ADR 0013 open-Q2; webhook-to-bridge is a later fold-in).
- **The acceptance tests (the bar — from DE-293):** R4 overspend halts with `cost_cap_reached`; R5 external halt stops on next tool call + idle auto-halt; R6 `ethics_review` can't call an `intake`-only tool; **privacy-guard test** (no raw entity value in any `autonomous.*` attribute — mirror `test_anonymization_observability.py`); **isolation test** (user A can't read user B's memory/precedents).
- **Boundary-registers doc update:** flip R4/R5/R6 to "shipped" with line-level citations in `docs/security/boundary-registers.md` when implemented.
- **Phasing:** suggest scaffolding + brakes first (prove the substrate), then the four primitives, then notifications + Learn viz. Each phase independently testable. Honor the §1.9 conservative posture + TDD.

**Resolve ADR 0013's three "Open questions remaining"** in the plan: (1) watch trigger plumbing, (2) notification surface, (3) precedent-board per-user vs per-deployment (pinned per-user for v1; note the alternative).

## 4. Deliverable 2 — the Learn-tab visualization spec

Spec (don't necessarily build yet — Kevin can decide build-now-vs-later) the following, mirroring the existing playground conventions (`web/static/learn/playgrounds/otel-eval.html`, `test-landscape.html` — self-contained single-file HTML, the shared dark theme, controls + preview, copy-out, honest "what's not built" caveats):
- **New "Autonomous flow" playground** — step through a single-agent session: phase transitions → guarded tool calls → the R4/R5/R6 brakes firing → the per-session receipt. The headline teaching point: *you can audit exactly what the agent did and why.*
- **How-it-Works (`web/src/routes/lq-ai/learn/how/+page.svelte`)** — a new section embedding that playground (it'll be §13; otel-eval is §11, test-landscape would be §12 once #91-era wiring lands — verify current section numbering at build time).
- **Build page (`…/learn/build/+page.svelte`)** — an "anatomy of an aligned agentic flow" element pointing at the alignment guide.
- **Updates to existing viz:** `data-residency.html` + `system-architecture.html` gain the new `api/app/autonomous` arq node (and its data stores).
- **Honesty:** until the autonomous layer ships, the playground must mark itself as illustrating a *planned* M4 capability (don't imply it's running).

## 5. Conventions + gotchas (from CLAUDE.md + memory)

- **TDD** (red→green), **ruff format + ruff check** (both, separately), **mypy** (api standard). New endpoints: unit + integration + OpenAPI-conformance tests. **DCO sign-off** (`git commit -s`) + the `Co-Authored-By: Claude Opus 4.7 (1M context)` trailer.
- **Two-remote push:** `tucuxi` IS now configured in `~/Code/lq-ai`. Push branches to **both** origin and tucuxi.
- **Canonical repo is `~/Code/lq-ai`** — never the stale `~/Desktop/lq-ai` (iCloud-corrupted).
- **`.gitignore build/` shadows `web/src/routes/lq-ai/learn/build/`** — edits to that file need `git add -f`.
- **OTel domain spans require an api/gateway image rebuild** to appear in a running stack (the F-phase code is no-op until built); rebuild before trusting a "no spans" observation.
- **Postgres host port is 15432** in `~/Code/lq-ai` `.env`. Local test DB: `cd api && DATABASE_URL="postgresql+asyncpg://lq_ai:<POSTGRES_PASSWORD from .env>@127.0.0.1:15432/lq_ai" ./.venv/bin/pytest -m "unit or integration" -q` (conftest makes a throwaway test DB — safe).
- **Stop on architectural questions** not anchored in the design — ask Kevin rather than guess.

## 6. Open workflow decision for Kevin (surface early)

The design docs (ADR 0013 + PRD §3.10 build-out + alignment guide) currently live only on `feat/lqvern-m4-autonomous`. **Decide with Kevin:** merge the design docs to `main` now via a small docs PR (so main's PRD doesn't lag the pinned design for months), or keep everything on the LQVern branch until M4 lands. (Claude leaned toward merging the docs to main + keeping LQVern as the implementation base.)

## 7. Loose ends (not blocking, for awareness)

- **PR #96 (DE-305 / #92) is MERGED** → `main` `8b8e549`. The **v0.3.1 patch is in flight**: version-bump PR **#97** (api+gateway `__version__` 0.3.0→0.3.1) is open (protected main needs it merged before tagging). Once #97 merges, cut the tag: `git tag -a v0.3.1 <main HEAD> -m "v0.3.1 — DE-305 default-install fix"` + `git push origin v0.3.1` (Release workflow runs green: images + SBOM + cosign) + `git push tucuxi v0.3.1` + `gh release create v0.3.1 --latest` (the workflow does NOT auto-create the GitHub Release). Same flow as v0.3.0 (memory `project_lq_ai_status`).
- **Open dependabot:** #66 (docling→3), #69 (html2canvas→2), #72 (marked 9→18) — held majors awaiting eval; #68 (langgraph→1.3) fails CI (breaking) — **note: langgraph is what the executor uses, so the langgraph major bump intersects M4; evaluate it as part of M4 dep work**; #73 (fastapi) may have auto-merged.
- The bridge test suites (`slack-bridge/`, `teams-bridge/`) and the repo-root `tests/` are **not in the main CI matrix** — a known gap.

---

*Drafted 2026-05-24 by Claude Code at the end of the M4/LQVern design session. The design is approved; this is the brief to turn it into an executable plan. Start with §0, honor §2, produce §3 + §4.*
