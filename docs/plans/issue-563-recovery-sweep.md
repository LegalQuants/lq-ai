# #563 — Bounded recovery sweep

Status: implemented and verified locally. Continues the
root-deadline and expired-claim recovery increments under proposed ADR 0035.
Publication remains held for explicit ADR ratification.

## Internal invocation

`sweep_recovery(store, after=None, limit=25, operation_timeout_seconds=2)` processes
one maintenance page. It is not registered with arq, exported through an API, or
called by the existing single-session watchdog. The caller must supply the store;
no permissive policy checker or production configuration is introduced.

Discovery selects only root IDs for approval-waiting, queued, running,
child-waiting or uncertain roots, plus roots of any outcome that still own worker
claims. It reads at most `limit + 1` IDs in UUID order and closes its transaction
and connection before recovery. Private plan JSON is not fetched or cast in the
query. Eligibility is broader than being due: current deadlines and leases are
rechecked by the existing locked store operations for each root.

Page size is a strict integer from 1 through 50; each operation's timeout is a
strict integer from 1 through 5 seconds. The cursor is a UUID or null. Discovery
and each recovery stage have an asyncio timeout. These bound awaited operations,
not the hard wall-clock duration of database cancellation/rollback cleanup.

For each candidate:

1. Recover expired claims. This remains possible when its stored plan is invalid
   or current execution authority is revoked.
2. Check/recover the root deadline using the locked current plan.

Stages commit independently. A deadline failure does not undo an earlier claim
cleanup, and failure of either stage does not stop later roots in the page.
Each underlying store operation retains its own atomic state/audit boundary.
No sweep transaction spans the page, no provider call occurs, and nothing is
queued, replayed, refunded or synthesized.

## Pagination, failure and restart

`RecoverySweep` returns candidate count, confirmed stage counts, a tuple of
failures, and `next_after`. Follow `next_after` until null, then start a new scan
from the beginning on a later tick. Advance past failed candidates as well as
successful ones so a persistent invalid first row does not starve later roots.
Rows inserted behind the cursor are visited on a subsequent scan.

This cursor belongs to maintenance pagination. It is not a graph continuation
cursor, durable dispatch decision or authority to retry an effect. No cursor is
persisted in governance tables. After interruption a caller can repeat its last
page; the store prevents duplicate fencing, charges and lifecycle audits.

A failure contains only root UUID, stage (`claims` or `deadline`) and one fixed
code: `timeout`, `not_found`, `conflict` or `internal_error`. Reports contain no
exception text, traceback, private plan or receipt. They are internal operational
diagnostics, not research completion or verification receipts. Discovery failure
propagates because no page was established; cancellation propagates at either
stage and does not silently consume the rest of the page.

`claims_recovered` counts only confirmed returns from the claim-cleanup stage.
The deadline stage can also drain ownership if time advances between operations;
that additional cleanup is recorded by the store's audits, not that counter.
Timeout can leave a commit unacknowledged. Treat the summary as stage diagnostics;
durable state and audit records remain authoritative.

## Verification

The initial focused sweep run passed **16 tests** in 3.88 seconds. The complete
orchestration suite, including five added boundary cases, passed **296 tests**
in 19.36 seconds. Real disposable Postgres coverage proves:

- Pagination advances past an invalid root while safely cleaning its expired
  claim; subsequent pages expire valid roots without skipped candidates.
- Live claims and old approval waits retain their state before the explicit
  deadline. Clean terminal roots drop out once ownership has been drained.
- Competing sweeps do not duplicate claim fencing or lifecycle audits.
- A locked root times out while later roots progress; retry recovers it once the
  lock is released. A discovery timeout propagates before page processing.
- A deadline audit failure rolls back that stage while retaining the earlier
  committed claim cleanup; the report contains no injected private error text.
- Deletion after discovery produces fixed `not_found` failures and does not stop
  other roots. Uncertainty retains its reservation while clean peers expire.
- Cancellation during an audit rolls back; cancellation after a prior commit
  preserves it. Repeating either page completes without double fencing.
- A real pool with exactly one connection succeeds, proving discovery releases
  the connection before invoking the store's independent transactions.

Ruff check/format passed for API/scripts (549 files), mypy passed for 201 API
source files, and diff whitespace checks passed. The full API suite passed
**3,067 tests, one skipped**, in 268.41 seconds.
Tests use the isolated environment with `uv run --locked --extra dev --extra
orchestration-test --no-sync`, focused `pytest tests/autonomous/orchestration -q`
and full `pytest -n 4 -q`. Postgres is disposable on port 57670 with per-run
databases; provider calls were stubbed. The disposable test container was removed
after verification. No development/production database changes.

## Remaining production integration

The scheduler must persist or otherwise carry its maintenance cursor, bound its
per-tick work, surface failed stages without leaking content, and restart scans.
Production scanning cadence, worker topology, shared policy/capacity, heartbeat
scheduling, idle treatment, retries, checkpoint-writer fencing, joins and API/UI
integration remain in the workflow. The existing legacy watchdog must not apply
its idle rules to orchestration waits when the new workers are enabled. No cron
registration, worker boot change, migration or dependency is included here.
