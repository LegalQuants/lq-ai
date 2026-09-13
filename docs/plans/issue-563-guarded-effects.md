# Issue 563: durable guarded execution

Local implementation, 13 September 2026, under proposed ADR 0035. No public
dispatch, implementation push or ADR ratification is implied.

## Adapter boundary

`api/app/autonomous/orchestration/effects.py` supplies `GuardedEffects`, an internal
adapter for skill inference and selected-file retrieval. Every call obtains a
fresh, fenced execution view from the durable store. Its scope comes from the
approved root or child assignment; callers cannot supply a permission envelope,
another child's task, a handler or a system prompt. Inference uses the system
instructions and supporting files from the same artifact text used for its skill
digest. It does not ask the gateway to resolve a mutable skill slug. Caller input
is bounded JSON in the user message, alongside the stored task; it remains
untrusted data. Root/run correlation stays in application effect identity, not
in additional provider request fields.

A required local `QuoteProvider` returns an explicit Decimal `CostQuote`, with a
pricing version, or `None` to refuse. Explicit zero pricing is valid. The legacy
judge estimator's cold-start fallback and unknown-external-price-as-zero behavior
are never used by this adapter. Fixture inference can use this explicit pricing
interface; the subsequent [direct inference binding](issue-563-inference-bindings.md)
uses the approved operator route and current token rates. Alias/fallback routing
remains closed for orchestration.
The subsequent [authority-source increment](issue-563-source-bindings.md) supplies
exact provider/operation and explicit per-call pricing from fresh gateway config.

The effect identity hashes the approved plan, run, phase, intent, narrowed call
and quote. Reusing an effect key for a different request is refused. The existing
guard still supplies R5 and R6, including current session halt/status/phase and
selected-document checks. At R4, its internal `GuardedEffect` hook obtains the
quote and commits application effect admission. The approved account allocation
is the budget authority for this path; the legacy session cap remains the
authority for unscoped callers.

## Transactions and recovery

1. Resolve the current approved plan and worker view in a short transaction.
   Release control locks before preparing instructions or calling the guard.
2. Run R5, R6 and quoted R4 admission. Admission rechecks current authority and
   the worker fence, reserves budget, and commits its audit/intent atomically.
3. Execute through `guarded_tool_call`. The guard's transaction may contain
   uncommitted audit/local result rows, but holds no orchestration root/account
   control locks across provider I/O.
4. After the effect, acquire the store's settlement locks and recheck the worker
   generation/lease. The receipt, account settlement, session cost/activity and
   final guard audit commit in the **same outcome transaction**. Failed settlement
   or final audit rolls all of them back. The existing standalone
   `complete_effect` method delegates to this same settlement implementation.

A completed receipt can be recovered at an exhausted allocation without another
dispatch, session charge or completion audit. It is still subject to current
authority/fencing checks. Framework checkpoint timing cannot turn this receipt
lookup into an external replay.

On cancellation, timeout, failed outcome persistence or a normalized
`gateway_error`, the adapter rolls back the outcome transaction and attempts a
separate bounded uncertainty transaction. That operation retains the reservation,
fences the worker and refuses subsequent effects; it cannot overwrite a completed
receipt or another generation. A process death between these steps leaves the
durable admitted intent for lease-expiry recovery. Recovery does not require
execution policy to remain enabled. Automatic retry/reconciliation of uncertain
calls is not supplied.

The invocation timeout uses the remaining stored lease. The store's database-time
fence remains authoritative at admission and settlement even if cancellation is
delayed or a provider client ignores it. Recovery cleanup itself is bounded to
five seconds; if unavailable it leaves the reservation for the watchdog.

Regression testing also exposed transaction-start timestamps tying separate audit
events. The shared audit writer now inserts database `clock_timestamp()` values,
preserving the write-time distinction within one commit. No schema migration or
audit-retention behavior changed. Committed test fixtures explicitly delete their
own audit rows before owner deletion, avoiding orphaned audit records in later
admin endpoint tests.

## Evidence and remaining integration

Tests exercise the actual adapter, current policy, filesystem registry, guard and
migrated Postgres with stub providers. They include:

- Completed receipt reuse at an exhausted cap, explicit free/unknown pricing,
  changed request identity, and pinned instructions versus authority-like input.
- Current policy revoked between preparation and admission; root halt committing
  while a provider is blocked, followed by settlement of the admitted call.
- Cancellation, lease timeout, normalized gateway errors, stale-worker completion
  and final-audit failure, with rolled-back session costs and retained reservations.
- Two children overlapping with separate sessions/accounts and no root charge.
- A fresh actual Postgres saver/graph resuming after outcome commit but before
  node checkpoint, with exactly one provider call and one charge.
- A separate Python process exiting abruptly inside the provider stub after
  admission, without Python cleanup; its reservation survives, expired recovery
  marks uncertainty and a subsequent adapter attempt cannot replay the provider.

The checkpoint and process-death cases are integration fixtures, not the final
arq/LangGraph worker topology. They establish the effect boundary without adding
a second continuation cursor. The full autonomous lifecycle, lease renewal/release,
shared capacity, queue wakeups, operator policy distribution and gateway
configuration revision enforcement remain gates. Root planning before approval, visible
orchestrator instructions, child result joining and public endpoints/UI also remain
in their work packages. Scoped authority calls require the subsequently implemented
source binding; missing pricing and required tool anonymization fail closed.

Final validation used locked dev/orchestration-test extras and a disposable
pgvector/Postgres 16 container:

- Full API: `pytest -n 4 -q` — **2,847 passed, one skipped** in 261.98 seconds.
- Ordered autonomous suite followed by audit tests — **822 passed** in 111.58
  seconds, verifying the committed fixtures do not pollute subsequent audit tests.
- Focused adapter tests — **16 passed**, including the selected-file receipt case.
- Ruff check/format, mypy (**198 source files**) and `git diff --check` passed.

The initial full run exposed phase-event timestamp ties and orphaned fixture audit
rows. The timestamp regression was reproduced before the writer fix; cleanup was
corrected in both the store and older W2 probe fixtures. The superseded serial
rerun was stopped after reproducing the remaining probe-fixture failure; the
final full parallel run and ordered regression above passed after both fixes.

No live provider, production database migration or application feature enablement
was used. Subsequent source-binding evidence and its remaining enablement gates
are recorded in the linked increment; the worker lifecycle remains pending.
