# PRD: Governed orchestration and optional skill capabilities

**Status:** Accepted design; bounded implementation released in 0.8.0 (2026-09-30).
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

The initial sample-only preview has been superseded by a bounded experimental
chat. A configured model proposes the plan, approved children apply installed
Contract QA to one fictional agreement, and a model synthesizes their findings.
Outputs remain unverified. Generated code and arbitrary shell execution are
excluded. Recursive delegation, watch/schedule orchestration and substantive
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
flows; regression checks passed with controlled providers. A separate local
model run exercised planning, skill-backed children and synthesis on fictional
inputs; see the [UAT evidence](../uat/adr35-chat/README.md). **R7's complete
confidentiality acceptance remains pending.** These results establish no
production-provider or legal-quality claim.

## Release conditions

- **Maintainers:** review the shared runtime update under
  [#524](https://github.com/LegalQuants/lq-ai/issues/524) before release.
- **Security reviewers and operators:** record approval for exact scripts,
  dependencies and images; complete R7 acceptance; approve production executor
  separation and operational data handling before helper enablement.
- **Real matter use:** complete selected-document/KB intake and project-policy
  propagation, including DE-294, before enabling real sources and inference.

Capabilities remain disabled by default. The bounded model-backed chat
demonstration shipped in 0.8.0 (2026-09-30) behind an operator switch;
production enablement remains a separate decision.

## Proposed: governed runs in chat (ADR 0038 pending)

[ADR 0038](../adr/0038-skill-backed-orchestration-profile.md) proposes moving the
bounded run into the main chat, letting approved children call tools, and adding
a first profile that reads real documents. It is not ratified. The requirements
below are implemented on an unmerged implementation branch, pending ratification
and review; they are in no release, and both profile switches default to off.
The accepted scope above stands for released software.

| Proposed requirement | Acceptance criterion |
|---|---|
| R8 — Runs in chat | The owner starts a run from the chat composer with an operator-enabled profile, approves or rejects the plan, follows progress, halts, and reopens the run after a refresh, all in one thread. Later turns see the delivered answer. |
| R9 — Visibility parity | Everything an ordinary chat turn shows (message fields, receipts, routing and tool-call correlation, audit rows, traces) is available for a run through the same channel. |
| R10 — Capability surface | A profile and a tool that the product does not ship can be added, and are offered, granted, recorded and presented with no other change. |
| R11 — Tools for children | An approved child calls only the tools its profile grants. Refused and failed calls are returned to the model and recorded. Completed calls are not repeated after a restart. |
| R12 — Real documents | With its own operator switch on, a run reads only the documents the owner selected for it, including a chat attachment once it is attached to the project. The answer carries citation results, and the owner's data export includes run data. |
| R13 — Closing an uncertain run | The owner can close an uncertain run without a retry. The unresolved reservation is charged, and a new run can start. |

**Evidence so far.** The plan's
[Implementation status](../plans/issue-662-c1-governed-runs-in-chat.md#implementation-status)
records what was built and how it was checked. Each of R8–R13 has
controlled-provider test coverage on the implementation branch, and the browser
behavior behind R8 was exercised in one recorded walkthrough, driven by an agent,
with a controlled provider. None of the six has human acceptance or a run on a
configured provider, and the changes have had no maintainer or security review.
R12 rests on controlled-provider tests: its limits are placeholders not measured
on real documents, and its quotation checks use only the Citation Engine's exact
and tolerant stages. The plan lists the remaining gaps under "Not done, or not
verified".

Build order and design: [plan](../plans/issue-662-c1-governed-runs-in-chat.md).
Script for human acceptance: [UAT runbook](../runbooks/adr38-runs-in-chat-uat.md).

Behavior details: [demonstration](../plans/issue-563-demonstration.md),
[run files](../plans/issue-563-workspace.md),
[skill capabilities](../plans/issue-563-skill-capabilities.md).
[Draft operator guidance](../deploy/skill-capabilities.md) covers configuration
and retention.
