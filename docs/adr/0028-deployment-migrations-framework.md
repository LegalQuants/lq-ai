# ADR 0028 — Deployment migrations: a journal for stack state, first used by the object-store swap

**Status:** Proposed (2026-09-19; revised 2026-09-20 after maintainer review) —
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
(a release carrying a migration is a minor; decision 2's launcher image pin
becomes a dependency), ADR [0016](0016-transparency-and-governance-invariants.md)
(P3 no raw payloads, P4 fail restrictive, P5 atomic audit, P7 human gate),
DE-033 (backup and restore tooling — the snapshot half lands here), DE-335 (the
web shell's own sqlite), `alembic` (which covers the schema and nothing else),
PRD §6.5.

## Summary

Alembic walks the database schema from any release to the latest, automatically,
on every api start. Nothing walks the rest of the stack, and v0.8.0 is the first
release that changes it. This ADR adds a small migration tool and a **journal in
a named volume** that records what the tool did to stack state. It borrows
alembic's discipline — a linear chain, each step written against the state the
previous one left, frozen code, a recorded walk — but not its storage model,
because alembic is safe only because its version row lives inside the thing it
versions, and stack state is spread across volumes and files that are backed up,
restored and frozen independently. **The state on disk is authoritative; the
journal records what ran; where they disagree the tool reports it rather than
trusting either.** In v0.8.0 the journal tracks one thing, the object-store
volume, for one migration, MinIO → RustFS. The inventory below says what else
holds state, so the next migration knows where it starts.

## Context

### Two kinds of migration, tooling for one

Alembic moves the schema: the chain is linear (`0001` → `0066`) and
`api/entrypoint.sh` runs `alembic upgrade head` before uvicorn. Everything else
an upgrade may need — a volume's ownership or format, an image swap, a config
file's shape, a launcher setting — has no mechanism. Until v0.8.0 none was
needed: every operator action so far (the gateway master key in 0.6.0; the JWT
secret, gateway key and https rule in 0.7.0) is a boot-time refusal that
explains itself, checked from state on every start and therefore safe across
skipped releases. The RustFS swap is the first change whose failure is a quiet
degradation: the store stays up, liveness stays green, every S3 call returns
503 (rehearsal phase 6a).

### Where LQ.AI keeps state outside Postgres

Read from both compose files, the Helm templates and the launcher. "Written at
runtime" means a running install changes it without an operator editing a
file.

| State | Lives in | Written at runtime by | Tracked today | Journal in v0.8.0 |
|---|---|---|---|---|
| Uploaded documents and export bundles | `miniodata` volume | api, on every upload | the store's own format file | **yes** — migration `0001` |
| Gateway configuration (`gateway.yaml`) | `gateway-config` volume; seeded from the example on first boot | gateway, via the runtime tool-provider admin API (`gateway/app/config_writer.py`) | nothing — the file has no version field | no; named as the likely second link |
| Launcher configuration | encrypted config blob plus a chmod-600 `.env` in the app-data directory | launcher (first-run wizard; the master-key backfill in `desktop/src/main/store.ts`) | nothing — one bespoke, unrecorded migration exists | no; the image-tag pin (decision 7) is the first change here |
| Job queue and cache | `redisdata` volume, append-only | arq workers, api cache | n/a — transient by design | no |
| Model caches | `ingest-hf-cache`, `ingest-easyocr-cache`; `ollamadata` on the dev profile | ingest worker; Ollama | n/a — re-downloadable | no |
| Operator environment | `.env` on the host; Helm values | operator | release notes | no; `0001` needs no `.env` edit (ADR 0027 decision 3) |
| The web shell's own database | `webui.db` inside the `web` container — **no volume is mounted** by either compose file or the web Dockerfile | OpenWebUI | nothing; lost on every container recreate | no — nothing durable belongs there (auth is delegated to the api, chats live in Postgres); DE-335 covers the wedge it can cause |
| Schema | `pgdata` | api entrypoint | `alembic_version` | no — alembic's job; the tool reads the revision only to enforce the floor |

The rows marked "written at runtime" but not journaled in v0.8.0 are the reason
this is a framework rather than a script: each is a future stack migration in
exactly this ADR's sense, and each will start from the same inventory.

### The floor is v0.3.0

Every tagged release from v0.3.0 to v0.7.1 ships the same seven named volumes.
Each shipped a known alembic head — 0038 for 0.3.x, 0045 for 0.4.0, 0047 for
0.4.1–0.4.2, 0055 for 0.5.x, 0065 for 0.6.x, 0066 for 0.7.x — so the schema
alone dates an install well enough to refuse below the floor. v0.1.0 is the
scaffold with no migrations and no users.

### The launcher cannot ask, and is already split across versions

The macOS app bundles the release compose file inside the `.dmg`, defaults its
image tag to `latest` (ADR 0025 decision 2 records the pin as unimplemented),
and treats `pull` as best-effort. A launcher install today runs whatever images
are newest against a compose file frozen at install time. Its "version" is not
one number, and any step that is "run this command before `up`" is, for its
users, a step that does not happen.

### What the 2026-09-19 rehearsal fixed about the design

Detection must read the volume (`.minio.sys/format.json` present, `.rustfs.sys`
absent), not a version string. Readiness must be `/health/ready`. Verification
can be stronger than a count: `files.hash_sha256` holds every document's digest.
And both stores' format files carry the same deployment id — RustFS preserves
MinIO's through the migration (receipts `minio-format.json` and the migrated
volume's `.rustfs.sys/format.json` show the same `id`) — so the volume has a
stable identity to key a marker on.

### Why alembic's model transfers only in part

Alembic is safe because **the position and the state it describes are the same
physical object**: `alembic_version` lives in the database it versions, so a
restore moves both together. Stack state has no such object. The first draft of
this ADR held the record in a Postgres table and trusted it as the position;
three cases show why that fails:

| Case | A database-held record would | The tool must instead |
|---|---|---|
| `pgdata` restored from Tuesday, `miniodata` from Monday | say `0001` is verified over a volume that is back on MinIO, and skip it | read the volume, find MinIO, supersede the stale entry, run again |
| The compose gate in front of the store must decide before Postgres is up; a future Postgres bump migrates the store the record lives in | be unreadable when needed most | keep the journal and markers outside Postgres |
| A volume migrated by hand following upstream's guide: `.rustfs.sys` present, no record | run the migration again, or refuse | read the volume, adopt the state, write a baseline entry |

What transfers is the discipline: a linear chain, each migration written against
the state the previous one left, a step that does not apply still advancing the
chain, code that never imports live application models, and a recorded walk
with receipts.

## Decision drivers

1. **One implementation for Compose, the launcher and Helm.** No host tooling
   beyond Docker; no second copy in TypeScript.
2. **State is authoritative; the journal records.** Disagreement is a finding,
   never a silent choice.
3. **Alembic's discipline for ordering and code.**
4. **Transparent.** What ran, when, on what, with what result, is a durable
   record (P5) whose receipts carry counts, digests, paths and durations —
   never content (P3).
5. **Safe by default.** Dry-run first; refuse on a failed precondition or an
   unrecognised state (P4); irreversible steps behind an explicit confirmation
   (P7) — a dialog in the launcher, a flag on the CLI.
6. **Testable in CI.** A fresh stack reports nothing pending; `0001` runs end
   to end against a fixture volume; the three cases above are unit tests.
7. **Sized for one migration, shaped for the next.** No new image, no new
   runtime, no alembic revision, no api route in this release.

## The options

- **A. A shell script per migration in `scripts/`.** Needs bash and the docker
  CLI on the host; no record; cannot query the database; hardest to test.
- **B. A Python tool inside the api image, run as a compose profile service,
  with a journal in a named volume.** The proposal.
- **C. Launcher-only, with commands documented for Compose users.** Two
  implementations, or prose for half the installs.
- **D. A separate ops image.** One more image to build, sign, mirror and carry
  in the SBOM, for code that needs exactly the api image's dependencies.
- **E. No framework; a one-off for `0001`.** The launcher still needs the flow,
  and the inventory above lists the next candidates.
- **F. Stack migrations as alembic revisions.** Wrong invariant (position in
  Postgres, state in the volumes); the api entrypoint cannot stop the store,
  mount the volume or ask before a long snapshot; `alembic_version` holds one
  row and no receipts.
- **G. Option B with a Postgres table as the authority** — the first draft.
  Fails the three cases above.

## Decision

**Option B.** Specifically:

### 1. What the journal tracks

In v0.8.0 the journal tracks **one component: the object-store volume**, and
records for it:

- its identity — the deployment id from the store's format file — and layout
  (`xl-single`, `xl`, or RustFS);
- the position of migration `0001` on it: `pending`, `applied`, `verified`,
  `rolled_back`, or `not applicable` (external S3, or already RustFS when the
  tool first ran);
- for each phase, a receipt: when, by which actor (`cli` · `launcher` ·
  `helm-job`), from which tool version, the snapshot's path, size and SHA-256,
  object and byte counts, the digest comparison result, per-step durations,
  and any error.

It records nothing about the schema (alembic's job), the env file, Redis, the
model caches, the web shell's sqlite, or the launcher's config. Adding a
component later means adding a migration that reads that component's own state
and writes its own marker — the gateway config file and the launcher config are
the two the inventory marks as next.

### 2. The ops volume

A small named volume `lq-ai-ops`, mounted at `/lq-ai/ops` by the `migrate`
service (read-write) and by the object-store init service (read-only):

- `journal.jsonl` — append-only, one entry per phase per migration, in the
  shape above. P3-clean by construction.
- `markers/objectstore/<deployment-id>.json` — written by `apply` (state
  `applied`, with the snapshot path), promoted by `verify`, removed by
  `rollback`. The init service's gate reads this without Postgres; the marker
  means "the snapshot exists", which is what the gate protects, so either
  state lets the store start.
- `snapshots/` — the default snapshot destination, overridable with
  `LQ_AI_SNAPSHOT_DIR` for a host path; the launcher binds its app-data
  directory so a large snapshot lands on the Mac's disk, not in the Docker VM.

**Reconciliation, on every `plan`.** The tool reads the volume, the marker and
the journal, then reports:

| Volume says | Marker / journal say | `plan` reports |
|---|---|---|
| MinIO layout | nothing | `0001` pending; first run writes a `baseline` entry |
| MinIO layout | marker `applied`, journal `applied` | "apply done, store not yet started: `up`, then `verify`" |
| MinIO layout | no marker, journal `verified` for this id | *Conflict:* "volume restored from before the migration; `0001` will run again; the earlier entry is superseded" |
| RustFS layout | no marker | "migrated outside the tool" — adopt: write `baseline`, run `verify` only |
| RustFS layout | marker `verified` | nothing pending |
| no store volume (external S3) | anything | `0001` not applicable, journaled |
| any | alembic revision below 0038 | refuse: below the supported floor |

A read-model of the journal in Postgres, an admin page and a `/ready` field are
**deferred**: display concerns, not needed for the tool, the gate or the
launcher to be correct.

### 3. The chain

A module `api/app/ops/migrations/NNNN_slug.py`, registered in linear order,
exposing `id`, `title`, `introduced_in`, `component`, `irreversible`, and:

- `detect(ctx) -> Applies(facts) | NotApplicable(reason) | Conflict(finding)` —
  reads the component's own state, never a release number.
- `preflight(ctx) -> list[Check]` — named checks with pass/fail and a message.
- `apply(ctx)` — idempotent steps, each journaled as it completes so an
  interrupted run resumes rather than restarts.
- `verify(ctx) -> Report` — runs after the new state is up; writes the receipt
  and promotes the marker.
- `rollback(ctx)` — restores from the receipt's snapshot where `irreversible`
  is false; otherwise explains the manual recovery.

Rules: a migration is written against the state the previous one left, and its
`apply` may assume the previous `apply`, not its `verify` (so one walk is
`apply` all, `up`, `verify` all); a `NotApplicable` result is journaled and the
walk continues; a migration never imports `app.models` or `app.storage` — raw
SQL and a private S3 client, so it runs unchanged from an image five releases
later; migrations are never deleted; a migration may not require the previous
release's images to be pullable. `verify` runs after `up`, when the api has
brought the schema to head, so a migration's SQL must hold across every schema
it can meet; `0001`'s columns (`files.hash_sha256`, `files.deleted_at`,
`user_export_jobs.storage_key`) exist from before the floor.

### 4. The CLI

`python -m app.ops.migrate <command>` inside the `migrate` service; every
command has `--json` for the launcher and a stable exit code:

| Command | Does | Exit |
|---|---|---|
| `plan` | reads the volume, marker and journal, reconciles, runs `detect` + `preflight`; prints what would run, why, the space and time expected | 0 nothing pending · 10 pending · 20 preflight failed · 21 conflict |
| `apply [--yes] [--only ID]` | walks pending migrations in order; confirms before any `irreversible` step unless `--yes` | 0 · 30 failed (journal says where) |
| `verify [ID]` | post-start verification; writes the receipt, promotes the marker | 0 · 40 failed |
| `status` | the journal, newest first | 0 |
| `rollback ID [--yes]` | restores per the receipt; removes the marker | 0 · 50 |

No `stamp` command: the baseline is derived from the volume on the first
`plan`, and adopting an outside migration is `plan` → `verify`.

### 5. Where it runs

A compose service `migrate` under `profiles: ["ops"]`: the api image,
`env_file: .env`, mounts `miniodata` at `/lq-ai/volumes/objectstore` and
`lq-ai-ops` at `/lq-ai/ops`, `depends_on: postgres: service_healthy` because
`0001` reconciles against `files`. The api image already runs as root, which the
ownership fix and the tar need; the service listens on nothing and exits when
done. It does not mount the Docker socket: sequencing services is the driver's
job (the operator's four commands, or the launcher). Helm gets a `Job` with the
same image and mounts, gated by a values flag because a hook cannot ask.

### 6. Enforcement without the tool

The one-shot init service in front of `rustfs` (ADR 0027 plan item 2) reads the
volume and the ops volume: empty, or already migrated with a marker for its
deployment id → fix ownership to uid/gid `10001` and exit 0; `.minio.sys`
present, `.rustfs.sys` absent, no marker → exit 1 with "existing MinIO volume
detected — run `docker compose --profile ops run --rm migrate plan` first".
`rustfs` depends on it with `service_completed_successfully`.
`LQ_AI_OPS_UNATTENDED=1` bypasses the marker check, is logged, and is the P7
override for operators with their own backup discipline.

### 7. Launcher flow, and one launcher-side dependency

On every start: `plan --json`. Nothing pending → `up` as today. Pending → a
dialog with the migration title and the facts from `plan` (volume size, object
count, snapshot destination and free space), one confirmation → `apply --yes
--json` with step progress from the journal → `up` for the store → wait on
`/health/ready` → `verify --json` → `up` for the rest. A conflict or any
non-zero exit stops the flow with the finding or receipt on screen and offers
`rollback`. The health view shows `status --json`.

**The launcher must pin the image tag it shipped against** (ADR 0025 decision
2; `desktop/src/main/index.ts` still defaults to `latest`). A walk needs a known
target. This lands with or before the launcher flow. The launcher's own config
blob is not versioned in this release; the existing master-key backfill stays
as it is.

### 8. Supported floor

**v0.3.0.** `plan` reads `alembic_version` and refuses below 0038 with a message
naming the floor. Nothing older is known to be running.

### 9. Migration `0001_object_store_minio_to_rustfs`

- `component`: object store. `irreversible`: false.
- `detect`: `.minio.sys/format.json` present with `format: xl-single` (or
  `xl`), `.rustfs.sys` absent → `Applies` with bucket, deployment id, object
  count, byte total. `.rustfs.sys` present → `NotApplicable("already RustFS")`,
  with the adoption path in decision 2 when no marker exists. No store volume →
  `NotApplicable("external S3")`. Any other layout → `Conflict`.
- `preflight`: free space ≥ volume bytes × 1.1 at the snapshot destination;
  the store not running; Postgres reachable; the `files` table readable.
- `apply`: tar the volume to `<snapshots>/0001-<deployment-id>-<timestamp>.tar`
  and journal its size and SHA-256; `chown -R 10001:10001`; write the marker
  in state `applied`; journal `applied`.
- `verify`: `/health/ready` 200; HeadBucket 200; object count equals rows in
  `files` including soft-deleted plus `user_export_jobs` rows whose
  `storage_key` is set; read every object (or, above a size threshold, a
  random sample plus every object under 1 MiB) and compare SHA-256 with
  `files.hash_sha256`; promote the marker; journal `verified` with the counts.
- `rollback`: the store must be stopped; restore the tar; remove `.rustfs.sys`;
  remove the marker; journal `rolled_back`. Prints the instruction to check out
  the previous release and start it against the cached MinIO image.

### 10. Testing

Unit tests for `detect` and `preflight` against fixture directories under
`api/tests/fixtures/ops/`, and for `plan`'s reconciliation against every row of
the table in decision 2 (each a fixture pair of volume state and journal). A
small committed MinIO fixture volume (a handful of objects with their
`xl.meta`, tens of kilobytes, from the 2026-09-19 rehearsal). Stack-smoke gains:
`migrate plan` on the fresh stack must exit 0 with nothing pending; a second
boot seeds the fixture into `miniodata`, runs `plan → apply → up → verify`.
That is the in-place rehearsal executed in CI on every compose change, which
the ADR 0027 exit criteria require.

### 11. Not in this release

The Postgres read-model, admin page and `/ready` field; a version field for the
launcher config blob and for `gateway.yaml`; a volume for the web shell's
sqlite (DE-335 decides whether it should have one at all); snapshot pruning;
migration `0002` (the `miniodata` key rename); the Helm Job if open question 3
says so.

## Consequences

**Positive.** One migration path for three deployment shapes, with a record an
operator can read and that cannot walk the tool past a step the disk says is
pending. Skip-version upgrades are not a special case. The launcher's hardest
feature becomes a thin driver over the same tool. DE-033's snapshot half exists,
with receipts. The inventory above is written down for the next migration.

**Negative / costs.** A compose profile service, a new named volume, an
entrypoint in the api image, a launcher flow with a dialog, the image-tag pin,
fixtures and tests — roughly one engineer-week for the framework plus `0001`
plus the launcher flow, against the day the YAML-only path would have cost.
The api image running the migration as root is a pre-existing posture now
relied on; DE-271 should note it. Until the read-model lands, `status` is the
only window onto the journal.

**Neutral.** Every release carrying a pending migration is a minor under ADR
0025 rule 3. The chain has one link for a while; the framework claims no more.

## Alternatives considered

Options A, C, D, E, F and G above, and **per-release runbooks only**: they cannot
reach the launcher (the master-key backfill exists because of this); they
expire with the world (the v0.7.1 runbook says pull, and the image is gone);
their composition across skipped releases is never tested; they leave no
record; they skip the checks humans skip (the measured uid failure is silent);
and they multiply across Compose, launcher, Helm and external S3 times every
from-version. Runbooks survive as the rendered output of `plan` for a given
install, and for actions outside the stack.

## Open questions (for the committee call)

1. **Snapshot destination:** default into the `lq-ai-ops` volume (proposed) or
   require a host path on Compose as the launcher already does.
2. **Retention:** whether `apply` prunes older snapshots, or `status` only
   reports them and pruning is manual.
3. **Helm scope for v0.8.0:** ship the pre-upgrade Job now, or document `plan`
   as manual until a chart release needs it (Helm has no data to migrate).
4. **Names:** `ops` profile, `migrate` service, `lq-ai-ops` volume,
   `app.ops.migrate` module.
5. **Floor:** v0.3.0 as proposed, or v0.4.0 (the first release with notes).
6. **The launcher image-tag pin:** in the ADR 0028 implementation PR, or its
   own PR under ADR 0025 landing first.

## Cross-references

- ADR [0027](0027-bundled-object-store-rustfs.md) — decision 8, upgrade plan
  items 2, 4 and 7, runbook A and B, exit criteria.
- Rehearsal research:
  [`docs/research/2026-09-19-rustfs-dropin-rehearsal.md`](../research/2026-09-19-rustfs-dropin-rehearsal.md)
  (phases 6–7 are the measurements behind the gate and the readiness probe;
  `minio-format.json` in the receipts is the deployment-id witness).
- ADR [0016](0016-transparency-and-governance-invariants.md) P3, P4, P5, P7;
  ADR [0025](0025-release-versioning-and-pipeline-ordering.md) decisions 2
  and 3; DE-335.
- `api/entrypoint.sh`, `api/alembic/versions/`, `api/app/models/file.py`,
  `api/app/models/user_export.py`, `gateway/entrypoint.sh` and
  `gateway/app/config_writer.py` (the gateway config as runtime state),
  `desktop/src/main/store.ts` (`ensureMasterKey`), `desktop/src/main/index.ts`
  (the `latest` default), `docker-compose.yml`, `docker-compose.release.yml`,
  `deploy/helm/lq-ai/`.
- DE-033, DE-271, DE-335.
