# Handoff — Phase 1 (Autonomous Operability) resume at plan Task 7 → then close M4 → tag v0.4.0

> **For:** the next Claude Code session continuing on branch **`feat/lqvern-m4-autonomous`** in **`~/Code/lq-ai`** (canonical repo — NEVER `~/Desktop/lq-ai`; Bash cwd resets to `~/Desktop` between calls, so **prefix every command with `cd ~/Code/lq-ai &&`**).
>
> **Where we are:** Branch HEAD **`71cf149`**, pushed origin + tucuxi, tree clean (only the intentionally-untracked Donna doc `docs/lq-ai-skill-inputs-corpus.md` shows as `??` — leave it). Two big things already shipped this session: (A) the **M4-D2 docs + Learn honest-alignment sweep — DONE, committed, not gated**; (B) **Phase 1 of the platform-cohesion / autonomous-operability build — Tasks 1–6 of 9 DONE**. **RESUME AT plan Task 7.**

---

## 1. The contracts (read these)

- **Spec (approved):** `docs/superpowers/specs/2026-05-31-platform-cohesion-and-autonomous-operability-design.md` — build **§4 only**; §3 model + §5 roadmap are recommendation-only (Phases 2–5 NOT built).
- **Plan (task-by-task source):** `docs/superpowers/plans/2026-05-31-platform-cohesion-phase1.md` — 9 tasks, each with exact code/steps.
- **Workflow:** `superpowers:subagent-driven-development` — fresh implementer subagent per task, then a spec+quality review subagent before marking done. One combined review per task (or per tight cluster) is fine.

## 2. Phase 1 progress (the 9-task plan)

| Task | What | Status | Commit |
|---|---|---|---|
| 1 | Tabular Citation-Engine honesty fix (§4.5) | ✅ DONE + reviewed | `bab1304` |
| 2 | Backend `POST /autonomous/run-now` (trigger_kind='manual'; §4.4) | ✅ DONE + reviewed | `de3fcd5` |
| 3 | `runNow()` frontend API client | ✅ DONE + reviewed | `f3a0d61` |
| 4 | Cost-cap field in schedule/watch create modals (§4.3) | ✅ DONE + reviewed | `dad5ccf` |
| 5 | Readable target/KB/matter names in rows (§4.3) | ✅ DONE + reviewed | `0d32160` |
| 6 | "Run now" UI on Sessions page + Cypress smoke (§4.4) | ✅ DONE | `71cf149` |
| **7** | **Configure/education tab + instructive empty-states (§4.2)** | **⬜ RESUME HERE** | — |
| 8 | Home discoverability signpost → opt-in (§4.1) | ⬜ TODO | — |
| 9 | Final verification pass | ⬜ TODO | — |

**Reviews:** Tasks 1, 2, and the 3+4+5 cluster all passed independent spec+quality review ✅. Task 6 (`71cf149`) was implemented + self-reviewed (Cypress 9/9 passing after a `docker compose build web`) but **has NOT yet had its formal review subagent** — the next session should run a quick spec+quality review of `71cf149` (the Run-now UI) before/while doing Task 7, OR fold it into a combined review of Tasks 6+7.

## 3. RESUME — plan Task 7 (Configure tab + empty-states)

Read `cd ~/Code/lq-ai && sed -n '/## Task 7:/,/## Task 8:/p' docs/superpowers/plans/2026-05-31-platform-cohesion-phase1.md` for full steps. Summary:
- Add a **"Configure"** nav link as the FIRST entry in `web/src/routes/lq-ai/autonomous/+layout.svelte` `navLinks` (before "Sessions").
- Create `web/src/routes/lq-ai/autonomous/configure/+page.svelte` — honest plain-language education: On/Off (opt-in, off by default; enabled in Settings → Autonomous; off stops new runs, keeps receipts + halt), Schedules (cron run of a skill/playbook), Watches (run on KB doc-arrival), **Run now** (one-off test before arming — now exists, Task 6), where results land (Sessions + receipt, Memory/Precedents/Proposals/Notifications), Safety (R4 cost cap / R5 halt+idle / R6 per-phase grants + receipt). Link to `/lq-ai/settings/autonomous`. Do NOT overclaim (no custom-task authoring; Run-now is the only "test").
- Replace bare empty-states on Sessions/Schedules/Watches with instructive ones that name the first action + link to Configure.
- Gate: `cd ~/Code/lq-ai/web && npm run check:lq-ai` → 0 errors. Commit -s + 4.7 trailer; push BOTH remotes.

Then **Task 8** (Home signpost — read `FeaturedToolsRow.svelte`/`GettingStartedChecklist.svelte`/`getting-started-signals.ts` first; surface Autonomous on Home linking to `/lq-ai/settings/autonomous` when off, `/lq-ai/autonomous` when on — uses `$preferences.autonomous_enabled`), then **Task 9** (full verify: `check:lq-ai`, `npx vitest run`, backend `ruff/mypy/pytest tests/autonomous tests/test_openapi.py` via `api/.venv/bin/...`).

## 4. Hard rules (memorize)

- **Canonical repo `~/Code/lq-ai`**; prefix every command `cd ~/Code/lq-ai &&`.
- **DCO:** every commit `git commit -s` + trailer `Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>` (kept at 4.7 for branch consistency).
- **Push BOTH remotes** after each task: `git push origin feat/lqvern-m4-autonomous && git push tucuxi feat/lqvern-m4-autonomous`.
- **NEVER** run host-side `alembic upgrade head` against `127.0.0.1:15432/lq_ai` (live dev DB; crash-loops the stack). Phase 1 adds NO migration. Verify backend via pytest's throwaway DB only (use `api/.venv/bin/pytest` — the bare `pytest` on PATH has a broken starlette; tests need `DATABASE_URL` set or they SKIP — that's expected, they run in CI).
- **Do NOT `docker compose down -v`** (preserves attorney-review acceptance data: KB `9003dbc6-abf5-4f25-922b-588714f26405`, 4 autonomous sessions incl. the R4-halted one). To refresh the running UI use `docker compose build web && docker compose up -d web`.
- **Edit-tool TAB caveat:** the autonomous Svelte files are TAB-indented; the Edit tool can render tabs as spaces and fail to match. If an Edit fails, verify with `cat -A`/`od -c` and use `perl -i` / a precise heredoc with real tabs; confirm tabs preserved.
- For touched SvelteKit routes: `cd ~/Code/lq-ai/web && npm run check:lq-ai` must be **0 errors** (5 pre-existing warnings in TierFloorOverrideModal/ComingSoonModal/SkillDetailTabs are fine).

## 5. The stale-container gotcha (Kevin hit this 2026-05-31)

The running `web` container serves a **pre-built static bundle** (no HMR), so it can be many commits stale. Kevin saw the Autonomous-flow Learn playground still showing "PLANNED — M4 CAPABILITY" — but **source is correct** (`autonomous-flow.html:308-309` = "M4 — shipped (opt-in, off by default)", committed `32ab870`). The container just predates the Task-14 + Phase-1 commits. **Fix: `cd ~/Code/lq-ai && docker compose build web && docker compose up -d web`** (NOT down -v). Same reason the new Run-now button / cost-cap fields won't appear until rebuilt.

## 6. After Phase 1 (Tasks 7–9 done) → M4 close → v0.4.0

In order:
1. **Phase 1 Task 9 verify** passes.
2. **M4-D2 closeout — plan Task 20** (the original docs/Learn sweep's final consistency pass): re-grep residual dishonesty across touched docs/Learn; confirm historical artifacts untouched (`git diff --name-only main...HEAD | rg "SESSION-HANDOFF|M[1-4]-IMPLEMENTATION"` returns nothing but the allowed current handoff); produce the full edited/created inventory. (This was interrupted earlier and never run — do it now.)
3. **Rebuild the stack** (`docker compose build web && up -d web`) so Kevin's live UI reflects everything, for his attorney walk-through.
4. **Kevin's attorney legal-substance walk-through** — KEVIN owns this per [[feedback_no_maintainer_legal_review]]. Inputs = the live acceptance stack + its memory/precedent/receipt output.
5. **Tag v0.4.0** — the M4 branch (code + honest docs + Learn + Phase-1 operability) merges to `main` and tags together.

## 7. AFTER M4 closes — the Donna backend asks (3 tasks, fold into M4)

Full verbatim spec is in memory `project_donna_backend_asks.md` (and task tracker). Three independent, caller-scoped, back-compatible backend changes for the Donna frontend; each updates `docs/api/backend-openapi.yaml` + runs `api/tests/test_openapi.py` + reports the merged SHA so Donna bumps its `vendor/lq-ai` pin:
1. **skill_inputs reach non-templated skills** (= DE-328 Option A) — `gateway/app/skills/assembler.py`: append unconsumed bound inputs as a `### Provided inputs for {skill}` block; gateway test.
2. **`MessageCreate.file_ids`** — per-message chat file attach: `api/app/schemas/chats.py` + `schemas/gateway.py` (`lq_ai_file_ids`) + `api/app/api/chats.py` send+stream paths (validate caller-owned, forward, echo applied ids); document interaction with `skill_inputs type:"file"`.
3. **`PATCH /api/v1/users/me`** — profile edit (display_name; optional email w/ 409 on dup) in `api/app/api/users.py` + `models/user.py`; audit `user.profile_updated`.

## 8. Stack + acceptance state

Stack is UP (may be a stale `web` bundle — rebuild web to see Phase-1 UI). Admin `admin@lq.ai` / `AcceptTest12345!`; dashboard `localhost:3000`; dev DB head `0045`. Autonomous is opt-in — Kevin's account is already opted in (the Autonomous top-tab is visible for him). Acceptance data preserved (do NOT down -v).

---

*Drafted 2026-05-31 at the Phase-1 mid-build checkpoint (Tasks 1–6 done, HEAD `71cf149`). The spec + plan are the contracts; this handoff is the navigation aid. RESUME AT plan Task 7.*
