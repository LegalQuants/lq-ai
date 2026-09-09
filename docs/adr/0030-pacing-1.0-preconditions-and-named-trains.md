# ADR 0030 — Pacing 1.0: date preconditions, the January checkpoint, and named trains

**Status:** Proposed (2026-09-09; tabled for decision at the LQAI Committee weekly call of
2026-09-13)
**Date:** 2026-09-09
**Owner:** Maintainer team (houfu)
**Related:** [ADR 0029 — definition of 1.0](0029-definition-of-1.0.md),
[ADR 0025 — release versioning and pipeline ordering](0025-release-versioning-and-pipeline-ordering.md),
[ADR 0034 — review capacity and reviewer roles](0034-review-capacity-and-reviewer-roles.md),
[PRD §7.8 release cadence](../PRD.md#78-release-cadence-and-supply-chain-transparency),
[ROADMAP.md](../ROADMAP.md)

---

## Context

[ADR 0029](0029-definition-of-1.0.md) decision 8 struck the 2027-03-31 target date. The member
survey that closed 2026-09-04 answered the timeline question **5 · 3 · 1**: five ballots for "no
date until the capacity constraint is addressed," three for other framings (settle the delivery
model first; anchor in demonstrated user need; settle the product definition first), one for the
proposed date. The date did not carry. The structural answer did.

The arithmetic behind that vote is not in dispute:

- The kept 1.0 gate is **90–145 person-days** (52–81 build + 33–54 review + 5–10 attorney-days).
- Observed throughput is **≈ 16 person-days per month**, maintainer-only.
- Roughly **25 substantive PRs** are open, and most of one contributor's month-old queue is
  unreviewed. The binding constraint is **review**, not authorship.

A date set against those numbers would be a date the project misses. But "no date" is not a plan
either: contributors cannot sequence work against an absence, and the trains that carry the gate
need somewhere to be scheduled. This ADR replaces the date with the machinery that would make a
date credible, and schedules the work in the meantime.

ADR 0025 already decided that `api`, `gateway`, `web` and `proxy` share **one version computed
from what lands on `main`** — patch means blind upgrade, minor means read the notes. A release
number is therefore an *output*, never a plan. Any milestone named `v0.9` is a promise about a
number the project does not control until the diff exists. This is why the trains below are
named, not numbered.

---

## Decision

### 1. No 1.0 date is set until three preconditions are measurably true

- **P1 — Bus factor ≥ 2.** A second maintainer with **both merge and security-review authority**,
  active for **≥ 1 quarter**. Measured as *activity* — merges landed, security-path reviews
  completed — not as membership of a GitHub team. A name on a team with no reviews is not a
  second maintainer.
- **P2 — An attorney pool of ≥ 2**, with **at least one completed D4 acceptance batch** behind
  it. Indications of interest do not count; a completed batch does.
- **P3 — Median PR first-response < 7 days**, sustained for a quarter. Measured from PR open to
  first substantive maintainer response, over all PRs opened in the window, excluding automated
  dependency bumps.

Each is a lagging indicator of the same thing: whether the project can absorb the gate's review
load. ADR 0034 is the machinery that recruits for P1 and P2 and publishes the SLA that P3
measures.

### 2. The first committee call of 2027 is a dated checkpoint

At that call the committee reads the three preconditions against measured data and takes one of
two paths, **publicly, at that call**:

- **Preconditions met** → the committee sets the 1.0 date from the remaining gate arithmetic.
- **Preconditions unmet** → the committee narrows scope or slows the trains, and says which, in
  the minutes.

The checkpoint is not a status update. It is the decision point where the project either earns a
date or adjusts the gate in public rather than sliding.

### 3. Release planning uses named milestones with target months, decoupled from version numbers

Four trains carry the gate. Each has a **theme** and a **date**; none promises a version number,
because ADR 0025 computes the number from `main`.

| Train | Due | Theme |
|---|---|---|
| **Enforced** | 2026-10-31 | What the docs promise, CI enforces |
| **Honest Documents** | 2026-12-31 | Documents never fail silently |
| *(checkpoint — first committee call of 2027)* | | Preconditions read against measured data |
| **First Run** | 2027-02-28 | The first run doesn't fight you |
| **Candidate** | 2027-04-30 | The acceptance lap |

Spacing is month-ends **61 · 59 · 61 days** apart — inside PRD §7.8's 8–12-week minor cadence.
The full per-train item lists live in [ROADMAP.md](../ROADMAP.md) "Path to 1.0", which is a
navigation aid; this ADR owns the names, the dates and the rule.

### 4. The rule of the trains: dates hold, content moves

A train ships what is green on its date. What is not green **rolls forward visibly** — recorded
in the release notes and the roadmap, not quietly re-dated. Even spacing is only honest under a
"no date" vote if the thing being promised is the cadence and not the contents.

### 5. The 1.0 tag is deliberately undated

`1.0.0` is cut when **the Candidate train's exit criteria hold** *and* **the preconditions in
decision 1 are met**. On the current arithmetic the earliest that can happen is **May 2027**. That
is an earliest, not a target, and it is promised to no one.

### 6. The governing formulation

> **Criteria govern the tag. Preconditions govern the date.**

ADR 0029 owns the criteria. This ADR owns the preconditions. Neither can be satisfied by
adjusting the other.

---

## Consequences

- **ADR 0029 is amended**: decision 8 (the 2027-03-31 target) is struck and points here, and the
  `v0.8 → v0.9 → v0.10 → v1.0.0` train wording in its Consequences is replaced by the named
  trains above.
- **PRD §7.8** gains a note that release *planning* uses named trains while release *numbering*
  stays computed per ADR 0025 — the two are not in tension, they are different objects.
- **ROADMAP.md** gains the "Path to 1.0" section with the four trains and their contents.
- GitHub milestones are renamed and created to match the train names; `road-to-1.0` labels attach
  to gate items. The empty `v0.7.3` milestone becomes *Enforced*; `v0.7.2` (the in-motion
  hardening cut, due 2026-09-30) is kept as-is and is **not** a train — it ships as whatever
  number ADR 0025 computes.
- The capacity arithmetic is published with the trains rather than held privately: each train
  carries its own build + review estimate against observed throughput, so when a train ships
  thin, the reason is already on the page.

## Alternatives considered

- **Keep 2027-03-31 as a target** — rejected: the survey rejected it 5–1–3, and a target that the
  arithmetic says is unreachable degrades every other date the project publishes.
- **Set no dates at all, including for the trains** — rejected: it leaves contributors with no
  sequencing signal and no way to see slippage. The compromise is that the *trains* have dates and
  the *tag* does not.
- **Number the trains (`v0.8`, `v0.9`, `v0.10`)** — rejected: it contradicts ADR 0025, which
  computes the number from `main`. "Enforced ships on 31 October" is a promise the project can
  keep; "v0.8 ships on 31 October" is a promise about a number the diff decides.
- **Tie the checkpoint to a gate percentage rather than a date** — rejected: a percentage of a
  gate that can be re-scoped is not a measurement. A dated call with named preconditions forces
  the conversation to happen whether or not the numbers are good.
- **Make the preconditions advisory rather than binding on the date** — rejected: that is the
  status quo the survey voted against. Advisory preconditions produce a date set on optimism.

## Explicitly not decided

- **What the 1.0 date is** — by construction. It is set at the January checkpoint if the
  preconditions hold.
- **What "narrower scope" would mean** if the preconditions are unmet — deliberately left to the
  committee at the checkpoint, with the full gate in front of it, rather than pre-committed now.
- **Whether the train cadence continues after 1.0** — revisit once the tag is cut.
