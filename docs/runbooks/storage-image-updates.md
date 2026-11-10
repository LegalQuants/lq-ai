# Bundled storage image updates

## Verified pins: 2026-10-26

The storage refresh accompanying Dependabot #755 uses these multi-architecture image indexes:

```text
pgvector/pgvector:pg16@sha256:7b822b0aac60967beb1ea5e576b8602c94c300a157d187f385ae3e0da199b90a
rustfs/rustfs:1.0.3@sha256:9ca9559533b537d10482fe923288b676ad08f92a7069d9a17327fbae3cab688b
```

Both Compose recipes and the API CI Postgres service use the pgvector pin. Both Compose recipes
and Helm's `objectStore.image` use the RustFS pin. Helm's pgvector and Redis references retain
the existing tag-only policy documented in `.github/dependabot.yml`.

For **both linux/amd64 and linux/arm64**, registry manifest/config/layer SHA-256 checks and
inspection of `/usr/share/postgresql/16/extension/vector.control` confirmed:

| Compose image index | Packaged pgvector | PostgreSQL package version |
| --- | --- | --- |
| Previous `sha256:ccc6e83d6e35e931dc7c5def2022729d5a6c370318d099181995567ff1fb4d6b` | 0.8.6 | 16.15-1.pgdg12+2 |
| Target `sha256:7b822b0aac60967beb1ea5e576b8602c94c300a157d187f385ae3e0da199b90a` | 0.8.7 | 16.15-1.pgdg12+2 |

The target's build history also names pgvector source tag `v0.8.7`. This is an extension patch
update within PostgreSQL 16. The [0.8.7 changelog](https://github.com/pgvector/pgvector/blob/v0.8.7/CHANGELOG.md)
reports fixes for an IVFFlat index-build buffer overflow and `avg` on an empty result set.
The packaged `vector--0.8.6--0.8.7.sql` contains catalog comments, without table/index rewrites.

## RustFS: preserve the init gate on fresh installs

The exact RustFS target's build history seeds `/data/.rustfs/events` and `/data/.rustfs/audit`,
matching its [1.0.3 Dockerfile](https://github.com/rustfs/rustfs/blob/1.0.3/Dockerfile).
[Docker's default volume copy-up](https://docs.docker.com/engine/storage/volumes/#mounting-a-volume-over-existing-data)
copies those directories to a fresh volume when the RustFS container is **created**, before
the `rustfs-init` dependency runs. The gate then correctly refuses an unrecognised non-empty
volume. Waiting for the init service to finish before starting RustFS does not prevent this.

Both Compose recipes therefore mount `miniodata` at `/data` with `volume.nocopy: true`. The
existing gate still validates migration state and sets uid/gid 10001 ownership. RustFS creates
its directories when it starts. Existing volume contents are preserved. Kubernetes PVC mounts
do not use Docker copy-up, so Helm needs the image pin update only.

This prevents fresh-volume contamination; it does not repair a volume already seeded by a
failed boot. If the gate still reports an unknown non-empty volume, stop and inspect/back it
up before choosing a repair. Do not delete its contents or bypass the gate. Existing MinIO
data still follows the [MinIO-to-RustFS migration runbook](minio-to-rustfs.md).

## pgvector: update the image, and optionally each database's extension

Replacing the image supplies new binaries and SQL files. It **does not** update an existing
database's `pg_extension.extversion`; `CREATE EXTENSION IF NOT EXISTS` also leaves it unchanged.
[Upstream's upgrade instructions](https://github.com/pgvector/pgvector#upgrading) run
`ALTER EXTENSION vector UPDATE` in each database you want to upgrade.

For 0.8.6 to 0.8.7 that extension update is **optional**. The packaged
`vector--0.8.6--0.8.7.sql` only changes catalog comments, and `vector.control` loads the
unversioned `$libdir/vector` library, so the 0.8.7 fixes take effect when Postgres restarts on
the new image whether or not the extension is updated. A database left at 0.8.6 keeps working;
the receipt below shows one doing so. The desktop launcher does not run the update. Run it if
you want `extversion` to match the installed binaries. A later pgvector update whose script
changes functions or operators will need it.

Use a maintenance window, stop application writers, and take a tested Postgres backup and
an object-store backup/snapshot before the storage update. Retain the old image digests.
The commands below use the default Compose recipe; release installations must use
`docker compose -f docker-compose.release.yml` consistently, with their existing project
name and environment file. Adapt user/database selection for any additional databases.

```bash
# With writers stopped and the previous database image still running:
docker compose exec -T postgres sh -c \
  'pg_dump -U "$POSTGRES_USER" "$POSTGRES_DB"' > lq-ai-pre-storage-update.sql

# After installing the updated Compose recipe:
docker compose pull postgres rustfs
docker compose up -d --wait --force-recreate postgres

# Optional for 0.8.7 (see above). Run as the extension owner/superuser, once per
# database using vector.
docker compose exec -T postgres sh -c \
  'psql -X -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB"' <<'SQL'
SELECT extversion FROM pg_extension WHERE extname = 'vector';
SELECT installed_version, default_version
FROM pg_available_extensions WHERE name = 'vector';
ALTER EXTENSION vector UPDATE TO '0.8.7';
SELECT extversion FROM pg_extension WHERE extname = 'vector';
SQL

# Existing MinIO volumes require the migration procedure linked above first.
docker compose up -d --wait --force-recreate rustfs-init rustfs
docker compose up -d --wait
```

Confirm storage health, an existing document download, a new upload/download byte match, and
representative knowledge-base searches. If you ran the extension update, also confirm
`extversion = 0.8.7`. Fresh databases install 0.8.7 by
default. An extension downgrade is not supplied by this update; rollback after changing
extension metadata requires the tested backup/restore procedure with the matching old image.

## Local verification receipt

On 2026-10-26, a disposable linux/arm64 Docker rehearsal passed the following checks. It used
the Compose-rendered RustFS service/mount/dependency configuration, the current repository's
real `app.ops.gate` in a Python 3.12 container, and throwaway credentials. No operator volumes
or application containers were used. Test containers, network, and named volumes were removed.

- Both full Compose recipes rendered successfully; RustFS mounts had `nocopy` enabled.
- pgvector pins matched across Compose and CI; RustFS pins matched across Compose and Helm.
- Creating the RustFS container before running init left the volume empty; init succeeded and
  RustFS 1.0.3 reached ready. S3 bucket creation and put/get returned identical bytes.
- After stopping RustFS and recreating init, the gate recognised its persisted format. RustFS
  became ready again and the same object returned identical bytes.
- A separate control container with default copy-up reproduced the gate's original
  `unrecognised non-empty object-store volume` refusal before RustFS had ever started.
- A database initialised with the old exact pgvector image retained its rows and installed
  extension version 0.8.6 after switching to the target image. The available default was 0.8.7.
- `ALTER EXTENSION vector UPDATE TO '0.8.7'` succeeded; nearest-neighbour results matched,
  the existing HNSW index remained valid, and `EXPLAIN` demonstrated use of that index.
- `CREATE EXTENSION vector` in a fresh database installed 0.8.7.
- The existing `api/tests/test_ops_migrations.py` suite passed: **14 passed**. This includes
  unknown-volume refusal and the MinIO marker/snapshot guards.

This focused rehearsal did not run the complete application build/stack smoke, a Kubernetes
deployment, or linux/amd64 runtime tests. Both image architectures were inspected statically.
The stack-smoke and sealed-install CI checks still need to pass on the pushed branch.
