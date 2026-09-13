# Issue 563 implementation workflow

Started 12 September 2026. This is the execution record for the local implementation
of [#563](https://github.com/LegalQuants/lq-ai/issues/563), anchored in proposed
[ADR 0035](../adr/0035-governed-orchestration-run-tree.md),
[PR #567](https://github.com/LegalQuants/lq-ai/pull/567).

## Authority and publication

Houfu authorized local implementation after opening the ADR PR. The proposed
direction is LangGraph continuation, arq scheduling and LQ-owned governance.
The ADR PR is open at `0e0b06d7120f6d5977233bbd0f3c50c51bab0f37`; no ratification
was recorded when this workflow started. Local work may supply integration
evidence for ratification. It must not be interpreted as ADR acceptance.

**Hold all implementation pushes and code PR creation until explicit ADR
ratification is recorded.** Repository policy separately reserves Git fetch,
pull and push for the owner. No merge, deployment, live-provider execution or
application feature enablement is part of this workflow without authorization.
Read-only GitHub checks and local commits are permitted.

## Workspaces and baseline

| Branch | Purpose |
|---|---|
| `codex/issue-563-governed-orchestration-adr` | Documentation PR #567; code does not enter this branch. |
| `codex/issue-524-langgraph-runtime` | Separate maintenance change for the runtime shared by all three executors, based on main `27c4521`. |
| `codex/issue-563-orchestration-implementation` | Harness implementation, based on the revised ADR commit; integrate reviewed local maintenance commits as required. |

The published research is preserved at `4ac3fee64`. Its SQLite experiment is
evidence for a fixed batch only; the application integration gates below remain
outstanding. Never overwrite the user's unrelated research worktree or import
unreviewed external contribution code to run tests.

## Ordered work packages

Each package is a coherent local commit or small series. Complete its focused
tests, inspect the diff for ADR compliance and code quality, fix findings, and
record evidence before advancing. A package is not complete merely because it
compiles. Broader suites run at integration boundaries, not repeatedly without
new changes or unresolved concerns.

| Package | Deliverable and acceptance gate | State |
|---|---|---|
| W0 — Runtime maintenance (#524) | Upgrade the existing LangGraph family; retype all three executors; review actual lock additions/removals/advisories; refresh the pin and debt docs and Dependabot exception. Preserve behavior and leave checkpointing disabled. Lock, Ruff, mypy, compiled graphs, required API tests and stack smoke pass. | Complete locally; publication held |
| W1 — Governed plan contracts | Strict bounded task data separate from server authority; stable plan identity/revision/hash; immutable approval scope; no model-supplied authority or arbitrary handler. Test malformed/hostile/extra input and scope/version changes. | Complete locally; 96 tests passed |
| W2 — LangGraph/Postgres integration | Real LQ guard and actual Postgres checkpoints, meaningful multi-step effect boundaries, independent child DB sessions, competing-owner/restart/halt fixtures and uncertain-call handling. Record worker topology and locked saver configuration; no second continuation cursor. | In progress; new store closes replay/uncertainty gaps in three actual guard/checkpoint fixtures; production adapter and process-death tests remain |
| W3 — Durable run tree and approval | Hierarchy migration/backfill/deletion rules, plan and approval persistence, version-bound approval, durable unique child admission and wakeup recovery. Real Postgres race/crash tests and migration up/down pass. | Persistence core implemented and tested locally; worker/wakeup integration remains |
| W4 — Authority, accounting and halt | Approved resource subset and current permission checks; inference/egress restrictions; atomic Decimal reservations/settlement; root allowance; fenced execution and cancellation; correct waiting/deadline/watchdog semantics. | Allocations, effect accounting, worker fences, current-policy callback and scoped document/inference guard implemented; external binding and shared policy/capacity/lifecycle integration remain |
| W5 — Parallel research and joining | Versioned visible orchestrator skill, isolated skill-backed children, bounded concurrency across root/user/deployment, internal child delivery, root-only output, partial/empty/failure outcomes. Barrier tests prove overlap and restart does not duplicate completed work. | Pending |
| W6 — API, gateway and receipts | Plan read/approve/reject, tree read, correlation stripped before provider calls, stable child receipts, separate completion/coverage/verification statuses and parent synthesis gate. Update API sketches/generated export, route pins and schema docs with code. | Pending |
| W7 — Intake and UI | Reuse corrected #410 entry point; explicit plan review, approve/reject, changing child progress, budget breakdown, halt, receipt links and bounded polling/manual refresh. Svelte/Vitest and controlled Cypress flow pass. | Pending |
| W8 — Integration and release readiness | Adversarial/race/crash/capacity/regression matrix, operator controls disabled by default, honesty/docs, migration compatibility, drain/rollback instructions and review evidence. No live search relevance or nonempty-result gate. | Pending |

W1 can be prepared before the runtime migration is integrated. W2 validates the
proposed backend before the larger persistence/execution work depends on it. W3
and W4 implement the production controls exercised in W2; the experiment does
not substitute for their actual migrations and integration tests. Reopen D4 only
for a material integration problem, documenting the evidence and proposed change.

## Dependencies to reconcile

- #411 is merged in the baseline; preserve its resource validation.
- #410 remains the intake dependency. Its review explicitly defers manual
  selected-KB retrieval; correct that and project data-policy propagation before
  real matter orchestration. Coordinate these corrections with W4/W7 and preserve
  omitted/null-query compatibility for existing single-agent callers.
- #536 is not required for the owner-scoped pilot. Use a current-access interface
  that later supports revocation without adding shared access implicitly.
- #558's 0.6.11 target is not the W0 migration. Do not merge it to bypass typing.
- #569 (KB emit authorization) and #570 (skill required-input enforcement) are
  newly open neighboring fixes. Inspect overlap when their paths are touched;
  do not claim their changes are on main or execute their branches during review.
- #564 may change ADR/DE identifiers and review routing. Record actual reviewers
  instead of assuming automatic routing supplies approval.

## Test environment

Use `uv` and isolated worktree environments. Real database tests use a disposable
`pgvector/pgvector:pg16` container and disposable per-run databases. Never migrate
the live dev DB, run `docker compose down -v`, or alter its volumes. Stack smoke
uses its own disposable compose project. Stub all inference/research providers.

Record commands, outcomes and limitations below. A skipped database test is not
database evidence. A provider-invoice ceiling is not established by estimated
cost tests. Uncertain external outcomes remain distinct from completed work.

## Progress and next action

- Baseline: implementation branch fast-forwarded locally to ADR revision
  `0e0b06d71`; separate W0 worktree created from `27c4521`.
- PR #567 description reconciled with the proposed LangGraph direction.
- W0 dependency resolution selected LangGraph 1.2.11, Core 1.6.3, checkpoint
  4.2.0 and SDK 0.4.4. The shared async node protocol resolves all 12 reproduced
  overload errors without changing function bodies. The focused 29 executor
  tests and full API suite (2,662 passed, one skipped) passed against disposable
  Postgres; Ruff, mypy, lock validation and the API image build passed. Full-stack
  smoke passed: all eight services healthy with zero restarts after 75 seconds,
  plus successful health probes and docling import. Detailed evidence is on the maintenance
  branch in `docs/plans/issue-524-runtime-migration.md`.
- W0 is saved as local signed-off commit `b5cd93a9` on
  `codex/issue-524-langgraph-runtime`. Integrated locally as `66602522`; resolved
  the PRD-only conflict by retaining the ADR link and verified migration evidence.
- W1: [contracts and limits](issue-563-contracts.md) implemented; 96 focused tests,
  Ruff and mypy (193 source files) passed. No orchestration routes, migrations or
  dispatch paths are enabled. The snapshot check is explicitly insufficient for
  durable admission or current authorization.
- W2: [six actual Postgres/guard probes](issue-563-postgres-probe.md) demonstrate
  interrupt/resume, overlapping multi-step children and current halt enforcement.
  They also reproduce committed-but-uncheckpointed replay, an uncertain request
  without a durable intent, and duplicate owners reaching the provider. The
  combined contract/probe run passed 102 tests. These diagnostic assertions do
  not satisfy production replay/fencing acceptance.
- W3/W4: [durable store and lifecycle](issue-563-durable-governance.md) implemented
  locally with migration 0067. Separate approval and admission transactions,
  immutable history/tree identity, fixed account allocations, worker generations,
  effect reservations/settlement and uncertainty recovery have real Postgres
  coverage. The final focused run passed 133 tests, including 31 new persistence,
  migration and actual guard/checkpoint tests. Full API regression passed 2,792
  tests with one skip; final focused regressions then verified preserved planning
  spend and that child phase updates do not lock their parent across I/O.
- Migration testing on populated legacy data caught and fixed the deferred-FK
  backfill ordering. Downgrade refuses to erase an existing tree/receipt history;
  legacy-only backfill and upgrade/down/upgrade preserve existing sessions.
- W4: [current policy and guarded scope](issue-563-current-policy.md) now check
  actual project document attachments, filesystem skill pins, operator versions,
  profile grants and source/tier restrictions. Scoped guard calls enforce selected
  file reads and authoritative inference settings. External dispatch remains
  refused until its exact provider/operation and pricing are bound.
  Autonomous regression: 791 passed; final focused policy/guard checks: 35 passed.
  Ruff check/format and mypy (197 source files) passed. The combined revocation
  fixture settles a pre-admitted call but refuses the next effect.
- Next: consume pinned instructions and bind external dispatch/pricing in the
  adapter's guard/effect integration, then shared current-policy distribution,
  worker topology/capacity, queue wakeup recovery and lifecycle handling. No public
  orchestration routes or ordinary workers invoke the store yet. Keep LangGraph
  as proposed.
- Ratification, production integration, code publication and release remain open.

### W1 implementation entry point

Keep pure contracts under `api/app/autonomous/orchestration/`, separate from
framework imports and existing single-session request schemas. Start with the
bounded model-authored task fields from ADR D3 and a one-to-four topic batch.
Reject unknown fields and invalid JSON without a free-text fallback. Test that
authority fields, arbitrary handlers and prompt overrides cannot enter through
this schema. Prose remains untrusted after structural validation.

The server-prepared plan must bind task content and approved execution settings:
root/project/owner identity, revision, policy version, pinned skill digest,
selected resources, grants, both tier constraints, Decimal budget and deadlines.
Use an immutable canonical representation for the approval hash; tests must show
that changing any executable setting invalidates an existing approval. Approval
is only evidence of consent to that snapshot: current-access validation, durable
idempotency, atomic admission and halt checks belong to the persistence boundary
and must never be represented as accomplished by a hash or an in-memory object.

Do not wire these contracts into dispatch before W2/W3 prove the durable barrier.
Record the internal contract and limits with its tests; add public API and DB
documentation when those surfaces are introduced in W3/W6.
