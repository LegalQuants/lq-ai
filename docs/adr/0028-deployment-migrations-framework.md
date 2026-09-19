# ADR 0028 — Deployment migrations: a state-authoritative, alembic-disciplined framework for stack changes

**Status:** Proposed (2026-09-19; revised the same day after maintainer review) —
for committee decision alongside ADR 0027
**Date:** 2026-09-19
**Owner:** Maintainer team (houfu)
**Origin:** ADR [0027](0027-bundled-object-store-rustfs.md) decision 8. The
MinIO → RustFS swap needs a pre-upgrade snapshot that must not be taken blind, a
detection step that works for an install skipping releases, a loud refusal
instead of the quiet 503 measured in the 2026-09-19 rehearsal, and a
verification against the database — none of which compose YAML can do, and all
of which the desktop launcher must do without the user running a command.

**Relates to:** ADR [0025](0025-release-versioning-and-pipeline-ordering.md)
(a release carrying a pending migration is a minor by definition; decision 2's
launcher image pin becomes a dependency of this ADR), ADR
[0016](0016-transparency-and-governance-invariants.md) (P3 no raw payloads, P4
fail restrictive, P5 atomic audit, P7 human gate), DE-033 (backup and restore
tooling — the snapshot half of it lands here), the desktop launcher playbook,
`alembic` (which covers the schema and nothing else), and PRD §6.5.

## Summary

Alembic already walks the database schema from any release to the latest,
automatically, on every api start. Nothing walks the rest of the stack — the
volumes, the images, the env file, the launcher's stored config — and v0.8.0
is the first release that changes it. This ADR adds a migration tool that
borrows alembic's *discipline* (a linear chain, each step written against the
state the previous one left, frozen code, a recorded walk) but not its
*storage model*, because the trick that makes alembic safe — the version row
lives inside the thing it versions — does not hold for a stack whose pieces
are backed up, restored, pulled and frozen independently. **The stack's state
is authoritative and read from each component; the record of what ran is a
journal, and where the two disagree the tool reports it rather than trusting
either.** The first release ships the tool, an ops volume for the journal and
markers, an init-service gate, the launcher flow, and migration `0001` for the
object store.

## Context

**There are two kinds of migration in this project and tooling for one.**
Alembic moves the database schema: the chain is linear (`0001` → `0066`,
one `down_revision` each), and `api/entrypoint.sh` runs `alembic upgrade head`
before uvicorn, so a schema walk from any release to the latest is automatic.
Everything else an upgrade may need — a volume's ownership or name, an image
swap with an on-disk format change, renamed env keys, a Postgres major-version
bump, a launcher config change — has no mechanism at all.

**The repo's history says the floor is v0.3.0 and the moves so far were quiet
for a reason.** Every tagged release from v0.3.0 to v0.7.1 ships the same
seven named volumes (`pgdata`, `redisdata`, `miniodata`, `ollamadata`,
`gateway-config`, `ingest-hf-cache`, `ingest-easyocr-cache`); v0.1.0 is the
scaffold with no migrations and no users. Each release shipped a known alembic
head, so the schema alone dates an install:

| Release | Alembic head |
|---|---|
| 0.3.x | 0038 |
| 0.4.0 | 0045 |
| 0.4.1, 0.4.2 | 0047 |
| 0.5.x | 0055 |
| 0.6.x | 0065 |
| 0.7.x | 0066 |

Every operator action before 0.8.0 was of one class: *a service refuses to
boot and says why* — the gateway master key in 0.6.0 (#278), the JWT secret,
the gateway key on `/v1` and the https rule in 0.7.0 (#399, #396, #400). Each
is checked from state on every boot, so each is skip-version safe by its
nature, and that is why upgrades looked silent. The RustFS swap is the first
change whose failure mode is a quiet degradation rather than a refusal — the
store stays up, liveness stays green, every S3 call returns 503 (rehearsal
phase 6a) — which is exactly why it cannot ride on that pattern.

**The launcher cannot ask, and is already split across versions.** The macOS
app bundles the release compose file inside the `.dmg`, defaults its image tag
to `latest` (`desktop/src/main/index.ts`; ADR 0025 decision 2 records the pin
as unimplemented), and treats `pull` as best-effort. A launcher install today
therefore runs whatever images are newest against a compose file frozen at
install time, with the schema following the images. Its "version" is not one
number. The launcher also already carries one bespoke migration in code — the
gateway master-key backfill (`ensureMasterKey`, #202, June 2026) — detected by
a regex on the env file, with no record that it ran. That is the shape a
second and third one-off would copy.

**Skip-version upgrades are normal.** Operators on 0.7.x will still exist
when 0.9.0 and 0.10.0 ship; a launcher user on `desktop-v0.5.x` may install
`desktop-v0.9.0` directly. A migration keyed on "the previous release" is
wrong for them.

**Foreseeable migrations, so a framework is not speculative:**

| Migration | Trigger | Component | Needs |
|---|---|---|---|
| `0001` object store MinIO → RustFS | v0.8.0 (ADR 0027) | `miniodata` | snapshot, ownership fix, marker, S3 + DB verification, rollback |
| `0002` rename the `miniodata` volume key | a later 0.x (ADR 0027 DE) | `miniodata` | copy or re-label a named volume, verify, retire the old one |
| Postgres major bump (`pgvector/pgvector:pg16` → pg17) | when pg16 ages out | `pgdata` | dump/restore or `pg_upgrade` across two volumes, verify row counts |
| Public presigned-URL endpoint for exports | ADR 0027 DE | env | key introduction with a detection that the old links are unreachable |
| Launcher config changes | any launcher release | launcher config | versioned config record |

**What the 2026-09-19 rehearsal fixed about the design.** Detection must read
the volume (`.minio.sys/format.json` present, `.rustfs.sys` absent), not a
version string. Readiness must be `/health/ready`, because liveness stays
green on a broken store. Verification can be stronger than a count:
`files.hash_sha256` holds every document's digest, so the tool can prove the
bytes survived. And both stores' format files carry the same deployment id —
RustFS preserves MinIO's through the migration (receipts `minio-format.json`
and the volume's `.rustfs.sys/format.json` show the same `id`) — so a volume
has a stable identity the tool can key a marker on.

## Why alembic's model transfers only in part

Alembic is safe because of one invariant: **the position and the state it
describes are the same physical object.** `alembic_version` lives in the
database it versions, so a restore, a copy or a crash moves both together and
the row can be trusted absolutely. The tool computes the walk from that row,
and each revision is written against the exact state the previous one left.

The stack has no such object. Its state lives in at least five places that
move independently — the schema in `pgdata`, the objects in `miniodata`, the
checkout that holds the compose file, the image tags actually pulled, and the
env file or launcher config — and each can be restored, replaced or frozen
without the others. Concrete skews, all live for this repo today:

| Skew | What a database-held position would do | What must happen instead |
|---|---|---|
| Launcher install: compose frozen in the `.dmg`, images on `latest`, schema following the images | report one version for three positions | read each component |
| Backups restored per volume: `pgdata` from Tuesday, `miniodata` from Monday | say the store migration is *verified* over a volume that is still MinIO, and skip the one step that must not be skipped | read the volume, find MinIO, supersede the stale record and run again |
| The database is the patient: a Postgres major bump migrates the store the record lives in; the init service in front of the object store decides before Postgres is up | be unreadable when it is needed most | keep the record and the markers outside Postgres |
| External S3 install: a schema position, no store to migrate | have nothing to say about the store | read the store, record `0001` as not applicable |
| Volume migrated by hand following upstream's guide: `.rustfs.sys` present, no record | run the migration again, or refuse | read the volume, adopt the state, write a baseline entry |

So the database is one witness for one component. It is the right witness for
the schema — the alembic revision tells the tool where the schema walk stands —
and it cannot speak for the volumes, the checkout, the images or the launcher.

**What does transfer** is alembic's discipline, and the framework keeps all of
it: a linear chain; each migration written against the state the previous one
left; a step that does not apply still advancing the chain; code that never
imports live application models, because a migration written for the 0.8.0
schema will be run from the 0.12.0 image; and a recorded walk with receipts.

## Decision drivers

1. **One implementation for Compose, the launcher and Helm.** No host tooling
   beyond Docker; no second copy in TypeScript.
2. **State is authoritative; the record is a journal.** Every decision the tool
   makes is grounded in what is on disk, in the database or in the env — read
   from the component that owns it. The journal says what ran; it never
   overrides what is there. Disagreement is a finding, not a silent choice.
3. **Alembic's discipline for ordering and code.** Linear chain, post-state
   contract, frozen code, schema anchors.
4. **Transparent.** What ran, when, on what, with what result, is a durable
   record an operator can read (P5), and receipts carry counts, digests, paths
   and durations — never content (P3).
5. **Safe by default.** Dry-run first; refuse when preconditions fail (space,
   a running store, an unknown layout, a state the chain does not recognise)
   rather than guess (P4); irreversible steps behind an explicit confirmation
   (P7) — a dialog in the launcher, a flag on the CLI.
6. **Testable in CI from every supported floor.** A fresh stack must report
   nothing pending; the object-store migration must run end to end against a
   fixture volume from each floor state; the skew cases above are unit tests.
7. **Small footprint, and nothing schema-related required to work.** No new
   image, no new runtime, no alembic revision in the first release.

## The options

### A. A shell script per migration in `scripts/`

Host-side bash calling `docker` and `docker compose`. Simple to write, but it
needs bash and the docker CLI on the host (fine on Linux, awkward on macOS
where the launcher is the whole point), has no record, cannot query the
database without more tooling, and is the hardest shape to unit-test.

### B. A Python tool inside the api image, run as a compose profile service

`app.ops.migrations` in `api/`, launched as
`docker compose --profile ops run --rm migrate <command>`. The service mounts
the object-store volume and a small ops volume, reads the same `.env`, can
reach Postgres, and records to a journal. The launcher runs the identical
command. Helm runs it as a pre-upgrade Job with the PVCs mounted.

### C. Implement in the launcher only, document commands for Compose users

Two implementations of every migration, or Compose users left with prose.

### D. A separate ops image

Clean separation, but one more image to build, sign, mirror for air-gap and
carry in the SBOM, for code that needs exactly the api image's dependencies.

### E. No framework; write `0001` as a one-off

Cheapest today. It leaves the launcher with a bespoke flow that the next
migration cannot reuse, no record, and no answer for skip-version upgrades
beyond "we kept the shims".

### F. Host stack migrations inside alembic revisions

Alembic already has the chain, the position, the walk and the entrypoint.
Rejected because it inherits the wrong invariant: the position would live in
Postgres while the state lives in the volumes (the skew table above), the api
entrypoint cannot stop the store, mount the volume, or ask before a
multi-minute snapshot (P7), and `alembic_version` holds one row with no
receipts.

### G. Option B with a database-held ledger as the authority

The first draft of this ADR: an `ops_migrations` table via a new alembic
revision, `plan` trusting it as the position, a `/ready` field and an admin
endpoint reading it. Rejected for the skew table above — the ledger and the
state are different physical objects, so the ledger can lie — and because the
init service needs the answer before Postgres is up.

## Decision

**Option B, with state as the authority.** Specifically:

### 1. Position is a vector, read from the components

`plan` computes the install's position from witnesses, one per component,
and prints it:

| Component | Witness | Where it lives |
|---|---|---|
| Schema | `alembic_version` | `pgdata` (Postgres's own marker) |
| Object store | format file (`.minio.sys/format.json` or `.rustfs.sys/format.json`: layout and deployment id) plus the tool's marker keyed by that id | the volume, and the ops volume |
| Env / config | presence and value of specific keys | `.env` (Compose), rendered `.env` + config blob (launcher), values (Helm) |
| Launcher config | `configVersion` | the launcher's encrypted config blob |
| Target | the tool's own version (`app.__version__`) and the compose file that mounted it | the checkout, the `.dmg`, the chart |

The launcher config blob is the one place a scalar version is right: the
launcher owns that file exclusively and moves it atomically, so alembic's
invariant holds there and nowhere else.

Postgres already witnesses its own major version (`PG_VERSION` in `pgdata`);
the future Postgres bump reads that, not the journal.

### 2. The chain: alembic's discipline

A module `api/app/ops/migrations/NNNN_slug.py`, registered in a linear order,
exposing:

- `id` (`0001_object_store_minio_to_rustfs`), `title`, `introduced_in`
  (release), `component`, `irreversible: bool`.
- `schema_anchor` — the alembic revision this migration was written against.
  Before running the step, the tool walks `alembic upgrade <anchor>` if the
  schema is behind it, so the migration always sees the schema of its day.
  The api entrypoint's `alembic upgrade head` stays as the fresh-install path
  and the final step of every walk.
- `detect(ctx) -> Applies(facts) | NotApplicable(reason) | Conflict(finding)`
  — reads the component's witness, never a release number. `Applies` carries
  the facts `plan` prints (layout, deployment id, object count, bytes).
  `Conflict` is a disagreement between the witness and the journal, or an
  unrecognised state; it stops `plan` with the finding (P4).
- `preflight(ctx) -> list[Check]` — named checks with pass/fail and a message:
  free space for the snapshot with a margin, the store not running, a
  recognised layout, Postgres reachable when the migration needs it.
- `apply(ctx)` — idempotent steps, each journaled as it completes so an
  interrupted run resumes rather than restarts.
- `verify(ctx) -> Report` — runs after the operator or launcher has brought
  the new state up; writes the receipt and promotes the marker.
- `rollback(ctx)` — restores from the receipt's snapshot where `irreversible`
  is false; otherwise explains what a manual recovery needs.

**Rules, all borrowed from alembic:**

- *Post-state contract.* A migration is written against the state the
  previous one left. Its `apply` may assume the previous `apply` succeeded,
  not that its `verify` ran — so one walk is `apply` all pending, bring the
  stack up, `verify` all.
- *Skipped steps advance the chain.* A `NotApplicable` result is journaled and
  the walk continues; the next migration may rely on it.
- *Frozen code.* A migration never imports `app.models` or `app.storage`. It
  uses raw SQL against the schema at its anchor and a private S3 client, so
  it still runs unchanged from an image five releases later.
- *Migrations are never deleted.* The chain in the image being upgraded to is
  the chain that runs, from whatever position the witnesses report.
- *Old images are not a dependency.* A migration may not require the previous
  release's images to be pullable; the MinIO image is gone and the Postgres
  bump will be written to the same rule.

### 3. The journal and the markers live in an ops volume

A small named volume `lq-ai-ops`, mounted at `/lq-ai/ops` by the `migrate`
service (read-write) and by the object-store init service (read-only):

- `journal.jsonl` — append-only. One entry per phase per migration: id,
  phase (`baseline` · `plan` · `apply` · `verify` · `rollback`), status,
  `started_at`, `finished_at`, actor (`cli` · `launcher` · `helm-job`), tool
  version, the position vector as read at the time, and the receipt (counts,
  byte totals, digests, snapshot path with its size and SHA-256, per-step
  durations). P3-clean by construction.
- `markers/objectstore/<deployment-id>.json` — written by `apply` (state
  `applied`, with the snapshot path) and updated by `verify` (state
  `verified`), removed by `rollback`. The init service's gate reads this
  without Postgres: the marker means "the snapshot exists", which is what the
  gate protects, so either state lets the store start.
- `snapshots/` — the default snapshot destination, overridable with
  `LQ_AI_SNAPSHOT_DIR` for a host path; the launcher binds its app-data
  directory so a large snapshot lands on the Mac's disk, not in the Docker VM.

**Reconciliation, on every `plan`.** The tool reads the journal and every
witness, then reports:

| Witness says | Journal says | `plan` reports |
|---|---|---|
| MinIO layout | nothing | `0001` pending; first run writes a `baseline` entry with the vector |
| MinIO layout, marker `applied` | `0001` applied | "apply done, store not yet started: `up`, then `verify`" |
| MinIO layout, no marker | `0001` verified (same deployment id) | *Conflict:* "volume restored from before the migration; `0001` will run again; the earlier entry is superseded" |
| RustFS layout, no marker | nothing | "migrated outside the tool" — adopt: write `baseline`, run `verify` only |
| RustFS layout, marker present | `0001` verified | nothing pending |
| no store volume (external S3) | anything | `0001` not applicable, journaled |
| alembic revision below 0038 | anything | refuse: below the supported floor (decision 8) |

**Deferred, not dropped:** a read-model copy of the journal in Postgres for
the admin page and for `pg_dump`, and a `/ready` field derived from it. Both
are display concerns; neither is needed for the tool, the gate or the
launcher to be correct, and the first release ships without them.

### 4. The CLI

`python -m app.ops.migrate <command>` inside the `migrate` service; every
command has `--json` for the launcher and a stable exit code:

| Command | Does | Exit |
|---|---|---|
| `plan` | reads witnesses and journal, reconciles, runs `detect` + `preflight` for every migration in chain order; prints the position vector, what would run, why, and the space and time expected | 0 nothing pending · 10 pending · 20 preflight failed · 21 conflict |
| `apply [--yes] [--only ID]` | walks pending migrations in order, schema anchor first; confirms before any `irreversible` step unless `--yes` | 0 · 30 failed (journal says where) |
| `verify [ID]` | post-start verification; writes the receipt and the marker | 0 · 40 failed |
| `status` | the journal, newest first, and the current vector | 0 |
| `rollback ID [--yes]` | restores per the receipt; removes the marker | 0 · 50 |

There is no `stamp` command: the baseline is derived from the witnesses on the
first `plan`, and adopting an outside migration is `plan` → `verify`.

### 5. Where it runs

A compose service `migrate` under `profiles: ["ops"]` (the repo's existing
profile convention): the api image, `env_file: .env`, mounts `miniodata` at
`/lq-ai/volumes/objectstore` and `lq-ai-ops` at `/lq-ai/ops`,
`depends_on: postgres: service_healthy` because `0001` reconciles against
`files`. The api image already runs as root, which the ownership fix and the
tar need; the service listens on nothing and exits when done. It does not
mount the Docker socket: sequencing services is the driver's job (the
operator's four commands, or the launcher), which keeps the api image's
posture unchanged. Helm gets a `Job` template with the same image and mounts,
gated by a values flag because a hook cannot ask.

### 6. Enforcement without the tool

The one-shot init service in front of `rustfs` (ADR 0027 plan item 2) reads
the volume and the ops volume: empty or already migrated with a marker for
its deployment id → fix ownership to uid/gid `10001` and exit 0; `.minio.sys`
present, `.rustfs.sys` absent, no marker → exit 1 with "existing MinIO volume
detected — run `docker compose --profile ops run --rm migrate plan` first".
`rustfs` depends on it with `service_completed_successfully`, so nothing
starts on an unmigrated volume. `LQ_AI_OPS_UNATTENDED=1` bypasses the marker
check, is logged, and is the P7 override for operators with their own backup
discipline. No Postgres is involved in this decision.

### 7. Launcher flow, and two launcher-side requirements

On every start: `plan --json`. Nothing pending → `up` as today. Pending → a
dialog with the migration title, the facts from `plan` (volume size, object
count, snapshot destination and free space), and a single confirmation →
`apply --yes --json` with step progress from the journal → `up` for the store
→ wait on `/health/ready` → `verify --json` → `up` for the rest. A conflict or
any non-zero exit stops the flow with the finding or receipt on screen and
offers `rollback`. The health view shows `status --json`.

The launcher's own config is the one scalar-versioned component: the blob
gains `configVersion`, and launcher-side migrations walk it in order in
TypeScript. The existing master-key backfill becomes `L-0001`, stamped by
state on first run (the key is present or it is not), so nothing changes for
installs that already have it.

**Dependency: the launcher must pin the image tag it shipped against**, as ADR
0025 decision 2 already requires and `desktop/src/main/index.ts` does not yet
do (`imageTag: 'latest'`). A walk needs a known target; an install whose
images float cannot tell which chain it is running. This lands with or before
the launcher flow.

### 8. Supported floor

**v0.3.0** — the first tagged release, the first with today's seven volumes,
alembic head 0038. `plan` refuses below it with a message naming the floor.
Nothing older is known to be running; the committee can raise the floor
(open question 6) but the chain does not need it raised.

### 9. Migration `0001_object_store_minio_to_rustfs`

- `component`: object store. `schema_anchor`: 0066 (`files.hash_sha256` and
  `user_export_jobs.storage_key` exist from well before it; the anchor is the
  schema the verify query was written against). `irreversible`: false.
- `detect`: `.minio.sys/format.json` present with `format: xl-single` (or
  `xl`), `.rustfs.sys` absent → `Applies` with bucket, deployment id, object
  count, byte total. `.rustfs.sys` present → `NotApplicable("already
  RustFS")`, with the adoption path in decision 3 when no marker exists. No
  store volume → `NotApplicable("external S3")`. Any other layout →
  `Conflict`.
- `preflight`: free space ≥ volume bytes × 1.1 at the snapshot destination;
  the store not running; Postgres reachable; the `files` table readable.
- `apply`: tar the volume to `<snapshots>/0001-<deployment-id>-<timestamp>.tar`
  and journal its size and SHA-256; `chown -R 10001:10001`; write the marker
  in state `applied`; journal `applied`.
- `verify`: `/health/ready` 200; HeadBucket 200; object count equals rows in
  `files` including soft-deleted plus `user_export_jobs` rows whose
  `storage_key` is set; read every object (or, above a size threshold, a
  random sample plus every object under 1 MiB) and compare SHA-256 with
  `files.hash_sha256`; promote the marker to `verified`; journal `verified`
  with the counts.
- `rollback`: the store must be stopped; restore the tar into the volume;
  remove `.rustfs.sys`; remove the marker; journal `rolled_back`. Prints the
  instruction to check out the previous release and start it against the
  cached MinIO image.

### 10. Testing

Unit tests for every migration's `detect` and `preflight` against fixture
directories under `api/tests/fixtures/ops/`, and for `plan`'s reconciliation
against every row of the table in decision 3 (each skew is a fixture pair of
volume state and journal). A small committed MinIO fixture volume (a handful
of objects with their `xl.meta`, tens of kilobytes, derived from the
2026-09-19 rehearsal) for `0001`. Schema floors are generated, not stored:
`alembic upgrade 0038` (and 0055, 0066) on an empty database plus a seed of
`files` rows matching the fixture. Stack-smoke gains: `migrate plan` on the
fresh stack must exit 0 with nothing pending; a second boot seeds the fixture
into `miniodata` at the 0.7.x floor and runs `plan → apply → up → verify`; a
nightly or on-demand job runs the same from the 0.3.x floor. That is the
in-place rehearsal executed in CI, which the ADR 0027 exit criteria require.

### 11. Scope of the first release

| Ships in v0.8.0 | Deferred |
|---|---|
| registry, chain rules, `plan`/`apply`/`verify`/`status`/`rollback` | Postgres read-model of the journal; admin endpoint; `/ready` field |
| `lq-ai-ops` volume: journal, markers, default snapshot dir | snapshot pruning policy (open question 2) |
| init-service gate reading the marker | Helm pre-upgrade Job (open question 4) |
| launcher flow + `configVersion` + image-tag pin | launcher-side migrations beyond `L-0001` |
| migration `0001`, fixtures, stack-smoke steps | `0002` volume rename |

## Consequences

**Positive.**
- One migration path for three deployment shapes, with a record an operator
  can read and an auditor can trust — and a record that cannot send the tool
  past a step the disk says is still pending.
- Skip-version upgrades stop being a special case: the chain runs from the
  position the witnesses report, whatever release the install came from.
- The launcher's hardest feature — sequencing an upgrade it cannot ask about
  — becomes a thin driver over the same tool everyone else runs, and its one
  existing bespoke migration gets a home.
- DE-033's snapshot half exists, with receipts.
- Nothing schema-related is required for the first release: no alembic
  revision, no route, no collision-guard edits in `api/tests`.

**Negative / costs.**
- A compose profile service and a new named volume, an entrypoint in the api
  image, a launcher flow with a dialog, the image-tag pin, fixtures, and
  tests. Roughly one to one and a half engineer-weeks for the framework plus
  `0001` plus the launcher flow, against the day the YAML-only path would have
  cost. The earlier draft's estimate was a third higher; the part removed is
  the part that would have been wrong.
- The api image running the migration as root is a pre-existing posture of
  that image, not a new one, but it is now relied on; DE-271 should note it.
- The chain has one link for a while. The framework is sized for that link
  and shaped so the Postgres bump and the volume rename fit without a
  redesign; it claims no more.
- A second place to look for the record (the ops volume) until the Postgres
  read-model lands. `status` is the one command that shows it.

**Neutral.**
- Every release carrying a pending migration is a minor under ADR 0025 rule 3,
  automatically.
- Migrations accumulate in the api image like alembic revisions do; each is a
  few hundred lines and a fixture.

## Alternatives considered (and why not)

- **Host shell scripts (A):** no launcher story, no record, no DB access.
- **Launcher-only (C):** drift between two implementations, Compose users left
  with prose.
- **Separate ops image (D):** SBOM and air-gap cost for no benefit over the
  api image, which already has every dependency the tool needs.
- **One-off script for `0001` (E):** the launcher would still need the flow,
  and `0002` is already on the list.
- **Stack migrations as alembic revisions (F):** wrong invariant, wrong
  process, no receipts.
- **Database-held ledger as the authority (G, the first draft):** it can lie
  after a per-volume restore, it is unreadable when Postgres is the patient,
  and the gate needs the answer before Postgres is up.
- **Per-release runbooks only:** they cannot reach the launcher (the master-key
  backfill exists because of this); they expire with the world (the v0.7.1
  runbook says pull, and the image is gone); their composition across skipped
  releases is never tested; they leave no record; they skip the checks humans
  skip (the measured uid failure is silent); and they multiply across Compose,
  launcher, Helm and external S3 times every from-version. Runbooks survive as
  the rendered output of `plan` for a given install, and for actions outside
  the stack (DNS, TLS, an identity provider).
- **Mounting the Docker socket into `migrate` so one command walks everything:**
  it would let `apply` bring services up and down itself, but it hands the
  api image root on the host. The driver loop (four commands, or the launcher)
  costs nothing and keeps the posture.

## Open questions (for the committee call)

1. **Snapshot destination:** default into the `lq-ai-ops` named volume
   (proposed; survives `down`, invisible to the operator, lives in Docker's
   disk) or require a host path on Compose as the launcher already does.
2. **Retention:** whether `apply` prunes snapshots older than N releases, or
   `status` only reports them and pruning is manual.
3. **Postgres read-model timing:** land the journal mirror and admin page in
   the release after v0.8.0, or when the admin UI first needs it.
4. **Helm scope for v0.8.0:** ship the pre-upgrade Job now, or document `plan`
   as manual for Helm until a chart release needs it (Helm has no data to
   migrate for `0001`).
5. **Names:** `ops` profile, `migrate` service, `lq-ai-ops` volume,
   `app.ops.migrate` module.
6. **Floor:** v0.3.0 as proposed, or v0.4.0 (the first release with notes).
7. **The launcher image-tag pin:** in the ADR 0028 implementation PR, or its
   own PR under ADR 0025 landing first.

## Cross-references

- ADR [0027](0027-bundled-object-store-rustfs.md) — decision 8, upgrade plan
  items 2, 4 and 7, runbook A and B, exit criteria.
- Rehearsal research:
  [`docs/research/2026-09-19-rustfs-dropin-rehearsal.md`](../research/2026-09-19-rustfs-dropin-rehearsal.md)
  (phases 6–7 are the measurements behind the enforcement and readiness
  choices; `minio-format.json` in the receipts is the deployment-id witness).
- ADR [0016](0016-transparency-and-governance-invariants.md) P3, P4, P5, P7;
  ADR [0025](0025-release-versioning-and-pipeline-ordering.md) decisions 2
  and 3.
- `api/entrypoint.sh` and `api/alembic/versions/` (the schema walk this
  framework interleaves with), `api/app/models/file.py` (`hash_sha256`,
  `deleted_at`), `api/app/models/user_export.py` (`storage_key`,
  `expires_at`), `desktop/src/main/store.ts` (`ensureMasterKey`, the existing
  bespoke migration), `desktop/src/main/index.ts` (the `latest` default),
  `desktop/src/main/orchestrator.ts` (best-effort pull), `docker-compose.yml`
  (profile convention), `deploy/helm/lq-ai/`.
- DE-033 (backup and restore tooling), DE-271 (dependency-criticality matrix).
