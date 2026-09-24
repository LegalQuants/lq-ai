# Risk-acceptance register

> **Status:** template, adopted by [ADR 0029](../adr/0029-definition-of-1.0.md) gate **H2**.
> No findings have been risk-accepted yet. Entries are added as Low/Info findings are
> dispositioned.

## What this is

[ADR 0029](../adr/0029-definition-of-1.0.md) H2 requires that **every open Low or Info finding of
the 360° security audit (#288) is either closed or explicitly risk-accepted in writing** before
1.0. This file is where the written acceptances live.

The committee was asked whether written risk-acceptance is an acceptable terminal state for a 1.0
gate, and answered yes — subject to three conditions, which this register exists to enforce:

1. **The record is complete.** Each entry names the finding, the reasoning, the compensating
   control if any, and the body that accepted it.
2. **Acceptance is a committee action, never a maintainer default.** A finding is not accepted by
   going stale. It is accepted by a recorded decision at a committee call, ratified under the
   [ADR 0022](../adr/0022-committee-governance-and-meeting-records.md) async rule.
3. **The register is public.** An operator evaluating LQ.AI can read exactly which risks the
   project decided to carry and why. That is the trade for allowing acceptance at all.

Risk acceptance is not a way to make a finding go away. It is a way to say, on the record, that
the project knows about it, decided not to fix it now, and is willing to be read on that decision.

## Scope

- **In scope:** Low and Info findings from #288, and any later finding the committee classifies at
  that severity.
- **Out of scope:** Medium and High findings. ADR 0029 H1 requires the seven open Mediums to be
  **closed**, not accepted. High findings were closed in v0.7.0. A Medium or High is never
  dispositioned in this register.

## How to add an entry

1. The maintainer team proposes a disposition with the reasoning, in the PR that would otherwise
   have carried the fix, or in the tracking issue.
2. The committee decides at a weekly call; the minutes record it.
3. After the 7-day objection window closes (ratification-final), a PR appends the entry below,
   linking the minutes.
4. `docs/security/threat-model.md` is cross-referenced if the acceptance changes a stated
   mitigation.

An entry is amended, never deleted. If a risk is later fixed, set **Status** to `Superseded — fixed
in <version>` and link the PR; the history of what was carried, and for how long, stays readable.

## Register

| ID | Finding | Severity | Disposition | Reasoning | Compensating control | Accepted by | Date | Review by | Status |
|---|---|---|---|---|---|---|---|---|---|
| — | *(no entries yet)* | | | | | | | | |

### Field definitions

- **ID** — the audit's finding ID (e.g. `GW-05`, `E-04`).
- **Finding** — one line naming the weakness, not the fix.
- **Severity** — as classified in #288.
- **Disposition** — `Accepted`, or `Superseded — fixed in <version>`.
- **Reasoning** — why carrying this risk is defensible. Written for an operator's security team,
  not for the maintainers. "Low impact" alone is not reasoning.
- **Compensating control** — what reduces the risk in practice, or `None`, said plainly.
- **Accepted by** — the deciding body and the meeting date, linked to the public minutes.
- **Date** — ratification-final date, not the call date.
- **Review by** — when this acceptance is revisited. An acceptance without a review date is a
  decision to stop looking.
- **Status** — `Active` while the risk is carried.
