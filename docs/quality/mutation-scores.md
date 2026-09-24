# Mutation testing (DE-229)

> **Status:** nightly runs configured; **no baseline recorded yet** — the first
> nightly run of `.github/workflows/mutation.yml` populates the score table below.

Mutation testing answers the criticism that coverage percentages can be gamed:
it makes small changes ("mutants") to the source — flipping a comparison,
deleting a call, changing a constant — and re-runs the tests that cover the
mutated function. A test suite that catches real defects *kills* the mutant
(some test fails); a suite that merely executes lines lets it *survive*. The
mutation score is the proportion of mutants killed (PRD §5.8 / DE-229).

## Tooling and configuration

- **Tool:** [mutmut](https://github.com/boxed/mutmut) (BSD-3-Clause), pinned to
  **3.6.0** in the workflow. Chosen over cosmic-ray per the DE-229 survey —
  cosmic-ray's distributed-execution machinery is unjustified at this scale.
- **Configuration:** the `[tool.mutmut]` section of
  [`api/pyproject.toml`](../../api/pyproject.toml) and
  [`gateway/pyproject.toml`](../../gateway/pyproject.toml). mutmut 3.x reads
  `source_paths`, the `only_mutate` allowlist, and the pytest test-selection
  arguments from there.
- **Where it runs:** [`mutation.yml`](../../.github/workflows/mutation.yml) —
  nightly cron + manual dispatch. **Never a PR gate**: full runs are too slow
  for PR latency, and absolute score thresholds flake with unrelated refactors.
  Surviving mutants do **not** fail the job; the job fails only on tool errors
  (broken config, clean tests failing, stats collection failing).
- mutmut is intentionally **not** in either package's dev extras — it would add
  its dependency tree (libcst, textual, rich) to every PR's CI install for a
  tool only the nightly workflow and occasional local runs use. Install it
  ad hoc (see "Running locally").

**Score definition:** `killed / (total − skipped)`. Mutants with **no covering
test** count *against* the score — untested critical code is a real gap, not a
denominator adjustment. The raw counts (killed / survived / no-test / timeout /
suspicious) are preserved in every run artifact so the score can be recomputed
under any other definition.

## The allowlist and its rationale

Mutating a whole package against a 237-file suite is an hours-to-days run for
little marginal signal. Scope is instead a named critical-module allowlist —
the code that enforces security policy or produces the artifacts the product's
trust story rests on:

### gateway (`gateway/pyproject.toml`)

| Modules | Why |
|---|---|
| `app/router.py`, `app/tier_floor.py` | Tier-Derivation + routing policy enforcement (PRD §3.13, §4.4) — the fail-closed security decisions. |
| `app/routing_log.py` | The per-request audit choke point (PRD §1.5.2). |
| `app/anonymization/**` | The Anonymization Layer (PRD §4.7), including the custom legal recognizers. |

Covering suites: `tests/test_tier_floor.py`, `tests/test_router.py`,
`tests/test_route_tool_call.py`, `tests/test_routing_log.py`,
`tests/anonymization/`.

### api (`api/pyproject.toml`)

| Modules | Why |
|---|---|
| `app/security/encryption.py` | Fernet encryption for provider keys / MCP tokens (ADR 0011). |
| `app/citation/{normalization,extraction,verification,caselaw,judge_prompts,authority_content_judge}.py` | The Citation Engine's deterministic core (PRD §3.3) — the exact/tolerant/ensemble verification cascade and its inputs. |

Covering suites: the DB-free files under `tests/citation/` plus
`tests/test_encryption.py` and `tests/test_mcp_encryption.py` (enumerated in
`[tool.mutmut] pytest_add_cli_args_test_selection`).

### Known scope limitations (honest state)

- **api DB-backed modules are out of the first wave** — `app/audit.py`,
  `app/security/{passwords,jwt,totp}.py`, and the DB-tested citation modules
  (`treatment*`, `cost.py`, `ledger.py`, `authority.py`). Cause: mutmut
  executes tests from a `mutants/` sandbox copy of the package, and the
  Alembic seed migrations `0032`/`0033` resolve the built-in playbook YAML at
  *four parents above the migration file* (`<repo>/skills/…`). Inside the
  sandbox that path resolves to `api/skills/…`, which doesn't exist, so any
  Postgres-backed suite fails at session setup (verified locally 2026-07-25).
  Bringing these modules in requires either making those migrations
  layout-independent or teaching the conftest a skills-path override —
  a candidate deferred enhancement, not a quiet hack in this change.
- **The gateway config-integration suites are excluded from mutmut's test
  selection** (e.g. `tests/test_inference_tier_floor.py`) because they resolve
  `gateway.yaml.example` via the repo root, which the sandbox layout breaks.
  The mutants those suites would additionally kill show up as `survived` or
  `no_tests` instead — the score is therefore a *floor*, not a ceiling.
- **No per-PR diff-based gate.** The survey pattern ("zero surviving mutants in
  changed lines") was evaluated and **scoped out** for mutmut 3.x: unlike the
  2.x line, 3.x has no supported line- or diff-based mutant selection — scoping
  is by module allowlist in config or by *dotted function-name* patterns on the
  CLI. A PR gate would need a hand-rolled `git diff` → function-name mapper,
  and the sandbox requirement that every selected suite passes cleanly makes
  PR-time behavior depend on which suites a PR touches. That is exactly the
  flaky-gate failure mode the survey warned against, so the PR half of DE-229
  is deferred until the tooling supports it robustly.
- **web/ (Stryker) is deferred.** The OpenWebUI fork carries a large inherited
  TypeScript-error backlog (9,362 errors at capture, tracked in
  `docs/SVELTE-CHECK-BACKLOG.md`); mutation testing on top of that gives noise,
  not signal. Revisit once the backlog burn-down reaches the LQ.AI-owned code.
- **No README badge yet.** DE-229's acceptance criteria include a score badge;
  that needs a stable published score endpoint, which needs a recorded
  baseline first. Sequence: first nightly → record scores here → badge.

## Where scores land

Each nightly run uploads, per package, a `mutation-<package>-<run_id>`
artifact (90-day retention) containing:

- `mutation-score.json` — score + raw counts + commit + timestamp,
- `mutation-survivors.txt` — the surviving-mutant list (`mutmut results`),
- `mutants/mutmut-cicd-stats.json` — mutmut's raw CI/CD stats.

The score also renders in the run's step summary. At release time the release
runner records the latest nightly scores in the table below and in the release
notes — the step is part of [`docs/BUILD-AND-RELEASE.md`](../BUILD-AND-RELEASE.md).

## Score history

| Date (UTC) | Release | Commit | api score | gateway score | Source |
|---|---|---|---|---|---|
| — | — | — | *no baseline recorded yet — the first nightly run populates this row* | — | — |

Scores in this table come **only** from CI nightly-run artifacts. Do not enter
hand-run numbers here.

### Local validation evidence (2026-07-25 — smoke only, NOT a baseline)

Recorded from the pre-merge validation of this configuration on a developer
machine (Apple Silicon, macOS). These prove the config works end-to-end; they
are not comparable to CI-runner numbers and are not the recorded baseline.

- **gateway smoke** (`mutmut run "app.tier_floor*"`): 43 mutants in
  `app/tier_floor.py` — 39 killed, 4 survived; ~6 s wall including mutant
  generation for the full allowlist (1,043 mutants generated).
- **api smoke** (`mutmut run "app.citation.normalization*"`): 29 mutants in
  `app/citation/normalization.py` — 28 killed, 1 survived; ~3 s wall
  (1,107 mutants generated across the allowlist).
- **Full-allowlist local runs** (same day, same machine): gateway
  542 killed / 307 survived / 194 no-test of 1,043 (~15 s wall); api
  571 killed / 178 survived / 358 no-test of 1,107 (~7 s wall). The high
  no-test counts are the excluded-suite effect described above.

## Running locally

From `api/` or `gateway/` (the package venv must have the dev extras):

```bash
pip install mutmut==3.6.0     # or: uv pip install --python .venv/bin/python mutmut==3.6.0

mutmut run                    # full allowlist for this package (fast — seconds locally)
mutmut run "app.tier_floor*"  # restrict to one module's mutants (dotted-name pattern)

mutmut results                # list surviving mutants
mutmut show <mutant-name>     # diff of one mutant — what change survived
mutmut browse                 # interactive TUI
mutmut export-cicd-stats      # write mutants/mutmut-cicd-stats.json
```

Notes:

- mutmut works in a `mutants/` copy of the package (git-ignored). `rm -rf
  mutants` for a from-scratch run; leaving it in place makes reruns
  incremental.
- No `DATABASE_URL` is needed — the configured test selections are DB-free by
  design (see scope limitations).
- A surviving mutant is a *lead*, not automatically a bug: kill it by adding
  the missing assertion, or conclude the mutation is semantically neutral
  (e.g. logging detail) and leave it documented in the nightly survivor list.
