# Issue 563 continuous demonstration

Owner direction, 14 September 2026: complete one sustained task without stopping
at each small milestone. The skill exists to demonstrate the orchestrator's
workflow, not to establish legal research quality. See the
[workflow and publication hold](issue-563-workflow.md).

## Acceptance

- A visible, pinned technical skill prepares a bounded plan for an owned project.
  The owner can inspect, approve or reject its exact revision before children run.
- Approved topics run as separate sessions, with bounded parallelism, independent
  transactions and durable checkpoints. Monitoring shows actual phase progress.
- Each topic delivers a bounded internal outcome. Empty and failed topics remain
  visible; successful siblings survive an ordinary failure. Only the root joins
  findings and delivers a synthesis, labelled as a demonstration and unverified.
- Halt prevents new work and renders available outcomes without a new model call.
  Restart reuses committed work, and uncertain calls retain their reservations.
- Deterministic provider fixtures prove the complete flow, overlap, approval,
  partial/empty outcomes and restart. No live providers or production enablement.

## Work sequence

1. Add the small root and child demonstration skills and reconcile ADR scope.
2. Connect durable phase/outcome lifecycle to a checkpointed root/child executor;
   enforce shared capacity and serialize writers to each checkpoint thread.
3. Add disabled-by-default worker dispatch/recovery, approval/tree API and the
   plan/progress view. Preserve the existing single-agent entry point.
4. Exercise the full demonstration with controlled providers, update API/schema
   documentation and operational instructions, and run integration regressions.

Advance directly after each step. Commit coherent reviewed increments locally
and record evidence here. Stop only for an actual external dependency or a
decision outside the existing authorization; elapsed coding time is not a gate.

## Deferred

Substantive research-skill authorship, search relevance, expanded citation
verification, legal-quality evaluation and real-matter source/KB integrations
are outside this demonstration. Keep existing mandatory checks and report their
actual status; never turn an absent verification into a passing verdict. ADR
ratification, implementation publication and live-provider enablement remain
separate owner decisions.

## Evidence

Implementation connects the two pinned demonstration skills, real governance
transactions, isolated LangGraph child sessions, durable root interruption and
resume, internal topic delivery and root synthesis. Six API paths expose the
closed sample plan and version/hash-bound approval, rejection, halt and tree
inspection. The new view is reachable from Autonomous sessions → Orchestration
demo. Browser polling is bounded to two minutes and supports manual refresh.

The local sample provider is deterministic and free. Planning turns the user's
selected topic labels into bounded task records; it does not call an LLM. Child
and synthesis sample responses pass through the actual guarded effect path using
the pinned skill instructions. Sample calls pause briefly so changing progress
is observable. This proves application orchestration with
controlled responses, not the quality of model planning or research. Successful
execution never changes `verification: unverified`.

The subsequent [working-file acceptance test](issue-563-workspace.md) adds a
seventh route for owner file inspection. Children save private notes, resume
from them and share immutable result files that the parent reads for synthesis.
Storage belongs to a run; reuse by a new invocation of the skill is not supported.

The initial demonstration completed locally on 14 September 2026 in one sustained
task (commit `75b115b94`). Its evidence follows; subsequent storage evidence is
recorded in the linked working-file plan.

- Full API regression: **3,083 passed, one skipped** in **242.16 seconds** against
  disposable pgvector Postgres, using four isolated test workers. This includes
  approval/privacy/lifecycle routes, the existing governance race/crash suite,
  migration 0069 up/down/up and session/user checkpoint deletion. The one skip is
  the existing empty stub-route parametrization, not a skipped database suite.
- A real arq subprocess, with disposable Redis and Postgres, completes the tree
  from a single approved root wakeup. Each child and the final synthesis have
  exactly one completed effect. This exercises actual queue scheduling and root
  resumption with the local sample provider.
- Controlled executor tests prove two children overlap while a third is refused
  at capacity, a competing writer cannot enter the same checkpoint thread,
  completed work survives fresh-executor recovery, and an uncheckpointed result
  reuses its committed effect. Losing the saver connection retains durable
  capacity until the old attempt releases ownership. Empty, malformed and mixed
  topic outcomes remain honest; halt retains completed findings without another
  synthesis call.
- Browser demonstration: **five Cypress scenarios passed** for plan/approval,
  progress/synthesis, rejection, halt/read after opt-out, disabled intake and
  stale consent. Browser API responses were controlled fixtures; the real API
  and queue flow were exercised separately above. Client Vitest: **two passed**.
- Svelte check: **zero errors, seven existing warnings** in unrelated files.
  Ruff lint and formatting passed (**562 Python files**); mypy passed
  (**210 API source files**). Dependency lock validation, API export drift and
  route inventory checks passed. No dependency versions changed in this slice.
- Isolated full-stack smoke: all **eight services healthy**, **zero restarts**
  after a **75-second** soak, with API/gateway/web health probes and docling
  import passing. The built stack exercised the default disabled configuration;
  the enabled queue flow used only disposable test services and sample responses.

Reproduce the API evidence from `api/` with a disposable `DATABASE_URL` and
`LQ_ORCHESTRATION_TEST_REDIS_URL`, using `uv run --locked --extra dev
--extra orchestration-test pytest -n 4 -q`. The queue probe skips explicitly when
its disposable Redis URL is absent. Browser evidence is in
`web/cypress/e2e/lq-ai-orchestration-demo.cy.ts`; run it against the local web
server. The previous governance evidence remains in the main workflow.

No ADR acceptance, implementation push or live-provider execution has occurred.

## Operator handoff (after ratification; not performed on development/production)

1. Deploy the same reviewed API/arq image and skill files together. Apply normal
   application migrations through **0070**. The new checkpoint schema is empty
   until execution; API requests and workers never create framework tables.
2. Set `LQ_AI_ORCHESTRATION_DEPLOYMENT_CHILDREN` explicitly (1–32, for example 2)
   and `LQ_AI_ORCHESTRATION_DEMO_ENABLED=true` on both API and arq workers. Compose
   forwards these values. An empty/missing limit does not mean unlimited. The
   worker checks the checkpoint schema at startup and refuses an enabled invalid
   configuration. The capability endpoint exposes the current mode and limit.
3. Opt into autonomous mode, choose an owned active matter and enter a goal with
   one to four topic labels. Review the plan, then approve or reject it. Approval
   commits before the arq wakeup; a dedicated minute sweep repairs lost wakeups.
4. Follow topic phases, internal findings, stable effect receipts and root
   synthesis. Halt is available after opt-out or feature disablement, including
   from an existing child receipt. No notifications, KB artifacts or memory writes
   are produced by this demonstration.

Disable new execution before changing shared capacity, pinned skills or operator
policy. Drain the API/arq deployment together; account ownership and uncertainty
remain conservative until recovery/reconciliation. Each invocation holds a single
saver connection and its advisory ownership lock. If that connection disappears,
durable occupied accounts still enforce capacity. Root/child waits retain no arq
invocation and do not trigger the old idle watchdog.

Checkpoint state contains identifiers, not findings. Migration 0069 binds every
checkpoint row to its session so root/user deletion cascades through continuation
data. Downgrade refuses owned accounts or retained checkpoints; export/drain and
explicitly remove the intended runs first. Do not clear uncertain reservations
merely to retry a call or reclaim a concurrency slot.

This handoff enables only the closed sample provider. Live sources, selected-KB
execution and a substantive research profile require their remaining #563 work
and separate enablement; they are not implied by completing the demonstration.
