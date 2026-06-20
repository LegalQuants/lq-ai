## What this PR does

<!-- One or two sentences describing the change. Keep this scoped to what
actually changed; the why goes in the next section. -->

## Why

<!-- The motivation. If this PR closes an issue or implements a deferred
enhancement, link it: "Closes #123" or "Refs DE-013". -->

## What this PR does *not* do

<!-- Optional but encouraged for non-trivial PRs. Naming the explicit
non-goals prevents reviewer scope creep and makes follow-up PRs cleaner. -->

## Type of change

<!-- Check all that apply -->

- [ ] Bug fix (non-breaking change that fixes an issue)
- [ ] New feature (non-breaking change that adds capability)
- [ ] Breaking change (fix or feature that would change existing behavior)
- [ ] Documentation update
- [ ] Skill contribution (see attestation below)
- [ ] Refactor (no behavioral change)
- [ ] Test / CI / tooling

## Testing

<!-- How did you verify the change? -->

- [ ] Unit tests added/updated
- [ ] Integration tests added/updated (if applicable)
- [ ] Manually tested against a real deployment (describe scenario below)
- [ ] Acceptance test plan updated (if changing skill behavior)

<details>
<summary>Manual testing notes (if applicable)</summary>

<!-- What you ran, against what configuration, and what you observed. -->

</details>

## Documentation

- [ ] PRD updated (if user-facing behavior changes)
- [ ] README updated (if quickstart or capability list changes)
- [ ] Skill-authoring guide updated (if skill conventions change)
- [ ] Deployment cookbook updated (if deployment changes)
- [ ] Compliance documentation updated (if compliance posture changes)
- [ ] OpenAPI schema regenerated (if API endpoints change)

## Transparency & governance invariants

<!-- The posture that *is* the product (ADR 0016). Check each box or mark it
n/a. If you can't, stop and either fix the change or surface the decision to a
maintainer. The cheap-to-check ones are enforced by
api/tests/test_transparency_invariants.py — but the judgment ones are on you. -->

- [ ] **Egress (P1):** any outbound third-party call goes through the gateway only — no direct egress from `api/`.
- [ ] **Closed set (P2):** any new model/autonomous-invokable capability is a bounded, operator-controlled allowlist entry, not an open hook.
- [ ] **No raw payloads (P3):** no row or log line I add carries raw content (message bodies, tool args/results, fetched text, keys) — counts, types, ids, digests, outcomes only.
- [ ] **Fail restrictive (P4):** missing/broken config fails closed, and I tested that path, not just the happy path.
- [ ] **Atomic audit (P5):** state changes get an audit row committed in the same transaction (helpers flush, the handler commits).
- [ ] **One governance path (P6):** I reused the shared governance/audit helpers rather than re-deriving tier/cost/audit logic.
- [ ] **Human gate (P7):** anything destructive/irreversible is behind the confirmation gate and excluded from unattended/autonomous execution.
- [ ] **Operator control (P8):** any new capability has an operator enable/disable and appears on an admin surface.
- [ ] **User owns data (P9):** outbound matter context is anonymized; the change respects export/delete and data-residency guarantees.
- [ ] **Contract is truth (P10):** OpenAPI sketch / DB schema doc / relevant ADR updated in this PR; any architectural/authz decision is recorded or surfaced, not made silently.

## DCO sign-off

- [ ] All commits in this PR are signed off per the [DCO](../CONTRIBUTING.md#sign-off-developer-certificate-of-origin)

<!-- Verify with: git log --show-signature -->

## Related issues

<!-- Closes #123, Refs DE-013, etc. -->

---

<!-- ============================================================
SKILL CONTRIBUTION ATTESTATION (uncomment if this PR contributes
or substantively modifies a skill containing legal substance)

## Skill attestation

I have reviewed the substantive legal content of this skill and
certify that, to the best of my knowledge as a [practicing
attorney / legal professional / specific role], the patterns,
severity calibrations, recommended language, and reference
material reflect accurate and reasonable legal practice in
[jurisdiction(s)]. I understand that this skill will be used in
real practice and that errors could affect real legal work; I
have authored this skill with the same care I would apply to my
own client work.

Signed: [your name and any relevant qualifications]

If you are not a practicing attorney, follow the alternative
attestation paths in skills/CONTRIBUTING.md (pair with a
practicing-attorney co-author, or have a practicing attorney
review the skill before submission).
============================================================ -->

## Reviewer notes

<!-- Anything the reviewer should know — areas where you'd specifically
appreciate scrutiny, design decisions you considered alternatives for,
known limitations of this PR. -->
