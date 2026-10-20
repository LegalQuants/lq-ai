# WS-E PR1c — Chat authority consumer (design)

> Slice: WS-E PR1c (Phase 2, "Fiduciary-grade agentic legal work").
> Branch: `feat/wse-pr1c-chat-authority` off `main` @ `96a7784`.
> Security-gated (`api/app/chat/**`, `api/app/api/chats.py` finalize, `api/app/citation/**`) → Kevin/security merges, NO self-merge; mirror `origin/main → tucuxi` after.
> Reuses PR1a (#245) + PR1b (#246) substrate verbatim. **No migration.** `gate.py` and `ledger.py` unchanged.

## 1. Goal

Let the **chat** model fetch USCODE/CFR authority from GovInfo and have its verbatim quotes char-verified at finalize, closing **DE-369** for the chat path. This is the chat analog of PR1b's autonomous path: fetched-authority quotes become durable, verified, ledger-backed provenance that feeds the fiduciary gate.

PR1c adds only chat-loop plumbing on top of PR1b's substrate:
- `citation/authority.py` — `authority_target`, `_AuthorityCandidate`, `store_authority_text`, `load_authority_text` (30-day TTL, path-traversal-hardened key, concurrent-safe upsert). **Reused unchanged.**
- `message_authority_citations` table + `authority_text_cache` (object storage + metadata) — mig 0064. **Reused unchanged.**
- `citation/ledger.py` 4th authority branch (assemble + resolve) — already keys by `message_id`, which chat has. **Reused unchanged.**
- `gate.py` — authority statuses already bucket (`exact_match`/`tolerant_match` → PASS, `paraphrase_judge` → SUPPORTED, `unverified` → FAIL). **Reused unchanged.**
- `research/registry.py` `resolve_available_sources(gateway)`, `research/adapters.py` `GovInfoAdapter.from_response`. **Reused unchanged.**

### DE-369, chat path — what this PR delivers
1. **Fetch → durable body:** chat `get_authority` writes the fetched text to the `authority_text_cache` (chat runs the write the autonomous path runs in `guard.py`).
2. **Provenance:** every authority tool call (search + get) writes a `MessageToolSource` row (chat *has* a `message_id`, unlike the autonomous loop).
3. **Char-verify at finalize:** verbatim quotes of fetched authority are located + verified against the cached body → `MessageAuthorityCitation` rows.
4. **Ledger + gate:** those rows flow through the existing `assemble_ledger_entries` → `compute_and_record_gate` unchanged.

**Honest ceiling (this PR):** chat blockquotes are *unattributed* — a blockquote may quote an uploaded document or caselaw, not the fetched statute. So a quote that matches no fetched body is **dropped** (no row), not FAILed, to avoid false-positives. Attributed-authority FAIL (the B1c-analog) is deferred to **DE-370**. See §5.

## 2. Background — the caselaw path this mirrors (verified against code, 2026-06-30)

Chat caselaw already does exactly this shape:
- **Exposure:** `RESEARCH_TOOL_SCHEMAS` (`tool_schemas.py:26`) declares granular ops (`search_case_law`, `get_cluster`, …); `assemble_allowlist` (`:130`) gates them as a block on `get_capabilities()`; `ChatToolAllowlist.function_schemas()` (`:116`) feeds the gateway (`tool_loop.py:591`).
- **Dispatch:** `_dispatch_research` (`tool_loop.py:299`) routes by op into `research.service`, returns `ToolResult`.
- **Governance:** `execute_tool` (`tool_loop.py:412`) maps `kind=="research" → ToolIntent.retrieve_caselaw` (`:462`) and wraps dispatch in `governed_tool_invocation(origin="chat", message_id=assistant_message_id, …)`.
- **Provenance:** `collect_tool_sources(spec, data)` (`tool_loop.py:283`) routes by `spec.kind`; caselaw records get `source_kind="caselaw"`. Persisted by `_persist_message_tool_sources` (`chats.py:2698`).
- **Verify at finalize:** `verify_and_persist_caselaw_citations` (`caselaw.py:319`) filters `tool_sources` by `source_kind`, loads opinion bodies, `extract_blockquote_passages(assistant_text)`, then per passage × body `locate_passage` → `verify` → `MessageCaselawCitation`. Wired into the finalize trio **after** persist-tool-sources and **before** `assemble_ledger_entries` / `compute_and_record_gate` at the two tool-bearing sites (non-stream `chats.py~2948`, stream `~3543`).

**Central divergence (chat vs autonomous):** chat does **not** expose a single `retrieve_authority(source, op, args)` tool. It exposes **granular ops** as individual functions (like caselaw); `ToolIntent.retrieve_authority` is only the **governance/audit label** applied in `execute_tool`. This is consistent with ADR 0021 D2 ("a generic intent … the audit names the concrete source+op"): D2's generic intent is realized in chat exactly as `retrieve_caselaw` already is — one governance label over granular ops. No ADR refinement required.

**Cache/provenance key vs ledger label (from PR1b spec §7 — carried forward):**
- Cache key = `(source_type, external_ref)` where **`source_type = "govinfo"`** (the registry source) and `external_ref = package_id`. `store_authority_text` / `load_authority_text` key on this.
- **`content_kind`** (`statute` / `regulation`) is a *separate* label carried on the citation row and used as the ledger `source_kind`. It is **not** the cache key.
- `MessageAuthorityCitation`: `source_type="govinfo"`, `content_kind` = statute/regulation, `external_ref` = package_id (matches PR1b's `build_authority_citations`).

## 3. Architecture (PR1c scope — chat only)

```
chat tool-loop (per round)
  assemble_allowlist(db, gateway, request_id)
     research ops   ← get_capabilities().enabled      (unchanged)
     authority ops  ← resolve_available_sources(gateway) filtered type==govinfo, enabled   (NEW)
     mcp ops        ← cached MCP tools                 (unchanged)
  → function_schemas() → gateway.chat_completion
  model calls search_authority / get_authority
  → execute_tool: kind=="authority" → ToolIntent.retrieve_authority
       governed_tool_invocation(origin="chat", message_id=…)   (R4/R5/R6 + DE-344 cost, reused)
       → _dispatch_authority: gateway.call_tool → GovInfoAdapter.from_response
            get_authority → store_authority_text(source_type="govinfo", external_ref, text)  [savepoint, non-fatal]
       → ToolResult(data={"authority": {...}})
  → collect_tool_sources: authority branch → ToolSourceRecord(source_kind=content_kind, external_ref=package_id, provider="govinfo")

finalize (tool-bearing sites only)
  _persist_message_tool_sources            (unchanged; writes MessageToolSource)
  verify_and_persist_caselaw_citations     (unchanged)
  verify_and_persist_authority_citations   (NEW — after caselaw, before ledger)
  assemble_ledger_entries                  (unchanged; already reads authority rows)
  compute_and_record_gate                  (unchanged; already buckets authority statuses)
```

## 4. Components & interfaces

### 4.1 `api/app/chat/tool_schemas.py`
- Add `AUTHORITY_TOOL_SCHEMAS: dict[str, dict[str, Any]]` — `search_authority` and `get_authority`, each `{description, parameters}` (OpenAI JSON-schema args). `search_authority` args: `{query, collection?}`; `get_authority` args: `{package_id}` (mirror the GovInfo adapter's op contract). Add `AUTHORITY_OPS = frozenset(AUTHORITY_TOOL_SCHEMAS)`.
- Extend `ToolSpec.kind`: `Literal["research", "mcp"]` → `Literal["research", "mcp", "authority"]`.
- `assemble_allowlist` — **signature change**: `async def assemble_allowlist(db, *, gateway, request_id=None)`. After the research block, add an authority block gated on `resolve_available_sources(gateway)` filtered to `type=="govinfo"` and `enabled=True`; for each authority op build a spec `kind="authority", provider="govinfo", tool=op, read_only=True, destructive=False, requires_confirmation=False`. If no govinfo source is available, add no authority specs (honest unavailability — the model simply doesn't see the tools).
- Confirm the `assemble_allowlist` call site (in `chats.py` / the loop entry) has `gateway` in scope; thread it through.

### 4.2 `api/app/chat/tool_loop.py`
- `collect_tool_sources(spec, data)` — add an `authority` branch (before the caselaw `else`): read `data["authority"]` → `ToolSourceRecord(source_kind=<content_kind>, label=<citation/title>, subtitle=<title/date>, url=<url>, external_ref=<package_id>, provider="govinfo", tool=spec.tool)`. Emitted for **both** search and get (provenance always). Guard against missing keys (best-effort, mirror `extract_mcp_tool_source`).
- New `_dispatch_authority(db, *, spec, args, gateway, request_id) -> ToolResult`:
  1. `result = await gateway.call_tool(spec.provider, spec.tool, args)`; `payload = result["payload"]`.
  2. `authority = GovInfoAdapter().from_response(spec.tool, payload)`.
  3. **`get_authority` only:** `await store_authority_text(db, source_type=spec.provider, external_ref=authority.external_ref, text=authority.citable_text)` wrapped in `begin_nested()` + `except Exception` non-fatal (never poison the session; the store already does its own savepoint upsert, but the outer guard covers the SELECT/flush path per the PR1b guard.py lesson). `search_authority` does not write the cache.
  4. Return `ToolResult(cost_usd=Decimal("0"), data={"authority": {"source": spec.provider, "op": spec.tool, "content_kind": authority.content_kind, "external_ref": authority.external_ref, "label": authority.label, "subtitle": authority.subtitle, "url": authority.url, "citable_text": authority.citable_text}}, outcome="success")`.
- `execute_tool` — extend the intent map (`:462`): `kind=="authority" → ToolIntent.retrieve_authority`; extend the inner `_dispatch()` branch to route `kind=="authority"` to `_dispatch_authority`. `governed_tool_invocation`, `estimate_tool_cost`, `resolve_provider_tier`, DE-344 cost accrual reused unchanged (they already accept `ToolIntent.retrieve_authority`).

### 4.3 `api/app/citation/authority.py` — new finalize orchestrator
Add (alongside the reused substrate):

```python
async def verify_and_persist_authority_citations(
    db: AsyncSession,
    *,
    message_id: uuid.UUID,
    assistant_text: str,
    tool_sources: Sequence[ToolSourceRecord],
    load_authority_text: _LoadAuthorityText = load_authority_text,
    gateway: _JudgeGatewayProtocol | None = None,
    judge_model: str = "fast",
) -> int:
```

Body — **two passes**, mirroring `caselaw.verify_and_persist_caselaw_citations` exactly (a verbatim PASS pass, then a separate whole-body judge SUPPORTED pass). This structure is load-bearing: `locate_passage` is a byte-exact substring finder, so a single `locate_passage`→`verify` loop can only ever reach the exact/tolerant (PASS) stages — the paraphrase judge (Stage 3 of `verify()`) is **structurally unreachable** in that shape (a located span trivially exact/tolerant-matches; an unlocatable paraphrase never produces a candidate). The SUPPORTED (paraphrase) tier therefore requires a distinct whole-body judge pass, precisely as caselaw's B1b does. (This corrects the original single-pass sketch, which overclaimed a paraphrase tier the loop could not deliver — surfaced by the Task-4 review, 2026-06-30.)

Setup (shared by both passes):
1. Select authority refs: `tool_sources` where `r.source_kind in {"statute", "regulation"}` and `r.external_ref` present. Empty → return 0.
2. `passages = extract_blockquote_passages(assistant_text)` (reuse from `caselaw.py`). Empty → return 0.
3. Load each distinct `(provider, external_ref)` body once: `body = await load_authority_text(db, source_type=r.provider, external_ref=r.external_ref)`. Cache-miss (`None`) → skip that ref (search-only refs and expired bodies drop naturally). Build a per-target tuple carrying `(source_type=provider, external_ref, content_kind=source_kind, target=authority_target(provider, external_ref, body))`. On per-ref load exception → log + skip. No targets → return 0.

Pass A — verbatim (PASS tier), first-match-wins, **drop-on-miss**, `gateway=None`:
4. For each passage, for each loaded target, `off = locate_passage(passage, target.normalized_content)`; on hit build `_AuthorityCandidate` and `result = await verify(cand, target, gateway=None)` (verbatim-only — honest; the judge is unreachable here anyway, and hardcoding `None` mirrors caselaw's verbatim loop at `caselaw.py:392`); if `result.verified`, append `MessageAuthorityCitation(source_type=<provider>, external_ref=<external_ref>, content_kind=<content_kind>, source_offset_start=start, source_offset_end=end, source_text=passage, verified=True, verification_method=result.method, verification_confidence=result.confidence, partial=result.partial)`, record the passage in a `verbatim_matched` set, and `break` (first matching authority wins). No match against any target → no row **in this pass**.

Pass B — whole-body paraphrase judge (SUPPORTED tier), only `if gateway is not None`, budget-bounded:
5. For each passage **not** in `verbatim_matched`, for each loaded target: `est = await estimate_authority_content_cost_usd(db, judge_model=judge_model, authority_text=target.normalized_content)`; if `spent + est > AUTHORITY_CONTENT_JUDGE_BUDGET_USD` → `break` (budget reached; drop remaining judge work); else `spent += est` and `result = await judge_authority_content(passage=passage, authority_text=target.normalized_content, gateway=gateway, judge_model=judge_model)` (per-call exceptions swallowed → MISS → `continue`); on `result.verified`, append `MessageAuthorityCitation(... source_offset_start=0, source_offset_end=len(body), source_text=passage, verified=True, verification_method="paraphrase_judge", verification_confidence=result.confidence, partial=True)` and `break`. Not verified → `continue` (drop-on-miss preserved — no FAIL row).
6. `if rows: db.add_all(rows); await db.flush()`; return `len(rows)`.

New module `api/app/citation/authority_content_judge.py` (thin mirror of `case_content_judge.py`):
- `judge_authority_content(*, passage, authority_text, gateway, judge_model) -> VerificationResult` — reuses the generic `build_judge_prompt(claim_text=passage, chunks=[authority_text])`, `_parse_judge_response`, `_MISS` (never raises; MISS on `no`/malformed/gateway-error). `verified=True → method='paraphrase_judge'`.
- `estimate_authority_content_cost_usd(db, *, judge_model, authority_text) -> Decimal` — same length-scaled estimate as `estimate_case_content_cost_usd` (`db=None` → `DEFAULT_PER_JUDGE_USD` scaled by length).
- `_PURPOSE = "judge_authority_content"` (segregates authority judge calls in the cost-calibration routing log — do **not** reuse caselaw's purpose tag).
- `AUTHORITY_CONTENT_JUDGE_BUDGET_USD = Decimal("0.25")` (per-assistant-turn hard cap, matching the caselaw budget).

Notes:
- Pass A uses `gateway=None` (verbatim-only, honest, deterministic); the SUPPORTED tier lives entirely in Pass B via the whole-body judge. This is the exact caselaw split (verbatim loop `gateway=None` + separate `case_content_judge` pass).
- No FAIL rows in the chat path (unattributed blockquotes) — divergence from `build_authority_citations`, which FAILs on locate-miss because it has explicit `(quote, source)` evidence pairs. Documented in §5. Attributed FAIL = DE-370.
- `paraphrase_judge` is already in the `message_authority_citations` `verification_method` CHECK (mig 0064) → no migration.
- Import `ToolSourceRecord` under `TYPE_CHECKING`; import `extract_blockquote_passages`/`locate_passage`/`verify` function-local (break the `tool_loop`/`caselaw` ↔ `authority` cycle — mirror `guard.py:874`).

### 4.4 `api/app/api/chats.py` — finalize wiring
- Thread `gateway` into `assemble_allowlist(...)` at the loop-entry call site.
- Insert `verify_and_persist_authority_citations(db, message_id=…, assistant_text=…, tool_sources=…, gateway=gateway, judge_model=_authority_judge_model)` at the **two tool-bearing finalize sites** — non-stream (`~2948`, after `verify_and_persist_caselaw_citations`, before `assemble_ledger_entries`) and stream (`~3543`, same order) — each in its own best-effort `try/except` mirroring the caselaw call. Reuse the same resolved judge model the caselaw call uses (`gateway.get_citation_engine_judge_model()`); no second gateway round-trip.
- Single-shot no-tools site (`~3179`) — untouched (no tools → no authority).

### 4.5 Tests
- **Unit — `tool_schemas.py`:** `assemble_allowlist` adds authority specs when a govinfo source is available; adds none when absent; research/mcp gating unchanged.
- **Unit — `tool_loop.py`:** `_dispatch_authority` maps payload → adapter → `ToolResult.data["authority"]`; writes the cache on `get_authority`; does **not** write on `search_authority`; store failure is swallowed (session still usable — assert a following query succeeds). `collect_tool_sources` authority branch emits a record for both ops with the right `source_kind`/`external_ref`/`provider`.
- **Unit — `authority.py` + `authority_content_judge.py`:** Pass A verbatim PASS (`exact_match`); **Pass B paraphrase SUPPORTED — a passage that does NOT locate verbatim but a stub judge accepts → one `paraphrase_judge` row (the stub's `chat_completion` IS called; assert `verification_method=="paraphrase_judge"` and `partial is True`)**; drop-on-miss (blockquote matches no body and judge rejects → 0 rows); budget cap (`spent > AUTHORITY_CONTENT_JUDGE_BUDGET_USD` halts Pass B — no further judge calls); cache-miss ref skipped; per-ref load exception non-fatal; `gateway=None` → Pass B skipped entirely (verbatim-only determinism). `judge_authority_content` never raises (MISS on gateway error).
- **Integration:** a chat turn (non-stream + stream) that calls `get_authority`, quotes it verbatim → one `MessageAuthorityCitation` PASS row → ledger entry (`source_kind=statute`) → gate `fiduciary_grade`; a fabricated quote → 0 authority rows, gate unaffected by authority.
- **Gate:** full **SOLO** api suite (DE-368 — no concurrent pytest vs `lqai_test`); `ruff check/format --check api scripts` + `mypy app` from repo root. Update `IMPLEMENTED_ROUTES` / `EXPECTED_PATHS` only if a route is added (none expected — this is loop/finalize plumbing, no new endpoint).

## 5. Invariants (binding)
- **Reuse-not-fork:** reuse `verify()` / `locate_passage` / `authority_target` / `store_authority_text` / `load_authority_text` / `extract_blockquote_passages` / `assemble_ledger_entries` / `compute_and_record_gate`. **`gate.py` and `ledger.py` unchanged.**
- **Never-poison-the-session:** the cache write in `_dispatch_authority` is savepoint-isolated + non-fatal; the finalize verify is best-effort try/except (never blocks the turn).
- **Honest verification:** Pass A confirms a quote that appears **verbatim** in a fetched body → PASS (`exact_match`/`tolerant_match`); Pass B's whole-body judge confirms a **faithful paraphrase** → SUPPORTED (`paraphrase_judge`); a quote that neither appears verbatim nor is judged faithful → **dropped** (no row), because chat blockquotes carry no reliable authority attribution. No false-FAIL on uploaded-doc/caselaw quotes. The PASS tier and the SUPPORTED tier live in **separate passes** — a single locate-then-verify loop cannot reach the paraphrase judge (see §4.3). (Attributed-authority FAIL = DE-370.)
- **Provenance always (ADR 0021 D3):** both search and get authority calls write a `MessageToolSource` row.
- **P3:** bodies live in object storage; audit/ledger rows carry only the cited passage + offsets.
- **One egress (ADR 0014):** authority is reached only via `gateway.call_tool`; the registry/adapter are shared with PR1a/PR1b.
- **Only `get_authority` is quotable:** `search_authority` puts the title in `citable_text` (`adapters.py:131`) and writes no cache; its refs cache-miss and are never verified as quotes.

## 6. Out of scope (→ later)
- **Attributed-authority FAIL (DE-370):** parse a blockquote's nearby statute/reg citation → matched `get_authority` ref → FAIL a quote attributed to authority X that isn't in X. The B1c-analog for authority; needs a reliable statute/reg citation-attribution parser (formats vary). Deferred, mirroring the caselaw B1b→B1c staging.
- **`search_authority` quote verification** — search returns title-only `citable_text`; nothing to verify.
- **SEC EDGAR / EUR-Lex sources** — WS-E PR2.
- **Autonomous-path authority SUPPORTED tier (follow-up DE — file fresh):** PR1b's `ledger_bridge.build_authority_citations` (autonomous) has the same single `locate_passage`→`verify(gateway=…)` shape, so it too only reaches the PASS tier and never the paraphrase judge — its `gateway=` pass is effectively dead for Stage 3. A follow-up DE should either give the autonomous path the same whole-body judge pass this PR adds for chat, or drop its dead `gateway=` argument to `verify()` for honesty. Not fixed here (autonomous is out of PR1c's scope; already merged).
- **No migration**, no `gate.py` / `ledger.py` change, no new endpoint.

## 7. Open questions resolved (maintainer, 2026-06-30)
- **Ops exposed:** `search_authority` + `get_authority` (mirror caselaw's search + get). Only `get_authority` bodies are verified.
- **Verification depth:** Level 2 — verbatim + paraphrase, PASS/SUPPORTED, **drop-on-miss** (no chat-FAIL). Realized as **two passes** (§4.3): Pass A verbatim (PASS), Pass B a separate budgeted whole-body judge (SUPPORTED) — because a single locate-then-verify loop cannot reach the paraphrase judge. (Corrected 2026-06-30 after the Task-4 review showed the single-pass sketch could deliver only the PASS tier; maintainer chose to build the real SUPPORTED pass rather than descope to verbatim-only + DE.) Attributed-FAIL deferred to DE-370.
- **Migration:** none — `MessageToolSource.source_kind` is unconstrained `String(32)`; `message_authority_citations` (method CHECK already allows `exact_match`/`tolerant_match`/`paraphrase_judge`) + `authority_text_cache` exist (mig 0064); `gate.py`/`ledger.py` already bucket authority statuses.
