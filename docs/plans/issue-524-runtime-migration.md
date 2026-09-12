# LangGraph 1.x runtime migration — issue 524

Prepared locally on 12 September 2026 from main `27c4521`. This is maintenance
evidence for [#524](https://github.com/LegalQuants/lq-ai/issues/524), a prerequisite
of [#563](https://github.com/LegalQuants/lq-ai/issues/563). It does not enable
orchestration, install a Postgres saver, or ratify ADR 0035. Publication remains
held under the owner's ADR-first workflow.

## Change and dependency review

The application now requires `langgraph>=1,<2`. The frozen lock selects:

| Package | Before | After |
|---|---|---|
| langgraph | 0.2.76 | 1.2.11 |
| langchain-core | 0.3.86 | 1.6.3 |
| langchain-protocol | absent | 0.0.19 |
| langgraph-checkpoint | 2.1.2 | 4.2.0 |
| langgraph-prebuilt | absent | 1.1.0 |
| langgraph-sdk | 0.1.74 | 0.4.4 |

These are the only package additions/version changes. The two new transitive
packages are required by the upgraded family; application code does not directly
use their helpers. PyPI metadata for these six exact versions reported MIT
licenses, non-yanked releases and no entries in its vulnerabilities field when
checked. This is not an exhaustive supply-chain audit.

Resolver constraints retain Core >=1.6.3, checkpoint >=4.1.1 and SDK >=0.4.4.
The latter two include the published
[checkpoint JSON fix](https://github.com/langchain-ai/langgraph/security/advisories/GHSA-fjqc-hq36-qh5p)
and [SDK custom-auth resource fix](https://github.com/langchain-ai/langgraph/security/advisories/GHSA-fvww-7h3r-vfhp).
The current executors do not activate checkpointing or SDK custom-auth resources.
Dependabot's obsolete LangGraph-family exclusion is removed.

## Callable compatibility

Upgrading alone reproduced 12 mypy `call-overload` errors at `add_node` across
the playbook, tabular and autonomous executors. Their factory annotations used
`Callable[[State], Awaitable[dict[str, Any]]]`, which loses the named `state`
parameter required by LangGraph 1.x's node protocol.

The shared `AsyncStateNode` protocol preserves that actual callable signature.
Only factory return annotations and imports change. Node bodies, phase order,
guards, retries, delivery and checkpoint configuration remain unchanged. There
are no type ignores or imports of private LangGraph types.

## Validation

Commands run from `api/` in an isolated worktree environment with the frozen
lock and development extras. Database tests used a disposable pgvector/Postgres
16 container; no development database or provider credentials were used.

| Check | Result |
|---|---|
| `uv lock --check` | Passed; 199 packages resolved. |
| `uv run --locked --extra dev --no-sync mypy app` | Passed, 191 source files. |
| Ruff check and format check for API and scripts | Passed; 523 files already formatted. |
| `pytest -q tests/playbooks/test_executor.py tests/autonomous/test_executor_skeleton.py tests/tabular/test_worker.py` | 29 passed; exercises compiled graphs and database-backed execution with stub providers. |
| `pytest -n 4 -q` | 2,662 passed, 1 skipped, 1,756 warnings in 232.58 seconds. |
| `docker build -t lq-ai-524-runtime-api:local api` from repository root | Passed with frozen production dependencies. |
| Full-stack smoke | Passed: all eight services healthy with zero restarts after the 75-second soak; API, gateway and web health probes and docling import passed. |

Full-stack smoke uses a copy of `scripts/stack-smoke.sh` with an isolated
Compose project, image tags and host ports. Build targets, health probes,
dependency import checks and the 75-second stability soak are unchanged.
Its dummy credentials are local test values. The development stack and its
volumes are not used.

The API suite still emits deprecation and test-mark warnings; this maintenance
slice does not clean unrelated tests. LangGraph/Postgres continuation,
competing-worker fencing and multi-step recovery remain separate #563 acceptance
work. Passing existing executors does not establish those properties.
