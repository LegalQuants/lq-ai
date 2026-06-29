# WS-D PR2 — Fiduciary Ledger + Gate for Matter Sessions (Design)

**Status:** Approved (2026-06-28, maintainer) · **Security-gated** (migration + `api/app/autonomous/**` + `api/app/citation/**` + `chats.py`).
**ADR:** [0020](../../adr/0020-governed-agentic-legal-matter-sessions.md) D6 (PR2 scope) · reuse anchors: [0016](../../adr/0016-transparency-and-governance-invariants.md) P6 (one governance path), [0018](../../adr/0018-citation-ledger-and-fiduciary-grade-output.md) (ledger + gate), [0019](../../adr/0019-transparent-validity-treatment-layer.md) D7 (P3 storage).
**Predecessor:** WS-D PR1 (#239, merged `7dd8ac6`) — the governed agentic loop + matter intake. PR1 produces `analysis_content` (fenced-JSON findings) + `analysis_plan_trace` and writes the receipt to `session.result`. PR2 adds **no ledger/gate fork** — it routes the session's work product through the *same* cascade the chat path uses.

## Goal

A matter-scoped autonomous session produces the **same** `citation_ledger_entry` + `work_product_fiduciary_gate` rows a chat turn produces, so a reviewer traces a session's citations exactly as they trace a chat turn's, and the work product is honestly labeled `fiduciary_grade` / `supported_only` / `flagged`. Achieved by manufacturing a **hidden session-owned chat + message** and feeding **structured citations** through the existing character-fidelity verifier → `assemble_ledger_entries` → `compute_and_record_gate`.

## Non-goals (deferred)

- The Svelte session-ledger **UI** → **PR2-UI follow-up** (self-merge after CI; mirrors the WS-G PR1 → PR1-UI split).
- MCP source provenance in the session ledger (WS-F is Phase 3).
- `treatment_id` linkage (WS-G; the column stays null per ADR 0018 D6).
- Metered-source cost (DE-344 lands in WS-E).

## Load-bearing invariants

1. **Reuse, do not fork (ADR 0016 P6 / 0020 D6):** the session writes the *same* `message_citations` / `message_caselaw_citations` / `citation_ledger_entry` / `work_product_fiduciary_gate` rows the chat path writes; it reuses the fidelity verifier (`verify()`), `assemble_ledger_entries`, and `compute_and_record_gate` unchanged. No parallel ledger/gate.
2. **Strictly additive / backward-compat:** query-less (non-matter) sessions are unchanged — no manufactured chat, no ledger/gate, `session.result` unchanged. Only sessions whose analysis produced a matter work product run the cascade.
3. **Best-effort, never blocks delivery:** the entire cascade is wrapped (try/except → log) exactly like the chat path's three call sites and PR1's brake-commit discipline. A cascade failure leaves the session delivered with an honest receipt, never crash-loops the worker.
4. **P3 (ADR 0016 / 0019 D7):** the planner keeps seeing only compact observations (counts/ids/case-names/short snippets); audit, `analysis_plan_trace`, and ledger rows store offsets/labels/status/ids — never raw opinion/chunk payloads. The synthesis call legitimately receives gathered evidence content (the model's working context), but that content is never persisted to audit/trace.
5. **Hidden chat is invisible in the chat surface:** a session-owned chat (`autonomous_session_id IS NOT NULL`) never appears in `list_chats` / `search_chats`; it is reachable only by direct id (the read endpoint).
6. **Honest labeling (ADR 0018 D3):** a work product is `fiduciary_grade` only when every assertion is ledger-backed and passing; unverifiable quotes are dropped/flagged exactly as the chat path does — never fabricated to inflate the gate.

## Verified reuse surface (file:line)

- `assemble_ledger_entries(db, *, message_id)` — `api/app/citation/ledger.py:32`. Self-derives `chat_id`/`project_id`; reads `message_citations` + `message_caselaw_citations` + `message_tool_sources` by `message_id` (tool-sources optional). Writes `citation_ledger_entry`, flushes, never commits.
- `compute_and_record_gate(db, *, message_id)` — `api/app/citation/gate.py:33`. Reads `citation_ledger_entry` by `message_id`; upserts one `work_product_fiduciary_gate` row (pass/supported/fail counts + status). Flushes, never commits. `resolve_gates` (gate.py:111) is the read path.
- Fidelity verifier — `verify(candidate, document, *, gateway=None, judge_model=...)` `api/app/citation/verification.py:545`; deterministic stages `verify_exact_match` (152), `verify_tolerant_match` (183). Takes `_CandidateProtocol` (offset_start/end, source_text, source_document_id) + `_DocumentProtocol`. **Separable from prose extraction.**
- KB offset resolution — `_locate_in_chunk(quote, chunk_content)` `api/app/citation/extraction.py:128` → promote to public `locate_in_chunk` (single fidelity-threshold source). `CitationCandidate` dataclass at extraction.py:87.
- Caselaw primitives — `locate_passage` `api/app/citation/caselaw.py:170`, `opinion_target` (162), `_CaselawCandidate` (153); cluster→opinion via `ResearchOpinionMetadata` (`api/app/models/research.py:31`); text via `read_opinion(db, opinion_id=...)` `api/app/research/service.py:210`.
- `MessageCitation` model `api/app/models/chat.py:225` (NOT NULL: message_id, source_file_id, source_offset_start/end, source_text, verified, partial; if verified→verification_method required). `MessageCaselawCitation` `api/app/models/message_caselaw_citation.py:23` (NOT NULL: message_id, opinion_id, cluster_id, offsets, source_text, verified, partial).
- `Chat` model `api/app/models/chat.py:54` (no visibility column today → migration). `list_chats` filter `api/app/api/chats.py:743`; `search_chats` 655/681. Chat manufacture pattern `create_chat` chats.py:556. `Message` minimal row: `chat_id`, `role="assistant"`, `content` (chat.py:123).
- `AutonomousSession` `api/app/models/autonomous.py`: `user_id` (91), `project_id` (96), `result` JSON (124). No chat link today.
- Latest migration `0062`; **next = `0063`**.

## Components

### C1 — Migration 0063: hidden session-owned chat
Add `chats.autonomous_session_id UUID NULL FK → autonomous_sessions.id ON DELETE SET NULL` + partial index `WHERE autonomous_session_id IS NOT NULL`. Template: `0056_chat_sticky_skills.py`. Update `docs/db-schema.md` (chats table). Add `Chat.autonomous_session_id` to the ORM. Add `.where(Chat.autonomous_session_id.is_(None))` to the base `stmt` in `list_chats` (chats.py:743) and the two `search_chats` subqueries (655/681). `_load_visible_chat` (340) is left as-is (direct GET by id still resolves — the read endpoint needs it).

### C2 — Loop evidence registry (planner stays P3)
`_run_analysis_loop` (`api/app/autonomous/nodes.py`) accumulates a per-session **evidence registry**: each successful `retrieve_chunks` / `retrieve_caselaw` act appends entries with a stable source number `N` → `{n, kind: "kb"|"caselaw", chunk_id | cluster_id, content, ...display}`. The planner observation summaries are unchanged (P3). `summarize_observation` for caselaw additionally includes the `cluster_id` (an id, P3-OK) so the synthesis can reference it. The registry is loop-local state returned for synthesis + delivery; it is **not** written to `analysis_plan_trace`/audit.

### C3 — Structured citations on the synthesis output
Extend the synthesis structured-output schema: each finding gains `citations: [{quote: str, source: int}]` where `source` indexes the evidence registry. `assemble_synthesis_messages` presents the evidence as a **numbered source list** and instructs the model to support each finding with verbatim quotes tagged to a source number. `parse_structured_output` tolerantly parses the new key (absent → empty; unknown source numbers → dropped). Drafting/`emit_finding` is unchanged (ignores `citations`). The findings + registry flow to the delivery node via state.

### C4 — Delivery cascade (structured → verifier → ledger → gate)
New module `api/app/autonomous/ledger_bridge.py` (keeps `nodes.py` focused) exposing `build_session_ledger(db, *, session, work_product_text, findings, evidence, gateway) -> GateVerdict | None`. In the delivery node, for a matter session with a parsed work product, before `build_receipt_safe`:
1. Manufacture `Chat`(autonomous_session_id=session.id, owner_id=session.user_id, project_id=session.project_id, title=f"Matter session {session.id}") + `Message`(role="assistant", content=work_product_text). Flush to get `message_id`.
2. For each finding citation, resolve `source N` → evidence; **KB:** `DocumentChunk` by `chunk_id` → `locate_in_chunk(quote, content)` → doc-absolute offsets → `CitationCandidate` → `verify()` → `MessageCitation` (verified rows only). **Caselaw:** `cluster_id` → `ResearchOpinionMetadata` → `read_opinion` → `locate_passage` → `verify()` → `MessageCaselawCitation`.
3. `assemble_ledger_entries(db, message_id)` → `compute_and_record_gate(db, message_id)`.
4. Return the gate verdict; the delivery node embeds `{gate_status, pass_count, supported_count, fail_count, total_assertions, confidence}` into `session.result["fiduciary_gate"]` alongside `plan_trace`.
All wrapped best-effort (invariant 3). The synthesis `judge_model` follows the session's model setting; tolerant/exact stages run deterministically, the judge stage opt-in via the gateway (same as chat).

### C5 — Read endpoint
`GET /api/v1/autonomous/sessions/{session_id}/ledger` (autonomous router): authorize the session owner, find the chat via `autonomous_session_id == session_id`, reuse the existing ledger-resolve + `resolve_gates` read path scoped to that chat, and return the same ledger/gate response shape the chat ledger endpoint returns (404 if the session has no ledger yet).

## Error handling

- Cascade wrapped best-effort in delivery; a failure logs (`event="autonomous_ledger_bridge_failed"`) and delivery proceeds with the receipt sans `fiduciary_gate`. Never crash the worker (DE-325 discipline).
- Async-session safety (PR1 C1 lesson): the bridge does only well-formed ORM inserts + the existing flush-only cascade; no model-arg-driven SQL. A `DBAPIError` would propagate to the delivery node's existing handling; the bridge does not swallow exceptions in a way that poisons the session (it runs after the loop, before the terminal commit, and its try/except logs then skips — the terminal commit still persists status).
- Unverifiable quotes: dropped (KB) / FAIL-row convention (caselaw, offsets 0..len) exactly as the chat path — honest, never fabricated.

## Testing

- **Unit:** the structured-citation adapter — KB (`locate_in_chunk` + `verify` → `MessageCitation`) and caselaw (`locate_passage` + `verify` → `MessageCaselawCitation`) for verified / unverified / partial; evidence-number → source resolution; tolerant parse of the new `citations` key.
- **Integration:** scripted matter session end-to-end (PR1's `_ScriptedGateway` + seeded KB + seeded `ResearchOpinionMetadata`) → asserts real `citation_ledger_entry` + `work_product_fiduciary_gate` rows on the manufactured chat; `session.result["fiduciary_gate"].gate_status` set; the manufactured chat **excluded** from `list_chats`/`search_chats` but resolvable by the read endpoint; query-less session unchanged (no chat, no gate).
- **Migration:** verified on a throwaway `pgvector` (conftest auto-migrates); `0063` up/down.
- **Gates (CI scope, repo root):** `ruff check api scripts` + `ruff format --check api scripts` + whole-app `mypy app` + full api suite **run solo** (the PR1 lesson: do not run concurrent pytest against the shared `lqai_test` DB — DE-368).

## PR structure & merge gating

- **PR2 (this slice, security-gated):** migration 0063 + `chats.py` filters, loop evidence registry, synthesis schema, `ledger_bridge.py` + delivery wiring, read endpoint, tests. → security/maintainer merge, **no self-merge**; mirror `origin/main → tucuxi` after.
- **PR2-UI (follow-up):** Svelte session-ledger view in `web/`, mirroring the chat ledger UI. Self-merge after CI.

## Open items folded into the plan

- Promote `_locate_in_chunk` → public `locate_in_chunk` (single fidelity-threshold source).
- `next migration = 0063`; `next DE = DE-369` (DE-368 was filed in PR1 verification).
