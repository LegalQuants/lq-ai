# ADR 0028 — Deployment migrations: a versioned, idempotent framework for operator-state changes

**Status:** Proposed (2026-09-19) — for committee decision alongside ADR 0027
**Date:** 2026-09-19
**Owner:** Maintainer team (houfu)
**Origin:** ADR [0027](0027-bundled-object-store-rustfs.md) decision 8. The
MinIO → RustFS swap needs a pre-upgrade snapshot that must not be taken blind, a
detection step that works for an install skipping releases, a loud refusal
instead of the quiet 503 measured in the 2026-09-19 rehearsal, and a
verification against the database — none of which compose YAML can do, and all
of which the desktop launcher must do without the user running a command.

**Relates to:** ADR [0025](0025-release-versioning-and-pipeline-ordering.md)
(a release carrying a pending migration is a minor by definition), ADR
[0016](0016-transparency-and-governance-invariants.md) (P3 no raw payloads, P4
fail restrictive, P5 atomic audit, P7 human gate — the framework's ledger and
gates are built to those), DE-033 (backup and restore tooling — the snapshot
half of it lands here), the desktop launcher playbook, `alembic` (which covers
schema and nothing else), and PRD §6.5.

## Context

**There are two kinds of migration in this project and tooling for one.**
Alembic moves the database schema and runs automatically in the api
entrypoint. Everything else an upgrade may need — a volume's ownership or
name, an image swap with an on-disk format change, renamed env keys, a
Postgres major-version bump, a launcher config schema change — has no
mechanism at all. Until now that was fine: no release since M1 has needed an
operator to touch a volume. v0.8.0 does.

**The launcher cannot ask.** The macOS desktop app renders `.env`, runs
`docker compose pull` and `up`, and watches service health. Its users are
in-house legal teams who chose the launcher precisely so they never run
docker. Any step that is "run this command before `up`" is, for them, a step
that does not happen. The launcher therefore needs the migration logic in code,
and if it exists in the launcher it must be the same code Compose operators
run, or the two will drift.

**Skip-version upgrades are normal.** Operators on 0.7.x will still exist when
0.9.0 and 0.10.0 ship. A migration keyed on "the previous release" is wrong for
them; one keyed on the install's actual state is right for everyone.

**Foreseeable migrations, so a framework is not speculative:**

| Migration | Trigger | Needs |
|---|---|---|
| `0001` object store MinIO → RustFS | v0.8.0 (ADR 0027) | snapshot, ownership fix, marker, S3 + DB verification, rollback |
| `0002` rename the `miniodata` volume key | a later 0.x (ADR 0027 DE) | copy or re-label a named volume, verify, retire the old one |
| Postgres major bump (`pgvector/pgvector:pg16` → pg17) | when pg16 ages out | `pg_dump` / restore or `pg_upgrade` across two volumes, verify row counts |
| Public presigned-URL endpoint for exports | ADR 0027 DE | env key introduction with a detection that the old links are unreachable |
| Launcher config schema changes | any launcher release | versioned config record |

**What the 2026-09-19 rehearsal fixed about the design.** Detection must read
the volume (`.minio.sys/format.json` present, `.rustfs.sys` absent), not a
version string. Readiness must be `/health/ready`, because liveness stays green
on a broken store. Verification can be stronger than a count: `files.hash_sha256`
holds every document's digest, so the tool can prove the bytes survived.

## Decision drivers

1. **One implementation for Compose, the launcher and Helm.** No host tooling
   beyond Docker; no second copy in TypeScript.
2. **Idempotent and state-driven.** `plan` decides from what is on disk and in
   the ledger, never from "what version were you on". Re-running is safe.
3. **Transparent.** What ran, when, on what, with what result, is a durable
   record an operator and the admin UI can read (P5), and the receipts carry
   counts, digests, paths and durations — never content (P3).
4. **Safe by default.** Dry-run first; refuse when preconditions fail (space,
   a running store, an unknown layout) rather than guess (P4); irreversible
   steps behind an explicit confirmation (P7) — a dialog in the launcher, a
   flag on the CLI.
5. **Testable in CI.** A fresh stack must report nothing pending; the
   object-store migration must run end to end against a fixture volume in
   stack-smoke on every compose change.
6. **Small SBOM footprint.** No new image, no new runtime; the api image
   already carries Python, `aioboto3`, SQLAlchemy and the models.

## The options

### A. A shell script per migration in `scripts/`

Host-side bash calling `docker` and `docker compose`. Simple to write, but it
needs bash and the docker CLI on the host (fine on Linux, awkward on macOS
where the launcher is the whole point), has no ledger, cannot query the
database without more tooling, and is the hardest shape to unit-test.

### B. A Python tool inside the api image, run as a compose profile service

`app.ops.migrations` in `api/`, launched as
`docker compose --profile ops run --rm migrate <command>`. The service mounts
the object-store volume and a snapshots location, reads the same `.env`,
depends on Postgres, and records to a ledger table. The launcher runs the
identical command. Helm runs it as a pre-upgrade Job with the PVC mounted.

### C. Implement in the launcher only, document commands for Compose users

Two implementations of every migration, or Compose users left with prose.

### D. A separate ops image

Clean separation, but one more image to build, sign, mirror for air-gap and
carry in the SBOM, for code that needs exactly the api image's dependencies.

### E. No framework; write `0001` as a one-off

Cheapest today. It leaves the launcher with a bespoke flow that the next
migration cannot reuse, no ledger, and no answer for skip-version upgrades
beyond "we kept the shims".

## Decision

**Option B.** Specifically:

### 1. Shape of a migration

A module `api/app/ops/migrations/NNNN_slug.py` registered in order, exposing:

- `id` (`0001_object_store_minio_to_rustfs`), `title`, `introduced_in`
  (release), `irreversible: bool`.
- `applies_when(ctx) -> Finding | None` — detection from live state: mounted
  volume contents, ledger rows, environment. Returns *why* it applies, with
  the facts (layout, object count, bytes) that `plan` prints. Never consults
  a version number.
- `preflight(ctx) -> list[Check]` — each check has a name, pass/fail and a
  message: free space for the snapshot with a margin, the store not running
  (its lock file absent, the S3 endpoint refusing connections), a recognised
  layout, the ledger not already holding a newer state.
- `apply(ctx)` — idempotent steps, each recorded to the ledger as it
  completes so an interrupted run resumes rather than restarts.
- `verify(ctx) -> Report` — runs after the operator (or launcher) has brought
  the new state up; writes the receipt.
- `rollback(ctx)` — restores from the receipt's snapshot where
  `irreversible` is false; otherwise explains what a manual recovery needs.

### 2. The CLI

`python -m app.ops.migrate <command>` inside the `migrate` service; every
command has `--json` for the launcher and a stable exit code:

| Command | Does | Exit |
|---|---|---|
| `plan` | detection + preflight for every registered migration; prints what would run, why, the space and time it expects | 0 nothing pending · 10 pending · 20 preflight failed |
| `apply [--yes] [--only ID]` | runs pending migrations in order; confirms before any `irreversible` step unless `--yes` | 0 · 30 failed (ledger says where) |
| `verify [ID]` | post-start verification; writes the receipt | 0 · 40 failed |
| `status` | the ledger, newest first, with snapshot locations | 0 |
| `rollback ID [--yes]` | restores per the receipt; clears the marker | 0 · 50 |

### 3. The ledger

Table `ops_migrations` via alembic revision 0067: `id` (migration id, PK),
`status` (`planned` · `applied` · `verified` · `failed` · `rolled_back`),
`started_at`, `finished_at`, `release_from`, `release_to` (the api version
strings), `actor` (`cli` · `launcher` · `helm-job`), `receipt jsonb`, `error`.
The receipt holds counts, byte totals, digests, the snapshot path and its size
and SHA-256, per-step durations, and the tool version — P3-clean by
construction. Putting it in Postgres rather than a file means `pg_dump` carries
it, the api can read it, and the admin UI can show it.

**Api surface.** `GET /api/v1/admin/ops/migrations` (admin-only, read-only)
returns the ledger. `/ready` gains `ops_migrations: {ok, applied_unverified: [],
failed: []}` derived from the ledger alone; `ok` is false, and readiness 503,
when a migration is `applied` but never `verified` or is `failed` (P4). The api
does not detect *needed* migrations — detection needs the volume, which the api
does not mount — so `plan` is the tool's job and the launcher runs it on every
start.

### 4. Where it runs

A compose service `migrate` under `profiles: ["ops"]` (the repo's existing
profile convention): the api image, `depends_on: postgres: service_healthy`,
`env_file: .env`, mounts `miniodata` at `/lq-ai/volumes/objectstore` and a
named volume `lq-ai-snapshots` at `/lq-ai/snapshots` (overridable with
`LQ_AI_SNAPSHOT_DIR` for a host path; the launcher binds its app-data
directory). The api image already runs as root, which the ownership fix and
the tar need; the service listens on nothing and exits when done. Helm gets a
`Job` template with the same image and mounts, gated by a values flag because a
hook cannot ask.

### 5. Enforcement without the tool

Compose's one-shot init service in front of `rustfs` (ADR 0027 plan item 2)
checks the volume: empty or already migrated → fix ownership and exit 0;
`.minio.sys` present, `.rustfs.sys` absent, no marker under
`/lq-ai/snapshots/markers/` → exit 1 with "existing MinIO volume detected — run
`docker compose --profile ops run --rm migrate plan` first". `rustfs` depends
on it with `service_completed_successfully`, so nothing starts on an
unmigrated volume. `LQ_AI_OPS_UNATTENDED=1` bypasses the marker check, is
logged, and is the P7 override for operators with their own backup discipline.
The marker is written by `apply` and removed by `rollback`.

### 6. Launcher flow

On every start: `plan --json`. Nothing pending → `up` as today. Pending →
a dialog with the migration title, the facts from `plan` (volume size, object
count, snapshot destination and free space), and a single confirmation →
`apply --yes --json` with step progress from the ledger → `up` for the store →
wait on `/health/ready` → `verify --json` → `up` for the rest. Any non-zero
exit stops the flow with the receipt on screen and offers `rollback`. The
health view lists the ledger. The launcher records its own config schema
version the same way, as a migration whose `apply` rewrites the stored config.

### 7. Migration `0001_object_store_minio_to_rustfs`

- `applies_when`: `.minio.sys/format.json` present with `format: xl-single`
  (or `xl`), `.rustfs.sys` absent, no ledger row in `verified`. Reports
  bucket, object count, byte total. An unknown layout is a preflight failure,
  not a guess.
- `preflight`: free space ≥ volume bytes × 1.1 at the snapshot destination;
  the store not running; Postgres reachable; the `files` table readable.
- `apply`: tar the volume to `<snapshots>/0001-<timestamp>.tar` and record
  its size and SHA-256; `chown -R 10001:10001`; write the marker; ledger →
  `applied`.
- `verify`: `/health/ready` 200; HeadBucket 200; object count equals rows in
  `files` including soft-deleted plus `user_export_jobs` rows whose
  `storage_key` is set; read every object (or, above a size threshold, a
  random sample plus every object under 1 MiB) and compare SHA-256 with
  `files.hash_sha256`; ledger → `verified` with the counts.
- `rollback`: the store must be stopped; restore the tar into the volume;
  remove `.rustfs.sys`; clear the marker; ledger → `rolled_back`. Prints the
  instruction to check out the previous release and start it against the
  cached MinIO image.
- `irreversible`: false.

### 8. Testing

Unit tests for every migration's `applies_when` and `preflight` against
fixture directories under `api/tests/fixtures/ops/`. A small committed MinIO
fixture volume (a handful of objects with their `xl.meta`, tens of kilobytes,
derived from the 2026-09-19 rehearsal) for `0001`. Stack-smoke gains two
steps: `migrate plan` on the fresh stack must exit 0 with nothing pending, and
a second boot seeds the fixture into `miniodata`, runs `plan → apply`, brings
the store up, and runs `verify`. That is the in-place rehearsal executed in CI
on every compose change, which the ADR 0027 exit criteria require.

## Consequences

**Positive.**
- One migration path for three deployment shapes, with a record an operator
  can read and an auditor can trust.
- Skip-version upgrades stop being a special case: detection is by state.
- The launcher's hardest feature — sequencing an upgrade it cannot ask about
  — becomes a thin driver over the same tool everyone else runs.
- DE-033's snapshot half exists, with receipts.

**Negative / costs.**
- A new table and endpoint (db-schema doc, OpenAPI sketch, the route-count
  and `IMPLEMENTED_ROUTES` collision guards in `api/tests`), an entrypoint in
  the api image, a compose profile service, a launcher flow with a dialog, and
  tests. Roughly one and a half to two engineer-weeks for the framework plus
  `0001` plus the launcher flow, against the day the YAML-only path would
  have cost. The difference buys the four things listed in ADR 0027 decision
  8 and every later migration.
- The api image running the migration as root is a pre-existing posture of
  that image, not a new one, but it is now relied on; DE-271 should note it.
- A `/ready` that fails on an unverified migration is a new way for an
  install to be not-ready. That is the point (P4), and the message says
  exactly which command clears it.

**Neutral.**
- Every release carrying a pending migration is a minor under ADR 0025 rule 3,
  automatically.

## Alternatives considered (and why not)

- **Host shell scripts (A):** no launcher story, no ledger, no DB access.
- **Launcher-only (C):** drift between two implementations, Compose users left
  with prose.
- **Separate ops image (D):** SBOM and air-gap cost for no benefit over the
  api image, which already has every dependency the tool needs.
- **One-off script for `0001` (E):** the launcher would still need the flow,
  and `0002` is already on the list.
- **Ledger as a JSON file in the snapshots volume instead of Postgres:**
  simpler, but invisible to the api and the admin UI, absent from `pg_dump`,
  and one more thing to lose with the volume. Kept as the open question below
  in case the committee prefers zero schema impact.

## Open questions (for the committee call)

1. **Ledger location:** Postgres table (proposed) or a JSON ledger in the
   snapshots volume.
2. **Default snapshot destination and retention:** a named volume
   `lq-ai-snapshots` (proposed; survives `down`, invisible to the operator) or
   a required host path; and whether `apply` prunes snapshots older than N
   releases.
3. **Readiness semantics:** should an `applied`-but-unverified migration make
   `/ready` 503 (proposed, P4), or only surface as a warning.
4. **Helm scope for 0.8.0:** ship the pre-upgrade Job now, or document `plan`
   as manual for Helm until a chart release needs it (Helm has no data to
   migrate for `0001`).
5. **Names:** `ops` profile, `migrate` service, `app.ops.migrate` module.

## Cross-references

- ADR [0027](0027-bundled-object-store-rustfs.md) — decision 8, upgrade plan
  items 2, 4 and 7, runbook A and B, exit criteria.
- Rehearsal research:
  [`docs/research/2026-09-19-rustfs-dropin-rehearsal.md`](../research/2026-09-19-rustfs-dropin-rehearsal.md)
  (phases 6–7 are the measurements behind the enforcement and readiness
  choices).
- ADR [0016](0016-transparency-and-governance-invariants.md) P3, P4, P5, P7;
  ADR [0025](0025-release-versioning-and-pipeline-ordering.md) rule 3.
- `api/app/main.py` (`/ready` shape), `api/app/models/file.py`
  (`hash_sha256`, `deleted_at`), `api/app/models/user_export.py`
  (`storage_key`, `expires_at`), `desktop/src/main/orchestrator.ts`,
  `desktop/src/core/types.ts`, `docker-compose.yml` (profile convention),
  `deploy/helm/lq-ai/`.
- DE-033 (backup and restore tooling), DE-271 (dependency-criticality matrix).
