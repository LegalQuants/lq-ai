# ADR 0036 — Bundled object store: replace archived MinIO with RustFS; keep the api S3-generic

**Status:** Accepted (2026-09-20) — committee-ratified at the weekly call
**Date:** 2026-09-17 · **Decision date:** 2026-09-20
**Owner:** Maintainer team (houfu)
**Origin:** Issue [LegalQuants/lq-ai#572](https://github.com/LegalQuants/lq-ai/issues/572)
*"Replace archived MinIO with a maintained S3-compatible backend"* (2026-09-13),
reframed as this ADR's tracking issue. Grounded in two executed runs: on
2026-09-17 the api's real storage module (`api/app/storage.py`, unmodified) driven
against a RustFS 1.0.0 binary with the api's pinned `aioboto3` / `botocore`
versions; on 2026-09-19 an in-place rehearsal in which RustFS 1.0.0 took over a
volume written by MinIO `RELEASE.2025-10-15`, preserved with receipts in
[`docs/research/2026-09-19-rustfs-dropin-rehearsal.md`](../research/2026-09-19-rustfs-dropin-rehearsal.md).
Both are summarised under *Evidence* below.

**Relates to:** ADR [0005](0005-file-storage-soft-delete-and-key-scheme.md) (the
object-key scheme; written in MinIO vocabulary), ADR
[0025](0025-release-versioning-and-pipeline-ordering.md) (this change requires
operator action, so the release that carries it is a **minor** bump), PRD §2.1
(reference architecture), §2.4 (deployment topology), §6.5 (backup recipe names
MinIO), Appendix B (license matrix), DE-033 (backup tooling), DE-271
(dependency-criticality matrix — the bundled store gets a row), and issues
[#301](https://github.com/LegalQuants/lq-ai/issues/301) (digest-pin images; docker
Dependabot ecosystem) and [#303](https://github.com/LegalQuants/lq-ai/issues/303)
(stack-smoke ingest round-trip — the natural home for a storage conformance check).

## Context

**The bundled object store can no longer be pulled.** LQ.AI ships MinIO as the
reference object store in both compose files, the Helm chart, and the macOS desktop
launcher. MinIO Community Edition entered maintenance mode in December 2025, the
upstream repository was archived in 2026, and in September 2026 the `minio/minio`
namespace disappeared from Docker Hub. This is not hypothetical for this repo:

- The stack-smoke job on `main` failed on **2026-09-15**
  ([run 34919920153](https://github.com/houfu/lq-ai/actions/runs/34919920153))
  at image pull: `pull access denied for minio/minio, repository does not exist`.
  The previous run on 2026-08-25 had passed.
- Direct registry probes on 2026-09-17 confirm it: the Docker Hub API answers 404
  for `minio/minio`, and an anonymous pull token gets the same 401 for the pinned
  digest that it gets for a repository that never existed.

Every fresh install from `docker-compose.yml`, `docker-compose.release.yml`, or the
Helm chart is therefore broken today. Existing installs keep running on their
cached image, but cannot re-pull it and get no upstream fixes.

**What LQ.AI actually needs from the store is small and generic.** The api talks
to object storage only through `api/app/storage.py`, an `aioboto3` client with
path-style addressing. The complete surface is: HeadBucket / CreateBucket on
startup (`ensure_bucket`, which auto-creates the bucket on an empty store),
multipart upload with 8 MiB parts and a trailing partial part (plus an explicit
zero-length part for an empty body), AbortMultipartUpload on the size-cap path,
GetObject streaming, DeleteObject, PutObject, and a presigned GET for the
per-user export bundle. Object keys are the bare file UUID (ADR 0005) and
`exports/<user_id>/<job_id>.zip`. Only the root credential pair is used —
there are no IAM users, policies, lifecycle rules, or bucket notifications to
carry over. Nothing else in `api/`, `gateway/`, or `web/` is MinIO-specific
beyond docstrings, three OpenAPI description strings, and the hard-coded label on
the trust data-residency card.

**Issue #572's shortlist predates RustFS GA.** When the issue was filed
(2026-09-13), RustFS's newest tag was a release candidate and its MinIO
compatibility was described as preview-only; the issue accordingly recommended
holding on a digest-pinned Quay mirror of MinIO, evaluating RustFS after a stable
1.0, and migrating via the S3 API onto a fresh volume rather than reusing the
MinIO one. RustFS 1.0.0 shipped on **2026-09-16**. This ADR re-runs the
evaluation against the GA release and records the decision the issue asked for.

## Decision drivers

1. **Fresh installs must work again, from a published, pinnable, multi-arch
   image.** Both compose files and Helm need an image that exists; the desktop
   launcher runs on Apple Silicon, so `linux/arm64` is required, not optional.
2. **Existing users' data must survive without a bespoke tool.** Every Compose and
   desktop-launcher install has real documents in the `miniodata` volume, written
   by MinIO's single-drive layout (`server /data`, `xl.meta` per object).
3. **Operator experience stays flat.** One container, one volume, one credential
   pair, S3 on 9000 and a console on 9001, and the quickstart promise that a
   single `docker compose up` yields a working stack — including in air-gapped
   Mode 2, where the image is mirrored once.
4. **License fits PRD Appendix B.** The project prefers permissive licenses and
   already carries one documented AGPL exception (PyMuPDF, server-side only).
   A separate-process AGPL service is not a linking problem, but it is a
   procurement question the project has chosen not to multiply (Appendix C risk 3).
5. **The S3 surface above works with the api's pinned client**, including the
   flexible-checksum defaults `botocore` ≥ 1.36 sends on every upload — the
   behaviour that broke several S3-compatible stores in 2025.
6. **Upstream is maintained, and the swap cost is bounded.** The store is a
   T3-class dependency in DE-271 terms only if the api stays S3-generic; this ADR
   must not let the reference default leak into code.

## The options

### A. RustFS (Apache-2.0, Rust)

Single binary, single container, `/data` volume, S3 on 9000, console on 9001,
credentials via `RUSTFS_ACCESS_KEY` / `RUSTFS_SECRET_KEY`. Erasure-coded on-disk
format modelled on MinIO's; **reads MinIO's erasure-coded and single-drive
(`xl` / `xl-single`) layouts in place** since
[rustfs/rustfs#4358](https://github.com/rustfs/rustfs/pull/4358) (merged
2026-07-07). Legacy MinIO "FS mode" without `xl.meta` is not readable, but no
LQ.AI install has ever produced that layout. Decrypting MinIO's on-disk config
and IAM store requires the RustFS root credentials to equal the MinIO root
credentials. GA `1.0.0` published 2026-09-16 as a multi-arch image
(`linux/amd64`, `linux/arm64`). Health at `/health` on the S3 port; the
container runs as uid/gid `10001` (the MinIO image ran as root).

### B. SeaweedFS (Apache-2.0, Go)

Mature (2014), broad S3 coverage, trailing-checksum support landed February 2025.
Architecture is master + volume + filer + S3 gateway; an all-in-one mode exists
but the operator surface (ports, auth config file, filer store) is larger than
one container with two env vars. No in-place read of MinIO data. Governance is
largely one maintainer.

### C. Garage (AGPL-3.0, Rust)

Lightweight, built for small self-hosted clusters, in production since 2020 at a
non-profit. Needs a cluster layout assigned and an access key created before the
first request, so the api's `ensure_bucket` bootstrap needs an init step in
compose and Helm. No in-place read of MinIO data. License cuts against driver 4.

### D. Versity Gateway (Apache-2.0, Go)

Single binary serving S3 over a plain POSIX directory: objects are ordinary
files, which is attractive for the project's transparency posture. No console,
no erasure coding, no in-place read of MinIO data. Smaller community; not
exercised against the api's client in this evaluation.

### E. Keep MinIO from a frozen build

A digest-pinned mirror (Quay), a third-party rebuild (Chainguard, individual
community builds), or a self-built image from the archived source. Zero
migration, zero operator change — and no upstream, no reviewed security patches,
a removed admin console, an AGPL license, and a supply chain that now depends on
whoever rebuilt it. Viable only as a stopgap to unbreak CI while the replacement
lands.

### F. Stop bundling an object store

Require operators to bring S3-compatible storage. Already supported through
`S3_ENDPOINT_URL`, but it breaks the quickstart and the air-gapped Mode 2
promise, and moves the hardest part of self-hosting onto every first-time
operator.

## Evidence

Executed 2026-09-17 in a clean sandbox, against the `rustfs-linux-x86_64-musl`
1.0.0 release binary (build stamp 2026-09-16 07:46 UTC), with the api's locked
`aioboto3 15.5.0` / `aiobotocore 2.25.1` / `botocore 1.40.61`, and the api's
`app.storage` module imported unmodified with `S3_*` settings pointed at it:

| Operation exercised (api function) | Result |
|---|---|
| `ensure_bucket` on an empty store (HeadBucket 404 → CreateBucket), then again (idempotent) | pass |
| `check_storage` readiness probe | pass |
| `stream_upload` 20 MiB + 3 bytes → 3 multipart parts; SHA-256 and byte count match | pass |
| `stream_upload` 12 bytes (single sub-5 MiB trailing part) | pass |
| `stream_upload` empty body (explicit zero-length single part) | pass |
| Size-cap path: `PayloadTooLarge` raised, multipart aborted | pass |
| `stream_download` of each object; bytes identical | pass |
| `upload_bytes` (PutObject) of an export bundle | pass |
| `presigned_get_url`, then an unauthenticated GET of that URL | pass |
| `delete_object`, repeated on the same key, and on a never-existing key (idempotent) | pass |
| `stream_download` of a deleted key surfaces `InternalError` | pass |

Health probes: `GET /health` → 200 with `{"status":"ok", …}`; `HEAD /health` →
200; the legacy `GET /minio/health/live` path also answers 200, so the existing
compose and Helm probes keep answering during the transition. Those are liveness
probes only — the rehearsal below shows they stay green while the store cannot
serve a single request; readiness is `GET /health/ready`. Startup logs show
`checking for a legacy storage format` — the in-place MinIO detection — and,
on a single drive, `automatic storage class has no parity`, the same
zero-redundancy posture MinIO's single-drive mode has.

### In-place rehearsal on a MinIO-written volume (2026-09-19)

Method, receipts and caveats are in
[`docs/research/2026-09-19-rustfs-dropin-rehearsal.md`](../research/2026-09-19-rustfs-dropin-rehearsal.md).
In short: MinIO `RELEASE.2025-10-15T17-29-55Z` (the last community release, built
from the archived source because no image is pullable) wrote a single-drive
volume of 45 objects shaped like the real key space — 41 bare-UUID documents from
12 B to 20 MiB across PDF, DOCX and text types, one empty object, two
`exports/…zip` bundles, all through the api's `stream_upload` / `upload_bytes` so
ETags carry the multipart part-count suffix. RustFS 1.0.0 was then started on
that same directory with the same root credentials, and every later step
listed the bucket and read every object back through `stream_download`,
comparing bytes, size, ETag and content type against the seed-time manifest.

| Phase | Result |
|---|---|
| RustFS first start on the MinIO volume, same credentials | log: `checking for a legacy storage format` → `Migrated format from MinIO config` → `Migrated compatible server config` → `Migrated bucket metadata: lq-ai-files` → `IAM migration complete`; **45/45 intact**, the 20 MiB object's `-3` multipart ETag included |
| Writes and a delete through RustFS on that volume | 46/46 intact |
| **MinIO restarted on the migrated volume** (now holding `.rustfs.sys` and two RustFS-written objects) | starts; **46/46 intact, RustFS-written objects included** |
| RustFS on a pristine snapshot with the **wrong** secret key | starts healthy, same migration log, no decryption error; bucket and all 45 objects readable with the new pair; the old pair gets 403 |
| Plain RustFS restart on the migrated volume | nothing left to migrate; 46/46 intact |
| RustFS run as uid 10001 (the image's user) on the root-owned volume, i.e. an existing install with no ownership fix | process up and `/health` 200, but the store loops on `FileAccessDenied` writing `pool.bin` and **every S3 call returns 503** |
| Same volume after `chown -R 10001:10001`, still as uid 10001 | 46/46 intact; writes and a delete verified 47/47 |
| Probe endpoints, stuck vs healthy | `/health`, `/health/live`, `/minio/health/live` 200 in both states; **`/health/ready` 503 while stuck, 200 when healthy** |

RustFS leaves `.minio.sys` in place, adds `.rustfs.sys`, and reads the existing
per-object `xl.meta` layout without rewriting it. The image runs as `USER rustfs`
(uid/gid 10001) and its entrypoint does not fix ownership of existing data — it
cannot, unprivileged — so the compose init service in the upgrade plan is the
same pattern RustFS's own compose example uses, and it is load-bearing: without
it an upgraded install looks alive and serves nothing. Two consequences for the
decision: the in-place default is measured, not assumed; and the volume stayed
MinIO-readable afterwards, so the migration is not one-way at this scale, though
upstream does not document that and one run does not make it a guarantee. The
wrong-credentials result means an operator who changes the root pair keeps their
objects; matching the pair stays in the guide because it is free and removes the
only failure mode upstream names (encrypted IAM data, which LQ.AI installs do not
have).

Not verified here, and recorded as such: a *real* `miniodata` volume with months
of soft-deleted files (the rehearsal volume is synthetic); the ownership mismatch
through the actual images (it was reproduced with the binary dropped to uid
10001, not with Docker mounting an existing named volume into the image); the
arm64 image on Apple Silicon; and whether the
migration-error fix [rustfs/rustfs#7652](https://github.com/rustfs/rustfs/pull/7652)
(merged 2026-09-11, backported 2026-09-13; before the fix, a failed metadata
import still reported ready — [#7651](https://github.com/rustfs/rustfs/issues/7651))
is inside the `1.0.0` tag. The rehearsals in the upgrade plan and the upgrade
guide's log check cover these.

## Decision

**Adopt RustFS as the bundled reference object store**, replacing MinIO in
`docker-compose.yml`, `docker-compose.release.yml`, the Helm chart, and the
desktop launcher. Specifically:

1. **The api stays S3-generic.** `S3_ENDPOINT_URL`, `S3_ACCESS_KEY`,
   `S3_SECRET_KEY`, `S3_BUCKET`, `S3_REGION` remain the only storage contract.
   No RustFS-specific code, client, or admin API call enters `api/`. The bundled
   store is a reference default an operator may replace with any S3-compatible
   endpoint, exactly as before.
2. **Pin by tag and digest** in both compose files and Helm (`rustfs/rustfs:1.0.0`
   plus the multi-arch index digest), and bump deliberately. The release compose
   currently pulls an unpinned `latest`; that ends here. Issue #301's docker
   Dependabot ecosystem is the mechanism for future bumps.
3. **Naming and compatibility shims.** The compose service becomes `rustfs`, the
   api's default endpoint `http://rustfs:9000`. The `rustfs` service also carries
   the Docker network alias `minio`: the shipped `.env.example` writes
   `S3_ENDPOINT_URL=http://minio:9000` as an explicit line, so every dev-stack
   `.env` copied from it has the old hostname baked in, and without the alias
   those installs would boot with storage silently degraded. Operator-facing
   credential keys become `RUSTFS_ACCESS_KEY` / `RUSTFS_SECRET_KEY`; the compose
   files fall back to the old `MINIO_ROOT_USER` / `MINIO_ROOT_PASSWORD` values,
   and to the old `MINIO_*_HOST_PORT` keys, so an existing `.env` keeps working
   unedited. **These shims stay for the rest of 0.x**, not for one release:
   operators skip versions, the shims cost nothing, and removing them would only
   convert a skipped release into a broken install (see *Compatibility window*
   in the upgrade plan). The named volume keeps the key `miniodata`: renaming it
   would silently hand every existing install an empty store. Its rename is
   filed as a deferred enhancement and will be the second migration under ADR
   0037.
4. **Health and ports.** Probe `GET /health/ready` on the S3 port — not `/health`
   or the legacy `/minio/health/live`, which are liveness-only and stayed 200 in
   the rehearsal while every S3 call returned 503; keep 9000/9001 and the
   `MINIO_*_HOST_PORT` → `RUSTFS_*_HOST_PORT` rename with the same 0.x-long
   fallback. The container's uid `10001` is respected in Helm via
   `securityContext.fsGroup` and in compose via a one-shot init service that
   fixes ownership of volumes MinIO wrote as root before the store starts (see
   *Upgrade plan*).
5. **Migration policy for existing installs** (see *Ratified resolutions* 1):
   - Snapshot first, always: the `miniodata` volume and a `pg_dump`. Upstream
     does not document the in-place read as reversible (the 2026-09-19 rehearsal
     found MinIO could re-read the migrated volume, but that is one run), and
     the old image cannot be re-pulled, so the snapshot plus the locally cached
     MinIO image are the only guaranteed rollback.
   - **In-place** for the default single-drive Compose and desktop installs,
     driven by the migration tool (decision 8): `plan` reports the volume,
     its layout and the snapshot it will take; `apply` snapshots, fixes
     ownership, writes the marker and journals the step; the store starts and
     imports;
     `verify` checks `/health/ready`, reconciles the object count against the
     `files` table including soft-deleted rows plus unexpired export bundles,
     and compares object digests against `files.hash_sha256`. Credentials stay
     the MinIO root pair.
   - **S3 copy** (rclone; the `minio/mc` image is gone too) onto a fresh volume
     for multi-drive or distributed MinIO, for external stores, and as the
     fallback whenever the in-place log check fails. No database change either
     way — keys are bare UUIDs and `exports/…` paths, and export links expire
     within 24 hours.
6. **The Helm api deployment is fixed in the same PR.** It currently sets
   `MINIO_ENDPOINT` / `MINIO_ROOT_*` variables the api has never read, so
   Helm-deployed storage was never wired; the rewrite sets the `S3_*` contract.
7. **Docs and records move with the code**, per CLAUDE.md "documentation is part
   of the change": PRD §2.1 / §2.4 diagrams, §6.5 backup wording, Appendix B row;
   `docs/architecture.md`; the threat model's service list (a refresh is due
   anyway when a component changes); ADR 0005's MinIO vocabulary gets a
   *Revisions* note; quickstart, README, `.env` examples; the trust
   data-residency card label; and a `docs/releases/` entry for the minor release
   that carries the change, with the upgrade guide above.

8. **A migration tool carries the upgrade, under the framework in ADR
   [0037](0037-deployment-migrations-framework.md).** An earlier draft of this
   ADR held that compose YAML alone could carry the migration. The rehearsal
   reversed that on four points that YAML cannot do: take a judgment call on
   the snapshot (free space, destination, size — a 50 GB volume must not be
   tarred blind onto a full disk); detect the install's actual state so that a
   0.7.x install upgrading straight to 0.9.x or later is handled the same way
   as a 0.7.x → 0.8.0 one; refuse loudly, with an explanation, instead of the
   quiet 503 measured in phase 6; and verify the result against the database
   rather than trusting a green probe. The desktop launcher needs that logic in
   code regardless, and it must not exist twice. The 0.8.0 swap is migration
   `0001` under that framework; the compose init service stays as the last
   line of defence and refuses to start the store on an unmigrated MinIO
   volume until the tool has run (or an explicit unattended override is set).

**Why A over the others, in one paragraph.** Drivers 2 and 3 decide it. RustFS is
the only candidate under which existing Compose and desktop users keep their
volume and their runbook; every other option turns the upgrade into a full data
copy for everyone plus a new operator surface. It satisfies driver 4 where Garage
does not, driver 1 where a frozen MinIO does not, and driver 5 by direct
measurement above. SeaweedFS is the strongest alternative on governance and is
named as the fallback should RustFS disappoint; Versity is the fallback if the
committee later weighs on-disk transparency above erasure coding.

## Upgrade plan for the next minor (v0.8.0)

Under ADR 0025 rule 3 a working install needs a human to touch it for this
change (re-pull, ownership fix, log check), so the release that carries it is a
**minor**. `main` is at `0.7.1` with nothing tagged beyond it, so that release is
**v0.8.0** unless another minor is cut first; the number is computed from `main`
at tag time, not reserved here. The plan below is what the implementation PR and
the `docs/releases/v0.8.0.md` note must deliver. The committee's ratified
resolutions below settle the remaining implementation choices.

### What v0.8.0 ships

1. **Image.** `rustfs/rustfs:1.0.0` pinned by tag and multi-arch index digest in
   `docker-compose.yml`, `docker-compose.release.yml`, and Helm `values.yaml`.
   MinIO leaves the reference stack.
2. **Compose.** Service `rustfs` on 9000/9001 with the `/health/ready` probe and
   the network alias `minio`; `RUSTFS_ACCESS_KEY` / `RUSTFS_SECRET_KEY` fed from
   the operator's `.env`, with fallbacks to `MINIO_ROOT_USER` /
   `MINIO_ROOT_PASSWORD`; the same fallback for the `*_HOST_PORT` keys; the
   volume key `miniodata` unchanged. A one-shot init service runs before
   `rustfs`: on an empty volume or an already-migrated one it sets ownership to
   uid/gid `10001` and exits; on a volume that holds `.minio.sys` but no
   `.rustfs.sys` and no marker in the ops volume it **refuses**, logs "existing MinIO
   volume detected — run the migration tool first", and `rustfs` does not start.
   `LQ_AI_OPS_UNATTENDED=1` skips the marker check for operators with their own
   backups, and is logged. A `migrate` service under the `ops` profile (api
   image, the object-store volume and the `lq-ai-ops` volume mounted) is the
   tool's home; it never runs as part of a plain `up`. The api's default endpoint
   becomes `http://rustfs:9000`.
3. **Helm.** The StatefulSet and Service are renamed, the pod gets
   `fsGroup: 10001`, the readiness probe moves to `/health/ready`, `values.yaml` keys are
   renamed with the old `minio.*` keys honoured for one minor, and the api
   deployment's env block is rewritten to the `S3_*` contract (the wiring fix in
   decision 6). Because that wiring never worked, a Helm install has no data in
   its MinIO PVC; the chart's upgrade note says to treat it as a fresh install
   and delete the old claim once confirmed empty. The chart stays "drafted" in
   HONEST-STATE (DE-327 is untouched).
4. **Desktop launcher `desktop-v0.8.0`.** Bundles the new release compose;
   `EXPECTED_SERVICES`, the rendered `.env` keys, the port fields, and the secret
   pair follow the rename, and the stored MinIO root pair is reused as the
   RustFS credentials. The launcher gains the migration flow ADR 0037
   specifies: on every start it runs `migrate plan`; when something is pending
   it shows what will happen, the snapshot destination under its app-data
   directory and the space needed, and asks once; then it runs `apply`, brings
   the store up, runs `verify`, and only then starts the rest. A failed `plan`
   or `verify` stops there with the receipt on screen and a rollback button.
   The journal is visible on the health view. Launcher users never run a
   docker command. This is the concern that makes the tool mandatory: the launcher has
   no other way to sequence stop → snapshot → fix → start → verify.
5. **Docs.** `docs/releases/v0.8.0.md` with the runbook below at the top;
   quickstart, README, both `.env` examples; PRD §2.1 / §2.4 diagrams, §6.5
   backup wording, Appendix B row; `docs/architecture.md`; the threat-model
   service list; ADR 0005 *Revisions* note; the trust data-residency card label.
6. **CI.** Stack-smoke green on RustFS. The #303 ingest round-trip lands in the
   same release if ready, otherwise as a follow-up.
7. **The migration framework and migration `0001`** (ADR 0037): the `ops`
   profile service, the `lq-ai-ops` volume holding the journal and the
   markers, the `plan` / `apply` / `verify` / `status` / `rollback` commands,
   the launcher flow with the image-tag pin ADR 0025 decision 2 requires, the
   fixture MinIO volume, and the stack-smoke run that applies `0001` to it.
   The Postgres read-model of the journal and the admin endpoint are deferred
   (ADR 0037 decision 11); nothing in this item needs an alembic revision.

### Sequencing

1. This ADR and ADR 0037 merge as *Accepted*, recording the committee's
   2026-09-20 decision and the resolutions below.
2. No frozen-MinIO bridge lands. The replacement implementation is next, and
   the broken stack-smoke run remains visible until that implementation merges.
3. The framework lands first (ADR 0037's PR: registry, the ops volume with
   journal and markers, CLI, compose profile, tests, with `plan` reporting
   nothing pending on a fresh stack).
   One implementation PR then carries items 1–7, labelled `breaking-change` so
   ADR 0025's version-consistency gate knows the next tag must be a minor. It
   touches no `gateway/` path; the stack-smoke workflow change for the fixture
   volume routes through the security-review path in CODEOWNERS.
4. **Rehearsals before tagging**, with receipts committed under
   `docs/research/` as ADR 0026 did. The synthetic in-place rehearsal is done
   and committed (*Evidence*). Two remain: an in-place upgrade of a *real*
   `miniodata` volume written by MinIO (from a maintainer machine that still
   holds the cached image), following the runbook verbatim and exercising the
   ownership fix through the container images; and a launcher upgrade on Apple
   Silicon. The *Evidence* section of this ADR is amended with both results,
   including anything that failed.
5. Version strings move together per the v0.7.1 note — `api`, `gateway`, the
   committed OpenAPI export, then `desktop` and its lockfile — and `v0.8.0` is
   tagged, followed by `desktop-v0.8.0`.
6. **Compatibility window.** The `MINIO_*` env fallbacks, the `minio` network
   alias, the `*_HOST_PORT` fallbacks and Helm's old `minio.*` value keys stay
   for the rest of 0.x. They are free, and an operator on 0.7.x when 0.9.0 or
   0.10.0 ships must land on the same path as one upgrading to 0.8.0: `migrate
   plan` detects the MinIO volume from its contents, not from a version number,
   and reconciles what it finds against its journal (ADR 0037 decision 2), so
   the tool, not the shims, is what makes skip-version upgrades safe. When a
   later release wants the shims gone, that release's `plan` flags stale `.env`
   keys and the removal gets its own release-note line (ratified resolution 2).

### Operator runbook (published verbatim in the v0.8.0 note)

**Before anything, on every topology:** take a `pg_dump`, as for any minor. The
object-store snapshot is taken by the migration tool, which refuses to proceed
without the space for it. Do not prune Docker images until the upgrade is
verified: upstream does not document the in-place read as reversible, and the
MinIO image cannot be re-pulled, so the tool's snapshot plus the image still
cached on the host are the guaranteed rollback. Expect a few minutes of
downtime; the import itself is quick because no bytes move.

**A. Compose, default single-drive volume (in-place).** Four commands, no
`.env` edit: the old `MINIO_*` keys and the `minio` hostname keep working.

1. Stop the stack (never with the flag that removes volumes) and check out
   v0.8.0.
2. `migrate plan` — reports the MinIO volume, its layout, object count and
   size, the snapshot destination and free space, and what `apply` will do.
3. `migrate apply` — snapshots the volume, fixes ownership, writes the marker
   the init service looks for, and journals the step.
4. `docker compose up -d` — the store imports on first start; the api waits on
   `/health/ready`.
5. `migrate verify` — readiness, object count against `files` including
   soft-deleted rows plus unexpired export bundles, and digests against
   `files.hash_sha256`; then open one existing document from the UI.

Rollback: stop the stack, `migrate rollback 0001` (restores the snapshot into
the volume and clears the marker), check out the previous release, start it
against the cached MinIO image. Keep the snapshot for at least one release
cycle; `migrate status` shows where it is.

**B. Desktop launcher.** Install `desktop-v0.8.0` and start it. The launcher
runs the same `plan → apply → up → verify` sequence itself, asks once before
`apply` with the snapshot location and size on screen, and stops with the
receipt visible if anything is red. Rollback is a button that does A's rollback
with the launcher's own snapshot, then reinstalling the previous launcher build.

**C. Helm.** Treat as a fresh install: upgrade the chart with the renamed values,
confirm the old PVC holds no objects, delete it. There is no data to migrate
because the api was never wired to the chart's store.

**D. External S3-compatible store** (operator set `S3_ENDPOINT_URL` to something
other than the bundled service). No action. The bundled service can be left
running empty or disabled, as today.

**E. Multi-drive or distributed MinIO, or a failed in-place import.** Run RustFS
on a fresh volume beside the old store, mirror `lq-ai-files` with rclone (the
`minio/mc` image is gone too), point `S3_ENDPOINT_URL` at the new store, run
`migrate verify` against it, and retire the old volume after a release cycle. No database change: keys are bare UUIDs and `exports/…` paths, and export
links expire within 24 hours.

### Exit criteria for tagging v0.8.0

- Stack-smoke green on `main` with RustFS, and a hands-on upload → download
  through the api on the smoke stack.
- Both rehearsals in sequencing step 4 executed and their receipts committed;
  the *Evidence* section amended.
- The v0.8.0 note carries the runbook, with the snapshot-first warning as its
  first paragraph.
- The four version strings agree, and the release is labelled a minor.
- `migrate plan` on the fresh smoke stack reports nothing pending, and
  `plan → apply → up → verify` passes against the fixture MinIO volume in
  stack-smoke — the CI-level in-place rehearsal, run on every compose change.

## Consequences

**Positive.**
- Fresh installs work again; CI's stack-smoke goes green on the same job that
  caught the breakage.
- The api's storage contract is unchanged and now demonstrably exercised against
  a second implementation, which is the strongest evidence yet that it is
  generic.
- License posture simplifies: the bundled store moves from AGPL-3.0 to
  Apache-2.0 (Appendix B).
- Existing users on the default topology upgrade without copying data.

**Negative / risks.**
- **RustFS is young.** GA is days old, a readiness bug in the very migration path
  we rely on was fixed six days before the tag, and the project moves fast.
  Mitigations: digest pin; the S3-generic contract keeps the swap cost at
  days if it must be repeated; the stack-smoke ingest round-trip (#303) becomes
  the conformance gate; RustFS gets a DE-271 row with SeaweedFS as its named
  fallback.
- **Ownership mismatch, measured.** The uid-10001 container cannot write a
  root-owned MinIO volume, and the failure is quiet: the process stays up,
  liveness probes stay green, and every S3 call returns 503. The image does not
  fix this itself. The compose init service is therefore mandatory, the
  healthcheck must be `/health/ready`, and the desktop launcher must carry the
  same init step.
- **Rollback rests on the snapshot.** Upstream does not document the in-place
  read as reversible; the 2026-09-19 rehearsal found MinIO re-reading the
  migrated volume, RustFS-written objects included, which is encouraging but a
  single synthetic run. With no MinIO image to re-pull, the snapshot-first rule
  is load-bearing, and the guide must say so in its first line.
- **Single-drive RustFS cannot grow in place** into a multi-drive pool (RustFS
  documents this explicitly); growth means a fresh deployment and an S3 copy.
  This is the same constraint MinIO's single-drive mode had.
- A temporary vocabulary split: code comments still say "MinIO" in places the
  implementation PR chooses not to touch. Acceptable; ADR 0005's meaning is
  unchanged.

**Neutral.**
- The release carrying this is a **minor** under ADR 0025 rule 3: a working
  install needs a human to touch it (re-pull, ownership fix, log check). The
  release-level plan, runbook, and exit criteria are in *Upgrade plan for the
  next minor (v0.8.0)* above.
- No test in `api/tests/` changes; storage is mocked there. The real-store
  coverage lives in stack-smoke.

**Follow-ups spawned (filed separately; not part of the ADR PR).**
- Implementation PR, scoped by *What v0.8.0 ships* above: compose ×2, `.env`
  examples ×2, Helm (templates, values, NOTES, api env fix), desktop launcher
  (service list, env, ports, secrets, the migration flow, tests), docs
  listed in decision 7, stack-smoke pass. Closes the operational half of #572's
  acceptance criteria.
- Two rehearsals with committed receipts before the tag (sequencing step 4),
  and the `docs/releases/v0.8.0.md` note carrying the runbook.
- ADR [0037](0037-deployment-migrations-framework.md), the deployment-migration
  framework, and migration `0001` under it; the launcher's migration flow.
- #303: extend the stack-smoke round-trip to assert an upload → download byte
  match through the api, which is the "backend conformance test" #572 asked for
  in the place the project already runs real infrastructure.
- Deferred enhancements to file in PRD §9: rename the `miniodata` volume key;
  a public presigned-URL endpoint setting (export links currently embed the
  internal service hostname — pre-existing, unaffected in kind by this swap);
  a DE-271 row for the bundled object store.
- #301: add the docker ecosystem to Dependabot so the new digest pin is
  refreshed rather than drifting.

## Alternatives considered (and why not)

- **Wait for RustFS to mature on a frozen MinIO (option E as a policy, not a
  stopgap).** Rejected: it converts a dated stopgap into an unbounded one, on an
  archived codebase with an AGPL license and no security process, while every
  new operator hits the same wall. Acceptable only as the bridge until the
  implementation PR merges, if the committee wants CI green sooner.
- **SeaweedFS as the primary.** Rejected on drivers 2 and 3: every existing
  install must copy its data, and the reference stack gains a second operator
  surface. Retained as the named fallback.
- **Garage.** Rejected on drivers 3 and 4: an init step for layout and keys, and
  AGPL-3.0 against a permissive-preference policy.
- **Versity Gateway.** Not rejected on merit — it was not measured against the
  api's client in this round. Retained as the transparency-first fallback.
- **No bundled store.** Rejected on driver 3; the option remains available to
  any operator via `S3_ENDPOINT_URL`, as today.

## Ratified resolutions (2026-09-20)

1. **Primary migration path:** in-place for the single-drive topology,
   snapshot-first, with S3 copy as the fallback.
2. **Compatibility window:** retain the `MINIO_*` env fallbacks, the `minio`
   network alias and the Helm `minio.*` keys for the rest of 0.x.
3. **CI bridge:** do not land a frozen-MinIO bridge; proceed directly to the
   replacement implementation and keep the failing stack-smoke result visible.
4. **Conformance test placement:** extend stack-smoke through #303; do not add
   a second RustFS-backed api integration job.

## Cross-references

- **Tracking issue:** [LegalQuants/lq-ai#572](https://github.com/LegalQuants/lq-ai/issues/572);
  related [#301](https://github.com/LegalQuants/lq-ai/issues/301),
  [#303](https://github.com/LegalQuants/lq-ai/issues/303).
- **Breakage evidence:** stack-smoke
  [run 34919920153](https://github.com/houfu/lq-ai/actions/runs/34919920153)
  (2026-09-15, `main`).
- **Rehearsal research and receipts:**
  [`docs/research/2026-09-19-rustfs-dropin-rehearsal.md`](../research/2026-09-19-rustfs-dropin-rehearsal.md)
  and `docs/research/2026-09-19-rustfs-dropin-receipts/` (driver scripts, the
  verified manifest, MinIO's `format.json`, log excerpts).
- **RustFS:** [repository](https://github.com/rustfs/rustfs);
  [1.0.0 release](https://github.com/rustfs/rustfs/releases/tag/1.0.0);
  in-place MinIO read [#4358](https://github.com/rustfs/rustfs/pull/4358);
  migration readiness bug [#7651](https://github.com/rustfs/rustfs/issues/7651)
  and fix [#7652](https://github.com/rustfs/rustfs/pull/7652).
- **MinIO status:** [maintenance mode](https://github.com/minio/minio/issues/21714).
- **Alternatives:** [Garage features and license](https://garagehq.deuxfleurs.fr/documentation/reference-manual/features/);
  [SeaweedFS trailing-checksum support](https://github.com/seaweedfs/seaweedfs/pull/6539).
- **In-repo:** ADR [0005](0005-file-storage-soft-delete-and-key-scheme.md), ADR
  [0025](0025-release-versioning-and-pipeline-ordering.md), ADR
  [0037](0037-deployment-migrations-framework.md) (the migration framework this
  upgrade is the first user of), `api/app/storage.py`,
  `docker-compose.yml`, `docker-compose.release.yml`,
  `deploy/helm/lq-ai/templates/statefulset-minio.yaml`,
  `deploy/helm/lq-ai/templates/deployment-api.yaml`, `desktop/src/core/types.ts`,
  PRD §2.1, §2.4, §6.5, Appendix B, DE-033, DE-271.
- Committee [minutes, 2026-09-20](https://github.com/LegalQuants/lq-ai-community/blob/main/meetings/2026-09-20-weekly/notes.md)
  for the ratification and resolutions above.
