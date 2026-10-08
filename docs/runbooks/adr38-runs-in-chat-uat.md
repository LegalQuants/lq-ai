# ADR 0038 governed runs in chat: UAT

This test checks that a governed run works as a turn in the main chat: the owner
chooses a profile in the composer, approves an exact plan, follows progress, receives
the answer in the same thread, and can halt a run or close an uncertain one. It
covers two profiles: the fictional Contract QA profile, and a profile that reads
documents the owner selects.

**A passing run shows that the flow, the controls and the records work. It does not
show that an answer is legally sound.** The fictional profile's answers are labelled
unverified. On the real-document profile, "checked against the selected documents"
describes quotations only: it says a quotation was found in the document it cites, not
that the answer is correct or complete. Before the real-document profile is described as
working live, a person must accept it on a configured provider; see
[Sign-off](#evidence-and-sign-off).

**Status.** [ADR 0038](../adr/0038-skill-backed-orchestration-profile.md) is Proposed,
not ratified. The implementation is on an unmerged branch, has had no maintainer or
security review, and does not merge before ratification. Both profile switches default
to off. Design and what was and was not verified:
[plan](../plans/issue-662-c1-governed-runs-in-chat.md#implementation-status). The
earlier stand-alone page, as released in 0.8.0, is covered by the
[ADR 0035 runbook](adr35-chat-uat.md).

## Setup

Use a dedicated, disposable deployment, a user with Autonomous mode enabled, and an
admin account. Do not test on a deployment whose data you cannot lose.

**Migrations.** Apply 0070 and 0071 (after 0069) by rebuilding `api`, `arq-worker` and
`ingest-worker` together, so no sibling runs on an old revision. Rebuild `web` too: it
serves a pre-built bundle, so a UI change does not appear until it is rebuilt. Never run
host-side `alembic upgrade` against a running development database; it desyncs the stack.
Check the migrations on a throwaway `pgvector/pgvector:pg16` container instead. Never use
`docker compose down -v`. Both migrations refuse to downgrade while the rows they
introduced are retained (chat-hosted runs, registry-profile runs, closed runs and
effects), so keep a deployment that has used this feature at 0071 until a reviewed export
and removal plan exists. A 0.8.0 run that is in flight when the branch is deployed stops on
the policy check and stays readable; complete or halt runs first.

**Skills.** Install `contract-qa` v1.0.0, `orchestration-chat-demo` v1.0.0 (with its
fictional agreement) and `contract-questions-orchestrator` v1.0.0. The last is new on the
branch and is the real-document profile's planner and combiner. Run profiles use built-in
skills only.

**Settings.** Set these on both the API and the arq worker. The two Compose files pass
them to both services. The budget values are the `.env.example` defaults, not
recommendations; size them as described under [Sizing the budget](#sizing-the-budget).

```dotenv
LQ_AI_ORCHESTRATION_DEPLOYMENT_CHILDREN=2

# Fictional profile
LQ_AI_ORCHESTRATION_CHAT_ENABLED=true
LQ_AI_ORCHESTRATION_CHAT_PROJECT_ID=<owned-demo-project-uuid>
LQ_AI_ORCHESTRATION_CHAT_PROVIDER=<direct-gateway-provider-name>
LQ_AI_ORCHESTRATION_CHAT_MODEL=<native-model-id>
LQ_AI_ORCHESTRATION_CHAT_BUDGET_USD=2.0000
LQ_AI_ORCHESTRATION_CHAT_MINIMUM_TIER=1
LQ_AI_ORCHESTRATION_CHAT_TIMEOUT_SECONDS=120

# Real-document profile: its own switch and route; nothing is inherited from the profile above
LQ_AI_ORCHESTRATION_DOCUMENTS_ENABLED=true
LQ_AI_ORCHESTRATION_DOCUMENTS_PROVIDER=<direct-gateway-provider-name>
LQ_AI_ORCHESTRATION_DOCUMENTS_MODEL=<native-model-id>
LQ_AI_ORCHESTRATION_DOCUMENTS_BUDGET_USD=5.0000
LQ_AI_ORCHESTRATION_DOCUMENTS_MINIMUM_TIER=1
LQ_AI_ORCHESTRATION_DOCUMENTS_TIMEOUT_SECONDS=300
```

`LQ_AI_ORCHESTRATION_DEPLOYMENT_CHILDREN` is the shared child capacity (1 to 32). It is
required before any profile can be enabled; drain runs before changing it. Enabling the
fictional profile never enables the real-document one, and the reverse. The fictional
profile runs only in the dedicated demo project named above. The real-document profile
has no project setting: it runs in any active project the owner owns, subject to the
project's inference-tier floor and privilege flag. A switched-on profile with incomplete
settings is reported to the owner as not configured. If a switch is on but no profile is
fully configured, or the shared child capacity is unset, the arq worker refuses to start.
As an admin, read `GET /api/v1/admin/orchestration/profiles` and confirm that both profiles
appear with the state you expect and no `problem`. To test one profile alone, leave the
other switch off.

**Route.** Each profile pins one direct gateway provider and model. Configure exact
gateway prices for `provider/model`; local inference needs explicit zero prices. Enable
gateway anonymization at the selected tier for a non-privileged project. Aliases, missing
prices, a tier weaker than the project allows and route drift are refused.
**A model that reasons before it answers spends its output limit on that reasoning.** The limit (8,192 tokens per call on both profiles) covers reasoning and answer together. In the recorded local-model pass one combined answer was cut off after the model had used the whole limit reasoning, and the run ended as "The combined answer could not be produced" with the task answers kept. Size the limit for the model, or turn its reasoning down at the provider.
**The pinned model must support native tool calls (function calling).** Approved children
are offered function schemas for the tools their plan grants. A provider that rejects a
request carrying tool schemas leaves the run uncertain, which the owner can then close
(UAT-23 to UAT-27). The planning call carries no schemas, so the failure shows when the
first task starts. Check the model's tool support before you start.

**Time limits.** The attempt timeout (1 to 900 seconds) is shown in the composer before
planning and is pinned in the proposal. A provider timeout leaves the call uncertain and
is never retried. Single calls on local models have exceeded their timeout in earlier
testing, so set it to suit the model. The run deadline includes the approval wait: one hour
for the fictional profile, two hours for the real-document profile.

**Test data.** Keep every fictional-profile goal fictional. For the real-document profile,
use a test matter and documents you are allowed to send to the configured provider. The
text a child reads is sent to that provider as stored: it travels as a tool result, and the
gateway pseudonymizes only the request, the task and the skill text, as it leaves retrieved
text alone in ordinary chat. Anonymization at the route does not cover document text. The
planning call is given the selected file names, not the documents' text. Use
non-confidential test documents until the profile has been accepted and reviewed.

## Sizing the budget

The composer shows the result of this rule before any planning is paid for. The rule is in
`prepare_intake` in `api/app/autonomous/orchestration/intake.py`.

- **One unit** is one model call at the profile's input and output limits, priced at the
  route's explicit rates. The limits are 98,304 input bytes and 8,192 output tokens for the
  fictional profile, and 262,144 input bytes and 8,192 output tokens for the real-document
  profile. The accounting counts each input byte as a token and adds a small fixed
  overhead. A unit is a conservative accounted estimate, not a provider invoice, and the
  composer's planning allowance is one unit.
- **The root gets two units**: one for planning and one for the combined answer.
- **Each task gets one unit per model call it may make**: the profile's tool turns plus one
  final answer turn, plus the quote of any priced tool. The fictional profile allows two
  tool turns, so three units a task. The real-document profile allows five, so six units a
  task. The three tools shipped with the profiles are not priced.
- **The total cap decides how many tasks can be funded**: the cap, less the root's two
  units, divided by one task's allowance, rounded down, and never more than four. As an
  illustration in units, not a cost, a cap of 11 units funds three tasks on the fictional
  profile and one on the real-document profile. A route with explicit zero rates costs
  nothing, so it funds the maximum of four.
- If the cap cannot fund planning, one task and the combined answer, the profile is
  unavailable and the composer shows "Run budget cannot fund planning, one task and
  synthesis".
- The planner is told the funded number, and a proposal with more tasks fails as an
  unfunded plan.
- Release 0.8.0 gave a task one unit, so on a priced route this branch funds fewer tasks at
  the same `LQ_AI_ORCHESTRATION_CHAT_BUDGET_USD`.

Record the composer's figures (model, total cap, planning allowance, per-task allowance and
the number of tasks) in the [acceptance record](../uat/adr38-runs-in-chat/README.md).

## Acceptance script

Run the cases in order. The Result column is for the tester; a case is not accepted until
a person has filled it in. Quoted interface wording is what the web components on the
branch show at the time of writing. If the wording differs, record the difference; it does
not fail the case on its own.

### A. Fictional profile in the main chat

| ID | Action | Expected result / evidence | Result |
|---|---|---|---|
| UAT-01 | With both switches off, open a chat inside a project and open the **Run** control (the profile menu) beside the model picker. Open the stand-alone page at `/lq-ai/autonomous/orchestration/chat`. | Both profiles are listed as unavailable with the reason "The operator has not enabled this profile." No model call is made, and ordinary chat sends normally. The stand-alone page has no intake form; runs that exist can still be opened. | |
| UAT-02 | Switch the fictional profile on. Open a chat inside the demo project and choose the profile from the **Run** control. | The profile is available. The composer shows the pinned model, the total cap, the planning allowance, the attempt limit and the number of tasks the cap can fund, names what the run may read (the fictional vendor agreement only), and says the planning call sees the request only, not earlier messages. The figures match the settings and the admin read. | |
| UAT-03 | Look at the composer in each case: a chat outside any project; the user's Autonomous setting off; a chat in a project other than the demo project. | The profile is unavailable and the composer gives the reason: "Runs start from a chat inside a matter. This chat has no matter."; "Turn on Autonomous in your settings to start a run."; "The operator has limited this profile to a dedicated demo matter." Nothing can be sent as a run, no message is written and no model call is made. | |
| UAT-04 | In the demo project, choose the profile, enter the default goal about payments, implementation and support, and renewal and termination, and select **Propose plan**. | Your request appears as your message. Below it a run message shows that a plan is being proposed. A chat still titled "New chat" takes a title from the request. The receipts show one planning call and no child call. | |
| UAT-05 | Inspect the plan card when it appears. | It lists the tasks, at most the number the cap funds and never more than four. Each task shows its question and boundaries, the skill and version (Contract QA v1.0.0), the tools it may call (read a selected document, read back a working note, save a working note), the document it may read (the fictional agreement) and its budget. It says "Review the plan below. Nothing runs until you approve it." and offers **Approve plan** and **Reject plan**. No child has started. | |
| UAT-06 | Select **Approve plan**, which approves the revision exactly as shown. Open a child while it runs. | Progress is described in plain words with the current step, and the run message updates without a manual refresh. A child opens to its steps (model turns, a document read with the file name and character range, notes it saved), its files and its receipts. The child reads the agreement through the document read, not from its prompt. **Halt** stays in view. A refused call, if the model attempts one, shows as a refused step, with the model's stated reason when it gave one, and the child carries on. | |
| UAT-07 | Wait for the answer. | The combined answer arrives in the same run message. It carries the skill chips, the tier badge, the provider and model, the token counts and the cost, as an ordinary answer does, and is labelled unverified. Check it against the fictional agreement using the facts listed after the table in the [ADR 0035 runbook](adr35-chat-uat.md#acceptance-script); record any model error as a defect. | |
| UAT-08 | In the same chat, select **Leave run mode** and send an ordinary turn that refers to the answer, for example "Summarize your last answer in one sentence." | The reply draws on the run's answer, so the thread's history includes it. There is no error about an empty message. | |
| UAT-09 | Start a run with a different goal, for example notice obligations and surviving duties. When the plan card appears, select **Reject plan**. | The plan is shown as rejected and the progress says "You rejected the plan". No child starts and no combined answer is produced. The run message says the work is not proceeding and stays without an answer. The planning call remains in the receipts. You can start another run. An ordinary turn afterwards works. | |
| UAT-10 | Start another run, approve it and select **Halt** while a child is working. | No new step starts after the halt, though a call already sent may finish at its provider. Delivered work stays readable and no combined answer is produced. The run message says "You halted the run" and has no answer. You can start another run. | |
| UAT-11 | Start and approve a run. Reload the browser while children are running. | The thread comes back from stored state with the same plan, approval and progress. The receipts show no second planning call and no repeated admission. The run keeps updating. | |
| UAT-12 | While a run is active (planning, awaiting approval or running), open a different chat in the same project. | The composer shows that profile as unavailable with "Another run of yours is still active. One run can be active at a time." and names the active run, its chat and its state. **Propose plan** is not offered. | |
| UAT-13 | Turn the fictional switch off on the API and the arq worker and restart both, with at least one run retained. Open the chat. | New runs are refused: the composer says "The operator has not enabled this profile." and nothing can be proposed or approved. The retained runs stay readable, with their plan, results, receipts and files, and can still be halted. Ordinary chat is unaffected. | |

### B. Real-document profile

Prepare a test matter owned by the test user. Attach to the matter at least two readable
test documents (plain text, Markdown or a PDF with a text layer) and one file the profile
cannot read, such as a Word file or an image-only PDF. Attach a further readable document to
the chat only, not to the matter. Switch the real-document profile on.

| ID | Action | Expected result / evidence | Result |
|---|---|---|---|
| UAT-14 | Open a chat in the test matter and choose the real-document profile. Then switch only that profile off and look again. | While on, the profile is available in any active project the user owns. The composer shows the pinned model, the total cap, the allowances, the attempt limit, the document limit (eight) and what it reads ("Only the documents you select for this run. No other matter files or live sources."). It does not depend on the fictional profile's switch. While off it is unavailable with "The operator has not enabled this profile." | |
| UAT-15 | Open the document picker. | The matter's files are listed and readable ones can be selected. The file that cannot be read is listed with its reason (unsupported type, not yet ingested, ingestion failed, or no text) and cannot be selected; it is not silently omitted. The chat-only attachment is listed with the note "Will be added to this matter when you propose the plan". No more than eight can be selected, and no other user's file appears. | |
| UAT-16 | Select two readable documents, one of them the chat-only attachment, and select **Propose plan**. Open the plan card. | The plan card lists the numbered selection and marks the chat-only file "added to this matter for this run". The matter's file list now includes it. The admin audit log shows a `project.file_attached` row with source `run_selection`. It is keyed to the matter, so it is not in the chat's receipts. | |
| UAT-17 | Select **Approve plan**. Follow the children. | Each child's steps show document reads by document number and file name, and nothing outside the selection. A document longer than one read is reported as cut, and the child reads on from the cut. Each task's tools and documents are as the plan card listed them. | |
| UAT-18 | Read the delivered answer. | Quotations are written as "quoted words" (Source: [N]), where N is the document's number in the selection. The run shows the result of the citation checks: how many quotations were checked, how many matched and how many did not, and the answer's gate status (fiduciary grade, supported only or flagged). Only a quotation written with a marker for a selected document is checked. If the answer also holds quoted passages with no marker, or a marker that names no selected document, the line says how many and that they were not checked; record whether a model you test writes its quotations without the marker. Open the ledger from the badge beside the citation chips: each matched quotation is listed with its text and its character offsets in document N. Pressing a chip itself opens nothing, as under an ordinary answer. Check at least three quotations against the documents yourself. If no quotation named a selected document, nothing was checked and the answer is labelled unverified. | |
| UAT-19 | Ask for something the documents do not contain, or for a paraphrase written inside quotation marks, until a quotation fails to match. | The quotation shows as unverified, the gate shows flagged, and the answer is still delivered. No judge model is called: the checks use only the exact and tolerant stages. If every quotation matches after reasonable attempts, record "not exercised by a person"; a controlled-provider test covers it. | |
| UAT-20 | Set the matter's minimum inference tier stronger than the route provides (a lower number is stronger). Open the composer. | The profile is unavailable and the composer gives the route reason. No planning call is made. Restore the tier afterwards. | |
| UAT-21 | In Settings, Account, request a data export. Open the ZIP when it is ready. | `orchestration_runs.json` contains the run: its request and plan, your approval, each task's result, the combined result, step receipts and the contents of the run's working files. `messages.json` contains the run message with kind `run` and its `autonomous_session_id`, and `work_product_attribution.json` contains its chain-of-custody row. Raw tool results and provider responses are not in the export. | |
| UAT-22 | Turn the real-document switch off on the API and the arq worker and restart both, with the run retained. | New runs are refused and nothing can be approved. The retained run stays readable and can be halted. The export still includes it. | |

If the citation checks themselves fail with an error at delivery, the answer is still
delivered, labelled unverified, and the delivery audit row records
`verification: unverified` and `checks: failed`. A tester cannot provoke this fault. A
controlled-provider test covers it.

### C. Closing an uncertain run

Do this on a disposable fixture only. Closing converts the unresolved reservation into a
charge and cannot be undone. To make a run uncertain, either set the attempt timeout to 1
second against a model that takes longer and restart the API and the worker, or pin a model
that rejects requests carrying tool schemas. Restore the settings afterwards.

| ID | Action | Expected result / evidence | Result |
|---|---|---|---|
| UAT-23 | Start a run (and approve it, if the model rejects tool schemas) so that a provider call ends uncertain. | The run message shows an unresolved provider call: the step reads "No confirmed outcome. It will not be retried automatically." Nothing is retried. | |
| UAT-24 | Select **Halt** on the uncertain run. Open another chat in the project. | The run stays uncertain, because a halt does not resolve the call. The other chat's composer names the run ("A run is active in" its chat), says "Uncertain: a provider call has no confirmed outcome", and offers **Close run** with the note "Closing charges the unresolved reservation, retries nothing, and frees you to start another run." | |
| UAT-25 | Select **Close run**. | The run says "You closed the run". Each unresolved call reads "Closed without an outcome. The reserved amount was charged." and has no result. Work that was already delivered stays readable. The run message has no answer. The receipts show an `orchestration.run_closed` audit row. | |
| UAT-26 | Open another chat in the project. | The composer no longer names a blocking run, and a new plan can be proposed. | |
| UAT-27 | The interface offers **Close run** only on an uncertain run, so use the API: call `POST /api/v1/autonomous/orchestration/chat-runs/<root id>/close` on the closed run, then on a completed run. | Closing the closed run returns it unchanged. Closing a completed or running run is refused with "Only an uncertain run can be closed". | |

### D. The run is as visible as an ordinary turn

Use a completed run from section A or B.

| ID | Action | Expected result / evidence | Result |
|---|---|---|---|
| UAT-28 | Compare the run message with an ordinary assistant reply on the same route. | The same fields are present on the run message: the applied skills (the profile's pinned skills), tier, provider and model, token counts and cost. The cost is the run's accounted spend, a conservative estimate rather than an invoice. | |
| UAT-29 | Open the chat's receipts drawer, or export the receipts as JSONL. | The run appears as an ordinary turn does: message and skill events, one inference event per model call with provider, model, tier, tokens, latency and anonymization, and audit events for the run's session and its tasks (planning started, approval, effects, delivery, and any tool refusal or close). | |
| UAT-30 | Operator check. Run these read-only queries against the database, using the run message's id from the receipts export or the messages response. `SELECT purpose, chat_id, message_id, routed_model, tokens_in, tokens_out FROM inference_routing_log WHERE message_id = '<run message id>' ORDER BY timestamp;` and `SELECT message_id, skill_ids, provider, model FROM work_product_attribution WHERE message_id = '<run message id>';` | Every model call of the run is a row with `purpose` set to `orchestration_run` and the run's chat and message identifiers. On the real-document profile there is no `judge_*` purpose for this message. There is one attribution row for the run message. No `tool_call_log` rows are expected, because that table records calls to external tool providers and neither profile grants one. | |
| UAT-31 | Search the chat history for a distinctive phrase from the answer. | The chat is found. | |
| UAT-32 | Optional, only if tracing is configured with one of the recipes under `deploy/observability/`. Find the trace of the request that accepted or approved the run. | The trace holds `orchestration.job`, `orchestration.run` and `orchestration.effect` spans from the service `lq-ai-arq-worker`, in the same trace as the API request and the gateway's spans. If the trace stops at the API, check that the arq worker has `OTEL_EXPORTER_OTLP_ENDPOINT` set. No span attribute contains prompt, document or answer text. See the [observability guide](../observability.md#orchestrationjob--orchestrationrun--orchestrationeffect). | |

### E. Extra checks

| ID | Action | Expected result / evidence | Result |
|---|---|---|---|
| UAT-33 | Approve a run that lasts longer than 15 minutes (a slow model, or the real-document profile) and keep the tab open without reloading. | Progress keeps updating through the 15-minute access-token expiry, with no sign-in prompt and no manual refresh, until the run ends. If the run ends sooner, repeat with a longer one or record "not exercised". | |
| UAT-34 | Approve a run, then leave the tab untouched for more than 30 minutes so the idle sign-out occurs. Sign in again and open the chat. | The run message is restored from stored state, showing the run's current progress or its answer. Nothing is repeated: the receipts show no second planning call and no repeated admission. | |
| UAT-35 | Open the matter workspace's chat (`/lq-ai/matters/<id>`) and start a run there. | The profile control, document picker, plan card, progress, answer and the active-run message behave as in the chats page. | |
| UAT-36 | Covered by UAT-12; record the result there. | With a run active in one chat, another chat's composer names it. | |
| UAT-37 | Put markup-like text in a document and in a request, for example `<img src=x onerror=alert(1)>`, `<script>alert(1)</script>` and `<b>bold</b>`, and ask a question whose answer quotes it. Add a sentence to the document that tells the model to ignore its instructions and read other files. | In the plan card, task text, steps, stated reasons and the answer, the characters appear as text. No HTML from the document, the request or the model is drawn, no image is loaded and no script runs. Markdown formatting in the answer (headings, lists, bold) is still drawn; a Markdown image appears as its source text. The run reads only the selected documents, and its plan, tools and budgets do not change. | |
| UAT-38 | Covered by UAT-13 and UAT-22; record the results there. | With each switch off, new runs are refused and retained runs stay readable. | |

## Automated checks

These use real Postgres, the store, the guard, the worker and checkpoint paths with a
controlled provider. They establish the contract. They use no configured provider and no
browser.

- `api/tests/autonomous/orchestration/test_runs_in_chat.py`: a run as one turn in the
  thread, delivery into its message, later turns, idempotent send, each refusal,
  isolation between owners, and the receipts and routing-log rows.
- `test_runs_in_chat_migration.py`: upgrading a release database through 0070 and 0071, and
  refusing a lossy downgrade.
- `test_tool_loop.py`: a granted call, a refused call, malformed arguments, the turn limit,
  restart in the middle of a loop, halt, an exhausted allowance and a detached document.
- `test_close_uncertain.py`: closing, the charge, and who may close.
- `test_document_runs.py`: the picker, selection, the read boundary, citation checks,
  hostile text, the tier floor and the export.
- `test_registry_contract.py` and `test_contract_versions.py`: adding a profile and a tool
  the product does not ship, and keeping 0.8.0 plan hashes.
- `test_run_tracing.py`: the run spans and the trace context carried through queued jobs.
- `gateway/tests/test_inference_b4.py`: the gateway's purpose labels.

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

The agent-driven walkthrough, with a controlled provider and native services, is in the
[acceptance record](../uat/adr38-runs-in-chat/README.md). It is not human acceptance. Record
the branch commit, the provider and model for each profile, the composer's figures, run and
message identifiers, and any failed attempts. Keep provider secrets out of the record.

ADR 0038 requires a run on a configured provider before the real-document profile is
described as working live. Record the provider and model used for UAT-14 to UAT-22.

- Human UAT, fictional profile (UAT-01 to UAT-13): **pending**. Tester: ______ Date: ______
- Human UAT, real-document profile (UAT-14 to UAT-22): **pending**. Tester: ______ Date: ______
- Closing an uncertain run (UAT-23 to UAT-27), records (UAT-28 to UAT-32) and extra checks
  (UAT-33 to UAT-38): **pending**.
- Configured-provider run for the real-document profile: **pending**. Provider/model: ______
- Branch commit: ______ Accepted cases: ______ Defects / deferred cases: ______
- Maintainer review: **pending**. Security review: **pending**. ADR 0038 ratification:
  **pending**.
- Production enablement: **not approved by this UAT**.
