# Handoff — M4 / LQVern: Phase C COMPLETE → resume at Phase D

> **For:** the next Claude Code session, branch **`feat/lqvern-m4-autonomous`** in **`~/Code/lq-ai`** (canonical repo — NEVER `~/Desktop/lq-ai`; Bash cwd resets to ~/Desktop between calls, so prefix every command with `cd ~/Code/lq-ai &&`).
> **Where we are:** **Phases A, B, C ALL COMPLETE.** The entire Autonomous Layer is shipped — backend (all `/autonomous/*` APIs) + the SvelteKit web dashboard. **RESUME AT Phase D.** Branch HEAD ~`04c85e4`, pushed to origin + tucuxi, working tree clean.

---

## Phase D — the remaining work

### Task M4-D1 — Learn-tab "Autonomous flow" visualization
Build per the spec **`docs/LQVern/learn-tab-autonomous-flow-viz-spec.md`** (spec-only so far). It's a Learn-tab "How it Works" visualization of the autonomous flow (phases → chokepoint/brakes → receipt). Lives under `web/src/routes/lq-ai/learn/`. **Gotcha:** `.gitignore`'s `build/` shadows `web/src/routes/lq-ai/learn/build/` — edits there need `git add -f`.

### Task M4-D2 — boundary-registers flip + fresh-install acceptance + docs finalize
- Flip R4 (economic) / R5 (temporal) / R6 (contextual) registers in **`docs/security/boundary-registers.md`** from "planned/Tier-2-design" to **shipped**, citing the now-implemented code (guard.py chokepoint, cost cap, halt switch + idle watchdog, per-phase `PHASE_GRANTS`). Update cross-refs from §1.8 + §3.10. The doc's "future milestone closes that flip a register's state must update this document in the same PR" rule applies.
- **Fresh-install acceptance** (the memory `feedback_dry_run_value` rule): a clean `git clone` → `docker compose up` → opt in → exercise the autonomous surfaces, before tagging. Catches whole classes of bugs that lint/type/live-with-prior-state don't.
- Finalize M4 docs (PRD §3.10 status flips to shipped, HONEST-STATE, db-schema, etc.).

---

## M4-C2 recap (just completed, 2026-05-27)

Brainstormed the dashboard layout with Kevin (8 decisions, visual companion mockups), wrote `docs/LQVern/m4-c2-dashboard-design.md` + a 20-task `docs/LQVern/m4-c2-implementation-plan.md`, executed subagent-driven (fresh implementer per task → spec-compliance review → code-quality review → fix → re-review). Shipped:
- **Backend opt-in slice:** `users.autonomous_enabled` column (migration **0044**), `/users/me/preferences` GET+PATCH field, `AutonomousEnabledUser` dependency gating the 14 mutate endpoints (read + halt stay on `ActiveUser` — the **opt-out split**: opted-out users keep audit-trail read + halt, mutate 403s), spawn-path opt-in guards (`watch_trigger` + schedule sweep join `User` + require `autonomous_enabled`), and per-entry `timestamp`s already present in `build_receipt` (pinned by a regression test).
- **Web dashboard** (`web/src/routes/lq-ai/autonomous/` + `web/src/lib/lq-ai/api/autonomous.ts` + `settings/autonomous/`): opt-in toggle; opt-in-gated **Autonomous top-tab** + left-rail sub-app (mirrors `admin/*`) with a redirect guard; **Sessions** list + inline Halt; **receipt** as a chronological interleaved timeline (`buildTimeline` in `web/src/lib/lq-ai/autonomous/receipt-timeline.ts`); **Memory** review (state tabs + keep/edit-on-keep/dismiss/delete); **Precedent** board (dismiss + promote→Project); **Proposals** (accept/reject); **Schedules** + a `CronInput` with client-side next-run preview (`web/src/lib/lq-ai/autonomous/cron.ts`); **Watches** (KB-trigger); **Notifications** rail page + unread badge.
- **Verification:** 322 backend tests + 124 web unit tests + **8 Cypress E2E** (`web/cypress/e2e/m4-autonomous.cy.ts` — opt-in→tab, redirect, receipt, halt, memory keep, precedent dismiss, opt-out) all green; ruff format + ruff check + mypy clean; OpenAPI still 113 paths.
- **Deferred:** **DE-323** (surface proposals on the Matter detail page) + **DE-324** (global-chrome notification bell) — both filed in PRD §9.

### Decisions locked in C2 (honor; don't re-litigate)
- IA: new "Autonomous" top-tab → left-rail sub-app (A), not a single dashboard.
- Opt-in = **full server-side enforcement** (not UI-only); opt-out keeps read+halt reachable, mutate 403s.
- Receipt = chronological interleaved timeline (sort entries by their `timestamp` key — NOT `at`).
- Promote→accept loop lives **inside** the Autonomous area (Proposals page); matter-page review is DE-323.
- Cron input = preset dropdown + Custom raw + client-side next-run preview; server 422 is authoritative.
- Notifications = rail page + unread badge; global bell is DE-324.

---

## ⚠️ Incident + lesson from the C2 session (READ — new memory)

Mid-session, Kevin's running Docker app broke (`login … ERR_CONNECTION_REFUSED`). **Root cause:** a plan step ran `alembic upgrade head` against `DATABASE_URL=…@127.0.0.1:15432/lq_ai` — which is the **live dev DB shared with the running stack**, not a throwaway. That jumped the dev DB from 0038→0044 while the running (pre-M4) container images only knew 0038, crash-looping the api+arq+ingest trio. **Fixed** by rebuilding the api/arq/ingest **and web** containers from current branch code (`docker compose build … && up -d`), which applied 0044 and served the dashboard.
**Rule (now in memory `feedback_no_host_alembic_on_dev_db`):** NEVER run host-side `alembic` against `127.0.0.1:15432/lq_ai`. Verify migrations via pytest only (conftest builds its own throwaway DB). To run a new migration in the dev stack, **rebuild the api+arq-worker+ingest-worker trio together** and let their entrypoint apply it (the standing `feedback_migration_rebuild_all_workers` rule).
**Current stack state:** all `lq-ai-*` containers (api trio + web) rebuilt from this branch and healthy; dev DB at **0044**; the dashboard is live at http://localhost:3000 (web 3000:8080, api 8000:8000).

## Tracked tech debt (not blocking; for a cleanup pass or DE)
- **Root shell layout doesn't centralize `initPreferences`** (`web/src/routes/lq-ai/+layout.svelte`) — each page calls it; the Autonomous tab can lag a navigation on a cold load before the prefs store hydrates (the localStorage cache + the reactive store make this benign in practice). Pre-existing pattern, surfaced during C2-T9 review. Candidate: call `initPreferences` once in the root shell.
- **`playbooksApi` not in the api barrel** (`web/src/lib/lq-ai/api/index.ts`) — schedules/watches import it directly. One-line consistency fix.
- Minor cosmetics noted in reviews: a "permanent soft-delete" confirm string (memory page), a duplicate "Expression" column (schedules table). Cosmetic only.

---

## How to execute (the workflow Kevin chose)
- **Subagent-driven, per task** (`superpowers:subagent-driven-development`): fresh implementer with full pasted task text → spec-compliance review → code-quality review → fix → re-review. For **frontend** tasks the backend TDD loop doesn't transfer (use build → `npm run check` *no-NEW-errors* → vitest helpers → Cypress). **`npm run check` has a ~9359-error pre-existing OpenWebUI-fork baseline** — the gate is "no new errors in the files this task touches," never zero.
- **Gates:** `ruff format` AND `ruff check` (separately) + `mypy` (api); web `npm run check` + `npm run lint`. **DCO** `git commit -s` + the `Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>` trailer. **Push BOTH remotes** after each task (`git push origin feat/lqvern-m4-autonomous && git push tucuxi feat/lqvern-m4-autonomous`). Never delete branches.
- Local test DB: read `POSTGRES_PASSWORD` from repo-root `.env`, then `cd api && DATABASE_URL="postgresql+asyncpg://lq_ai:<pw>@127.0.0.1:15432/lq_ai" ./.venv/bin/pytest … -q` (conftest = throwaway DB — safe; do NOT run alembic against this URL).

*Drafted 2026-05-27 at M4-C2 close.*
