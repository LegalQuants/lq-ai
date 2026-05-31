# Honest Alignment: Docs + Learn — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reconcile every current-facing doc and all Learn-tab visualizations to what is actually built in the codebase (M1→M4), and add Learn visualizations for shipped capabilities not yet represented.

**Architecture:** One continuous pass anchored on a rewritten `docs/HONEST-STATE.md` "truth-map" produced first from a ground-truth codebase read; every subsequent doc/viz edit conforms to that map. Documentation work, not code — the only "tests" are (a) verifying each asserted fact against source before writing it and (b) for Learn, confirming the page renders. Historical artifacts are preserved untouched.

**Tech Stack:** Markdown docs; self-contained offline HTML/CSS/JS Learn playgrounds (`web/static/learn/playgrounds/`) following existing conventions; SvelteKit Learn routes (`web/src/routes/lq-ai/learn/`); verification via `grep`/`rg`/file reads against `api/`, `gateway/`, `web/`, `skills/`, `api/alembic/versions/`.

**Spec:** `docs/superpowers/specs/2026-05-30-honest-alignment-docs-learn-design.md`

**Branch:** `feat/lqvern-m4-autonomous` (this is M4-D2 doc finalization; merges to main + tags v0.4.0 with M4). Repo: `~/Code/lq-ai` (NEVER `~/Desktop`; `cd ~/Code/lq-ai &&` prefix every command). DCO `git commit -s` + trailer `Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>`. Push BOTH remotes (origin + tucuxi) after each task.

**Truth discipline (applies to EVERY task):** never write a capability/status/path/field/label claim from memory — grep or read the source first. No overclaiming ("handles all X"), no understating shipped work. On any cross-doc conflict, `HONEST-STATE.md` (Task 1) wins.

**Out of scope (do NOT edit):** all past `docs/SESSION-HANDOFF-*.md`, `docs/M1-IMPLEMENTATION-ORDER.md`, `docs/M1-PROGRESS.md`, `docs/M{2,3,4}-IMPLEMENTATION-PLAN.md`, and `docs/LQVern/` plan/design/handoff docs EXCEPT the active M4 handoff (Task 13). No code changes — record any code drift in HONEST-STATE / file as a DE.

---

## File Structure (what gets created or modified)

**Created:**
- `docs/autonomous-layer.md` — M4 feature doc (Task 11).
- New Learn playgrounds under `web/static/learn/playgrounds/` — one per confirmed gap (Tasks 15+; exact set determined by Task 1's gap list).

**Modified — docs:** `docs/HONEST-STATE.md` (Task 1), `README.md` (Task 4), `docs/PRD.md` (Tasks 5, 12), `docs/architecture.md` (Task 6), `docs/db-schema.md` (Task 7), `docs/observability.md` (Task 8), `docs/security/boundary-registers.md` (Task 9), per-feature docs (Task 10), `docs/quickstart.md` (Task 10), active M4 handoff (Task 13).

**Modified — Learn:** all 14 playgrounds + 4 pages audited (Task 14 produces the audit + per-file fix list; Tasks executed per-file).

---

## PHASE 0 — The truth-map spine

### Task 1: Ground-truth codebase analysis → rewrite `docs/HONEST-STATE.md`

**Files:**
- Modify: `docs/HONEST-STATE.md`
- Read (no edit): `api/app/`, `gateway/app/`, `web/src/`, `web/static/learn/`, `skills/`, `api/alembic/versions/`, `api/tests/`, `gateway/tests/`

- [ ] **Step 1: Read the current HONEST-STATE to see what it claims**

Run: `cd ~/Code/lq-ai && cat docs/HONEST-STATE.md`
Note every status claim (esp. the known-stale "M3 and M4 not yet started in source" and any §3.11/§3.12 autonomous cross-refs — autonomous is §3.10).

- [ ] **Step 2: Enumerate shipped capabilities from ground truth**

Establish, by reading source (not memory), the true status of each capability. Minimum evidence to gather:
```bash
cd ~/Code/lq-ai
# API routers actually mounted:
rg -n "include_router|APIRouter\(" api/app/api/*.py api/app/main.py | head -80
# Migrations present (schema truth):
ls api/alembic/versions/ | sort
# Autonomous layer wired (M4):
rg -n "guarded_tool_call|ToolIntent|run_autonomous_session|build_receipt" api/app/autonomous/*.py | head
# Brakes R4/R5/R6:
rg -n "CostCapReached|SessionHalted|ToolNotGranted|cost_cap_reached" api/app/autonomous/guard.py
# Citation engine, anonymization, tiers, playbooks, tabular, word-addin, intake-bridges:
rg -ln "anonymiz" gateway/app api/app | head
ls api/app/playbooks api/app/citation 2>/dev/null; ls word-addin 2>/dev/null
rg -ln "slack|teams|bridge" api/app/api docker-compose.yml | head
# Learn viz inventory:
ls web/static/learn/playgrounds/
```
For each capability record: **name · true shipped status (shipped / partial-with-specifics / not-built) · which doc(s) describe it · which Learn viz covers it (or "GAP") · any stale/false claim found.**

- [ ] **Step 3: Rewrite `docs/HONEST-STATE.md` as the capability truth-map**

Replace stale content. Structure: a dated header ("current as of <commit>"), then a table or section list with the five columns from Step 2 for every capability across M1→M4. This section is the authoritative source for all later tasks. Flag every drift found (these become the fix-list other tasks consume). Include a short "known code drift / DEs" subsection referencing DE-325/326/327.

- [ ] **Step 4: Verify — no claim unsupported**

Re-grep each "shipped" claim's keystone symbol/migration/endpoint. Confirm the "GAP" entries truly have no playground file. Confirm no remaining "not started" lie about a shipped layer:
```bash
cd ~/Code/lq-ai && rg -n "not yet started|not started|planned|coming soon" docs/HONEST-STATE.md
```
Expected: every remaining hit is genuinely-true (about something actually not built).

- [ ] **Step 5: Commit**

```bash
cd ~/Code/lq-ai && git add docs/HONEST-STATE.md && \
  git commit -s -m "docs(m4-d2): rewrite HONEST-STATE as the M1-M4 capability truth-map

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>" && \
  git push origin feat/lqvern-m4-autonomous && git push tucuxi feat/lqvern-m4-autonomous
```

---

## PHASE 1 — Core docs

> Each task: identify claims → verify against source → reconcile in place → re-verify → commit + push both remotes. The HONEST-STATE truth-map (Task 1) is the reference; do not re-derive status, but DO re-grep any specific path/field/label before writing it.

### Task 4: README.md

**Files:** Modify `README.md`

- [ ] **Step 1: Read README + list every status/capability claim**
Run: `cd ~/Code/lq-ai && cat README.md` — note each claim about what LQ.AI does/ships, the milestone status, feature list, and any quickstart/install snippet.
- [ ] **Step 2: Cross-check each claim against the truth-map + source**
For each claim, confirm against `docs/HONEST-STATE.md` (Task 1) and re-grep specifics (e.g. an endpoint or `docker compose` service it names). List discrepancies.
- [ ] **Step 3: Reconcile in place**
Edit so shipped reads as shipped, unshipped as unshipped; the feature list matches reality (M1 ingestion/KB/chat, M2 citation+anonymization+tiers, M3 playbooks+tabular+word-addin+intake-bridges, M4 autonomous layer). Conservative phrasing where a feature is partial.
- [ ] **Step 4: Verify**
Run: `cd ~/Code/lq-ai && rg -n "TODO|coming soon|not yet|planned" README.md` — confirm any hit is genuinely accurate. Confirm any `docker compose`/CLI snippet matches `docker-compose.yml` / `api/app/cli.py`.
- [ ] **Step 5: Commit + push** (DCO + trailer; push both remotes).

### Task 5: docs/PRD.md — capability statuses

**Files:** Modify `docs/PRD.md` (§3 capability sections; §3.10 autonomous; the brake registers)

- [ ] **Step 1:** `cd ~/Code/lq-ai && rg -n "SHIPPED|PLANNED|DEFERRED|not yet|in progress|M[0-9]" docs/PRD.md | head -120` — locate every status marker.
- [ ] **Step 2:** Cross-check each §3.x capability status against the truth-map. Focus: §3.10 Autonomous Layer (now shipped — executor, chokepoint, R4/R5/R6, four primitives, receipts, opt-in), citation engine, anonymization, tiers, playbooks, tabular, word-addin, intake-bridges.
- [ ] **Step 3:** Flip shipped capabilities to SHIPPED with honest scope notes; keep genuinely-deferred items as deferred. Reconcile any stale section cross-references.
- [ ] **Step 4:** Verify each flipped status against its keystone source symbol (re-grep). `rg -n "§3.11|§3.12" docs/PRD.md` — confirm autonomous cross-refs are corrected.
- [ ] **Step 5:** Commit + push (note: PRD §9 DE filing is Task 12, separate commit).

### Task 6: docs/architecture.md
**Files:** Modify `docs/architecture.md`
- [ ] **Step 1:** Read it; list each subsystem/data-flow claim.
- [ ] **Step 2:** Verify the component inventory against actual services (`docker-compose.yml`: api, gateway, web, postgres, redis, minio, ingest-worker, arq-worker, slack-bridge, teams-bridge, ollama) and the autonomous layer (arq job, not a separate service). Confirm the gateway-as-only-key-holder boundary still holds.
- [ ] **Step 3:** Reconcile (add the autonomous executor + intake bridges if absent; correct any service list).
- [ ] **Step 4:** Verify service names against `docker-compose.yml`: `cd ~/Code/lq-ai && rg -n "^  [a-z-]+:" docker-compose.yml`.
- [ ] **Step 5:** Commit + push.

### Task 7: docs/db-schema.md
**Files:** Modify `docs/db-schema.md`
- [ ] **Step 1:** `cd ~/Code/lq-ai && ls api/alembic/versions/ | sort` — the full migration set (through 0045) is the schema truth.
- [ ] **Step 2:** Cross-check every documented table/column against migrations + `api/app/models/`. Confirm the autonomous tables (autonomous_sessions/schedules/watches/memory + precedent_entries + autonomous_notifications + project_context_proposals + the `max_cost_usd`/`params`/`autonomous_enabled` columns) and any M2/M3 tables are documented.
- [ ] **Step 3:** Reconcile (add missing tables/columns; fix wrong ones; supersede any sketched-but-renamed tables e.g. `autonomous_tasks`).
- [ ] **Step 4:** Verify: pick 5 tables at random and confirm columns match the `CREATE TABLE`/`op.create_table` in the owning migration.
- [ ] **Step 5:** Commit + push.

### Task 8: docs/observability.md
**Files:** Modify `docs/observability.md`
- [ ] **Step 1:** Read it; list each span name / attribute / audit-action / outcome claim.
- [ ] **Step 2:** Verify against source: `cd ~/Code/lq-ai && rg -n "start_as_current_span|record_attributes|autonomous_session\.|inference.dispatch|outcome=" api/app gateway/app | head -80`. Confirm the autonomous spans/audit actions + the M2 inference-routing observability are described; confirm no claimed-but-unemitted span (cf. the known `gateway/app/observability.py` "refused" outcome that's never emitted — document honestly or note as known-gap).
- [ ] **Step 3:** Reconcile.
- [ ] **Step 4:** Verify each named span/attribute exists in source (re-grep).
- [ ] **Step 5:** Commit + push.

### Task 9: docs/security/boundary-registers.md — R4/R5/R6 → SHIPPED
**Files:** Modify `docs/security/boundary-registers.md`
- [ ] **Step 1:** Read; find the R4/R5/R6 (and any other autonomous-layer) register rows + their status.
- [ ] **Step 2:** Verify the brakes are implemented + tested: `cd ~/Code/lq-ai && rg -n "CostCapReached|SessionHalted|ToolNotGranted" api/app/autonomous/guard.py && ls api/tests/autonomous/test_brakes.py`.
- [ ] **Step 3:** Flip R4 (cost cap), R5 (external halt + idle watchdog), R6 (phase-gated tool grants) to SHIPPED, with citations to the chokepoint + tests + the live acceptance evidence (terminal_reason=cost_cap_reached). Note: this is a `docs/security/**` file → security-review-gated per CODEOWNERS; that's expected.
- [ ] **Step 4:** Verify no register still claims a shipped brake is pending.
- [ ] **Step 5:** Commit + push.

---

## PHASE 2 — Per-feature docs + new autonomous-layer.md

### Task 10: Per-feature docs reconciliation
**Files:** Modify `docs/citation-engine.md`, `docs/playbooks.md`, `docs/tabular-review.md`, `docs/word-addin.md`, `docs/intake-bridges.md`, `docs/skill-authoring-guide.md`, `docs/quickstart.md`

Do these one file per sub-step (each is its own commit + push). For EACH file:
- [ ] **Step (per file) a:** Read the file; list its capability/endpoint/status claims.
- [ ] **Step (per file) b:** Verify against source (the owning module + the truth-map). Examples: citation-engine → `api/app/citation/`; playbooks → `api/app/playbooks/` + seed migration 0032; tabular → tabular module + export; word-addin → `word-addin/` (confirm shipped scope honestly — e.g. which doc types); intake-bridges → slack/teams bridge services + `docs/intake-bridges.md` against the bridge code; quickstart → the actual upload-then-attach flow + `docker compose` steps.
- [ ] **Step (per file) c:** Reconcile in place (conservative on partial features).
- [ ] **Step (per file) d:** Verify the specific paths/endpoints named exist (re-grep).
- [ ] **Step (per file) e:** Commit (one commit per file) + push both remotes.

### Task 11: Create docs/autonomous-layer.md
**Files:** Create `docs/autonomous-layer.md`
- [ ] **Step 1:** Gather the M4 facts from source: executor phase machine (`api/app/autonomous/executor.py`, `nodes.py` — intake→analysis→drafting→ethics_review→delivery), the chokepoint (`guard.py` `guarded_tool_call` + `ToolIntent` + `PHASE_GRANTS`), brakes R4/R5/R6, the four primitives (watches/schedules/memory/precedent) + their endpoints, receipts (`receipt.py` + `build_receipt`/`build_receipt_safe`, terminal_reason), opt-in (`autonomous_enabled`), `max_cost_usd`.
- [ ] **Step 2:** Write the doc: overview, architecture (arq job not a service), the phase walk, the single-chokepoint security model, the brakes, the primitives + API surface, the receipt/transparency story, opt-in + cost cap. Conservative + honest (note the light-v1 ethics gate, the gateway-error honest path).
- [ ] **Step 3:** Verify every endpoint/field/enum named exists: `cd ~/Code/lq-ai && rg -n "autonomous" api/app/api/*.py | head` + spot-check against `api/app/autonomous/`.
- [ ] **Step 4:** Link it from HONEST-STATE + the docs index/README feature list if appropriate.
- [ ] **Step 5:** Commit + push.

### Task 12: File DE-325 / DE-326 / DE-327 in PRD §9
**Files:** Modify `docs/PRD.md` (§9 Deferred Enhancements)
- [ ] **Step 1:** `cd ~/Code/lq-ai && rg -n "DE-32[0-9]" docs/PRD.md` — confirm the next free number is 325 (latest existing is 324).
- [ ] **Step 2:** Add three DE entries matching the §9 format of the neighbours (DE-322/323/324): **DE-325** harden `build_receipt` call sites (DONE — reference commit; or note as shipped-fix); **DE-326** fresh-install worker alembic-migration race (DONE — reference commit); **DE-327** Helm/k8s worker-migration parity — community-suitable ("good first issue"), not yet done. (For 325/326 which are already implemented this session, file them as resolved-DEs with the commit SHAs, matching how prior resolved DEs are noted.)
- [ ] **Step 3:** Verify formatting matches the surrounding §9 entries.
- [ ] **Step 4:** Commit + push.

### Task 13: Align the active M4 handoff to HONEST-STATE
**Files:** Modify `docs/LQVern/HANDOFF-2026-05-29-m4-real-executor-mid-execution.md`
- [ ] **Step 1:** Read its current state (it already tracks through Task 19 + DEs).
- [ ] **Step 2:** Ensure its "current state" framing matches the rewritten HONEST-STATE; add a pointer to `docs/autonomous-layer.md` + `HONEST-STATE.md` as the canonical current-truth sources. Do NOT rewrite its history sections — only reconcile the "where we are now" framing.
- [ ] **Step 3:** Commit + push.

---

## PHASE 3 — Learn audit (existing 14 playgrounds + 4 pages)

### Task 14: Audit all existing Learn content → per-file fix list, then fix
**Files:** Modify (as needed) `web/static/learn/playgrounds/{anonymization-layer,autonomous-flow,citation-engine-cascade,data-residency,otel-eval,playbook-cascade,request-lifecycle,skill-composition,skill-format,system-architecture,tabular-review,test-landscape,tier-system,word-addin-flow}.html` + `web/src/routes/lq-ai/learn/{+page,how/+page,use/+page,build/+page}.svelte`

- [ ] **Step 1: Audit each of the 14 playgrounds against source**
For each playground, read it and check every factual claim (span names, statuses, "running"/"not running", counts, flow steps) against the truth-map + source. Record a per-file verdict: ACCURATE / FIX (with the exact stale claims). Known fix: `data-residency.html` claims anonymization "not running" — false. Re-check `system-architecture.html` against the real service list (incl. autonomous arq job + bridges).
- [ ] **Step 2: Audit the 4 Learn pages** (landing/how/use/build) the same way.
- [ ] **Step 3: Fix each FIX file in place** (one commit per file, or per small cluster of trivial claim-fixes). Preserve the existing visual/interaction design — correct the *content/claims* only; no design rework unless §7-of-spec rework is decided for `data-residency.html`/`system-architecture.html`.
- [ ] **Step 4: Verify each fixed file renders** — open in a browser / confirm no JS error (the playgrounds are self-contained; `web/static/learn/` is served). For touched SvelteKit pages: `cd ~/Code/lq-ai/web && npx svelte-check --threshold error` on the touched routes (or the project's check script).
- [ ] **Step 5: Commit (per file/cluster) + push both remotes.**

---

## PHASE 4 — New Learn visualizations for the gaps

> The exact set is finalized by Task 1's gap list. For EACH confirmed gap, create one new playground following the existing conventions. The candidate gaps below are confirmed/denied in Task 1; create only those that are genuinely missing AND represent a shipped capability.

### Task 15+ (one task per confirmed gap): New playground `web/static/learn/playgrounds/<name>.html`

Candidate gaps (confirm in Task 1): **intake-bridges flow** (Slack/Teams → chat), **autonomous brakes** (R4/R5/R6 — if `autonomous-flow.html` doesn't already cover them adequately), **autonomous primitives** (watches/schedules/memory/precedent lifecycle), **projects/org-profile**, **KB hybrid retrieval**. (Several may already be covered — e.g. `autonomous-flow.html` includes brake scenarios — so this list will shrink.)

For EACH confirmed gap:
- [ ] **Step 1: Study an existing playground as the template** — read 1-2 existing `.html` playgrounds (e.g. `autonomous-flow.html`) to match structure, the Learn design-system, offline-self-contained constraint, and no-new-color-palette rule.
- [ ] **Step 2: Gather the capability's true mechanics from source** (the relevant module) so the viz is accurate.
- [ ] **Step 3: Build the playground** — self-contained HTML/CSS/JS, honest (PLANNED badge only if a sub-part genuinely isn't shipped), interactive in the established style.
- [ ] **Step 4: Wire it into the Learn index** so it's reachable (mirror how the existing 14 are linked — check `web/src/routes/lq-ai/learn/` + any playground manifest/list). If `build/` is `.gitignore`d, use `git add -f` per the established pattern.
- [ ] **Step 5: Verify it renders + no JS error; every claim matches source.**
- [ ] **Step 6: Commit (one per new playground) + push both remotes.**

---

## PHASE 5 — Final consistency pass

### Task 20: Cross-artifact consistency + closeout
**Files:** any touched (small fixups only)
- [ ] **Step 1: Re-read HONEST-STATE + skim every edited doc** — confirm a given capability is described consistently everywhere; fix any divergence (HONEST-STATE wins).
- [ ] **Step 2: Grep for residual dishonesty across the touched set**
```bash
cd ~/Code/lq-ai && rg -n "not yet|coming soon|TODO|skeleton|walking skeleton|not running|placeholder" README.md docs/*.md web/static/learn/playgrounds/*.html
```
Confirm every remaining hit is genuinely accurate (truly-not-built things only).
- [ ] **Step 3: Confirm historical artifacts untouched** — `cd ~/Code/lq-ai && git diff --name-only main...HEAD | rg "SESSION-HANDOFF|M[1-4]-IMPLEMENTATION"` should return nothing except (allowed) the active M4 handoff.
- [ ] **Step 4: Final commit (if any fixups) + push both remotes.**
- [ ] **Step 5: Report** the full list of edited + created artifacts and the DEs filed, for the v0.4.0 tag readiness check.

---

## Self-Review notes (author)

- **Spec coverage:** HONEST-STATE spine → Task 1. Core docs → Tasks 4-9. Per-feature + autonomous-layer.md → Tasks 10-11. DEs → Task 12. Current handoff → Task 13. Learn audit → Task 14. New viz → Tasks 15+. Out-of-scope preservation verified → Task 20 Step 3. Comprehensive viz coverage → Phase 4 (gap-driven). All spec §2.1 items mapped.
- **Analysis-driven content:** doc/viz *prose* is intentionally produced during execution against the Task-1 truth-map rather than pre-written here — pre-writing it would mean asserting facts from memory, which the truth-discipline forbids. Each task instead specifies the exact claims to verify and the verification commands. This is the correct shape for honesty-reconciliation work.
- **Numbering:** task numbers are clustered by phase with gaps (4-9, 10-13, 14, 15+, 20) to leave room; executors should treat them as an ordered list, Task 1 first (it gates the rest).
