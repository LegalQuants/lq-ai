# Test Strategy and E2E Coverage Matrix

> **Purpose:** the documented test strategy for LQ.AI — what test suites exist, what each covers per product surface (smoke / happy-path / edge-case, with milestone tags and real spec paths), how each suite runs locally, and exactly what CI runs today. This is the M1 deliverable referenced from [CLAUDE.md](../CLAUDE.md) that shipped late (roadmap item 4.1).
>
> **Honesty contract (same as [HONEST-STATE.md](HONEST-STATE.md)):** every cell in the coverage matrix cites a real file in this repository. Gaps are stated as gaps with a pointer to the roadmap item or DE row that closes them. If a claim here disagrees with the codebase, the codebase is canonical — please open an issue.

Counts and CI facts below were verified on 2026-07-25 (`main`-based branch). Reproduce any count with the command shown; none require standing up the stack.

---

## 1. Test inventory

| Suite | Files | Where | Reproduce count |
|---|---|---|---|
| Backend (api) pytest | 236 | `api/tests/` (root 131 + `autonomous/` 49 + `integration/` 21 + `citation/` 21 + `tabular/` 7 + `models/` 3 + `chat/` 2 + `playbooks/` 2) | `find api/tests -name "test_*.py" \| wc -l` |
| Gateway pytest | 71 | `gateway/tests/` (incl. `anonymization/` 7) | `find gateway/tests -name "test_*.py" \| wc -l` |
| Web unit (Vitest) | 80 | `web/src/` (71 in `lib/lq-ai`, 9 in `routes/lq-ai`) | `find web/src -name "*.test.ts" \| wc -l` |
| Web E2E (Cypress) | 17 spec files — **16 with tests**; `documents.cy.ts` is an empty shell | `web/cypress/e2e/` | `ls web/cypress/e2e/*.cy.ts \| wc -l` |
| Cross-cutting contract | 2 | `tests/` (`test_error_code_contract.py`, `test_observability.py`) | `ls tests/test_*.py` |
| Slack bridge pytest | 3 | `slack-bridge/tests/` (`test_signing.py`, `test_oauth.py`, `test_config.py`) | `ls slack-bridge/tests/test_*.py` |
| Teams bridge pytest | 2 | `teams-bridge/tests/` (`test_oauth.py`, `test_config.py`) | `ls teams-bridge/tests/test_*.py` |
| Word add-in (Vitest) | 2 | `word-addin/src/taskpane/__tests__/` (`auth.test.ts`, `version.test.ts`) | `ls word-addin/src/taskpane/__tests__/` |
| Desktop launcher (Vitest) | 9 | `desktop/src/core/*.test.ts` + `desktop/src/main/orchestrator.test.ts` | `find desktop/src -name "*.test.ts" \| wc -l` |

Of the 17 Cypress spec files, four are inherited from upstream OpenWebUI (`chat.cy.ts`, `documents.cy.ts`, `registration.cy.ts`, `settings.cy.ts`); the other 13 are LQ.AI-authored (the `m2-*`/`m3-*`/`m4-*` and `wave-*` specs).

The E2E tool is **Cypress**, not Playwright. Older prose (CONTRIBUTING.md "End-to-end tests — Playwright"; the `e2e` pytest marker text in `api/pyproject.toml`) predates that reality; no Playwright tests exist in the repository.

---

## 2. What CI runs today (precise)

Read the workflows yourself: [.github/workflows/ci.yml](../.github/workflows/ci.yml), [stack-smoke.yml](../.github/workflows/stack-smoke.yml), [release.yml](../.github/workflows/release.yml), [desktop-release.yml](../.github/workflows/desktop-release.yml).

**`ci.yml`** — on every PR (any target branch) and pushes to `main`. Three jobs:

- **Web:** `npm run check:lq-ai` (svelte-check scoped to LQ.AI-owned code; upstream OpenWebUI debt tracked as DE-262) + `npm run test:frontend -- --run` (Vitest).
- **API:** `ruff check api scripts`, `ruff format --check`, `mypy app` (standard mode), `pytest -q` against a real `pgvector/pgvector:pg16` service container (`api/tests/conftest.py` creates a fresh per-run database).
- **Gateway:** `ruff check gateway`, `ruff format --check`, `mypy app` (`--strict` per config), `pytest -q` (no service containers).

**`stack-smoke.yml`** — on dependency-manifest/Dockerfile/migration PR paths, pushes to `main`, and manual dispatch. Runs `scripts/stack-smoke.sh`: builds every default-profile compose image, boots the stack to healthy (api boot runs `alembic upgrade head`), probes health endpoints and lazily-imported deps, soaks, asserts no restarts. It proves "builds, migrates, boots, and holds" — **not** that features work.

**`desktop-release.yml`** — only on `desktop-v*` tag push or manual dispatch: runs the desktop Vitest suite + typecheck before building the .dmg.

**`release.yml`** — image build/SBOM/signing only; runs no tests.

**What CI does *not* run — stated plainly:**

| Not in CI | Where it lives | Closed by |
|---|---|---|
| Cypress E2E (all 17 specs) | `web/cypress/e2e/` | roadmap 4.2 |
| Coverage measurement or gate (no `--cov` anywhere in workflows) | — | roadmap 4.3 |
| Provider-marked tests (`pytest -m provider`) | `gateway/tests/test_anthropic_provider.py`, `test_inference_anthropic.py`, `test_courtlistener_live.py` | operator-run only (need real API keys) |
| Cross-cutting contract tests | `tests/` | not wired into any workflow |
| Slack/Teams bridge suites | `slack-bridge/tests/`, `teams-bridge/tests/` | not wired into any workflow |
| Word add-in Vitest | `word-addin/src/taskpane/__tests__/` | not wired into any workflow |
| Desktop Vitest on PRs | `desktop/src/` | runs only at desktop-release tag time |

Note the aspirational prose elsewhere: CONTRIBUTING.md says "CI enforces no-decrease coverage" and "provider tests run nightly" — neither is wired today. This document is the honest statement of record until 4.2/4.3 land.

---

## 3. E2E coverage matrix — surface × depth

Columns: **Smoke** (it renders / the route answers), **Happy path** (the primary workflow end-to-end), **Edge cases** (failure modes, authorization, limits). Milestone tags per [HONEST-STATE.md](HONEST-STATE.md). Cypress cells are UI-level E2E (against a running stack, network often stubbed via `cy.intercept`); pytest cells are listed where they carry depth the UI specs don't.

| Surface | Milestone | Smoke | Happy path | Edge cases | Gaps |
|---|---|---|---|---|---|
| Chat & conversational | M1 | `web/cypress/e2e/registration.cy.ts`; `web/cypress/e2e/chat.cy.ts` (upstream) | `web/cypress/e2e/wave-d1-power-features.cy.ts` (enhance prompt, KB attach, receipts drawer); `api/tests/test_chats_send_message.py`, `api/tests/test_chat_rag.py` | tier-floor refusal + admin override + member-no-override (`wave-d1-power-features.cy.ts`); `api/tests/test_chats_tier_floor.py`; `gateway/tests/test_inference_tier_floor.py` | — |
| App chrome / dashboard / trust surfaces | M1 | `web/cypress/e2e/wave-a-chrome.cy.ts` (tabs, role-aware visibility, ambient footer) | `web/cypress/e2e/wave-b-surfaces.cy.ts` (dashboard, trust cards, developer cards) | role-gated tab visibility (`wave-a-chrome.cy.ts`) | — |
| Matters / projects | M1 | `web/cypress/e2e/wave-c-matters.cy.ts` (routes, modal) | create matter → workspace → chat-in-matter (`wave-c-matters.cy.ts`); `api/tests/test_projects_endpoints.py` | privileged matter without tier floor → validation error (`wave-c-matters.cy.ts`); `api/tests/integration/test_projects_sandbox_concurrency.py` | — |
| Knowledge bases / ingestion | M1 | — | KB create → PDF upload → ingest to `ready` (`web/cypress/e2e/wave-m1-final-surfaces.cy.ts` Test 2 — real ingest round-trip, 90s response timeout in `web/cypress.config.ts`); `api/tests/test_knowledge_endpoints.py`, `api/tests/test_pipeline_ingest.py` | non-UTF-8 → `decode_error` (`api/tests/test_pipeline_parsers_text.py`); retrieval audit (`api/tests/test_kb_retrieval_audit.py`) | DOCX ingest is roadmap (DE-332 shipped text/md only) |
| Skills & skill creator | M1 | slash-invocation pill (`web/cypress/e2e/wave-d2-skill-creator.cy.ts` Test 4) | capture, wizard, fork, try-it sandbox (`wave-d2-skill-creator.cy.ts` Tests 1–5); `api/tests/test_user_skills.py`; `gateway/tests/test_skill_assembler.py` | `slash_alias` collision → inline error (`wave-d2-skill-creator.cy.ts` Test 6); `api/tests/test_projects_sandbox_slug_reserved.py`; SIGHUP reload (`api/tests/test_skill_sighup_reload.py`) | — |
| Saved prompts / receipts | M1 | — | saved-prompt round-trip + receipts source attribution (`web/cypress/e2e/wave-m1-final-surfaces.cy.ts` Tests 1, 3); `api/tests/test_saved_prompts.py`, `api/tests/test_chat_receipts.py` | — | — |
| Citation engine | M2 | — | all four citation UI states in one message (`web/cypress/e2e/m2-c2-citation-states.cy.ts`); cascade stages (`api/tests/citation/test_verify_cascade.py`, `test_exact_match.py`, `test_tolerant_match.py`, `test_paraphrase_judge.py`, `test_ensemble.py`) | chunk boundaries, edge cases, cost caps (`api/tests/citation/test_chunk_boundary.py`, `test_edge_cases.py`, `test_cost.py`) | — |
| Anonymization layer | M2 | — | gateway middleware + engine (`gateway/tests/anonymization/test_middleware.py`, `test_engine_integration.py`); round-trip identity (`gateway/tests/anonymization/test_round_trip.py`) | `gateway/tests/anonymization/test_edge_cases.py`; observability (`gateway/tests/test_anonymization_observability.py`) | property-based invariants → DE-230/DE-240 |
| Playbooks | M3 | — | execution happy path incl. cost preview + polling (`web/cypress/e2e/m3-a4-playbook-execution.cy.ts`); easy-playbook wizard (`web/cypress/e2e/m3-a6-easy-playbook-wizard.cy.ts`); `api/tests/playbooks/test_executor.py` | builtin playbook conformance (`api/tests/test_builtin_nda_playbooks.py`, `test_builtin_msa_dpa_playbooks.py`) | no UI edge-case spec (failure mid-execution is pytest-only) |
| Tabular review | M3 | — | wizard → execute → poll → grid → citation modal (`web/cypress/e2e/m3-c-tabular-review.cy.ts`); `api/tests/tabular/test_nodes.py`, `test_worker.py`, `test_export.py` | ensemble-verification integration + cost (`api/tests/tabular/test_ensemble_verification_integration.py`, `test_cost.py`) | — |
| Word add-in | M3 (scaffold) | OAuth dialog renders without app chrome (`web/cypress/e2e/m3-b2-word-addin-oauth.cy.ts`) | oauth-success postMessage flow (`m3-b2-word-addin-oauth.cy.ts`); `api/tests/test_word_addin_endpoints.py`; `word-addin/src/taskpane/__tests__/auth.test.ts` | password-change + inline-401 paths (`m3-b2-word-addin-oauth.cy.ts`) | in-Word feature surfaces deferred (DE-287); add-in tests not in CI |
| Intake bridges (Slack/Teams) | M3 (partial) | — | request signing, OAuth install, config (`slack-bridge/tests/test_signing.py`, `slack-bridge/tests/test_oauth.py`, `teams-bridge/tests/test_oauth.py`); api side (`api/tests/test_integrations_slack.py`, `test_integrations_teams.py`, `test_admin_intake_bridges.py`) | — | never exercised against live Slack/Microsoft endpoints (DE-312); bridge suites not in CI; no E2E |
| Autonomous layer | M4 | opt-in gating / tab visibility (`web/cypress/e2e/m4-autonomous.cy.ts` Scenario 1) | receipt view, memory keep, precedent dismiss, run-now (`m4-autonomous.cy.ts` Scenarios 2–6); `api/tests/autonomous/test_executor_real_work.py`, `test_sessions_api.py` | brakes R4/R5/R6 (`api/tests/autonomous/test_brakes.py`, `test_r4_per_trigger_cap.py`, `test_idle_watchdog.py`, `test_spawn_optin_guard.py`); gateway-error path (`test_executor_gateway_error.py`) | Cypress scenarios are network-stubbed, not live-executor E2E |
| Legal research / fiduciary layer | post-M4 | — | `api/tests/test_research_endpoints.py`, `test_research_service.py`; ledger + gate (`api/tests/integration/test_citation_ledger.py`, `test_fiduciary_gate.py`); tool-loop (`api/tests/integration/test_chat_tool_loop_send.py`); adapters (`gateway/tests/test_courtlistener_adapter.py`, `test_edgar_adapter.py`, `test_govinfo_adapter.py`, `test_eurlex_adapter.py`) | fail attribution (`api/tests/integration/test_caselaw_fail_attribution.py`); treatment concurrency (`api/tests/citation/test_treatment_concurrency.py`); tool rate-limit (`gateway/tests/test_tool_ratelimit.py`) | no Cypress spec for research/"Sources consulted" UI |
| Admin & settings | M1–M4 | `web/cypress/e2e/settings.cy.ts` (upstream modals); fresh-install login UX (`web/cypress/e2e/m3-0-fresh-install-login.cy.ts`) | `api/tests/test_admin_provider_keys.py`, `test_admin_users_list.py`, `test_admin_tool_providers.py` | bootstrap-hint 401 discrimination (`m3-0-fresh-install-login.cy.ts`); MFA + session timeout (`api/tests/test_mfa.py`, `test_session_timeout_mfa_mandatory.py`) | — |
| Gateway inference & providers | M1–M2 | `gateway/tests/test_health.py` | per-provider adapters (`gateway/tests/test_anthropic_adapter.py`, `test_openai_adapter.py`, `test_azure_openai_adapter.py`, `test_ollama_adapter.py`); streaming/routing (`test_inference_streaming_routing_log.py`) | provider error mapping (`gateway/tests/test_provider_error_mapping.py`); guarded egress (`test_guarded_egress.py`); live-provider tests gated `-m provider` | live-provider tests never run in CI |
| Security & transparency invariants | cross-cutting | — | transparency invariants (`api/tests/test_transparency_invariants.py`); audit log (`api/tests/test_audit_log.py`); secrets (`gateway/tests/test_secrets.py`); encryption (`api/tests/test_encryption.py`) | receipt PII-sentinel assertions (`api/tests/autonomous/test_sessions_api.py`); error-code contract across subsystems (`tests/test_error_code_contract.py`) | `tests/` contract suite not in CI; injection/PII detection-rate measurement → DE-239/DE-240 |
| Desktop launcher | post-M4 | — | `desktop/src/core/engine.test.ts`, `desktop/src/core/compose.test.ts`, `desktop/src/main/orchestrator.test.ts` | `desktop/src/core/ports.test.ts`, `desktop/src/core/secrets.test.ts` | runs in CI only at `desktop-v*` tag time; no E2E |

Depth caveat worth repeating: most LQ.AI Cypress specs stub the network layer (`cy.intercept`) and verify UI behavior against controlled responses; the notable full-stack exceptions are the KB ingest round-trip (`wave-m1-final-surfaces.cy.ts` Test 2) and skill-creator try-it (`wave-d2-skill-creator.cy.ts` Test 5), which need the real stack. "Happy path covered" in a Cypress cell means the *UI workflow* is covered, not that a live provider call was made.

---

## 4. How to run each suite locally

```bash
# API (needs Postgres with pgvector; conftest creates a throwaway per-run DB)
cd api && DATABASE_URL=postgresql+asyncpg://lq_ai:lq_ai@localhost:5432/lq_ai pytest
# NEVER run host-side alembic against the live dev DB (127.0.0.1:15432) — see CLAUDE.md.
# Use a throwaway pgvector/pgvector:pg16 container; conftest auto-migrates it.

# Gateway (no services needed)
cd gateway && pytest
pytest -m "not provider"      # default posture; provider tests need real API keys

# Web unit
cd web && npm run test:frontend -- --run

# Web E2E (needs the stack up at http://localhost:3000 — see web/cypress.config.ts)
cd web && npx cypress run           # headless; npm run cy:open for interactive

# Cross-cutting contract tests
cd tests && pytest

# Bridges
cd slack-bridge && pytest
cd teams-bridge && pytest

# Word add-in / desktop
cd word-addin && npm test
cd desktop && npm test

# Full-stack boot smoke (same script CI runs)
./scripts/stack-smoke.sh
```

Conventions (locked in per CONTRIBUTING.md "Test stack conventions"): pytest + `pytest-asyncio` in `auto` mode; markers `unit` / `integration` / `provider` / `slow` declared in each `pyproject.toml`; api integration tests hit real Postgres, gateway tests mock providers with `respx`.

---

## 5. Flake register

Known non-deterministic tests. A flake stays listed until the fix merges with a regression note.

| Test | Symptom | Cause | Status |
|---|---|---|---|
| `api/tests/autonomous/test_sessions_api.py::test_receipt_assembles_phase_transitions_and_tool_calls` | `started`/`success` tool-call rows occasionally assert out of order | `build_receipt` orders audit rows by `AuditLog.timestamp` only (`api/app/autonomous/receipt.py`); rows written in the same transaction can tie on timestamp, making order nondeterministic | open — fix is a stable tiebreaker (e.g. `order_by(timestamp, id)`) + regression test |

---

## 6. Gap register → roadmap

| Gap | Impact | Closed by |
|---|---|---|
| Cypress not in CI | the 16 live E2E specs only run when someone runs them | roadmap 4.2 |
| No coverage measurement/gate | the 80% api / 90% gateway targets are aspirational; no floor is enforced | roadmap 4.3 (ratchet from measured floor) |
| Bridge, word-addin, and cross-cutting `tests/` suites not in any workflow | regressions in those packages land silently | fold into 4.2/4.3 wiring |
| `documents.cy.ts` empty shell | inventory overstates E2E count by one | delete or populate during 4.2 |
| No mutation / property-based / a11y / contract / chaos / perf testing | see the engineering-discipline roadmap | 4.4–4.9, DE-229/230/231/232, DE-250/251/252/253 |
| No eval harness for skill substantive quality | "passes tests" ≠ "correct legal work product" | DE-237 |

---

*Maintained alongside HONEST-STATE.md §8. When a suite is added, moved, or wired into CI, update the inventory, the matrix, and the gap register in the same PR.*
