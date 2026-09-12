# Postgres continuation integration probe — W2

13 September 2026. This extends the SQLite research with real application
integration evidence. It does **not** complete W2's production acceptance gate.
The tests characterize both supported continuation and unsafe integration
windows that W3/W4 must close before orchestration can run.

## Tested configuration

- LangGraph 1.2.11 / checkpoint 4.2.0 from the verified #524 runtime commit.
- Optional `orchestration-test` extra: Postgres saver 3.1.2, Psycopg 3.3.5,
  Psycopg binary 3.3.5 and pool 3.3.1. These are the only four additions to the
  lock; no existing version changes. This extra is not installed in production.
- Disposable pgvector/Postgres 16 database, with real application Alembic
  migrations and committed `AutonomousSession` and audit rows.
- `AsyncPostgresSaver.from_conn_string`: a fresh connection/saver for each
  reconstructed graph, autocommit and dictionary rows as configured by the
  library. Saver `setup()` runs only in the disposable test database.
- Synchronous graph checkpoint durability. Explicit restricted JSON/MessagePack
  allowlists, no pickle fallback. State contains fixture IDs and bounded step
  metadata. Remote framework tracing is disabled.
- Real `guarded_tool_call`, estimator, phase map and audit writes. Only the
  gateway/provider response is stubbed. Every effect has its own SQLAlchemy
  session; concurrent children never share one.

The [saver's official metadata](https://pypi.org/project/langgraph-checkpoint-postgres/3.1.2/)
reports MIT licensing. The exact Psycopg packages report LGPL-3.0-only. Their
official PyPI metadata had no listed vulnerabilities or yanked files at review;
this is not a complete supply-chain audit. Psycopg 3 is required by this saver;
the existing Psycopg 2 migration driver remains in place. Production adoption
must review the resulting distribution and operational configuration separately.

## What the tests establish

| Probe | Observed result | Consequence |
|---|---|---|
| Interrupt, close connection, reconstruct graph/saver, resume | No provider call before resume; two distinct guarded effects complete afterward. | Real Postgres continuation supports releasing the invocation during an interrupt. This is a framework interrupt, not durable LQ approval. |
| Two multi-step children dispatched through LangGraph `Send` | An async barrier inside both first provider calls proves overlap; both effects complete for both children with independent DB sessions. Empty responses are successful. | A coordinator invocation can drive this bounded batch. No distributed worker/capacity conclusion follows from this fixture. |
| Halt requested in a separate committed transaction during the interrupt | The real R5 guard stops resumed work, persists its halt latch/audit, and makes no provider call. | Checkpoint state need not override current LQ halt state. Repeated resume, root-wide halt and every other authority state still need admission checks. |
| Crash after the second effect's LQ commit but before its checkpoint | Step one runs once; step two reaches the provider twice on naive resume. Three success audit rows confirm the replay. | A successful application commit and synchronous graph checkpoint are not atomic. Durable effect identity/outcome must suppress repeat dispatch. |
| Node cancellation after the second request may have reached the provider | The uncommitted second intent audit disappears; naive resume sends the second request again. | Commit admission/intent and reservation before I/O. Persist or derive an explicit uncertain outcome and prohibit automatic replay. LangGraph 1.2.11 converts node-raised cancellation into `NodeCancelledError`, so the run fails explicitly. |
| Two independent savers/graphs use the same thread ID concurrently | Both workers cross the real guard and reach the first provider call. | A saver is not a worker claim. LQ needs atomic ownership/fencing before graph invocation and each effect admission. |

The last three probes deliberately assert the unsafe behavior of **naive wiring**.
They are diagnostic evidence, not desired production behavior or a passing
orchestration safety gate. Keep separate production regression tests requiring
one admitted effect, fenced ownership and explicit uncertainty when W3/W4 land.

## Acceptance still open

The result supports continuing with LangGraph; it does not justify reopening
the backend choice. These failure windows are precisely the application-owned
governance boundaries required by ADR 0035 D4–D6.

Before W2 can close, implement and test:

1. Durable approved plan/admission records, a unique dispatch/effect identity and
   outcomes that survive the application-commit/checkpoint gap. Revalidate current
   plan revision and permissions before each admission.
2. Atomic, fenced ownership and short control transactions. Retain outstanding
   reservations for uncertain effects. The existing guard still wraps its audit
   and effect work in the caller's transaction; this probe deliberately does not
   change that production contract.
3. Multi-worker restart tests with the production adapter, including stale owner
   completion, root halt/revocation, crash-before-enqueue and completion-before-
   wakeup. Fresh graph objects here do not simulate an OS process death.
4. Final worker topology, shared deployment/user capacity, per-attempt deadlines,
   actual PostgreSQL saver deployment/migrations, tracing and checkpoint retention.
   The current fixture runs children inside one coordinator invocation; it does
   not adopt that topology or make one-process semaphores deployment limits.

No second graph cursor, application checkpoint tables, production saver, routes,
or worker scheduling changes are introduced by this probe.

## Reproduce

From `api/`, set `DATABASE_URL` to a disposable pgvector/Postgres instance only:

```sh
uv sync --locked --extra dev --extra orchestration-test
LANGSMITH_TRACING=false LANGCHAIN_TRACING_V2=false \
  uv run --locked --extra dev --extra orchestration-test --no-sync \
  pytest -q tests/autonomous/test_orchestration_postgres_probe.py \
  tests/autonomous/test_orchestration_contracts.py
```

Result: 102 passed (96 contract tests and six Postgres probes). Without the
optional extra or disposable database, the probe is skipped; a skipped run is
not acceptance evidence. The original five probes passed independently before
the cancellation probe was added. Its first run identified the runtime's
`NodeCancelledError` wrapper; the corrected expected exception passed.

Ruff check/format and lock consistency passed. The default production dependency
export was checked and contains none of the four optional probe packages. The
API mypy result remains the W1 run (193 files); W2 adds no application module.
