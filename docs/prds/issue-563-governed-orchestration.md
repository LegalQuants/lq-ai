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

[ADR 0038](../adr/0038-governed-runs-in-chat.md) proposes an orchestrator
model in the main chat, "New harness": an experimental entry in the model picker. It
answers a request that needs nothing read, or plans the request as one to four tasks that
the owner approves and that approved sub-agents carry out, with tools to read the
documents the owner selected and to search the matter's knowledge bases by keyword. A chat
need not be in a matter. The ADR is not ratified. Its direct answer, a run in a chat
that is in no matter, and the selection of a file a knowledge-base search finds amend ADR
0035 D1, D2 and D3, which are Accepted; ADR 0038 D1 gives the words, and they are ratified
with it.
The requirements below are implemented, pending
ratification and review; they are in no release, and both profile switches default to off.
The accepted scope above stands for released software.

| Proposed requirement | Acceptance criterion |
|---|---|
| R8 — Runs in chat | The owner chooses New harness in the chat's model picker (the first row, marked experimental, showing its route) and sends a request from a chat in a matter or in none. The request is an ordinary message, and the reply is one run message in the same thread. While New harness is chosen, Skills, "Keep skills on" and the prompt enhancer are not offered, and a chat whose model is New harness never sends to another model. The owner approves or rejects the exact plan, follows progress as one column of lines, halts, and reopens the run after a refresh. A request that needs nothing read may be answered by the orchestrator itself, with no plan, task or approval; the run says that nothing was read or searched, and the answer is unverified. Later turns see the delivered answer. |
| R9 — Visibility parity | Everything an ordinary chat turn shows (message fields, receipts, routing and tool-call correlation, audit rows, traces) is available for a run through the same channel. The owner can also read, for every call of the run, the system prompt it was pinned to, the opening message sent and the tools offered, compared with a digest recorded when the call went out, and each turn's text and tool calls. The system prompts are versioned files that any signed-in user can read, and a released file is never edited. |
| R10 — Capability surface | A profile and a tool that the product does not ship can be added, and are offered, granted, recorded and presented with no other change. A profile pins skills or prompt files for its roles, and a prompt name is never resolved among skills. |
| R11 — Tools | An approved sub-agent calls only the tools its plan grants. Refused and failed calls are returned to the model and recorded. Completed calls are not repeated after a restart. The orchestrator is offered one tool, `propose_plan`, and one call to it is the plan; nothing is sent back to the model. A plan written out as text, a call to any other tool, and arguments that are not a valid plan each fail the plan, and nothing runs. |
| R12 — What a run reads | A run reads only the documents the owner selected for it (none to eight) and, in a matter, searches by keyword the knowledge bases attached to that matter, which the plan names. In a matter it reads only that matter's files. Outside a matter it reads the owner's files wherever they are filed, under the strictest inference-tier floor and the privilege flag of the matters that hold them. Quotations written with a source marker are checked against the file they name, and the answer carries the counts; a run with nothing to check against says that its answer is unverified. Pseudonymization follows the operator's gateway setting and covers the whole request, what a task reads and the arguments of earlier tool calls included. The owner's data export includes run data, among it the thread excerpt shown to the planning call. |
| R13 — Closing an uncertain run | The owner can close an uncertain run without a retry. The unresolved reservation is charged, and a new run can start. |

**Evidence so far.** The plan's
[Implementation status](../plans/issue-662-c1-governed-runs-in-chat.md#implementation-status)
records what was built and how it was checked. Each of R8–R13 has controlled-provider test
coverage. The browser behavior behind R8 and R9 was exercised
in single runs driven by agents, on a scripted provider and on local models. The first
build's recorded walkthrough was removed from the branch, and none of the present design
is recorded. None of the six has a recorded human acceptance or a run on a configured
provider (the maintainer used the present design on a local model on 2026-10-09 and said
that it passes C1's acceptance statement), and
the changes have had no maintainer or security review. R12 rests on controlled-provider
tests and those single runs: its limits are placeholders not measured on real documents,
its quotation checks use only the Citation Engine's exact and tolerant stages, and its
knowledge-base search is by keyword only. On a route that pseudonymizes, the gateway
restores the placeholders it assigned in a plan's arguments, and a plan that still carries
one is refused (ADR 0038, ruling 6). The maintainer ruled on ADR 0038's eleven open
questions on 2026-10-09, and the plan lists the remaining gaps under "Not done, or not
verified".

Build order and design: [plan](../plans/issue-662-c1-governed-runs-in-chat.md).
Script for human acceptance: [UAT runbook](../runbooks/adr38-runs-in-chat-uat.md).

Behavior details: [demonstration](../plans/issue-563-demonstration.md),
[run files](../plans/issue-563-workspace.md),
[skill capabilities](../plans/issue-563-skill-capabilities.md).
[Draft operator guidance](../deploy/skill-capabilities.md) covers configuration
and retention.
