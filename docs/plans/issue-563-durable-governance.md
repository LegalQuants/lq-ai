# Durable governance — W3 and the initial W4 transaction boundary

Local implementation of ADR 0035 D2/D5/D6. Public routes, ordinary worker
dispatch, production checkpoint deployment and full current-resource resolution
are not enabled by this slice. The internal store requires an explicit current
policy checker; it supplies no permissive production default.

## Lifecycle contract

The new lifecycle is private to `orchestration_roots`. Existing session phase,
status and halt enums are unchanged. Before wiring scheduling, the watchdog and
public session views must use this lifecycle for orchestration sessions.

| Operation | Required state | Result |
|---|---|---|
| Save initial plan | Owned active manual root, owner opted in, future deadline | `awaiting_approval`; root allowance recorded, no children |
| Replace plan | `awaiting_approval` or `queued`, next revision, no claim/reservation/admission, allowance covers prior spend | Previous revision superseded (consent and prior planning spend retained), new revision `awaiting_approval` |
| Approve exact revision/hash | `awaiting_approval` with valid current policy | `queued`; immutable consent stored, no children |
| Repeat approval | Current approved revision in executable state | Same consent, no additional event |
| Reject | `awaiting_approval` | `rejected`; repeat rejection is idempotent |
| Claim root/child | Approved `queued`, `running` or `waiting_children`; no live claim | New worker generation and bounded lease; root `running` |
| Release root/child claim | Exact live worker generation; no outstanding effect or reservation; cleanup allowed after revocation | Clear worker/lease, advance generation and audit atomically; preserve lifecycle, consent and accounting |
| Admit batch | Valid root worker claim and current approval | Child sessions, unique admissions, budget allocations and audit atomically stored; `waiting_children` |
| Admit effect | Executable root, current policy/phase/grants, live worker fence, budget available | Durable unique effect and reservation, then caller may perform I/O |
| Record effect | Matching live generation and admitted identity | Result/charge and reservation settlement stored; allowed for a pre-admitted call after halt/revocation |
| Recover expired claim with unresolved effect | An admitted/uncertain effect remains | Root `uncertain`; reservation retained, old generation invalidated; no replacement dispatch |
| Recover expired effects after halt/deadline/opt-out | Expired worker lease and an admitted effect | Recovery-only operation marks uncertainty and fences the old worker; does not require execution permission or retry a call |
| Owner halt | Any nonterminal root, even after opt-out/archival/revocation | `halted` (or retains `uncertain`); later effect admission refuses |
| Observed charge exceeds allocation | During completion | Record full charge; root `halted` with `observed_budget_overrun` |

`completed`, `failed` and `expired` are reserved terminal outcomes. No terminal
join/watchdog implementation sets them yet. `uncertain` counts against the
one-active-root-per-owner limit and has no automatic retry or resolution path.
The first implementation allows replacement revisions only before execution;
the immutable admitted batch cannot be edited in place. New follow-on work needs
a separately approved root. Account allocations remain fixed for this batch.

## Transactions and recovery

Every public store method owns one short transaction and commits before return.
No method calls a provider, writes a queue job, invokes LangGraph or waits for a
child. All write operations use owner/project/root/account/effect lock order;
root locking gives root halt and effect admission a single ordering. Owner and
project share locks prevent a concurrent opt-out/archive update crossing an
admission transaction. The injected checker must use database/local policy
reads only and preserve lock order; resolving remote config inside it is invalid.

The store checks owner opt-in, active project ownership, current project tier and
privilege restrictions, stored plan/hash/consent, root state and deadline. The
checker must add current selected-document/source visibility, pinned skill
coverage/digest and operator grants. Tests use an explicitly named fixture
checker; this does not establish that the production authority integration exists.

Worker claims use database time, a unique worker token and a monotonically
increasing generation. The lease is bounded by the plan deadline and per-attempt
timeout. A live claim cannot be acquired again, even with the same token.
Completion from a stale/expired generation refuses to rewrite records.

Stable `(session_id, effect_key)` identity and request hash distinguish replay
from changed input. An in-flight duplicate refuses; a completed receipt returns
its original result without allocating or charging again. One outstanding effect
per run is enforced by a partial unique index. On recovery, a missing outcome
becomes `uncertain`; its conservative reservation remains held. No framework
checkpoint can turn that into a new provider request.

The root allowance and child allocations come from the approved Decimal plan.
Initial storage carries forward existing root session cost; it cannot reset
planning spend. A replacement revision preserves that spend and cannot lower the
root allowance below it. Pre-planning budget admission still requires the W5
root-start integration; this store must not be used to adopt a concurrently
executing legacy session.
Admission creates all child allocations atomically; it does not yet activate
parallel worker capacity. Per-account effect admission checks spent plus reserved
against allocation. Settlement replaces reservation with charge once. An overrun
is recorded honestly, even above allocation; it stops further tree work rather
than changing observed usage to fit a constraint. Pricing verification and unused
child-allowance reclamation remain W4 work.

## Persistence and deletion

Migration 0067 backfills every old session as its own depth-zero root. A trigger
supplies that same default for existing callers. New children have depth one,
stable order, same owner/project as their root, and immutable tree identity.
Reparenting, cycles and deeper delegation fail at the database boundary. Parent
scope locking occurs at child insertion only. Ordinary child phase/cost updates
do not acquire a parent row lock that could block halt across provider I/O.

Deleting a root cascades its children and private governance records. Deleting
an individual child removes its account/effect records; it does not modify the
immutable approved plan or the root's permanent admitted-revision marker.
Recovery rejects any incomplete admitted batch, including deletion of every
child; it cannot recreate that work implicitly. Existing owner
deletion policy still governs account removal; project deletion is restricted
while orchestration records exist. The ordinary project archival path remains.

Downgrade refuses if any orchestration records or child sessions exist. Operators
must drain/export and explicitly remove those records before attempting a
downgrade; no automatic lossy rollback is supplied. A legacy-only database can
upgrade and downgrade without losing its existing sessions.

Plan/result content stays in private governance records. Audit events carry
only identifiers, revision/counts, generations, intent enums and monetary values.
The store uses the existing flush-only audit helper within its transaction.

The subsequent [worker-handoff milestone](issue-563-worker-handoff-milestone.md)
adds explicit claim release. It requires the caller to stop its graph invocation
first, refuses pending/uncertain effects or any retained reservation, and does not
wait for lease expiration. Root and child checkpoint fixtures prove a fresh worker
reuses a completed receipt and then executes a second effect without duplicate
provider calls or charges. This is a cooperative handoff, not arbitrary stale
checkpoint fencing or production queue integration.

## Outstanding integration

- Connect a production current-policy resolver and preserve R5 → R6 → R4 through
  the real guard's admission/effect/outcome integration. A store reservation alone
  is insufficient authority to call a provider.
- Connect the adapter to completed/uncertain receipts, including actual worker
  death, stale completion, checkpoint gaps and queue wakeup recovery.
- Implement final topology, shared deployment capacity, claim renewal,
  root/child watchdogs, deadline recovery and terminal joins. Do not put new child
  sessions on existing workers until these distinctions are honored.
- Implement pricing validation, budget reclamation and reconciliation policy for
  uncertain outcomes. No automatic uncertain-effect retry is allowed.
- Add API/UI/schema export changes only with the corresponding public surfaces.

## Validation evidence

- 133 focused tests passed: 96 W1 contracts, six original W2 characterization
  probes, and 31 new durable-store/migration/guard-recovery tests.
- Concurrent approvals, claims and child/effect admissions use independent
  sessions/transactions. Tests prove one consent/batch/worker/effect wins, audit
  failure rolls back its matching state, and settlement is idempotent.
- Fresh graph/saver integration with the actual LQ guard proves that a completed
  receipt prevents provider replay across the checkpoint gap; an unresolved
  provider outcome becomes uncertain and cannot be replayed. A root halt commits
  while the provider is waiting, and only the already-admitted effect can finish.
- The isolated migration round trip covers populated legacy backfill, upgrade /
  downgrade / upgrade, tree deletion cascades and refusal of a lossy downgrade.
  Its first run exposed deferred FK events during backfill; adding that FK after
  backfill fixed the issue. No live development database was touched.
- Full API regression passed: 2,792 tests, one skipped, in 344.39 seconds.
  The final focused run above followed the planning-cost and parent-lock review
  fixes and includes their three added regression cases. Mypy passed across 195
  API source files; Ruff check/format and whitespace checks passed.

These tests use actual application SQL/audit/guard code and Postgres. The current
resource policy is explicitly stubbed, the graph is an integration fixture and
the gateway returns fixture data. They do not establish production policy
resolution, actual process-death recovery, distributed capacity or a shipped
orchestration profile.
