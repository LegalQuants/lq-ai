# ADR 0021 — Content-source registry & free-source expansion (WS-E)

**Status:** Accepted (2026-06-29) — maintainer-accepted (PR #241; the four design forks settled with the maintainer 2026-06-29). Implementation PRs (WS-E PR1+) carry **security review** per CODEOWNERS (the `gateway/**` egress boundary, the `api/app/autonomous/**` governance chokepoint, and a new external-egress surface).

**Relates to:** [ADR 0014](0014-gateway-egress-boundary-for-tool-providers.md) (the gateway is the only egress boundary for tool providers — WS-E adds sources *on* this class, never a second egress path), [ADR 0015](0015-governed-tool-calling-model.md) (the closed-set governed tool-calling model — the new retrieval intent is one closed member with model-generated/handler-validated args), [ADR 0016](0016-transparency-and-governance-invariants.md) (P3 no-raw-payload; P6 one governance path), [ADR 0018](0018-citation-ledger-and-fiduciary-grade-output.md) (the citation ledger + fiduciary gate that fetched authority must flow into), [ADR 0020](0020-governed-agentic-legal-matter-sessions.md) (the agentic loop whose planner gains a source-parameterized retrieval intent), and the [fiduciary-grade mini-PRD](../proposals/fiduciary-grade-agentic-legal-work.md) WS-E. Realizes **PRD §3.6** (the deferred Research surface) and **DE-344** (per-provider external-tool cost model).

---

## Context

WS-E is the milestone's "authoritative content" workstream. The thesis (mini-PRD §1.2): LQ.AI does **not** own a Westlaw-scale corpus. Operators **bring their own** licensed sources through the existing tool-provider / MCP-client model, and we **expand free authoritative sources**. Today CourtListener is the only wired source, and it is itself **operator-key-gated** (BYO CourtListener token) — "free" means "no LQ.AI-side licensing cost," not "turnkey."

Two concrete gaps:

1. **No registry.** The agentic planner (ADR 0020) and the chat tool-loop cannot *reason over* which authoritative sources exist, their jurisdiction/coverage, or their egress tier. `retrieve_caselaw` is hardwired to the CourtListener provider type (`research.service._resolve_provider()` filters `type == "courtlistener"`, `service.py:48-67`); there is no source-parameterized retrieval and no source metadata the planner can consult.
2. **R4 is a no-op for external tools (DE-344).** `estimate_tool_cost` returns `Decimal("0")` for `retrieve_caselaw` / `call_mcp_tool` (`cost.py:44-84`), so the R4 economic brake does not throttle external calls. The moment WS-E adds a *metered* source, R4 must actually bound spend.

The free sources to expand to (PRD §3.6): **GovInfo** (US federal — USC, CFR, Federal Register, bills), **SEC EDGAR** (US corporate filings), **EUR-Lex** (EU legislation + caselaw). All are free-of-licensing-cost; none are caselaw in the CourtListener sense (statutes, regulations, filings) — so they exercise content types the current caselaw-specific cache (`ResearchClusterMetadata`/`ResearchOpinionMetadata`, `research.py`) and the caselaw verifier (`caselaw.py`) do not model.

This ADR pins: where the registry lives, how the closed-set planner targets multiple sources, how non-caselaw fetched authority becomes citable in the fiduciary ledger, and the DE-344 cost model — phased so the registry + first free source + the cost model land before breadth.

## Decision drivers

1. **One egress boundary (ADR 0014).** New sources are tool-providers *on the existing gateway class*. The backend never calls a source directly; secrets/auth/allowlist/rate-limit stay gateway-side. WS-E adds no second egress path.
2. **One governance path + one ledger (ADR 0016 P6 / 0018).** Fetched authority flows through the *existing* citation cascade, ledger, and fiduciary gate — reuse, not a parallel verifier per source. This is the milestone's recurring north star.
3. **Closed-set, deterministic governance (ADR 0015).** The planner picks from a fixed `ToolIntent` enum; source/op selection is model-generated **args** validated by the handler against the registry — never open function-calling.
4. **Honest, conservative posture (PRD §1).** A source the operator has not configured (no key, disabled, over budget) degrades honestly — the planner is told it is unavailable; nothing is fabricated. Free ≠ turnkey; the registry surfaces the BYO-setup reality.
5. **Anti-overclaiming on coverage.** The registry must not imply LQ.AI has comprehensive coverage. It enumerates *what is configured and reachable*, with jurisdiction/coverage stated plainly.

## Decisions

### D1 — Hybrid registry: gateway holds egress, backend holds content metadata

The content-source registry is **two layers joined at read time**:

- **Gateway layer (egress, ADR 0014):** each source is a `tool_providers` entry in `gateway.yaml` carrying transport/governance — `name`, `type`, `base_url`, auth (`api_key_env`/`api_key_encrypted`), `egress_tier`, `allowlist.hosts`, `rate_limit`, `anonymize_outbound`, **plus the new D4 cost fields**. The gateway remains the only holder of secrets and the only egress.
- **Backend layer (content semantics):** a backend registry — a **versioned config module** `api/app/research/registry.py` (a declarative table keyed by provider `type`) — holds the application-level metadata the planner reasons over and the adapter needs: `jurisdiction` (e.g. `us-federal`, `eu`), `coverage` (human string + structured tags: statutes/regulations/caselaw/filings), `content_type`, the **op set** the source supports, the **adapter** that translates the source's API shapes, and a default-`False` `enabled` gate. The backend joins its registry (keyed by `type`) with the gateway-discovered *enabled* providers (`list_tool_providers`) so the live registry is **the intersection**: a source is "available" only when both an operator has configured it in the gateway AND the backend ships an adapter for its type.

Rationale: transport/auth/tier/allowlist are egress concerns that belong in the gateway (and must not leak to the backend — `list_tool_providers` already strips them); jurisdiction/coverage/op-mapping/adapter logic is application semantics that belongs in the backend, versioned with the code that consumes it. Neither layer alone is correct (a gateway-only registry pushes content semantics into the egress boundary; a backend-only registry duplicates and drifts from the operator's actual config).

A read-only surface — `GET /api/v1/research/sources` (PRD §3.6) — exposes the joined registry (name, type, jurisdiction, coverage, enabled, egress_tier; **never** auth or cost-secret fields) for the planner, the UI, and operator diagnostics.

### D2 — One generic, registry-validated retrieval intent: `retrieve_authority`

Add a single closed-set member `ToolIntent.retrieve_authority` (granted in `Phase.analysis`, added to the WS-D `PLANNER_ALLOWLIST` so the agentic loop can choose it). Its args are **model-generated, handler-validated** (the ADR 0015 boundary, as used by WS-D PR1's `validate_action_args`): `{"source": <registry type/name>, "op": <op the source supports>, "args": {...}}`. The handler validates `source` against the live registry (D1) and `op` against that source's declared op set; an unknown/disabled source or unsupported op is a **non-fatal failed observation** (never an exception that escapes the governed path — the WS-D invariant #5 / PR1-C1 lesson).

`retrieve_caselaw` is **retained unchanged** for the CourtListener path that the WS-G treatment/citation-graph layer keys off (it has caselaw-specific cache + `get_citing_opinions` semantics). New sources route through `retrieve_authority`.

Rationale: a generic intent keeps `PHASE_GRANTS` and the planner allowlist **stable** as sources grow (no enum churn per source), stays closed-set, and loses no audit fidelity — `governed_tool_invocation` already records `provider`/`tool` on the `tool_call_log` row, so the audit names the concrete source+op even though the intent is generic. (Rejected: per-content-category intents — cleaner audit label but multiplies the closed set and the allowlist with every content type; extending `retrieve_caselaw` with a `source` param — conflates caselaw with statutes/filings and muddies the treatment path.)

### D3 — Non-caselaw authority becomes citable via the ephemeral-document pipeline (reuse the KB verifier)

Per PRD §3.6 ("fetched content runs through the document pipeline; citations work the same way as for uploaded files"): when `retrieve_authority` fetches a passage of authority (a statute section, a filing excerpt), the adapter **materializes the fetched text as an ephemeral `Document`** through the existing ingestion pipeline, and cited quotes are verified by the **existing KB character-fidelity cascade** (`verification.py`) → `MessageCitation` rows → the ledger → the fiduciary gate. No per-source verifier; no per-source cache model.

Scoping and lifecycle (the open sub-questions, settled here):
- **Ephemeral + scoped, not in the user's KBs.** Fetched-authority Documents are **session/matter-scoped** and excluded from the user's normal KB lists/search — mirroring WS-D PR2's hidden session-owned chat pattern (a marker column + a list filter), so a fetched statute never pollutes a user's knowledge base. They ARE retrievable for the citation trace (the ledger entry points at the materialized Document's offsets).
- **Cache with a TTL** keyed by a stable source identity (e.g. `(source_type, external_ref)`) so repeated fetches of the same authority within the window reuse the materialized Document (reuse the WS-G 30-day-TTL pattern; statutes/regs are stable, so a generous TTL is fine — exact value is a spec detail).
- **Provenance always.** Every `retrieve_authority` call also writes a `MessageToolSource` row (`source_kind` = the registry content-type, provider/tool from the call) — the unverified provenance slot the ledger already routes (`ledger.py:114`), so even a non-quoted fetch is traceable.

Rationale: this is the milestone's reuse-not-fork principle applied to content — statutes/filings get the **same** char-fidelity guarantee as uploaded files and CourtListener caselaw, with one verifier. (Rejected: generalizing `ResearchClusterMetadata` into a discriminated model + a parallel `locate_passage` verifier — forks a second verification path and rewrites caselaw code; per-source cache models — proliferates tables + verifiers.) The CourtListener caselaw path stays on its dedicated cache because it additionally feeds the WS-G citation-graph/treatment layer; new sources have no such need.

> **Refinement (2026-06-29, maintainer — WS-E PR1 spec input).** On mapping the code, D3's literal mechanism ("persist an ephemeral `Document` → `MessageCitation`") collides with `MessageCitation.source_file_id` being NOT NULL — it would force ephemeral-`File` machinery (a `files.file_origin` marker, a `storage_path` sentinel, a download-endpoint guard, and web file-listing exclusion). The **existing caselaw path already verifies fetched legal text** the lighter way: the *same* shared `verify()` core run against an **in-memory target** (`caselaw.opinion_target`, no `Document` row), with results in a dedicated `MessageCaselawCitation` table. Statutes/filings are structurally identical. **Decision:** D3 is realized by **mirroring the caselaw path** — an in-memory authority verification target + ONE new `message_authority_citations` table (for ALL fetched-authority sources, not per-source) routed into the ledger via a new FK slot, plus a small `(source_type, external_ref) → text` TTL cache for cross-turn reuse. This preserves D3's *intent* (reuse the shared verifier core; one ledger; one gate; reuse-not-fork) while dropping the ephemeral-`File`/storage machinery. The "reuse the KB verifier" wording above means "reuse the shared `verify()` core," which the in-memory-target path does exactly.

### D4 — DE-344 cost model: a configured rate on the `tool_providers` entry

Add optional `cost_per_call` (and `cost_per_unit` + a `unit` label, for usage-metered sources) to the gateway `tool_providers` entry. The backend caches these alongside the provider tier (extend the `resolve_provider_tier` cache in `governance.py:67-95`), and `estimate_tool_cost` returns the configured projection for `retrieve_authority` / `retrieve_caselaw` / `call_mcp_tool` instead of `Decimal("0")`. **Free sources omit the field → $0 → R4 stays a no-op for them** (correct: a free source should not be throttled). The **realized** cost is recorded on `tool_call_log.cost_usd` via the handler's `ToolResult.cost_usd` (the column + write path already exist, `governance.py:271/300`) — populated from the gateway response's cost field when the adapter parses one, else the configured estimate.

Rationale: the PRD leans this way ("a configured cost-per-call or cost-per-unit on the gateway `tool_providers` entry"); it's the simplest correct first step, requires no realized-cost bootstrap (unlike a rolling average), and the plumbing (`cost_usd` on the log + R4's single-estimate forwarding) is already in place. (Rejected: rolling-average estimator — chicken-and-egg before any metered source; per-op cost table — premature expressiveness.) This makes the R4 economic brake real for external tools by construction, satisfying DE-344's "when to ship."

### D5 — Honest unavailability + conservative coverage

A source in the backend registry but **not** enabled/configured in the gateway (no operator key, disabled, or absent) is surfaced to the planner as **unavailable with a reason** (not silently dropped) and is never selectable by `retrieve_authority` (the handler rejects it as a non-fatal failed observation, D2). `GET /api/v1/research/sources` reports each source's `enabled`/availability honestly. The registry's `coverage` strings state scope plainly and never imply comprehensive coverage (anti-overclaiming, decision driver 5; consistent with the launch-docs honesty posture, DE-365).

### D6 — Phased build: registry + cost model + first source, then breadth

- **WS-E PR1 — the registry, the intent, the cost model, and the FIRST free source.** D1 backend registry + `GET /research/sources`; D2 `retrieve_authority` intent + handler + registry validation + `PLANNER_ALLOWLIST` grant; D3 ephemeral-document materialization + KB-verifier reuse for fetched authority (the citable path); D4 cost fields + real `estimate_tool_cost`; and **GovInfo** as the first source (US federal statutes/regs — the most natural complement to CourtListener caselaw; free, well-documented API). All behind a per-source `enabled` flag (default off). Security-gated.
- **WS-E PR2 — breadth.** Add **SEC EDGAR** and **EUR-Lex** adapters on the same registry + intent + verify path, behind flags (satisfies the mini-PRD's "≥2 new free sources live behind feature flags," with GovInfo making three). Any planner/UI polish for multi-source selection.

(The exact first/second source ordering is a spec detail; GovInfo-first is the recommendation. SEC EDGAR requires only a descriptive `User-Agent` (no key) and is high-value for transactional practice; EUR-Lex extends jurisdiction to the EU.)

### D7 — Reuse, never bypass, the governance + output rails

Every `retrieve_authority` call goes through `guarded_tool_call` → R5/R6/R4 (now cost-real, D4) → `governed_tool_invocation` → the gateway. Fetched authority flows through the existing ingestion + citation cascade + ledger + gate (D3). No new egress path, no new ledger, no new verifier, no second governance path. WS-E adds **sources and a cost model**, not parallel machinery.

## Consequences

- The agentic matter session (WS-D) can now plan over **multiple jurisdictions and content types** — "find the controlling statute and the SEC filing language" — with every fetched passage char-fidelity-verified and ledger-backed, exactly like caselaw and uploaded files.
- The R4 economic brake becomes **real** for external tools; a metered source (a future paid MCP or a CourtListener rate-tier overage) is throttled and its realized cost recorded.
- Operators get an honest, inspectable map of configured authoritative sources (`GET /research/sources`) — and the BYO-setup reality (keys, enablement) is explicit, not hidden.
- New surface to secure: each adapter parses an external API response into ingested text (SSRF/allowlist stay gateway-side per ADR 0014; the adapter is parse-only). Ephemeral-document scoping must be airtight so fetched authority never leaks into a user's KBs or another matter.
- Cost: WS-E does not ship a curated corpus and does not ship anyone's licensed content — it ships the *registry + adapters + cost model* and free-source connectors. Licensed corpora remain a BYO-MCP path.

## Open questions (resolve in the WS-E PR specs/plans)

- **Ephemeral-document model & TTL (PR1).** Exact storage/marker for session/matter-scoped fetched-authority Documents (a marker column + KB-list filter à la WS-D PR2's hidden chat vs a dedicated ephemeral-KB), the cache key `(source_type, external_ref)`, the TTL value, and the cleanup/expiry path.
- **Adapter contract (PR1).** The interface every source adapter implements (op → gateway `call_tool` args; response → {citable text to ingest, provenance fields, external_ref}); how a source declares its op set and citation-format to the registry.
- **GovInfo op surface (PR1).** Which GovInfo collections/ops PR1 exposes (USC / CFR / Federal Register / bills) and their arg schemas; the citation/identifier scheme for a statute/reg section.
- **`retrieve_authority` arg validation (PR1).** The `validate_action_args` extension for the new intent (source/op/required-args per the registry) — reuse WS-D PR1's boundary-validation pattern so a bad source/op is a non-fatal failed observation.
- **Realized-cost parsing (PR1/PR2).** Whether/which source responses carry a cost field the gateway adapter surfaces into `ToolResult.cost_usd`, vs recording the configured estimate as the realized cost.
- **Planner source-awareness (PR2).** How much of the registry (jurisdiction/coverage) is injected into the planner prompt so it picks the *right* source for a matter, vs leaving source choice to the synthesis — and the P3 budget for that.
