# ADR 0038 governed runs in chat: browser walkthrough of 2026-10-14

A first pass on 2026-10-14 was discarded because the stack's worker was running an older build,
and every run in this record was made after that was fixed.

- **Date:** 2026-10-14.
- **Commit:** `00dda1dd8`, the head of pull request #599.
- **Stack:** a machine-local development stack (native processes, the Vite dev server for the web
  pages) on a fresh database at schema 0077. Every document is fictional and was written for the
  stack or for this walkthrough.
- **Model:** `qwen3.8:27b-mlx` through Ollama, as the gateway provider `ollama-local`. The route is
  inference tier 1 with zero prices. The gateway's setting applies no pseudonymization at tier 1, so
  the route is not pseudonymized on this stack. The composer's "Limits and tools" said so: "Text is
  sent to the model as written: the operator's setting applies no pseudonymization at this route's
  tier."
- **Each scenario is one run, not a rate.**
- **Who drove it:** an agent drove the real page with Playwright and headless Chrome. No person has
  followed these steps. Nothing here is human acceptance.
- **What a match means:** "N of M checked quotations matched" says that each checked quotation was
  found in the file its source number names. It does not say the answer is correct or complete.
  Nobody checked the answers' legal substance.

`walk.json` holds the facts per scenario: chat and run ids, statuses, seconds, the lines as text,
whether an approve button was offered, quotation counts, the runs' terms, audit rows by privilege
mark, the stored text of every message, page errors and failed responses. Times are seconds by the
driver's clock. Screen recordings of all nine scenarios exist, with a cue list for each. They are
kept outside the repository because of their size.

**Set-up for scenarios 7 to 9.** Through the API: a second matter, "Lending matter", privileged
with a minimum inference tier of 2; a knowledge base "Lending references" attached to it; and
fictional files put in that knowledge base only. One of those files, `facility-rate-sheet.txt`, was
attached to the demo matter before this record was made, so in this record the demo matter's
picker lists it beside the two seeded documents, with the lending matter's note. No run in this
record read it.

## 1. The model picker

A new chat in the matter "Harness demo matter" opened with the alias `smart` chosen. The skill
picker, "Keep skills on", the prompt enhancer and the button that attaches a knowledge base were on
the page.

The open picker listed a group headed "Experimental" first. Its one entry was "New harness", with
an `experimental` chip, the route `ollama-local/qwen3.8:27b-mlx` and the note "Answers a request
that needs nothing read. Otherwise plans it, and runs the tasks you approve." The aliases followed.

With New harness chosen, the skill picker, "Keep skills on", the prompt enhancer and the
knowledge-base button were not on the page. Typing "/" opened no skill list. The box's placeholder
read "Ask New harness…". The empty thread read "No messages yet. Type a request and send it. New
harness answers a request that needs nothing read, and otherwise proposes a plan for you to
approve."

With `smart` chosen again, all four controls were back and "/" opened the skill list. New harness
was then chosen once more and the page reloaded: New harness was still the chat's model. No model
call was made.

Screenshots: `01-picker-new-harness-first.png`, `02-picker-new-harness-chosen.png`,
`03-picker-ordinary-model-chosen.png`.

## 2. A run on two documents

In a new chat in the demo matter, New harness was chosen and the two seeded documents were ticked
(`services-agreement.txt` as 1, `data-processing-addendum.txt` as 2). The request was "Compare the
payment terms in the services agreement with the personal data breach notice duty in the data
processing addendum. Quote the clauses you rely on."

The page showed "Reading your request…". After 43 s the status read "Waiting for your approval" and
the plan's line "Plan proposed · 2 tasks · total cap $5.00 · waiting for your approval", with
"Approve plan" and "Reject plan". The plan card named each task, the system prompt it is pinned to,
its tools, the two numbered documents, and "Tasks may search: Harness policies."

"How this run was set up" on the plan showed "System prompt: new_harness/orchestrator.v2 (version
2)" with the first characters of its digest, the prompt's text (9,279 characters), an opening
message with the sections STEP, REQUEST, CONVERSATION SO FAR, DOCUMENTS, KNOWLEDGE BASES, TODAY'S
DATE and LIMITS, and one tool offered, `propose_plan`. The check line read "Rebuilt from this run's
records. It matches the digest recorded when the call was sent." "What the model wrote" showed one
`propose_plan` call with the plan as its arguments.

After "Approve plan" the plan's line read "Plan approved · revision 1 · 2 tasks". Each task line
went from "waiting to start" to "Asked the model…" to "done · read 1 document · 2 model calls". The
status line read "2 tasks running", "1 task running", "Combining the answers" and "Answer
delivered". The page updated without a manual refresh. The answer came 269 s after approval.

The answer line read "Answer delivered · 5 of 5 checked quotations matched the selected documents,
7 more were not checked". The note under the run read "5 of 5 checked quotations matched the
selected documents. 7 quoted passages have no source marker and were not checked." Five citation
chips were drawn under the answer, each in the state `verified-exact`, and the five quotations were
underlined in the prose. No separate list of sources was drawn for this run: the list headed
"Files found by search" appears only where a search found a file (scenario 3).

Task line 1, opened, showed its set-up (the sub-agent prompt, an opening message with TASK,
DOCUMENTS, KNOWLEDGE BASES and LIMITS, and four tools offered: `read_document`, `read_note`,
`save_note`, `search_knowledge_base`) and its steps: "Asked the model (turn 1) · asked for 1 tool
call", the `read_document` call with the model's stated reason, "Read document 1
(services-agreement.txt)" with the range of characters read (all 1,495), "Asked the model (turn 2)
· wrote its answer", and the steps that save and share the findings.

The routing log held six model calls for the run's message, all with the purpose
`orchestration_run`, tier 1, and anonymization not applied.

Screenshots: `04-documents-both-ticked.png`, `05-documents-plan-and-how-it-was-set-up.png`,
`06-documents-task-lines-running.png`, `07-documents-answer-quotations-and-sources.png`,
`08-documents-task-line-open-with-its-trace.png`.

## 3. Knowledge base, no document ticked

In a new chat in the demo matter, with New harness chosen and no document ticked, the strip read
"Tasks may search this matter's knowledge bases: Harness policies." The request was "How many days
of annual leave do employees get, and how much can be carried over? Quote the policy."

A plan with one task was shown after 34 s. The plan card read "Tasks may search: Harness
policies." After approval the task line ended as "Annual leave and carry-over policy · done ·
searched 2 times · 2 model calls". The model asked for two searches in its first turn, `annual
leave` and `carry over`. The steps read "Searched the knowledge bases · 3 passages from [1]
leave-policy.txt" and "· 2 passages from [1] leave-policy.txt", each with the model's stated
reason.

The answer came 126 s after approval. The answer line read "Answer delivered · 8 of 8 checked
quotations matched the knowledge-base files they name, 2 more were not checked". All eight chips
were `verified-exact`. Under the answer the list "Files found by search" had one row: "[1]
leave-policy.txt · found by task 1".

Screenshots: `09-knowledge-base-plan-names-it.png`,
`10-knowledge-base-task-searched-and-answer.png`.

## 4. Follow-ups that need nothing read

In the same chat, two more requests were sent with New harness.

**"Shorten that to three bullet points."** The orchestrator answered by itself after 29 s. No plan
card appeared and no approve button was offered at any time. The run's one line read "Answered
directly · no plan · nothing read". The status read "Answer delivered". The note under the run read
"Answered by the orchestrator alone. It read no document and searched nothing for this answer.
Model-generated; not checked." The reply was two opening sentences and three bullets (Entitlement,
Carry-over, Caveat). It repeated quotations from the earlier answer with markers that name the file
("(Source: leave-policy.txt)") rather than a number, and said it had not re-read or re-searched
anything. Opened, the line read "The orchestrator answered this request by itself. No task ran,
nothing was read or searched, and nothing was put to you for approval.", and its set-up listed
`propose_plan` among the tools offered.

**"Thanks."** The orchestrator answered by itself after 18 s, with the same line, the same note and
no approve button. The reply was two sentences beginning "You're welcome." and offering further
help.

Both replies are verbatim in `walk.json` under `stored.s34_chat.messages`. Answering directly was
the model's choice. This is one attempt of each.

Screenshots: `11-follow-up-shorten-answered-directly.png`,
`12-follow-up-thanks-answered-directly.png`.

## 5. Reload

The page was reloaded in two chats, each time after its runs had ended and in the same browser
session.

- In the chat of scenario 2: the run message came back as "Answer delivered", New harness was still
  chosen, and the document picker's closed line read "Documents · 2 selected:
  services-agreement.txt, data-processing-addendum.txt", with both rows ticked and numbered 1 and 2.
- In the chat of scenarios 3 and 4: three run messages came back, each "Answer delivered", two of
  them with the line "Answered directly". New harness was still chosen and the picker read
  "Documents · none selected (optional)".

Screenshots: `13-reload-new-harness-and-last-documents-offered.png`,
`14-reload-thread-each-run-as-it-ended.png`.

## 6. Reject and halt

In a new chat in the demo matter, with the two seeded documents ticked:

**Reject.** The request was "What does each document say about termination and about liability?
Quote the clauses." A plan with two tasks was shown after 26 s. "Reject plan" was pressed. The
status read "You rejected the plan", with "No task work or combined answer will run. The planning
charge stays in the receipts. You can start a new run from the composer." The run's one line read
"You rejected the plan". No task line appeared and the message carried no answer. The routing log
held one model call, the planning call.

**Halt.** The picker offered the same two documents for the next request without their being
ticked again. The request was "List the notice periods in both documents, with a quotation for
each." A plan with two tasks was shown after 21 s and approved. About 12 s later, with the status
"2 tasks running" and both task lines at "Asked the model…", "Halt" was pressed. The status read
"Halted" 3.6 s later, with "You halted the run. No combined answer was produced. Task answers and
files finished before the halt remain below." Both task lines read "halted after 5 steps". The
message carried no answer. The run read gave the stop reason `owner_halt`. Afterwards the server
reported no active run and New harness as available.

Screenshots: `15-rejected-plan-end-state.png`, `16-halted-run-end-state.png`.

## 7. A chat in no matter

A new chat in no matter was opened and New harness chosen. It was available. The strip had no line
about knowledge bases. The open picker read "No documents yet. Attach a file to this chat, then
refresh the list."

A fictional file, `facility-letter.txt`, was uploaded to the chat with the page's "+ Files"
control. The picker listed it, ticked, with no note. Then, through the API and not through the
page, the same file was attached to the lending matter. After "Refresh list" the row carried the
note: "From the matter “Lending matter”. A run that reads it follows its rules: inference tier 2 or
stronger; privileged, so nothing is pseudonymized."

The request was "What is the arrangement fee, and what interest cover must the borrower keep? Quote
the letter." A plan with one task was shown after 50 s and approved. The answer came 93 s later:
"Answer delivered · 2 of 2 checked quotations matched the selected documents". The plan card had no
"Tasks may search" line and the task's tools did not include the search.

**The run's terms.** The run message did not state them. Its "Receipts, digests and accounting"
fold showed the run id, profile, model, accounting, digests and the orchestrator's steps, and
neither it nor "How this run was set up" had a line about a tier floor or a privilege flag. From
the API's run read (`planning.root`) and the records:

- `privileged`: true.
- `minimum_inference_tier`: 1. The lending matter's floor is 2. ADR 0038 D5 says a run records the
  stricter of its matters' floor and the profile's own floor, and the profile's floor on this stack
  is 1.
- The routing log held four model calls, each at tier 1 with anonymization not applied. On this
  stack that is also true of every run that was not privileged, so the walkthrough cannot show the
  privilege flag changing what the gateway did.
- All 53 audit rows that name the run were privilege-marked with the basis "run terms: a selected
  file is held by a privileged matter", across twelve actions from `orchestration.planning_started`
  to `orchestration.root_delivered`.

Screenshots: `17-no-matter-picker-file-with-its-matter-and-terms.png`,
`18-no-matter-run-answer-and-receipts.png`.

## 8. Ruling 12: another matter's knowledge-base file, from a chat in a matter

The file for this scenario, `fee-letter.txt`, was uploaded through the API into no matter and put
in the "Lending references" knowledge base only. It was attached to no matter before the run.

**How the file reached the picker.** The page has no control that names an existing file as a
candidate. Its picker lists the matter's files, files uploaded to the chat in the same page
session, and the documents of the chat's last run. A file uploaded from a chat in a matter is filed
in that matter, which would not be the case ruling 12 describes. So the driver added the file's id
to the page's own read of the list, in the browser (`GET /chats/{chat}/run-documents` gained one
`file_id` value). The server's reply, the row, its note, the tick and the Send were the page's own.

In a new chat in the demo matter the picker listed `fee-letter.txt`, selectable, with the note:
"From the matter “Lending matter”. A run that reads it follows its rules as well as this matter’s:
inference tier 2 or stronger; privileged, so nothing is pseudonymized. Will be added to this matter
when you send the request".

Only that file was ticked. The request was "What agency fee and prepayment fee does the fee letter
set, and what is the cap on legal costs? Quote the fee letter." A plan with one task was shown after
20 s and approved. The answer came 52 s later: "Answer delivered · 3 of 3 checked quotations matched
the selected documents".

**The run's terms**, from the API's run read and the records:

- `privileged`: true. The demo matter is not privileged; the lending matter is.
- `minimum_inference_tier`: 1, for the reason given in scenario 7.
- The run's document entry had `attached_for_run`: true, and afterwards the file was in the demo
  matter's file list.
- The routing log held four model calls, each at tier 1 with anonymization not applied. As in
  scenario 7, this stack cannot show a difference.
- All 54 audit rows that name the run were privilege-marked with the basis "run terms: a selected
  file is held by a privileged matter", including `project.file_attached`.

As in scenario 7, the run message itself did not state the floor or the privilege flag.

Screenshots: `19-ruling-12-picker-note-on-the-lending-matters-file.png`,
`20-ruling-12-run-answer.png`.

## 9. Ruling 13: an ordinary follow-up after a stricter answer

Each chat was opened in a new browser session, so no file was attached in the page's own file
panel. In both chats the picker already showed the alias `smart` when the chat opened (finding 6).
`smart` was picked in the model picker, and the ordinary message "Repeat your previous answer word
for word." was sent. The request the page sent carried the model `smart` and no file ids.

**A. The chat of scenario 7** (in no matter; its run read the privileged lending matter's file and
answered with the arrangement fee of GBP 9,300 and the interest cover of 4.25 times). The reply came
after 9 s and held neither figure. The model's reply, verbatim:

> [An earlier answer is not shown here. It was written under stricter data terms (a matter's
> inference tier floor or privilege flag) than this request has.]

That is the application's note for a withheld answer, word for word. Asked to repeat its previous
answer, the model repeated the text it had been given in that answer's place. The routing log
recorded the call with 83 input tokens.

**B. The chat of scenario 2** (in the demo matter; its run read that matter's own two documents).
The reply came after 39 s and reproduced the earlier run's answer. Compared as text with the stored
answer, the similarity ratio was 1.0, and it held "GBP 4,500" and "48 hours". The routing log
recorded the call with 1,339 input tokens. The reply is verbatim in `walk.json`
(`scenarios.9_ruling_13.after_an_answer_on_the_matters_own_terms.reply_verbatim`).

Each ordinary reply carried the badges "Tier 1" and "Fiduciary-grade".

Screenshots: `21-ruling-13-ordinary-follow-up-after-the-stricter-answer.png`,
`22-ruling-13-ordinary-follow-up-in-the-demo-matter.png`.

## Not covered

- **An uncertain run and closing it.** It needs a provider timeout, which a working local model does
  not give. It was not attempted.
- **Pseudonymization.** The route is not pseudonymized on this stack, so nothing here shows text
  being replaced or restored, or the privilege flag turning that off.
- **A tier floor refusing a route.** The route is tier 1, which meets every floor.
- **A reload while tasks were running**, and the notice in a second chat while a run is active.
- **A model that fails.** No plan failed, no quotation failed to match, and no call timed out in
  these runs. The pages for those cases were not seen.
- **The answers' substance.** Nobody checked them against the documents beyond the application's
  own quotation check.

## Findings

Each is one observation on one stack. "Application" and "model" say where the behaviour comes
from, as far as this walkthrough can tell.

1. **The run message does not state the run's tier floor or privilege flag (application).** In
   scenarios 7 and 8 the picker's note said what the file brings before the request was sent. After
   that, the plan card, "How this run was set up" and the receipts fold said nothing of it. The
   terms had to be read from the API. Evidence: `18-…png`, `20-…png`; `walk.json`,
   `run_terms_from_the_run_read` under scenarios 7 and 8.
2. **Ruling 12's case cannot be reached from the page alone (application).** See "How the file
   reached the picker" in scenario 8. Evidence: `walk.json`,
   `scenarios.8_ruling_12.how_the_file_became_a_candidate` and `requests_rewritten`.
3. **The model wrote quoted passages with no source marker in most planned answers (model).**
   Passages not checked: 7 in scenario 2, 2 in scenario 3, none in scenarios 7 and 8. The page
   counted them and said they were not checked. In scenario 4 the direct answer's markers named the
   file instead of a number, and the page labelled that answer not checked. Evidence: the note under
   each answer; `evidence_result.unmarked` in `walk.json`.
4. **Quotations in a block quote are drawn with two sets of quotation marks (application styling,
   with the model's formatting).** Where the model put a quotation in a Markdown block quote, the
   page drew its own curly marks around the model's straight ones. Evidence: `18-…png`.
5. **A font file is refused on every page load (stack, not the feature).** The dev server answered
   403 for one font file, once or twice per scenario. There were no page errors and no other failed
   responses in any scenario. Evidence: `page.failed_responses` under each scenario.
6. **The choice of New harness is kept by the browser, not the chat (application).** In scenario 9
   the chats of scenarios 2 and 7, whose model had been New harness, opened in a new browser
   session with `smart` chosen. Every reload in scenarios 1 and 5 was in the same browser session
   and kept New harness. Evidence: `walk.json`, `scenarios.9_ruling_13.*.picker_button_before`.
7. **Ruling 13 held in the one attempt made (application).** The ordinary follow-up after the
   privileged run's answer received the note in that answer's place, which the model repeated word
   for word; the one after the demo matter's run repeated the answer exactly. Evidence: `21-…png`,
   `22-…png`; `walk.json` under `9_ruling_13`.
8. **Every audit row of the two privileged runs was privilege-marked (application).** 53 of 53 in
   scenario 7 and 54 of 54 in scenario 8, all with the run-terms basis. Evidence: `walk.json`,
   `audit_rows_by_privilege_mark` under both scenarios, and `stored.*.runs[].audit_rows`.

Nothing else went wrong in the page during the nine scenarios: no error dialog, no control that did
nothing, and no text seen to contradict what the API returned.
