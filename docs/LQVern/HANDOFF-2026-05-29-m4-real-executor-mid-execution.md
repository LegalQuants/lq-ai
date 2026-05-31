# Handoff — M4 real-executor-work execution (Tasks 1–18 done) → resume at Task 19 (fresh-install acceptance)

> ## ⮕ Status update (as of the M4 close — 2026-05-31)
>
> **This handoff is historical.** As of the M4 close, the M4 real-executor-work series is **CODE-COMPLETE** — all **19** executor tasks landed, plus the beyond-plan brake-receipt fix and the deferred-enhancement writeups (DE-325 / DE-326). **Fresh-install acceptance PASSED live** (a real R4 per-trigger cost-cap halt fired, `terminal_reason=cost_cap_reached`). The remaining work on branch `feat/lqvern-m4-autonomous` is the **docs + Learn honest-alignment sweep (M4-D2)**, in progress; then Kevin's attorney legal-substance walk-through; then the branch merges to `main` (code + docs + Learn together) and **v0.4.0 is tagged**. *(v0.4.0 is **not yet tagged** as of this note.)*
>
> **Canonical current-state sources — read these, not this handoff, for "what's true now":**
> - [`docs/HONEST-STATE.md`](../HONEST-STATE.md) — the capability truth-map (M4 is §5).
> - [`docs/autonomous-layer.md`](../autonomous-layer.md) — the M4 Autonomous Layer feature doc.
>
> Everything below this addendum (the title line, the original "where we are" header, and the Task 1–19 / DE / resume-instruction body) is **preserved unchanged as the point-in-time record** of the mid-execution session. Treat it as history, not as the current plan of record.
>
> ---

> **For:** the next Claude Code session continuing the M4 real-executor-work series on branch **`feat/lqvern-m4-autonomous`** in **`~/Code/lq-ai`** (canonical repo — NEVER `~/Desktop/lq-ai`; Bash cwd resets to `~/Desktop` between calls, so prefix every command with `cd ~/Code/lq-ai &&`).
>
> **SUPERSEDED — see the "Status update (M4 close)" addendum directly below for current truth.** The historical "where we are" line that follows is preserved as the point-in-time record of the mid-execution session and is no longer the current state.
>
> **Where we were (point-in-time, 2026-05-30):** Tasks **1–18 of 19 SHIPPED** + one **beyond-plan brake-receipt fix** (see UPDATE block below). Branch HEAD `f6bec54`, pushed origin + tucuxi, tree clean. Full gate green: autonomous suite **361 passed**, `ruff check api scripts` + `ruff format --check api scripts` + `mypy app` (141 files) all clean. Resume point at the time was Task 19 (fresh-install re-acceptance). *(Task 19 has since PASSED — see the UPDATE block and the addendum below.)*
>
> **The contract:** the design at [`docs/LQVern/m4-real-executor-work-design.md`](m4-real-executor-work-design.md) (commit `d1293b4`) and the 19-task plan at [`docs/LQVern/m4-real-executor-work-implementation-plan.md`](m4-real-executor-work-implementation-plan.md) (commit `7da5c47`). The plan is the source — every task's full text is in that file with TDD steps + code snippets + commit messages.

---

## UPDATE 2026-05-30 — Tasks 12–18 SHIPPED + brake-receipt fix

Executed subagent-driven (implementer → spec review → code-quality review → fix → re-review → push both remotes). Commits since the original `41558c5` handoff:

| # | Task | Commit | Note |
|---|---|---|---|
| 12 | `drafting_node` — parse structured output + per-item guarded calls | `76d4bba` | Quality review caught a real regression (delivery read `state["findings"]` but drafting wrote only `findings_count`); fixed so drafting populates BOTH keys on every emit path. |
| 14 | `ethics_review_node` — privilege/scope concerns finding | `321aa6f` | Light v1; combined spec+quality review (small single-node). |
| 15 | `delivery_node` — write `completed` audit row (terminal_reason fix, §7.1) | `0c39e7d` | RED→GREEN confirmed; flush-visibility verified. |
| 13 | gateway_error + unstructured-output complete honestly (E2E) | `ff1c43a` | Done AFTER 14/15 per the recommended reorder. Strengthened test #2 (assert gateway awaited + exact emit_finding count). |
| 16 | R4 per-trigger live test | `09d7239` | **Surfaced a real gap** (see below). R4-proper assertions pass. |
| — | **brake-receipt fix (beyond plan, Kevin-approved)** | `5e9f2bd` | The executor's `except AutonomousBrake` handler never called `build_receipt`, so R4/R5 **halted** sessions had `result=None` / no `terminal_reason` — contradicting design §10 and blocking Task 19's R4/R5 acceptance. Plan misjudged this (Task 15 fixed only the *completed* path). Fix: `if status == "halted": session.result = await build_receipt(session, db)` before commit. Scoped to halted only; `ToolNotGranted`/failed intentionally excluded. Un-xfailed the Task 16 receipt test → passes. |
| 17 | refresh `test_executor_skeleton.py` + strengthen chokepoint invariant | `f6bec54` | The file had no obsolete assertions (plan's premise was stale); refreshed skeleton-era wording + added `test_no_tool_call_bypasses_chokepoint`. |
| 18 | full pre-acceptance gate | (no code) | autonomous suite 361 passed; ruff + mypy clean. CI runs `mypy app` (NOT tests/) — 4 pre-existing `unused-ignore` warnings in test files are out of CI scope, non-blocking. |

**DE to file in the M4-D2 doc batch (next free number DE-325):** harden the `build_receipt` call sites against a receipt-build failure converting a clean terminal session into a worker crash / stuck row. Both `delivery_node` (completed) and the brake handler (halted) call `build_receipt` bare; a raise in the brake handler isn't caught by the sibling `except Exception` and would crash the worker mid-job. `build_receipt` is defensive today (null-guards, Decimal try/except), so low likelihood — file as DE, don't block.

**Trailer note:** the series uses `Co-Authored-By: Claude Opus 4.7 (1M context)` on every commit for branch consistency (actual session model is Opus 4.8). Keep 4.7.

---

## UPDATE 2026-05-30 (later) — Task 19 fresh-install acceptance PASSED ✅

Destructive `docker compose down -v && up --build` (Kevin green-lit). Migrations ran cleanly **0001 → 0045** via the api entrypoint; all containers healthy; admin bootstrapped + password rotated to `AcceptTest12345!`; opted in; created KB `9003dbc6…` + watch (NDA-Mutual `726cb3dd…`, cap $1.00); upload-then-attach NDAs (correct flow: POST /files → poll `ingestion_status=ready` → POST /knowledge-bases/{kb}/files `{"file_id":…}`).

**Verified live (DB + receipt ground truth):**

| session | trigger | status | cost | terminal_reason |
|---|---|---|---|---|
| `09543815` | watch | completed | $0.0050 | completed |
| `1e49dc62` | watch | completed | $0.0050 | completed |
| `3ae382df` | watch (cap 1.00) | completed | $0.0050 | completed |
| `4554cdd9` | watch (cap 0.001) | **halted** | $0.0000 | **cost_cap_reached** |

- **Real executor work end-to-end:** phase walk intake→analysis→drafting→ethics_review→delivery; a real `run_playbook` gateway call (cost $0.005, outcome success); **9 `emit_finding`** + **`propose_memory` ×N** + **`propose_precedent` ×N** + `notify`, each independently brake-checked through the chokepoint; receipt `terminal_reason='completed'`, cost > 0.
- **R4 live (Step 7):** second watch cap $0.001 → session `4554cdd9` halted, `cost_cap_reached=true`, **receipt `terminal_reason='cost_cap_reached'`** — this is the LIVE PROOF of the beyond-plan brake-receipt fix `5e9f2bd` (the field was `None` before it).
- **Durable analytical work product** (the attorney-reviewable output): memory proposals (survival-of-confidentiality flags, permitted-disclosure expansion, a `client-preference` learning for "Cypress Holdings… two-year terms, Delaware law", and a `playbook_selection` proposal correctly flagging that an MSA should NOT get the NDA-Mutual playbook end-to-end — honest self-correction, not hallucinated NDA findings); precedent entries (survival_coextensive_with_term, permissive_irreparable_harm, narrow-permitted-disclosures, msa_confidentiality_section). Notifications written (in-app).

**Step 8 (R5 live halt):** SKIPPED — timing-sensitive (happy path runs ~40s); already test-covered (`test_brakes.py`). Optional per the plan.

**Findings surfaced (file in the M4-D2 doc batch):**
- **DE-325** (already noted): harden `build_receipt` call sites against a build failure crashing the worker.
- **DE-326 (new):** fresh-install worker-migration race. The **arq-worker** (and likely ingest-worker) entrypoint runs `alembic upgrade head` on boot, but the arq image doesn't ship `skills/`, so migration **0032** (seed builtin NDA playbooks, which reads `/skills/playbooks/nda/playbook.yaml`) raises `RuntimeError` in the worker. It self-recovered (the **api** owns migrations and reached 0045; the worker retried until head), but it logs scary tracebacks on every fresh boot. Fix options: only the api runs migrations (set `LQ_AI_SKIP_MIGRATIONS=1` on the workers), or mount `skills/` into the worker images. Non-blocking but a fresh-install polish item.
- **Process note (not a code bug):** a runaway background `docker compose logs` process corrupted/interleaved terminal output mid-acceptance, producing phantom "cost=0 / no run_playbook" readings that triggered a false-alarm investigation. Ground-truth DB queries (after killing the log stream) confirmed every real session worked. Lesson: for live acceptance, query the DB/receipt directly; don't stream `docker compose logs` unbounded in the background.

**REMAINING for v0.4.0 tag:**
1. **Attorney legal-substance walk-through — Kevin owns** (per [[feedback_no_maintainer_legal_review]]). Inputs ready: the memory/precedent content above + receipts on KB `9003dbc6…`, admin `admin@lq.ai` / `AcceptTest12345!`, dashboard `localhost:3000`.
2. **M4-D2 docs:** boundary-registers R4/R5/R6 → SHIPPED (with the live citations above), PRD §3.10 SHIPPED, new `docs/autonomous-layer.md`, HONEST-STATE sweep M3+M4, grep M4 markers, file DE-325 + DE-326 in PRD §9.
3. Then tag **v0.4.0**.

---

## Why this exists (the pivot, in one paragraph)

Per the 2026-05-27 destructive fresh-install acceptance, the M4 autonomous **substrate + R4/R5/R6 brakes + the four primitives' lifecycle + dashboard + Learn viz** are all shipped, but the **executor itself is an intended walking skeleton** (analysis_node docstring literally says *"In the current skeleton no inference tools are called"*; drafting emitted a hardcoded `{phase:drafting,status:oriented}` finding; no node ever called `run_skill`/`run_playbook`/`propose_memory`/`propose_precedent`). Kevin decided: **wire real in-loop agentic work before tagging v0.4.0**, AND fix both minor bugs found (terminal_reason=None on completed sessions; watch-trigger live verify). The good news: the chokepoint's `_handle_gateway_inference`/`_handle_retrieve_chunks`/`propose_memory`/`propose_precedent`/`notify`/`emit_finding` handlers are **fully implemented** (real anonymized gateway calls, real DB writes). The 19 tasks are bounded **node-orchestration work** + 2 small enabling changes + 2 bug fixes.

---

## Tasks 1–11 — DONE (commits + summary)

Branch starting point: `7da5c47` (design + plan committed). Each task: TDD red→green → ruff format + check + mypy → DCO commit → push both remotes after spec + code-quality review pass.

| # | Task | Commit(s) | What landed |
|---|---|---|---|
| 1 | Migration 0045 — per-trigger `max_cost_usd` on watches+schedules | `3969a16` | `NUMERIC(10,4)` `NULL` columns on `autonomous_watches` + `autonomous_schedules`, mirroring `autonomous_sessions.max_cost_usd`. Migration round-trips via pytest's throwaway DB. |
| 2 | Config — `autonomous_default_max_cost_usd` | `fa78765` | New `Settings.autonomous_default_max_cost_usd: Decimal = Decimal("5.00")` (env override `LQ_AI_AUTONOMOUS_DEFAULT_MAX_COST_USD`). 2 tests. |
| 3 | ORM + Pydantic schemas — `max_cost_usd` | `39de9a3` | Mapped column on both ORM models; field on all 6 schemas (Create/Update/Read × Watch+Schedule); 4 tests. |
| 4 | Watch + Schedule endpoints persist + surface `max_cost_usd` | `6982b49` | POST + PATCH on `/watches` + `/schedules` accept Decimal; `exclude_unset=True` idiom preserves clear-to-NULL semantic. 8 tests (incl. clear-to-NULL coverage). |
| 5 | Spawn paths always set `session.max_cost_usd` (per-trigger or default) | `bf7bc88` | `fire_watches_for_kb` + `_run_schedule_sweep` thread per-trigger value or fall back to config default (NEVER None). Schedule sweep also threads `last_run_at` into `session.params["since"]` (capture-before-advance). 6 tests. |
| 6 | `_handle_retrieve_chunks` gains optional `file_id` + `since` scopes | `2a44b8a` + fix `1cbfb15` | Three modes: query (existing), file_id (watch intake), since+kb_id (schedule intake). Fix `1cbfb15` enforces the documented naive-datetime rejection. All modes share `_format_chunks_result`; soft-deleted files excluded. 6 tests. |
| 7 | `prompts.py` — assemble analysis messages from skill/playbook + chunks | `72c0122` + fix `d2dc444` | `assemble_analysis_messages(session, chunks, db, registry=None)` resolves `skill_ref` via `SkillRegistry.get_skill().content_md` or `playbook_id` via `select(Playbook).options(selectinload(positions))`. `STRUCTURED_OUTPUT_INSTRUCTION` constant. Fix `d2dc444`: filter soft-deleted playbooks; render `fallback_tiers.language`; pin contract for Task 8. 5 tests. |
| 8 | `structured_output.py` — tolerant JSON parser | `ac1db1e` + fix `4425c1d` | `StructuredResult` dataclass + `parse_structured_output()` (3-tier: fenced JSON → whole-content JSON → unstructured). NEVER raises. Fix `4425c1d`: `_as_list` helper coerces non-list values for array keys to `[]` (closed the never-raise contract gap for `{"findings": 42}` and silent-corruption for string/dict). 13 tests. |
| 9 + 10 | `intake_node` — watch (file_id) + schedule (since) + first-tick + no-target wiring | `6d08f3b` | 4-way dispatch on `session.params`: file_id → mode 2; kb_id+since → mode 3; kb_id only → `first_tick_no_baseline=True`; else empty. `AutonomousSessionState` TypedDict updated. 4 tests. (Orchestrator combined adjacent plan tasks 9+10 since both modify `make_intake_node`.) |
| 11 | `analysis_node` — guarded `run_skill`/`run_playbook` call | `276da7a` | Skips inference for first-tick + no-target sessions. Otherwise calls `assemble_analysis_messages` (Task 7), picks intent (run_playbook precedence over run_skill), picks model (`params["model"]` → `settings.autonomous_default_model`), `guarded_tool_call` with `anonymize=True`. Stores `result.data["content"]` + `result.outcome` in state. Added `autonomous_default_model: str = "claude-opus-4-7"` to config. 3 tests. |

**Branch state at handoff:** HEAD `276da7a`, pushed to origin + tucuxi, working tree clean. Wider autonomous suite **350 passed** + all gates clean (ruff format + ruff check + mypy).

---

## Tasks 12–19 — REMAINING (the plan's text per task)

The implementation plan at `docs/LQVern/m4-real-executor-work-implementation-plan.md` has the FULL text for each — read it BEFORE dispatching. One-line summaries for orientation only:

### Task 12 — `drafting_node` (the largest remaining)
Parse `state["analysis_content"]` via Task 8's `parse_structured_output`. Dispatch each item as its own guarded call:
- For each `parsed.findings[i]` → `guarded_tool_call(emit_finding, {"finding": f}, ...)`.
- For each `parsed.suggested_memories[i]` → `guarded_tool_call(propose_memory, {category, content, rationale}, ...)`.
- For each `parsed.suggested_precedents[i]` → `guarded_tool_call(propose_precedent, {pattern_kind, summary}, ...)`.

**Honest gateway_error path:** if `state["analysis_outcome"] == "gateway_error"`, emit ONE explanatory finding and return — session continues to ethics_review honestly, doesn't pretend findings exist.

**Tolerant fallback:** if `parsed.is_structured is False`, emit ONE `emit_finding` with `{"title": "Unstructured autonomous output", "summary": parsed.raw_content[:8000], "severity": "info"}`.

**First-tick path:** if `state["first_tick_no_baseline"]`, emit ONE "First scheduled tick — baseline set" finding and return.

**Carry forward `parsed.privilege_concerns` + `parsed.scope_concerns` in state** for ethics_review (Task 14) to consume.

**Critical pre-edit check:** re-read `api/app/autonomous/guard.py`'s `_handle_emit_finding`, `_handle_propose_memory`, `_handle_propose_precedent` to pin the EXACT param-dict shapes each handler expects. The plan's snippets are illustrative; the shipped handler signatures win.

**Tests:** at least `test_drafting_dispatches_per_item_guarded_calls` from the plan, plus tolerant-fallback and honest-gateway_error coverage.

### Task 13 — Tolerant-parse + gateway-error end-to-end (integration tests)
Two integration tests in NEW file `api/tests/autonomous/test_executor_gateway_error.py`:
- `test_gateway_error_completes_honestly` — mock gateway raises mid-analysis; session completes (not halted); receipt shows one error-explanation finding; `terminal_reason="completed"`.
- `test_tolerant_parse_unstructured_completes_with_raw_finding` — mock gateway returns text that doesn't fit the JSON schema; session completes with one raw-content finding.

**Depends on Task 15's terminal_reason fix.** If you run Task 13 before Task 15, the `terminal_reason=='completed'` assertion fails. **Recommended:** swap order — do Task 15 first, then Task 13. The plan notes this in Step 2 of Task 13.

### Task 14 — `ethics_review_node`
Emit ONE `emit_finding` summarizing `state["privilege_concerns"]` + `state["scope_concerns"]` (from Task 12). Empty lists → emit "no concerns flagged" finding.

### Task 15 — `delivery_node` (with **terminal_reason fix**)
- `guarded_tool_call(notify, {title, body, payload}, ...)` — already wired in skeleton; verify it still works.
- **NEW (bug fix):** write `await autonomous_audit(db, session, "completed", cost_total_usd=str(...), findings_count=...)` BEFORE `session.result = await build_receipt(session, db)`. This is the bug fix for the `terminal_reason=None` finding from the 2026-05-27 acceptance. `"completed"` is already in `_ACTIONS` (audit.py).
- Set `session.status = "completed"`, `session.completed_at`, `session.result = receipt`, `await db.commit()`.

Test: `test_delivery_writes_completed_audit_row_so_receipt_terminal_reason_populates`.

### Task 16 — R4 per-trigger live test
End-to-end test: watch with `max_cost_usd=0.001` + mock gateway returning enough projected cost → R4 latches `cost_cap_reached`, session halts, receipt's `terminal_reason="cost_cap_reached"`. Verifies the production-shape spawn path's R4 wiring (existing brake tests covered the chokepoint in isolation; this verifies the trigger→session→R4 chain).

### Task 17 — Update existing `test_executor_skeleton.py`
The existing skeleton tests may assert behaviors that are now obsolete (e.g., "no tool calls made", "drafting emits exactly one hardcoded finding"). Drop those; preserve/strengthen the "no tool path bypasses the chokepoint" invariant.

### Task 18 — Full pytest + ruff + mypy gate before re-acceptance
Run the full `tests/autonomous/` suite + ruff format + ruff check + mypy across all touched files. Push both remotes. This is the pre-acceptance checkpoint.

### Task 19 — Fresh-install re-acceptance (the v0.4.0 tag gate)
**Destructive: `docker compose down -v && up --build` — wipes the dev DB volume.** Kevin must explicitly green-light the teardown before running. Then:
- Clean build + migrations 0001 → 0045.
- Bootstrap admin + change password + opt in.
- Create KB + watch with `max_cost_usd=1.00` bound to a seed playbook (NDA-mutual).
- Upload an NDA via `POST /api/v1/files` → get `file_id` → POST `/knowledge-bases/{kb}/files` with `{"file_id":"..."}` (the CORRECT upload-then-attach flow — the 2026-05-27 acceptance hit a 422 because it sent multipart to the attach endpoint).
- Verify the spawned session runs real work end-to-end: phase walk → real `run_playbook` call → structured-output → `emit_finding`/`propose_memory`/`propose_precedent` per-item dispatch → notify → receipt has `cost > 0`, `terminal_reason="completed"`, real content in the receipt's tool_calls.
- R4 live demo: second watch with `max_cost_usd=0.001` → drop another doc → session halts with `terminal_reason="cost_cap_reached"`.
- R5 live demo: hit `POST /halt` between phases on a long-running session.
- Attorney legal-substance walk-through against a real document — **Kevin owns this per `feedback_no_maintainer_legal_review`**.

After Task 19 passes + Kevin's attorney review, M4-D2 doc finalization can proceed (boundary-registers R4/R5/R6 → SHIPPED with citations + PRD §3.10 SHIPPED + new `docs/autonomous-layer.md` + HONEST-STATE sweep M3+M4 + grep M4 markers), then tag v0.4.0.

---

## The workflow Kevin chose (don't re-litigate)

**Subagent-driven per task** (`superpowers:subagent-driven-development`):
1. Dispatch implementer subagent with **full pasted task text + scene-setting context** (do NOT make subagent read the plan file — paste the task in).
2. Implementer reports DONE/DONE_WITH_CONCERNS/BLOCKED/NEEDS_CONTEXT.
3. Dispatch **spec-compliance** reviewer (verify against the spec independently — *don't trust the report*).
4. If spec issues → implementer fixes → spec re-review.
5. Once spec ✅, dispatch **code-quality** reviewer (broader quality lens).
6. If quality issues → implementer fixes → quality re-review.
7. Push both remotes (`git push origin feat/lqvern-m4-autonomous && git push tucuxi feat/lqvern-m4-autonomous`).

**Combined spec+quality review** is acceptable for small pure-Python tasks (no DB, single file, clear contract — used on Task 8). Use sparingly; prefer two separate reviews for any task that touches the DB or multiple files.

**Combining adjacent plan tasks** is acceptable when they modify the same function (used on Tasks 9+10 since both modify `make_intake_node`). Don't combine across files; keep PR-able units honest.

**Don't fix manually** — dispatch a fix subagent with specific instructions. Exception: a one-line cosmetic fix where the cost of dispatching exceeds the value (used judgment a couple of times; not a habit).

**Token budget:** each task uses ~3 subagent rounds @ 30-80K tokens each. Plan for ~3 tasks per fresh session if context is tight.

---

## Hard rules (memorize)

- **Canonical repo `~/Code/lq-ai`** — NEVER `~/Desktop/lq-ai`. Bash cwd RESETS to `~/Desktop` between calls — **prefix every command with `cd ~/Code/lq-ai &&`**.
- **NEVER run host-side `alembic upgrade head` against `127.0.0.1:15432/lq_ai`** — that's the live dev DB; crash-loops the running stack. See [[feedback_no_host_alembic_on_dev_db]]. Verify migrations via pytest only (conftest builds its own throwaway DB on the same server, isolated).
- Local test DB invocation pattern:
  ```bash
  cd ~/Code/lq-ai/api && \
    PW=$(grep -m1 '^POSTGRES_PASSWORD=' ../.env | cut -d= -f2-) && \
    DATABASE_URL="postgresql+asyncpg://lq_ai:${PW}@127.0.0.1:15432/lq_ai" \
    ./.venv/bin/pytest tests/autonomous/<file>.py -v
  ```
- **DCO required:** every commit `git commit -s` + the trailer `Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>`.
- **Push BOTH remotes** after each task: `git push origin feat/lqvern-m4-autonomous && git push tucuxi feat/lqvern-m4-autonomous`. Never delete branches.
- **Gates per task:** `ruff format` AND `ruff check` (separately — CI runs them as separate gates) + `mypy` (standard mode for `api/`).
- **Honesty / no-drift:** every span attribute, audit action, outcome label, and receipt field used MUST match what shipped code in `api/app/autonomous/{guard,audit,receipt,enums}.py` already emits. Re-grep if in doubt.

---

## Stack + admin state (2026-05-29 snapshot)

- All `lq-ai-*` containers rebuilt from this branch + healthy after the 2026-05-27 acceptance. Dev DB at 0044 (Task 1's 0045 has NOT been deployed to the dev stack yet — it landed via pytest's throwaway DB only). To deploy 0045 to the dev stack: rebuild the api+arq-worker+ingest-worker trio together (per [[feedback_migration_rebuild_all_workers]]).
- Admin: `admin@lq.ai` / **`AcceptTest12345!`** (was bootstrapped during the 2026-05-27 fresh-install; Kevin chose to keep this password for now).
- Test acceptance watch (kb `187447f3-f1f2-4786-b69d-f000688337df`) + a disabled test schedule (`5e41b64c-...`) live in the dev DB; harmless. Task 19 will tear this down.
- Provider keys: `ANTHROPIC_API_KEY` + `OPENAI_API_KEY` + Ollama all set in `.env` — real inference works on a fresh build.

---

## Where to start (fresh-session paste-ready)

```
Continue M4 real-executor-work execution on LQ.AI in ~/Code/lq-ai (canonical repo —
never ~/Desktop/lq-ai; Bash cwd resets to ~/Desktop between calls, so prefix every
command with `cd ~/Code/lq-ai &&`), on branch feat/lqvern-m4-autonomous.

Read docs/LQVern/HANDOFF-2026-05-29-m4-real-executor-mid-execution.md first — full
state. Tasks 1-11 of 19 SHIPPED (branch HEAD ~276da7a, pushed origin+tucuxi, tree
clean, 350 autonomous tests + all gates green).

RESUME AT Task 12 (drafting_node — parse Task 8's structured output + per-item
dispatch + tolerant fallback + honest gateway_error path). The full task text +
TDD steps + code snippets + commit message are in
docs/LQVern/m4-real-executor-work-implementation-plan.md (commit 7da5c47). Don't
make the implementer subagent read the plan — paste full task text into its prompt.

RECOMMENDED order tweak: do Task 15 (delivery_node + terminal_reason fix) BEFORE
Task 13 (gateway-error E2E test), since 13's assertions depend on 15's fix. The
plan's Task 13 Step 2 notes this.

Workflow: subagent-driven per task (fresh implementer with full pasted task text →
spec-compliance review → code-quality review → fix → re-review). Combined
spec+quality is fine for small pure-Python tasks (e.g., 8). Combining adjacent
plan tasks that share a file is fine when they're a tight unit (used on 9+10).

Gates per task: ruff format AND ruff check separately + mypy. DCO `git commit -s`
+ Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com> trailer.
Push BOTH remotes after each task (origin + tucuxi). Never delete branches.

⚠️ Hard rule: NEVER run host-side `alembic upgrade head` against 127.0.0.1:15432/lq_ai
(it's the live dev DB; crash-loops the stack — see feedback_no_host_alembic_on_dev_db).
Verify migrations via pytest only (conftest throwaway DB). Local tests: read
POSTGRES_PASSWORD from repo-root .env, then `cd api && DATABASE_URL="postgresql+
asyncpg://lq_ai:<pw>@127.0.0.1:15432/lq_ai" ./.venv/bin/pytest …`.

Don't re-litigate the locked design decisions (in the design doc + handoff).

Stack currently up + healthy; admin = admin@lq.ai / AcceptTest12345!.
```

---

*Drafted 2026-05-29 mid-execution as Tasks 1-11 completed. The design + plan are the contract; this handoff is just a navigation aid.*
