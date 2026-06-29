# Handoff — 2026-06-28 — Phase 2: WS-G complete; WS-D started (PR1 mid-build)

`main` (LegalQuants + tucuxi, both == **`b407de2`**). **Next migration = `0063`. Next DE = DE-368.**

---

## ⭐ SESSION-START NOTE — read first

**WS-G (transparent validity/treatment layer) is COMPLETE and merged.** **WS-D (governed agentic legal-matter sessions) has started:** **ADR 0020 is accepted + merged** (`docs/adr/0020-governed-agentic-legal-matter-sessions.md`, #238), and **WS-D PR1 (the governed agentic loop + matter intake) is mid-build on a LOCAL branch** via subagent-driven development. **Tasks 1–4 of 6 are done and review-clean; Tasks 5–6 + the Opus whole-branch review + push/PR remain.** Resume the SDD loop at Task 5.

### Immediate first action — resume WS-D PR1's SDD loop at Task 5
- **Branch:** `feat/wsd-pr1-agentic-loop` (**LOCAL, NOT pushed** — 7 commits on `main` `b407de2`, head `dcaddae`).
- **Plan:** `docs/superpowers/plans/2026-06-28-wsd-pr1-agentic-loop.md`. **Spec:** `docs/superpowers/specs/2026-06-28-wsd-pr1-agentic-loop-design.md`.
- **SDD ledger (authoritative resume map):** `.superpowers/sdd/progress.md` — Tasks 1–4 marked complete with commit SHAs; **5 and 6 are `pending`.** Trust the ledger + `git log` over recollection.
- **Re-enter SDD:** invoke `superpowers:subagent-driven-development`, read the ledger, generate the Task 5 brief (`<sdd>/scripts/task-brief docs/superpowers/plans/2026-06-28-wsd-pr1-agentic-loop.md 5`), dispatch the implementer (sonnet — Task 5 is the integration heart), review (sonnet), then Task 6 (sonnet), then the **Opus whole-branch review**, then push + PR.
- **Task 5 = the loop in `analysis_node`** (backward-compat gate + the `plan→act→observe→replan` while-loop + step cap + final synthesis). Its tests have `...` bodies delegated to the existing autonomous node/receipt fixtures — the implementer must reuse `api/tests/autonomous/conftest.py` fixtures (`session_with_skill_ref`, `sample_chunks`, `db_session`) and the existing `make_analysis_node` test pattern; tell them to build `seeded_matter_session` = a skill-ref session with `params["query"]` set, and `seeded_skill_session_no_query` = without. **Task 6 = surface the plan trace in the receipt** (thread `analysis_plan_trace` from state → `session.result`).
- **After Tasks 5–6 + Opus review:** run the **full gates at CI scope from the repo root** (`ruff check api scripts` + `ruff format --check api scripts` + `mypy app` whole-app + both full suites — the THRICE-burned lesson: format/lint scope is `api scripts` + `gateway` from root, never `app tests`), then **push origin + tucuxi → open the security-gated PR (NO self-merge; `api/app/autonomous/**` is the chokepoint) → after Kevin/security merges, mirror `origin/main → tucuxi`.**

### WS-D PR1 load-bearing invariants (the tests pin these — do not let them slip)
1. **Backward-compat:** the planner loop engages ONLY when `state["query"]` is non-empty. Query-less sessions (cron/watch/schedule) take the UNCHANGED single-`run_skill` path — byte-identical (same intents, audit rows, outputs; no `plan` intent emitted). Strictly additive.
2. **Synthesis contract:** however the loop ends (`planner_done`/`step_cap`/`planner_unparseable`/`planner_out_of_set`), a final `run_skill` synthesis ALWAYS produces the fenced-JSON `findings` that `drafting.parse_structured_output` expects, as `analysis_content`. A cap-halt → partial-but-honest, never fabricated-complete.
3. **Every loop step via `guarded_tool_call`** (R5→R6→R4); no bypass; **no new brake machinery** — bounded by `DEFAULT_MAX_ANALYSIS_STEPS=6` (`params["max_analysis_steps"]` override) + R4's $5 cap.
4. **Planner allowlist = OBSERVE intents only** (`retrieve_chunks`, `retrieve_caselaw`, `call_mcp_tool`); `run_skill` reserved for synthesis; emit/side-effect intents not planner-driven.
5. **Args model-generated, handler-validated** (closed-set boundary, ADR 0015). **P3:** observations + the plan trace hold counts/ids/case-names/short snippets/rationale — never full payloads.
6. **No migration** (ToolIntent is a StrEnum; audit `action` is event-keyed, not an intent CHECK — verified in Task 1).

## WS-D PR1 progress (SDD)
| Task | State | Commit |
|---|---|---|
| 1 — `ToolIntent.plan` + grant + cost + dispatch | ✅ review-clean | `33337c4` |
| 2 — planner prompt + decision parser (`planner.py`) | ✅ review-clean | `7602385` |
| 3 — observation summarizer (P3-clean) | ✅ review-clean | `0695fef` + test-fix `6a25eb9` |
| 4 — synthesis messages (preserve drafting contract) | ✅ review-clean | `dcaddae` |
| 5 — the loop in `analysis_node` (gate + while + step cap + synthesis) | ⏳ pending | — |
| 6 — receipt plan-trace (D5 transparency) | ⏳ pending | — |
Minors logged in the ledger for the final review (test-local imports, fence-strip path untested, truthy-non-sequence guard). All gates green through Task 4 (autonomous suite 481+ pass; whole-app mypy + ruff clean).

## Milestone arc (fiduciary-grade agentic legal work — Phase 2)
- **Phase 1 COMPLETE** (WS-A ledger, WS-B gate, WS-C UI).
- **WS-G COMPLETE** — ADR 0019 + PR1 graph signal (#233) + PR1-UI (#234) + PR2 treatment judge (#236) + PR3 hardening DE-363/364/364b (#237). The KeyCite-analog validity layer, derive-don't-assert.
- **WS-D STARTED** — ADR 0020 accepted (#238); **PR1 mid-build (this handoff).** ADR 0020 D6 phases it: **PR1 = governed loop + intake (no ledger/gate); PR2 = WS-A ledger + WS-B gate integration, REUSING the chat-path `assemble_ledger_entries` + `compute_and_record_gate` (ADR 0016 P6, not a fork).**
- **After WS-D:** **WS-E** (content-source registry + free-source expansion: GovInfo/EUR-Lex/SEC EDGAR; **where DE-344's R4 metered-tool cost wiring lands** — pinned to WS-E by its first-metered-source trigger). **WS-F** (MCP-server ingress) stays **Phase 3** (own ADR; largest new security surface).
- **End of Phase 2 / pre-launch:** **DE-365** — the launch-documentation pass: README + transparency visualizations + an **evidence-linked** honest comparison vs TR/Westlaw/CoCounsel's announced-but-unshipped (later-summer-2026) fiduciary-grade direction. Kevin's framing (captured in memory `project-fiduciary-grade-positioning-and-launch-docs`): **"turn it up to 11" — honest but unflinching, fundamental truths NOT digs: every comparison cell links to proof (ADR/code/test/live trace); "we show the work, they ask you to trust them"; their editorial verdicts diffuse responsibility (no one on the line) vs. LQ.AI's named practicing-attorney attestation.** The conservative-engineering posture (never overclaim) still binds every claim.
- Open PR2 follow-ups already filed: **DE-366** (treatment worker short-circuit when no gateway), **DE-367** (rollup materialization).

## Workflow reminders (load-bearing)
- **Security-gated** (`api/app/autonomous/**`, `gateway/**`, `api/app/citation/**`, `chats.py`, auth/authz/audit/crypto): Kevin/security merges; **Claude does NOT self-merge.** Docs-only + `web/`-only → self-merge after CI. Mirror `origin/main → tucuxi` after every merge; confirm `origin == tucuxi`.
- **Branch off `main`** (never commit on `main`); push feature branches to **origin + tucuxi**.
- **Tests:** host venv `api/.venv` + throwaway pgvector `lqai-test-pg` on `:55432`, `DATABASE_URL=postgresql+asyncpg://postgres:postgres@127.0.0.1:55432/lqai_test` (conftest auto-migrates). Mocked gateway → no `-m provider`. NEVER host `alembic upgrade` the dev DB (port 15432).
- **CI scope (thrice-burned):** `ruff format --check api scripts` + `ruff check api scripts` + gateway equivalents from the **repo root** (covers `api/alembic/`); `mypy app` whole-app (`--strict` gateway); both full suites. Full api suite ≈ 14 min; API CI check ≈ 18 min.
- **Opus for the final whole-branch review** — it has caught a real gate-passing defect on EVERY slice this milestone (WS-G PR2 orphaned-signal; WS-G PR3 refresh-path race + a `MissingGreenlet`). Worth the cost every slice.
- Commits: `git commit -s` + `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`.

## Pointers
- ADR: `docs/adr/0020-governed-agentic-legal-matter-sessions.md` (D1–D7; §Open-questions = PR1/PR2 inputs)
- Strategy: `docs/proposals/fiduciary-grade-agentic-legal-work.md` (WS-D/E §"Phase 2"; WS-F = Phase 3)
- Autonomous-layer map (the substrate WS-D builds on): `guarded_tool_call` chokepoint, closed `ToolIntent` set, `PHASE_GRANTS`, R4/R5/R6, the scripted LangGraph `intake→analysis→drafting→ethics_review→delivery`, `audit_log`+receipt. Today's analysis = ONE `run_skill` call; PR1 makes it a loop INSIDE the node (no graph change).
- Memory: `project-fiduciary-grade-milestone` (current state), `project-fiduciary-grade-positioning-and-launch-docs` (DE-365 launch framing), `MEMORY.md` index.
- Prior handoff: `docs/LQVern/HANDOFF-2026-06-26-wsg-phase2.md`.
