# DE-365 Sub-project 1 — Docs/README claims-vs-reality honesty audit + fiduciary-grade refresh

**Date:** 2026-07-01
**Status:** Design (approved in brainstorming; pending written-spec review)
**Parent:** DE-365 (PRD §9) — Launch-documentation pass. Decomposed into three sub-projects, built in order: **(1) this — docs/README honesty audit; (2) Learn-tab fiduciary-grade playgrounds; (3) evidence-linked competitor comparison.** Each gets its own spec → plan → build.

---

## Goal

Make `README.md` and the honest-state docs faithfully reflect what the code actually does as of the fiduciary-grade milestone — by **both** adding the missing Phase-2 capabilities **and** systematically auditing every existing capability/status claim against the code and correcting over- and under-statements. This is the pre-launch honesty pass (the "claims-vs-reality" / Arm-A audit from the release-readiness plan), scoped to documentation only.

**Why now:** WS-E PR2b just merged, so all Phase-2 backend workstreams (WS-D/E/G) have landed. The README's capability narrative and roadmap table currently stop at the "Legal research + connectors (MCP)" milestone (the CourtListener era); the entire fiduciary-grade milestone — Citation Ledger, fiduciary gate, governed agentic matter sessions, free authority sources, treatment/validity — appears **nowhere** in README, and `docs/HONEST-STATE.md` has zero coverage of it either.

## Non-goals (out of scope for sub-project 1)

- The in-app Svelte `learn` pages / interactive playgrounds → **sub-project 2**.
- The competitor comparison chart → **sub-project 3** (and per a standing constraint it must be **vendor-neutral** — no named products).
- A blanket rewrite of `docs/PRD.md` (it is the source of truth and is kept current per-DE; touch only where the audit finds a concrete inaccuracy).
- Any code / test / product change. Documentation only.

## Guiding constraint

CLAUDE.md principle 4 (conservative posture — never overclaim) binds every line. Where a capability is partial or roadmapped, say so. The standard for a "shipped ✓" claim is "demonstrable by an in-house lawyer on real documents," and each such claim links to the artifact that proves it (ADR / code path / test). **Vendor-neutral** throughout — no named competitor products, even in honesty prose.

---

## Approach — bidirectional audit-worksheet-first

One audit worksheet drives both directions, then all fixes land in a single reconciled pass so the docs stay mutually consistent.

### Direction A — docs → code (catch overstatement / staleness)

Extract every capability/status claim from `README.md`, `docs/HONEST-STATE.md`, and `docs/ROADMAP.md`. Each becomes a worksheet row:

| field | content |
|---|---|
| claim | the asserted capability/status, quoted |
| where | file + section/line |
| artifact | the proving-or-refuting ADR / code path / test |
| verdict | Accurate · Overstated · Understated · Stale |
| resolution | the exact edit (or "attach link, no prose change") |

Verdict semantics:
- **Accurate** — code backs it. Ensure the doc shows the proving link where it belongs; no prose change otherwise.
- **Overstated** — claims more than the code does → soften to the honest state.
- **Understated / missing** — code does more, or a shipped thing sits under roadmap → upgrade / move it.
- **Stale** — milestone framing outdated (e.g. "current shipped = MCP milestone") → update.

### Direction B — code → docs (catch shipped-but-undocumented)

Enumerate what is actually shipped from the authoritative sources and confirm each has honest representation in the docs. Authoritative sources:
- ADRs: **0018** (Citation Ledger + fiduciary-grade output), **0019** (treatment/validity), **0020** (governed agentic matter sessions), **0021** (content-source registry + free-source expansion).
- `api/app/research/registry.py` `SOURCE_REGISTRY` (the live authority sources: govinfo, edgar, eurlex).
- The migration sequence (latest = 0064) and the DE ledger (esp. DE-344, DE-369, DE-370, DE-371, DE-372, DE-373, DE-374, DE-375, DE-376).
- Merged PRs for the milestone (WS-D #239/#240, WS-E #245/#246/#251/#254/#255/#257, WS-G series).

This direction is where the whole fiduciary-grade milestone gets added to the docs.

### Reconcile in one pass

Apply all resolutions together and enforce cross-document consistency: a claim marked "shipped" in README must not sit under "not yet built" in HONEST-STATE, and ROADMAP must agree with both. README status ↔ HONEST-STATE ↔ ROADMAP form one consistent account.

### Implementation note (not a spec commitment)

During the build, Direction-A verification can fan out across parallel audit subagents (one per capability domain) via plain `Task` agents in the subagent-driven flow. **No `Workflow` invocation** (no ultracode opt-in). This is a plan detail; the spec only commits to the worksheet + reconciled docs.

---

## Fiduciary-grade additions (the shipped capabilities to document, with honest caveats)

| Capability | Anchor artifact(s) | Honest caveat to state |
|---|---|---|
| **Citation Ledger** — matter/turn-scoped record of every source + passage read, verification status from the cascade, one-click "trace this source" | ADR 0018; ledger read API + UI (`api/app/citation/ledger.py`, ledger UI route) | References content by id/offset only — **no raw payloads** in the audit layer (P3, ADR 0016) |
| **Fiduciary-grade gate** — derive-don't-assert; the verification cascade runs over every tool-retrieved source; PASS/FAIL → `flagged` | ADR 0018; `api/app/citation/gate.py` | Chat vs autonomous **parity gaps are real**: attributed-authority FAIL tier (DE-370) and autonomous SUPPORTED tier (DE-371) still open |
| **Governed agentic matter sessions** — plain-language matter → planned closed-set (ADR 0015) multi-source session under R5→R6→R4 brakes → work product + ledger | ADR 0020; WS-D #239/#240 | Built on the autonomous layer; **no dedicated matter-intake UI yet** (reuses the autonomous session UI) — an honest-state item |
| **Content-source registry + free authority sources** — GovInfo, SEC EDGAR, EUR-Lex; `retrieve_authority` + verify, chat + autonomous, registry-driven | ADR 0021; `SOURCE_REGISTRY`; gateway tool adapters | Behind operator config; **EUR-Lex is get-by-CELEX only** (search = DE-374; treaty/corrigendum = DE-375) |
| **Validity / treatment layer** — derived treatment signals, one-click trace to the citing cases | ADR 0019; `api/app/citation/treatment.py` | Signals are **"derived, not editorial,"** not an authoritative citator; per-case judge budget bounds cost |
| **Governed egress cost model** — per-provider cost on the R4 cumulative brake | DE-344; `api/app/tools/governance.py` | **Configured** per-call rate, not response-parsed; best-effort / fails-open on a systemic gateway-config failure |

(The audit may surface more; the worksheet is the authority. This table is the known-minimum set.)

---

## Deliverables

1. **`docs/audits/2026-07-01-claims-vs-reality.md`** — the durable audit worksheet (both directions), retained as standing honesty-gate evidence.
2. **`README.md`** — reconciled: capability narrative ("What it does"), "What you can verify," Project-status prose, and the roadmap table — fiduciary-grade milestone added; every over/under-statement corrected; proving links attached.
3. **`docs/HONEST-STATE.md`** — fiduciary-grade shipped state added; now-shipped items moved out of "not yet built"; new honest caveats (matter-intake UI gap, DE-370/371 parity, EUR-Lex get-only scope).
4. **`docs/ROADMAP.md`** — reconciled with the current DE / milestone state.
5. **`docs/PRD.md` §8 status lines** — edited **only** where the audit finds a concrete inaccuracy.

## Verification (definition of done)

Docs have no unit tests, so verification is explicit:
1. **Link resolution** — every cross-link added/changed resolves to a real path on `main` (scripted check over changed files).
2. **Markdown well-formed** — headings, tables, and lists render; no broken anchors.
3. **Cross-document consistency** — nothing marked "shipped" in README appears as unbuilt in HONEST-STATE; ROADMAP agrees with both.
4. **Caveat accuracy** — each fiduciary-grade caveat matches the actual DE-ledger state (DE-370/371/374/375/376 open as described).
5. **No overclaim, no named vendor** — a read-through against CLAUDE.md principle 4 and the vendor-neutral constraint.
6. **Worksheet completeness** — every claim row has a verdict and a resolution; no "TBD".

## Risks / notes

- **Scope creep into a full doc rewrite.** Mitigation: the worksheet bounds the work — only claims with a non-Accurate verdict get edited; Accurate claims at most gain a link.
- **PRD blast radius.** Mitigation: PRD edits are audit-finding-gated, not a sweep.
- **Security-sensitivity.** These are docs, but they describe `gateway/**` and citation-integrity behavior; keep descriptions accurate to avoid implying stronger guarantees than the code provides (that would itself be an overclaim).
