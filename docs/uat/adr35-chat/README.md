# ADR 0035 chat demonstration: execution evidence

**Date:** 2026-09-27. **Branch:** `feat/adr35-chat-orchestration`.
**Implementation commit:** `253eeaaa8f74c75c9eb4c2abed0f712386a97cef`.
**Result:** agent-executed live flow passed for the two-question scenario below.
**Human UAT:** pending; this record does not provide human acceptance or production
enablement. Follow the [UAT script](../../runbooks/adr35-chat-uat.md).

## What ran

The browser submitted a natural-language request. A real local model proposed
two tasks. The browser paused at approval, approved that revision, observed two
separate Contract QA children, and received a model synthesis. Reload during
execution and after completion recovered the retained run. A second, changed
goal produced different tasks; rejecting it dispatched no children.

This used the LQ API, Postgres, arq, Redis, the governed autonomous executor,
LangGraph checkpoints, the LQ gateway with anonymization, and Ollama's installed
`gemma4:26b-mlx`. No deterministic sample provider produced these results. The
source was the installed fictional agreement; no live research, real matter
documents, persistent skill storage or bundled helper was selected.

The dedicated native test services used ports 15173 (Vite), 18090 (API), 18091
(gateway), 55435 (throwaway Postgres), 56385 (throwaway Redis), and 8080 (isolated
OpenWebUI development shell). Existing development services were left alone.
The successful fixture database is `lqai_demo3`; earlier failed runs remain in
separate disposable fixtures. These services are temporary local UAT facilities,
not deployment evidence for the full Docker composition.

The same fixture is now running with the orchestration demo settings removed.
Open a [completed run](http://127.0.0.1:15173/lq-ai/autonomous/orchestration/chat/699ea090-85ce-45ab-9426-8f4247a680d4)
or the [disabled request page](http://127.0.0.1:15173/lq-ai/autonomous/orchestration/chat).
The model profile remains disabled by default in committed configuration.

## Post-demo switch-off check

After human UAT, the same `lqai_demo3` database, Redis instance, account and
run history were retained. The API, arq worker and gateway were restarted with
the same connection settings but **no `LQ_AI_ORCHESTRATION_*` environment
variables**. The old demo environment file was removed; no fresh database was
substituted. The frontend continues to serve this branch on port 15173.
The gateway's local model route was held constant to isolate the effect of
switching off orchestration; ordinary chat still offers that route.

The API and gateway health checks passed. In the signed-in browser, Home,
ordinary Chats and Autonomous sessions loaded, and a new ordinary chat opened
with its composer. A completed orchestration run still showed its plan, child
answers, agreement and combined answer. The new orchestration request page
reported that model orchestration was not enabled and showed no intake form.
The Autonomous sessions page now displays “Orchestration chat (experimental) —
disabled by operator” as a disabled control. Direct links to retained runs
remain readable.

A new ordinary chat sent one short prompt to the unchanged local
`local-uat/gemma4:26b-mlx` route and received “Confirmed. I can read this
message.” After a page reload, the chat appeared in the list and reopening it
restored both messages. This exercises basic chat creation, database persistence
and inference after the demo switch-off. Human UAT-11 remains for the reviewer
to confirm; other app workflows were not exercised in this check.

## Second-user isolation check

A separate disposable member account, `adr35-reviewer@example.com`, was added
to the **same** fixture database with Autonomous access enabled. It has no
admin role and owns no sessions. Its own API login succeeded. With that
account's token, `GET /autonomous/sessions` returned 200 and zero rows;
reading the owner's completed chat run
`699ea090-85ce-45ab-9426-8f4247a680d4` through either the chat-run endpoint
or the autonomous-session endpoint returned 404. Chat orchestration capabilities
still reported disabled. This verifies the live API isolation for this pair of
accounts. Human UAT-12 remains for the reviewer to exercise in the browser.

## Successful run

User goal:

> Use two independent agents to answer two focused questions about this fictional
> agreement: (1) What amount must Customer pay and when? (2) What notice is required
> to prevent renewal or terminate for convenience? Combine their concise
> clause-based answers and flag only information that the agreement does not specify.

Root: `129b14e7-d75f-45b1-aa9d-a0d1267042e4`.
Provider/model: `local-uat/gemma4:26b-mlx`, direct tier 1 route, anonymization on.
Accounted cap: USD 2.0000; local route explicitly priced at zero. Every inference
settled at USD 0.0000, with no remaining reservation. This demonstrates accounting
and admission, not paid-provider invoice accuracy.
Limits: 98,304 input bytes, 8,192 output tokens, 300 seconds per attempt,
one-hour root deadline, two concurrent children, one inference per phase/child.

| Event (UTC) | Evidence |
|---|---|
| Planning: 08:12:37.279–08:12:58.471 | Real model proposed “Payment terms” and “Renewal and Termination notice”. |
| Approval: 08:16:37.772 | Revision 1; hash `05c9d5c97c553f14b6f42d7528daa94960508afd8a55b9af295b1d8fd839306d`. |
| Child admission: 08:16:37.958 | Both admissions occurred after approval. |
| Payment inference: 08:16:38.842–08:17:22.385 | Child `d867ed77-053d-4276-8dc3-66a0dd0e9d3c`; `run_skill`, Contract QA v1.0.0. |
| Notice inference: 08:16:38.852–08:17:52.002 | Child `6cf7d53e-d3bc-4691-9d93-b6f1731f5b25`; `run_skill`, Contract QA v1.0.0. |
| Synthesis: 08:17:52.858–08:18:09.649 | Root read both immutable shared findings files, then made one synthesis call. |

The child requests overlap for about 43.5 seconds. This proves concurrent child
execution and outstanding provider calls; it makes no claim about parallel GPU
scheduling inside the local model server. All four responses finished with
`stop`. Reported prompt/completion token counts were 1,872/2,056 (plan),
15,699/2,290 (payment), 15,708/1,711 (notice), and 2,015/1,317 (synthesis).

Both children loaded the installed Contract QA instructions and supporting
material. The controlled-provider integration test independently asserts that
material enters the model request and the preserved answer reaches synthesis.
The live receipts identify the same artifact:

| Pin | SHA-256 |
|---|---|
| Contract QA v1.0.0 | `898f5b10cd75eb45d484dce8ce94b20186f436250ac2825b646f98acba61ae42` |
| Orchestration profile v1.0.0 | `76895d69471329b86615d6cdaa01cdff8a0f57ac29a4b3219a5025753d15783d` |
| Fictional agreement | `31621b3b2ac3b863a5fdfaf6f9e0021d24751e041654792d17b776d3d193b6db` |
| Gateway revision | `2e80c52a5ddf325ba9ab468c11e751a522ae0f025414bf1fcd9914502ca9ae79` |

The returned answer correctly states USD 200/month, invoicing in advance, the
30-day payment window, 30-day non-renewal notice, and 60-day convenience notice
with fees remaining through the current term. Clause references are retained.
This is a check against the fictional packet, not automated citation verification
or a legal-substance acceptance. The UI preserves Markdown as plain text in this
bounded demonstration.

## Evidence files

- [model-run.json](model-run.json): completed owner read projection, approved
  plan, child findings, file digests, skill receipts, and root synthesis.
- [dispatch-evidence.json](dispatch-evidence.json): approval binding, admission
  timestamps, actual token counts and completed inference timestamps, read from
  the dedicated database without raw prompts, credentials or provider bodies.
- [reload-and-rejection.json](reload-and-rejection.json): completed projection
  unchanged after browser reload; rejected run has zero child admissions and
  exactly one completed planning effect.
- [rejected-run.json](rejected-run.json): changed-goal run
  `fbc1b9cc-bc4b-49b6-af39-26e9212a04fc`. Its proposed tasks concern notice
  requirements and surviving obligations. Pending child entries in this view
  are plan projections, not admitted sessions. No synthesis was dispatched.
- [plan.png](plan.png), [parallel.png](parallel.png),
  [skill-receipt.png](skill-receipt.png), [result.png](result.png), and
  [rejected.png](rejected.png): browser captures. The progress capture shows one
  child finished while the other was running; the timestamps above establish
  their earlier overlap. These are screenshots, not a filmed demonstration.

## Earlier attempts and defects found

Failed attempts are retained rather than edited into apparent success:

| Evidence | Observed result and response |
|---|---|
| [timeout-run.json](timeout-run.json) | Qwen planning succeeded; children exceeded the ordinary gateway client's 60-second timeout. The run became uncertain. Added a dedicated, bounded model-demo transport that respects the pinned attempt timeout and closes its client. |
| [stalled-model-run.json](stalled-model-run.json) | With a 300-second attempt, Qwen completed one child but other requests stalled. Halt retained uncertain receipts. Its completed answer also treated pseudonymized numeric values as missing; the adapter now explains that supplied placeholders are values restored by the gateway. No provider failover or automatic retry was introduced. |
| [truncated-plan-run.json](truncated-plan-run.json) | Gemma consumed the initial 2,048-token ceiling before emitting a visible plan; finish reason was `length`. The proposal was refused. Raised the bounded ceiling to 8,192 to accommodate reasoning and retained the 4,096-character child answer limit. Truncated synthesis is also refused, with delivered child work retained. |
| [fenced-plan-run.json](fenced-plan-run.json) | Gemma returned a valid plan inside one JSON Markdown fence. The original parser refused it. The adapter now removes exactly that complete outer wrapper, then applies strict JSON and schema validation; prose, duplicate keys and authority fields remain invalid. No extra model call repairs a response. |

The Qwen uncertain runs remain unresolved after Halt, as designed. A fresh
disposable fixture was used for Gemma. This increment has no reconciliation UI;
an uncertain run blocks further runs by its owner. Do not clear production
receipts to get around this condition. The local model was changed explicitly
between fixtures, never during an approved run.

## Follow-up during human UAT

Two further three-topic experiments (`26ff23e3-68d2-4bb9-a1d7-889ffec73d5b`
and `3934ea18-7181-4384-bc6d-4dc9d25f53e5`) exposed a child output mismatch.
The Implementation and Support child failed with `invalid_output` in both runs;
the Term/Renewal/Termination child also failed in the second. Their inference
receipts completed with `finish_reason=stop`. Two of the three failed responses
were substantive Contract QA Markdown; one was malformed fenced JSON. The
previous adapter required every child to return a JSON envelope even though
the installed skill specifies an adaptive Markdown answer.

The branch now requests the skill's Markdown directly. A bounded adapter wraps
that answer in the server-owned, unverified child outcome and preserves the full
text for the shared findings file. It still refuses empty or truncated output,
oversized text, control characters, malformed JSON attempts and model-supplied
artifact references. One completed older JSON envelope remains readable for
effect replay. No retry, authority grant or change to the retained failures was
made. Replaying the three actual response texts through the new adapter accepts
the two Markdown answers and still rejects the malformed JSON.

The focused integration test now drives the full approved child flow with
Markdown. The orchestration and API regression suite passed **455 tests, with
3 skipped**; ruff and mypy passed. The isolated arq worker was restarted with
the fix after both user runs completed. A new live run after this change remains
a human UAT check; previous run records must continue to show their original
failures.

## Verification results

| Check | Result |
|---|---|
| Orchestration, contracts, worker-registration, endpoints and OpenAPI regression | **452 passed, 3 skipped** against disposable Postgres; includes the latest adapter fixes. |
| All LQ frontend Vitest tests | **638 passed**, 75 files. |
| API ruff / format | Passed; 599 files already formatted. |
| API mypy | Passed; 229 source files. |
| Frontend `check:lq-ai` | 0 errors; 7 existing warnings in 4 files. |
| Prettier on changed frontend files | Passed; existing `pluginSearchDirs` option warnings. |
| Migration 0069 | Applied on fresh disposable databases and exercised by integration tests. |
| Full API suite, earlier in implementation | 3,186 passed, 10 skipped, 4 failed. One worker-cron test fixture was updated for the new flag. Three unchanged audit-order assertions failed in that broad run and passed in isolation; their ordering is sensitive to equal transaction timestamps. All four failing cases and their nearby checks passed on rerun (12 passed). A fresh all-API green run is **not claimed**. |
| Full Docker stack smoke | **Blocked by memory**, twice. Default build failed with `cannot allocate memory`; a temporary 4 GB Node heap override failed with JavaScript heap exhaustion. Neither reached compose boot/soak. Native live UAT does not replace this gate. |

Terminal logs for this local session are under `/private/tmp/adr35-*`, including
`adr35-regression-complete.log`, `adr35-web-all-tests.log`,
`adr35-api-all-tests.log`, `adr35-failed-checks-rerun.log`, and the two
`adr35-stack-smoke` logs. The reported totals above are captured from those runs.

## Acceptance still required

Agent browser exercise covers the focused two-task variants of UAT-02 through
UAT-09. Earlier failed runs exercised Halt with uncertainty; controlled tests
cover halt during planning/work, disabled operation, changed policy/skill/route,
owner isolation and stale/premature approvals. Disabled/re-enabled browser
operation and the broader default three-topic scenario still need human UAT.

Run the full stack smoke on a host with sufficient memory, review the full API
suite's audit-order failures in CI, and execute the runbook as the intended user.
Ordinary chat integration, live sources, optional skill storage/helpers, and
production release gates remain outside this bounded demonstration.

Reviewer: ______ Date: ______ Accepted cases: ______ Remaining defects: ______
