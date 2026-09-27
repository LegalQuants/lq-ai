# ADR 0035 bounded chat: UAT

This test demonstrates model planning, explicit approval, parallel autonomous
children applying an installed skill, and model synthesis in an experimental
conversation. It does not sign off production orchestration, live research,
persistent skill storage or bundled helpers.

Implementation: `feat/adr35-chat-orchestration`. Design:
[bounded chat plan](../plans/issue-563-chat-demonstration.md). The earlier
sample-only page has been removed; its recording is historical preview evidence.

## Setup

Use a dedicated demo deployment, an owned active demo project and a user with
Autonomous mode enabled. Keep all goals fictional. Do not attach real documents.
Install the unchanged `contract-qa` v1.0.0 skill and the new technical
`orchestration-chat-demo` v1.0.0 profile, including its fictional agreement.
Apply migration 0069 and deploy API and workers from the same branch.

Set these values on both API and arq worker:

```dotenv
LQ_AI_ORCHESTRATION_CHAT_ENABLED=true
LQ_AI_ORCHESTRATION_CHAT_PROJECT_ID=<owned-demo-project-uuid>
LQ_AI_ORCHESTRATION_CHAT_PROVIDER=<direct-gateway-provider-name>
LQ_AI_ORCHESTRATION_CHAT_MODEL=<native-model-id>
LQ_AI_ORCHESTRATION_CHAT_BUDGET_USD=2.0000
LQ_AI_ORCHESTRATION_CHAT_MINIMUM_TIER=1
LQ_AI_ORCHESTRATION_CHAT_TIMEOUT_SECONDS=120
LQ_AI_ORCHESTRATION_DEPLOYMENT_CHILDREN=2
```

The minimum tier defaults to local inference (tier 1). For another route, choose
an explicitly permitted tier consistent with the project and installed skills.
Configure exact gateway prices for `provider/model`; local inference requires
explicit zero prices. Enable gateway anonymization at the selected tier for a
non-privileged project. Aliases, missing prices and route drift are refused.

Planning reserves one call, each child one call, and the root a final synthesis
allowance. Readiness checks that the cap can fund six bounded calls (planning,
four children, synthesis); the actual proposal can contain fewer children.
Input limit is 98,304 UTF-8 bytes, including pinned skill supporting files.
Output limit is 8,192 tokens per call, including reasoning where the provider
counts it toward the same limit. Visible child answers remain capped at 4,096
characters. Accounted costs conservatively retain
the reservation as a charge floor; they are not provider invoices.

The attempt timeout is configurable from 1 to 900 seconds, displayed before
planning and pinned in the proposal. Set it to 300 for the local model tested
here. The root deadline is one hour, including the approval wait. A provider
timeout is uncertain and is never automatically retried; Halt preserves that
uncertainty. This increment has no reconciliation UI. An uncertain run blocks
another run for that owner. For repeated testing, preserve its evidence and
use a fresh disposable fixture; never clear production receipts to retry.

Open `/lq-ai/autonomous/orchestration/chat`. For native Vite development, follow
[frontend development](../../web/docs/frontend-dev.md): the OpenWebUI shell must
also be reachable on port 8080, and Vite must target the dedicated API with
matching CORS. Do not point host migrations at an existing development database.

## Acceptance script

| ID | Action | Expected result / evidence | Results |
|---|---|---|
| UAT-01 | Leave the new flag off; open the chat page. | Clear disabled state; ordinary work remains available; the superseded sample preview is absent. No model call. | Agent switch-off check passed; human confirmation pending. |
| UAT-02 | Enable the dedicated fixture; select Contract Questions Orchestrator and inspect the agreement. | Model, project, fictional packet, total cap, planning allowance and attempt timeout are disclosed. | OK, but the page on Autnomous sessions says “Orchestration chat (experimental)"|
| UAT-03 | Submit the default goal about payments, implementation/support, renewal/termination. | Durable `planning` state; one real gateway planning receipt; then 2–4 proposed questions. No child admission before approval. | OK when a request is submitted , the “model is proposing bounded tasks”. A run provenance and root receipts are provided. No child runs. |
| UAT-04 | Inspect every proposed task. | Each has question, boundaries, expected output, stopping condition, Contract QA v1.0.0 and allowance. No extra tools or deeper delegation. | OK all pass |
| UAT-05 | Approve once; refresh while children run. | Approved revision/hash retained; two child sessions overlap; any additional child waits for capacity. Reload follows the same run without repeating planning or admission. | Pass |
| UAT-06 | Open “Skill execution receipt and files” for the renewal/termination child. | Actual `run_skill` effect, `contract-qa` version/digest, provider/model, accounting and timestamps; answer reaches shared `findings.json`. Merely naming the skill in prose does not pass. | Pass |
| UAT-07 | Inspect the combined answer. | Model synthesis uses the delivered child findings, retains missing information and clause references, and is labeled unverified. No synthetic replacement for failed children. | PASS |
| UAT-08 | Reopen the run URL after completion. | Same plan, approval, child results, receipts and synthesis; no new inference. | PASS |
| UAT-09 | Start a new request focused only on notice obligations and surviving duties. Reject its proposal. | Different model-authored tasks; planning receipt retained, zero child inferences and no synthesis. | PASS but the interface should inform that the work is not proceeding. Retested. Pass |
| UAT-10 | Start another request; halt during planning or child work. | No new effects after halt; retain delivered work and unresolved reservations. An already-dispatched call may finish at its provider. | PASS but I noted that Retained results tried to syntehsis as well. Retested Pass. |
| UAT-11 | Disable the flag after a retained run exists. | Read and Halt remain reachable; fresh planning/approval/dispatch refused. | Agent switch-off check passed for retained reads and new-intake refusal; human confirmation and live Halt check pending. |
| UAT-12 | Use another owner, stale hash, unpriced route or changed skill/config. | Owner-only reads; refusal before unauthorized dispatch. Controlled-provider tests exercise these without spending model calls. | Agent second-owner API isolation passed; human confirmation and other live variants pending. |
| UAT-13 | Open the results page after completion, rejection or halt. | The original request and the fictional agreement used for that run remain available for comparison; the agreement is shown only when its content matches the run's pinned digest. | PASS |
| UAT-14 | Open `notes.md` or `findings.json` from a child receipt. | The preview clearly identifies the saved file, revision and sharing status, and displays its contents in a distinct file viewer within that child's receipt. | PASS |

For UAT-07, check the fictional agreement rather than accepting plausible prose:
USD 200/month and 30-day payment window; two onboarding sessions within 20 business
days after the user list; support acknowledgement within two business days, with
no resolution SLA; twelve-month renewal with 30-day non-renewal notice; 30-day
breach cure; 60-day convenience termination with remaining-term fees; CSV export
within ten business days after termination upon request; the listed survival terms. Model quality
issues are recorded as defects, not silently edited out of the recording.

## Automated checks

`api/tests/autonomous/orchestration/test_chat_demo.py` uses real Postgres,
governance transactions, checkpoints, worker dispatch and installed skills with
a controlled provider. It covers the full plan/approve/parallel/join lifecycle,
required skill prompt content and provenance, invalid proposals, retained costs,
idempotent intake, rejection, disabled execution, scope/pricing/route refusals,
cross-owner access, premature approval, uncertainty and bounded transport cleanup.
The existing orchestration suites cover the shared authority and recovery core.

Run against a disposable PostgreSQL database:

```bash
cd api
uv sync --frozen --extra dev
DATABASE_URL=postgresql+asyncpg://test:test@127.0.0.1:55435/lqai_test \
  .venv/bin/python -m pytest tests/autonomous/orchestration \
  tests/autonomous/test_orchestration_contracts.py tests/test_openapi.py \
  tests/test_endpoints.py -q
```

Run `ruff check`, `ruff format --check`, API mypy, frontend `check:lq-ai`, the
orchestration Vitest contract tests and the isolated `scripts/stack-smoke.sh`.
Mocked provider tests do not establish live inference or human acceptance.

## Evidence and acceptance

Execution notes and redacted-to-fictional evidence live in
[`docs/uat/adr35-chat`](../uat/adr35-chat/README.md). Record branch commit, model,
packet and skill hashes, root/child IDs, call timestamps, actual outcomes and
any failed attempts. Capture proposed plan, skill receipt and combined answer.

- Agent-executed live smoke: see evidence record.
- Human UAT: **pending**. Reviewer: ______ Date: ______
- Accepted cases: ______ Defects / deferred cases: ______
- Production enablement: **not approved by this UAT**.
