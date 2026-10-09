# ADR 0038 — Governed runs in chat: an orchestrator model

**Status:** Proposed (2026-09-23; rewritten 2026-10-06; rewritten again 2026-10-09, after
the maintainer redirected C1 on 2026-10-07 and 2026-10-08; D8 added 2026-10-09; the maintainer's
rulings on the open questions recorded 2026-10-09). Nothing in it is ratified.
**Extends:** [ADR 0035](0035-governed-orchestration-run-tree.md); retains its run-tree,
authority, budget, recovery and execution decisions.
**Amends:** [ADR 0020 D1](0020-governed-agentic-legal-matter-sessions.md) for run
sub-agents only, as stated in D4. D1 also proposes an amendment to ADR 0035 D1 (a direct
answer). ADR 0035 stays Accepted and its text is unchanged; the amendment is a separate
draft and needs its own ratification.
**Touches:** [ADR 0011](0011-transparency-first-model-selection.md): its model picker now
holds one entry that is not a provider model (D1).
**Tracks:** [#563](https://github.com/LegalQuants/lq-ai/issues/563) and track C1 of
[#662](https://github.com/LegalQuants/lq-ai/issues/662).

The file keeps its original name so that existing links resolve. The orchestrator is no
longer skill-backed (D3).

## Context

ADR 0035 accepted a governed run tree. Release 0.8.0 ships one bounded profile of it: a
model proposes a plan, the owner approves it, sub-agents apply Contract QA to a fictional
agreement, and a root call combines their answers
([#631](https://github.com/LegalQuants/lq-ai/pull/631)). It runs on its own page under
Autonomous, behind `LQ_AI_ORCHESTRATION_CHAT_ENABLED`.

#662 asks for that journey in the main chat, as the base for bringing LegalQuants OSS
skills into LQ.AI. The expected direction is that governed runs replace the
chat-completion path over several releases; this ADR does not authorize that change (D7).
At 0.8.0 four properties of the code shaped the decision:

- A run had no link to a chat. Its conversation was a projection of run records.
- A sub-agent made one model call and could not call a tool. The profile, its skills and
  its limits were constants.
- A run's model calls reached the gateway without a chat or message identifier, and the
  worker that executes runs was not wired into tracing. A run was therefore less visible
  than an ordinary chat turn in receipts, the routing log and traces.
- A capability added then was wired separately into three engines: the chat tool loop, the
  matter-session planner and the run adapters.

### The maintainer's direction

A first build of this ADR put a run in the chat as a control beside the model picker, with
a skill as the orchestrator, and ran Contract QA either on the fictional agreement or on
documents the owner selected. After using it the maintainer gave a different direction on
2026-10-07 and added to it on 2026-10-08:

1. The orchestrator is an experimental model chosen in the model picker, not a skill.
   While it is chosen, Skills, "Keep skills on" and the prompt enhancer are not offered.
   Its name is **New harness**.
2. New harness is the base for tracks C1 to C7 of #662.
3. The run message is one column of lines. Each line is a live one-line summary of what is
   under it and opens on its trace. Two sub-agents are two lines to click.
4. C1's acceptance is the statement quoted under "Acceptance and release".
5. New harness has a system prompt of its own, and the owner can read it.
6. (2026-10-08) New harness is the first row of the model list, still marked experimental.
7. (2026-10-08) A chat need not be in a matter.

The same direction set these points for the build: one picker entry and a Send button;
lines that stay after the answer; no profile choice, because the context decides what a
run works on; the fictional demonstration out of chat, kept as a test fixture; sub-agents
that run one general instruction set pinned by New harness; a planning call that sees the
recent thread; an orchestrator that may answer directly, with no sub-agents and no
approval; sub-agents that may search the matter's knowledge bases; a plan handed over as a
native tool call; pseudonymization where the operator's gateway setting says to for the
routed tier; and thinking control in the gateway for Ollama. These are directions to the
build. The design below is proposed, and none of it is ratified.

An implementation exists on an unmerged branch and has had no maintainer or security
review. The build plan's
[Implementation status](../plans/issue-662-c1-governed-runs-in-chat.md#implementation-status)
records what was built, by increment, and what was not verified. Both profile switches
default to off, and the implementation does not merge before this ADR is ratified.

## Decision

### D1 — A run is a turn in the chat thread, started by choosing New harness

**The picker.** The model picker in the chat composer holds one entry that is not a
provider model: **New harness**. It is the first row of the list, in an Experimental
group, with an `experimental` chip, and it shows the `provider/model` its runs are pinned
to, as an alias shows its target (ADR 0011). The first build of this ADR rejected a picker
entry because the picker is where the user chooses a provider and a model; the maintainer
directed otherwise, and the chip and the shown route are how the entry says what it is.
The server names the entry (`composer_profile` on the run-profiles read) and the registry
refuses a second one, so the browser never chooses between profiles. The choice is kept
for each chat and survives a reload. The entry is never sent as the message's model.

**What choosing it changes.** The button says Send. The skill picker, "Keep skills on",
the prompt enhancer and the button that attaches a knowledge base are not offered, and the
slash popover stays closed, because a run uses none of them. A chat whose model is New
harness never sends to another model in its place: while New harness cannot be checked or
used in that chat, Send waits and says why. Choosing an ordinary model brings the controls
back.

**Send.** The request becomes an ordinary user message. The reply is one assistant message
of kind `run`, bound to the run's root autonomous session. Sending authorizes one planning
call within a disclosed allowance. Nothing else runs until the owner approves a plan.

**What the planning call is shown.** The request; the chat's recent messages; the names of
the selected documents, never their contents; the names of the matter's knowledge bases;
today's date (UTC); and the run's limits. The recent messages are at most 20 earlier user
and assistant messages that have content and no error. Each is cut to 6,000 characters and
marked when cut, the whole excerpt is at most 32,768 bytes with the oldest dropped first,
and a source marker `(Source: [N])` in an earlier run's answer is rewritten to the name of
the file it pointed at, because source numbers belong to one run. The excerpt and the date
are read once when the request is accepted and kept in the run's planning snapshot
(version 3). A replay therefore sees the thread the first attempt saw, the owner can read
what was sent, and the excerpt is exported and deleted with the run. A request that with
its excerpt is too long for one planning call is refused before anything is stored.

**What the planning call does.** It is one call, offered one tool, `propose_plan` (D4).
Either it calls the tool, and the arguments are a plan of one to four tasks that the owner
approves, as that exact plan, before any sub-agent runs; or it replies without calling the
tool, and the reply is the orchestrator's own answer.

**The direct answer (amends ADR 0035 D1; needs its own ratification).** A complete reply
with no call is the orchestrator's own answer, or one question back. It is delivered at
once and the run ends `completed`, with no plan, no task and no approval: sending the
request authorized the one planning call, and nothing beyond it ran. Nothing was read or
searched for that answer. The run's one line reads "Answered directly" with "no plan ·
nothing read", and the answer is unverified. If documents were selected, quotations it
marks with a source are still checked and reported; the orchestrator read none of them, so
a quotation it invented shows as not matching. The prompt tells the model never to answer
this way a question that depends on what a document or a knowledge base says. That is an
instruction, and no code enforces it.

What code does enforce: the store delivers an answer only for a run whose intake records
that the plan is handed over by tool call, and only if the answer equals the planning
call's own stored reply. A reply that is incomplete, empty or holds control characters
fails the plan, and so does a reply that writes the plan out as text, or the tool call as
JSON, in place of calling the tool (stop reason `plan_not_handed_over`); neither is shown
as an answer. An answer longer than 16,384 characters is cut and marked. The answer is
delivered whatever the planning call cost within the root's whole allocation; a charge past
that halts the run when the call settles, as for any effect. Migration 0073 lets a run end
`completed` with no plan revision.

ADR 0035 D1 permits one immutable batch of one to four children. The proposed amendment
changes it to *at most* one batch, and adds that a root whose profile allows it may
instead deliver the reply of its one planning call as its answer and end with no batch;
such a root makes no other model call, admits no child, reads no document and calls no
tool. A sentence added to ADR 0035 D2 says that where a root answers without a batch there
is nothing to approve, and that the owner is shown that the answer came from the planning
call alone. The barrier D2 protects is the admission of work (children, tools, document
reads, spend past the planning allowance), and a direct answer admits none of it. What
changes is that a model's text reaches the owner without a plan approved first, as it does
in an ordinary chat turn. Only New harness answers this way; the fictional profile plans
in text, and a reply of its that is not a plan fails as before.

**A chat outside a matter.** *Authorization path; needs security review.* A chat need not
be in a matter (the API calls a matter a project). Migration 0072 lets
`orchestration_roots.project_id` be null. Such a run is never privileged, and a plan that
says otherwise is refused. Its inference-tier floor is the profile's own. Nothing is
attached to a matter for it, it reads only the owner's files that are filed in no matter
(D5), and it searches no knowledge base. A file in a matter carries that matter's tier
floor and privilege flag, which a run with no matter does not apply. The fictional profile
still needs its dedicated matter.

**The fictional demonstration is out of chat.** The composer does not offer the 0.8.0
fictional profile (`model_demo_v1`). It stays a test fixture, and its retained runs stay
readable. Its stand-alone route, `POST /autonomous/orchestration/chat-runs`, still starts
it where `LQ_AI_ORCHESTRATION_CHAT_ENABLED` is on, and tests depend on that. The 0.8.0
page no longer starts runs. It is the receipt view of any run, and it tells the reader to
start a run from a chat. Upgrade note for operators who enabled the 0.8.0 page: its
intake form is gone.

**Records and delivery.** Run records stay authoritative under ADR 0035 D4 and D5. The
message holds the link. Root delivery writes the answer into the message in the same
transaction as its audit row and keeps its evidence status. A run that ends without an
answer leaves the message without content, so it is not replayed to later turns.
Approval, rejection, halt, closing and inspection keep their existing owner-only routes.
Chat adds an intake route and no second governance path (ADR 0016 P6). The binding is to
the autonomous session, not to the orchestration root, so other governed session kinds can
later be hosted the same way without a new link.

**Preconditions.** The owner's Autonomous opt-in; an operator-enabled profile whose route
is priced and whose total cap can fund planning, one task and synthesis; a chat that is not
archived; and one active run per owner (ADR 0035 D1). A matter is not required. The
composer states why New harness is unavailable. A run that holds the owner's single
active-run allowance, including a run whose plan waits for approval, blocks Send in every
chat, and the composer names that run. Archiving a chat does not halt its run.

### D2 — A run is at least as visible as an ordinary chat turn

Whatever an owner or operator can see for an ordinary chat turn must be available for a run
through the same channel: the message's applied-skills, tier, provider, model, token and
cost fields; the chat receipts; chat and message identifiers on routing-log and
tool-call-log rows; audit rows; and traces that connect the API, the worker, the gateway
and the provider where tracing is configured. The acceptance table below is the checklist.
The gateway records a truthful purpose, `orchestration_run`, for run traffic instead of
labelling it `chat`. A run's spans carry identifiers and labels only.

**One column of lines.** Under its status line the run message is one column: the plan
line, one line for each task, and the answer line. A run the orchestrator answered itself
has one line. Each line is a native fold. Its closed line is a one-line summary of that
part of the run, with the figures that belong to it (for the plan, the task count and the
total cap; for a task, its latest step while it runs and afterwards what it did, such as
documents read, searches made and model calls, with its spend; for the answer, the
quotation checks), and it opens on that part's trace. The lines stay after the answer is
delivered. In the chat every line is closed except the plan line while it waits for
approval. A task's topic is model-written and is shown as text, as is every other string
from the run's records, a document or a model; none of it is rendered as markup.

**Receipts.** Receipts, digests and accounting are one fold at the foot of the column.
Nothing is dropped. The receipt page, `/lq-ai/autonomous/orchestration/chat/<run>`, shows
the same column with every line open and no chat around it.

**How each call was set up.** Under the plan line, the direct line, each task line and the
answer line, a fold named "How this run was set up" shows each model call of that session:
the pinned system message (its name, version and digest, and its text), the opening user
message, and the tools offered, in full. Beside the reply to a call, in the plan card, in a
task's steps, under the answer line and on the plan line of a run that has no plan,
"What the model wrote" shows the text and each tool call with its arguments, as text; the
direct line has no such fold, because its reply is the answer drawn under the run (it has the
set-up fold and "Receipts"). Both come from an owner-only read,
`GET /autonomous/orchestration/{root_id}/sessions/{session_id}/trace`. The opening message
is not stored. It is rebuilt from the run's records by the function that built it for
sending, and compared with the digest recorded when the call went out; the read reports
`matches`, `differs`, `not_recorded` or `not_rebuilt`. The read shows what the application
sent before any pseudonymization at the gateway. A later turn's full request is not kept,
only its reply and tool calls. Document text that a read returned and passages that a
search returned are not in it. The two prompt texts can be read before anything is sent,
by any signed-in user, from the "Limits and tools" fold of the composer strip, which names
each prompt and its version (`GET /autonomous/orchestration/prompts/{family}/{name}`).

**A run that ended before it had a plan.** A run with no plan that did not answer by itself
(it failed, was halted, expired or was closed, or its first call is uncertain) still has a
plan line that opens. It offers "How this run was set up" for the call that was meant to make
a plan, "What the model wrote" for that call's reply, and "Receipts", so that a refused plan
can be read: for `plan_not_handed_over` the text the model wrote where a tool call was
expected, and for `plan_has_placeholders` the `propose_plan` call with the placeholder in its
arguments.

**The applied-skills row.** New harness applies no installed skill (D3), so the message's
`applied_skills` is empty and the answer carries no skill chip. The run message is headed
"New harness v<N> → provider/model", where N is the version of the orchestrator prompt the
run pinned, with an `experimental` chip. The heading is a label and opens nothing. The
orchestrator's pinned prompt, with its digest, is in the receipts, and each call's pinned
prompt is named in "How this run was set up".

Keeping every request and every tool payload is outside this ADR, because an ordinary turn
does not keep them either. PRD §5.4 assigns that to an optional self-hosted LLM-tracing
sink at the gateway, which is not implemented. When it is built it must serve ordinary
turns and runs alike, so this rule continues to hold.

### D3 — Profiles, tools and renderers are the capability surface; New harness is instructed by prompt files

A **profile** is an operator-enabled registry entry. It names what instructs each role
(pinned skills, or the engine's own versioned prompt files), the tools granted in each
phase, the resources a run may read, its limits and its model route. The set is closed and
visible to the operator (ADR 0016 P2, P8). Supporting another skill in runs means adding a
profile, not engine or interface code.

Two profiles are registered. `model_demo_v1` is the 0.8.0 fictional Contract QA profile,
kept as a test fixture and for its retained runs; installed skills instruct it, and it
plans in text. `new_harness_v1` is **New harness**, the one profile the composer offers
(D1). It has its own operator switch, `LQ_AI_NEW_HARNESS_ENABLED`, and its own pinned
route. Enabling one never enables the other.

**The system prompt is a prompt file, not a skill.** The orchestrator and the sub-agents of
New harness are instructed by the engine's own prompt files, `new_harness/orchestrator.v2`
and `new_harness/subagent.v2`, in `api/app/autonomous/orchestration/prompts/`. A file's
whole text is the system message of the session it pins. Nothing is added to it and
nothing is substituted in it. The facts of one run go in the opening user message, which
one function builds from the run's own records in labelled sections: the step, the request,
the chat so far, the documents by number and name, the knowledge bases by name, today's
date, the limits, and on the combine step each task's result. It carries no document text
and no instructions. Sending uses that function and so does the trace read (D2), and tests
compare what the read rebuilds with the request bodies a controlled provider recorded.

A skill would sit in the skill library, appear in the ordinary skill picker and be written
under the answer as a skill chip. A prompt file is none of these: it is not in the library,
it cannot be attached to a chat, and any signed-in user can read it. This follows PRD §1.3,
which holds that there is no hidden layer between the user's prompt and the model's output
that the user cannot inspect.

A released file is never edited. A change is a new file (`orchestrator.v3.md`). Version 1
of each prompt stays beside version 2, so a retained run can still show the exact text it
ran on, and a pin whose digest no longer matches its file is refused. A run pins a prompt
by name and digest under its own kind, `prompt`, beside `skill`. Every place that resolves
a pin reads from the place its kind names, so a prompt name is never looked up among
installed skills and a skill name never among prompts. A skill pin serializes without its
kind, as it did before, so a plan retained from 0.8.0 keeps the hash its approval is bound
to (`test_contract_versions.py`). The prompts are engine prompts and are reviewed as code.
Neither needs an attorney's attestation (ruling 1).

With Skills hidden, a skill would reach New harness only when the orchestrator assigns
one. That is track C2 and depends on ADR 0035 D3. It is not built.

**One composer profile.** One registry entry has `composer` set. `register_profile`
refuses a second, because which of two profiles a request would run is a decision the
registry does not hold.

**Thinking control.** *Gateway; security boundary; needs security review.* The gateway's
chat-completion request accepts an optional `reasoning_effort` (`none`, `minimal`, `low`,
`medium` or `high`). The Ollama adapter maps it to `think`. The OpenAI and Azure OpenAI
adapters send it as it is, since it is OpenAI's own parameter. The Anthropic adapter sends
nothing for it. On a reasoning model hidden reasoning counts against the output limit,
which is why a run with a fixed limit needs the control. A profile's route may carry an
effort (`LQ_AI_NEW_HARNESS_REASONING_EFFORT`). It is part of the bound policy and so of
each call's identity, and it is omitted when unset, so a 0.8.0 call keeps its identity.
New harness sends none unless the operator sets one (ruling 5). The model's
reasoning text is not kept or shown.

**A run's terms are frozen in its intake.** The limits a run states to its models and is
held to, and how its plan is handed over, are copied from the profile into the intake when
the request is accepted: the turns that may use tools in a task, the task answer length,
the combined answer length, the characters one read returns, and `planning` (`text` or
`tool`). The run's messages state those numbers and the engine holds the run to the same
ones, so a later change to the profile changes neither for a retained run. An intake
recorded without terms reads its profile's present limits and plans in text. The wording
of the assembled messages still comes from the code at the time of each call (D7).

A **tool** is one governed definition of a capability: input model, handler, cost quote,
destructive and confirmation flags (a run refuses a tool that sets either) and a
plain-language label. The run loop in D4 takes its tools from this registry. The chat tool loop and the
matter-session planner are not moved to it by this ADR; they move as they are changed.
Every call still passes the single chokepoint.

A **renderer** presents one kind of step or output in the run message. An unknown kind
falls back to a generic presentation, never to an error.

A contract test adds a profile and a tool that the product does not ship. It checks that
they are offered, granted, recorded and presented with no other change.

### D4 — Approved children may call granted tools

**Sub-agents.** ADR 0035 calls a sub-agent a child, and the heading keeps that word so
that links to it hold. Inside an approved task, the model is offered function schemas for
the tools its plan grants in the current phase, and nothing else. It may request several
calls in a turn, at most eight; calls past eight are dropped without a result, and the
prompt says so. The application executes them one at a time, each as a durable effect
through the chokepoint with its own reservation (ADR 0035 D5, D6). A refused or failed call
is returned to the model as an error result and recorded. It does not end the task. New
harness allows five turns that may use tools. One further turn without tools then asks for
the answer, so a task makes at most six model calls. A sub-agent's answer is Markdown,
stored whole as one finding, at most 12,000 characters. An answer that runs past a limit
is cut at it and marked in the text, and is not discarded.

New harness grants four tools: Read a selected document (`read_document`), Search the
matter's knowledge bases (`search_knowledge_base`), Save a working note (`save_note`) and
Read back a working note (`read_note`). A task is not offered `read_document` when the run
selected no document, nor `search_knowledge_base` when the run lists no knowledge base; a
plan may grant a subset of what the operator allows. No tool that leaves the deployment is
granted. The plan card lists each task's granted tools, the documents it may read and the
knowledge bases it may search, so approval of the exact plan is also the consent for that
use (ADR 0035 D2). Destructive and confirmation-required tools cannot be registered for
runs (ADR 0015 D4). Each call is recorded with its tool, outcome, cost and the model's
stated reason. Arguments and results are not copied into audit rows (ADR 0016 P3).

This amends ADR 0020 D1 for run sub-agents: native tool calls within the granted set
replace the closed-choice planner contract. The set stays closed, as in the chat tool loop
(ADR 0015 D1). The orchestrator's combine step is one call that is offered no tool.

**Two tool-calling changes in the gateway.** *Security boundary; needs security review.*
The Ollama adapter names a tool result after the call it answers, taking the name from the
earlier call that bears the same identifier, so that two results in one turn are each
matched to their own call. It
also no longer escapes non-ASCII characters in a tool call's arguments, because an escape
makes the string longer than the text it stands for and the application bounds a call's
arguments in bytes.

**The orchestrator's one terminal tool.** The planning call is offered one tool,
`propose_plan`, and nothing else; the effect adapter refuses any other set of schemas on
that call. The arguments are one object with one member, `tasks`: one to four tasks, each
with five text fields (`topic`, `question`, `boundaries`, `output_contract`,
`stopping_condition`). The application reads them with the strict parser that read a plan
written as text. That parser refuses duplicate keys, an unknown member and a task with an
extra field. The tool is terminal. Nothing is sent back to the model and no handler runs,
so planning stays one model call, and the tool is not in the run tool registry, whose
shipped set a test pins. The tool's schema limits each long field to 2,048 characters and
the topic to 256, and the application caps one call's arguments at 49,152 bytes. More than
one call, a call to another name, and arguments that are not a valid plan fail the plan
(`invalid_proposal`). A plan with more tasks than the total cap can fund fails as
`unfunded_plan`. A plan written out as text fails as `plan_not_handed_over` (D1). A plan
from a pseudonymized call that carries a placeholder fails as `plan_has_placeholders`
(D7). The fictional profile keeps its text plan. The orchestrator has no other tool: it
cannot read a document or search, so a question about a document always goes through a
plan.

**For track C7: the gates between a chat tool and a run.** The chat tool loop and the run
tool loop share no tool definition. A chat tool is a `ToolSpec` in the chat's allowlist
(`api/app/chat/tool_schemas.py`); a run tool is a `RunTool` in
`api/app/autonomous/orchestration/tools.py`. A case-law lookup, an authority lookup or an
MCP tool therefore does not reach a sub-agent, and several separate gates stand in the
way. Bringing one into a run means opening each gate on purpose, with security review. The
gates found in the code:

1. No run tool has the intent. A profile's grants are computed from the intents of its
   registered tools, and none has `retrieve_caselaw` or `call_mcp_tool`.
2. The boundary does not implement the intent. `constrain_call` refuses an intent outside
   its implemented set, which holds neither `retrieve_caselaw` nor `call_mcp_tool`.
3. The run's scope names no source. The operator policy lists none and an intake's scope
   carries no source name, and the authority path in the boundary refuses a source the
   scope does not name.
4. The egress ceiling is 0. The operator policy and every intake set it, and source
   binding refuses a source whose egress tier is above it.
5. The case-law source is a passthrough in the source registry and has no response
   adapter, and source binding refuses a source with none.
6. When a run pseudonymizes, source binding requires the gateway's authority-anonymization
   version and the provider's outbound pseudonymization setting. The default entries for
   GovInfo, EDGAR and EUR-Lex leave that setting off, so binding refuses them unless the
   operator turns it on.
7. A task's call is accepted only if its name is in the plan's grant list for the phase.
   Any other name is refused as `tool_not_granted` and recorded.
8. A grant must be legal for its phase (`PHASE_GRANTS`), and a destructive or
   confirmation-required tool cannot be registered.

### D5 — What a run reads, and how its answer is checked

**Documents are optional.** A run selects none to eight documents. With none, no task is
offered `read_document`. In a matter, the selectable files are the matter's files plus
the owner's own files named as candidates, typically chat attachments. Selecting a
candidate attaches it to the matter when the request is accepted, with an audit row
(`project.file_attached`), and the plan card says so. Outside a matter only named
candidates are listed and nothing is attached. The composer starts from the documents the
last run in this chat read, so a follow-up keeps them after a reload; the owner can change
the selection. The plan cannot propose matter documents. The owner supplies them. The plan
card lists the selection, and approval covers exactly that list. Every read rechecks
selection, ownership and matter attachment (ADR 0035 D3). Only formats the pipeline
ingests are selectable, currently PDF with text, plain text and Markdown. A file that
cannot be read is shown with its reason and is never silently omitted. The whole selection
is refused if any file is missing, another owner's or unreadable.

**The file rule: a run never takes a file out of its matter.** *Authorization path; needs
security review.* One rule decides which files a run may read. It is applied at intake, at
every policy check while the run is live, and at each read.

- A run in a matter reads the owner's own, undeleted files that are attached to that
  matter.
- A run outside any matter reads the owner's own, undeleted files that are filed in no
  matter.
- A file that a matter holds carries that matter's tier floor and privilege flag. A run
  with no matter does not read it; the composer lists it as `in_a_matter`. A run in one
  matter does not accept, as a candidate to attach, a file that only another matter holds;
  it is listed as `in_another_matter`. The owner can attach the file to the second matter
  themselves, which is their recorded action, and it is then readable there.

Ordinary chat is looser: it reads any file the owner owns. The maintainer has ruled
that a run outside a matter may read a matter's file on that matter's terms (ruling 4);
that is not built, and this section describes the branch.

**Evidence is per run.** A source is a selected document or a file one of the run's
searches found. For a run with a source, the delivered answer's quotations are checked. A
quotation is recognised when it is written exactly as `"quoted words" (Source: [N])`; it
is looked up in the whole text of the file that source number N names, by the Citation
Engine's exact stage and then its tolerant stage, with its ledger and its gate, on the
run's chat message. No judge model is called, because a judge call would be neither a
priced nor a reserved effect. A quotation neither stage matches is recorded as not
matching, which flags the gate. It is never dropped. The message shows counts: quotations
checked, matched and not matched; quotations whose marker names no source of the run, or
that fall past the limit of 64 checked per answer; and quoted passages of 20 or more
characters that have no marker. The last two groups were not checked. The application
reports which marked quotations matched a file. That is all it reports. A match shows that
the words are in the file; it does not show that the task was shown that passage, that the
words support the point they are cited for, or that nothing relevant was left out. A run
with no source is labelled unverified, and the note under the answer says the answer came
from the model alone. A direct answer is unverified (D1).

The pattern that recognises a quotation is the Citation Engine's, shared with ordinary
chat (`api/app/citation/extraction.py`, mirrored in the web at `citations/state.ts`). A
quotation wrapped in Markdown emphasis, `*"words"* (Source: [N])`, is not recognised, and
the answer is reported as having quotations that were not checked. Both prompts tell the
model to write quotations plainly. The pattern is to accept emphasis (ruling 2); that is
not built.

**Knowledge-base search.** *Authorization path; needs security review.* A run in a matter
lists the knowledge bases attached to that matter when the request is accepted: the
owner's own, not archived, oldest attachment first, at most 16. The composer says how many
more are attached and not searched. The owner does not pick them. They are named in the
intake and in the plan, so approving the plan is the consent. A task searches them with
one registry tool, `search_knowledge_base`, by keyword.

- The search uses the full-text index only. No query embedding is requested, so nothing is
  sent to a model and a search costs nothing. A passage is found only when it contains
  every word of the query. A search returns at most five passages, within the characters
  the task has left to read.
- Each search rechecks, in the same transaction and before reading, that a listed
  knowledge base is still the owner's, not archived and still attached to the matter. One
  that is not is not searched, and that never ends the run.
- A search that fails for one knowledge base is counted and skipped. The call completes
  and tells the model how many knowledge bases were listed, searched, failed, and how many
  passages were withheld. A failed search never ends the run.
- A passage is shown only when its file is the owner's own, is not deleted, and is not
  held by another matter unless this matter holds it too. Any other passage is withheld
  and counted, for the reason in the file rule.
- A run outside a matter searches none.

**Source numbers.** The selected documents are numbered 1 to D when the request is
accepted. A file a search finds is numbered when it is found, in the block of numbers of
the task that found it. Task k (1 to 4) numbers its files from D + (k − 1) × 25 + 1, in
order of first sight, at most 25 files per task. Tasks run side by side, and separate
blocks keep two tasks from giving one number to two files. The largest number is 108. The
numbers are recorded in the search step's receipt with the file identifiers and file
names, never passage text. They are read back from there to resolve a marker, to list the
found files under the answer, and to rewrite an earlier answer's markers in a later run's
thread. A quotation from a found file is checked like a quotation from a selected
document.

**Pseudonymization follows the operator's setting.** *Authorization path; needs security
review.* Under the earlier rule every shipped profile required pseudonymization on every
tier, and a run was refused unless the gateway pseudonymized at the routed tier. New
harness expects pseudonymization exactly when the gateway's `anonymization` setting
applies it at the routed tier and the matter is not privileged. Each call's receipt
records what was applied. A response that reports otherwise is refused as untrusted. A
call whose gateway configuration revision differs from the one recorded at intake is
refused, so a setting changed after the request was accepted is not applied silently. The
fictional profile keeps the earlier rule. Where the setting applies none at the routed
tier, text is sent as written and the composer says so.

What is pseudonymized is message text: the request, the thread, the task text a sub-agent
receives, and the model's own earlier text. Document text that a task reads, and passages
that a search returns, return to the model as a tool result, which the gateway does not
rewrite (PRD Decision M2-1, so that quotations can be checked against the source).
Tool-call arguments are not rewritten in either direction, so a note, a stated reason or a
search query can carry a placeholder. A call's `anonymization_applied` flag covers message
text only. The composer states this where it says a route is pseudonymized. The case of a
plan that carries a placeholder is in D7.

**Handoff.** Document text, search results, task results, the thread and the request are
data. None of them can change a task, its tools or its limits. Those are enforced in code
and are never read back from the assembled message, which marks any line that could pass
for one of its own section titles. Tests cover hostile text in a document, a task result
and the thread (DE-294).

**Export.** The owner's data export includes run plans, the thread excerpt kept with the
run, task results and run files (ADR 0016 P9). Deletion follows the owning session, root
and user.

### D6 — An owner can close an uncertain run

ADR 0035 D5 stands: an effect with an uncertain outcome is never repeated automatically,
and its reservation is retained. An uncertain run also holds the owner's single active-run
allowance, and before this decision no action released it.

The owner may close such a run (`POST /autonomous/orchestration/chat-runs/{root_id}/close`).
Closing ends it without synthesis, keeps retained work inspectable, converts the unresolved
reservation into a charge, writes an audit row and releases the allowance. Nothing is
retried. Like halt, closing stays reachable after opt-out or a switched-off profile. Only
an uncertain run can be closed. Until then the composer names the run that is blocking a
new one. Migration 0071 adds the `closed` state.

### D7 — New harness stays experimental until its stated limits close; replacing the chat-completion path needs its own decision

This ADR does not authorize replacing the chat-completion path, and it does not remove the
experimental mark. A later decision must show that the replacing engine satisfies D2 in
full, and must resolve how the pricing requirement in ADR 0035 D6 applies to ordinary
turns. These limits of the branch must close first.

- **Opt-in and capacity.** The owner must have turned on Autonomous. One run can be active
  per owner, and it blocks Send in every chat, including while a plan waits for approval
  and is never approved. A matter is no longer required.
- **No streaming.** An answer arrives when the run finishes. A run has a deadline of 7,200
  seconds, and development runs on local models have taken minutes.
- **A run outside a matter cannot read a file that is filed in a matter** (D5).
- **No tools that leave the deployment.** No case-law, authority or MCP tool is granted to
  a run, and the organisation profile does not reach a run. Ordinary chat has them.
- **No library skills** until the orchestrator can assign them (C2, ADR 0035 D3).
- **The orchestrator has one tool and makes one planning call.** It cannot read a document
  or search by itself, so a question about a document always goes through a plan. The plan
  cannot propose matter documents; the owner supplies them.
- **Knowledge-base search is by keyword only, and the owner does not pick the knowledge
  bases.** A search finds a passage only when it holds every word of the query. A run lists
  every knowledge base attached to its matter, at most 16 (D5, rulings 7 and 9; DE-405).
- **A quotation is checked only when it is written exactly as `"words" (Source: [N])`.**
  With Markdown emphasis around it, it is not recognised and the answer is reported as
  having quotations that were not checked (D5). Ruling 2 changes this; not built.
- **A task's answer is plain Markdown of at most 12,000 characters, and a combined answer
  is at most 16,384.** A longer one is cut and marked.
- **A plan is strict.** A plan with any member beyond `tasks`, or a task with any extra
  field, fails as `invalid_proposal`. On one local model, one plan call in six added a
  `request` member before the tool's description told the model to add nothing else.
- **Pseudonymization covers message text only** (D5). On a route that pseudonymizes, a
  note, a stated reason or a search query can carry a placeholder, and the model sees the
  request with names replaced and a document with names as written, so the two can fail
  to match and a search on a name finds little.
- **The wording of the assembled messages is not frozen with the run's terms.** A run's
  limits are frozen at intake (D3); the wording of the messages that state them still comes
  from the code at the time of each call. An upgrade that changes that wording in the
  middle of a run can stop the run with an identity conflict.
- **The trace shows less than a full record.** The model's reasoning is not kept or shown.
  The trace shows each turn's text and tool calls, not the document text a read returned.
  Full payload capture waits for PRD §5.4 (D2).
- **The 0.8.0 page no longer starts runs.** Operators who enabled it lose its intake form
  (D1).
- **Access rules are not in one place.** The rule for what a run reads is the run
  engine's own, and nothing makes a new run tool use it (D8). Not built.
- **Evidence is thin.** Tests use a controlled provider. Development runs on local models,
  driven by agents, are single runs and not a rate. The maintainer used the branch on a
  local model and said on 2026-10-09 that it passes C1's acceptance statement; that is
  one person's judgment of the build and not a measurement. No run has used a hosted
  provider. The requirement below names a configured provider and does not say hosted.

**A plan that carries a placeholder is refused, until the gateway restores it (ruling 6).** On a route that
pseudonymizes, the gateway replaces a name in message text with a placeholder such as
`PERSON_0001` and puts it back in a reply's text, with a mapping that lasts for one
request. It does not touch tool-call arguments. A plan handed over as a tool call (D4)
therefore keeps any placeholder it carries. The calls that follow have their own mappings:
they cannot restore it, and can give the same placeholder to a different name, so a wrong
name could be put into the delivered answer and nothing would report it. A plan from a
pseudonymized call that carries a placeholder fails with its own stop reason,
`plan_has_placeholders`, and nothing runs. The test looks for a token of that shape in
every key and string value of the arguments, including one spelled with a JSON escape. A
call counts as pseudonymized unless its receipt records that none was applied. The
orchestrator's own answer is reply text and is restored as usual.

The cost is that, on a route that pseudonymizes, a request that names a person usually
cannot be planned. With the gateway's example setting `apply_at_tiers: [3, 4, 5]` that is
every route that resolves to tier 3, 4 or 5. The fix is for the gateway to restore the plan
tool's arguments on request. That is a change to the security boundary. It is not made here, and a note for the
security reviewers has been drafted. The alternatives are to plan in text on a route that
pseudonymizes, which makes the orchestrator behave in two ways depending on the route, or to
keep refusing; the maintainer chose the gateway fix. In one development run on a pseudonymizing route, made before the refusal
existed, the plan call's arguments held a placeholder. In two runs made after it, the model
carried none. The refusal itself has been exercised in tests only.

**Not built:** a query embedding for the search (it would be a priced, tier-bound model
call with its own binding); restoring placeholders in the plan tool's arguments at the
gateway; case-law, authority and MCP tools for a run; and the orchestrator reading or
searching by itself.

### D8 — Who may read what is decided in one place, and a run tool cannot read around it

*Authorization path; needs security review. Proposed on 2026-10-09 at the maintainer's
direction that access limits be enforced by structure. Not built.*

**What the code does today.** Access to a file, a knowledge base or a matter is decided by
ownership: each has one `owner_id`, and PRD §5.2's per-resource permissions (read, write,
share, delete) are not implemented. The rule is written in several places. Each resource
route file has its own `_load_visible_*` helper with its own ownership check. The run
engine has its own rule in `api/app/autonomous/orchestration/reading.py` (D5), which
intake, the live policy check and each read share, and ownership comparisons appear in six
files of the run engine. Nothing makes these agree. A run tool handler reaches its data
through the guarded effect path, and the model can name only a document number or a query,
never a user, a matter or a file; but a new handler that issued its own query would not
fail any check. A run rechecks its owner's Autonomous opt-in at each admission and does
not look at the owner's role.

**One access module.** The API gains one module, outside the run engine, that answers who
may read what. It takes a principal (the user, with their role) and an optional matter,
and returns queries: the files that principal may read there, the knowledge bases they may
search there, the matters they may open. Resource routes, the chat path and run tools all
take their rows from it. The D5 file rule moves into it unchanged. Ordinary chat's looser
rule (any file the owner owns) is stated in the same module beside it, so the difference
between the two is one visible line and not two implementations (ruling 4).

**A run tool is handed a reader, not a database.** A run tool handler receives a reader
that the access module built for the run's stored owner and matter. The handler has no
database session and no model classes. It cannot name another owner or another matter,
because the reader has no parameter for either. A contract test fails a registered tool
whose handler module imports a model class or a session, so the rule is held by the test
suite and not by the author remembering it. The eight gates in D4 are unchanged; this is
a ninth, and it is the only one about rows.

**The principal is rechecked while a run executes.** Each admission builds the principal
again from the stored owner. A run whose owner no longer exists, is scheduled for deletion
or may no longer act stops at its next admission, as it does today when the opt-in is
turned off. Which roles may start, approve or read a run is ruling 10; the module is
where that answer is written.

**What this does not do.** It adds no sharing model and changes nobody's access. A
deployment behaves the same before and after it. Its purpose is that a later change to
access (a role limit, a knowledge base shared with a team, the per-resource permissions of
PRD §5.2) is made in one place and reaches chat, the resource routes and every run tool
together.

**Order.** It is a precondition for tracks C2 to C7 adding run tools, so that no tool is
written against the scattered checks. It is not a condition of C1's acceptance. It lands
as its own reviewed change: the module with the run engine moved onto it first, then the
resource routes and the chat path one file at a time (ruling 11, DE-406).

## Rulings on the open questions

The maintainer ruled on all eleven on 2026-10-09, and on the same day said that the branch
passes C1's acceptance statement. A ruling is a direction. It does not ratify this ADR, and
it does not replace security review where the item is on the authorization path or the
gateway. Four rulings ask for something the branch does not do yet. Until each is built,
the decision text above describes the branch as it is, and the item is marked **not
built**.

1. **The prompt texts.** They are engine prompts, reviewed as code. No attorney's
   attestation is required for either.
2. **Quotations in emphasis.** The shared quotation pattern is to accept a quotation
   wrapped in Markdown emphasis, for ordinary chat and for runs alike. It lands as its own
   reviewed change with tests for both. **Not built**: D5 and D7 still describe the strict
   pattern.
3. **A 0.8.0 run in flight at upgrade** need not survive. The upgrade notes are to tell
   operators to finish or halt demonstration runs before upgrading.
4. **The file rules.** A run outside a matter may read a file that a matter holds, and
   then takes on that matter's inference-tier floor and privilege flag. This replaces the
   rule in D1 and D5 that such a run reads only files filed in no matter. Not ruled on:
   whether the same holds for a run in one matter reading a file that only another matter
   holds, and what applies when the selected files come from matters with different
   floors (the proposal is the highest floor, and privileged if any is). Authorization
   path; needs security review. **Not built.**
5. **Reasoning effort** ships empty. Nothing is sent unless the operator sets a level.
6. **The placeholder limit.** The gateway is to restore the plan tool's arguments, as it
   restores reply text. It is a change to the security boundary and goes to security
   review with the drafted note. The refusal (`plan_has_placeholders`) stays until that
   change lands. **Not built.**
7. **Knowledge-base search** stays keyword only for C1, as a stated limit. Looser matching
   and a query embedding are deferred as DE-405.
8. **A direct answer when documents are selected** is allowed, as built.
9. **Which knowledge bases a run lists**: all that are attached to the matter, at most
   16, without the owner picking, as built.
10. **Roles.** A viewer cannot start, approve or reject a run, and can read their own. An
    auditor may read any owner's run and its trace, and can change nothing. This widens
    who can read a run's prompts, plan and task results beyond its owner, so it needs
    security review. Not ruled on: whether an auditor's read includes a run's working
    files and the text of its answer. **Not built**: run routes are still on ownership and
    the Autonomous opt-in.
11. **The order of D8.** The run engine moves onto the access module first. The resource
    routes and the chat path may follow later and do not hold back a C2 to C7 run tool;
    that move is deferred as DE-406.

## Alternatives

| Alternative | Reason not selected |
|---|---|
| Keep the separate page and link to it from chat | Leaves two conversation surfaces and no follow-up turn; does not meet #662 C1. |
| A pill beside the model picker that chooses a profile, and a Propose plan button (the first build) | The maintainer directed that the orchestrator be an experimental model in the picker. Context decides what a run works on, so there is no profile to choose, and a second control would present one engine as two. |
| Run the fictional Contract QA demonstration in chat (the first build) | The maintainer's acceptance statement says the constrained demonstration is not to be reproduced in chat. That build required a document, told the orchestrator that every task was Contract QA and ran every sub-agent on the `contract-qa` skill. The demonstration stays a test fixture. |
| Instruct the orchestrator with a skill (the first build) | A skill sits in the skill library, appears in the ordinary skill picker and is written under the answer as a skill chip. PRD §1.3 rules out a hidden layer; a prompt file is shown with each run. |
| Select a profile by attaching a skill | Chat skills can be combined, kept on and forked by users; a profile is one operator-pinned artifact. A skill chip would hide a change of execution engine. |
| Let the chat model start a run through a tool call | Planning would run on an unpinned model before any allowance is disclosed (ADR 0035 D2). The tool-confirmation record is a short-lived resume, not approval of an exact plan. |
| Hand over the plan as JSON in the reply text | A reply that is a plan cannot be told from an answer without parsing it, and the orchestrator may now answer. Text stays for the fictional profile, and D7 considers it again for a route that pseudonymizes. |
| Stream run progress over the message stream | Runs outlive requests, and ADR 0035 defers streaming. |
| Keep the closed-choice planner for sub-agents | One choice per turn, stopping on anything else, limits what a skill can do. The chat tool loop already uses native calls on a closed set. |
| Authorize chat attachments by ownership alone | Adds a second rule to the read boundary. In a matter, attaching to the matter keeps one rule. Outside a matter the one rule is the owner's own files that are filed in no matter (D5). |
| Let a run outside a matter read any file the owner owns, on its own terms | A file in a matter carries that matter's tier floor and privilege flag, which a run with no matter does not apply (D5). The maintainer ruled that such a run may read the file on the matter's terms (ruling 4). |
| Embed the knowledge-base search query | A priced, tier-bound model call that needs its own binding and allowance. Not built (D7). |
| Keep a full prompt record in the application now | Exceeds what an ordinary turn keeps; it belongs with the PRD §5.4 sink, for both. |
| Allow open-ended agents to choose skills, tools or sources | Task prose would become authority and defeat the approved-scope boundary. |
| Move orchestration to a separate harness service | Duplicates the governance path without solving authorization. |
| Leave the read rule in the run engine and review each new tool by hand | The rule is then held by reviewers remembering it. A change to access would need a separate edit in each route file and in the run engine, and one missed place is a read that should have been refused (D8). |
| Decide access in the database with row-level security | It would be structural, and it changes how every query in the API runs, including the workers' and the migrations'. It is not ruled out for later; D8's module is the smaller step and is where such policies would be derived from. |
| Replace the chat-completion path now | The gaps listed in D7. |

## Consequences

- The work is larger than moving the demonstration page. On the branch it is built in
  three increments that can be reviewed apart: the interface (the picker entry, Send and
  the one column of lines); the system prompts and the general engine (prompt files, the
  thread, optional documents, a chat outside a matter, pseudonymization by the operator's
  setting, thinking control, small tool-calling fixes and the trace read); and the
  orchestrator's turn with knowledge-base search (the plan tool, the direct answer, source
  numbers and frozen terms). They should land as ordered, separately reviewed changes.
- Release 0.8.0 shipped the orchestration tables, so schema changes must upgrade deployed
  databases. Migrations 0070 to 0073 are additive on a 0.8.0 database: 0070 adds the `run`
  message kind and the message-to-session link, and turns the profile column's enumerated
  check into a pattern check validated against the registry; 0071 adds the `closed` state;
  0072 lets a run have no project; 0073 lets a run complete with no plan revision. Each
  downgrade refuses while the data it would break is retained.
- The changes touch authorization, audit and the gateway, and are routed to security
  review. The items that need it are the gateway changes (the truthful purpose label, the
  reasoning-effort request field and its mapping to Ollama's `think`, naming a tool result
  after the call it answers, and sending non-ASCII characters in tool-call arguments as
  themselves), the rule for a run outside a matter (D1, D5), pseudonymization following the
  operator's setting (D5), and the knowledge-base search (D5).
- D8 is not built. It is a change to authorization across the API, routed to security
  review, and it lands before any C2 to C7 run tool.
- ADR 0011's model picker now holds one entry that is not a provider model (D1).
- ADR 0035 is unchanged. Its D1 amendment is a separate draft awaiting ratification.
- PRD §3.1 and §3.10, the feature PRD, the OpenAPI sketches, the schema document,
  HONEST-STATE and the observability guide change with the code.
- Not decided here: sources and connectors in runs; helpers and persistent workspaces on
  real documents; a tool loop for the orchestrator; a single-agent profile; runs started by
  schedules or watches; recursion; streaming; full prompt capture; and library skills
  assigned by the orchestrator (C2).

## Acceptance and release

**C1's acceptance test** is the maintainer's statement of 2026-10-07:

> when I input a query to the chat, it can run an orchestrator [that] can devise a plan
> and execute it. it is not to reproduce the constrained demo to the chat

The bracket marks a word missing from the statement. Nothing else in it is changed.
Whether the branch meets it is for the maintainer to say after using it. On 2026-10-09,
after using the third increment on a local model, the maintainer said that it passes. The
checks below exercise the build and do not stand in for that judgment. Passing C1 is not
ratification of this ADR and does not replace maintainer or security review.

**Visibility (D2).** Each row must hold for a run in main chat.

| Channel | An ordinary turn provides | A run must provide |
|---|---|---|
| Message | Applied skills, tier, provider, model, tokens and cost on the assistant message; content found by chat search and included in export | The same fields on the run's message, filled at delivery. `applied_skills` is empty for New harness, which applies no installed skill. The run heading carries the "New harness v<N> → provider/model" marker, the orchestrator's pinned prompt and its digest are in the receipts, and each call's pinned prompt is named in "How this run was set up" |
| Receipts, model calls | Provider, model, tier, tokens, latency and anonymization, from routing-log rows carrying the chat identifier | Chat and message identifiers on every run model call |
| Receipts, audit | Audit rows for the chat | The bound session's audit rows in the same feed |
| Tool call log | Chat and message identifiers on each row | The same, together with the session identifier |
| Routing-log purpose | A truthful purpose label | `orchestration_run` for run traffic |
| Traces | One trace across API, gateway and provider | Where tracing is configured, traces connecting API, worker, gateway and provider, with spans for each worker job, each claimed execution and each effect. Spans carry identifiers and labels only |
| Citations | Citation checks, ledger and gate when the turn retrieves | The same for an answer that quotes a selected document or a file a search found (D5) |

**Chat hosting (D1).** In main chat with New harness chosen, each of these must hold:

- a request with two attached documents is planned, the plan is approved, the lines
  update, and the answer shows checked quotations;
- a request with no documents is planned, approved and answered, and the answer is
  labelled unverified;
- a follow-up that depends on the earlier answer produces a plan that reflects it, also
  after a reload with the earlier run's documents still selected;
- a thank-you, or a request to shorten the last answer, is answered directly with no plan
  and no approval, and a question about a selected document produces a plan and not a
  direct answer (this depends on the model, D1);
- a chat in no matter can use New harness;
- rejecting a plan, halting a run, reloading mid-run and closing an uncertain run work;
- choosing New harness hides Skills, "Keep skills on" and the prompt enhancer, and
  choosing an ordinary model brings them back; and
- a chat whose model is New harness waits, and sends nowhere else, while New harness
  cannot be checked or used.

**Tool loop (D4).** A sub-agent must be able to call a granted tool and use its result,
including two calls in one turn with each result matched to its call. A call outside the
grant is refused, returned to the model and recorded. The turn limit ends tool use and
still yields an answer. A plan arrives as a `propose_plan` call, including one with
non-ASCII text. A reply that calls any other tool fails the plan, and so does a plan
written as text. Recovery across a worker restart reuses completed effects and repeats
none.

**What a run reads (D5).** Tests must reject unselected or revoked documents, a file held
by another matter, a chat attachment that was not attached to the matter, widened task
grants, stale approval, and hostile handoff text including a hostile thread. A
knowledge-base search must show only the passages D5 allows and count those it withholds.
A quotation from a found file must be checked against that file. A run in a matter must
list the knowledge bases attached to it, and a run outside a matter must list none. The
tests must also exercise halt, partial results, budget accounting, closing an uncertain
run (D6) and the export of run data. Where the setting applies pseudonymization at the
routed tier, a run must pseudonymize and its receipts must report it. Where it applies
none, the run must send names as written and report that none was applied.

Controlled-provider tests establish the contract. A configured-provider acceptance run is
required before claiming live operation. The build plan's Implementation status says what
has been run, on what, and what has not. Each profile's switch defaults to off. Maintainer
and security review, including ADR 0035's helper-specific gates, remain release
requirements. Ratification of this ADR precedes merging the implementation.

## Supporting evidence

The [UAT record](../uat/adr35-chat/README.md) shows provider timeouts leaving runs
uncertain, which D6 addresses. The [recorded walkthrough of the first
build](../uat/adr38-runs-in-chat/README.md) was made before the redirection and shows the
earlier design. It is not evidence for this one.
[#662](https://github.com/LegalQuants/lq-ai/issues/662) and its research note describe the
capability tracks that D3 serves. The [feature PRD](../prds/issue-563-governed-orchestration.md)
defines the requirements this ADR extends.
