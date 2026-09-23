# ADR 0038 — Skill-backed orchestration as the first user-facing profile

**Status:** Proposed (2026-09-23)
**Amends:** [ADR 0035](0035-governed-orchestration-run-tree.md) first-profile scope and activation; retains its run-tree, authority, budget and execution decisions.
**Tracks:** [#563](https://github.com/LegalQuants/lq-ai/issues/563)

## Context

ADR 0035 approved a governed run tree but limited its first profile to sample
findings. That validates coordination without letting an owner use approved skills
to do the work being coordinated. Issue #563's user-facing capability is the
approval, parallel work and monitoring flow applied to real, bounded tasks.

## Decision

The first operator-enabled profile runs **installed, approved skills** in one
manual batch of one to four child sessions. The owner supplies an active
project and goal; a bounded planning step proposes tasks for review. The owner
selects authorized documents or KBs and available source access. The application
resolves the approved skills, model route, grants, inference and egress tiers,
budget, deadline and data restrictions into an exact plan. The owner approves
that plan before any child starts. Model-proposed tasks are data; they cannot
select executable authority or broaden the approved scope.

Each child executes its pinned skill through the governed tool and inference
path, with only its approved resources and grants. Children share bounded
results with the root, which synthesizes them through the same governed path.
The owner can inspect progress, receipts, partial results and retained files,
or halt further work. The limits and recovery semantics in ADR 0035 remain.

The operator's orchestration switch enables this real profile. Deterministic
sample responses remain test fixtures and may be offered as a clearly labelled
example, but they are not the only executable path behind that switch.
Research is a canonical example, not an exclusive child profile. Optional
persistent workspaces and bundled helpers retain their separate enablement and
security gates. This decision does not permit recursive delegation, arbitrary
tools, generated code or unreviewed skills.

Before the real profile is enabled, selected-document and KB authorization,
project-policy propagation and cross-agent handoff validation (DE-294) must be
implemented and tested. The gateway remains the only provider-key and external
egress boundary. Child output and retrieved content remain untrusted data; the
application rechecks current authority and data restrictions at each effect.

## Alternatives

| Alternative | Reason not selected |
|---|---|
| Keep the sample-only profile as the user-facing feature | It demonstrates coordination but cannot perform an owner's approved work. |
| Allow open-ended agents to choose skills, tools or sources | Task prose would become authority and defeat the approved-scope boundary. |
| Move orchestration to a separate harness service | It would duplicate the existing governance path without solving authorization. |

## Acceptance and release

An enabled run must execute two approved child skills on selected matter
resources, enforce exact-plan consent and bounded concurrency, show changing
progress, and produce a root result with honest evidence status. Tests must
reject unselected or revoked resources, widened child grants, stale approval,
unauthorized egress and hostile handoff text. They must also exercise halt,
partial results, budget accounting and recovery across a worker restart.
Controlled-provider tests establish the contract; a configured-provider
acceptance run is required before claiming live operation. Maintainer and
security review, including ADR 0035's helper-specific gates, remain release
requirements. Ratification of this amendment precedes publishing the expanded
implementation.
