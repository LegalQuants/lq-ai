# Mini-PRD: Fiduciary-grade agentic legal work — LQ.AI's transparent answer to closed legal-AI platforms

> **Status:** Proposed — strategic PRD for the milestone *after* [legal-research + MCP](legal-research-and-mcp.md). Forks resolved with the maintainer 2026-06-24 (see §Decisions). Inventory **reconciled against a codebase pass 2026-06-24** (see §Reconciliation). Phase 1's centerpiece decision is pinned in [ADR 0018 — The Citation Ledger & fiduciary-grade output](../adr/0018-citation-ledger-and-fiduciary-grade-output.md) (**accepted 2026-06-24**); remaining **(ADR needed)** pieces must be promoted before their workstream starts. Phase 1 task-level plan: see §Phase 1 — detailed design & PR decomposition.
> **Effort:** XL (a multi-milestone program; phased — see §Roadmap).
> **Contributor profile:** Backend engineers across `api/` (FastAPI + LangGraph autonomous layer + citation engine) and the `gateway/` security boundary; one `web/` (SvelteKit) contributor for the ledger surface. Read [PRD §1.3](../PRD.md#13-transparency-as-a-founding-principle), [§1.8](../PRD.md#18-security-posture), and ADRs [0013](../adr/0013-autonomous-layer-design-influences.md)/[0014](../adr/0014-gateway-egress-boundary-for-tool-providers.md)/[0015](../adr/0015-governed-tool-calling-model.md)/[0016](../adr/0016-transparency-and-governance-invariants.md) first.
> **Mentor:** Maintainer (via PR review); security review required for the egress/ingress boundaries and the autonomous guard.

## What this is

In May 2026 Thomson Reuters and Anthropic [announced](https://www.thomsonreuters.com/en/press-releases/2026/may/thomson-reuters-and-anthropic-expand-partnership-to-connect-claude-with-cocounsel-legal) the next generation of **CoCounsel Legal**: a legal-AI platform rebuilt on Anthropic's Claude Agent SDK that "plans, selects tools, retrieves authoritative content, and adapts mid-workflow," paired with an MCP integration that lets lawyers "move seamlessly between general-purpose AI and citation-grounded legal work." Its pitch rests on three pillars: **authoritative content at scale** (1.9B Westlaw/Practical Law documents, 1.4B KeyCite validity signals), a **patent-pending citation ledger** that "makes every source traceable in one click," and **trust as a property of the system** — "built into the architecture and verifiable at every step."

This PRD scopes LQ.AI's response. The thesis: **LQ.AI already has most of the architecture CoCounsel describes** (a governed agentic layer, a single audited egress boundary, an MCP subsystem, a citation engine, and a transparency posture promoted to ADRs). What's missing is mostly *productization and surfacing*, not foundational invention. And LQ.AI's answer is differentiated on the one axis CoCounsel structurally cannot match: **CoCounsel's trust is asserted ("trust us — 2,600 experts, a patent-pending ledger"); LQ.AI's trust is demonstrable** — read the skill, inspect the ledger, run it on your own data in your own environment. We replicate the *capability*; we do not clone the *closed, proprietary-corpus model*.

## Decisions (forks resolved with the maintainer, 2026-06-24)

1. **Phase it — agentic platform first, MCP-server ingress as a later phase.** CoCounsel's literal headline is the inbound MCP integration (use it from inside Claude.ai/Desktop). LQ.AI is MCP-*client*-only today. We build the next-gen-platform half first (Phases 1–2) and add the **MCP-server ingress** as Phase 3. *(Rejected: ingress as the v1 centerpiece — too much new security surface up front; in-app-only — drops the "use it from Claude" parity entirely.)*

2. **Authoritative content = BYO-connector + free sources.** LQ.AI will not own a Westlaw-scale corpus. Operators **bring their own licensed sources** (including a Westlaw/CoCounsel MCP server *if they are licensed for it*) through the existing tool-provider / MCP-client model, and we **expand free authoritative sources** (CourtListener today — itself gated on an **operator-supplied CourtListener API token** (BYO key), not turnkey; GovInfo, EUR-Lex, SEC EDGAR are the deferred [Research surface (PRD §3.6)](../PRD.md#36-research)). *(Rejected: shipping first-class proprietary connectors as a core deliverable — operators add those via the BYO path; attempting an owned curated corpus — off-mission.)*

3. **Validity/treatment = a transparent, derived layer (not an editorial one).** CoCounsel's KeyCite is 1.4B *editorial* validity signals you must trust. LQ.AI instead **derives** treatment ("is this still good law" — followed / distinguished / criticized / questioned / overruled) from the **citation graph** (CourtListener's citing-opinions relationships) plus an **LLM-judge over the citing passages**, reusing the citation engine's existing judge machinery. Every signal is **labeled "derived, not editorial," confidence-scored, and traceable** back to the specific citing cases in the ledger — so the *reasoning* is inspectable, which an editorial flag never is. This is the transparency wedge applied to validity. *(Rejected: deferring validity entirely; cloning an opaque editorial signal.)* **(ADR needed — methodology + how the platform avoids overclaiming authority.)**

4. **Posture = LQ.AI-native differentiation.** Match the capability bar, but **lead with the open / transparent / self-hosted / BYO wedge.** The citation ledger, the *derived-and-inspectable* validity layer, and forkable skills are the headline — not a corpus we don't have. *(Rejected: literal feature-parity-first; lean-MVP-first — the differentiation IS the product, so it ships from the start.)*

5. **External/caselaw citations are character-verified in v1, not just provenance-tracked.** Today only KB-*document* citations run through the cascade; external sources are "sources consulted" (retrieval provenance), explicitly not quote-verified. v1 fiduciary-grade **requires** running the cascade over external sources too — achieved by *materializing* the fetched authoritative-source text as a citable source and verifying quotes against it (the shared substrate for [DE-279](../PRD.md#de-279) resolution + [DE-280](../PRD.md#de-280) content-accuracy). *(Rejected: ship the ledger fast with external sources as provenance-only and defer quote verification — the maintainer chose the more faithful, conservative path.)* Pinned in **ADR 0018 D2/D3**.

6. **The ledger is a thin *referencing* table, not a snapshot or a view.** `citation_ledger_entry` references the existing `message_citations` / `message_tool_sources` / `work_product` / materialized-source rows by id + offset and adds a reserved treatment slot — no content duplication, P3-preserving, re-run-surviving. *(Rejected: read-model/view only — no durable treatment slot, no re-run survival; denormalized snapshot — duplicates content, drifts.)* Pinned in **ADR 0018 D1**.

7. **Plan depth: Phase 1 deep now; Phases 2–3 at roadmap resolution.** Write ADR 0018 + the full Phase-1 task plan (WS-A/B/C); keep WS-G (validity) and WS-F (ingress) at roadmap resolution behind their own ADR-needed gates, since they depend on Phase-1 decisions. *(Rejected: spec all three phases up front — Phases 2–3 would be provisional on unmade Phase-1 calls.)*

## The parity target (decomposed)

The announcement is **two** deliverables plus three pillars:

| CoCounsel element | What it is |
|---|---|
| **(D1) Next-gen platform** (Claude Agent SDK, GA summer 2026) | "Plans, selects tools, retrieves authoritative content, and adapts mid-workflow." Plain-language matter → pursue inquiry → draft with citations → validated references in "fiduciary-grade work product." |
| **(D2) MCP integration** (shipped) | CoCounsel exposed to Claude (claude.ai / Desktop) so lawyers move between general-purpose AI and citation-grounded legal work "from either working environment." |
| **(P1) Authoritative content at scale** | 1.9B Westlaw/Practical Law docs; 1.4B KeyCite validity signals; 2,600 experts curating. "Not a database to be searched… the foundation on which it reasons." |
| **(P2) Citation ledger** (patent-pending) | Tracks "every source the agent brings into context and the specific passages it reads," traceable in one click. "Verification part of the system's architecture rather than an afterthought." |
| **(P3) Trust as a system property** | "Trust in AI is a property of the system itself… verifiable at every step." Plus privacy: no third-party-model training, no data beyond the customer's environment. |

## What LQ.AI already has vs. what's net-new

> **Reconciliation — verified 2026-06-24 against `main`** (four-front codebase pass). Every "have/partial" call below is confirmed present in code (file:symbol evidence on file). The pass also sharpened four points the table understated — recorded in §Reconciliation immediately after the table.

| CoCounsel element | LQ.AI today | Net-new work |
|---|---|---|
| **D1 agentic platform** | **Partial → strong.** Autonomous layer (M4): `Phase`/`PHASE_GRANTS`/`guarded_tool_call` with R5→R6→R4 brakes (`api/app/autonomous/`); governed chat tool-loop (ADR 0015 / PR5 — substrate merged, chat loop PR5b next). | The **plain-language matter intake → matter-scoped agentic session** that spans research *and* drafting in one flow, and **drafting with inline ledger-backed citations** as the output. Productize, don't reinvent. |
| **D2 use-from-Claude** | **Missing.** LQ.AI is an MCP *client* (connects outward); no inbound MCP server. | **MCP-server ingress** — a new inbound boundary (Phase 3, **ADR needed**). |
| **P1 authoritative content** | **Partial.** Gateway tool-provider class (ADR 0014); CourtListener wired (WS3) but **gated on an operator-supplied CourtListener token** (the only "free" source today, and only with the operator's own key); MCP client lets operators connect their own sources (WS2). | Expand free sources (GovInfo/EUR-Lex/SEC EDGAR — the deferred [Research surface, PRD §3.6](../PRD.md#36-research)); a **content-source registry** so the agent knows which authoritative sources exist, their jurisdiction + egress tier; the BYO-licensed-corpus framing. |
| **P2 citation ledger** | **Partial — the pieces exist, the artifact doesn't.** Citation engine cascade (exact→tolerant→paraphrase→ensemble); `tool_call_log` + `tool_egress_log` (counts/types only); PR6/WS5 plans external-source citation provenance ("source-kind" modeling, [C4](legal-research-and-mcp.md)). | The **Citation Ledger as a first-class, user-facing artifact** — the centerpiece of this PRD (**ADR needed**). |
| **P3 trust-as-architecture** | **Have — and ahead.** ADRs 0013–0016 already make this binding: single audited egress boundary, closed-set governance, counts-not-payloads audit, the [transparency invariants](../adr/0016-transparency-and-governance-invariants.md) with CI gates. | Surface it as product: the ledger + inspectable skills + a "how this answer was produced" view. LQ.AI's open posture beats an asserted-trust claim. |
| **validity/treatment (KeyCite)** | **Missing.** The citation engine verifies a citation *exists / is accurately quoted*, not whether it's *still good law*. The pieces to derive it exist: CourtListener citing-opinions data + the engine's LLM-judge. | **A transparent, derived validity layer (WS-G)** per Decision 3 — net-new, populates the ledger's treatment slot, labeled "derived, not editorial." |

The headline finding: **the foundations are built.** This program is mostly about (a) turning the existing citation/provenance plumbing into a first-class ledger, (b) joining research + drafting into one agentic legal-work flow, (c) deriving a transparent validity layer from the citation graph + the engine's judge, and (d) — later — making LQ.AI reachable from Claude.

## Reconciliation (verified 2026-06-24 against `main`)

The codebase pass confirmed the inventory and the "foundations are built" thesis. Confirmed load-bearing: the autonomous layer (`api/app/autonomous/`: `Phase`, `PHASE_GRANTS`, `guarded_tool_call`, the R5→R6→R4 brakes in `guard.py`); the chat tool-loop (`run_chat_tool_loop`, `ChatToolAllowlist`, per-turn cap, the `chat_pending_tool_call` confirmation gate) sharing **one** governance path with the autonomous layer (`governed_tool_invocation`); the citation cascade with a **reusable LLM-judge behind a Protocol** (`api/app/citation/verification.py`) and char-precise offsets end-to-end; the source-kind model `MessageToolSource`; counts-not-payloads audit logs enforced by the ADR 0016 P3 tripwire (`api/tests/test_transparency_invariants.py`); the web provenance primitives (`ProvenancePill`, `ToolSourcesPanel`, `M2Citations`). The pre-req (PR5b chat tool-loop + PR6/WS5 C4 source-kind provenance) is **merged to `main`**, so Phase 1 is unblocked.

Four sharpenings the table understated — each now reflected in the Phase 1 plan and ADR 0018:

1. **The R5→R6→R4 brakes are autonomous-only.** The chat tool-loop enforces allowlist + per-turn cap + confirmation, but *not* R4/R5/R6. WS-D inherits the brakes only because it is built on the autonomous layer — correct, but the plan states it explicitly rather than implying chat already has them.
2. **R4 (economic brake) is a no-op for external tools today.** `estimate_tool_cost` returns `Decimal(0)` for `retrieve_caselaw` / `call_mcp_tool` ([DE-344](../PRD.md#de-344)). The moment WS-E adds *metered* sources — and as soon as WS-A verifies quotes against long opinions (inference cost) — R4 must actually bound spend. A real dependency for WS-A's cost ceiling and WS-E.
3. **`MessageToolSource` is populated for case-law only** (`search_case_law` / `get_cluster`); generic-MCP results are [DE-350](../PRD.md#de-350). WS-A's ledger wants *every* tool-retrieved source, so **DE-350 is pulled in-scope for WS-A.**
4. **External/caselaw citations are not character-verified today** — the single largest Phase 1 scope lever. The cascade runs over *documents* (`documents.normalized_content` offsets); external sources are retrieval-provenance only (`docs/HONEST-STATE.md` §5.5). Decision 5 + ADR 0018 D2 resolve this by **materializing** fetched source text as a citable source so the existing cascade verifies external quotes unchanged — the shared substrate for DE-279/DE-280.

## Workstreams

### Phase 1 — The Citation Ledger + fiduciary-grade output (the centerpiece)

**WS-A — Citation Ledger artifact (ADR needed).** A first-class, matter- and turn-scoped record of *every source the agent brought into context and the specific passages it read*, traceable in one click. Built on the existing citation cascade and the WS5 source-kind modeling (C4). Each ledger entry: source identity (document / case cluster+opinion / external tool result / KB chunk), the passage(s) read (char-precise where available), verification status from the cascade, retrieval provenance (provider, tier, `retrieved_at`), and a reserved **treatment/validity** slot. "Verification part of the architecture" means the citation cascade runs automatically over *every* tool-retrieved source, not just document citations. *Counts/types-and-pointers, never raw payloads in the audit layer (ADR 0016 P3); the ledger references content by id/offset.* The ADR pins: data model, relationship to `tool_call_log`/`tool_egress_log`/the citation engine, retention, and the one-click "trace this source" read model.

**WS-B — Fiduciary-grade work product.** Drafted output (memo / answer / clause) where **every assertion's citation is ledger-backed** and verified through the cascade. Builds on `work_product` + autonomous artifacts + skills. A draft is "fiduciary-grade" iff every citation resolves to a ledger entry with a passing verification status; un-verifiable claims are flagged, not silently emitted (the conservative-posture rule, PRD §1).

**WS-C — Ledger UI ("how this answer was produced").** The `web/` surface: the one-click source trace, provenance pills (PR6/WS5 builds the primitives), per-source verification status, and the matter-scoped ledger view. This is where LQ.AI's transparency posture becomes a visible product, contrasted with an opaque "trust us" claim.

### Phase 2 — Agentic legal-matter workflow

**WS-D — Plain-language matter intake → agentic session.** "Describe a matter in plain language and have LQ.AI pursue the right inquiry." A matter-scoped agentic session built on the autonomous layer that plans, selects from the **operator-enabled** tool allowlist (closed-set, ADR 0015 — *not* open function-calling), retrieves authoritative content, adapts mid-workflow, and produces a WS-B work product with a WS-A ledger. Reuses `PHASE_GRANTS` + the R5→R6→R4 brakes; no new brake machinery.

**WS-E — Content-source registry + free-source expansion.** A registry of available authoritative sources (jurisdiction, coverage, egress tier, enabled flag) the planner can reason over, plus new free tool-providers (GovInfo, EUR-Lex, SEC EDGAR — the deferred [Research surface, PRD §3.6](../PRD.md#36-research)) on the ADR-0014 tool-provider class. Note even CourtListener today is operator-key-gated (BYO token), so "free source" means "no LQ.AI-side licensing cost," not "zero operator setup." Operators connect licensed corpora (incl. a Westlaw/CoCounsel MCP if licensed) through the existing MCP-client model — LQ.AI never ships someone else's licensed content.

**WS-G — Transparent validity/treatment layer (ADR needed).** The KeyCite analog, done LQ.AI's way: **derive** a citation's treatment rather than assert it. Inputs: the **citation graph** (CourtListener citing-opinions relationships — which later cases cite this one) + an **LLM-judge** over each citing passage (reusing the citation engine's stage-3/4 judge), classifying treatment (followed / distinguished / criticized / questioned / overruled / superseded) with a confidence score. Output: a treatment summary that **populates the WS-A ledger's treatment slot**, every signal **labeled "derived, not editorial,"** linked to the exact citing cases and passages it rests on, so a lawyer can audit *why* a case is flagged. Where a connected source (a licensed provider / MCP) supplies its own editorial treatment, the ledger records that *alongside* the derived signal, attributed to its source. The ADR pins: methodology, confidence calibration, the anti-overclaiming posture (LQ.AI surfaces signals + reasoning; it does not claim editorial authority), and refresh/staleness of the citation graph. The citing-passage judge fan-out is the largest cost lever in the milestone and the first proving ground for **[DE-360](../PRD.md#de-360)** (gateway-native, transparency-preserving cheap→capable escalation routing).

### Phase 3 — MCP-server ingress (use LQ.AI from Claude)

**WS-F — MCP-server ingress boundary (ADR needed).** Expose LQ.AI as an MCP server so a user in Claude.ai / Claude Desktop can call LQ.AI's research / skills / ledger tools — the inbound counterpart to ADR 0014's egress boundary. This is a **new ingress boundary** (auth, scoping, rate-limiting, audit) and challenges the single-boundary mental model, so it needs its own ADR: where the server lives, how it authenticates an external Claude session to an LQ.AI user/matter, what's exposed (read-only research + ledger first; never destructive tools un-gated), and how every inbound call lands in the same audit/ledger as in-app calls. Phased last precisely because it is the largest new security surface.

## Roadmap (phased)

| Phase | Workstreams | Depends on | Security review | The bar |
|---|---|---|---|---|
| **Pre-req** | Finish the legal-research+MCP milestone | — | per that milestone | PR5b chat tool-loop + PR6/WS5 external-source citation provenance (C4) merged — WS-A builds directly on the source-kind model. |
| **Phase 1** | WS-A ledger (ADR), WS-B work product, WS-C UI | Pre-req | **Yes** (ledger touches audit + citation) | Every tool-retrieved source auto-runs the citation cascade and lands in a one-click-traceable ledger; a draft is gated "fiduciary-grade" only when all citations are ledger-backed. |
| **Phase 2** | WS-D agentic matter flow, WS-E source registry + free sources, WS-G validity layer (ADR) | Phase 1 | Yes (autonomous guard; WS-G methodology) | Plain-language matter → planned, closed-set, multi-source agentic session → WS-B output + WS-A ledger; ≥2 new free sources live behind feature flags; derived treatment signals populate the ledger, labeled "derived, not editorial," with one-click trace to the citing cases. |
| **Phase 3** | WS-F MCP-server ingress (ADR) | Phase 1 (ledger) | **Yes** (new boundary) | External Claude can reach LQ.AI read-only research + ledger; every inbound call authenticated, scoped, tier-checked, and audited identically to in-app calls. |

## New ADRs this program needs

- **[ADR 0018 — The Citation Ledger & fiduciary-grade output](../adr/0018-citation-ledger-and-fiduciary-grade-output.md)** (WS-A/B) — **accepted 2026-06-24**: the thin referencing data model (D1), external-source quote-verification via materialized citable sources (D2), the fiduciary-grade gate (D3), the one-click trace read model (D4), the no-raw-payload guarantee (D5), the reserved treatment slot (D6), and retention (D7). Phase 1 code PRs (P1-A1+) carry security review per CODEOWNERS.
- **ADR — Transparent validity/treatment layer** (WS-G): the derive-don't-assert methodology, the citation-graph + LLM-judge pipeline, confidence calibration, the anti-overclaiming posture, and how derived vs. connector-editorial signals coexist in the ledger.
- **ADR — MCP-server ingress boundary** (WS-F): the inbound counterpart to ADR 0014 — auth, scoping, exposure policy, rate-limiting, and unified audit/ledger.
- *(Possible)* **ADR — Authoritative-source registry & tiering**, if WS-E's registry warrants structural status beyond config.

## Phase 1 — detailed design & PR decomposition

Phase 1 = WS-A (ledger) + WS-B (fiduciary-grade gate) + WS-C (UI), all pinned by ADR 0018. Decomposed into reviewed increments per the [build loop](../../CLAUDE.md) (implement → spec review → code review → security review where flagged → merge). Each touches the citation/audit/content surface, so **most carry security review** per CODEOWNERS.

### Sequencing

```
P1-0  ADR 0018 acceptance (maintainer + security)        ── gate, no code
  └─ P1-A1  external quote-verification core (riskiest)   ── sec review
       └─ P1-A2  citation_ledger_entry table + assembly   ── sec review
            ├─ P1-A3  ledger read API + one-click trace   ── sec review   ┐ parallel
            └─ P1-B1  fiduciary-grade gate                                 ┘
                 └─ P1-C1  matter-scoped ledger UI + trace ── web
```

### PRs

**P1-0 — ADR 0018 acceptance (gate, no code).** Maintainer + security accept the ledger data model, the materialized-source approach (a new content store derived from egress), and the P3 stance. Resolves ADR 0018's open questions (`citable_source` vs. extending `documents`; pinned-reference GC; gate surfacing granularity; cost ceiling). **Gates all code below.**

**P1-A1 — External-source quote-verification core (WS-A, ADR 0018 D2).** The single largest scope item. Materialize fetched authoritative-source text (the CourtListener opinion the gateway already returns via `get_cluster`/`get_cases`) as a citable source — normalized content + chunk offsets, matter-scoped, non-anonymized public flag — and run the **existing** cascade (`verify_exact` → `verify_tolerant` → `verify_paraphrase`) over quotes attributed to it. Shared substrate with [DE-279](../PRD.md#de-279) (resolution) and [DE-280](../PRD.md#de-280) (content-accuracy = the paraphrase tier).
- *Files:* `api/app/models/` (citable_source model + migration), `api/app/citation/` (external-source verify entry reusing the cascade), `api/app/chat/tool_loop.py` (materialize on external-source return), tests. **Security review.**
- *Acceptance:* a chat answer quoting a CourtListener opinion yields a verified citation (`exact`/`tolerant`) against the materialized text; an invented quote resolves `failed`/`unverified`; the materialized source is retrievable for trace; long-opinion verification stays within a pre-flight cost bound (touches [DE-344](../PRD.md#de-344)).

**P1-A2 — `citation_ledger_entry` table + assembly (WS-A, ADR 0018 D1/D5).** The thin referencing table; assembly at turn finalize (one entry per *(turn, source)* referencing `message_citation_id` / `message_tool_source_id` / `citable_source_id`, mirroring `verification_status` + `confidence` + provenance, `treatment_id` null). Pull in **[DE-350](../PRD.md#de-350)** so generic-MCP sources also get entries (not just case-law). Add the table to the P3 no-raw-payload tripwire.
- *Files:* model + migration, assembly in the chat finalize path, `api/tests/test_transparency_invariants.py` (extend the scanned set), tests. **Security review.**
- *Acceptance:* every source brought into a turn yields a correctly-referenced entry with mirrored status; tripwire stays green (no payload columns); DE-350 MCP sources covered.

**P1-A3 — Ledger read API + one-click trace (WS-A, ADR 0018 D4).** `GET /api/v1/chats/{chat_id}/ledger` (turn/matter-scoped) + per-entry trace, joining citations / tool-sources / citable-source. **P10:** OpenAPI sketch, `IMPLEMENTED_ROUTES`, the pinned path-count + `EXPECTED_PATHS` bump, `docs/db-schema.md`.
- *Files:* `api/app/api/ledger.py` (or extend `chats.py`), schemas, `docs/api/backend-openapi.yaml`, `docs/db-schema.md`, tests (handler + integration + openapi conformance + endpoints guard). **Security review.**
- *Acceptance:* endpoint returns the matter/turn ledger resolved to source + passage(offsets) + status + provenance; conformance + collision guards pass.

**P1-B1 — Fiduciary-grade gate (WS-B, ADR 0018 D3).** Compute the gate at finalize — PASS `{exact, tolerant}`; SUPPORTED `{paraphrase, ensemble}` labeled distinctly; FAIL `{unverified, failed}` flagged inline, never silently dropped (conservative posture). Record the verdict against `work_product`; include in the P9 export. Reuse `TOLERANT_MATCH_THRESHOLD` / aggregation ([DE-281](../PRD.md#de-281)).
- **Split (maintainer-approved 2026-06-25):** **P1-B1 is gate-only** — deterministic over existing ledger statuses, **no new egress, no cost**. The verdict + per-tier counts land on a new 1:1 `work_product_fiduciary_gate` table (metadata-only → P3 tripwire). It also fixes a P1-A2 assembler mislabel (unverified KB `message_citations` were labeled `"verified"`) so FAIL is flagged honestly for KB quotes. Caselaw-FAIL persistence and the **paraphrase tier** are deferred.
- **P1-B1b — Caselaw paraphrase judge, SUPPORTED-only (WS-B).** Wires [DE-280](../PRD.md#de-280)'s opinion-scale content-accuracy judge as the **SUPPORTED/paraphrase tier** for caselaw: a whole-opinion judge over a dropped (non-verbatim) blockquote that the judge finds faithfully supported persists a `paraphrase_judge` row → gate `supported_only`. Per-message cost pre-flight ([DE-344](../PRD.md#de-344)) bounds egress. **Additive-only — writes no FAIL/unverified rows, never flips a turn to `flagged`.** New gateway egress + cost → security review; high-fan-out cost lever is [DE-360](../PRD.md#de-360)'s target. *(Scope corrected 2026-06-25: caselaw FAIL persistence moved to P1-B1c — see below.)*
- **P1-B1c — Caselaw FAIL + passage→opinion attribution (WS-B).** Safe fabrication-flagging for caselaw: a parser maps each blockquote to its `### Case Name` H3 heading and matches it to a consulted opinion, so the whole-opinion judge runs against the **attributed** opinion only; a judge-rejected quote persists a `verified=False` FAIL row (gate → `flagged`) **without** false-positives on legitimate non-caselaw blockquotes (a statute, a KB quote). Split out of B1b (2026-06-25) because no reliable per-passage attribution exists today — judging against *all* consulted opinions would mis-flag good drafts, the worst failure for a fiduciary tool. Pairs with the deferred [DE-279](../PRD.md#de-279) case-cite resolution. New gateway egress → security review.
- *Files:* chat finalize path, `work_product_fiduciary_gate` table + model (migration `0059`), gate module, P3 tripwire, tests.
- *Acceptance:* all-PASS draft → `fiduciary_grade`; one unverifiable claim → `flagged` + inline flag; verdict recorded + exported; "supported, not verbatim" never presented as a verbatim quote.

**P1-C1 — Matter-scoped ledger UI + one-click trace (WS-C).** A ledger view (matter/turn) reusing `ProvenancePill` / `ToolSourcesPanel` / `M2Citations`; per-source verification status; "trace this source" → exact passage + offsets; verbatim-vs-supported rendered distinctly; a fiduciary-grade badge reflecting the gate.
- *Files:* `web/src/lib/lq-ai/components/` (Ledger view + trace), `MessageBubble.svelte` integration, Vitest + Playwright.
- *Acceptance:* a matter's ledger renders; clicking a source opens the exact passage; verbatim vs supported visually distinct; unverified flagged; the badge reflects the gate.

### DEs pulled in-scope / dependencies

- **[DE-350](../PRD.md#de-350)** (generic-MCP provenance) → required by **P1-A2** (ledger covers every tool source).
- **[DE-279](../PRD.md#de-279) / [DE-280](../PRD.md#de-280)** (case citation resolution / content-accuracy) → **P1-A1** shares their materialized-opinion substrate; DE-280's content judge *is* the paraphrase tier of external verification.
- **[DE-344](../PRD.md#de-344)** (external-tool cost is `Decimal(0)`) → **P1-A1/P1-B1b** add the long-opinion verification cost pre-flight that begins to close it.
- **[DE-360](../PRD.md#de-360)** (gateway-native quality-escalation routing — cheap→capable, reasoning logged) → the cost-control pattern for **WS-G**'s citing-passage LLM-judge fan-out and **P1-B1b**'s opinion-scale paraphrase judge; deferred until that frontier-judge cost is a felt constraint.

### Out of Phase 1 (roadmap resolution — see §Roadmap)

WS-D matter intake, WS-E source registry + free-source expansion, WS-G validity layer (the `treatment_id` slot stays null until its ADR), WS-F MCP-server ingress. Each behind its own **(ADR needed)** gate.

## Open questions (resolve in the relevant ADR / plan)

- ~~**Ledger granularity & retention.**~~ **Resolved in ADR 0018 D7** — per-(turn, source), accumulated per matter, history-preserving; materialized sources are pinned-while-referenced, GC mechanism pinned at P1-0.
- ~~**"Fiduciary-grade" gate definition.**~~ **Resolved in ADR 0018 D3** — PASS `{exact, tolerant}`; SUPPORTED `{paraphrase, ensemble}` labeled distinctly; FAIL flagged inline. Operator threshold tuning deferred (a later DE).
- **Validity layer methodology (WS-G).** How treatment is classified from citing passages, how confidence is calibrated and surfaced, how the citation graph is refreshed/staleness-bounded, and exactly how the platform labels derived signals so it never reads as editorial authority. (Pinned in the WS-G ADR.)
- **MCP-server identity model (WS-F).** How an external Claude session authenticates to an LQ.AI user + matter without weakening the self-hosted/BYO posture; what scopes are exposable.
- **Drafting surface.** Whether fiduciary-grade drafting reuses the Word add-in (M3) path, the chat work-product path, or both.

## Out of scope (file as DE-XXX if they surface)

- Owning or redistributing a proprietary corpus (Westlaw/Practical Law/KeyCite) — operators BYO-license via connectors.
- **Claiming editorial authority over validity.** WS-G surfaces *derived* signals with their reasoning and confidence; it does not assert a definitive "good law / bad law" verdict the way an editorial product does.
- Open model-driven function-calling beyond the operator allowlist (ADR 0015 forbids it).
- Exposing destructive/`requires_confirmation` tools over the MCP-server ingress without a human gate (ADR 0015 D4 carries forward to ingress).
- Non-MCP inbound integrations (a bespoke partner API) — MCP-server ingress is the one inbound surface.

## Cross-references

- Announcement: [Thomson Reuters press release](https://www.thomsonreuters.com/en/press-releases/2026/may/thomson-reuters-and-anthropic-expand-partnership-to-connect-claude-with-cocounsel-legal) (12 May 2026).
- Prior milestone this builds on: [legal-research-and-mcp.md](legal-research-and-mcp.md) (ADRs [0014](../adr/0014-gateway-egress-boundary-for-tool-providers.md)/[0015](../adr/0015-governed-tool-calling-model.md)).
- Posture this productizes: ADR [0013](../adr/0013-autonomous-layer-design-influences.md) (autonomous layer), ADR [0016](../adr/0016-transparency-and-governance-invariants.md) (transparency invariants), [PRD §1.3](../PRD.md#13-transparency-as-a-founding-principle)/[§1.8](../PRD.md#18-security-posture)/[§3.6](../PRD.md#36-research).
- Deferred items in scope: [DE-200](../PRD.md#de-200) (MCP — landed); [DE-279](../PRD.md#de-279)/[DE-280](../PRD.md#de-280) (case citation resolution + content-accuracy — the WS-A external-verify substrate); the deferred [Research surface (PRD §3.6)](../PRD.md#36-research) (free-source expansion: GovInfo/EUR-Lex/SEC EDGAR — note CourtListener today is operator-key-gated); [DE-344](../PRD.md#de-344) (per-provider external-tool cost); [DE-350](../PRD.md#de-350) (generic-MCP provenance).
