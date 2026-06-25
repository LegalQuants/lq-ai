# Handoff — 2026-06-25 — Fiduciary-grade milestone, Phase 1 in flight

`main` (LegalQuants + tucuxi, both == **`e9c399d`**) at session end. All work below is **merged to `main`**.

## What shipped this session

### Inbox cleanup — parallel contributor PRs #185 / #186 (PR5b-i/ii, SaifAlYounan)
Both were rebuilds of the governed chat tool-loop already on `main` (closed P5b work). Verified by local merge: #185 conflicted in 4/6 files; #186's `0054_pending_tool_call.py` collided with main's `0054_chat_pending_tool_call.py` (duplicate alembic revision off `0053`). **Closed both with appreciative notes.** Genuinely-additive bits filed as **DE-358** (PR #215, merged) — streaming `tool_use` accumulation, OpenAPI doc gap, a `tools` count cap, granular `tool_choice` tests, encryption-at-rest for the pending-call payload, an api-side tier ceiling.

### New milestone scoped — "Fiduciary-grade agentic legal work" (LQ.AI's transparent answer to next-gen CoCounsel)
- Mini-PRD relocated from repo root → **`docs/proposals/fiduciary-grade-agentic-legal-work.md`** (its `../` links were written for that folder), inventory **reconciled against a 4-front codebase pass** (foundations thesis holds; 4 corrections folded in), maintainer decisions recorded, and a **Phase 1 PR decomposition** added.
- **ADR 0018** (`docs/adr/0018-citation-ledger-and-fiduciary-grade-output.md`) — the Citation Ledger + fiduciary-grade output decision. **Accepted 2026-06-24.** (PR #216.)
- Removed a stale `adr0016transparencyinvariants.patch` (ADR 0016 + its CI test were already committed).

### Phase 1 (WS-A) — three slices built, reviewed, merged
Each built via brainstorm → spec → plan → **subagent-driven development** (per-task spec+quality review + an Opus whole-branch review) → PR. Specs/plans live in `docs/superpowers/specs/` and `docs/superpowers/plans/` (dated `2026-06-24`).

1. **P1-A1 — external caselaw quote-verification core** (PR #218). Verifies the model's **verbatim** caselaw quotes (cascade stages 1–2, `gateway=None`, deterministic/no-cost) against the opinion text **already stored** by the research service — no new content store. New table `message_caselaw_citations` (migration `0057`), module `api/app/citation/caselaw.py`, guarded hook at the two tool-loop finalize sites. Paraphrase verification deferred to P1-B1.
2. **P1-A2 — Citation Ledger entry table + assembly** (PR #219). `citation_ledger_entry` (migration `0058`) — a **thin referencing** table over the three per-turn artifacts (`message_citations` / `message_caselaw_citations` / `message_tool_sources`) via three nullable FKs + `source_kind` (exactly-one-non-null CHECK), reserved `treatment_id` (WS-G). Assembler `api/app/citation/ledger.py` (`assemble_ledger_entries(db, *, message_id)`), guarded at all three chat-finalize sites incl. single-shot. **Metadata-only → added to the P3 no-raw-payload tripwire.** Reconciled ADR 0018 D1 (`citable_source_id` → `message_caselaw_citation_id`; `tier` dropped — `message_tool_sources` can't populate it).
3. **DE-350 — generic-MCP provenance** (PR #220). One `message_tool_sources` row per MCP call (`source_kind='mcp'`) via `extract_mcp_tool_source` + defensive `_mcp_label_url` + a `collect_tool_sources` router (keyed on `spec.kind`) in `tool_loop.py`. No schema/ledger change — flows into the P1-A2 ledger for free. PRD DE-350 marked **SHIPPED**.

### Also filed
- **DE-359** — savepoint-isolate the chat-finalize persistence flushes (defense-in-depth; surfaced by the P1-A1 final review; pre-existing risk class, unreachable in practice).
- **DE-358** — tool-use hardening backlog (above).
- Committed a stray Donna upstream request (`docs/lq-ai-skill-inputs-corpus.md`, PR #217) — `skill_inputs` don't reach the model for non-templated built-in skills; **likely wants its own DE/issue for the fix** (not filed unilaterally).

## Current milestone state

Phase 1 = WS-A (ledger) + WS-B (fiduciary-grade gate) + WS-C (UI), per ADR 0018. Sequence and status:

```
P1-0  ADR 0018 accept ............................ DONE (#216)
P1-A1 external caselaw quote-verify .............. DONE (#218)
P1-A2 citation_ledger_entry + assembly ........... DONE (#219)
DE-350 generic-MCP provenance .................... DONE (#220)   (ledger now covers KB-doc + caselaw + MCP sources)
   ├─ P1-A3 ledger read API + one-click trace .... NEXT (read surface; GET /chats/{id}/ledger + per-entry trace; P10: OpenAPI + IMPLEMENTED_ROUTES + path-count bump)
   └─ P1-B1 fiduciary-grade gate ................. NEXT (finalize-time computation; PASS {exact,tolerant} / SUPPORTED {paraphrase,ensemble} labeled / FAIL flagged; record on work_product; cost pre-flight for long-opinion paraphrase = DE-280/DE-344)
        └─ P1-C1 matter-scoped ledger UI ......... after A3+B1 (web/: reuse ProvenancePill/ToolSourcesPanel/M2Citations; trace + verbatim-vs-supported + fiduciary badge)
```
**P1-A3 and P1-B1 are parallelizable** (A3 is a read surface; B1 is a finalize computation). **P1-B1 pulls in DE-280** (case-content-accuracy judge over the stored opinion text) for the paraphrase tier.

**Phases 2–3** (each needs its own ADR before its workstream): WS-D plain-language matter intake → agentic session; WS-E content-source registry + free-source expansion (note: free-source expansion = the deferred Research surface, PRD §3.6, NOT DE-280/281; CourtListener today is BYO-key-gated); WS-G transparent validity/treatment layer (populates the reserved `treatment_id`); WS-F MCP-server ingress (the inbound boundary).

## Workflow reminders (load-bearing)

- Branch off `main` (never commit on `main`); push feature branches to **origin + tucuxi**; after a PR merges, **mirror `origin/main → tucuxi main`** (`git push tucuxi origin/main:main`) and confirm `origin == tucuxi`. Release tags are origin-only.
- **Security review per CODEOWNERS** for the citation/audit surface (`api/app/citation/**`, `chats.py`) — Kevin/security merge; Claude does **not** self-merge gated branches.
- **Tests run via host venv + a throwaway pgvector** (conftest auto-migrates): `docker run -d --rm --name lqai-test-pg -e POSTGRES_PASSWORD=postgres -e POSTGRES_DB=lqai_test -p 55432:5432 pgvector/pgvector:pg16` (then `CREATE EXTENSION vector`), and `cd api && DATABASE_URL=postgresql+asyncpg://postgres:postgres@127.0.0.1:55432/lqai_test .venv/bin/pytest …`. **NEVER** host `alembic upgrade` against the dev DB; never use port `15432`. No `-m provider` needed for this work (deterministic).
- Next migration number is **`0059`** (0057 = caselaw citations, 0058 = ledger).
- Build method that's working well: brainstorm (surface forks → AskUserQuestion) → spec → writing-plans → subagent-driven-development (cheap model for transcription tasks, sonnet for integration, **opus for the final whole-branch review**) → finishing-a-development-branch (push + PR). SDD ledger lives at `.superpowers/sdd/progress.md` (git-ignored scratch).
- Commits: `git commit -s` + `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`.

## Pointers
- Strategy: `docs/proposals/fiduciary-grade-agentic-legal-work.md`
- Decision: `docs/adr/0018-citation-ledger-and-fiduciary-grade-output.md`
- Specs/plans: `docs/superpowers/specs/2026-06-24-*` and `docs/superpowers/plans/2026-06-24-*`
- Memory: `project-fiduciary-grade-milestone`, `project-tool-use-and-ingest-state`
