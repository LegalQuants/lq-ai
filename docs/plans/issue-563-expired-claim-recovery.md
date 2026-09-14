# #563 — Expired ownership recovery

Status: implemented and verified locally. Continues bounded
lease renewal and safe worker handoff under ADR 0035 D4/D7. No implementation
publication or feature enablement; explicit ADR ratification remains required.

## Behavior

`OrchestrationStore.recover_expired_claims(root_id)` returns the number of expired
owned accounts it fences in one transaction. It uses the established owner →
project → root → account → effect lock order, database time, and a deterministic
account order. It only narrows authority and therefore remains available after
halt, deadline, opt-out, archival or policy revocation. It does not need to parse
or approve a plan to release expired ownership.

For each expired claim it increments the generation and clears worker,
lease expiry and attempt deadline. The `orchestration.claim_expired` event contains
only session identity and the new generation, and commits atomically with all
claims recovered in that call. A failure while auditing any account rolls back
the entire transaction, including prior accounts and effect changes.

- A clean account retains its root lifecycle, stop reason, update/activity times,
  approval, allocations, completed receipts and charges. Recovery does not mark
  the run complete or count as research progress.
- An admitted effect becomes uncertain, keeps its reservation and emits the
  existing `effect_uncertain` event. An already uncertain effect remains uncertain.
- A nonzero reserved balance without a pending receipt is still unresolved. Keep
  the balance and mark the root uncertain with `unresolved_reservation` when no
  prior stop reason exists. An existing stop reason, including owner halt, is
  preserved. Zero-cost pending effects also remain uncertain.
- Live ownership and other roots are untouched. Repeating recovery after cleanup
  returns zero without another audit or generation change. A concurrent new claim
  or lease renewal cannot have its live ownership cleared by recovery.

The earlier `recover_expired_effects` API retains its admitted-effect-only count
and behavior through the same private transaction implementation. It still skips
idle accounts. New lifecycle integration can use the broader operation to drain
both idle and unresolved expired ownership.

Recovery does not admit work, enqueue a retry, release budget allocations or
reconcile unknown provider outcomes. A replacement must pass the existing current
approval/policy/deadline checks. Root uncertainty continues to prohibit execution.

## Resume evidence

Root and child fixtures stop an actual LangGraph invocation after a receipt
commits but before its node checkpoint. They close the saver, expire the claim,
recover ownership and race two replacement claimants. One wins; its fresh
Postgres saver reuses the completed receipt and performs a second effect once.
Exactly two provider calls and charges remain across both workers, and the old
generation cannot admit, settle, release or mark the new effect uncertain.

This models application ownership recovery after the earlier graph invocation
has stopped. It does not fence arbitrary stale framework checkpoint writes;
production worker topology and checkpoint-writer fencing remain required.

## Drain and verification

This fills the previously documented idle-ownership gap in migration 0068's
downgrade procedure. Stop the workers, allow live leases to expire, then invoke
the internal recovery operation for the affected roots before a downgrade.
Receipts and reservations remain inspectable. Production operator tooling and
watchdog scheduling are still unimplemented; this is not an exposed drain API.
No migration, dependency, public endpoint or worker boot path changes here.

The focused `pytest tests/autonomous/orchestration -q` run passed **241 tests**
in 14.34 seconds against disposable Postgres. Two additional cases exercise the
broader recovery operation in the existing renewal/reclaim race tests. The full
API regression passed **3,014 tests, one skipped**, in 268.01 seconds. Final store/lease/effect
verification passed **120 tests** in 8.10 seconds, including an additional
orphan-reservation reason case and rollback after the final account audit.
Ruff check and format
passed for API/scripts (546 files), mypy passed for 200 API source files, and diff
whitespace checks passed. Providers were stubbed and databases disposable; the
test container was removed after verification.

Commands use `uv run --locked --extra dev --extra orchestration-test --no-sync`
in the isolated API environment; full API uses `pytest -n 4 -q`. Database runs use
only disposable Postgres port 57670 and per-run databases. The preceding renewal
increment already passed the required migration build/boot smoke; this increment
changes only internal recovery behavior and its tests/docs.

Shared policy/capacity, production heartbeat and watchdog scheduling, bounded
retry/backoff, root deadline transitions, joins and public API/UI remain in the
existing workflow. This increment does not complete W2/W4 or epic #563.
