# PRD: Governed orchestration and optional skill capabilities

**Status:** Accepted design; local implementation available for review, release pending.
**Tracks:** [#563](https://github.com/LegalQuants/lq-ai/issues/563).
[ADR 0035](../adr/0035-governed-orchestration-run-tree.md) records the architecture;
the [research note](../research/issue-563-harness-research.md) explains its evidence.

## Problem and users

Matter owners need to delegate parallel work without losing control of scope,
spend or confidential information. Skill authors need optional continuity across
runs and reviewed computations; operators need explicit control over enablement.

- As a matter owner, I want to approve, monitor and stop delegated work so I can
  inspect its progress and retain useful findings when a topic fails.
- As a skill author, I want to opt into saved work and installed helpers so my
  skill can reuse information and perform a reviewed computation.
- As an operator, I want bounded, disabled-by-default capabilities so I can enable
  them only after the required reviews.

## Goals and scope

Demonstrate an inspectable flow from plan and approval through parallel children,
collection and synthesis. Preserve work across interruptions and, when a skill
opts in, across runs. Keep access, spending and execution under owner/operator
control.

The first profile uses sample findings and labels results unverified. Generated
code and arbitrary shell execution are excluded to keep execution within reviewed
helpers. Recursive delegation, watch/schedule orchestration and substantive
legal-research quality are outside this delivery.

## Requirements and acceptance

| Requirement | Acceptance criterion |
|---|---|
| R1 — Explicit consent | The owner can inspect scope, budget and one to four topics for an active owned project. No child runs before approval of that exact revision; rejected or stale approval cannot start work. |
| R2 — Observable parallel work | Two children can progress concurrently within configured limits. Each topic exposes progress and an outcome; partial, empty, failed and halted results remain distinguishable. Only the root delivers the synthesis, retaining its evidence status. |
| R3 — Control and recovery | Calls respect current permissions, approved scope and the accounted budget. Halt stops new work and preserves results; already-admitted calls may finish. Restart retains committed findings and charges; uncertain calls remain visible for reconciliation without automatic repetition. |
| R4 — Run working files | Children can save private notes across interruptions and explicitly share immutable findings with the root, with no sibling access. Owners can inspect files after halt; owning-run deletion removes them. |
| R5 — Optional persistent storage | An opted-in skill can explicitly reuse saved work in later runs within its owner/matter/skill namespace, including a personal namespace for projectless chat. Run deletion retains it. Owners can inspect, export and reset it with execution disabled; hard owner/matter deletion removes it. |
| R6 — Optional bundled helpers | An opted-in skill can call declared installed Python helpers with selected JSON data. Missing or mismatched bundles refuse execution. Calls are isolated and bounded; storage and helper execution can be enabled independently. |
| R7 — Confidentiality under compromise | A compromised approved helper cannot access unrelated matter data or cause protected content to reach an unauthorized destination, including through later model/tool calls and saved-work reuse. |

Helper tools are available to chat, query-driven background planning and guarded
root/child execution. Single-inference playbooks, tabular and query-less watch
paths do not gain a tool loop.

## Success and current acceptance

Success means the acceptance criteria hold with controlled sample inputs,
including failure, interruption and empty-result cases. R1–R6 have local
acceptance coverage across real storage, queue, helper containers and browser
flows; regression checks passed with controlled providers. **R7's complete
confidentiality acceptance remains pending.** These results describe unpublished
code; they establish no live-provider or legal-quality claim.

## Release conditions

- **Maintainers:** review the shared runtime update under
  [#524](https://github.com/LegalQuants/lq-ai/issues/524) before release.
- **Security reviewers and operators:** record approval for exact scripts,
  dependencies and images; complete R7 acceptance; approve production executor
  separation and operational data handling before helper enablement.
- **Real matter use:** complete selected-document/KB intake and project-policy
  propagation, including DE-294, before enabling real sources and inference.

Capabilities remain disabled by default. Production enablement is a separate
decision; no release date is committed.

## Proposed real orchestration profile (ADR 0038 pending)

The first released orchestration profile should let an owner approve and monitor
one bounded batch of **real skill-backed child work**. An operator enables that
profile; the current sample workflow remains an acceptance fixture, not the
only work the switch can run. An owner supplies an active project and goal,
reviews one to four proposed tasks, and selects approved installed skills and
explicitly authorized matter resources. Research is one canonical example, not
the only child profile. The application supplies the model route, grants, data restrictions, budget and
deadline for exact-plan approval. Children run independently, share bounded
results with the root, and never gain authority from task text or sibling output.

Acceptance requires selected-document/KB checks, project-policy propagation,
DE-294 handoff validation, real gateway-backed child and root execution,
observable progress, halt, partial results, recovery and honest evidence status.
The existing disabled-by-default operator switch must enable this profile after
those gates pass. Optional persistent storage and bundled helpers remain
separate. This expansion does not authorize recursive delegation or generated
code. Until ADR 0038 is ratified, the accepted first-profile scope above remains
the sample demonstration.

Behavior details: [demonstration](../plans/issue-563-demonstration.md),
[run files](../plans/issue-563-workspace.md),
[skill capabilities](../plans/issue-563-skill-capabilities.md).
[Draft operator guidance](../deploy/skill-capabilities.md) covers configuration
and retention.
