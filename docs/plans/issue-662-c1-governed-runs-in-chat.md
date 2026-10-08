# Governed runs in chat: build plan for #662 C1

**Status:** Proposed. [ADR 0038](../adr/0038-skill-backed-orchestration-profile.md)
is not ratified. This plan was superseded in part on 2026-10-07 and 2026-10-08 (see the
note below). An implementation of the revised design exists on an unmerged branch and is
described under [Implementation status](#implementation-status). It has had no
maintainer or security review and does not merge before ratification.
**Date:** 2026-10-06. **Baseline inspected:** `5e128d5ba`. The plan was written
from a read of the code. The implementation status was rewritten on 2026-10-09.
**Tracks:** track C1 of [#662](https://github.com/LegalQuants/lq-ai/issues/662),
[#563](https://github.com/LegalQuants/lq-ai/issues/563),
[ADR 0035](../adr/0035-governed-orchestration-run-tree.md) and the
[feature PRD](../prds/issue-563-governed-orchestration.md).

> **Superseded in part.** This plan describes the first design: a profile control
> beside the model picker, the fictional profile in chat, a second profile that runs
> Contract QA on selected documents, and the ten slices below. After using that build the
> maintainer redirected C1 on 2026-10-07 and 2026-10-08 to an orchestrator model, **New
> harness**, chosen in the model picker, and ADR 0038 was rewritten on 2026-10-09 for it.
> The sections from "What exists and what changes" to "Risks" are kept as written and
> describe the first design. Where they speak of a profile control, a plan button,
> children or a documents profile, the ADR is the current statement.
> [Implementation status](#implementation-status) says what exists now, by increment,
> and what does not.

Move the governed run from its own page into the main chat. Keep it as visible as
an ordinary chat turn. Give later capabilities one surface to attach to. Let
approved children call tools. Add a first profile that reads real documents.
ADR 0038 records the decisions; this plan says what exists, what changes and in
what order.

## What exists and what changes

| Existing code | Reuse | Required change |
|---|---|---|
| [Chat panel](../../web/src/lib/lq-ai/components/ChatPanel.svelte), mounted by the chats page and the matter workspace | Composer, thread, receipts drawer, attached-files panel | A profile control in the composer; run messages in the thread |
| [Message model](../../api/app/models/chat.py) | A `kind` discriminator; skill, tier, provider, model, token and cost fields. History replay skips assistant rows with no content | A new kind, `run`, and a link to the autonomous session |
| [Message bubble](../../web/src/lib/lq-ai/components/MessageBubble.svelte) | Dispatch on `kind`; skill chips, tier badge, citation, ledger and source panels; the approve/deny prompt for gated tools | Dispatch `run` to the run components |
| [Run API](../../api/app/api/orchestration.py) and [views](../../api/app/autonomous/orchestration/views.py) | Owner-only read, approve, reject, halt and file routes | A chat intake route; views accept registry profiles instead of one literal |
| [Run store](../../api/app/autonomous/orchestration/store.py) | Planning, approval, admission, budgets, effects, delivery, halt | Delivery writes the bound message; the owner can close an uncertain run |
| [Demo profile](../../api/app/autonomous/orchestration/chat_demo.py) | The fictional Contract QA profile, held as constants | Becomes the first registry entry |
| [Effects adapter](../../api/app/autonomous/orchestration/effects.py) and the [chokepoint](../../api/app/autonomous/guard.py) | Durable effects for inference, run files, document reads, skill tools and sources, all through `guarded_tool_call` | Children choose among granted tools; chat and message identifiers are passed on |
| [Read boundary](../../api/app/autonomous/orchestration/boundary.py) and [policy](../../api/app/autonomous/orchestration/policy.py) | Every document read rechecks selection, ownership and project attachment | Unchanged. A chat attachment is attached to the project before it can be selected |
| [Inference binding](../../api/app/autonomous/orchestration/inference.py) | Pinned route, pricing, reservation | Accepts exactly one system and one user message today; children need a conversation with tool schemas |
| [Run page component](../../web/src/lib/lq-ai/components/OrchestrationChat.svelte) | Plan, approval, child and file presentation; polling | Split into run components. It stops following a run after four minutes today |
| [Chat receipts](../../api/app/api/chat_receipts.py) | One feed of message, skill, model-call and audit events per chat | Include the bound session's audit rows |
| [Ledger bridge](../../api/app/autonomous/ledger_bridge.py) | Citation checks, ledger and gate for a session's work product, attached to a hidden chat | Attach to the run's own message |
| [Recorded runs](../uat/adr35-chat/README.md) | Six recorded run projections: completed, rejected, two uncertain, two failed plans | Fixtures for the run components' tests |

## Visibility: where a run falls short today

ADR 0038 D2 requires a run to be at least as visible as an ordinary chat turn.

| Channel | An ordinary turn | A run today | Change |
|---|---|---|---|
| Message | Skill chips, tier and provider badge, tokens and cost; found by chat search; in data export | No message exists; the run page shows model and spend | Fill the same fields on the run's message at delivery |
| Receipts, model calls | Provider, model, tier, tokens, latency, anonymization, from routing-log rows carrying the chat identifier | Rows carry no chat or message identifier | Pass both on each run model call. The request fields already exist |
| Receipts, audit | Audit rows keyed to the chat | Audit rows keyed to the session; the feed never reads them | Read the bound session's rows into the feed |
| Tool call log | Chat and message identifier on each row | Session identifier only | Pass both as well |
| Routing-log purpose | `chat`, which is true | Sent as `autonomous_executor`, recorded as `chat` | The gateway keeps real purpose values |
| Traces | One trace across API, gateway and provider | The worker that executes runs receives no tracing endpoint; no span for the run or for skill use | Wire the worker in both compose files and both recipes; carry the trace through queued jobs; add the two spans |
| Citations | Checks, ledger and gate when the turn retrieves | None; labelled unverified | Same checks on an answer that quotes selected documents |

Full prompts and tool payloads are not kept for an ordinary turn, so they are not
part of this plan. See [Deferred](#deferred).

## What the owner experiences

1. In a chat inside a project, the owner chooses a profile beside the model
   picker. The composer shows the model, the total cap, the planning allowance and
   the attempt limit, and names what the run may read. If a profile is
   unavailable, the composer says why: the operator switch, the Autonomous opt-in,
   the project, or another run that is still active.
2. The composer's plan button sends the request, which appears as the owner's message.
   The run message below it shows that a plan is being proposed.
3. The plan card lists the tasks. For each child it shows the skill and version,
   the tools it may call, the documents it may read, and its budget. The owner
   approves or rejects that exact revision.
4. Progress appears in plain words with the current step. Each child opens to its
   steps, files and receipts. **Halt** stays in view.
5. The answer arrives in the same message with its evidence status, and carries
   the same skill chips, tier badge and cost as any answer. Follow-up questions
   are ordinary turns that can see it.
6. Reloading, or returning after a sign-out, restores the thread from stored state.
7. On the real-document profile, the owner first picks the documents. A file
   attached only to the chat is added to the matter when picked, and the plan card
   says so. The answer shows the result of the citation checks.
8. If a run ends uncertain, the composer names it and the owner can close it.

The planning call sees the request only, not earlier messages. The composer says so.

## Design

### Binding and delivery

- The run's reply is an assistant message of kind `run` with a nullable link to
  the root autonomous session. `chats.autonomous_session_id` is not reused: it
  marks hidden, session-owned chats and removes them from chat lists.
- `POST /chats/{chat_id}/runs` returns 202. It checks the chat, its project, the
  profile and the owner's opt-in, writes the two messages, and then follows the
  existing planning path. The client's request identifier makes a repeated send
  return the same run.
- A read for the composer returns each profile's availability for this chat and
  the reason when it is unavailable.
- Approval, rejection, halt, tree and file reads stay on the existing routes.
- `deliver_root` writes the answer and the message's skill, tier, provider, model,
  token and cost fields in its own transaction. A run that is rejected, halted,
  failed, expired or closed leaves the content empty; the run message shows the
  status.
- One additive migration. It must upgrade 0.8.0 databases, which carry the
  orchestration tables. `messages.kind` accepts `run`; the link gets a partial
  index; the enumerated profile check becomes a pattern check.

### Registries

- **Profiles** replace the constants in the demo profile module and the literal
  in the API and view types. An entry names pinned skills by role, tools granted
  per phase, readable resources, limits and model route. Each has an operator
  switch, and an admin read lists them with their state.
- **Tools** are single definitions: input model, handler, cost quote, safety
  flags and plain-language label. Run children take their tools from the
  registry. The chat tool loop and the matter-session planner are not moved in C1.
- **Renderers** in the web client map each step kind and output kind to a
  component, with a generic fallback.
- A contract test adds a profile and a tool that the product does not ship.

### Child tool loop

- Each model turn and each tool call is its own effect, identified by child, turn
  and call. A restart reuses completed effects and repeats none.
- The tools offered are the profile's grants, narrowed by the phase and by
  current policy. A call outside them, or one with malformed arguments, is
  refused, returned to the model as an error result and recorded.
- Calls run one at a time, because a session may have one effect in flight. Each
  takes a reservation from the child's allocation.
- The profile sets a turn limit. At the limit, one turn without tools requests
  the answer. The bounded answer and the shared findings file are unchanged.
- **Proving case on fictional data:** the Contract QA child reads the fictional
  agreement through the document-read tool, where today it receives the text in
  its prompt. The agreement becomes a file in the demo project, so selection and
  the read boundary are exercised before any real document is involved.

### Real documents

- A second profile with its own operator switch, usable in any active project the
  owner owns.
- The picker lists project files that are ingested and of a supported type. A
  chat attachment is attached to the project through the existing attach route
  when picked.
- Each read registers numbered evidence. Child findings carry quotations with
  their source numbers, and the root answer keeps them. At delivery the citation
  checks, ledger and gate run on the run's message.
- Limits become profile parameters, sized on real documents. Today they are
  98,304 input bytes per call including the skill's supporting files, 4,096
  characters per child answer, 16,384 per combined answer, 900 seconds per attempt
  and one hour per run. A document longer than a read returns is reported as cut.
- The [user export](../../api/app/workers/user_export.py) gains run plans, child
  results and run files.

### Closing an uncertain run

A new owner action on a run in the `uncertain` state. It closes the unresolved
effects without an outcome, settles their reservations as charges, ends the run,
writes an audit row and frees the owner's active-run allowance. The state names
are settled in review, and the status checks change by migration.

## Ordered slices

Sizes are guesses for one engineer, to be corrected after slice 1.

| # | Slice | Completion evidence | Depends on | Review | Days |
|---|---|---|---|---|---|
| 0 | ADR 0038, the PRD section and this plan | Ratified by the committee | — | Committee | 1 |
| 1 | Bind runs to chat: migration, intake route, availability read, delivery into the message | API tests for idempotent intake, each refusal, delivery and replay; migration round trip from 0.8.0; OpenAPI guards and schema document updated | 0 | Security, maintainer | 4–6 |
| 2 | Visibility: identifiers on run calls, audit rows in receipts, run and skill spans, worker tracing in compose and recipes | A receipts test showing the same event kinds as an ordinary turn; routing rows carry both identifiers; span tests on the worker path | 1 | Maintainer | 3–5 |
| 2g | Gateway keeps real purpose values | Gateway tests; gateway OpenAPI updated | — | Security (`gateway/**`) | 1–2 |
| 3 | Run message in the thread: run components, plain-language progress, composer control, following without a cap | Helper tests over the six recorded runs; a browser test for propose, approve, progress, answer, reject, halt, uncertain, failed plan, reload and hostile text | 1 | Maintainer | 6–9 |
| 4 | Profile and tool registries; admin read; contract test | The fictional profile runs unchanged from the registry; the contract test passes | 1 | Security, maintainer | 4–6 |
| 5 | Child tool loop on the fictional profile | Tests for a granted call, a refused call, malformed arguments, the turn limit, budget exhaustion, halt and restart in mid-loop | 4 | Security, maintainer | 6–10 |
| 6 | Close an uncertain run | Tests for the action, the charge, the audit row and the freed allowance | 1 | Security, maintainer | 2–3 |
| 7 | First profile on real documents: selection, evidence and citations, limits, export | The ADR's real-document acceptance, including the handoff tests of DE-294 | 5, 6 | Security, maintainer | 8–12 |
| 8 | Acceptance: runbook, recorded evidence, documentation, removal of the stand-alone intake form | Human UAT on the fictional profile after slice 3 and on real documents after slice 7 | 3, 7 | Maintainer | 3–4 |

Slices 1 to 3 put the fictional profile in main chat with full visibility and
can ship on their own. Slices 4 and 5 can follow in a later release, and slice 7
stays behind its own switch until its acceptance is recorded.

## Acceptance

ADR 0038's acceptance section is the contract. The runbook adds these checks:

- A run that outlasts the 15-minute access token keeps updating.
- A run left alone past the 30-minute idle sign-out is restored after signing in.
- A run started in the matter workspace's chat behaves as in the chats page.
- With a run active in one chat, another chat's composer names it.
- Text in a document or an answer that looks like markup is shown as text.
- With each switch off, new runs are refused and retained runs stay readable.

A passing run shows that the flow, the controls and the records work. It does
not show that an answer is legally sound.

## Points to settle in review

1. How the model's stated reason for a tool call is obtained. One way is a
   required reason field on every tool schema.
2. The state names for a closed uncertain run and its effects.
3. Names for the new audit actions, the real-document switch and the route paths.
4. Whether the profile registry lives in code, in operator configuration, or in a
   skill declaration that the operator pins.
5. Whether the demo orchestrator skill is hidden from, or labelled in, the
   ordinary skill picker. It is listed there today and starts nothing governed.
6. The limits for the real-document profile.

## Deferred

Unnumbered; the maintainer allocates identifiers.

- **Full prompt and tool-payload capture.** PRD §5.4 assigns it to an optional
  self-hosted tracing sink at the gateway. That sink is not implemented: the
  `telemetry` block in the gateway configuration is read by no code. It should
  serve ordinary turns and runs alike. The
  [observability guide](../observability.md#6-whats-not-yet-shipped) lists it as unshipped.
- Sources and connectors in runs.
- Bundled helpers and persistent skill workspaces on real documents, pending
  ADR 0035 D8c and D8d.
- A tool loop for the root, and a single-agent profile.
- Moving the chat tool loop and the matter-session planner onto the tool registry.
- Runs started by schedules or watches; recursion; streamed progress.
- An operator screen for reconciling uncertain runs.
- Word input, which waits on ADR 0017.
- Replacing the chat-completion path, which ADR 0038 D7 leaves to a later decision.

## Risks

1. **Size.** This is several releases of work, not a page move.
2. **Tools widen the handoff surface.** A child that reads a hostile document can
   now ask for tool calls. The grant check and the handoff tests carry the weight.
3. **Effect identity inside a loop.** Restart safety depends on each turn and
   call keeping a stable identity.
4. **Limits against real documents and local models.** The UAT record shows
   single calls exceeding their timeout. A one-hour run deadline may be short.
5. **Evidence through the tree.** Carrying quotations from a child's read to the
   root's answer and into the citation checks is new plumbing.
6. **Review time.** The gateway and authorization changes wait on security review.
7. **Deployed schema.** The orchestration tables carry strict checks and refuse
   downgrade while runs are retained.

## Implementation status

Recorded 2026-10-09 on an implementation branch built on `91973fd80` (the v0.9.0 release
commit). Unmerged, unreviewed, and ahead of ratification. Both profile switches default
to off. The branch follows the revised design in
[ADR 0038](../adr/0038-skill-backed-orchestration-profile.md), not the ten slices above as
they are written. The slice table below says what became of each slice, and three
increments followed the first build.

### What was built

**The first design's slices, as they stand now.**

| # | Slice | Now |
|---|---|---|
| 1 | Bind runs to chat | Built. Migration 0070; `POST /chats/{chat_id}/runs`; `GET /chats/{chat_id}/run-profiles`; delivery writes the bound message in the delivery transaction. Since changed: a chat may be in no matter (migration 0072), and a run may complete with no plan (migration 0073). Tests: `api/tests/autonomous/orchestration/test_runs_in_chat.py`, `test_runs_in_chat_migration.py` |
| 2 | Visibility | Built. Chat and message identifiers on every run model call and tool-call-log row; the run's session audit rows in the receipts feed; `orchestration.job`, `orchestration.run` and `orchestration.effect` spans carrying identifiers and labels only; trace context carried through queued jobs; the worker wired for tracing in both compose files and both recipes. Tests: `test_runs_in_chat.py`, `test_run_tracing.py` |
| 2g | Gateway purposes | Built. The gateway's closed purpose set lists every label the backend sends that fits the column, including `orchestration_run`. Test: `gateway/tests/test_inference_b4.py` |
| 3 | Run message in the thread | Redone in increment 1. One column of lines replaces the first build's run panel and progress list. |
| 4 | Registries | Built. `profiles.py`, `tools.py`; `GET /admin/orchestration/profiles`; the contract test (`test_registry_contract.py`). A profile may now pin engine prompt files in place of skills, and one profile is the composer profile. |
| 5 | Child tool loop | Built. `loop.py`: native calls on the granted set, one durable effect per turn and per call, refusals recorded, the turn limit, replay from receipts. Sub-agents of New harness also have the knowledge-base search. Tests: `test_tool_loop.py`, `test_contract_versions.py` |
| 6 | Close an uncertain run | Built. Migration 0071; `POST /autonomous/orchestration/chat-runs/{root_id}/close`. Test: `test_close_uncertain.py` |
| 7 | Real documents | Replaced by New harness, in increments 2 and 3. The first build's documents profile no longer exists. |
| 8 | Acceptance | The runbook was rewritten for the revised design and no person has followed it. The recorded walkthrough describes the first build and was not redone (see "Not done, or not verified"). The stand-alone page's intake form is removed. |

**Increment 1: the interface, on the first build's engine.**

| Part | Built |
|---|---|
| Server | `GET /chats/{chat_id}/run-profiles` names the one profile the composer offers (`composer_profile`), and `register_profile` refuses a second. The fictional profile is not offered there. Its API route still accepts it where its operator switch is on. The planning notice was reworded for Send. |
| Picker and composer | An Experimental group with one row, New harness, first in the list, with an `experimental` chip and its `provider/model`. The choice is kept for each chat. A row that cannot be chosen says why; a run in progress is a Send blocker and a notice and does not disable the row. While New harness is chosen the skill picker, "Keep skills on", the prompt enhancer, the slash popover and the attach-knowledge-base button are not shown, and Send is the one button. The mode panel is a compact strip with a "Limits and tools" fold and the document picker. `RunProfileMenu.svelte` was removed. |
| Run message | One column of lines (`run/activity.ts`, `RunActivity.svelte`): the plan, one line for each task, the answer. Each is a native fold with a live one-line summary. `RunProgressList.svelte` was removed. The test id `lq-ai-run-progress` became `lq-ai-run-activity`. |

Tests: `web/src/lib/lq-ai/run/__tests__/` (`composer.test.ts`, `harness.test.ts`,
`activity.test.ts`, `components.render.test.ts`, `text-safety.test.ts`) and
`web/src/lib/lq-ai/__tests__/ChatPanel-model-persist.test.ts`.

**Increment 2: the system prompts and the general engine.**

| Part | Built |
|---|---|
| Prompts | `new_harness/orchestrator.v1.md` and `subagent.v1.md` in `api/app/autonomous/orchestration/prompts/`, loaded outside the skill registry and pinned by digest under a pin kind of their own (`prompt`). `GET /autonomous/orchestration/prompts/{family}/{name}` returns a prompt's text. |
| Opening message | One function builds it from the run's records. Sending uses it, and so does the trace read. |
| The profile | `new_harness_v1` replaced the first build's documents profile. Operator switches are `LQ_AI_NEW_HARNESS_*`. The operation name, response contract and outcome wrapper became per-profile. The fictional profile keeps its Contract QA strings. |
| Thread and date | Planning snapshot version 3: the chat's recent messages (at most 20, 32,768 bytes) and the date, read once when the request is accepted. |
| Documents | Optional, none to eight. A run with none is not offered the read tool. The composer starts from the documents the last run in the chat read (`suggested_file_ids`). |
| Evidence | Per run: `citations` only when the run had a source to check against, otherwise `unverified`. |
| Pseudonymization | Follows the operator's gateway setting for the routed tier. The fictional profile keeps the earlier rule. |
| Gateway | A reasoning-effort request field, mapped to `think` by the Ollama adapter; an Ollama tool result named after its call; non-ASCII characters in tool-call arguments sent as themselves. The setting `LQ_AI_NEW_HARNESS_REASONING_EFFORT` ships empty. Tests: `gateway/tests/test_ollama_tool_calls.py`. |
| Trace read | `GET /autonomous/orchestration/{root_id}/sessions/{session_id}/trace`: each call's system message, opening message and tools, rebuilt and compared with the recorded digest, and each turn's text and tool calls. |
| A chat outside a matter | Migration 0072. Such a run is never privileged, has the profile's tier floor, reads only files filed in no matter and searches no knowledge base. |

Tests: `test_new_harness.py`, `test_new_harness_guards.py`, `test_document_runs.py`,
`test_evidence_counts.py`, `test_registry_contract.py`, `test_contract_versions.py` in
`api/tests/autonomous/orchestration/`.

**Increment 3: the orchestrator's turn, and knowledge-base search.**

| Part | Built |
|---|---|
| The plan tool | The planning call is offered `propose_plan` and nothing else. One call to it is the plan. More than one call, another tool, or arguments that are not a valid plan fail the plan (`invalid_proposal`). |
| The direct answer | A complete reply with no call is the orchestrator's own answer. It is delivered with no plan, no task and no approval, and is unverified. Migration 0073. A plan written as text fails the plan (`plan_not_handed_over`). `ChatRunRead.answered_directly` and the run's one "Answered directly" line. |
| Knowledge-base search | The registry tool `search_knowledge_base`. A run in a matter lists the matter's knowledge bases (at most 16), named in the intake and the plan. Keyword only. Passages are shown subject to the file rule. Files a search finds get source numbers in the task's own block, and quotations from them are checked. `ChatRunRead.sources`, a step of kind `knowledge_search`, and the composer's knowledge-base line. |
| Terms | The run's limits and how its plan is handed over are frozen in its version 3 intake (`terms`). |
| Prompts | `orchestrator.v2.md` and `subagent.v2.md`. Version 1 of each stays beside them. |
| Placeholders | A plan from a pseudonymized call that carries a placeholder fails (`plan_has_placeholders`). The gateway change that would make this unnecessary is written up for security review and not made. |
| Skill list | The skill list and autocomplete leave out any skill that instructs a run profile's orchestrator (the 0.8.0 demonstration skill). The skill `contract-questions-orchestrator`, added in the first build, was removed. |

Tests: `test_new_harness_turn.py`, `test_new_harness_turn_guards.py` and the files named
for increment 2. Web fixtures were recorded again from this branch.

**Gates.** On 2026-10-09 the whole API suite passed (3,816 passed, 17 skipped; `ruff` and
`mypy` clean, run as CI runs them). That run began before the last tests were added, and the
orchestration suite was run again afterwards and passed (936 passed, 9 skipped). The gateway
suite passed (1,037 passed, 3 skipped; increment 3 changes nothing in the gateway). The web
suite passed (3,271 passed in 108 files), and `check:lq-ai` gave 0 errors and 7 known
warnings.

### Choices made on the points to settle

These were needed to build. Each is open for review and cheap to change.

1. **Stated reason.** Every tool input model carries a required `reason`. It is
   kept with the call's receipt in the run's records and shown to the owner. It
   is model-authored text and is not written to an audit row.
2. **State names.** A closed run is `closed` with stop reason `owner_closed`. Its
   unresolved effects are `closed`: charged, with no result. Its sessions are
   `halted`.
3. **Names.** Audit actions `orchestration.tool_refused`,
   `orchestration.run_closed` and `project.file_attached`. Switch
   `LQ_AI_NEW_HARNESS_ENABLED`, with `_PROVIDER`, `_MODEL`, `_BUDGET_USD`,
   `_MINIMUM_TIER`, `_TIMEOUT_SECONDS` and `_REASONING_EFFORT`. Routes as in the
   slice table above, plus `GET /chats/{chat_id}/run-documents`, the trace read and the
   prompt read.
4. **Registry location.** In code. Each entry reads its operator switch and
   pinned route from deployment settings.
5. **The demonstration orchestrator skill in the skill picker.** Hidden. The
   skill catalogue and the composer's autocomplete leave out a skill that
   instructs a run profile's orchestrator. It stays installed and readable by name.
6. **Limits for New harness.** 262,144 input bytes and 8,192 output tokens per
   call, five tool turns per task, 40,000 characters per read, 12,000 characters per
   task answer, 16,384 per combined answer, eight documents per run, a two-hour
   deadline. These are placeholders, not measured.

### Choices made while building the revised design

Nobody has ruled on these. [ADR 0038](../adr/0038-skill-backed-orchestration-profile.md#open-questions)
lists the open questions.

- **A direct answer when documents are selected** is allowed, because a follow-up such as
  "shorten that" keeps the earlier run's documents selected. The prompt tells the model
  never to answer a question about a document this way. No code enforces that.
- **Which knowledge bases.** Every one attached to the matter when the request is accepted,
  at most 16. The owner does not pick. A run outside a matter searches none.
- **The search is by keyword only.** No query embedding is requested, so a search costs
  nothing and sends nothing to a model.
- **The file rules.** A run never takes a file out of its matter, and a knowledge-base
  passage whose file another matter holds is withheld.
- **A reply that writes the plan out as text** fails the plan. It is neither shown as an
  answer nor accepted as a plan.
- **The direct answer's cost.** It is delivered whatever the planning call cost within the
  root's whole allocation. The rule that a plan must leave room for its tasks applies to a
  plan only.
- **A plan that carries a placeholder is refused** on a route that pseudonymizes. The
  alternatives are in the ADR.
- **Reasoning effort** ships empty.

### Where the build differs from this plan

- **Attaching a chat attachment.** It is attached when the run is accepted,
  inside the intake transaction and with an audit row, not through the existing
  attach route at the moment it is picked. That route writes no audit row, and a
  file picked for a run that is never proposed stays unattached.
- **No second orchestrator skill.** The first build added a built-in skill,
  `contract-questions-orchestrator`, for the documents profile. It was removed. New
  harness is instructed by engine prompt files, which are not skills. Whether either
  prompt needs an attorney's attestation is open.
- **Budget.** A task is allowed one unit per model call it may make. For the fictional
  profile that is two tool turns and an answer; for New harness it is five tool turns and
  an answer. The total cap decides how many tasks can be funded, the planner is told, and a
  larger proposal fails as `unfunded_plan`. A deployment with a priced route funds fewer
  tasks at the same cap than 0.8.0 did.
- **Runs in flight at upgrade.** The fictional profile's operator policy changes,
  so a 0.8.0 run that is mid-flight stops at its next admission and stays
  readable. Completed and stopped runs keep their plan hashes and approvals. Whether such
  a run must survive is open.
- **Document reads and pseudonymization.** A document a task reads is returned to the
  model as a tool result. The gateway pseudonymizes the content of system, user and
  assistant messages only, so the document's text reaches the provider as stored, as
  retrieved text does in ordinary chat. The request, the thread and the task text are
  pseudonymized where the route's tier calls for it, and placeholders in a reply's text are
  restored. A placeholder inside a tool call's arguments is not restored, so a note, a
  stated reason or a search query can hold one, and so can the plan tool's arguments (a plan
  that does is refused). Both facts are pinned in
  `gateway/tests/anonymization/test_middleware.py`. Whether source documents should be
  pseudonymized is the open question
  [DE-269](../PRD.md#9-deferred-enhancements-and-identified-future-work) already
  tracks. This plan did not decide it.
- **Citation checks.** The delivered answer's quotations are checked with the Citation
  Engine's exact and tolerant stages only, against the whole text of the file their source
  number names. No judge model is called, because a run's model calls are priced, reserved
  effects. A quotation those stages cannot match is recorded as unverified and flags the
  gate.
- **What the planner sees.** The file names of the selected documents and the names of the
  matter's knowledge bases, not their text, and the chat's recent messages. Planning
  authorizes one model call and no read.
- **Gateway purposes.** Two playbook labels are longer than the 32-character
  column and are still recorded as `chat`. Judge and tabular cost calibration
  now find their own rows, which they were written to do and never could.
- **The stand-alone intake.** The page's form is removed. The
  `POST /autonomous/orchestration/chat-runs` route remains for existing clients and starts
  only the fictional profile.
- **Chain of custody.** Delivery also writes the work-product attribution row
  that every answered chat turn gets. The visibility table did not list it.
- **A model that cannot call tools.** Both profiles offer function schemas, to
  sub-agents and, for New harness, to the planning call. A provider that rejects such a
  request leaves the run uncertain, and the owner can close it. A malformed call from a
  sub-agent is refused and recorded; it does not end the task or the run. A planning call
  that cannot call `propose_plan` and writes the plan out as text fails the plan. Any other
  complete reply from it is delivered as the orchestrator's own answer, unverified.
- **A failed citation check.** If the checks themselves raise at delivery, the
  answer is still delivered and recorded as unverified with the checks marked
  failed.
- **What the evidence line counts.** The citation checks see a quotation only
  when it is written with a marker for a source of the run. The run's evidence
  result therefore also counts quoted passages with no marker, and markers that
  name no source of the run, and the line under the answer says they were not
  checked. The plan did not ask for this. The run on a local model showed the
  need: one task wrote its quotations without markers, and the line would
  otherwise have read as if every quotation had matched.
- **The cost on the run's message.** It is the run's accounted spend: the
  charges ADR 0035 records, each the larger of the call's conservative estimate
  and its reported usage. Its token fields are the reported token counts. The
  gateway's routing-log rows for the same calls carry usage-based estimates, so
  the two do not add up to the same figure. Whether the message should show the
  usage-based sum instead is for review.
- **Text sent to the model.** Run inputs travel as JSON. They were escaped to
  ASCII, as in 0.8.0, so a section mark or a curly quote reached the model as
  `\uXXXX`. A local model told to keep quotations exactly copied the escape
  into its answer. Inputs are now sent as the characters themselves, and so are a
  tool call's arguments through the Ollama adapter. This changes the request bytes only
  when the text is not ASCII.
- **How the answer is drawn.** An ordinary assistant message is Markdown turned
  into sanitised HTML, so HTML written in it is drawn and its images are loaded.
  A run's answer keeps its Markdown structure, but raw HTML in it is shown as
  the characters written, an image is never loaded, and a link is drawn only
  for an http, https or mailto address (`web/src/lib/lq-ai/run/answer.ts`). The
  acceptance line on markup-like text requires this. The first build used the
  ordinary path; the browser walkthrough caught it. Ordinary messages are
  unchanged.

### Not done, or not verified

- **Local models only, and single runs.** Agents ran New harness on local models through
  Ollama, through the API and in a browser: a plan with and without documents, a request
  answered directly, a question answered from a knowledge base and a chat outside a matter.
  These are single runs and not a rate. No hosted provider was used, so this is not the
  configured-provider acceptance ADR 0038 requires before live operation is claimed. The
  runs are recorded in the maintainer's working notes, which are not in the repository.
- **A reasoning model and the output limit.** The limit of 8,192 output tokens per call
  covers reasoning and answer together. The gateway can now ask for a reasoning effort, but
  New harness sends none unless the operator sets one, and a level did not reduce
  reasoning on the two models it was tried on (ADR 0038, open question 5).
- **Findings passed as JSON.** The fictional profile still hands the tasks' findings to
  its orchestrator as JSON, so a line break or a quotation mark inside them is escaped and
  a model can copy the escape into its answer. New harness passes them as text between
  marked lines.
- **No human acceptance.** The runs were driven by agents. The
  [UAT runbook](../runbooks/adr38-runs-in-chat-uat.md) was rewritten on 2026-10-09 for
  New harness, from a read of the code, and no person has followed it. The first build's
  [recorded walkthrough](../uat/adr38-runs-in-chat/README.md) was not redone, so its
  screenshots show a composer, a run message and a profile choice that no longer exist.
- **The walkthrough's tooling is not in the branch.** The scripted provider, the stack
  scripts and the browser scripts are kept with the maintainer.
- **Long sessions.** A run that outlasts the access token, and the idle
  sign-out, were not exercised.
- **No security review.** The changes touch authorization, audit and
  `gateway/**`. Four are routed to it: the gateway changes, the rule for a run outside a
  matter, pseudonymization following the operator's setting, and the knowledge-base search.
  The DE-294 handoff rules are implemented as tests, not reviewed.
- **No ratification.** ADR 0038 is Proposed. The direct answer amends ADR 0035 D1, which is
  Accepted, and that amendment is a separate draft awaiting its own ratification.
- **Open rulings.** The ADR's nine open questions are unanswered, among them the two prompt
  texts, the quotation pattern, the file rules and the placeholder limit.
- **No full Docker stack smoke** of the revised design is recorded here.
- **No browser test in CI.** The browser walkthrough is a recorded script, as the
  test strategy states for browser coverage generally.

## Evidence and limits

This plan comes from reading the code at the baseline above and from the
[UAT record](../uat/adr35-chat/README.md). The plan itself was written before
anything was run, and its sizes were guesses. The implementation status above
is evidence from controlled-provider tests and from single runs by agents on local
models. The recorded runs use a fictional agreement, short fictional documents and a
scripted or local model. They establish no claim about real matters, paid providers or
legal quality.
