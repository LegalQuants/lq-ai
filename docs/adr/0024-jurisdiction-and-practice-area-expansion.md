# ADR 0024 — Routing expansion contributions (new jurisdictions and practice areas)

**Status:** Proposed
**Date:** 2026-07-20
**Owner:** Maintainer team (houfu)
**Origin:** Committee call of 2026-07-19 (expansion ADR assigned); extracted from the
direction paper [docs/proposals/jurisdiction-and-practice-area-expansion.md](../proposals/jurisdiction-and-practice-area-expansion.md),
which holds the full evidence, the program roadmap, and the list of later
extractions. This ADR decides **one thing**: where an expansion contribution
goes, and that the claim is recorded.

## Context

Contributors are proposing coverage of new jurisdictions and practice areas
— a dozen open items across `legalquants/lq-ai` and `legalquants/lq-skills`
as of 2026-07-20 — and stalling, because no document says where each kind of
contribution belongs. The direction paper's §Motivation records the full
picture: the four de-facto homes with diverging bars, the routing folklore
(the only precedent is the lq-ai#190 → lq-skills#10 redirect, recorded in a
PR comment), and the failure modes already realized on the docket
(mis-filed PRs, a contributor waiting a month on "where should this live?",
a duplication merged past nobody noticing).

Every routing answer below **restates something already in canon** — this ADR
makes the folklore citable; it invents nothing.

## Decision

An incoming jurisdiction or practice-area contribution is classified by a
maintainer into one of four shapes and routed accordingly:

1. **Skills (S2) go to `legalquants/lq-skills`.** Community work-product
   skills route to the community skills repo; `lq-ai`'s `skills/` directory
   holds the curated first-party set. *(Codifies the lq-ai#190 →
   lq-skills#10 redirect.)*
2. **Authority sources (S1) go to `lq-ai`** as WS-E sources under ADR
   [0021](0021-content-source-registry-and-free-source-expansion.md) D1–D6,
   with the security review that gateway-egress changes already carry —
   for authors outside the known-contributor circle, that means the
   adversarial read in
   [docs/security/external-contribution-vetting.md](../security/external-contribution-vetting.md).
   *(Restates ADR 0021 + the vetting playbook's own §1 scope.)*
3. **Corpora / statutory graphs (S3) go to org-level repos** per the DE-264
   pattern (PRD §9); the placement choice for a given corpus (new sibling
   repo vs. a tree in an existing one) is a per-proposal maintainer call
   until an S3 charter ADR exists. Anything S3 that reaches operators —
   first-party MCP wiring, live external lookups — is gated in `lq-ai` as
   an S1-class change. *(Restates DE-264 + ADR 0014's single-egress rule.)*
4. **Practice areas excluded by PRD §1.6 (S4) require a mini-PRD and a
   committee-decided PRD amendment first**; the proposal's S1/S2/S3 parts
   route normally once the amendment lands. *(Restates the PRD-amendment
   reality and the governance process proposed in PR #311.)*

And one recording rule:

5. **Every routed proposal's claim is recorded** in a plain markdown table,
   `docs/contribute/coverage-map.md` (jurisdiction, practice area, claim
   issue link, status), checked before routing and updated in the same
   sweep. *(Extends skills/CONTRIBUTING.md's existing "claim first" step
   with a visible ledger; the lq-skills#18-vs-#6 duplication is the
   realized cost of not having one.)*

A proposal may decompose into several shapes (lq-ai#271 is S1 here with
sibling S2 PRs in lq-skills; lq-ai#287 is S4 first, then S2); the maintainer
response names each part and its route, and parts proceed independently.
A classification is a maintainer recommendation, not a ruling — a disputed
routing gets a second maintainer's review.

## Out of scope (deliberately)

Substantive gates (trust tiers, attestation — companion ADR 0025), the
jurisdiction vocabulary, the response
playbook's templates, lq-skills' own gate, security threat-class additions,
and everything in the direction paper's "New ADRs this program needs" table.
This ADR routes; it does not gate.

## Alternatives considered

- **Everything into `lq-ai` `skills/`.** Puts every community skill behind
  the full attestation gate and the maintainer review bottleneck; the #190
  redirect points the other way. Rejected.
- **Everything into `lq-skills`.** Sources are gateway egress and must stay
  behind `lq-ai`'s security review (ADR 0014/0021); corpora need versioned-
  data release cadence skills repos don't have. Rejected.
- **Per-jurisdiction repos.** Fragments discovery and multiplies governance
  surface; the coverage map gives the by-jurisdiction view without the
  split. Rejected.
- **Decide the gates and vocabulary in the same ADR.** The first draft did;
  consensus-by-bundle ratifies nothing cleanly. Restructured per the
  direction paper's Decision 1. Rejected.

## Consequences

- skills/CONTRIBUTING.md gains a short "Where does my contribution go?"
  section (the four routes + the coverage-map check).
- `docs/contribute/coverage-map.md` is created (whether it back-fills merged
  lq-skills coverage or starts from the first routed proposal is an
  acceptance-time detail).
- The open docket is answered by routing responses citing this ADR.
- The S4 route's committee path takes effect against the governance text
  adopted in PR #311 (filing precondition).

## Cross-references

- Direction paper (evidence, roadmap, later extractions):
  [docs/proposals/jurisdiction-and-practice-area-expansion.md](../proposals/jurisdiction-and-practice-area-expansion.md)
- ADR [0021](0021-content-source-registry-and-free-source-expansion.md) (S1),
  [0014](0014-gateway-egress-boundary-for-tool-providers.md) (egress),
  PRD §1.6 (S4) and §9 DE-264 (S3);
  [skills/CONTRIBUTING.md](../../skills/CONTRIBUTING.md) (claim step);
  [docs/security/external-contribution-vetting.md](../security/external-contribution-vetting.md)
  (S1 external-author read).
- Companion: ADR [0025](0025-jurisdictional-skill-trust-tiers-and-maintainer-of-record.md) (trust tiers & maintainer of record).
- GOVERNANCE.md + ADR 0022 — pending in PR #311.
