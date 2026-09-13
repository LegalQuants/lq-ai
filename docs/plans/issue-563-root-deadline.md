# #563 — Root deadline recovery

Status: implemented and verified locally. Publication remains
held for ADR ratification.
This internal lifecycle increment follows ADR 0035 D2/D7 and expired-claim recovery.

## Transition contract

| Condition | Result |
| --- | --- |
| Stored current plan invalid or identity/hash mismatched | Refuse; never guess a deadline. Expired-claim cleanup remains independently available. |
| Before root deadline | No mutation, audit or claim drain, including approval and child waits. |
| Deadline reached, awaiting approval / queued / running / waiting children, no unresolved accounting | Drain expired ownership and mark private root `expired`; record `root_deadline` unless a prior stop reason exists. |
| Deadline reached, admitted/uncertain effect or retained reservation anywhere in the tree | Retain funds and uncertainty; no clean expiry or automatic retry. Include accounts already unowned. |
| Deadline reached, root already uncertain | Preserve uncertainty even if no current pending receipt exists; reconciliation remains separate. |
| Deadline reached, clean halted / failed / rejected / completed / expired root | Preserve its outcome and stop reason; drain any expired ownership. |
| Repeated recovery | No extra generation or lifecycle audit once state is unchanged. |

Owner/project/root/account/effect locking follows the existing store ordering.
Deadline comparison uses database time after the root lock, and the stored plan
is validated without requiring current execution permission. The whole operation,
including claim cleanup and lifecycle audits, commits or rolls back together.
No provider call, enqueue, budget refund, synthesis or notification occurs.

This does not change legacy session status/phase enums, install a watchdog job,
or expose a public API. The private lifecycle must be integrated into worker and
API/UI behavior before production use. Awaiting approval and children have no
idle timeout applied here; only the explicit root deadline ends a clean wait.

## Implementation and verification

The internal `expire_root(root_id)` operation returns `True` only when the root
newly becomes cleanly expired. `False` can still accompany expired ownership
cleanup or a transition to uncertainty. `root_expired` and `deadline_uncertain`
audits carry only the current revision alongside the root's normal audit identity.
They commit with all claim/effect recovery in the same transaction. There is no
second graph continuation cursor and no new table or migration.

Plan parsing/identity checks are shared with execution admission, but deadline
recovery does not call current execution-policy checks. The account recovery
implementation is shared with existing expiry APIs inside the caller's transaction.
The existing owner/project/root lock ordering serializes deadline recovery with
approval, plan replacement, effect admission, renewal and settlement.

The first complete orchestration run passed **269 tests** in 14.83 seconds. It
covers clean waits, repeated/concurrent expiry, preserved terminal outcomes,
revocation, invalid snapshots/hashes/identity, a plan-revision race and atomic
rollback of both clean-expiry and uncertainty audits. The real guarded adapter
also reaches a stub provider barrier: deadline recovery commits promptly, the
reservation becomes uncertain, and the late response cannot commit a receipt or
session charge. No subsequent provider request starts.

Five final cases exercise unresolved child accounts and show that clean expiry
preserves completed charges/receipts while freeing the owner's active-root slot
for a new plan requiring its own approval. Final review added auditing when an
already-uncertain root receives a previously missing reason. The final full
orchestration run passed **275 tests** in 15.61 seconds, including all six added
cases and that audit correction. The full API run passed **3,045 tests, one
skipped**, in 263.17 seconds; the subsequent final orchestration run covers the
audit correction added after full-suite collection.
Ruff check/format passed for API/scripts (547 files); mypy passed for 200 API
source files, and diff whitespace checks passed.

Commands use the isolated API environment with `uv run --locked --extra dev
--extra orchestration-test --no-sync`: focused `pytest tests/autonomous/orchestration
-q`, full `pytest -n 4 -q`, plus Ruff, `mypy app` and `git diff --check`.
Database tests use disposable Postgres port 57670 and per-run databases. All
provider calls were stubbed. The disposable test container was removed after
verification. No development or production database was migrated.

## Remaining integration

Production watchdog scanning/scheduling, root/child idle rules, bounded retries,
shared policy/capacity, checkpoint-writer fencing, joins and public API/UI remain
in the workflow. The existing single-session cron/watchdog is unchanged. This
private deadline transition must be connected deliberately to orchestration
worker and user-facing lifecycle handling before it is enabled.
