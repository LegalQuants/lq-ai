# Research — Is RustFS 1.0.0 a drop-in for the MinIO volume LQ.AI installs already have?

**Preserved research, committed to inform ADR [0036](../adr/0036-bundled-object-store-rustfs.md)
(bundled object store: MinIO → RustFS) and the v0.8.0 upgrade guide.**

**Status:** executed 2026-09-17 (API surface) and 2026-09-19 (in-place volume rehearsal),
against canon `8a29c23` (`api/app/storage.py` blob `8791e0c2f95f`, unmodified). Receipts in
[`2026-09-19-rustfs-dropin-receipts/`](2026-09-19-rustfs-dropin-receipts/).

**Question.** ADR 0036 proposes reading each existing install's `miniodata` volume in place
with RustFS rather than copying objects over S3. Two things had to be true for that to be
safe: the api's S3 client must work unchanged against RustFS, and RustFS must read a volume
that MinIO's single-drive mode wrote — including the objects' bytes, ETags and content types
— and keep working after it has written to that volume itself. Neither had been measured in
this repository before; the ADR listed the second as *not verified*.

**Method.** No docs-only inference on the load-bearing question. Everything below was run in
a clean Linux x86_64 sandbox, with real binaries, and driven through the api's own storage
module so the calls are exactly the ones production makes:

| Component | What was used |
|---|---|
| MinIO | `RELEASE.2025-10-15T17-29-55Z` — the last community release, and the build `minio/minio:latest` last resolved to. Built from the archived source at that tag with Go 1.24.7, because the Docker Hub image is gone and the download host is unreachable from the sandbox. Started as `minio server <dir>`, the same single-drive mode both compose files use. |
| RustFS | `rustfs 1.0.0`, the `linux-x86_64-musl` release binary (build stamp 2026-09-16 07:46 UTC). |
| Client | The api's locked `aioboto3 15.5.0` / `botocore 1.40.61`, importing `app.storage` from the repo with `S3_*` settings pointed at whichever store was running. |
| Volume | One directory, first written by MinIO, then reused by RustFS, then by MinIO again, then by RustFS again — never copied or converted by hand. For the ownership phases a copy of it, still root-owned, was served by RustFS running as uid 10001 (`setpriv`), the user the `rustfs/rustfs` image runs as. |
| Data | 45 objects, 21.8 MB, shaped like the real key space (ADR 0005): 41 bare-UUID documents from 12 B to 20 MiB + 3 B across `application/pdf`, DOCX and `text/plain`, one empty object, and two `exports/<user>/<job>.zip` bundles. Every object was written through `stream_upload` / `upload_bytes`, so ETags carry the api's multipart part-count suffix (`-1`, `-3`). |

A manifest recorded each object's SHA-256, size, ETag and content type at seed time; every
later verification listed the bucket, read every object back through `stream_download`,
and compared all four fields.

## Results

| Phase | What ran | Result |
|---|---|---|
| 0 | API surface: `app.storage` against an empty RustFS — bucket bootstrap, multipart upload (3 parts, 1 part, empty body), size-cap abort, streaming download, put, presigned GET, idempotent delete, missing-key error path | all pass; `/health`, `HEAD /health` and the legacy `/minio/health/live` answer 200 |
| 1 | MinIO seeds the volume; baseline verify through MinIO | 45/45 intact; `format.json` says `xl-single`, 45 `xl.meta` files |
| 2 | **RustFS started on that volume, same root credentials.** Startup log, then verify | log: `checking for a legacy storage format` → `Migrated format from MinIO config` → `Migrated compatible server config` → `Migrated bucket metadata: lq-ai-files` → `Migrated IAM config` → `IAM migration complete`. **45/45 intact: bytes, ETag (including the `-3` multipart ETag on the 20 MiB object) and content type.** |
| 2b | Through RustFS: write a 9 MiB two-part object and an export bundle, delete one seeded object, verify | 46/46 intact |
| 3 | **MinIO restarted on the migrated volume** (which now also holds `.rustfs.sys` and two RustFS-written objects) | starts cleanly; **46/46 intact, including the RustFS-written objects** |
| 4 | RustFS started on a pristine copy of the MinIO snapshot with the **wrong secret key**; client configured with that same wrong pair | starts and reports healthy; migration log identical to phase 2 with no decryption error; bucket visible; **all 45 objects readable and byte-identical** with the new pair; the original pair is refused with 403 |
| 5 | Plain RustFS restart on the volume after phases 2–3 | no legacy-format messages (nothing left to migrate); 46/46 intact |
| 6a | **RustFS run as uid 10001**, the image's user, on the root-owned volume — what the container hits on an existing install with no ownership fix | process stays up and **`/health` answers 200**, but the store loops on `FileAccessDenied` writing `.rustfs.sys/pool.bin` (`Pool metadata writes blocked`, `retry after 5 second`); **every S3 call returns 503**; the api sees the bucket as unavailable |
| 6b | Same volume after `chown -R 10001:10001` (what a helper container does), RustFS still as uid 10001 | 46/46 intact; a multipart write, a put and a delete through RustFS verified 47/47 |
| 7 | Probe endpoints in the stuck state vs the healthy state | `/health`, `/health/live`, `/minio/health/live`: **200 in both states**. `/health/ready`, `/minio/health/ready`, `/minio/health/cluster`: **503 `degraded` while stuck, 200 when healthy** |

Disk layout at the end: `.minio.sys/` (88 KB, untouched `format.json`), `.rustfs.sys/`
(216 KB, added by RustFS), `lq-ai-files/` (31 MB, one directory per object, `xl.meta` as
before). RustFS reads and writes MinIO's per-object layout directly; it does not rewrite
existing objects.

## What this establishes, and what it does not

**Established.**

- The api needs no code change: its entire S3 surface, with the checksum defaults of the
  pinned botocore, works against RustFS 1.0.0.
- The in-place read that ADR 0036 proposes as the default path works on exactly the layout
  every LQ.AI install has (`xl-single`), preserving bytes, ETags and content types, and
  RustFS keeps working across its own restarts on that volume.
- **The volume stays MinIO-readable after RustFS has migrated it and written to it.** ADR
  0036 was drafted assuming the migration was one-way; at this scale it was not. The
  snapshot-first rule stays, because upstream does not document reversibility and this is
  one run, but the rollback story is stronger than the ADR assumed.
- Changing the root credentials at the same time does not lose objects. RustFS's IAM
  decryption requirement (rustfs/rustfs#4358) bites only when MinIO had IAM users, policies
  or an encrypted server config worth keeping; LQ.AI installs use the root pair only, and
  the objects themselves are unencrypted. Matching the credentials remains the guide's
  instruction because it is free and removes the only known failure mode.
- **The ownership fix is not in the image, and its absence fails quietly.** The image sets
  `USER rustfs` (uid/gid 10001) and its entrypoint only `chown`s the volume root,
  non-recursively, when `RUSTFS_UID`/`RUSTFS_GID` are set — which an unprivileged
  process cannot do to root-owned data anyway. RustFS's own `docker-compose-simple.yml`
  ships a separate `volume-permission-helper` container running `chown -R 10001:10001`.
  Run as uid 10001 on the root-owned MinIO volume, RustFS stays up, answers 200 on
  `/health`, and returns 503 to every S3 call. A recursive chown fixes it completely. The
  compose init service in ADR 0036's upgrade plan is therefore load-bearing, not
  belt-and-braces.
- **Readiness must be probed on `/health/ready`.** `/health`, `/health/live` and the legacy
  `/minio/health/live` are liveness probes and stayed green through the stuck state above;
  `/health/ready` (and the legacy `/minio/health/ready`) returned 503 `degraded`. The
  compose healthcheck, the Helm readiness probe and the upgrade guide's "store is up" check
  must use the ready path, or a broken volume looks healthy to everything except the api.

**Not established — and still on the ADR's rehearsal list before the v0.8.0 tag.**

- A *real* `miniodata` volume: this one is synthetic (45 objects, 31 MB, single bucket, no
  versioning, no lifecycle rules, no SSE). A production volume with months of soft-deleted
  files and export bundles is the rehearsal that matters.
- The ownership mismatch through the actual images. Phases 6–7 reproduced it with the
  binary dropped to uid 10001 via `setpriv`, which is the same kernel check the container
  hits; what was not run is Docker itself mounting an existing named volume into the
  `rustfs/rustfs` image (Docker does not chown a non-empty existing volume, so the outcome
  should match 6a, but that is documented behaviour rather than a measurement here).
- The arm64 image on Apple Silicon (desktop launcher).
- Whether rustfs/rustfs#7652 (migration errors must block readiness) is inside the `1.0.0`
  tag. Nothing failed here, so the fix was never needed; the guide's log check stands.
- MinIO built from source is not the official image byte-for-byte, but the on-disk format is
  a property of the tagged source, which is what was built.

## Receipts

- [`dropin_rehearsal.py`](2026-09-19-rustfs-dropin-receipts/dropin_rehearsal.py) — seed /
  verify / mutate driver over `app.storage` (throwaway; not project code).
- [`s3_surface_check.py`](2026-09-19-rustfs-dropin-receipts/s3_surface_check.py) — phase 0
  API-surface check.
- [`stores.sh`](2026-09-19-rustfs-dropin-receipts/stores.sh) — how each store was started
  (ports, env, credentials) and stopped.
- [`final-manifest.json`](2026-09-19-rustfs-dropin-receipts/final-manifest.json) — the 46
  objects with SHA-256, size, ETag and content type as verified in phases 3 and 5.
- [`minio-format.json`](2026-09-19-rustfs-dropin-receipts/minio-format.json) — MinIO's
  `.minio.sys/format.json` (`xl-single`).
- [`phase6-ownership-mismatch.sh`](2026-09-19-rustfs-dropin-receipts/phase6-ownership-mismatch.sh)
  and [`phase7-probe-endpoints.sh`](2026-09-19-rustfs-dropin-receipts/phase7-probe-endpoints.sh)
  — the uid-10001 runs (via `setpriv`) before and after the chown, and the probe
  comparison; results in
  [`phase7-probe-endpoints-stuck-vs-healthy.txt`](2026-09-19-rustfs-dropin-receipts/phase7-probe-endpoints-stuck-vs-healthy.txt).
- Log excerpts: RustFS phases 2, 4, 5, 6a and 6b (migration, warning and error lines only;
  the full JSON logs carry multi-kilobyte option dumps per line and were not kept), MinIO
  phases 1 and 3 in full.

Re-running it needs: the two binaries, the api checkout, a venv with the api's locked
`aioboto3`, and `source stores.sh` from the receipts directory.
