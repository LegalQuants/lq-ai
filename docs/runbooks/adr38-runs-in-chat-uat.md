# ADR 0038 governed runs in chat: UAT

This test checks that a governed run works as a turn in the main chat when the owner
chooses **New harness** in the model picker. The owner sends a request. The orchestrator
either answers it by itself or proposes a plan, the owner approves that exact plan, and
sub-agents carry out its tasks. The answer arrives in the same thread, and the owner can
read how each call was set up. The test covers a chat in a matter, a matter with a
knowledge base, a chat in no matter, a route that pseudonymizes, and the controls to
reject a plan, halt a run and close an uncertain one.

**A passing run shows that the flow, the controls and the records work. It does not show
that an answer is legally sound.** An answer the orchestrator gives by itself read nothing,
and the page says so. Where an answer quotes a source, "N of M checked quotations matched"
says that each checked quotation was found in the file whose source number it cites. It does
not say that a task was shown that passage, that the words support the point they are cited
for, or that the answer is correct or complete. Before New harness is described as working
live, a person must accept it on a configured provider; see
[Evidence and sign-off](#evidence-and-sign-off).

**Status.** [ADR 0038](../adr/0038-skill-backed-orchestration-profile.md) is Proposed,
not ratified. The implementation is on an unmerged branch, has had no maintainer or
security review, and does not merge before ratification. Both profile switches default to
off. The direct answer amends ADR 0035 D1, which is Accepted; that amendment is a separate
draft awaiting its own ratification. Design, and what was and was not verified:
[plan](../plans/issue-662-c1-governed-runs-in-chat.md#implementation-status). This runbook
replaces the one written for the first build, which had a profile control beside the model
picker. The recorded walkthrough in
[`docs/uat/adr38-runs-in-chat/`](../uat/adr38-runs-in-chat/README.md) shows that build and
not this one. The earlier stand-alone page, as released in 0.8.0, is covered by the
[ADR 0035 runbook](adr35-chat-uat.md).

## Setup

Use a dedicated, disposable deployment, a user with Autonomous mode enabled, and an
admin account. Do not test on a deployment whose data you cannot lose.

**Migrations.** Apply 0070 to 0073 (after 0069) by rebuilding `api`, `arq-worker` and
`ingest-worker` together, so no sibling runs on an old revision. Rebuild `web` too: it
serves a pre-built bundle, so a UI change does not appear until it is rebuilt. Never run
host-side `alembic upgrade` against a running development database; it desyncs the stack.
Check the migrations on a throwaway `pgvector/pgvector:pg16` container instead. Never use
`docker compose down -v`. Each of the four migrations refuses to downgrade while the rows it
introduced are retained: 0070 chat-hosted runs and registry-profile runs, 0071 closed runs
and effects, 0072 runs that belong to no matter, 0073 runs that completed without a plan. Keep
a deployment that has used this feature at 0073 until a reviewed export and removal plan
exists. A 0.8.0 run that is in flight when the branch is deployed stops at its next
admission and stays readable; complete or halt runs first.

**Skills.** New harness is instructed by engine prompt files and needs no skill. The 0.8.0
profile, kept as a test fixture, uses the built-in skills `contract-qa` and
`orchestration-chat-demo`; they matter here only if you switch that profile on (UAT-05).

**Settings.** Set these on both the API and the arq worker. The two Compose files pass
them to both services. The budget values are the `.env.example` defaults, not
recommendations; size them as described under [Sizing the budget](#sizing-the-budget).

```dotenv
LQ_AI_ORCHESTRATION_DEPLOYMENT_CHILDREN=2

# New harness: its own switch and route; nothing is inherited from the 0.8.0 profile
LQ_AI_NEW_HARNESS_ENABLED=true
LQ_AI_NEW_HARNESS_PROVIDER=<direct-gateway-provider-name>
LQ_AI_NEW_HARNESS_MODEL=<native-model-id>
LQ_AI_NEW_HARNESS_BUDGET_USD=5.0000
LQ_AI_NEW_HARNESS_MINIMUM_TIER=1
LQ_AI_NEW_HARNESS_TIMEOUT_SECONDS=300
# Leave empty unless you are testing it; see "Route" below
LQ_AI_NEW_HARNESS_REASONING_EFFORT=
```

`LQ_AI_ORCHESTRATION_DEPLOYMENT_CHILDREN` is the shared child capacity (1 to 32). It is
required before any profile can be enabled; drain runs before changing it. Enabling the
0.8.0 profile (`LQ_AI_ORCHESTRATION_CHAT_ENABLED` and its project, provider and model
settings, as in the [ADR 0035 runbook](adr35-chat-uat.md)) never enables New harness, and
the reverse. New harness has no project setting: it runs in any active matter the owner
owns, and in a chat in no matter, subject to the matter's inference-tier floor and
privilege flag. A switched-on profile with incomplete settings is reported to the owner as
not configured. If a switch is on but no profile is fully configured, or the shared child
capacity is unset, the arq worker refuses to start. As an admin, read
`GET /api/v1/admin/orchestration/profiles` and confirm that the profiles appear with the
state you expect and no `problem`.

**Route.** New harness pins one direct gateway provider and model. Configure exact gateway
prices for `provider/model`; local inference needs explicit zero prices. Aliases, missing
prices, a tier weaker than the matter allows and route drift are refused. Pseudonymization
follows the gateway's own `anonymization` setting for the route's tier. Where that setting
applies none, a run is not refused; the composer says that text is sent as written (section
H).

**A model that reasons before it answers spends its output limit on that reasoning.** The
limit (8,192 tokens per call) covers reasoning and answer together, and
`LQ_AI_NEW_HARNESS_REASONING_EFFORT` ships empty, so nothing is sent for it. On the two local
models it was tried on, a level did not reduce reasoning and only `none` did, and a model that
cannot think may refuse every call. Try a value against the pinned model before you rely on
it (ADR 0038, open question 5).

**The pinned model must support native tool calls (function calling).** The planning call is
offered the tool `propose_plan`, and sub-agents are offered their tools. A provider that
rejects a request carrying tool schemas leaves the run uncertain at its first call, which the
owner can then close (section G). A model that does not call the tool and writes its plan out
as text fails the plan; any other complete reply is shown as the orchestrator's own answer.
Check the model's tool support before you start.

**Time limits.** The attempt timeout (1 to 900 seconds) is shown in the composer before
planning and is pinned in the proposal. A provider timeout leaves the call uncertain and
is never retried. Single calls on local models have exceeded their timeout in earlier
testing, so set it to suit the model. The run deadline includes the approval wait: two
hours for New harness and one hour for the 0.8.0 profile. A run on a local model takes
minutes; record how long each case took.

**Test data.** Prepare a test matter owned by the test user:

- two readable test documents attached to the matter (plain text, Markdown or a PDF with a
  text layer), short and fictional, for example `msa.txt` and `dpa.md`;
- one file the run cannot read, such as a Word file or an image-only PDF;
- for section D, a knowledge base attached to the matter, its documents ingested to `ready`,
  on a subject the two documents do not cover, for example a leave policy;
- for UAT-25 and UAT-29, a second matter, and for section E a chat that is in no matter.

Use documents you are allowed to send to the configured provider, and keep every request
fictional. The text a task reads, and the passages a search returns, are sent to that
provider as stored: they travel as tool results, which the gateway does not rewrite. The
request, the chat's recent messages and the task text are pseudonymized only where the
gateway's setting applies it at the route's tier (section H). The planning call is given the
selected file names and the knowledge bases' names, not their text. Use non-confidential test
documents until New harness has been accepted and reviewed.

## Sizing the budget

The composer shows the result of this rule before any planning is paid for. The rule is in
`prepare_intake` in `api/app/autonomous/orchestration/intake.py`.

- **One unit** is one model call at the profile's input and output limits, priced at the
  route's explicit rates. The limits are 262,144 input bytes and 8,192 output tokens for
  New harness, and 98,304 input bytes and 8,192 output tokens for the 0.8.0 profile. The
  accounting counts each input byte as a token and adds a small fixed overhead. A unit is
  a conservative accounted estimate, not a provider invoice, and the composer's planning
  allowance is one unit.
- **The root gets two units**: one for planning and one for the combined answer. An answer
  the orchestrator gives by itself is the planning call alone.
- **Each task gets one unit per model call it may make**: the profile's tool turns plus one
  final answer turn, plus the quote of any priced tool. The 0.8.0 profile allows two tool
  turns, so three units a task. New harness allows five, so six units a task. The tools
  shipped with the profiles are not priced, the knowledge-base search included.
- **The total cap decides how many tasks can be funded**: the cap, less the root's two
  units, divided by one task's allowance, rounded down, and never more than four. As an
  illustration in units, not a cost, a cap of 11 units funds three tasks on the 0.8.0
  profile and one on New harness. A route with explicit zero rates costs nothing, so it
  funds the maximum of four.
- If the cap cannot fund planning, one task and the combined answer, the profile is
  unavailable and the composer shows "Run budget cannot fund planning, one task and
  synthesis".
- The planner is told the funded number, and a proposal with more tasks fails as an
  unfunded plan.
- Release 0.8.0 gave a task one unit, so on a priced route this branch funds fewer tasks at
  the same `LQ_AI_ORCHESTRATION_CHAT_BUDGET_USD`.

Record the composer's figures (model, total cap, planning allowance, per-task allowance and
the number of tasks) with the results below.

## Acceptance script

Run the cases in order; some use the run of an earlier case. The Result column is for the
tester; a case is not accepted until a person has filled it in. Quoted interface wording is
what the web components on the branch show at the time of writing. If the wording differs,
record the difference; it does not fail the case on its own.

Some cases depend on what the model chooses: UAT-15 (a follow-up), UAT-19 and UAT-20 (a
request that needs nothing read), UAT-21 (a question about a selected document), UAT-27
(the same, in a chat in no matter) and UAT-41 and UAT-42 (a request that names a person on a
route that pseudonymizes). For each attempt, record the request, whether the model planned
or answered directly, and the answer. The outcome is the model's, and one attempt is not a
rate.

### A. The model picker and the composer

| ID | Action | Expected result / evidence | Result |
|---|---|---|---|
| UAT-01 | With `LQ_AI_NEW_HARNESS_ENABLED` off, open a chat in the test matter and open the model picker. Open the stand-alone page at `/lq-ai/autonomous/orchestration/chat`. | New harness is the first row, in a group headed "Experimental", with an `experimental` chip. The row is disabled and gives its reason, "The operator has not enabled New harness."; clicking it chooses nothing. Ordinary models send normally, and no model call is made for New harness. The stand-alone page has no intake form: it reads "Runs now start from a chat" and says that "A request that needs nothing read is answered there at once. Otherwise you review and approve its plan there and follow its progress." Runs that exist can still be opened. | |
| UAT-02 | Switch New harness on and restart the API and the arq worker. Open a new chat in the test matter. Open the model picker and choose New harness. | The row shows the route it is pinned to, "→ provider/model", under its name, with the note "Answers a request that needs nothing read. Otherwise plans it, and runs the tasks you approve." Hovering over the "Experimental" group shows "Not a provider model. Send makes one model call that answers the request or proposes a plan. Tasks run only after you approve the plan." Once chosen, the picker button reads "Model:", "New harness", the `experimental` chip and "→ provider/model". The skill picker, "Keep skills on", the ✨ prompt enhancer and the 📎 button that attaches a knowledge base are not on the page, and typing "/" opens no skill list. The box's placeholder is "Ask New harness…" and the button says "Send"; hovering over it shows "Makes one model call. It answers a request that needs nothing read, or proposes a plan. No task runs until you approve a plan." These three wordings are the ones for a server that says the orchestrator may answer by itself (`answers_directly` in `GET /api/v1/chats/<chat id>/run-profiles`); record any other wording you see. The empty thread reads "No messages yet. Type a request and send it. New harness answers a request that needs nothing read, and otherwise proposes a plan for you to approve." Above the box a strip shows one line: a closed fold named "Limits and tools" with the cap beside it, as "total cap $… · planning up to $…" (on a route with zero rates, "no charge at this route’s rates"). What a run reads and what Send does are inside the fold (UAT-03). Under the fold is the document picker's closed line, "Documents · none selected (optional)". When the matter has a knowledge base attached, the strip also names it (UAT-22). Choose an ordinary model: the skill picker, "Keep skills on" and ✨ come back, and an ordinary message sends normally. Choose New harness again and reload the page: New harness is still this chat's model. | |
| UAT-03 | Open "Limits and tools". Open each of the two system prompts listed in it. | "What a request reads" reads "Your request, this chat's recent messages, the documents you select, if any, and in a matter the knowledge bases attached to it. No other files and no live sources." "What Send does" reads "Sending makes one model call within the displayed total cap. It receives your request, this chat's recent messages, and the names of the documents you selected and of the matter's knowledge bases. It either answers a request that needs nothing read, or proposes a plan. Nothing else runs until you approve the plan." Then rows for Route (the model and "inference tier N"), Total cap, Planning allowance, Per-task allowance, Maximum tasks, Attempt limit and Tool turns per task ("up to 5, then one answer"). "Reasoning effort" appears only when the operator set one. The Pseudonymization row is described in section H. "Tools the tasks may use" lists "Read a selected document", "Read back a working note" and "Save a working note", and "Search the matter's knowledge bases" only when the matter has a knowledge base. "System prompts" lists "Orchestrator prompt, version 2" and "Sub-agent prompt, version 2"; opening one fetches its text, which is the system message the run's calls are pinned to. "What this does" reads "Answers a request that needs nothing read. Otherwise plans it as one to four tasks, runs the tasks you approve, and combines their results into one answer." "Direct answers" reads "A request that needs nothing read may be answered at once, without a plan. That answer is not put to you for approval." The figures match the settings and the admin read. Read both prompts. Record any sentence that is wrong, missing or that you would not want a model to follow (ADR 0038, open question 1). | |
| UAT-04 | Turn off the test user's Autonomous setting and reload the chat. Open the model picker. Then, with New harness already this chat's model, type a request. | The row is disabled and gives its reason, "Turn on Autonomous in your settings to start a run." Under the box, Send is disabled and the text reads "Turn on Autonomous in your settings to start a run. Choose another model to send this message." Nothing is sent as a run, no message is written and no model call is made. Turn Autonomous back on afterwards. | |
| UAT-05 | Optional. Switch the 0.8.0 profile on as well and restart. Open the model picker in the demo matter and, in a chat with an ordinary model, the skill picker and the "/" autocomplete. | New harness is still the only entry that is not a provider model, and there is no profile control beside the picker. The skill `orchestration-chat-demo` is in neither the skill list nor the autocomplete. The 0.8.0 profile can still be started through its API route, which these cases do not exercise. | |

### B. A run on documents

Use a chat in the test matter with New harness chosen. Attach a readable test document to the
chat only, not to the matter, with the "+ Files" button in the attached-files panel, and wait
until it is processed.

| ID | Action | Expected result / evidence | Result |
|---|---|---|---|
| UAT-06 | Open the document line, "Documents · none selected (optional)". | The picker opens under the heading "Documents for this run", with "0 of 8 selected" and the help text "Pick up to 8 documents the run may read. They are numbered in the order you pick them; the plan and the answer refer to them by those numbers. With none selected, the run reads no document." The matter's files are listed and readable ones can be ticked. The file that cannot be read is listed, disabled, with its reason, for example "This type of file cannot be read in a run. Runs read PDF with text, plain text and Markdown."; it is not silently omitted. The chat-only attachment is listed with the note "Will be added to this matter when you send the request". No more than eight can be ticked ("Up to 8 documents can be selected."), and no other user's file appears. "Refresh list" reads the list again. Ticking two files changes the closed line to "Documents · 2 selected: " followed by their names. | |
| UAT-07 | Tick two readable documents, one of them the chat-only attachment. Type a request about both, for example "What do these two agreements say about payment terms and about termination, and where do they differ?", and select **Send**. | Your request appears as your message. Below it is a run message headed "New harness v2 → provider/model" with the `experimental` chip. The status line reads "Reading your request…", with "Nothing has been approved, and nothing else runs until you approve a plan.", and the run's one line reads "Reading your request…". A chat still titled "New chat" takes a title from the request. The chat-only file is now in the matter's file list, and the admin audit log shows a `project.file_attached` row with source `run_selection`; it is keyed to the matter, so it is not in the chat's receipts. Open "Receipts, digests and accounting": under "Orchestrator steps" there is one step, "Asked the model how to respond", and no task call. | |
| UAT-08 | Inspect the plan card when it appears. | The status reads "Waiting for your approval" with "Review the plan below. Nothing runs until you approve it." The plan's line reads "Plan proposed · N tasks · total cap $… · waiting for your approval" and is open. The card gives Total cap, Combining the answers, Planning allowance, Deadline, Attempt limit, At the same time and Model, and "May read:" with the same text as the strip. It lists at most the number of tasks the cap funds and never more than four. Each task shows its topic and question; "System prompt" with `new_harness/subagent.v2` and its version; "Tools it may call" (Read a selected document, Read back a working note, Save a working note); "Documents it may read", numbered as you ticked them, for example "[1] msa.txt", with " · added to this matter for this run" on the chat-only file; "Budget", with "up to 5 tool turns, then one answer"; and a fold, "Task boundaries and expected output". Under the tasks are the buttons "Approve plan" and "Reject plan", and the notes "Approves revision 1 exactly as shown. Tasks cannot start further tasks." and "Planning is already charged ($…) and stays in the receipts if you reject." No task has started. | |
| UAT-09 | Under the plan card, open "How this run was set up", then the fold "Show the system prompt", then "What the model wrote". | "System prompt: new_harness/orchestrator.v2 (version 2)" with the first characters of its digest; the fold shows the same text as in the strip. "Opening message" shows labelled sections: STEP ("Respond"), REQUEST (your words), CONVERSATION SO FAR ("None. This request opens the chat." or earlier messages, each line quoted with ">"), DOCUMENTS (the numbered names, never their contents), KNOWLEDGE BASES (only when the matter has some), TODAY'S DATE and LIMITS. "Tools offered" lists `propose_plan` with its description and a "Schema" fold. A line says "Rebuilt from this run's records. It matches the digest recorded when the call was sent." "What the model wrote" says "No text; the model asked for tools." and shows one `propose_plan` call with its arguments exactly as the model wrote them: the tasks and their five fields. No document text appears. Record any check line other than the one quoted. | |
| UAT-10 | Select **Approve plan**, which approves the revision exactly as shown. | The plan's line reads "Plan approved · revision 1 · N tasks" and closes, and the buttons go. The status reads "Plan approved. Waiting for the tasks to start", then "N tasks running", then "Combining the answers". At most two tasks run at once ("At the same time"). There is one line for each task, showing "waiting to start", then its latest step with its spend at the right, then "done" with what it did, for example "done · read 2 documents · 3 model calls". The run message updates without a manual refresh, and **Halt** stays in view. | |
| UAT-11 | Open a task's line while it runs and again when it is done. | The topic; the prompt it is pinned to with "spent $… of $…"; "How this run was set up", with "System prompt: new_harness/subagent.v2 (version 2)", an opening message with the sections TASK (Topic, Question, Boundaries, "The result must contain", "Stop when"), DOCUMENTS, TODAY'S DATE and LIMITS (turns that may use tools, calls in one turn at most 8, characters per read, and the answer length), and the tools offered by their names (`read_document`, `read_note`, `save_note`). Steps such as "Asked the model (turn 1)", "Read document 1 (msa.txt)" with its character range (a document longer than one read is shown as "(cut short)" and the task reads on from the cut) and "Saved a working note (note-….md)", each with the model's stated reason where it gave one. Nothing outside the selection is read. A refused call, if the model attempts one, shows as "A tool call was refused: …" with the reason, and the task carries on. The task's findings carry "Model-generated; unverified." Folds "Files (n)" and "Receipts" are present. | |
| UAT-12 | Wait for the answer, then open the answer's line. | The status reads "Answer delivered". The answer line reads "Answer delivered · N of M checked quotations matched the selected documents" (with ", K did not match" or ", K more were not checked" where they apply). The answer is drawn under the run with Markdown structure and no raw HTML. The message carries the tier badge, the provider and model, the token counts and the cost, as an ordinary answer does, and no skill chip. Under the answer a note repeats the counts and never calls the answer verified. The answer line opens on "How this run was set up" for the combining call: STEP "Combine", REQUEST, DOCUMENTS, TODAY'S DATE, RESULTS (each task's result between marked lines, "--- Task 1 of 2: … (completed) ---") and LIMITS, and "No tools were offered on this call." Check the answer against the documents yourself and record any model error as a defect. | |
| UAT-13 | Read the quotations. | Quotations are written as "quoted words" (Source: [N]), where N is the document's number in the selection. Open the ledger from the badge beside the citation chips: each matched quotation is listed with its text and its character offsets in document N. Check at least three quotations against the documents yourself. Only a quotation with that marker is checked; Markdown emphasis around the quotation marks, such as `**"words"** (Source: [1])`, is accepted. If the answer also holds quoted passages with no marker, or a marker that names no source of the run, the line says how many and that they were not checked, for example "1 quoted passage has no source marker and was not checked." Record whether the model writes quotations without the marker. Record also any quotation with emphasis around it that is missing from the citation list: it should be listed and checked (ADR 0038, ruling 2). | |
| UAT-14 | Ask for something the documents do not contain, or for a paraphrase written inside quotation marks, until a quotation fails to match. | The quotation shows as unverified, the gate shows flagged, and the answer is still delivered. No judge model is called: the checks use only the exact and tolerant stages. If every quotation matches after reasonable attempts, record "not exercised by a person"; a controlled-provider test covers it. | |
| UAT-15 | Reload the browser. Without touching the document picker, send a follow-up that depends on the earlier answer, for example "Which of those differences matters most for termination?" Approve the plan if one appears. | The picker's closed line reads "Documents · 2 selected: …" with the two documents the last run read. If a plan appears, its task text reflects the earlier answer. Under it, "How this run was set up" shows CONVERSATION SO FAR with your earlier request and the earlier answer, each line quoted with ">", and a source marker in the earlier answer now names its file, for example "(Source: msa.txt)", not "[1]". Record whether the model planned or answered directly. | |
| UAT-16 | Choose an ordinary model in the picker and send "Summarize your last answer in one sentence." | The reply draws on the run's answer, so the thread's history includes it. There is no error about an empty message. | |
| UAT-17 | Set the matter's minimum inference tier stronger than the route provides (a lower number is stronger). Open the chat and the model picker. | New harness is disabled and the row gives the route reason, for example "Inference route, protection or pricing is unavailable". No planning call is made. Restore the tier afterwards. | |
| UAT-18 | In Settings, Account, request a data export. Open the ZIP when it is ready. | `orchestration_runs.json` contains each run: its profile, status and stop reason; `planning`, which is the intake, including the thread excerpt the planning call was shown, the documents, the knowledge bases and the terms the run was held to; the plan revisions and your approval; each session's step receipts; and the contents of the run's working files. `messages.json` contains the run message with kind `run` and its `autonomous_session_id`, and `work_product_attribution.json` contains its chain-of-custody row. Raw tool results, passage text and provider responses are not in the export. | |

If the citation checks themselves fail with an error at delivery, the answer is still
delivered, labelled unverified, and the delivery audit row records
`verification: unverified` and `checks: failed`. A tester cannot provoke this fault. A
controlled-provider test covers it.

### C. A request that needs nothing read

Use the chat of section B after its run, with both documents still ticked. Whether the model
answers by itself is its choice (see above); the cases test what the page does when it does.

| ID | Action | Expected result / evidence | Result |
|---|---|---|---|
| UAT-19 | Send "Shorten that to three bullet points." | A new run message whose column is one line, "Answered directly · no plan · nothing read", with its spend at the right. There is no plan card and no approve button at any time. The status reads "Answer delivered". The answer is drawn under the run. The note under it reads "Answered by the orchestrator alone. It read no document and searched nothing for this answer. Model-generated; not checked." If the shortened answer still carries (Source: [N]) markers, the quotations that carry them are checked against the selected documents and the note reports the counts, followed by "The orchestrator did not read these documents in this run."; record whether the model kept the markers. Open the line: "The orchestrator answered this request by itself. No task ran, nothing was read or searched, and nothing was put to you for approval."; "How this run was set up", with STEP "Respond" and `propose_plan` among the tools offered; and "Receipts", with one step, "Asked the model how to respond". If the model proposes a plan instead, record that. It is the model's choice and not a failure of this step. Record whether the picker's note ("Answers a request that needs nothing read. Otherwise plans it, and runs the tasks you approve.") and the Send button's hover text ("Makes one model call. It answers a request that needs nothing read, or proposes a plan. No task runs until you approve a plan.") prepared you for an answer with no plan. | |
| UAT-20 | Send "Thanks." | The same shape as UAT-19: one line, no approve button, the same note. Repeat UAT-19 and UAT-20 once each and record how often the model answered directly. | |
| UAT-21 | With the two documents still ticked, send a question about one of them, for example "What does the first document say about notice periods?" | A plan, not a direct answer: "Reading your request…", then a plan card that you approve as in UAT-10. If the model answers this request directly, record the request and its answer. That is the case the system prompt forbids and no code prevents (ADR 0038 D1): such an answer has read nothing. | |

### D. A matter with a knowledge base

Use a chat in a matter that has a knowledge base attached (see Test data). A search finds a
passage only when it holds every word of the query, so choose a request that uses words the
knowledge base's documents contain.

| ID | Action | Expected result / evidence | Result |
|---|---|---|---|
| UAT-22 | Open a chat in the matter, choose New harness and open "Limits and tools". | The strip has the line "Tasks may search this matter's knowledge bases: <names>." When more than 16 are attached it adds "N more attached to this matter are not searched: a run lists at most 16." "Tools the tasks may use" includes "Search the matter's knowledge bases". | |
| UAT-23 | Untick every document. Send a request that the knowledge base answers and the two documents do not, for example "What does our leave policy say about carrying over unused leave?" Approve the plan. | The plan card has the line "Tasks may search: <names>." Each task lists "Search the matter's knowledge bases" among "Tools it may call" and "none listed" under "Documents it may read". A task's steps include "Searched the knowledge bases · 2 passages from leave-policy.txt", or "Searched the knowledge bases · nothing found" when no passage held every word of its query. A task may search several times. Under the task's reply in "What the model wrote", the `search_knowledge_base` call shows its query and stated reason; passages appear nowhere in the trace. Record each query and what it found. | |
| UAT-24 | Read the answer and the list under it. | Quotations carry source numbers, for example (Source: [1]). The answer line reads "Answer delivered · N of M checked quotations matched the knowledge-base files they name". Under the answer a list headed "Files found by search" has a row for each file found, for example "[1] leave-policy.txt · found by task 1". Check a quotation against the file in the knowledge base. With no document ticked the first file task 1 finds is [1] and the first file task 2 finds is [26]. With the two documents also ticked the numbers start above them: [3] for task 1 and [28] for task 2. A task cites at most 25 different files. | |
| UAT-25 | Optional, needs the API. Add to the knowledge base a document whose file is also attached to a second matter and not to this one (`POST /api/v1/projects/<second matter id>/files` with `{"file_id": "<id>"}`). Search for words only that document holds. | The step reads "Searched the knowledge bases · nothing found · 1 matching passage left out", and the answer does not quote the document: a passage is withheld when its file belongs to another matter and not to this one. | |

### E. A chat in no matter

| ID | Action | Expected result / evidence | Result |
|---|---|---|---|
| UAT-26 | Open a chat that is in no matter: start one from the chats page, not from a matter. Open the model picker, choose New harness, and look at the strip. | New harness is available; the row is not disabled. The strip shows the same facts as in a matter, with no line naming knowledge bases, and "Search the matter's knowledge bases" is not among the tools. The document picker lists only this chat's own attachments. With none it reads "No documents yet. Attach a file to this chat, then refresh the list.", and no file carries the note "Will be added to this matter". | |
| UAT-27 | Send "Thanks.", then a short general question, for example "What is a force majeure clause?" | Each is answered directly: one line, "Answered directly · no plan · nothing read", no plan card and no approve button, and the note "Answered by the orchestrator alone. It read no document and searched nothing for this answer. Model-generated; not checked." Record any request the model planned instead. For the general question, record whether the answer says what it rests on, and whether it names a case or a statute without saying that it is from memory. | |
| UAT-28 | Upload a short test document to this chat, tick it, and send a request about it. Approve the plan. | A plan, approval and answer as in section B. The plan card has no "Tasks may search" line, and the tasks' tools do not include the knowledge-base search. The document is not added to any matter. | |
| UAT-29 | Upload a file to this chat and attach the same file to a matter by the API (`POST /api/v1/projects/<matter id>/files` with `{"file_id": "<id>"}`; the id is in the upload's response). Press "Refresh list". Then, in a chat in the test matter, do the same with a file that only a second matter holds. | In the chat in no matter the file can be selected, with the note "From the matter “<name>”. A run that reads it follows its rules." When the matter sets an inference tier floor or is privileged the note ends with them, for example "inference tier 2 or stronger; privileged, so nothing is pseudonymized." Send a request with it selected: the run's receipts show that floor, and for a privileged matter that no call was pseudonymized. If the route is weaker than the floor the request is refused with "A selected document belongs to a matter whose inference tier floor or privilege setting this run's route does not meet." In the test matter's chat the other matter's file is disabled, with "This file belongs to another matter. Add it to this matter yourself if this run should read it." (ADR 0038, ruling 4). | |

### F. Rejecting, halting, reloading and switching off

| ID | Action | Expected result / evidence | Result |
|---|---|---|---|
| UAT-30 | Start a run with a different request, for example notice obligations and surviving duties. When the plan card appears, select **Reject plan**. | The status reads "You rejected the plan" with "No task work or combined answer will run. The planning charge stays in the receipts. You can start a new run from the composer." No task starts and no combined answer is produced. The run message stays without an answer. The planning call remains in the receipts. You can start another run. An ordinary turn afterwards works. | |
| UAT-31 | Start another run, approve it and select **Halt** while a task is working. | No new step starts after the halt, though a call already sent may finish at its provider. The status reads "Halted" with "You halted the run. No combined answer was produced. Task answers and files finished before the halt remain below." Delivered work stays readable and no combined answer is produced. You can start another run. | |
| UAT-32 | Start and approve a run. Reload the browser while tasks are running. | The thread comes back from stored state with the same plan, approval and progress, and New harness is still the chat's model. The receipts show no second planning call and no repeated admission. The run keeps updating. | |
| UAT-33 | While a run is active (reading the request, waiting for approval or running), open a different chat in the same matter. | A notice above the box reads "A run is active in <chat title>" with its state ("Reading the request", "Waiting for your approval" or "Tasks are running") and a button "Open that chat". New harness stays chosen. Send is disabled, and once you type a request the text under the box reads "Another run of yours is still active. One run can be active at a time." Ordinary models send normally. | |
| UAT-34 | Turn the New harness switch off on the API and the arq worker and restart both, with at least one run retained. Open the chat in which New harness was the model. | New harness is not available: the row is disabled with "The operator has not enabled New harness.", and Send waits with that reason and "Choose another model to send this message." Nothing can be proposed or approved. The retained runs stay readable, with their plan, results, receipts and files, and can still be halted. Ordinary chat is unaffected, and the export still includes the runs. | |

### G. Closing an uncertain run

Do this on a disposable fixture only. Closing converts the unresolved reservation into a
charge and cannot be undone. To make a run uncertain, either set the attempt timeout to 1
second against a model that takes longer and restart the API and the worker, or pin a model
that rejects requests carrying tool schemas; the planning call carries one, so that run is
uncertain at its first call. Restore the settings afterwards.

| ID | Action | Expected result / evidence | Result |
|---|---|---|---|
| UAT-35 | Start a run so that a provider call ends uncertain. | The status reads "Uncertain: a provider call has no confirmed outcome", with "A provider call was sent but its outcome was never confirmed. The run stopped there and will not retry it, because repeating it could be charged twice. The amount reserved for that call stays held, and while it does you cannot start another run. Closing the run charges that unresolved reservation, retries nothing, and frees you to start another run. Work that finished earlier stays readable." The step reads "No confirmed outcome. It will not be retried automatically." Nothing is retried. If the run is uncertain at its first call, it has no plan, and the plan's line reads "Reading your request… · a provider call has no confirmed outcome" and opens (test id `lq-ai-run-noplan`). "How this run was set up" shows the call that was sent, with `propose_plan` among the tools offered and the line "No digest of what was sent was recorded for this call."; "What the model wrote" says "No reply was recorded for this call."; "Receipts" shows the unresolved step. | |
| UAT-36 | Select **Halt** on the uncertain run. Open another chat in the matter. | The run stays uncertain, because a halt does not resolve the call. The other chat's notice reads "A run is active in <chat title>" with "Uncertain: a provider call has no confirmed outcome", and offers "Open that chat" and **Close run** with the note "Closing charges the unresolved reservation, retries nothing, and frees you to start another run." | |
| UAT-37 | Select **Close run**. | The status reads "Closed" with "You closed the run. The unresolved reservation was charged and nothing was retried. You can start another run. Work that finished earlier remains below." Each unresolved call reads "Closed without an outcome. The reserved amount was charged." and has no result. Work that was already delivered stays readable. The run message has no answer. The receipts show an `orchestration.run_closed` audit row. For a run closed before it had a plan, the plan's line reads "No plan was produced · You closed the run." and still opens to the call that was out. | |
| UAT-38 | Open another chat in the matter. | The notice no longer names a blocking run, and a new request can be sent. | |
| UAT-39 | The interface offers **Close run** only on an uncertain run, so use the API: call `POST /api/v1/autonomous/orchestration/chat-runs/<root id>/close` on the closed run, then on a completed run. | Closing the closed run returns it unchanged. Closing a completed or running run is refused with "Only an uncertain run can be closed". | |

### H. A route that pseudonymizes

Pseudonymization follows the gateway's setting, so this section starts with an operator step.

| ID | Action | Expected result / evidence | Result |
|---|---|---|---|
| UAT-40 | Open "Limits and tools" and read the Pseudonymization row. Then do the operator step: in the gateway configuration set `anonymization.enabled: true` and put the route's inference tier (the strip's Route row shows it) in `anonymization.apply_at_tiers` (the example file has `[3, 4, 5]`; a local model at tier 1 needs `1` added), restart the gateway, and reload the chat. Read the row again. | Before the step the row reads "Text is sent to the model as written: the operator's setting applies no pseudonymization at this route's tier.", and runs are not refused for it. After the step the row reads "On the way to the model, the gateway replaces what it recognises as a personal name or an identifier in your request, this chat’s messages and the plan with a placeholder, and puts it back in what the model writes. It cannot put one back in a plan, so a plan that carries a placeholder is refused and nothing runs. It does not recognise everything, and a miss is not reported. Organisation names are not replaced. The text of a document that a task reads, and of a passage that a search returns, is sent as written, so that quotations can be checked. A task’s notes and stated reasons may show a placeholder." Record any difference in its wording. | |
| UAT-41 | Send a request that names a fictional person who appears in a selected document, for example "What does the agreement say about payments to Maria Okafor?" Repeat it twice. If a run ends with no plan, open the plan's line (test id `lq-ai-run-noplan`), wait for "How this run was set up" to load, and read it, "What the model wrote" and "Receipts". | Record, for each attempt, which of these happens. **(a) The run fails after its first call because the plan carried a placeholder.** The status reads "The run failed" with the detail "The plan carried a placeholder that stands for a name or an identifier. This route is pseudonymized, and a placeholder in a plan cannot be turned back into the real value, so the plan was refused. Nothing ran. Try the request again without the name or identifier." The plan's line reads "No plan was produced · The plan carried a placeholder that stands for a name or an identifier." and opens. "How this run was set up" shows the orchestrator's system prompt, an opening message whose section REQUEST holds your words with the name as you wrote it (the application sent that text and the gateway replaced the name afterwards), `propose_plan` among the tools offered, and the line "Rebuilt from this run's records. It matches the digest recorded when the call was sent." "What the model wrote" shows "No text; the model asked for tools." if the model wrote no text, then one `propose_plan` call whose arguments hold a token shaped like `PERSON_0001` where the name would be. That token is why the plan was refused. "Receipts" shows one step, "Asked the model how to respond", and no task step. **(b) The model produces a plan.** Read the plan card, every task line, each task's "Files", the stated reasons, "What the model wrote" (the plan's arguments and any search query) and the answer, and record every place where a token shaped like `PERSON_0001` is visible. A plan that carries one is refused, so none is expected in the plan card. A placeholder may appear in a task's notes, stated reasons and search queries. The answer shows names as written, not placeholders. **(c) The run fails because the model wrote its plan out as text.** The name does not cause this; record it if it happens, with the text. The status reads "The run failed" with the detail "The model wrote its plan out as text instead of handing it over, so there is no plan to approve. Nothing ran. Send the request again." The plan's line reads "No plan was produced · The model wrote its plan out as text instead of handing it over, so there is no plan to approve." and opens. "How this run was set up" shows `propose_plan` among the tools offered, so the model had the tool. "What the model wrote" shows the text of its reply, which is a plan written out (for example a JSON object with a `tasks` member, or the call spelled out with the name `propose_plan`), and no tool call. "Receipts" shows one step, "Asked the model how to respond". This is the limit in ADR 0038 D7 and open question 6; record the outcome even if it matches. | |
| UAT-42 | After a run from UAT-41 that used the name, send "Shorten that." | If the model answers directly, as in UAT-19, the answer shows the name as written and no placeholder, because the orchestrator's own answer is reply text and is restored. Record any placeholder you see. | |

### I. The run is as visible as an ordinary turn

Use a completed run from section B.

| ID | Action | Expected result / evidence | Result |
|---|---|---|---|
| UAT-43 | Compare the run message with an ordinary assistant reply on the same route. | The same fields are present on the run message: tier badge, provider and model, token counts and cost. The cost is the run's accounted spend, a conservative estimate rather than an invoice. There is no skill chip, because New harness applies no installed skill. The run is headed "New harness v2 → provider/model" with the `experimental` chip; the heading is a label and opens nothing. | |
| UAT-44 | Open the fold "Receipts, digests and accounting" on the run message. Open the chat's receipts drawer, or export the receipts as JSONL. | The fold shows the run's id, the profile `new_harness_v1`, the model, "Spent $… · reserved $…", the gateway configuration digest, the plan digest, and "Orchestrator prompt" with `new_harness/orchestrator.v2` and its digest; under "Orchestrator steps" are the orchestrator's own steps. The receipts feed shows the run as it shows an ordinary turn, without skill events because no skill was applied: message events, one inference event per model call with provider, model, tier, tokens, latency and anonymization, and audit events for the run's session and tasks (planning started, approval, effects, delivery, and any tool refusal or close). | |
| UAT-45 | Operator check. Run these read-only queries against the database, using the run message's id from the receipts export or the messages response. `SELECT purpose, chat_id, message_id, routed_model, tokens_in, tokens_out FROM inference_routing_log WHERE message_id = '<run message id>' ORDER BY timestamp;` and `SELECT message_id, skill_ids, provider, model FROM work_product_attribution WHERE message_id = '<run message id>';` | Every model call of the run is a row with `purpose` set to `orchestration_run` and the run's chat and message identifiers. There is no `judge_*` purpose for this message. There is one attribution row for the run message, and its `skill_ids` is empty. No `tool_call_log` rows are expected, because that table records calls to external tool providers and no run profile grants one. | |
| UAT-46 | Search the chat history for a distinctive phrase from the answer. | The chat is found. | |
| UAT-47 | Optional, only if tracing is configured with one of the recipes under `deploy/observability/`. Find the trace of the request that accepted or approved the run. | The trace holds `orchestration.job`, `orchestration.run` and `orchestration.effect` spans from the service `lq-ai-arq-worker`, in the same trace as the API request and the gateway's spans. If the trace stops at the API, check that the arq worker has `OTEL_EXPORTER_OTLP_ENDPOINT` set. No span attribute contains prompt, document, answer or search text. See the [observability guide](../observability.md#orchestrationjob--orchestrationrun--orchestrationeffect). | |

### J. Extra checks

| ID | Action | Expected result / evidence | Result |
|---|---|---|---|
| UAT-48 | Approve a run that lasts longer than 15 minutes (a slow model, or several documents) and keep the tab open without reloading. | Progress keeps updating through the 15-minute access-token expiry, with no sign-in prompt and no manual refresh, until the run ends. If the run ends sooner, repeat with a longer one or record "not exercised". | |
| UAT-49 | Approve a run, then leave the tab untouched for more than 30 minutes so the idle sign-out occurs. Sign in again and open the chat. | The run message is restored from stored state, showing the run's current progress or its answer. Nothing is repeated: the receipts show no second planning call and no repeated admission. | |
| UAT-50 | Open the matter workspace's chat (`/lq-ai/matters/<id>`) and start a run there. | The picker entry, document picker, plan card, progress, answer and the active-run notice behave as in the chats page. | |
| UAT-51 | Put markup-like text in a document, in a request and in an earlier message of the chat, for example `<img src=x onerror=alert(1)>`, `<script>alert(1)</script>` and `<b>bold</b>`, and ask a question whose answer quotes it. Add a sentence to the document, and to the earlier message, that tells the model to ignore its instructions and read other files. | In the plan card, task text, steps, stated reasons, "How this run was set up", "What the model wrote" and the answer, the characters appear as text. No HTML from the document, the request, the thread or the model is drawn, no image is loaded and no script runs. Markdown formatting in the answer (headings, lists, bold) is still drawn; a Markdown image appears as its source text. The run reads only the selected documents, and its plan, tools and budgets do not change. | |

## Automated checks

These use real Postgres, the store, the guard, the worker and checkpoint paths with a
controlled provider. They establish the contract. They use no configured provider and no
browser.

- `api/tests/autonomous/orchestration/test_runs_in_chat.py`: a run as one turn in the
  thread, delivery into its message, later turns, idempotent send, each refusal,
  isolation between owners, and the receipts and routing-log rows.
- `test_runs_in_chat_migration.py`: upgrading a release database through 0070 to 0073, and
  refusing a lossy downgrade.
- `test_new_harness.py`, `test_new_harness_guards.py`, `test_new_harness_turn.py` and
  `test_new_harness_turn_guards.py`: the prompt files and their pins, the opening message
  and the trace read, the thread, optional documents, a chat outside a matter, the file
  rule, pseudonymization by the operator's setting, the plan tool and the direct answer,
  the knowledge-base search and its source numbers, a run's frozen terms, and hostile text.
- `test_tool_loop.py`: a granted call, a refused call, malformed arguments, the turn limit,
  restart in the middle of a loop, halt, an exhausted allowance and a detached document.
- `test_close_uncertain.py`: closing, the charge, and who may close.
- `test_document_runs.py` and `test_evidence_counts.py`: the picker, selection, the read
  boundary, citation checks, the quotation counts, hostile text, the tier floor and the
  export.
- `test_registry_contract.py`, `test_contract_versions.py` and `test_run_skills_listing.py`:
  adding a profile and a tool the product does not ship, keeping 0.8.0 plan hashes, and
  keeping a run's orchestrator skill out of the skill list.
- `test_run_tracing.py`: the run spans and the trace context carried through queued jobs.
- `gateway/tests/test_inference_b4.py`, `test_ollama_tool_calls.py` and
  `test_reasoning_effort_adapters.py`: the gateway's purpose labels, the Ollama changes and
  the reasoning-effort field.

Run against a disposable PostgreSQL database:

```bash
cd api
uv sync --frozen --extra dev
DATABASE_URL=postgresql+asyncpg://test:test@127.0.0.1:55435/lqai_test \
  .venv/bin/python -m pytest tests/autonomous/orchestration \
  tests/test_openapi.py tests/test_openapi_export.py tests/test_endpoints.py -q
```

Run `ruff check`, `ruff format --check`, API mypy, the gateway tests, frontend
`check:lq-ai` and the Vitest tests under `web/src/lib/lq-ai/run/`. Controlled-provider tests
do not establish live inference or human acceptance.

## Evidence and sign-off

The recorded walkthrough in the [first build's folder](../uat/adr38-runs-in-chat/README.md)
was made on 2026-10-06, before the design changed, and a walkthrough of this build has not
been recorded. Agents have run New harness on a scripted provider and on local models, which
is not human acceptance. Record the branch commit, the provider and model, the composer's
figures, run and message identifiers, the model-dependent outcomes (the cases listed at the
head of the acceptance script) and any failed attempts. Keep provider secrets out of the record.

ADR 0038 requires a run on a configured provider before New harness is described as working
live. Record the provider and model used for UAT-06 to UAT-29.

- Human UAT, picker and composer (UAT-01 to UAT-05): **pending**. Tester: ______ Date: ______
- Human UAT, runs on documents (UAT-06 to UAT-18): **pending**. Tester: ______ Date: ______
- Requests that need nothing read (UAT-19 to UAT-21), knowledge bases (UAT-22 to UAT-25) and
  a chat in no matter (UAT-26 to UAT-29): **pending**.
- Reject, halt, reload and switches (UAT-30 to UAT-34) and closing an uncertain run
  (UAT-35 to UAT-39): **pending**.
- A route that pseudonymizes (UAT-40 to UAT-42), records (UAT-43 to UAT-47) and extra checks
  (UAT-48 to UAT-51): **pending**.
- Configured-provider run for New harness: **pending**. Provider/model: ______
- Branch commit: ______ Accepted cases: ______ Defects / deferred cases: ______
- Maintainer review: **pending**. Security review: **pending**. ADR 0038 ratification:
  **pending**. ADR 0035 D1 amendment ratification: **pending**.
- Production enablement: **not approved by this UAT**.
