# Governed runs in chat: build plan for #662 C1

**Status:** Proposed. [ADR 0038](../adr/0038-governed-runs-in-chat.md)
is not ratified. This plan was superseded in part on 2026-10-07 and 2026-10-08 (see the
note below). An implementation of the revised design exists and is
described under [Implementation status](#implementation-status). It has had no
maintainer or security review.
**Date:** 2026-10-06. **Baseline inspected:** `5e128d5ba`. The plan was written
from a read of the code. The implementation status was rewritten on 2026-10-09 and
extended on 2026-10-10.
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
commit). Unreviewed, and ahead of ratification. Both profile switches default
to off. The branch follows the revised design in
[ADR 0038](../adr/0038-governed-runs-in-chat.md), not the ten slices above as
they are written. The slice table below says what became of each slice, and three
increments followed the first build.

### What was built

**The first design's slices, as they stand now.**

| # | Slice | Now |
|---|---|---|
| 1 | Bind runs to chat | Built. Migration 0074; `POST /chats/{chat_id}/runs`; `GET /chats/{chat_id}/run-profiles`; delivery writes the bound message in the delivery transaction. Since changed: a chat may be in no matter (migration 0076), and a run may complete with no plan (migration 0077). Tests: `api/tests/autonomous/orchestration/test_runs_in_chat.py`, `test_runs_in_chat_migration.py` |
| 2 | Visibility | Built. Chat and message identifiers on every run model call (a run writes no tool-call-log row, because neither profile grants an external tool); the run's session audit rows in the receipts feed; `orchestration.job`, `orchestration.run` and `orchestration.effect` spans carrying identifiers and labels only; trace context carried through queued jobs; the worker wired for tracing in both compose files and both recipes. Tests: `test_runs_in_chat.py`, `test_run_tracing.py` |
| 2g | Gateway purposes | Built. The gateway's closed purpose set lists every label the backend sends that fits the column, including `orchestration_run`. Test: `gateway/tests/test_inference_b4.py` |
| 3 | Run message in the thread | Redone in increment 1. One column of lines replaces the first build's run panel and progress list. |
| 4 | Registries | Built. `profiles.py`, `tools.py`; `GET /admin/orchestration/profiles`; the contract test (`test_registry_contract.py`). A profile may now pin engine prompt files in place of skills, and one profile is the composer profile. |
| 5 | Child tool loop | Built. `loop.py`: native calls on the granted set, one durable effect per turn and per call, refusals recorded, the turn limit, replay from receipts. Sub-agents of New harness also have the knowledge-base search. Tests: `test_tool_loop.py`, `test_contract_versions.py` |
| 6 | Close an uncertain run | Built. Migration 0075; `POST /autonomous/orchestration/chat-runs/{root_id}/close`. Test: `test_close_uncertain.py` |
| 7 | Real documents | Replaced by New harness, in increments 2 and 3. The first build's documents profile no longer exists. |
| 8 | Acceptance | The runbook was rewritten for the revised design and no person has followed it. The recorded walkthrough described the first build, was not redone, and was removed from the branch on 2026-10-10 (see "Not done, or not verified"). The stand-alone page's intake form is removed. |

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
| A chat outside a matter | Migration 0076. Such a run searches no knowledge base. Since ruling 4 (built 2026-10-10) it reads the owner's files wherever they are filed, under the strictest terms of the matters that hold them; with no document from a matter it is not privileged and has the profile's tier floor. |

Tests: `test_new_harness.py`, `test_new_harness_guards.py`, `test_document_runs.py`,
`test_evidence_counts.py`, `test_registry_contract.py`, `test_contract_versions.py` in
`api/tests/autonomous/orchestration/`.

**Increment 3: the orchestrator's turn, and knowledge-base search.**

| Part | Built |
|---|---|
| The plan tool | The planning call is offered `propose_plan` and nothing else. One call to it is the plan. More than one call, another tool, or arguments that are not a valid plan fail the plan (`invalid_proposal`). |
| The direct answer | A complete reply with no call is the orchestrator's own answer. It is delivered with no plan, no task and no approval, and is unverified. Migration 0077. A plan written as text fails the plan (`plan_not_handed_over`). `ChatRunRead.answered_directly` and the run's one "Answered directly" line. |
| Knowledge-base search | The registry tool `search_knowledge_base`. A run in a matter lists the matter's knowledge bases (at most 16), named in the intake and the plan. Keyword only. Passages are shown subject to the file rule. Files a search finds get source numbers in the task's own block, and quotations from them are checked. `ChatRunRead.sources`, a step of kind `knowledge_search`, and the composer's knowledge-base line. |
| Terms | The run's limits and how its plan is handed over are frozen in its version 3 intake (`terms`). |
| Prompts | `orchestrator.v2.md` and `subagent.v2.md`. Version 1 of each stays beside them. |
| Placeholders | The gateway restores the placeholders in a pseudonymized planning call's plan arguments (ruling 6, built on 2026-10-10). A plan that still carries one fails (`plan_has_placeholders`). |
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

These were written on 2026-10-09, before the maintainer ruled. He ruled on all of them
that day ([ADR 0038](../adr/0038-governed-runs-in-chat.md#rulings-on-the-open-questions)).
"Built after the maintainer's rulings" below says what then changed: the quotation
pattern, the file rule, the plan's placeholders and the roles on runs. Where a point
here differs from that section, that section is the present state.

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
  harness is instructed by engine prompt files, which are not skills. Ruling 1 settled
  that neither prompt needs an attorney's attestation; they are reviewed as code.
- **Budget.** A task is allowed one unit per model call it may make. For the fictional
  profile that is two tool turns and an answer; for New harness it is five tool turns and
  an answer. The total cap decides how many tasks can be funded, the planner is told, and a
  larger proposal fails as `unfunded_plan`. A deployment with a priced route funds fewer
  tasks at the same cap than 0.8.0 did.
- **Runs in flight at upgrade.** The fictional profile's operator policy changes,
  so a 0.8.0 run that is mid-flight stops at its next admission and stays
  readable. Completed and stopped runs keep their plan hashes and approvals. Ruling 3
  settled that such a run need not survive; the upgrade notes are to say so.
- **Document reads and pseudonymization.** A document a task reads is returned to the
  model as a tool result. As first built, the gateway pseudonymized the content of
  system, user and assistant messages only, so the document's text reached the provider as
  stored, as retrieved text does in ordinary chat. That was an inconsistency, and the
  maintainer ruled that the gateway is where the rule applies: what leaves it for a
  provider is pseudonymized as one request, in every role, and between the backend's own
  agents nothing is. For a caller that holds its tool arguments as originals, which a run is, the gateway now rewrites a tool message's JSON string values and the arguments of an assistant message's earlier calls, with the one mapper, and replaces a name it found anywhere in the request wherever else it stands in that tool text, and restores
  placeholders in a reply's text and, on the caller's request, in a call's arguments. A
  governed run's calls that are offered tools or carry earlier tool text make that request on a route that
  pseudonymizes, so a note, a stated reason or a search query is held with the name in it
  and is pseudonymized again when the conversation goes out. What the gateway does is
  pinned in `gateway/tests/anonymization/test_middleware.py`. Ordinary chat is unchanged:
  its retrieval context stays un-pseudonymized under Decision M2-1, which
  [DE-269](../PRD.md#9-deferred-enhancements-and-identified-future-work) tracks.
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

### Built after the maintainer's rulings of 2026-10-09

The maintainer ruled on ADR 0038's open questions on 2026-10-09 and said the branch
passes C1's acceptance statement. Four rulings needed code. Each is its own commit, so
that it can be reviewed apart, and none has had maintainer or security review.

- **Ruling 2, quotations in emphasis.** The Citation Engine's quotation pattern, which
  ordinary chat shares, accepts up to three `*` or `_` between the closing quotation mark
  and `(Source: [N])`, in `api/app/citation/extraction.py` and in the web's
  `citations/state.ts`. Tests: the extractor, the counts of what the checks could see,
  a run whose delivered answer holds two emphasised quotations the documents hold and
  one they do not, and the web's marker iterator. Not changed: emphasis inside the
  quotation marks, and the underline in an ordinary message's prose, which is not drawn
  for an emphasised quotation.

  Run on the development stack on 2026-10-10 with the local model, one run each. Asked
  for its quotations in bold, the orchestrator first declined and told the reader that
  the application does not recognise a bold quotation. Both prompt files still said so,
  and this ruling had made it untrue. In `orchestrator.v2` and `subagent.v2` that
  sentence is replaced by the reason that still holds: emphasis marks inside the
  quotation marks are looked up as part of the quoted words. The instruction to write
  quotations plainly stays, and a test holds both files to the pattern. The files are
  edited in place because neither is released, so a development run that pinned the
  earlier text now reads as changed. On the corrected prompts the same request gave an
  answer with two quotations written `**"words"** (Source: [1])`. The pattern before
  this ruling finds neither. Both were checked and matched, and in a browser the
  citation list under the answer showed both as verified, with no underline in the
  prose. Whether a model writes bold at all is the model's choice; this is one answer.

- **Ruling 6, the plan's placeholders.** The gateway's chat-completion request takes an
  opt-in, `lq_ai_restore_tool_arguments`. With it, and where the request was
  pseudonymized, the non-streaming response path restores this request's placeholders in
  the string values of each tool call's JSON arguments, whole tokens only, in one pass,
  and returns anything it will not rewrite exactly as sent
  (`gateway/app/anonymization/middleware.py`). The field is stripped from the outbound
  body. The application first set it on a planning call that is offered the plan tool where the route binding expects pseudonymization. It now sets it on every call of a run that is offered tools or carries earlier tool calls and results where the binding expects pseudonymization (the plan tool, a task's tools, a task's last turn); it is part of that binding and of the call's identity, and the run boundary refuses it on a call with no route binding. The same opt-in puts the run's tool results and earlier call arguments under the request pseudonymization, which is what makes restoring a task's arguments safe. The refusal of a plan that
  still carries a placeholder is kept. Tests: the restore step alone, the gateway against
  a mocked provider with and without the opt-in and for a request that was not
  pseudonymized, the adapter's stripped fields, the binding's form and match, the
  boundary's refusal, and controlled-provider runs. An independent review found three
  things, each fixed with a test: a placeholder glued to other characters was neither
  restored nor refused, so the plan check now looks for the shape anywhere; an escape for
  a lone surrogate could make the gateway fail to send its reply, so such arguments are
  returned as sent; and the application sent the field as false on every call, which a
  gateway that does not know it would pass to an OpenAI-type provider, so it is now left
  out unless asked for. Run once on the development stack with
  the gateway pseudonymizing at the local route's tier: sent straight to the gateway, the
  same request came back with `PERSON_0001` in the plan arguments three times of three
  without the field and with the name three times of three with it; through the
  application, three requests naming a person were all planned, one plan naming the person
  and two naming nobody. An independent read of the documents then found why: the
  orchestrator's prompt still told the model to write no placeholder in a plan, because
  the application could not put the value back. That had been untrue since this ruling.
  The prompt now tells the model to keep a placeholder as written in a plan, and says
  that a changed or invented one is refused; a test holds it. With that, the same three
  requests were all planned and all three plans named the person, with no placeholder
  left (one run each). Not done: a test of the streaming path with the field set (that
  path does not read it).

- **Ruling 10, roles.** Starting a run, approving a plan and rejecting one require a
  member or admin role (`RunActor` in `api/app/api/dependencies.py`); the store refuses a
  read-only role as well. The composer reports `role_read_only`. An admin or auditor may
  read another owner's run, tree and session trace, each read writing one audit row
  (`auditor.run_viewed`, `auditor.run_trace_viewed`); working files, approval, rejection,
  halt and closing stay with the owner. Tests: a viewer and an auditor refused at the
  routes and in the store, a viewer reading and halting their own run, an auditor and an
  admin reading another owner's run with the audit rows counted, and the 404 for anyone
  else. No new route. An independent review found that the owner-only file route does not
  keep a task's work from a privileged reader: the findings are in the tree and a saved
  note's text is in the trace. A test now states that, and the documents say it. Not done:
  leaving tool-call arguments out of the trace a privileged reader is given; the web shows
  such a reader the owner's controls on the receipt page, and each fails; a run is not
  stopped when its owner's role changes.

- **Ruling 4, a matter's file in a chat that is in no matter.** `reading.readable_documents`
  no longer excludes a matter's file for a run with no matter. `reading.selection_terms`
  gives the strictest terms of the matters that hold a set of documents; `begin_run` sets
  the run's floor and privilege flag from it, and `store._data_terms` works it out again
  at every admission and stops the run when the terms have tightened or the privilege
  flag no longer matches. A route that cannot meet the terms is refused before anything
  is stored, with a message that names the cause. The document listing gives each
  matter-held file its matters' names, floor and privilege flag, and the picker notes
  them. No migration. Tests: the listing, the terms of a set of files, a run under a
  floor and under privilege with the gateway fields and receipts checked, a direct
  answer, the refusal, four kinds of change after approval, and a change that loosens
  the terms. An independent review then found that such a run's answer was shown, through
  the thread, to a later run without the terms; `intake.thread_excerpt` now replaces an
  earlier answer written under stricter terms with a note, and tests cover a privileged
  matter, a floor alone and privilege alone. Three choices are the build's and not the
  maintainer's: the strictest terms where matters differ, withholding that earlier
  answer, and no change for a run in a matter. Run once on the development
  stack: a privileged matter with a floor of 1, a file filed in it, and a chat in no
  matter. The listing named the matter and its terms, the run took them on, the planning
  call went out at tier 1 and its receipt records that nothing was pseudonymized. On that
  stack the local route is not pseudonymized in any case, so the run does not show the
  privilege flag turning pseudonymization off; a controlled-provider test does. In a
  browser, the picker drew the file as selectable with its note. Not done: the strip is
  not quoted again when such a file is picked.

The guards these four changes add were probed by breaking each one in a copy of the tree
and running the tests that should notice: 49 breaks (19 for ruling 4, 8 for ruling 10, 20
for ruling 6, 2 for ruling 2). Forty-eight were caught by a failing test. The one that was
not removes the owner check a halt route makes before calling the store, and the store
makes the same check itself, so the route still refused. A fiftieth break was badly built
and is not counted: it changed the not-found message of the trace read, which one branch
gives both for a run that does not exist and for another owner's, so both answers changed
alike and no test could differ. The probes show that a test holds each guard that was
probed. They do not show that the guards are the right ones or that none is missing.

An independent review of rulings 4, 6 and 10 was made by an agent that was given the code
and not the author's view of it. It found two things of substance: an answer written
under a matter's terms reached a later run through the thread, and a task's findings and
notes reach a privileged reader through the tree and the trace. It found three smaller
ones in the gateway change. Each is fixed or stated above. It is not a maintainer or
security review.

**Gates on 2026-10-10.** The branch was then rebased onto `main`, three times that day. The
first rebase, onto `224044cc9`, took in one commit, which changes documents and review
rules and no code. The second, onto `994ccbade`, took in two more: #701, which changes
one ADR, and #684, which closes a refused ownership check in `retrieve_chunks` with an
`ownership_denied` audit row (#494). #684 changes the line of `guard.py` where this
branch adds the bounded document read, and the rebase conflicted there. It is resolved
as main's audited check followed by the bounded read, and a test holds that order
(`api/tests/autonomous/test_bounded_read_ownership_audit.py`): with the check left
unaudited, three of its five cases fail. The maintainer then ruled that the bounded
read is refused outside a governed run, as the knowledge-base search is. The
chokepoint now refuses it there before the ownership check, and the whole-file read
is unchanged; `test_document_runs.py` and the last case of that file hold both.
The knowledge-base search this branch adds
does not go through that check. It leaves out a knowledge base that is no longer the
owner's, archived or detached, counts it, and writes no audit row when the owner archived or detached it. One that has become another owner's, or no longer exists, writes one `ownership_denied` row and the search goes on; `docs/security/audit-logging.md` says so.

The third rebase, onto `7ac94dd1a`, took in #637, which adds a ceiling on tool
egress that an operator and a matter can set. #637 takes migration 0070, so this
branch's four migrations were renumbered 0071 to 0074 and the first now revises
0070. Both change `guard.py`, in different places, and the rebase did not conflict
there. The one conflict was in `docs/db-schema.md`, where each had added a section
at the same place; both are kept.

The fourth rebase, on 2026-10-11 onto `d185a623b`, took in seven changes. Two of
them add migrations 0071 and 0072 (#418, #710), so this branch's four moved again,
to 0073 to 0076, and the first now revises 0072. Two take DE-404 and DE-405 (#710,
#711), so this branch's three deferred enhancements are now DE-406 to DE-408. Four
files conflicted. The pinned count of API paths is the sum of both sides, 164, and
the generated OpenAPI file was regenerated. In `ChatPanel.svelte` both sides' line
is kept where a chat is selected. #418 adds a purpose label, `tabular_bulk_op`, to
the gateway's set, which this branch widens: the label is kept in the widened set,
and the gateway test that pins the list and the three documents that give it now
include it. The gateway run after this rebase is what found the test's list short.

On 2026-10-13 `main` at `f36c0c09c` was merged into the branch, not rebased under it,
because the pull request was by then open for review. It took in #438 and #715. #715
adds migration 0073 (`user_credential_version`), so this branch's four moved once more,
to 0074 to 0077, and the first now revises 0073. Two files conflicted. The pinned count
of API paths is the sum of both sides, 165, and the generated OpenAPI file was
regenerated. Git reported no conflict for the migrations, since the file names differ;
the check that compares revision ids did.

The suites were run as CI runs them. After the second rebase the whole API suite
passed with its coverage gate (3,928 passed, 17 skipped; 82.77% against
80%), and passed again on the commit that refuses the bounded read outside a run
(3,930 passed, 17 skipped; 82.76%), and a third time after the third rebase and
the renumbering (4,076 passed, 17 skipped; 82.83%). `ruff` was clean, and so was
`mypy app tests ../script_runner`, which is CI's command and checks the tests too; an
earlier pass had run `mypy app` alone and missed one error in a test helper, since
fixed. The gateway suite passed with its gate (1,074 passed, 3 skipped; 90.49% against
88%). The web suite passed (3,289 passed in 108 files), and `check:lq-ai` gave 0 errors
and 7 known warnings. The gateway and web suites were run after the first rebase and
after the last change to this branch's code, tests or prompts. The second rebase
changes no file under `gateway/` or `web/`, so they were not run again after it; nor
does the third. The fourth changes files under all three, so all three were run again
after it, on 2026-10-11: the API suite (4,193 passed, 17 skipped; 82.82%), the
gateway suite (1,088 passed, 3 skipped; 90.76%) and the web suite (3,360 passed in 112
files; `check:lq-ai` 0 errors and 7 known warnings), each with `ruff` and `mypy` as
before. `main` now also has an accessibility job (#712), which scans seven pages in
two sizes and two themes against a list of known exceptions; it passed on this branch
(28 states), and its check that a new violation fails the job passed too. Not
run: CI's stack smoke workflow, its release-image check, its bundled-helper acceptance
step and the air-gap verification workflow (#711), which need Docker images that this
pass did not build. The air-gap workflow runs on a change to `docker-compose.yml`,
which this branch makes.

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
  reasoning on the two models it was tried on (ADR 0038, ruling 5).
- **Findings passed as JSON.** The fictional profile still hands the tasks' findings to
  its orchestrator as JSON, so a line break or a quotation mark inside them is escaped and
  a model can copy the escape into its answer. New harness passes them as text between
  marked lines.
- **No recorded human acceptance.** The maintainer used the third increment on a
  local model on 2026-10-09 and said that it passes C1's acceptance statement. That
  is one person's use, not a recorded acceptance: the runs kept as evidence were
  driven by agents. The
  [UAT runbook](../runbooks/adr38-runs-in-chat-uat.md) was rewritten on 2026-10-09 for
  New harness, from a read of the code, and no person has followed it. The first build's
  recorded walkthrough showed a composer, a run message and a profile choice that no
  longer exist. It was removed from the branch on 2026-10-10, and no walkthrough of
  the present build is recorded.
- **The walkthrough's tooling is not in the branch.** The scripted provider, the stack
  scripts and the browser scripts are kept with the maintainer.
- **Long sessions.** A run that outlasts the access token, and the idle
  sign-out, were not exercised.
- **No security review.** The changes touch authorization, audit and
  `gateway/**`. Five are on a security path: the gateway changes (a reasoning-effort
  field, two Ollama tool-call fixes, and an opt-in that restores placeholders in the arguments of the calls a reply makes and puts a run's tool text under the request pseudonymization); the rule for a run outside a matter, including a matter's file read on
  that matter's terms; the roles on runs and the cross-owner read with its audit row;
  pseudonymization following the operator's setting; and the knowledge-base search.
  Under ADR 0034, accepted on 2026-10-04, security review means maintainer review
  with the security-path checklist applied; the project has no separate security team.
  The DE-294 handoff rules are implemented as tests, not reviewed.
- **No ratification.** ADR 0038 is Proposed. The direct answer, a run in a chat that
  is in no matter, and the selection of a file a knowledge-base search finds amend ADR 0035
  D1, D2 and D3, which are Accepted. ADR 0038 D1 gives the words, and they are ratified
  with it.
- **Choices inside the rulings.** The maintainer ruled on all eleven of the ADR's open
  questions. Rulings 4, 6 and 10 were built on choices he has not ruled on, which the
  ADR lists under each. D8, the access module, is proposed and not built.
- **No full Docker stack smoke** of the revised design is recorded here.
- **No browser test in CI.** The browser checks were scripts that agents ran, kept outside
  the repository, as the test strategy states for browser coverage generally.

## Upgrade notes for the release that carries this

The release notes are written at release time; these are what they need from this change.
Each applies whether or not `LQ_AI_NEW_HARNESS_ENABLED` is on, unless it says so.

- **A 0.8.0 run in flight at upgrade need not survive** (ruling 3). Completed and stopped
  runs, with their plan hashes and approvals, stay readable.
- **Migrations 0074 to 0077** run on upgrade. They are additive, and each downgrade
  refuses while run data exists. 0074 changes `messages` in one transaction that holds an
  `ACCESS EXCLUSIVE` lock while two checks, a foreign key and a unique index are
  validated, so the pause grows with the number of messages. Plan a window on a database
  with a large `messages` table.
- **Routing-log purpose labels change for existing traffic.** The tabular executor and the
  three Citation Engine judges used to be recorded as `chat`; they are now recorded as
  themselves. The cost estimators for tabular runs and for citation calibration read rows
  by purpose, so as new rows accrue they stop returning cold-start defaults and use the
  deployment's own history. Pre-flight estimates and confirmation thresholds can change.
- **With an OTLP endpoint set, the arq worker now exports spans** for every job (before,
  only the API and the gateway did), under the service name
  `LQ_AI_ARQ_WORKER_OTEL_SERVICE_NAME`. The autonomous, tabular, orchestration and citation spans record a failure's class and never its message; other spans, such as the playbook and skill spans, still record it.
- **The shared citation pattern accepts emphasis after a closing quotation mark** and
  closes a curly quotation at the nearest opening quote (see `docs/citation-engine.md`).
  This applies to ordinary chat as well.
- **Where the operator's gateway setting pseudonymizes at a route's tier, a governed run's
  tool results and tool-call arguments are pseudonymized with the rest of the request (the run asks for this with `lq_ai_restore_tool_arguments`).** Ordinary chat is unchanged.

## Evidence and limits

This plan comes from reading the code at the baseline above and from the
[UAT record](../uat/adr35-chat/README.md). The plan itself was written before
anything was run, and its sizes were guesses. The implementation status above
is evidence from controlled-provider tests and from single runs by agents on local
models. The recorded runs use a fictional agreement, short fictional documents and a
scripted or local model. They establish no claim about real matters, paid providers or
legal quality.
