# Handoff — 2026-06-30 — WS-E PR1a + PR1b merged; PR1c (chat authority consumer) next

`main` (LegalQuants + tucuxi, both == **`36b5126`**). Last migration = **`0064`** (PR1b). Next DE = **DE-370**.

---

## ⭐ SESSION-START NOTE — read first

**WS-E PR1a (#245) and PR1b (#246) are both MERGED + mirrored (origin==tucuxi==`36b5126`; branches deleted).** **DE-344 SHIPPED** (PR1a per-provider external-tool cost). **DE-369 SHIPPED for the AUTONOMOUS path** (PR1b: fetched-authority quotes are char-verified → ledger → fiduciary gate). **The one thing left in WS-E PR1 is PR1c: the CHAT consumer**, which closes DE-369 for the chat path by reusing ALL of PR1b's substrate. This handoff hands you the chat-loop map so you don't re-explore.

**Recommended first action:** this is a fresh design slice — run **brainstorm → spec → plan → subagent-driven-development** (same flow as PR1a/PR1b). Start by confirming ADR 0021 (D2/D3) doesn't need a refinement note for the chat path, then brainstorm. **Security-gated** (`api/app/chat/**` tool-loop, `api/app/api/chats.py` finalize, `api/app/citation/**`) → Kevin/security merges, **NO self-merge**; mirror `origin/main → tucuxi` after.

---

## What PR1c builds (reuse PR1b's substrate — do NOT rebuild it)

PR1b already shipped, on `main`, and PR1c **reuses all of it unchanged**:
- `citation/authority.py`: `authority_target`, `_AuthorityCandidate`, `store_authority_text(db, *, source_type, external_ref, text)`, `load_authority_text(db, *, source_type, external_ref) -> str | None` (30d TTL, path-traversal-hardened key, concurrent-safe upsert).
- `message_authority_citations` table + `authority_text_cache` (object storage + metadata) — mig 0064.
- `citation/ledger.py` 4th authority branch (assemble + resolve) — **already handles chat-path rows too** (keyed by message_id, which chat has).
- `gate.py` unchanged — authority statuses already bucket.
- `research/registry.py` `resolve_available_sources(gateway)`, `GovInfoAdapter.from_response`.

**PR1c adds only the chat-loop plumbing** so the chat model can fetch authority and its quotes get verified at finalize. **`gate.py` stays unchanged.** Likely **NO migration** (the tables exist; `MessageToolSource.source_kind` is a free String(32), so statute/regulation fit) — confirm in the spec; if none, next mig stays 0065 for a later slice.

## Chat tool-loop map (gathered in the PR1b session — verbatim, verify line numbers still hold)

**Central divergence from the autonomous shape:** chat does NOT expose a single `retrieve_authority(source,op,args)` tool. Chat exposes **granular ops** as individual functions (like `search_case_law`, `get_cluster`); `ToolIntent.retrieve_authority` is only the **governance/audit label**. So "expose authority in chat" = add granular `get_authority` (+ maybe `search_authority`) tool schemas, NOT one tool.

1. **Tool exposure** — `app/chat/tool_schemas.py:26` `RESEARCH_TOOL_SCHEMAS` (per-op `{description, parameters}`); `ChatToolAllowlist.function_schemas()` (`:116`) builds the model-facing list (fed to the gateway at `tool_loop.py:591`). **Add** an authority schema block here. `ToolSpec` (`:96`) is `kind: Literal["research","mcp"]` — **extend to include `"authority"`** and update every `spec.kind ==` branch.
2. **Availability gating** — `assemble_allowlist(db, *, request_id)` (`tool_schemas.py:130`) gates research ops on `get_capabilities()` (CourtListener-only, `research/service.py:38`). **Authority must gate on `resolve_available_sources(gateway)` filtered to `type=="govinfo"`, `enabled=True`** — a different signal; provider name comes from the registry, not `research_resolve_provider`.
3. **Dispatch — SEPARATE from guard** — the chat loop has its own closures in `app/chat/tool_loop.py`: `_dispatch_research` (`:299`) routes by op into `research.service`; `_dispatch_mcp` (`:360`). **Write a new `_dispatch_authority`** (mirror `_dispatch_research`): `gateway.call_tool(provider, op, args)` → `result["payload"]` → `GovInfoAdapter().from_response(op, payload)` → **`store_authority_text(db, source_type=..., external_ref=authority.external_ref, text=authority.citable_text)`** (this is where the chat path populates the cache — savepoint-isolate it non-fatally, mirroring PR1b guard.py) → `ToolResult(data={"authority": {...}})`.
4. **Shared governance (ADR 0016 P6)** — `execute_tool` (`tool_loop.py:412`) sets `intent = ToolIntent.retrieve_caselaw if kind=="research" else ToolIntent.call_mcp_tool` at `:462`; **add `kind=="authority" → ToolIntent.retrieve_authority`**; wraps `_dispatch` in `governed_tool_invocation` (`origin="chat"`, `message_id=assistant_message_id`). So chat authority also goes through R4/R5/R6 + the DE-344 cost model.
5. **Provenance at finalize** — `collect_tool_sources(spec, data)` (`tool_loop.py:283`) routes by `spec.kind`; **add an authority branch** → `ToolSourceRecord(source_kind=content_kind[statute/regulation], external_ref=package_id, provider="govinfo", ...)`. Persisted by `_persist_message_tool_sources` (`chats.py:2698`). **Chat CAN write `MessageToolSource`** (message_id exists at finalize — unlike the autonomous loop) → `source_kind` is a free `String(32)`, no migration.
6. **The finalize verify hook** — mirror `verify_and_persist_caselaw_citations` (`caselaw.py:319`): a new `verify_and_persist_authority_citations(db, *, message_id, assistant_text, tool_sources, load_authority_text=<from authority.py>, gateway, judge_model)`. It reads `tool_sources` where `source_kind in {statute,regulation}`, takes `external_ref` (package_id) as the join key, **loads the body from the authority cache** (`load_authority_text` — the chat analog of caselaw's `_default_load_opinion_text` which reads `ResearchOpinionMetadata`→object storage), extracts blockquotes from `assistant_text` (`extract_blockquote_passages`), `locate_passage` + `verify` → `MessageAuthorityCitation` rows. **Insert it into the finalize trio** at `chats.py` non-stream `~2957` and stream `~3556` — AFTER `verify_and_persist_caselaw_citations`, BEFORE `assemble_ledger_entries`/`compute_and_record_gate` (both already pick up the authority rows). Third site (`chats.py:3179`, single-shot, no tools) needs no authority verify.
7. **Only `get_authority` yields a quotable body** — `search_authority` puts the title in `citable_text` (`adapters.py:131`); PR1c should verify only `get_authority`-sourced refs.

## Load-bearing invariants (same as PR1b)
- **Reuse-not-fork:** reuse `verify()`/`locate_passage`/`assemble_ledger_entries`/`compute_and_record_gate`; **gate.py unchanged**. Don't re-implement the substrate.
- **Never-poison-the-session:** savepoint-isolate the cache write in `_dispatch_authority` (PR1b's guard.py lesson — bare SELECT/flush in `store_authority_text` must be inside a `begin_nested`); the finalize verify must be best-effort (mirror the existing caselaw finalize try/except — "never block the turn").
- **Honest verification:** a fabricated authority quote must FAIL → flag the gate (mirror caselaw's conservative `_fail_row`/`_parse_judge_response`).
- **P3:** body in object storage; audit/ledger rows carry only the cited passage + offsets.
- **One egress (ADR 0014):** the chat dispatch reaches GovInfo only via `gateway.call_tool` (the registry/adapter are shared).

## Process reminders (load-bearing — from PR1a/PR1b)
- **Create the PR1c branch BEFORE committing the spec/plan** (never commit planning docs on local `main` — it diverges from the squash). Push feature branches to **origin + tucuxi**.
- **subagent-driven-development**: per-task implement→review→fix + a **final Opus whole-branch review** — it caught a real gate-passing defect on **every** slice this milestone (3 of 5 PR1b tasks; the cross-task killer was a stale test call the per-task glob missed). Point the whole-branch review at cross-task signature changes + the never-poison paths.
- **DE-368:** run the api suite **SOLO** (no concurrent pytest vs the shared `lqai_test` DB). The **full SOLO suite is the real gate** — per-task test globs miss `tests/integration/` and `mypy app` doesn't check test stubs.
- **CI-scope gates from repo ROOT:** `ruff check/format --check api scripts` + `mypy app` (whole-app) + both full suites.
- **Test harness:** api host venv `api/.venv` + throwaway pgvector `lqai-test-pg` on `:55432`, `DATABASE_URL=postgresql+asyncpg://postgres:postgres@127.0.0.1:55432/lqai_test` (conftest auto-migrates).
- **Security-gated → Kevin/security merges, NO self-merge; mirror origin/main→tucuxi after; confirm origin==tucuxi.**
- Commits: `git commit -s` + `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`.

## Pointers
- PR1b spec/plan (the substrate PR1c reuses): `docs/superpowers/{specs/2026-06-30-wse-pr1b-authority-verification-design.md, plans/2026-06-30-wse-pr1b-authority-verification.md}` — see spec §6 "Out of scope (→ PR1c)".
- ADR: `docs/adr/0021-content-source-registry-and-free-source-expansion.md` (D2 generic intent / chat exposes granular ops; D3 mirror-the-caselaw-path).
- DE-369 (PRD §9): marked SHIPPED-autonomous; PR1c completes the chat path.
- Memory: `project-fiduciary-grade-milestone` (current-state block at top), `MEMORY.md` index.
- Prior handoff: `docs/LQVern/HANDOFF-2026-06-29-wse-pr1a.md`.

## After PR1c (WS-E remaining)
- **WS-E PR2:** SEC EDGAR + EUR-Lex adapters on the same registry + intent + verify path (behind flags). Then **PR2-UI** (Svelte session-ledger view, self-merge) → **DE-365** end-of-Phase-2 launch-docs pass. **WS-F (MCP ingress) = Phase 3** (own ADR).
