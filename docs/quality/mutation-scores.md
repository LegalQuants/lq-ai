# Mutation testing (DE-229)

> **Status:** scoped Python workflow proposed in PR #434; **no CI baseline recorded**.
> The first valid run after merge establishes the baseline. DE-229 remains partial.

Mutation testing measures whether the selected tests detect small changes in the
selected source modules. It complements coverage; it is not a security certification
or a score for the whole product. The originating configuration and scope proposal
are credited to @SaifAlYounan (PR #434, replacing #381).

## Frozen tooling

Each Python subsystem declares `mutmut==3.6.0` in the opt-in `mutation` dependency
group of its existing `uv.lock`. The normal dev and production installs do not
select this group. Mutation jobs install application, dev and mutation dependencies
together from that same reviewed lock, so the tool cannot silently replace the
application's locked transitive dependencies.

```bash
# From api/ or gateway/, in a disposable test environment:
uv lock --check
uv sync --frozen --extra dev --group mutation
uv run --frozen --extra dev --group mutation mutmut run
uv run --frozen --extra dev --group mutation mutmut results
uv run --frozen --extra dev --group mutation mutmut show <mutant-name>
```

The configuration lives under `[tool.mutmut]` in each `pyproject.toml`.
It selects both the source modules and their covering test suites. mutmut works
in a git-ignored `mutants/` copy; local runs can retain incremental results.
CI starts from a fresh checkout and does not cache mutation results.

## First-wave scope

| Package | Selected modules |
|---|---|
| gateway | `router.py`, `tier_floor.py`, `routing_log.py`, `anonymization/*` |
| api | `security/encryption.py`; citation `normalization`, `extraction`, `verification`, `caselaw`, `judge_prompts`, `authority_content_judge` |

The test selections are explicit in the configuration and repeated in every
valid report. The first API wave selects DB-free suites; it does not cover
authentication/authorization, audit or the DB-backed citation modules.
The original PR reports that seed migrations 0032/0033 resolve the skills
corpus from a repository-relative layout that breaks inside mutmut's copy.
That report must be reproduced before accepting a repair; it is not a verified
fix or a reason to claim those excluded paths are tested.

The first wave excludes pytest tests marked `slow` or `provider`. In particular,
Gateway spaCy integration/round-trip tests need a separately provisioned NLP
model and are not included; the nightly job must not download it implicitly.
The report includes this marker filter as `pytest_args`.

Some gateway integration tests also depend on the repository-root configuration
file and are excluded. Consequently the measured scope includes a subset of
the tests available for the selected modules. No-test outcomes remain visible.

## Execution and failure policy

`.github/workflows/mutation.yml` runs nightly and on manual dispatch. There is
no PR trigger or mutation-score merge gate. Both packages run independently,
with a 90-minute ceiling per job. Measure actual CI time before widening scope;
the author's local smoke timings are not CI cost evidence.

Surviving mutants, missing covering tests and per-mutant timeouts lower the
score but do not fail the job. Tool/setup failures, interrupted or unchecked
mutants, suspicious/crashed outcomes, missing exports and empty measurements
produce an **unavailable** report and a failed job. A failed run never supplies
a release score. Result and diagnostic artifacts are uploaded even on failures
when the runner remains available; a hard cancellation cannot guarantee upload.

The report validator (`scripts/mutation_report.py`) requires complete raw
counts plus evidence that tests were recorded. Its isolated regression tests run
in normal PR CI. Failed measurements are never represented as 0% or 100%.

## Measurement contract

`mutation_score_percent = 100 * killed / (total - skipped)`

Only killed mutants contribute to the numerator. Survived, no-test and timeout
counts remain in the denominator. Preserve all raw categories; explicitly
review any skipped outcomes. A zero denominator is unavailable.

A valid `mutation-score.json` includes the measured commit, source run URL,
timestamp, tool/version, module/test selections, configuration and lockfile
digests, counts and mutation-run duration. Changes in scope, configuration,
dependency tree or tool version start a new comparable series rather than
silently changing the meaning of a trend. DE-229's initial 80% target for
Gateway/Citation is informational, not a claim that the baseline already meets it.

Each `mutation-<package>-<run_id>` artifact retains the report, run log, outcome
list, raw mutation counts and test statistics for 90 days. These are short-term
diagnostics, not the permanent publication endpoint.

## Score history and durable release evidence

| Date (UTC) | Release | Measured commit | API scoped score | Gateway scoped score | Evidence |
|---|---|---|---|---|---|
| — | — | — | No valid CI baseline recorded | — | — |

Only validated CI reports (`status: valid` and `measurement_origin: github-actions`)
enter this table; local validation runs do not establish a published baseline.
At release time preserve both report JSON files, raw counts and outcome lists
under `docs/quality/mutation-baselines/<release>/` in the release PR.
Link those permanent files from the table and release notes, with the source run
URL retained in the report. A report for a different commit must be labeled
as that commit's measurement, not the release commit's. If the tested code,
configuration, dependencies or tool have changed since that measurement,
record “mutation score unavailable” and obtain a fresh run rather than reusing
the older number. See [the release procedure](../BUILD-AND-RELEASE.md).

## Remaining DE-229 work

The full outstanding checklist lives in [PRD DE-229](../PRD.md#de-229--mutation-testing-in-ci-with-per-release-scores-published):
first valid CI baseline and review of runtime, seed-path reproduction/repair,
DB-backed auth/audit/citation coverage, the excluded gateway integration suites,
TypeScript/Stryker, the durable badge/feed publication path, and follow-up tests
for meaningful survivors. Issue #380 closes with the scoped Python first wave;
remaining acceptance is tracked separately in follow-up issue [#718](https://github.com/LegalQuants/lq-ai/issues/718).

A maintainer reviews survivor reports during the existing review block and
turns meaningful gaps into focused test changes. Reassess the nightly schedule
if the reports are not being used. A surviving mutation is a lead to investigate,
not automatically a production bug.
