# ADR 0038 governed runs in chat: recorded walkthrough

**Date:** 2026-10-06. **Base commit:** `5e128d5ba`. The feature is uncommitted
working-tree changes on top of that commit.
**What this is:** screenshots and API records of governed runs in chat, taken by an
agent driving a real browser against services running natively on one machine.
**What it is not:** human acceptance; a run on a hosted provider; a full Docker
stack; a test that CI runs; or any statement that an answer is legally sound.
A person should follow the [UAT runbook](../../runbooks/adr38-runs-in-chat-uat.md).
[ADR 0038](../../adr/0038-skill-backed-orchestration-profile.md) is proposed, not
ratified.

## Two providers

Files `01` to `26` use a **scripted provider**. It is an OpenAI-compatible stub
behind the gateway (`controlled/scripted-1`). It reasons about nothing: it returns
a fixed plan, asks for the tools a task is granted, and copies sentences out of
the documents it is given. It can also be told to never answer, to return a plan
that is not usable, to add a quotation that is in no document, to ask for tools
it was not granted, and to put markup in everything it writes. Its rates are
invented for this walkthrough (0.50 per million input tokens, 1.50 per million
output tokens) so that budgets, reservations and charges show amounts. The stub
costs nothing to call.

Files `30` to `48` use a **local model**: `gemma4:26b-mlx-64k` served by Ollama on
the same machine, reached through the gateway's `ollama` provider at tier 1 with
zero rates. Nothing scripted the model. See [the local-model pass](#the-local-model-pass).

## How it was set up

- API, arq worker, ingest worker and gateway ran as native processes from the
  working tree. Postgres (pgvector), Redis and object storage ran in three
  throwaway containers. The web client ran from the working tree under Vite, with
  the published v0.8.0 web image as the OpenWebUI shell it needs in development.
- Both run profiles were switched on. Budgets were 2.00 USD (fictional profile)
  and 5.00 USD (document profile). The attempt timeout was 60 seconds on the stub
  and 600 seconds on the local model. Gateway anonymization was on at tier 1.
- One user, with Autonomous turned on, and one matter, "Harness demo matter",
  holding two short fictional documents (`services-agreement.txt`,
  `data-processing-addendum.txt`), a PNG that cannot be read, and files the
  scenarios added. Every document is fictional.
- A Playwright script drove headless Chrome at 1440 by 900. Each scenario waited
  on what the page showed. Files ending in `-full` are a screenshot of the whole
  run message; the others are the browser window.
- The stub, the stack scripts and the browser script are not part of the branch.
  They are kept with the maintainer and can be added if wanted.
- With the invented rates the budget rule gave: fictional profile, planning
  allowance 0.062, per-task allowance 0.186, up to four tasks; document profile,
  planning allowance 0.1446, per-task allowance 0.8676, up to four tasks. The
  screenshots show these figures.

`00-manifest.json` lists every file here with the scenario that produced it and a
fingerprint of the run interface's source at that moment. One fingerprint covers
every scripted file. Two small changes were made after the last capture; see
findings 9 and 12.

## What each screenshot shows

Each screenshot was looked at by the agent before it was listed. "UAT" is the
case in the runbook that the picture corresponds to. A picture is not a pass of
that case: a person has not run it.

### Fictional profile, scripted provider

| File | Shows | UAT |
|---|---|---|
| `01-profile-menu.png` | The Run control beside the model picker, open, listing both profiles | 02, 14 |
| `02-run-mode-request-typed.png` | Run mode: model, total cap, planning and per-task allowance, maximum tasks, attempt limit, tool turns, tools, what the run may read, and that the planning call sees the request only | 02, 04 |
| `03-planning-full.png` | The run message while the plan is being proposed | 04 |
| `04-plan-awaiting-approval-full.png` | The plan card: tasks, skill and version, tools, numbered document, budget and tool turns per task, Approve and Reject, the planning charge | 05 |
| `05-in-progress-full.png` | Two tasks running: a model turn, a document read with its character range and the model's stated reason, a note saved, amounts spent and reserved | 06 |
| `06-completed-receipts-open-full.png` | The delivered run with every fold open: task answers, steps, receipts with charges and skill pins, accounting, digests, and the answer below it with skill chips and tier badge | 07, 28 |
| `06-completed-tier-details.png` | The tier panel of the run's message: provider, model, token counts and cost | 07, 28 |
| `07-follow-up.png` | An ordinary turn sent after the run in the same chat, and its reply | 08 |
| `08-rejected-full.png` | A rejected plan | 09 |
| `09-halted-full.png` | A run halted while its tasks were working, with what had finished | 10 |
| `10-plan-failed-full.png` | A run whose plan could not be used (the stub returned prose) | — |
| `11-uncertain-full.png` | A run left uncertain after a call was sent and never answered, with the explanation, Close run and Halt | 23 |
| `11-closed-full.png` | The same run after Close run: each unresolved call closed without an outcome and charged | 25 |
| `12-profile-menu-unavailable.png` | A second chat while a run waits for approval: both profiles unavailable with the reason, and the notice naming the run | 12, 36 |
| `12-active-run-notice-uncertain.png` | A second chat while a run is uncertain: the notice, Open that chat and Close run | 24 |
| `12-after-close-other-chat-can-start-again.png` | The same second chat about fifteen seconds after the run was closed, without a reload: no notice, profiles selectable | 26 |
| `13-after-reload-while-running.png` | The run message after a full page reload while tasks were running | 11 |
| `14-hostile-plan-full.png` | Markup in the plan's task text, shown as text | 37 |
| `14-hostile-answer.png` | Markup in the delivered answer, shown as text, with Markdown structure kept | 37 |

### Document profile, scripted provider

| File | Shows | UAT |
|---|---|---|
| `15-document-picker.png` | The picker: numbered selection, and a file that cannot be read with its reason | 15 |
| `15-chat-only-file-in-picker.png` | A file attached to the chat only, marked as one that will be added to the matter | 16 |
| `16-documents-plan-full.png` | The plan card naming the two selected documents for each task | 16 |
| `16-chat-only-file-added-to-matter-on-plan.png` | The plan card marking the chat-only file "added to this matter for this run" | 16 |
| `17-documents-answer-full.png` | The delivered answer: reads by document number and file name, the evidence line "3 of 3 checked quotations matched the selected documents", underlined quotations and citation chips | 17, 18 |
| `17-documents-ledger-panel.png` | The citation ledger for that answer: three exact matches with character offsets | 18 |
| `17-long-document-read-cut-short.png` | A document longer than one read, reported as cut short (0 to 40,000 of 83,191 characters) | 17 |
| `18-documents-bad-quote-answer.png` | The evidence line when one quotation is in no document: "3 of 4 checked quotations matched … 1 could not be matched and is marked unverified" | 19 |
| `18-documents-bad-quote-answer-citations.png` | That answer's chips: three matched, one unverified, and the "Unverified claims flagged" badge | 19 |
| `18-documents-bad-quote-ledger-panel.png` | The ledger for that answer | 19 |
| `19-receipts-drawer-model-calls.png` | The chat's receipts drawer: skill events and one event per model call with provider, model, tier, tokens, latency and anonymization | 29 |
| `19-receipts-drawer-audit.png` | The drawer's audit view: the run's audit rows | 29 |

### Other surfaces, scripted provider

| File | Shows | UAT |
|---|---|---|
| `20-autonomous-sessions-list.png` | The sessions list at `/lq-ai/autonomous` with the runs' sessions | — |
| `20-run-receipt-page-documents-run.png` | The stand-alone receipt page of a run | — |
| `20-autonomous-orchestration-chat-notice-no-form.png` | The old intake address: a notice that runs start from a chat, and no form | 01 |
| `21-chat-without-matter.png` | A chat outside any matter: profiles unavailable with the reason | 03 |
| `21-autonomous-off-run-menu.png` | The user's Autonomous setting off: profiles unavailable with the reason | 03 |
| `23-tool-refused-steps.png` | Three refused tool calls (a document that was not selected, a tool that was not granted, arguments that did not fit) and the task carrying on | 06 |
| `24-export-ready.png` | Settings, Account, Export my data, with the export ready | 21 |
| `25-matter-workspace-plan-awaiting-approval.png` | A run started from the matter workspace's own chat | 35 |
| `26-switched-off-run-menu.png` | Both switches off: profiles unavailable with "The operator has not enabled this profile", a retained run still shown | 01, 13, 22, 38 |
| `26-switched-off-completed-run-readable.png` | A completed run still readable with the switches off | 13, 22, 38 |

### Local model

| File | Shows |
|---|---|
| `30-local-model-composer.png` | Run mode with the local model pinned and a ten-minute attempt limit |
| `31-local-model-plan.png` | The plan the model proposed on the fictional profile |
| `33-local-model-final.png` | That run delivered: each task asked for one document read, gave a reason, and answered |
| `41-local-model-plan.png` | The plan the model proposed on the document profile |
| `43-local-model-final.png` | That run delivered on the final code: reads of both documents, "3 of 3 checked quotations matched the selected documents" |
| `47-local-model-documents-attempt-1-synthesis-failed.png` | The first attempt: both tasks done, the combined answer not produced, task answers kept |
| `48-local-model-documents-attempt-2-before-the-fixes.png` | The second attempt, before two fixes: `[§2]` in place of a section mark, and "2 of 2 quotations matched" although two quoted passages had no marker |

## Records beside the screenshots

JSON files carry what a picture cannot. They hold identifiers, counts, statuses
and the fictional text of these runs. A scan for tokens, keys and passwords
found none.

- **Run reads** at each stage: `04-run-awaiting-approval`, `05-run-in-progress`,
  `08-run-rejected`, `09-run-halted`, `10-run-plan-failed`, `11-run-uncertain`,
  `11-run-closed`, `14-run-hostile`, `17-documents-run`, `17-long-document-run`,
  `18-documents-bad-quote-run`, `23-run-tool-refused`.
- **The run's message** with its skill, tier, provider, model, token and cost
  fields: `06-`, `17-`, `18-` and `23-chat-messages-*`.
- **Routing log** (`*-inference-routing-log-rows-*`): eight rows for each of four
  runs. Every row has purpose `orchestration_run` and the chat and message
  identifiers (UAT-30).
- **Chain of custody** (`*-work-product-attribution-*`) and **receipts feed**
  (`*-chat-receipts-*`) for the same runs.
- **Availability** (`*-run-profiles-*`): available; a run active in another chat;
  an uncertain run in another chat; after a close, a halt, a rejection and a
  failed plan; a chat with no matter; a chat in another matter; Autonomous off;
  each switch off.
- **Refusals:** `12-second-start-refused*` (409 while a run is active or
  uncertain), `11-close-on-completed-run-refused` (409),
  `11-close-again-on-closed-run` (the same state returned),
  `26-switched-off-refusals` (403 for a new run and for approving a retained one).
- **Operator view:** `00-admin-orchestration-profiles`, and the same with the
  switches off and back on.
- **Other checks:** `06-run-follows-without-manual-refresh` (the page followed a
  run with Refresh never pressed), `13-reload-receipt-counts` (one planning call
  before and after the reload), `14-hostile-dialogs-and-dom` (no dialog fired; no
  `img`, `script` or `b` element came from the hostile text; a control dialog was
  caught by the same handler), `16-chat-only-file-added-to-matter` (the matter's
  files before and after, and the `project.file_attached` audit row),
  `17-long-document-reads`, `20-autonomous-pages-no-intake-form` (no form,
  textarea or Propose button on the stand-alone pages), `24-export-zip-contents`
  (the export holds `orchestration_runs.json`, the run message and its custody
  row), `07-follow-up-what-the-model-was-sent` (the follow-up turn's history held
  the run's answer), `07-chat-search-finds-the-run` (UAT-31).

## The local-model pass

One model, one machine, one evening. The claims are no wider than that.

| Run | Code | Result |
|---|---|---|
| Fictional profile, first run | before the fixes below | Completed about a minute and a half after the request was sent. Two tasks. Each asked for one document read, gave a reason, and answered with clause references. Six model calls. |
| Document profile, attempt 1 | before the fixes | **Failed** with "The combined answer could not be produced". Both tasks finished, each reading both documents. The final call returned 8,192 output tokens, the limit, of which 77 characters were answer: the model spent the rest reasoning. The cut-off answer was refused and the task answers were kept (`47-…`). |
| Document profile, attempt 2 | before the fixes | Completed. It showed two defects in the application (findings 4 and 5) (`48-…`). |
| Fictional profile, second run | final code | Completed (`30-`, `31-`, `33-`). |
| Document profile, attempt 3 | final code | Completed. Both tasks wrote their quotations with source markers. "3 of 3 checked quotations matched the selected documents." Section marks are shown as section marks (`40-`, `41-`, `43-`). |

What the pass showed:

- The model called the document tool through the gateway's Ollama provider with
  native tool calls, gave a reason with each call, and read only the selected
  documents. No call was refused.
- Tasks used one or two of their tool turns. No task saved a note.
- The final call's reasoning is heavy on the document profile: it used 8,192,
  7,220 and 4,388 output tokens across the three attempts, against a limit of
  8,192. The limit is too tight for this model on that profile.
- In attempt 2 one task wrote its quotations without the `(Source: [N])` marker.
  In attempt 3 both tasks used it. Whether a model follows the marker form varies
  from run to run.
- In attempt 3 the combined answer holds one literal `\n\n`. The orchestrator
  receives the tasks' findings as JSON, where a line break is written `\n`, and
  the model copied it. Not fixed.
- Every model call was recorded with purpose `orchestration_run`, the chat and
  message identifiers, tier 1 and anonymization applied. The message's cost is
  0.00 because local inference is priced at zero.

## Findings

Found by this walkthrough. Items 1 to 6, 9 and 12 were fixed while it ran, and the
screenshots and records here come from the code after those fixes, except where a
file name or the item says otherwise.

1. **The composer's notice about the active run went stale.** It read "Proposing a
   plan" while the run message beside it read "Waiting for your approval", and in
   another chat it never noticed that the run had ended. Fixed: the notice follows
   the run message in the same thread, and the composer reads availability again
   every ten seconds while a run is active. `04-composer-notice-against-run-message.json`
   records what the notice and the message said at each stage after the fix.
2. **A halted run did not say who halted it.** The runbook expected "You halted the
   run". Fixed in the interface (`09-halted-full.png`).
3. **Markup in a run's answer was drawn as HTML.** The answer went through the
   ordinary path for assistant messages, which sanitises HTML and draws what
   remains, including images. No script ran, but the plan's acceptance requires
   text. Fixed: a run's answer keeps its Markdown structure, shows raw HTML as
   text and never loads an image (`14-hostile-answer.png`). Ordinary assistant
   messages are unchanged.
4. **Text was sent to the model as escapes.** Run inputs were written as JSON with
   every non-ASCII character as `\uXXXX`. The local model, told to keep quotations
   exactly, copied `§` into its answer in place of a section mark
   (`48-…`). Fixed: characters are sent as themselves (`43-…`).
5. **The evidence line could read wider than the checks.** Only a quotation written
   with a marker for a selected document is checked. An answer with two unmarked
   quotations read "2 of 2 quotations matched" (`48-…`). Fixed: the line says
   "checked quotations", and counts quoted passages with no marker and markers
   that name no selected document as not checked. The scripted answers contain
   neither, so no screenshot here shows those sentences; the tests do.
6. **A task card printed its first line twice.** Fixed.
7. **A model that reasons can use the whole output limit before it answers.** See
   attempt 1 above. Not fixed. The runbook now says so, and the limit for the
   document profile is still a placeholder.
8. **The cost on the run's message is the run's accounted spend, not the sum of the
   gateway's estimates.** For the scripted fictional run the message shows 0.3143
   and its eight routing-log rows sum to 0.0555. The run charges the larger of a
   conservative estimate and reported usage for each call, as ADR 0035 specifies.
   Left as built, for review; the plan records it.
9. **While answers were being combined, the current-step line could read "Asked the
   model for a plan".** Seen in the local-model run just after the last task
   finished. Fixed after the last capture, with a test. No screenshot kept here
   shows that moment.
10. **A new chat keeps the title "New chat" in the page after a run is proposed,
    until the page is reloaded.** The API holds the title taken from the request
    (`04-title-from-request.json`). The page does not read a chat's title again
    after an ordinary send either, so this was left alone.
11. **Pressing a citation chip under an answer opens nothing.** The badge beside
    the chips opens the ledger, which lists each quotation with its text and
    offsets (`17-citation-chip-click-effect.json`, `17-documents-ledger-panel.png`).
    Chips under an ordinary answer behave the same way: the message bubble does not
    act on a chip being pressed, before or after this work. Left alone. The runbook
    now sends the tester to the ledger.
12. **A task list in a run's answer would have lost its ticks.** The stricter
    renderer of finding 3 forbids form controls, and Markdown draws a task list's
    ticks as checkboxes. Found by a test, not in the browser. Fixed after the last
    capture: the ticks are shown as `[x]` and `[ ]` in text. No screenshot here
    shows a task list.
13. **The browser was signed out twice during early passes.** Vite reloaded the
    page, after another process edited the web source, while a token refresh was
    in flight, and the rotated refresh token was lost. This is an effect of the
    shared development server. The authentication code is unchanged by this work.

## Not captured

- **A run that outlasts the 15-minute access token, and the 30-minute idle
  sign-out** (UAT-33, UAT-34). No run here lasted that long.
- **A trace through a Collector** (UAT-32). Tracing was not configured. The spans
  are covered by tests with an in-memory exporter.
- **A tier floor stronger than the route** (UAT-20). Covered by a test.
- **Hostile text inside a document** (the second half of UAT-37). The hostile
  scenario puts markup in the request and in everything the provider writes. A
  test covers a document that tries to redirect the run.
- **A child reading on from a cut document.** The stub never asks for the next
  part, so `17-long-document-read-cut-short.png` shows the cut being reported,
  not a continued read.
- **The evidence line's sentences about unmarked quotations**, as noted in
  finding 5.
- **The full Docker stack, a hosted provider, a second user, PDF documents and
  the Word add-in.** None was exercised.
