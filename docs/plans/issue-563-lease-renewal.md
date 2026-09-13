# #563 — Bounded worker lease renewal

Status: implemented and verified locally.
This continues the safe-handoff milestone under ADR 0035 D4/D7. Publication remains
held for explicit ADR ratification.

## Contract

A claim now persists two timestamps on its budget account:

- `attempt_deadline`: fixed at claim admission to the earlier of the approved
  root deadline and database time plus the approved attempt timeout.
- `lease_until`: the current ownership expiry, at or before that fixed deadline.

The internal `renew_claim(claim, seconds=...)` method returns the effective lease
expiry. It accepts the same strict integer range as claim admission (1–900
seconds), revalidates owner/project, consent, policy and root execution state,
and requires the exact live worker and generation after taking the account lock.
It extends expiry to at most the fixed attempt/root deadline. A delayed shorter
heartbeat cannot shorten an existing lease. Repeated renewals at the limit are
no-ops, but still revalidate authority. Actual extensions and the identifiers-only
`orchestration.claim_renewed` audit event commit together; audit failure rolls back
both. Renewal never changes the generation or fixed attempt deadline.

An admitted provider call may remain in flight during renewal. Its reservation,
receipt and generation stay unchanged, and control locks remain free during
provider I/O. The guarded adapter retains the timeout it computed before that
call: renewal does not lengthen an already-running provider request. If ownership
expires before settlement, the existing uncertainty path retains the reservation
and refuses replay. Renewing an expired or superseded claim cannot revive it.

Renewal leaves root lifecycle, root update time and session activity/phase fields
unchanged. A heartbeat is evidence of ownership, not research progress. Expiration
recovery and safe release clear all ownership timestamps and fence the old
worker. A fresh claim starts a new bounded attempt; production retry/backoff
policy remains a separate integration gate.

## Migration and rollback

Migration `0068` adds nullable `orchestration_accounts.attempt_deadline`, and
backfills existing owned accounts with their current lease expiry. It grants no
extra time to existing claims. Unowned accounts remain null. Database checks
require the deadline when ownership exists and forbid leases beyond that limit;
budget allocations, approval snapshots and effect receipts are unchanged.

Drain workers before changing application versions. Old writers do not maintain
the new timestamp and fail the constraint, so this is not a mixed-version worker
rollout. Rebuild API, arq-worker and ingest-worker together when the owner later
applies the migration. No development or production database is migrated by this local work.

Downgrade to `0067` takes an exclusive account-table lock and refuses while any
worker ownership remains, including an expired claim that has not been drained.
Complete safe releases or existing uncertainty recovery first. The migration
preserves charges, reservations, approval and receipts; it does not clear them to
force rollback. Unowned accounts and uncertain receipts round-trip unchanged.
For abandoned ownership without an effect, the bounded store currently permits
reclaim followed by release while execution remains authorized; stopped/expired
roots need the future lifecycle drain tooling before downgrade. Do not bypass
this guard with a destructive database reset.

## Verification

Real disposable Postgres tests cover root/child renewal, fixed attempt and root
limits, repeated/shorter heartbeat behavior, authority revocation, stale and
expired claims, account-lock expiry, renewal/release and renewal/recovery races,
atomic audit rollback and preserved activity/accounting. The actual guarded
adapter fixture renews while its stub provider is blocked, then proves either
single-charge settlement or conservative uncertainty at expiry.

The migration fixture upgrades populated accounts at `0067`, checks conservative
backfill and SQL constraints, verifies refused downgrade while owned, and tests
upgrade/down/upgrade with completed and uncertain receipts preserved.

Initial verification exposed a test-module import assumption, an accidental extra
release-audit argument and a JSON SQL fixture parsed as a bind parameter. These
were corrected; the orchestration suite then passed **214 tests** in 11.78 seconds.
Three subsequent boundary tests cover no-op revalidation and plan expiry after
account locking. The full API suite, including those cases, passed **2,988 tests,
one skipped**, in 254.64 seconds. Ruff check/format passed for API and scripts
(546 files); mypy passed for 200 API source files, and diff whitespace checks
passed. The isolated stack smoke passed: all eight default services healthy,
zero restarts after 75 seconds, successful host health probes and docling import.
All providers were stubbed; only disposable databases were used. The test container, smoke containers and
their six project-owned volumes were removed after verification.

Verification commands use the isolated API environment with `uv run --locked
--extra dev --extra orchestration-test --no-sync`. Database runs use only the
disposable Postgres port 57670 and per-run databases:

- `pytest tests/autonomous/orchestration -q`
- `pytest -n 4 -q`
- `ruff check api scripts` and `ruff format --check api scripts` from repository root.
- `mypy app` from `api/`.
- `git diff --check`.
- The repository `scripts/stack-smoke.sh` gates, via a temporary copy changing
  only the workdir, project/image names, environment-file isolation and probe
  ports. Project `lq-ai-563-renewal-smoke` uses dummy secrets, separate ports and
  private volumes. It builds all default images, boots all services, probes
  health/docling and observes the standard 75-second soak. No dev-stack service
  or volume is reused.

## Remaining integration

No production heartbeat task or worker invocation is enabled. Shared policy and
capacity distribution, scheduler wakeups, retry/backoff, lifecycle watchdogs,
checkpoint-writer fencing and root/child joining remain in the existing workflow.
This increment supplies the bounded ownership primitive those workers need; it
does not complete W2/W4 or the #563 epic.
