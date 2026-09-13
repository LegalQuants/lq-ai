# #563 — One-hour milestone: safe worker handoff

Status: implemented and verified locally. The
original target was approximately 60 minutes of coding, verification and
documentation. ADR ratification and implementation publication remain open.

## Outcome

A worker can relinquish a run at a safe effect boundary. A replacement worker
claims the run immediately and resumes from the existing LangGraph checkpoint,
reuses the committed effect receipt and continues to the next effect. The
previous worker's claim cannot authorize more effects or change their outcomes.

This is a bounded W2/W4 prerequisite for the arq/LangGraph worker integration in
ADR 0035 D4/D5. The store already supplies claims, generations, effect receipts,
expiration recovery and lock ordering. The milestone adds explicit release and extends the existing
fresh-Postgres-checkpoint proof to replacement workers and a second effect.

## Implementation boundary

The internal `OrchestrationStore.release_claim(claim)` operation now:

- Lock using the established owner → project → root → account → effect order,
  with database time for lease validity. Require the exact current worker and
  generation with an unexpired lease.
- Refuse release while an admitted or uncertain effect exists for the account;
  retain its ownership, reservation and receipt unchanged. Existing uncertainty
  recovery remains responsible for abandoned effects.
- At a safe boundary, clear worker/lease fields and advance the generation in
  the same transaction as a counts-and-identifiers-only audit event. Audit
  failure must roll back release.
- Permit ownership cleanup after halt, opt-out, project archival or policy
  revocation; releasing authority must not require permission to execute again.
  Preserve root status, stop reason, approval, budget and receipts.
- Reject a repeated or superseded release as a stale claim. A later claim still
  performs all current approval, policy, resource and deadline checks.

Reuse existing columns and audit mechanisms. Keep this method internal to the
store; production scheduler wiring is a later milestone. The integration fixture
must stop the first graph invocation before releasing its claim. This milestone
fences application effects; it does not claim to fence arbitrary stale LangGraph
checkpoint writes or resolve production worker topology.

## Acceptance demonstration

Use migrated disposable Postgres, the real store/guard, actual Postgres saver and
stubbed provider calls:

1. Worker A completes effect one; its receipt and charge commit, then its graph
   invocation stops before the corresponding node checkpoint is written.
2. A releases its claim. Two replacement claimants race; exactly one succeeds.
3. The winner B opens a fresh saver/graph and resumes the same run. Effect one
   is read from its receipt without a second provider request or charge; a
   distinct effect two runs once and receives its own receipt and charge.
4. A's old claim cannot admit a new effect, settle an effect or release B's lease.

Focused store cases also prove release is refused with an in-flight/uncertain
effect, revoked policy allows cleanup but prevents subsequent execution, and
audit failure preserves ownership. Assert monetary totals and generation changes
in the database, not only mock call counts. Reuse barriers and database timestamps
instead of slow timing sleeps.

## Original time budget

| Time | Work |
| --- | --- |
| 0–10 min | Confirm release invariants, existing locks/audit conventions and fixture reuse. |
| 10–25 min | Implement release and focused transaction/fencing tests. |
| 25–45 min | Extend the actual checkpoint fixture with replacement-worker continuation and receipt reuse; fix findings. |
| 45–55 min | Run focused governance tests, API regression, Ruff, mypy and diff checks. |
| 55–60 min | Record evidence and remaining limitations; save a local signed-off commit. |

Allow roughly 60–75 minutes if regression exposes related failures. Do not add a
second feature to fill spare time. If a new schema or topology decision is needed,
record that concrete dependency rather than quietly expanding the milestone.

## Deliverable and completion rule

One reviewable local commit containing the store operation, regression/integration
tests and updated workflow evidence. Done means the handoff demonstration and
required checks pass. A helper that compiles without the resume proof is incomplete.

Primary implementation files are `api/app/autonomous/orchestration/store.py`,
`api/tests/autonomous/orchestration/test_store.py` and
`api/tests/autonomous/orchestration/test_effects.py` (or a focused handoff test
module if clearer).

Lease renewal and fixed attempt deadlines, shared capacity/policy distribution,
queue wakeups, production checkpoint fencing, root/child lifecycle transitions,
joins, API/UI and the EDGAR identifier limitation remain separate work. LangGraph
continues to own continuation. No feature enablement, push or implementation PR
publication is included; the existing ADR ratification gate remains in force.


## Implementation evidence

The release operation uses the existing fields and increments the generation,
clearing worker and lease atomically with `orchestration.claim_released`.
In addition to pending receipt checks, a nonzero reserved balance alone refuses
release, preventing orphaned reservations from being treated as a safe boundary.

Both root and child fixtures run an actual two-node LangGraph with a Postgres
saver and stub provider. The first invocation stops after the first receipt
commits, closes its saver, and explicitly releases ownership. Exactly one of two
claimants wins. A fresh saver resumes the graph, reuses the first receipt and
runs the second effect once. While the second provider is paused at a barrier,
release by its current worker is refused promptly; the old worker cannot admit,
settle, release ownership or mark the new effect uncertain. Both receipts retain
their original generations, charges total exactly two fixture dollars, and the
child case leaves parent/sibling spending unchanged.

Store tests cover release/admission races, retained uncertainty/reservations,
stale/expired/mismatched claims, waiting-parent and sibling isolation, cleanup
after policy/owner/project/halt changes, preserved consent and audit rollback.
The initial focused run found incorrect test calls to the settlement method and
a privileged-project fixture missing its required tier; both were corrected.
The subsequent complete orchestration suite passed **184 tests** in 9.93 seconds.

Full API regression passed **2,955 tests, one skipped**, in 210.41 seconds.
The final store/effects run passed **64 tests** in 5.08 seconds, including three
cases added after full-suite collection: zero-cost admitted/uncertain effects
still block release, and a claim expiring while waiting for an account lock
cannot release ownership. Ruff check/format, mypy (200 source files) and diff
whitespace checks passed. Tests used a separate disposable database and no live
providers. Production topology, checkpoint-writer fencing and scheduler wakeups
remain unimplemented.
