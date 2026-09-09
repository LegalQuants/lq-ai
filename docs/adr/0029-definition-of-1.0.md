# ADR 0029 — Definition of 1.0

**Status:** Proposed (drafted 2026-08-17; amended 2026-09-09 against the closed member
survey; tabled for decision at the LQAI Committee weekly call of 2026-09-13)
**Date:** 2026-08-17 (amended 2026-09-09)
**Owner:** Maintainer team (houfu)
**Related:** [ADR 0025 — release versioning](0025-release-versioning-and-pipeline-ordering.md),
[ADR 0030 — pacing 1.0](0030-pacing-1.0-preconditions-and-named-trains.md),
[ADR 0031 — headless use](0031-headless-api-only-use.md),
[ADR 0032 — Word add-in 1.0 slice](0032-word-add-in-1.0-slice.md),
[ADR 0033 — document-pipeline honesty](0033-document-pipeline-honesty-and-ocr.md),
[ADR 0034 — review capacity and governance](0034-review-capacity-and-reviewer-roles.md),
[PRD §8 Roadmap](../PRD.md#8-roadmap), [HONEST-STATE.md](../HONEST-STATE.md)

---

## Context

ADR 0025 reserved the `major` version for "a `1.0.0` milestone whose criteria this ADR does not
decide," and recorded that no project document defines what 1.0 or GA means: the roadmap (PRD §8)
is milestone-based delivery rather than convergence on a single 1.0, and `docs/HONEST-STATE.md`
frames nothing as a 1.0 gate. It left the definition "to a separate, future committee decision —
likely its own ADR, once someone is ready to own it." This is that ADR.

Where the project stands at `v0.7.1`:

- **Every planned feature milestone has shipped** — M1 through M4, plus the two post-M4
  milestones (legal research + connectors (MCP); fiduciary-grade agentic legal work, ADR
  0018–0021). What remains is punch-list work, not milestone work.
- **`v0.7.0` was a hardening release**, closing all three High-severity findings of the 360°
  security audit (#288) plus three Mediums. Sixteen findings remain open: seven Medium (GW-02,
  GW-03, API-02, API-03, AG-02, D-02, E-05), eight Low (GW-05, AG-03, AG-04, D-03, E-03, E-02
  remainder, E-04, E-06), one Info (GW-06).
- **Three user-facing surfaces are placeholders.** The Word add-in's feature tabs are deep-link
  cards to the web app (DE-287; HONEST-STATE §4.3: "do not market it as feature-shipped"). The
  Slack/Teams bridge webhook handlers are signature-verified but inert, and the OAuth dance has
  never been exercised against live Slack/Microsoft (DE-288, DE-312). The governed-matter entry
  point is a session-state seam reusing the autonomous-session UI, not a purpose-built intake
  surface (ROADMAP §1.6).
- **Engineering discipline is asserted, not enforced.** The 80%/90% coverage targets have no CI
  gate, the Cypress suite does not run in CI, and `docs/test-strategy.md` — an M1 deliverable —
  does not exist (ROADMAP §4.1–4.3).
- **One PRD-committed capability is not started in source**: Contract Repository /
  auto-relationship detection (PRD §3.16; no `contract_relationships` table). It is XL, senior
  work, and no owner has emerged in the ~3 months it has been on the open roadmap.
- **ADR 0025's own implementation is partially open**: the desktop launcher still defaults to the
  floating `latest` image tag (`desktop/src/main/index.ts:87`) rather than the pinned tag that
  decision 2 requires.

Why decide now: the open punch list (~150 DE entries) has no converging frame, so contributors
cannot tell which items advance a release-worthy goal and which are backlog. The audiences the
project courts — operator security teams, procurement — read `0.x` as "not ready" regardless of
actual maturity. Defining 1.0 turns the punch list into a countable checklist.

### The member survey

The 2026-08-17 draft of this ADR was tabled for acknowledgment on 2026-08-24 and then put to the
membership as a structured survey, which closed on 2026-09-04 with **9 ballots** (220 of 306
possible positions explicit, 71.9%). Results are recorded here as aggregates only; individual
ballots are not published. Where the survey settled a question, the decision below cites the
count. Where it did not, this ADR says so and the committee decides at the call.

The survey's own method ruling, recorded for the avoidance of doubt: **blanks are reported
separately and never folded into either bucket**, explicit abstain-by-instruction is honored, and
ballots cast through the comment field are read by their comments.

---

## Decision

### 1. What 1.0 means

**1.0 is an operator-trust milestone with a short feature-completion list, not a feature
milestone.** The operating principle, from which every gate below derives:

> At 1.0, every surface an operator can reach is either complete or explicitly labeled
> experimental, and every promise the documentation makes is either enforced in CI or verifiable
> by the operator.

The feature set of 1.0 is what has shipped through the fiduciary-grade milestone, plus the three
completion items in decision 2 — nothing else. Everything further (M5+ workflow intelligence, the
skill-ecosystem backlog, per-framework compliance docs) is post-1.0 by definition, not by slippage.

**Survey:** operator-trust **4** · operator-trust + a marquee capability **2** · disagree or own
definition **3** (one of the three endorsed the definition and used the disagree option only to
carry a comment). The definition carries, 6 of 9 in effect. The two "marquee" ballots sorted
*document-pipeline* work into 1.0 rather than a new surface — which is what ADR 0033 schedules.

**Dissent recorded.** Three ballots disagreed with the framing itself. They are recorded here, not
overruled, because each names work this ADR does not do:

1. **Product definition first.** 1.0 should follow from a stated target user and job-to-be-done,
   not from a gate. → PRD §1.4 gains a target-user / job-to-be-done section in this ADR's
   acceptance PR. This was the cheapest and most-asked-for remedy on the ballot.
2. **Adoption is not a version number.** A 1.0 tag does not itself make the project adoptable;
   assurance comes from design partners and demonstrated use. → tracked as a separate assurance
   track, not folded into the gate.
3. **Solve a real problem for early adopters.** → the Part 3 candidate ordering in decision 9 and
   the design-partner work above; the gate is not where this is answered.

### 2. Feature must-haves (the completion list)

Three items, each curing a placeholder surface rather than adding a capability:

- **F1 — Matter-intake UI.** A purpose-built "describe your matter" entry point for governed
  agentic matter sessions (backend shipped; ADR 0020). Replaces the session-state seam.
  *(Survey: keep 6 · cut 1.)*
- **F2 — Slack/Teams `/lq` + `/lq ask` flows (DE-288), verified live (DE-312).** Finishes the
  inert webhook handlers on both bridges and exercises the OAuth dance against live
  Slack/Microsoft once, with the recipe recorded. If unowned as the date approaches, the fallback
  is demoting the bridges to an explicit "experimental" label at 1.0 — permitted by the operating
  principle, but the worse outcome. *(Survey: keep 4 · cut 3 — **the most contested row in the
  gate**. It is kept, and the experimental-label fallback is the honest exit if the live
  verification in DE-312 cannot be run against maintainer-held tenants.)*
- **F3 — Word add-in slice: skills on selection/document with tracked-changes redlines.** The
  M3-B4/B5 core of DE-287 only. In-Word chat, playbook execution, and the tier badge remain
  post-1.0; the add-in's remaining tabs keep their deep-link cards but are labeled as pointers,
  not features. *(Survey: keep 5 · cut 2. The scope sub-question drew no consensus — 2 thinner ·
  1 as-proposed · 2 wider · 4 blank — so it is decided, not voted, in **ADR 0032**.)*

### 3. Hardening gates

- **H1 — All seven open Medium findings of #288 closed** (GW-02, GW-03, API-02, API-03, AG-02,
  D-02, E-05), each landing with its finding ID in the commit subject per the v0.7.0 convention.
  *(Survey: 5–0.)*
- **H2 — Every open Low/Info finding closed or explicitly risk-accepted in writing**, in a
  per-finding register appended to the audit doc. Risk-acceptance is a committee action, not a
  maintainer default. *(Survey: 3–2.)* The committee was asked whether written risk-acceptance is
  an acceptable terminal state for a 1.0 gate. **It is** — subject to three conditions: the
  register records the finding, the reasoning, the compensating control if any, and the accepting
  body; acceptance is a recorded committee decision, never a maintainer default; and the register
  is public. The template lives at `docs/security/risk-acceptance-register.md`.
- **H3 — M4-D2 acceptance lap complete**: the fresh-install walkthrough of every M4 surface that
  flips PRD §3.10 to "Shipped." *(Survey: 4–1.)*

### 4. Engineering-discipline gates

- **D1 — Coverage gate enforced in CI** at the PRD §5.8 targets (80% api / 90% gateway), as a
  threshold, not a no-decrease rule. *(Survey: 4–1.)*
  **Reconciliation:** PR #433 implements the gate but ratchets the gateway at **88%**, where the
  PRD says 90%. The ratchet is accepted on a **never-lower, raise-to-90-within-two-trains** rule;
  the alternative — amending PRD §5.8 down to 88% — is the committee's to take instead if it
  prefers the doc to match the gate exactly. Either way the gate and the PRD agree by the
  *Honest Documents* train.
- **D2 — Cypress E2E suite runs in CI** on PRs touching `web/`. *(Survey: 4–2.)*
  **Reconciliation:** PR #432 runs the suite **nightly**, where this gate says on-PR. Resolved:
  the deterministic subset runs **on PRs touching `web/`**; the flaky or long tail runs nightly.
  The gate is met by the on-PR track, not by the nightly one.
- **D3 — `docs/test-strategy.md` exists** with the per-surface E2E coverage matrix (the open M1
  deliverable). *(Survey: 5–0.)*
- **D4 — Acceptance tests run for the 10 starter skills against a real document corpus**
  (DE-051/DE-236), with results recorded per skill. *(Survey: 5–1.)* This is the one gate
  requiring practicing attorneys, and therefore the longest lead time; **it starts first**, and
  the pool it needs is what ADR 0034 recruits.

### 5. Release-mechanics gates

- **R1 — The desktop launcher defaults to a pinned image tag** and each `desktop-v*` release
  records the image set it ships against — completing ADR 0025 decision 2's implementation.
  *(Survey: 3–2.)*
- **R2 — Docs reconciliation at tag time**: HONEST-STATE, ROADMAP, and the release notes agree
  with source; no capability is documented as shipped that is not. The v0.7.0 release-notes
  "Honest scope" section is the template. *(Survey: 5–0.)*
- **R3 — Post-1.0 version semantics** extend ADR 0025 decision 3: **patch** = blind upgrade;
  **minor** = read the release notes, operator action may be needed; **major** = an upgrade that
  can break a working install's data, config, or API contracts. The operator-centric test ("does
  a working install need a human to touch it?") continues to govern the minor/patch line.

### 6. Procurement and compliance line

The **Procurement-Readiness Pack** (SIG Lite + CAIQ Lite + cover letter; mini-PRD, DE-086/DE-235)
is a 1.0 gate — it is what an evaluating team asks for first. *(Survey: 5–0.)* The per-framework
alignment documents (SOC 2, ISO 27001, ISO 42001, GDPR, HIPAA, FedRAMP) remain post-1.0 community
items; their stubs are labeled as stubs.

The committee was asked whether the procurement pack alone is the right 1.0 compliance bar. **It
is.** The pack is the artifact an evaluating team actually requests first; the six framework
documents are long-lead, auditor-shaped work that no amount of maintainer effort makes credible
without an audit behind it, and shipping them as stubs labeled as stubs is more honest than
gating 1.0 on them.

### 7. Contract Repository (PRD §3.16) is re-scoped to post-1.0

The one PRD-committed capability not started in source moves out of the 1.0 gate and onto the
post-1.0 roadmap. The PRD is amended in this ADR's acceptance PR so that 1.0 does not tag with an
unmet PRD commitment.

**Survey: 0 keep · 6 cut · 3 blank — the clearest mandate on the ballot**, and on the follow-up
question about its afterlife, 3 said post-1.0 and 4 said not a priority at all. Accordingly PRD
§3.16 is amended to read: post-1.0; a separate project or a pluggable integration point; no
owner; not scheduled. No separate ADR is needed.

### 8. Target date — struck

The 2026-08-17 draft targeted **end of Q1 2027 (2027-03-31)**. **The survey did not carry it**:
1 endorse · 5 "no date until the capacity constraint is addressed" · 3 other (delivery model
first; anchor in demonstrated user need; product definition first).

The date is therefore **struck from this ADR**. What replaces it is not a different date but a
different mechanism: three measurable preconditions, a dated committee checkpoint, and named
release trains decoupled from version numbers — **[ADR 0030](0030-pacing-1.0-preconditions-and-named-trains.md)**.

The relationship between the two ADRs is: **criteria govern the tag, preconditions govern the
date.** This ADR owns the checklist. ADR 0030 owns when it is credible to promise a date for it.
If a date is later set and the gates and that date conflict, the date slips — the gate does not
shrink.

### 9. The candidate features and the gate

The survey's Part 3 asked which additional capabilities belong in 1.0. The leaders were **OCR /
scanned-PDF handling (6)**, **Matter Memory (5)**, **lite mode (4)**, **chat attachments (3)** and
**fully-local operation (3)**; the strongest write-in was **attorney-first UX polish (6)**, ahead
of every listed candidate except OCR. Decision 1 says the 1.0 feature set is F1–F3 *and nothing
else*. The survey raised that tension and did not resolve it; this decision does.

**The gate stays as it is. The candidates run as priority-but-non-blocking work, sequenced by the
vote** — with one binding exception:

**The operating principle's honest-labeling duty binds at 1.0.** A scanned PDF, an Anthropic-only
install, and a still-ingesting attachment must each **fail visibly** by the tag. They need not
work by the tag; they must not lie. That is the cheap "tier 1" of each candidate, and it is
already required by decision 1 rather than added to it — see **[ADR 0033](0033-document-pipeline-honesty-and-ocr.md)**,
which schedules it.

The one defensible variation, recorded so the committee can take it deliberately rather than
discover it later: admit **OCR tier 2** — the opt-in scanned-PDF adapter, 5–7 person-days, with a
confirmed champion — as a fourth completion item **F4**. The release plan in ADR 0030 is the same
either way; only what *blocks* the tag changes.

---

## Consequences

- `docs/ROADMAP.md` gains a **"Path to 1.0"** section mapping these gates onto the four named
  trains of ADR 0030, and an **"After 1.0"** section recording the ordering the survey produced
  (see below). The sections are navigation aids; this ADR is canon.
- **Post-1.0 ordering**, from the survey's Part 3 post-1.0 column, recorded here because the
  2026-08-17 draft listed the shape of the post-1.0 roadmap as explicitly not decided: evaluation
  harness **6** · compliance packs **6** · DOCX tracked changes **5** · email intake **5** ·
  principles-as-tests **5** · jurisdiction packs **5** · practice-management connectors **5** ·
  the full Word add-in surface **4** · litigation carve-in **4**.
- 1.0-blocking items are labeled `road-to-1.0` on the issue tracker and take priority in
  maintainer review; the `help wanted` semantics (scoped and ready for pickup) apply to each.
- **D4 starts immediately** — attorney acceptance testing is the critical path, and the attorney
  pool it depends on is a precondition in ADR 0030 and a recruitment action in ADR 0034.
- **What 1.0 deliberately does not claim**: no eval harness (DE-237), no mutation testing
  (DE-229), the OpenWebUI fork's TypeScript-check debt remains (DE-262), per-framework compliance
  docs remain stubs, headless/API-only use is acknowledged but unsupported (ADR 0031), and the
  M5+ workflow-intelligence direction stays community-driven and uncommitted. HONEST-STATE
  remains the honest ledger of all of it.

## Alternatives considered

- **Feature-complete 1.0** (Contract Repository plus the full Word add-in surface in the gate) —
  rejected: both are XL senior work with no owner; the gate would push 1.0 well past any credible
  date at current capacity, and the operator-trust work would wait on feature work it does not
  depend on. The survey agreed on the Contract Repository, 6–0.
- **Pure operator-trust gate** (freeze features at v0.7.1, harden only) — rejected: it tags 1.0
  with visible placeholder surfaces, which fails the same honesty test the hardening gates exist
  to pass.
- **No 1.0; continue 0.x indefinitely** — rejected: ADR 0025 already reserved `major` for this
  milestone, and the audiences the project courts read a perpetual 0.x as perpetual beta.
- **Date-computed 1.0** (tag whatever `main` holds on a fixed date) — rejected: it inverts the
  criteria/date relationship and would let the gate shrink silently. The survey rejected the
  fixed date on the opposite ground — that no date is yet credible — and both objections point
  the same way: the criteria govern.
- **Admitting the top-voted candidates into the gate** (OCR, Matter Memory, lite mode) — rejected
  in decision 9: it would convert an operator-trust gate back into a feature gate and re-open the
  date question the survey just closed. The honest-labeling tier of each is in the gate already,
  by the operating principle.

## Explicitly not decided

- **Whether OCR tier 2 becomes F4** — put to the committee in decision 9; the recommendation is
  no, and the plan is unchanged either way.
- **LTS / support windows for 1.x** — PRD §7.8's support-cadence language was already restated as
  best-effort by ADR 0025; whether 1.0 changes that is deferred until the gate is closer.
- **Whether PRD §5.8's gateway target moves to 88% or the gate rises to 90%** — decision 4 (D1)
  takes the raise-to-90 path by default and leaves the amendment open to the committee.
