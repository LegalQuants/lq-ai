# M4-C2 — Autonomous dashboard: design

> **Status:** Design agreed (brainstorm, 2026-05-25). Feeds the M4-C2 implementation plan.
> **Scope:** the SvelteKit web dashboard for the Autonomous Layer (`web/src/routes/lq-ai/autonomous/`), driving the now-complete `/autonomous/*` API (sessions, memory, precedents, proposals, schedules, watches, notifications).
> **Constraints:** OpenWebUI SvelteKit fork — **SvelteKit, not React; design-system primitives, not ad-hoc Tailwind** (CLAUDE.md). The web layer **renders receipts; it does not run the loop** (ADR 0013 D2). Autonomous is **off by default, opt-in per user** (PRD §3.10).
> **References:** Task M4-C2 in `docs/M4-IMPLEMENTATION-PLAN.md`; PRD §3.10; ADR 0013 D2/D3/D4/D5.

---

## 1. Information architecture

A new **`Autonomous` top-tab** (added to `web/src/lib/lq-ai/tabs.ts`) opens a **sub-app with a left rail**, mirroring the existing `admin/*` multi-page pattern. The rail switches between sibling pages; **Sessions** is the landing page.

| Rail item | Route | Drives |
|---|---|---|
| Sessions | `/lq-ai/autonomous` (and `/sessions/[id]`) | `GET /sessions`, `GET /sessions/{id}`, `POST /sessions/{id}/halt` |
| Memory | `/lq-ai/autonomous/memory` | `GET/POST /memory`, keep/dismiss/delete |
| Precedents | `/lq-ai/autonomous/precedents` | `GET /precedents`, dismiss, promote |
| Proposals | `/lq-ai/autonomous/proposals` | `GET /project-context-proposals`, accept/reject |
| Schedules | `/lq-ai/autonomous/schedules` | `GET/POST/PATCH/DELETE /schedules` |
| Watches | `/lq-ai/autonomous/watches` | `GET/POST/PATCH/DELETE /watches` |
| Notifications | `/lq-ai/autonomous/notifications` | `GET /notifications?unread=`, `POST /{id}/read` |

A new **`autonomous.ts`** api-client module under `web/src/lib/lq-ai/api/` wraps every endpoint, following the per-domain `apiRequest` convention (see `models.ts`, `intakeBridges.ts`). Shared row/list components live under `web/src/lib/lq-ai/components/` where reuse warrants.

## 2. Opt-in gate (full enforcement)

§3.10 requires autonomous off-by-default, opt-in per user, **enforced server-side** — there is no such gate today (spawn paths only check each resource's own `enabled` flag). C2 therefore includes a **contained backend slice**:

- **`autonomous_enabled: bool` (default `false`)** added to the server-synced user preferences: a migration, the `Preferences` Pydantic schema (GET required / PATCH optional), and the existing `PATCH /users/me/preferences` handler. Mirrors the migration-0019 precedent for preference fields.
- **Toggle UI:** a new **Settings → Autonomous** page (`web/src/routes/lq-ai/settings/autonomous/`) with the opt-in toggle + a short explainer of what the layer does and the boundary registers (R4/R5/R6) that bound it. Pre-opt-in, this page is the only autonomous-related surface reachable.
- **UI gating:** the `Autonomous` top-tab and rail are hidden until opted in; direct navigation to an autonomous route redirects to the Settings → Autonomous page when off.
- **Spawn-path guards:** `watch_trigger.fire_watches_for_kb` and the schedule sweep (`_run_schedule_sweep`) skip sessions for users whose `autonomous_enabled` is false.
- **Opt-out split (transparency-preserving, per §1.3):** when a user opts out —
  - **Reachable:** `GET /sessions`, `GET /sessions/{id}` (receipts), `POST /sessions/{id}/halt` — you never lose the audit trail of what already ran, and can still stop a runaway session.
  - **403:** all create/mutate paths — schedules, watches, memory keep/edit/dismiss/delete, precedent dismiss/promote, proposal accept/reject, notification read.
  - A FastAPI router **dependency** enforces the split (a read+halt allowlist; everything else requires `autonomous_enabled`).

Each guard and the split get pytest coverage.

## 3. Sessions + receipt (the headline UX)

**Sessions list** (landing): newest-first rows — status pill (running/completed/halted/failed) · trigger (schedule/watch/manual) · current phase · cost/cap · started-at. A **running** row shows an inline **Halt** button (confirm dialog → `POST /sessions/{id}/halt`). Paginated newest-first (the endpoint already paginates).

**Receipt view** (`/sessions/[id]`): rendered as a **chronological interleaved timeline** — phase-transition markers and tool calls woven into a single vertical thread that reads top-to-bottom as "what the agent did and why." Each tool-call node expands to show intent, params **summary** (IDs / counts / enum labels only — never raw values, honoring the alignment contract), cost, outcome, and gate decision. The terminal state (completed / cost_cap_reached / halted+reason) is the final node. Halt repeats at the top while the session is running.

**Backend tweak:** `build_receipt` currently emits `phase_transitions[]` and `tool_calls[]` as two separately-ordered lists without per-entry timestamps. Add a per-entry timestamp (from each audit row's `created_at`) to both so the web layer can merge them into one correctly-ordered timeline. One-line-per-entry change in `receipt.py`; covered by an updated receipt test.

## 4. Memory review (system-proposes, user-owns · D4)

Filtered list with **state tabs**: **Proposed** (default — where the work is) · Kept · Dismissed, backed by `GET /memory?state=`.

- **Proposed** rows: `Keep` / `Edit & keep` / `Dismiss`. Edit-&-keep opens an inline textarea and calls `keep` with `body.content` (edit-on-keep).
- **Kept** rows: `Edit` / `Delete`.
- **Dismissed** rows: `Delete`.

Consistent with the sessions / intake-bridges list idiom.

## 5. Precedent board + promote loop

**Board** (`/precedents`): read + `Dismiss`, same filtered-list idiom. Each entry offers **Promote** → pick a Project → `POST /precedents/{id}/promote` creates a `project_context_proposals` row.

**Proposals** (`/proposals`): pending proposals listed with **Accept** (`accept` → appends to `projects.context_md`) / **Reject** (`reject` → discards). The full promote→review loop stays **inside the Autonomous area**; on accept, a toast links to the updated matter.

→ **DE (filed):** also surface pending proposals as an inbox banner on the Matter detail page (`/lq-ai/matters/[id]`). Deferred to keep C2 from touching the Matters route.

## 6. Schedules + watches config

Both create via a **modal** (matching `NewMatterModal`). List rows mirror intake-bridges: an **enable/disable** toggle (`PATCH`) and **soft-delete**.

- **Cron input (schedules):** a **preset dropdown** (Daily / Weekly on… / Monthly on… / **Custom**) that compiles to a 5-field cron client-side; **Custom** reveals a raw cron field. A **client-side next-run preview** (small in-repo helper, no new dependency) plus **live validation** surfacing the API's 422 on invalid/unsatisfiable expressions.
- **Target picker:** playbook **or** skill (`playbook_id` / `skill_ref`), reusing `SkillPicker` + the playbooks list; optional Project scope (`project_id`).
- **Watches:** required, immutable **KB picker** (`knowledge_base_id`) + the same target picker. No cron.

## 7. Notifications

A **rail page** (`/notifications`) listing notifications with an **unread badge** on the rail item and the `Autonomous` top-tab (`GET /notifications?unread=true` for the count). Mark-read on click (`POST /{id}/read`) + a mark-all-read affordance. Email is already sent server-side (C1); this is the in-app channel.

→ **DE (filed):** a global-chrome notification bell (cross-cutting OpenWebUI shell change, with its own opt-in gating). Deferred to keep C2 contained.

## 8. Scope

All six surfaces ship with full controls in C2 (the backend is complete; each surface is an API wrapper). Two enhancements are deferred as DEs (matter-page proposals; global bell).

## 9. Deferred enhancements to file (PRD §9)

- **DE-323 — Autonomous context proposals on the Matter detail page.** Surface pending `project_context_proposals` as an inbox banner on `/lq-ai/matters/[id]`, alongside the in-Autonomous Proposals surface (M4-C2 §5 option B).
- **DE-324 — Global-chrome notification bell.** A bell + unread badge in the shared OpenWebUI chrome with its own opt-in gating, in addition to the Autonomous rail Notifications page (M4-C2 §7).

## 10. Verification

- `cd web && npm run check` (svelte-check) passes; `npm run lint` clean.
- Cypress E2E (`web/cypress/e2e/m4-autonomous.cy.ts`): opt-in → view a session receipt → halt → keep a memory entry → dismiss a precedent.
- Visual smoke: autonomous surfaces unreachable until opt-in.
- Backend slice (pytest): `autonomous_enabled` preference round-trip; spawn-path guards skip opted-out users; router-dependency 403s on mutate-when-off; read+halt reachable when off; `build_receipt` per-entry timestamps. OpenAPI conformance updated for the preferences change.

---

*Drafted 2026-05-25 from the M4-C2 layout brainstorm. Decisions here are the input to the M4-C2 implementation plan.*
