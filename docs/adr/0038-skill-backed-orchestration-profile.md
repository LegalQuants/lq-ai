# ADR 0038 — Governed runs in chat and the first profile on real documents

**Status:** Proposed (2026-09-23; rewritten 2026-10-06)
**Extends:** [ADR 0035](0035-governed-orchestration-run-tree.md); retains its run-tree,
authority, budget, recovery and execution decisions.
**Amends:** [ADR 0020 D1](0020-governed-agentic-legal-matter-sessions.md) for run children
only, as stated in D4.
**Tracks:** [#563](https://github.com/LegalQuants/lq-ai/issues/563) and track C1 of
[#662](https://github.com/LegalQuants/lq-ai/issues/662).

## Context

ADR 0035 accepted a governed run tree. Release 0.8.0 ships one bounded profile of
it: a model proposes a plan, the owner approves it, child sessions apply Contract
QA to a fictional agreement, and a root call combines their answers
([#631](https://github.com/LegalQuants/lq-ai/pull/631)). It runs on its own page
under Autonomous, behind `LQ_AI_ORCHESTRATION_CHAT_ENABLED`. The earlier sample
switch no longer exists.

#662 asks for that journey in the main chat, as the base for bringing LegalQuants
OSS skills into LQ.AI. The expected direction is that governed runs replace the
chat-completion path over several releases; this ADR does not authorize that
change (D7). Four properties of the current code shape the decision:

- A run has no link to a chat. Its conversation is a projection of run records.
- A child makes one model call and cannot call a tool. The profile, its skills
  and its limits are constants.
- A run's model calls reach the gateway without a chat or message identifier, and
  the worker that executes runs is not wired into tracing. A run is therefore
  less visible than an ordinary chat turn in receipts, the routing log and traces.
- A capability added today is wired separately into three engines: the chat tool
  loop, the matter-session planner and the run adapters.

An implementation of these decisions exists on an unmerged branch and has had no
maintainer or security review. The plan's
[Implementation status](../plans/issue-662-c1-governed-runs-in-chat.md#implementation-status)
records what was built and what was not verified. Both profile switches default
to off, and the implementation does not merge before this ADR is ratified.

## Decision

### D1 — A run is a turn in the chat thread

The owner starts a run from the chat composer by choosing an operator-enabled
profile, shown as a control beside the model picker. The request is an ordinary
user message. The reply is one assistant message bound to the run's root
autonomous session. It presents the plan, approval, child progress, retained
files and the answer.

Run records stay authoritative under ADR 0035 D4 and D5. The message holds the
link. Root delivery writes the answer into the message in the same transaction
as its audit row and keeps its evidence status. A run that ends without an
answer leaves the message without content, so it is not replayed to later turns.
Approval, rejection, halt and inspection keep their existing owner-only routes.
Chat adds an intake route and no second governance path (ADR 0016 P6).

The binding is to the autonomous session, not to the orchestration root, so
other governed session kinds can later be hosted the same way without a new link.

Preconditions are unchanged: the owner's Autonomous opt-in, a chat inside a
project the profile permits, and one active run per owner (ADR 0035 D1). The
composer states why a profile is unavailable. The planning call receives the
request only, not earlier messages, and the composer says so. Archiving a chat
does not halt its run.

The existing run page remains as a receipt view for runs that have no chat. Its
intake form is removed once chat hosting is accepted.

### D2 — A run is at least as visible as an ordinary chat turn

Whatever an owner or operator can see for an ordinary chat turn must be
available for a run through the same channel: the message's skill, tier,
provider, model, token and cost fields; the chat receipts; chat and message
identifiers on routing-log and tool-call-log rows; audit rows; and traces that
connect the API, the worker, the gateway and the provider. The acceptance table
below is the checklist. The gateway records a truthful purpose for run traffic
instead of labelling it `chat`.

The run message opens on a plain-language progress list with the current step.
Receipts, digests and accounting stay one action away and are never dropped.

Keeping full prompts and tool payloads is outside this ADR, because an ordinary
turn does not keep them either. PRD §5.4 assigns that to an optional self-hosted
LLM-tracing sink at the gateway, which is not implemented. When it is built it
must serve ordinary turns and runs alike, so this rule continues to hold.

### D3 — Profiles, tools and renderers are the capability surface

A **profile** is an operator-enabled registry entry. It names pinned skills by
role, the tools granted in each phase, the resources a run may read, its limits
and its model route. The set is closed and visible to the operator (ADR 0016 P2,
P8). The fictional Contract QA profile becomes the first entry. Supporting
another skill in runs means adding a profile, not engine or interface code.

A **tool** is one governed definition of a capability: input model, handler,
cost quote, safety flags and a plain-language label. The run loop in D4 takes its
tools from this registry. The chat tool loop and the matter-session planner move
to it as they are changed. Every call still passes the single chokepoint.

A **renderer** presents one kind of step or output in the run message. An
unknown kind falls back to a generic presentation, never to an error.

A contract test adds a profile and a tool that the product does not ship. It
checks that they are offered, granted, recorded and presented with no other
change.

### D4 — Approved children may call granted tools

Inside an approved child, the model is offered function schemas for the tools its
profile grants in the current phase, and nothing else. It may request several
calls in a turn. The application executes them one at a time, each as a durable
effect through the chokepoint with its own reservation (ADR 0035 D5, D6). A
refused or failed call is returned to the model as an error result and recorded.
It does not end the child. A profile sets the turn limit; reaching it ends tool
use and requests the answer.

The plan card lists each child's granted tools and readable documents, so
approval of the exact plan is also the consent for that use (ADR 0035 D2).
Destructive and confirmation-required tools are never granted to children
(ADR 0015 D4). Each call is recorded with its tool, outcome, cost and the
model's stated reason. Arguments and results are not copied into audit rows
(ADR 0016 P3).

This amends ADR 0020 D1 for run children: native tool calls within the granted
set replace the closed-choice planner contract. The set stays closed, as in the
chat tool loop (ADR 0015 D1). The root keeps its fixed sequence, and a
single-agent profile is not part of this decision.

### D5 — The first profile on real documents

A second profile runs Contract QA children on documents the owner selects. It
has its own operator switch, so enabling the fictional profile never enables it.
It may run in any active project the owner owns. The project's inference-tier
floor and privilege flag apply at every effect, and the profile's pinned model
route is refused where it does not satisfy them.

**Selection.** The owner selects documents attached to the chat's project. A
file attached only to the chat can be selected; selecting it attaches it to the
project, with an audit row, and the plan card says so. The plan card lists the
selection, and approval covers exactly that list. Every read rechecks selection,
ownership and project attachment (ADR 0035 D3). Only formats the pipeline
ingests are selectable, currently PDF with text, plain text and Markdown. A file
that cannot be read is shown as such and never silently omitted.

**Tools.** These runs may read the selected documents and use run working
files. Bundled helpers and persistent skill workspaces are not granted to them
until the conditions in ADR 0035 D8c and D8d are met. Both may be granted on the
fictional profile where the operator has enabled them.

**Answer.** Each document read is registered as numbered evidence. Quotations in
the delivered answer pass the same citation checks, ledger and gate as a chat
answer, and the message shows the result. An answer whose quotations cannot be
checked is labelled unverified.

**Handoff.** Selected-document authorization, project-policy propagation and
cross-agent handoff validation (DE-294) are implemented and tested before the
switch can be turned on. Document text and child output are data. Neither can
change another child's task, tools or instructions.

**Export.** The owner's data export includes run plans, child results and run
files (ADR 0016 P9). Deletion already follows the owning session, root and user.

### D6 — An owner can close an uncertain run

ADR 0035 D5 stands: an effect with an uncertain outcome is never repeated
automatically, and its reservation is retained. An uncertain run also holds the
owner's single active-run allowance, and no reconciliation action exists today.

The owner may close such a run. Closing ends it without synthesis, keeps
retained work inspectable, converts the unresolved reservation into a charge,
writes an audit row and releases the allowance. Until then the composer names
the run that is blocking a new one.

### D7 — Replacing the chat-completion path needs its own decision

This ADR does not authorize it. A later decision must show that the replacing
engine satisfies D2 in full. It must also provide what ordinary chat provides
today: streamed answers, comparable time to first output, confirmation for
destructive tools, chats outside a project and more than one concurrent run per
owner. It must resolve how the pricing requirement in ADR 0035 D6 applies to
ordinary turns.

## Alternatives

| Alternative | Reason not selected |
|---|---|
| Keep the separate page and link to it from chat | Leaves two conversation surfaces and no follow-up turn; does not meet #662 C1. |
| Select a profile by attaching a skill | Chat skills can be combined, kept on and forked by users; a profile is one operator-pinned artifact. A skill chip would hide a change of execution engine. |
| List the orchestrator in the model picker | The picker is where the user chooses provider and model (ADR 0011); a profile pins its own route. |
| Let the chat model start a run through a tool call | Planning would run on an unpinned model before any allowance is disclosed (ADR 0035 D2). The tool-confirmation record is a short-lived resume, not approval of an exact plan. |
| Stream run progress over the message stream | Runs outlive requests, and ADR 0035 defers streaming. |
| Keep the closed-choice planner for children | One choice per turn, stopping on anything else, limits what a skill can do. The chat tool loop already uses native calls on a closed set. |
| Authorize chat attachments by ownership alone | Adds a second rule to the read boundary; attaching to the project keeps one. |
| Keep a full prompt record in the application now | Exceeds what an ordinary turn keeps; it belongs with the PRD §5.4 sink, for both. |
| Allow open-ended agents to choose skills, tools or sources | Task prose would become authority and defeat the approved-scope boundary. |
| Move orchestration to a separate harness service | Duplicates the governance path without solving authorization. |
| Replace the chat-completion path now | The gaps listed in D7. |

## Consequences

- The work is larger than moving the demonstration page. It should land as
  ordered, separately reviewed changes: chat hosting and D2 on the fictional
  profile; the registries; the child tool loop on the fictional profile; then
  the real-document profile behind its switch.
- Release 0.8.0 shipped the orchestration tables, so schema changes must upgrade
  deployed databases. The profile column's enumerated check becomes a pattern
  check validated against the registry.
- The changes touch authorization, audit and the gateway, and are routed to
  security review. The gateway purpose change can proceed as its own small change.
- PRD §3.1 and §3.10, the feature PRD, the OpenAPI sketches, the schema
  document, HONEST-STATE and the observability guide change with the code.
- Not decided here: sources and connectors in runs; helpers and persistent
  workspaces on real documents; a tool loop for the root; a single-agent profile;
  runs started by schedules or watches; recursion; streaming; full prompt capture.

## Acceptance and release

**Visibility (D2).** Each row must hold for a run in main chat.

| Channel | An ordinary turn provides | A run must provide |
|---|---|---|
| Message | Applied skills, tier, provider, model, tokens and cost on the assistant message; content found by chat search and included in export | The same fields on the run's message, filled at delivery |
| Receipts, model calls | Provider, model, tier, tokens, latency and anonymization, from routing-log rows carrying the chat identifier | Chat and message identifiers on every run model call |
| Receipts, audit | Audit rows for the chat | The bound session's audit rows in the same feed |
| Tool call log | Chat and message identifiers on each row | The same, together with the session identifier |
| Routing-log purpose | A truthful purpose label | A truthful purpose label for run traffic |
| Traces | One trace across API, gateway and provider | Traces connecting API, worker, gateway and provider, with spans for the run and for skill use |
| Citations | Citation checks, ledger and gate when the turn retrieves | The same for an answer that quotes selected documents (D5) |

**Chat hosting (D1).** On the fictional profile, in main chat: plan approval and
rejection, child progress, the combined answer, retained files and execution
records, halt, and reopening after refresh.

**Tool loop (D4).** A child calls a granted tool and uses its result. A call
outside the grant is refused, returned to the model and recorded. The turn limit
ends tool use and still yields an answer. Recovery across a worker restart
reuses completed effects and repeats none.

**Real documents (D5).** An enabled run executes two approved Contract QA
children on selected project documents, enforces exact-plan consent and bounded
concurrency, shows changing progress and produces a root answer with its
evidence status. Tests reject unselected or revoked documents, a chat attachment
that was not attached to the project, widened child grants, stale approval and
hostile handoff text. They also exercise halt, partial results, budget
accounting, closing an uncertain run (D6) and the export of run data.

Controlled-provider tests establish the contract. A configured-provider
acceptance run is required before claiming live operation. Each profile's switch
defaults to off. Maintainer and security review, including ADR 0035's
helper-specific gates, remain release requirements. Ratification of this ADR
precedes merging the implementation.

## Supporting evidence

The [UAT record](../uat/adr35-chat/README.md) shows provider timeouts leaving
runs uncertain, which D6 addresses. [#662](https://github.com/LegalQuants/lq-ai/issues/662)
and its research note describe the capability tracks that D3 serves. The
[feature PRD](../prds/issue-563-governed-orchestration.md) defines the
requirements this ADR extends.
