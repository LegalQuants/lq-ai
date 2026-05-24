# LQVern — M4 Autonomous Layer working folder

This folder collects the design + contributor material for **M4 / LQVern**: incorporating autonomous tasks (the PRD §3.10 Autonomous Layer) into LQ.AI, using [AnttiHero/lavern](https://github.com/AnttiHero/lavern)'s **Clawern** autonomous mode as a *design reference* (not a code dependency — stack mismatch; see DE-289).

## Canonical design artifacts (read these in order)

1. **[ADR 0013 — Autonomous Layer design influences](../adr/0013-autonomous-layer-design-influences.md)** — the gating design study. Pins single-agent v1, the api/arq executor substrate, the four primitives, the R4/R5/R6 brakes, the memory + precedent-board model, and the alignment contract. Answers §3.10's open questions.
2. **[PRD §3.10 Autonomous Layer](../PRD.md#310-autonomous-layer-m4)** — the built-out capability spec (data model, API surface, functional requirements, alignment contract).
3. **[agentic-flow-alignment-guide.md](agentic-flow-alignment-guide.md)** — the contributor how-to: the transparency/audit/OTel contract with pseudo-code, how to leverage the backend, and the "is my flow aligned?" checklist. **The most important doc for whoever builds this.**

Still to come (via the writing-plans step, after Kevin reviews the above): the phased implementation plan, and the Learn-tab visualization spec (a new "Autonomous flow" playground + How-it-Works section + build-page "anatomy of an aligned agentic flow" viz).

## Provenance / source material

- **`HANDOFFlavernevaluation.md`** — the original Lavern-evaluation handoff from a prior Claude Code web session (Lavern factual summary, the strategic "design reference, not dependency" conclusion, and the original Phase-1 deliverable structure). Useful reference; some of its scope framing is now superseded by ADR 0013 + the current PRD.

The work began as a "DE-265" PRD patch; that content was re-landed and renumbered on `main` as **DE-289** (expanded there with the boundary-register mapping), so the original patch is not carried here.

## Status

Design phase (feature branch `feat/lqvern-m4-autonomous`). The branch is intended for others to build on: the ADR + PRD build-out + alignment guide give a contributor the *what*, *why*, and *how* (including how agentic flows stay aligned with LQ.AI's transparent, auditable, OpenTelemetry-instrumented approach) before implementation begins.
