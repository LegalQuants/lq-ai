# ADR 0031 — Headless / API-only use: acknowledged, not supported

**Status:** Proposed (2026-09-09; tabled for decision at the LQAI Committee weekly call of
2026-09-13)
**Date:** 2026-09-09
**Owner:** Maintainer team (houfu)
**Related:** [ADR 0029 — definition of 1.0](0029-definition-of-1.0.md),
[ADR 0025 — release versioning](0025-release-versioning-and-pipeline-ordering.md),
[PRD §9 — deferred enhancements](../PRD.md#9-deferred-enhancements-and-identified-future-work),
[docs/api/backend-openapi.yaml](../api/backend-openapi.yaml)

---

## Context

The `api` and `gateway` services expose a 182-operation HTTP surface, and a stack of
`postgres + redis + minio + gateway + api` boots and serves it without `web` ever starting. People
have noticed. The question the survey put was whether that de-facto capability should become a
supported product surface — a "headless edition" — or stay an unsupported side effect.

The stakes are real in both directions. Supporting it means the OpenAPI surface becomes a
compatibility contract, which extends ADR 0025's patch/minor promises to third-party clients the
project cannot see and cannot test against. Not supporting it means answering a recurring
question with a recurring "no", and leaving a capability undocumented that people will use anyway.

**Survey: acknowledge but do not support 4 · a supported headless edition 2 · ship it and build
on it 2 · that is a fork's job 1.** This is the least settled of the key decisions. The proposal
held as the default and no option outpolled it, but "reconcile it in some form" also drew four
ballots, split two ways. This ADR records that honestly rather than reporting a mandate it does
not have.

---

## Decision

### 1. Headless use is acknowledged, not supported

One honest page in the deployment documentation: a headless `api + gateway` stack boots today,
here is the compose profile that does it, here is what works, **and there is no compatibility
promise**. The page exists so the answer is documented rather than repeated, not to invite
dependency.

### 2. API-consumer issues are answered "unsupported, PRs welcome"

Bug reports against the HTTP surface from clients that are not the project's own `web`, desktop
launcher, Word add-in or bridges are triaged as unsupported. They are not closed rudely and they
are not fixed on a promise; a PR with a test is welcome and is reviewed on its merits.

### 3. The OpenAPI export is a drift guard, not a public contract

The 182-operation export stays CI-drift-guarded (DE-373) because that guard protects the
project's *own* clients. It is **not** a public compatibility contract: **ADR 0025's patch and
minor promises do not extend to third-party API clients.** A patch that is a blind upgrade for an
operator may still break an unsanctioned client, and that is not a regression.

This is the load-bearing sentence of the ADR. Without it, "we publish an OpenAPI spec" silently
becomes "we version an OpenAPI spec."

### 4. The documentation site keeps API consumption out of scope

The docs site (#511) documents operating LQ.AI, not building against it. Revisit if decision 5
triggers.

### 5. Named revisit triggers

This decision is reopened — not merely reconsidered — when **either** holds:

- **The slim image ships.** Lite mode is the stated prerequisite for a credible headless edition;
  a 12 GB image that is mostly Docling and torch is not a thing anyone deploys headless. Until it
  exists, a "headless edition" would be an edition of an image nobody wants.
- **A design partner has a genuine API-only need.** Demonstrated use, not speculative demand.

Recorded alongside them, because it is the shape any future reconcile path would take: the
**first-party agent harness** rider from the survey — if the project ever supports programmatic
use, the credible form is a first-party harness the project itself tests against, not a bare API
surface with a support promise stapled on.

---

## Consequences

- A new page under the deployment docs describing the headless boot, explicitly labeled
  unsupported. It is a factual description, not a quickstart.
- PRD §9 gains a note recording this decision and the revisit triggers.
- The survey's own rule stands: **headless use never moves the 1.0 meter.** It is neither a gate
  row nor a candidate; it is a support-posture question that happens to have been asked at the
  same time.
- Nothing structural changes in source. This ADR is a promise *not* made, written down so that it
  is not made by accident.

## Alternatives considered

- **A supported headless edition** (2 ballots) — rejected for now: it converts the OpenAPI surface
  into a versioned contract at exactly the moment the project has one maintainer with merge
  authority and a 90–145 person-day gate in front of it. Revisit trigger 1 exists for this.
- **Ship it and build on it** (2 ballots) — rejected: same objection, plus it would put a second
  product surface in front of a gate that ADR 0029 deliberately kept to three completion items.
- **That is a fork's job** (1 ballot) — not adopted as the framing, though it is close to the
  practical outcome. "Unsupported, PRs welcome" is friendlier to the person asking and keeps any
  eventual contribution in-tree.
- **Say nothing** — rejected: the capability is discoverable, so silence is not neutrality. It
  produces the same support burden with none of the clarity.

## Explicitly not decided

- **Whether a future headless edition would be a separate compose profile, a separate image, or a
  documented subset** — a design question for whenever a trigger fires.
- **Whether the first-party agent harness is worth building on its own merits**, independent of
  headless support — a separate proposal if anyone wants to make it.
