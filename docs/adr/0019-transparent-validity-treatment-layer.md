# ADR 0019 — Transparent validity/treatment layer (WS-G)

**Status:** Proposed (2026-06-26) — awaiting maintainer acceptance. Implementation PRs (WS-G PR1+) carry **security review** per CODEOWNERS (new gateway egress operation; citation/audit surface).
**Date:** 2026-06-26
**Owner:** Fiduciary-grade agentic legal work milestone — Phase 2 (WS-G), feature branch `docs/adr-0019-validity-treatment-layer`
**Supersedes / relates to:** [ADR 0014](0014-gateway-egress-boundary-for-tool-providers.md) (where egress lives — the new citing-graph operation lands here), [ADR 0015](0015-governed-tool-calling-model.md) (how a tool call is governed), [ADR 0016](0016-transparency-and-governance-invariants.md) (the binding invariants — P3 no-raw-payload, P6 one governance path), [ADR 0018](0018-citation-ledger-and-fiduciary-grade-output.md) (D6 reserves the `citation_ledger_entry.treatment_id` slot this ADR fills), and the [fiduciary-grade mini-PRD](../proposals/fiduciary-grade-agentic-legal-work.md) WS-G.

## Context

Thomson Reuters' CoCounsel and the incumbent citators (Westlaw KeyCite, Lexis Shepard's) answer one question the LQ.AI citation engine does **not**: *is this case still good law?* The Phase-1 citation engine verifies that a citation **exists** and is **accurately quoted** (verbatim or paraphrase-supported, ADR 0018 D2/D3); it says nothing about whether a later court has **overruled, criticized, distinguished, or followed** the case. That is the validity/treatment gap — and the last major parity axis in the milestone (mini-PRD §"What LQ.AI already has vs. what is net-new").

The incumbents answer it with **editorial** judgments: human (and increasingly model) editors assign a treatment verdict the customer is asked to trust. LQ.AI's founding principle (PRD §1.3) forecloses that posture — an opaque "bad law" flag the user cannot inspect is exactly the "trust us" claim the project exists to replace. So WS-G answers the question **LQ.AI's way: derive the signal transparently and show the work.**

A codebase verification pass (2026-06-26) established what exists and what is net-new:

- **Reusable** — the LLM-judge rails (`_JudgeGatewayProtocol`, `build_judge_prompt`, `_parse_judge_response`, `_CONFIDENCE_MAP`, the per-call cost estimator) and `read_opinion(opinion_id)`, which reads any materialized opinion's plaintext — cited or **citing** — identically.
- **Net-new** — (1) the **citing-graph data is not reachable today**: the CourtListener provider exposes only `verify_citations` / `search_case_law` / `get_cases`; none return "which later opinions cite case X," though CourtListener's REST API does (`opinions_cited` / citation network). (2) The judge's verdict vocabulary is `yes/partial/no` (a *support* judgment), **not** a treatment classification. (3) There is no `citation_treatment` table — only the reserved `citation_ledger_entry.treatment_id` slot (ADR 0018 D6).

This ADR pins WS-G's methodology, its compute/trigger model, the new egress surface, the storage model and its P3 posture, the anti-overclaiming guarantees, and the phased build. It does **not** specify endpoint shapes or migrations — those land in the per-PR specs/plans after acceptance.

## Decision drivers

1. **Transparency is the product (§1.3).** A treatment signal must be *demonstrable*: one click from "questioned" to the exact later case and passage that questioned it, with the judge's reasoning and confidence visible. This is the axis on which an open, self-hosted, *derived* signal beats an opaque editorial verdict.
2. **Derive, don't assert.** LQ.AI is not a citator and does not claim editorial authority (mini-PRD §"Out of scope"). It surfaces *derived signals + reasoning + confidence*, never a definitive "good law / bad law" verdict.
3. **Reuse the substrate; do not fork it (ADR 0016 P6).** WS-G reuses the citation engine's judge rails and the research layer's opinion store. The treatment judge is a new *prompt + verdict schema* over the *same* gateway-brokered judge surface — not a parallel inference path.
4. **No raw payloads in the index (ADR 0016 P3).** `citation_treatment` references citing opinions by id + offset; the citing passage text lives in the content layer and is read at trace time, never duplicated into a derived-signal row.
5. **Conservative posture (PRD §1).** Absence of a negative signal is **not** an assertion of good law — it is "no negative treatment found as of <date>." A derived signal is never presented as final or editorial.
6. **Cost is a first-class constraint.** The citing-passage judge fan-out is the milestone's largest cost lever; a landmark case is cited by thousands of later opinions. The R4 economic brake (a no-op for external tools today, [DE-344](../PRD.md#de-344)) and gateway-native escalation routing ([DE-360](../PRD.md#de-360)) must bound it. The build phases the cost in.

## Decisions

### D1 — Derive, don't assert (the binding posture)

WS-G **derives** treatment signals from the citation graph + an LLM-judge over citing passages and surfaces each with its reasoning, confidence, and one-click links to the exact citing case and passage. It **never** emits a definitive "good law / bad law" verdict. Every derived signal is labeled **"derived, not editorial."** The absence of a negative signal is surfaced as *"no negative treatment found as of <date>,"* never as an affirmative "good law." This posture is load-bearing and binds every WS-G PR; a PR that presents a derived signal as an editorial verdict violates this ADR.

### D2 — Compute model: per-cited-case, cached, off the critical path

A new `citation_treatment` record (keyed by the cited opinion, with its cluster) holds the derived case-level signal. When a turn's ledger contains a caselaw citation to case X, treatment for X is derived **off the assistant turn's critical path** — the default is an **async** derivation after turn finalize, with **lazy on-first-trace-open** as the fallback when no async worker has populated it yet. The result is **cached** in `citation_treatment` with a staleness bound (D8); subsequent citations of X reuse the cache. The derived row's id populates `citation_ledger_entry.treatment_id` (ADR 0018 D6). The expensive citing-graph fetch + judge fan-out never sits on the turn's latency path, and a turn's fiduciary-grade gate (ADR 0018 D3) does **not** depend on treatment — treatment enriches the ledger entry; it does not gate the turn.

### D3 — A new gateway operation exposes the citing graph (new egress, security-gated)

The citing-graph data is reached by **adding a CourtListener tool operation** (working name `get_citing_opinions`) on the ADR-0014 egress boundary, wrapping CourtListener's citation/citing-opinions REST surface to return the later opinions that cite a given case (with citation count, citing court, and date). It is **BYO-key-gated** exactly as CourtListener is today (operator-supplied token; no LQ.AI-side licensing). This is the **only** new egress surface WS-G introduces; it carries security review per CODEOWNERS (`gateway/**`). Reading a citing opinion's full text reuses the existing materialize-then-`read_opinion` path (no second egress design).

### D4 — Phased build: graph-first, judge-second

This ADR pins the full methodology; the build phases the cost in.

- **WS-G PR1 — the citation graph as a derived provenance signal.** Ship `get_citing_opinions` + a `citation_treatment` row carrying the **graph-level** signal only: *"cited by N later opinions; here they are, with court and date,"* surfaced on the ledger entry. **No judge fan-out** — cheap, deterministic, immediately useful (a lawyer sees the citing set and can inspect it), and it stands up the table, the trigger, and the trace UI without the cost lever.
- **WS-G PR2 — the treatment-classifying judge.** Add the new treatment judge (D5) over a **prioritized, capped** subset of the citing opinions: negative-signal-likely + higher-court + most-recent first, a **hard cap N**, bounded by a **per-case cost budget** in the manner of B1b/B1c's per-turn budget, and the first proving ground for DE-360 escalation routing. Later judge runs refine the same `citation_treatment` row (the graph signal from PR1 is never lost).

Subsequent PRs (trace UI, refresh policy surfacing) follow; each is scoped in its own spec/plan.

### D5 — Taxonomy and case-level rollup

The treatment judge classifies **each citing passage** into one of: `followed`, `distinguished`, `criticized`, `questioned`, `overruled`, `superseded`, or `neutral` (the last covers the common case — a citation that carries no treatment signal). This is a **new judge prompt + verdict schema** reusing the judge *rails* (the gateway protocol, the cost estimator, the response-parsing discipline) but **not** the `yes/partial/no` vocabulary. The per-passage classifications **roll up** to a case-level signal that surfaces the **strongest negative treatment found** (e.g. *"questioned by 2, distinguished by 5, otherwise neutral — derived as of <date>"*), with each contributing signal linked to its exact citing case + passage and confidence. The rollup never collapses to a single editorial bucket (D1).

### D6 — Confidence: reuse the existing scale

Each per-passage treatment judgment carries a confidence on the existing `_CONFIDENCE_MAP` scale (`high`/`medium`/`low` → `0.90`/`0.70`/`0.50`). The case-level signal's confidence is a function of the strongest-negative contributor's confidence and the corroboration count (how many citing passages agree). The exact aggregation function is fixed in the PR2 plan; the constraint this ADR pins is that confidence is **surfaced per signal**, never hidden, and never inflated to imply certainty.

### D7 — P3-preserving storage

`citation_treatment` stores **derived classifications + references** — the cited opinion/cluster id, the contributing citing `opinion_id`s + passage offsets, court/date, per-signal classification + confidence, the rollup, and the "as-of" date. It does **not** store raw citing-passage text; the passage is read from the content layer at trace time, exactly as the ledger reads quoted text (ADR 0018 D5). `citation_treatment` is metadata-only and is **added to the ADR 0016 P3 no-raw-payload tripwire** in the PR that introduces it.

### D8 — Staleness and refresh

A derived treatment signal is **never** presented as final. Each `citation_treatment` row carries an **"as-of" date**, surfaced to the user wherever the signal appears ("derived as of <date>"). A staleness TTL (**default 30 days, operator-tunable**) triggers re-derivation on the next access after expiry. The citation graph grows monotonically (new citing opinions appear over time), so refresh is additive; a stale row is still shown, labeled with its age, rather than withheld.

### D9 — Derived and connector-editorial signals coexist, each attributed

Where an operator has connected a **licensed** source (a Westlaw/CoCounsel MCP, or another provider) that supplies its **own** editorial treatment, the ledger records that editorial signal **alongside** the derived signal, **attributed to its source**. The derived signal stays labeled "derived, not editorial"; the connector's signal is labeled and attributed to the connector. LQ.AI **never** relabels a third party's editorial product as its own derived signal, and never ships someone else's licensed treatment content (mini-PRD §WS-E posture).

### D10 — The R4 economic brake becomes real here

WS-G is the first workstream whose value depends on **metered** external work: the citing-graph fetch (metered CourtListener egress) and the judge fan-out (inference cost). The per-case cost budget (D4) bounds the judge fan-out, and `estimate_tool_cost` for the new citing-graph operation must return a real estimate rather than `Decimal(0)` ([DE-344](../PRD.md#de-344)) so the R4 brake can bound external-tool spend for the first time. The exact budget values and the DE-344 wiring are fixed in the PR plans.

## Consequences

- **Fills the reserved slot.** `citation_ledger_entry.treatment_id` stops being always-null; the Phase-1 ledger gains a validity dimension without a schema change to the ledger itself (a new `citation_treatment` table + the existing FK slot).
- **One new egress operation, security-gated.** The CourtListener provider grows one read operation (D3); no new provider, no new boundary. The MCP-server *ingress* boundary remains Phase 3 (WS-F).
- **Cost is bounded and phased.** PR1 carries no fan-out cost; PR2 introduces the bounded judge fan-out and is where DE-360/DE-344 first bite. No turn's latency or fiduciary-grade gate depends on treatment (D2).
- **The posture is auditable, not editorial.** A reviewer can trace any "questioned"/"overruled" signal to the exact citing opinion and passage and the judge's reasoning — the transparency claim is demonstrable, not asserted (D1, D7).
- **New P3 surface.** `citation_treatment` joins the no-raw-payload tripwire; the PR that adds it adds the tripwire assertion in the same change (ADR 0016 P3).

## Open questions (resolve in the WS-G PR specs/plans)

- **Citing-opinion prioritization (PR2).** The exact ranking that selects which ≤N citing opinions to judge (negative-signal heuristics from CourtListener metadata? citing-court seniority? recency?), and the cap N and per-case budget values.
- **Rollup + confidence aggregation (PR2).** The precise function from per-passage judgments to the case-level signal and its confidence (D5/D6).
- **Treatment-passage localization (PR2).** How the citing *passage* (the span where opinion B discusses case X) is located within opinion B's text to feed the judge — a `find_in_case`-style locator vs. a whole-opinion judge like `case_content_judge`.
- **Async derivation mechanism (PR1).** Which worker/queue derives treatment after finalize, and the lazy-on-trace-open fallback's exact trigger (D2).
- **Refresh surfacing + TTL default (PR1).** Confirm the 30-day default and how "derived as of <date>" renders in the trace UI (D8).
- **DE-344 scope for the citing-graph op (PR1/PR2).** The cost model for `get_citing_opinions` and where the R4 brake reads it (D10).
