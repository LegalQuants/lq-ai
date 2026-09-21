# MinIO to RustFS migration runbook

> **Governing decisions:** [ADR 0036](../adr/0036-bundled-object-store-rustfs.md)
> and [ADR 0037](../adr/0037-deployment-migrations-framework.md). Those ADRs
> define the storage replacement and the state-authoritative migration model;
> this runbook is the operator procedure.

Use this runbook when upgrading a bundled, single-drive LQ.AI object store from
MinIO to RustFS. Migration `0001` supports releases from v0.3.0 onward and the
MinIO `xl` / `xl-single` layouts. External, multi-drive, or distributed stores
use the copy path below instead.

## Time, prerequisites, and safety

- Allow about 15 minutes plus snapshot time. Snapshot duration is approximately
  `object-store size ÷ local disk throughput`; `migrate plan` prints the detected
  size, destination, required free space, and checks before changing anything.
- Keep at least 110% of the object-store volume size free at the snapshot
  destination.
- Take a separate `pg_dump` and keep the locally cached MinIO image. The
  migration tool snapshots the object-store volume, but does not back up
  Postgres.
- Never run `docker compose down -v` during this procedure.
- Keep the generated snapshot for at least one release cycle. The tool never
  prunes snapshots automatically.

The application-facing contract remains `S3_ENDPOINT_URL`, `S3_ACCESS_KEY`,
`S3_SECRET_KEY`, `S3_BUCKET`, and `S3_REGION`. The bundled-store variables are:

| Canonical bundled-store variable | Legacy variable accepted as fallback |
|---|---|
| `OBJECT_STORE_ACCESS_KEY` | `MINIO_ROOT_USER` |
| `OBJECT_STORE_SECRET_KEY` | `MINIO_ROOT_PASSWORD` |
| `OBJECT_STORE_API_HOST_PORT` | `MINIO_API_HOST_PORT` |
| `OBJECT_STORE_CONSOLE_HOST_PORT` | `MINIO_CONSOLE_HOST_PORT` |
| `OBJECT_STORE_BIND_ADDR` | `MINIO_BIND_ADDR` |

The legacy variables and the `minio` network alias remain supported through at
least v0.10.0; ADR 0036 currently retains them for the remainder of 0.x. An
existing `.env` therefore does not need to be renamed for this migration. New
installations should use `OBJECT_STORE_SECRET_KEY` and the other
`OBJECT_STORE_*` names. Compose translates them to the image-native `RUSTFS_*`
process variables internally.

## Compose: bundled single-drive store

With the old release still running, save Postgres:

```bash
docker compose exec -T postgres pg_dump -U lq_ai lq_ai > lq-ai-pre-rustfs.sql
```

Stop containers without removing volumes, then install or check out the target
release:

```bash
docker compose down
git checkout v0.8.0
```

Inspect the on-disk format, database floor, snapshot size, free space, and
stopped-store precondition:

```bash
docker compose --profile ops run --rm migrate plan
```

Exit `0` means nothing applies. Exit `10` means the displayed migration is
pending. Do not continue on exit `20` (preflight failure) or `21` (state
conflict).

Apply the snapshot and ownership migration, then start RustFS:

```bash
docker compose --profile ops run --rm migrate apply
docker compose up -d
```

RustFS imports the supported MinIO layout in place. Verify readiness, bucket
access, every expected object key, and document SHA-256 values against
Postgres:

```bash
docker compose --profile ops run --rm migrate verify
docker compose --profile ops run --rm migrate status
```

Open an existing document in the UI after verification. `status` reports the
append-only journal and retained snapshots.

## macOS launcher

Install the new LQ.AI app before upgrading the stack. The new launcher bundles
the RustFS compose definition, pins the matching release images, stores its
migration journal and snapshots under the app-data directory, and drives
`plan → apply → start RustFS → verify → start the remaining services`.

The old app bundles the old MinIO compose file and cannot acquire
`minio/minio:latest` now that the repository is unavailable. Its pull step is
best-effort, so an existing install can continue only while the old MinIO image
or container is still present in Docker's local cache. It fails after a fresh
install, Docker image prune, reset onto a host without that image, or any other
event that requires the image to be pulled again. Pressing Start in the old app
does not install RustFS or run migration `0001`.

In the new app, Start shows the detected object count, byte size, snapshot
destination, and available space before asking for confirmation. A failed phase
stops the launch and leaves a receipt in the Deployment migrations panel. Use
**Restore latest migration snapshot…** only when following the rollback section
below.

## Helm

The old chart supplied `MINIO_*` variables that the API did not read, so its
bundled PVC should normally be empty. Confirm that before treating RustFS as a
fresh store.

If an operator deliberately wired and used the old claim:

1. Take an independent PVC snapshot and `pg_dump`.
2. Scale the old MinIO StatefulSet to zero so the claim is unmounted and the
   stopped-store preflight can pass.
3. Set `migrations.enabled=true` and
   `migrations.objectStoreClaim=<old-claim-name>` for the upgrade.
4. The gated pre-upgrade Job runs the same migration implementation with
   `apply --yes`; enabling it is the explicit confirmation.
5. After RustFS is ready, run `verify` from the target API image and inspect the
   journal before retiring the old release.

## External, multi-drive, and fallback path

An external S3-compatible endpoint needs no bundled-volume migration; migration
`0001` reports not applicable when the mounted bundled volume is empty.

Do not use the in-place path for multi-drive or distributed MinIO. Start RustFS
on a fresh volume, mirror the `lq-ai-files` bucket with `rclone`, point the
`S3_*` contract at the new endpoint, and run `migrate verify` before retiring
the source. Use the same copy path whenever RustFS's import log or verification
does not match this runbook.

## Rollback

Stop the target stack, restore the journalled tar, and return to the prior
release:

```bash
docker compose down
docker compose --profile ops run --rm migrate rollback 0001 --yes
git checkout v0.7.1
docker compose up -d
```

Rollback verifies the snapshot SHA-256, requires the store to be stopped,
restores the MinIO layout, removes the migration marker, and records the action.
The previous release still needs the cached MinIO image because it can no longer
be pulled.

## CLI exit codes

| Command | Success / action-required exits | Failure exit |
|---|---|---|
| `plan` | `0` nothing pending · `10` pending | `20` preflight · `21` conflict |
| `apply` | `0` | `30` |
| `verify` | `0` | `40` |
| `status` | `0` | — |
| `rollback` | `0` | `50` |

All commands accept `--json`. Receipts contain identifiers, counts, paths,
digests, durations, and errors—never document content.
