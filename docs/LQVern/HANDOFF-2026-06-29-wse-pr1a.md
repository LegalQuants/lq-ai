# Handoff — 2026-06-29 — WS-D complete; WS-E started (PR1a ready to build)

`main` (LegalQuants + tucuxi, both == **`83fe323`**). **Next migration = `0064`** (reserved for WS-E PR1b). **Next DE = DE-369.**

---

## ⭐ SESSION-START NOTE — read first

**Phase 1 + WS-G + WS-D are all COMPLETE and merged.** **WS-E (content-source registry + free-source expansion) has started:** **ADR 0021 is accepted + merged** (#241, `docs/adr/0021-content-source-registry-and-free-source-expansion.md`), and **WS-E PR1a (registry + GovInfo + DE-344 cost) has a committed spec + plan on a LOCAL branch, ready to build via subagent-driven development.** No code written yet — resume by starting the SDD loop at Task 1.

### Docs landed first (this handoff's flow)
The WS-E PR1a **docs** (ADR 0021 D3 refinement + spec + plan + this handoff) were pushed on branch `feat/wse-pr1-registry-govinfo` and merged to `main` as their own docs PR **before** the code build (Kevin's call 2026-06-29: land docs, let CI clear, merge, then start a fresh build session). So on resume the spec/plan/handoff are **already on `main`**.

### Immediate first action — build WS-E PR1a CODE on a FRESH branch off updated main
- **Create a fresh branch off `main`** (e.g. `feat/wse-pr1a-code`) — do NOT reuse the merged docs branch. The spec/plan/ADR are on `main`.
- **Plan:** `docs/superpowers/plans/2026-06-29-wse-pr1a-registry-govinfo.md`. **Spec:** `docs/superpowers/specs/2026-06-29-wse-pr1-registry-govinfo-design.md`. **ADR:** `docs/adr/0021-...md` (read D1–D7 + the **2026-06-29 D3 refinement note** = mirror-the-caselaw-path).
- **SDD ledger (authoritative resume map):** `.superpowers/sdd/progress.md` — 7 tasks, all `pending`. **Refresh its `Branch:`/`Base:` lines to the new code branch + its base commit** on resume. Trust the ledger + `git log` over recollection.
- **Re-enter SDD:** invoke `superpowers:subagent-driven-development`, read the ledger, generate the Task 1 brief (`<sdd>/scripts/task-brief docs/superpowers/plans/2026-06-29-wse-pr1a-registry-govinfo.md 1`), dispatch implementer (sonnet) → review (sonnet) → next task. Tasks 1–2 are **gateway** (`gateway/.venv`, `mypy --strict`); Tasks 3–7 are **api**. After Task 7: Opus whole-branch review → full gates (CI scope, **SOLO** suite) → push origin+tucuxi → security-gated PR (**NO self-merge**) → mirror after Kevin/security merges.

### WS-E PR1a scope + the 7 tasks (C1–C5; PROVENANCE-level, NO migration)
PR1a makes the autonomous loop able to **reach GovInfo** (US federal statutes/regs) through the governed gateway egress via a new `retrieve_authority` intent, registry-validated, with a real DE-344 cost model — fetched authority captured as ledger **provenance** (`MessageToolSource`). **Char-fidelity verification + fiduciary-ledger-backing of fetched quotes is PR1b** (C6, mech-B, migration 0064 — a separate plan to write next).
1. Gateway: `govinfo` type + `GovInfoToolAdapter` skeleton/transport (`X-Api-Key`, SSRF, `skip_anonymization=True`) + register.
2. Gateway: `search_authority` + `get_authority` ops (USCODE + CFR) + `gateway.yaml.example`. (Task 2 Step 1 = confirm live GovInfo endpoint shapes via api.govinfo.gov/docs.)
3. Backend: `research/registry.py` (`SOURCE_REGISTRY`, `resolve_available_sources` = enabled∩adapter-shipped) + `research/adapters.py` (`GovInfoAdapter.from_response` → `FetchedAuthority`).
4. Backend: `GET /api/v1/research/sources` (no secrets) + openapi/endpoints collision-guard bumps.
5. Autonomous: `ToolIntent.retrieve_authority` + grant(analysis) + `_EXTERNAL_TOOL_INTENTS` + `_resolve_external_call` + `_handle_retrieve_authority` (registry-validate → `call_tool` → adapter → `MessageToolSource` provenance).
6. Autonomous: planner `PLANNER_ALLOWLIST` += ; `validate_action_args` branch; `collect_evidence` authority kind; minimal source-awareness in `build_planner_messages`.
7. Governance: DE-344 — cache `cost_per_call`/`cost_per_unit` (provider `model_extra`) + `estimate_tool_cost` returns the rate (free→$0) + realized on `tool_call_log.cost_usd`.

### Load-bearing invariants (the tests pin these — see the ledger for the full list)
- **One egress (ADR 0014):** backend reaches GovInfo ONLY via `gateway call_tool`; secrets/SSRF/rate-limit gateway-side.
- **Closed-set + validated (ADR 0015):** `retrieve_authority` args handler-validated vs the live registry; a bad/disabled source/op/args → clean `ValueError` → **non-fatal failed observation** (the WS-D PR1-C1 lesson — never poison the session).
- **Honest unavailability (D5):** not-configured source surfaced unavailable-with-reason; GovInfo BYO-key (`GOVINFO_API_KEY`).
- **DE-344:** configured per-provider rate; free→$0→R4 no-op; realized on `tool_call_log`. `cost_per_call`/`cost_per_unit` ride `ToolProviderConfig` `extra="allow"` — **no config-schema field/migration**.
- **P3:** `/sources` + planner context = name/type/jurisdiction/coverage/ids only, never auth/cost secrets.

### ⚠️ DE-368 (bit us TWICE in WS-D PR2's final gate) — the SOLO-suite rule
The api test suite is **serial-only** against the shared `lqai_test` DB. **NEVER run concurrent pytest** during a final-gate full-suite run — including a review subagent's focused tests. Concurrent DB access produces ~24 spurious failures in `test_research_service.py` / `test_mcp_*` / `test_integrations_*` (gateway-client singleton + provider-cache + respx global state). CI runs serially so it's unaffected; the solo local run is clean. When running the final full suite, dispatch nothing else that touches the DB.

## Milestone arc (fiduciary-grade agentic legal work — Phase 2)
- **Phase 1 (WS-A/B/C) COMPLETE. WS-G COMPLETE. WS-D COMPLETE** (PR1 #239 governed loop; PR2 #240 fiduciary ledger+gate for matter sessions).
- **WS-E STARTED** — ADR 0021 accepted (#241). **PR1a ready to build (this handoff).** Then **PR1b** (C6 verify+ledger, mech-B, mig 0064 — write its plan after PR1a lands). Then **PR2** (SEC EDGAR + EUR-Lex, flagged).
- **Sequencing locked w/ Kevin (2026-06-29):** WS-E → **PR2-UI** (Svelte session-ledger view, self-merge) → **DE-365** end-of-Phase-2 launch-docs pass (needs the UI visible so every comparison cell links to a live trace). **WS-F (MCP-server ingress) = Phase 3** (own ADR).
- **Open follow-ups (not blocking):** DE-369 (user_export includes session-owned chats — product call); shared-gate "zero verifiable assertions → fiduciary_grade" semantics (affects chat path too — possible shared-gate DE).

## Workflow reminders (load-bearing)
- **Security-gated** (`gateway/**`, `api/app/autonomous/**`, `api/app/citation/**`, `chats.py`, governance/auth/audit/crypto, migrations): Kevin/security merges; **NO self-merge.** Mirror `origin/main → tucuxi` after every merge; confirm `origin == tucuxi`. Docs-only + `web/`-only → self-merge after CI.
- **Branch off `main`** (never commit on `main`); push feature branches to **origin + tucuxi**.
- **Opus whole-branch review every slice** — it has caught a real gate-passing defect on EVERY slice this milestone (WS-D PR1's C1 model-arg→DBAPIError poison was the biggest).
- **CI scope (repo root):** `ruff check/format --check api scripts` + gateway; `mypy app` whole-app + gateway `--strict`; both full suites SOLO.
- Commits: `git commit -s` + `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`.

## Pointers
- ADR: `docs/adr/0021-content-source-registry-and-free-source-expansion.md`
- Spec/plan: `docs/superpowers/{specs/2026-06-29-wse-pr1-registry-govinfo-design.md, plans/2026-06-29-wse-pr1a-registry-govinfo.md}`
- SDD ledger: `.superpowers/sdd/progress.md`
- Memory: `project-fiduciary-grade-milestone` (current-state block at top), `project-fiduciary-grade-positioning-and-launch-docs` (DE-365), `MEMORY.md` index.
- Prior handoff: `docs/LQVern/HANDOFF-2026-06-28-wsd-pr1.md`.
