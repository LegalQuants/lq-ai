# ADR 0027 — Bundled object store: replace archived MinIO with RustFS; keep the api S3-generic

**Status:** Proposed (2026-09-17) — for committee decision at the next weekly call
**Date:** 2026-09-17
**Owner:** Maintainer team (houfu)
**Origin:** Issue [LegalQuants/lq-ai#572](https://github.com/LegalQuants/lq-ai/issues/572)
*"Replace archived MinIO with a maintained S3-compatible backend"* (2026-09-13),
reframed as this ADR's tracking issue. Grounded in a verification run executed on
2026-09-17: the api's real storage module (`api/app/storage.py`, unmodified) driven
against a RustFS 1.0.0 binary with the api's pinned `aioboto3` / `botocore`
versions. Receipts are summarised under *Evidence* below.

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
compose and Helm probes keep working during the transition. Startup logs show
`checking for a legacy storage format` — the in-place MinIO detection — and,
on a single drive, `automatic storage class has no parity`, the same
zero-redundancy posture MinIO's single-drive mode has.

Not verified here, and recorded as such: an in-place migration of a real
`miniodata` volume (no MinIO binary or image was obtainable from this sandbox),
the arm64 image on Apple Silicon, and whether the migration-error fix
[rustfs/rustfs#7652](https://github.com/rustfs/rustfs/pull/7652) (merged
2026-09-11, backported 2026-09-13; before the fix, a failed metadata import
still reported ready — [#7651](https://github.com/rustfs/rustfs/issues/7651))
is inside the `1.0.0` tag. The implementation PR's stack-smoke run and the
upgrade guide's log check cover the first and third; the desktop launcher's
verification run covers the second.

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
3. **Naming.** The compose service becomes `rustfs`, the api's default endpoint
   `http://rustfs:9000`. Operator-facing credential keys become
   `RUSTFS_ACCESS_KEY` / `RUSTFS_SECRET_KEY`; the compose files fall back to the
   old `MINIO_ROOT_USER` / `MINIO_ROOT_PASSWORD` values **for one minor release**,
   so an existing `.env` keeps working unedited. The named volume keeps the key
   `miniodata` for this release: renaming it would silently hand every existing
   install an empty store. Its rename is filed as a deferred enhancement.
4. **Health and ports.** Probe `GET /health` on the S3 port; keep 9000/9001 and the
   `MINIO_*_HOST_PORT` → `RUSTFS_*_HOST_PORT` rename with the same one-release
   fallback. The container's uid `10001` is respected in Helm via
   `securityContext.fsGroup` and in compose via a documented one-shot ownership
   fix for volumes MinIO wrote as root.
5. **Migration policy for existing installs** (see *Open questions* 1 for the
   fork the committee is asked to ratify):
   - Snapshot first, always: the `miniodata` volume and a `pg_dump`. The in-place
     read is not documented as reversible, and the old image cannot be re-pulled,
     so the snapshot plus the locally cached MinIO image are the only rollback.
   - **In-place** for the default single-drive Compose and desktop installs:
     same volume, RustFS credentials set to the exact MinIO root pair, ownership
     fixed, RustFS started alone, startup log checked for the legacy-format
     import completing without bucket-metadata or IAM errors, object count in
     `lq-ai-files` reconciled against the `files` table, then the rest of the
     stack.
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

**Why A over the others, in one paragraph.** Drivers 2 and 3 decide it. RustFS is
the only candidate under which existing Compose and desktop users keep their
volume and their runbook; every other option turns the upgrade into a full data
copy for everyone plus a new operator surface. It satisfies driver 4 where Garage
does not, driver 1 where a frozen MinIO does not, and driver 5 by direct
measurement above. SeaweedFS is the strongest alternative on governance and is
named as the fallback should RustFS disappoint; Versity is the fallback if the
committee later weighs on-disk transparency above erasure coding.

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
- **Ownership mismatch.** The uid-10001 container cannot write a root-owned
  MinIO volume; the upgrade guide must make the one-shot fix impossible to miss,
  and the desktop launcher must automate it.
- **One-way migration with no upstream rollback image.** The snapshot-first rule
  is load-bearing, and the guide must say so in its first line.
- **Single-drive RustFS cannot grow in place** into a multi-drive pool (RustFS
  documents this explicitly); growth means a fresh deployment and an S3 copy.
  This is the same constraint MinIO's single-drive mode had.
- A temporary vocabulary split: code comments still say "MinIO" in places the
  implementation PR chooses not to touch. Acceptable; ADR 0005's meaning is
  unchanged.

**Neutral.**
- The release carrying this is a **minor** under ADR 0025 rule 3: a working
  install needs a human to touch it (re-pull, ownership fix, log check).
- No test in `api/tests/` changes; storage is mocked there. The real-store
  coverage lives in stack-smoke.

**Follow-ups spawned (filed separately; not part of the ADR PR).**
- Implementation PR: compose ×2, `.env` examples ×2, Helm (templates, values,
  NOTES, api env fix), desktop launcher (service list, env, ports, secrets,
  tests), docs listed in decision 7, stack-smoke pass. Closes the operational
  half of #572's acceptance criteria.
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

## Open questions (for the committee call)

1. **Primary migration path.** Issue #572 recommended an S3 copy onto a fresh
   volume rather than reusing the MinIO one. This ADR proposes in-place as the
   documented default for the single-drive topology, with snapshot-first and an
   S3-copy fallback, because it preserves the operator surface and avoids a
   double-storage window on small hosts. Ratify, or make the S3 copy the default
   and in-place the documented alternative.
2. **Compatibility window.** Keep the `MINIO_ROOT_*` and `MINIO_*_HOST_PORT`
   fallbacks for one minor release (proposed), or cut over in the same release
   with a required `.env` edit.
3. **CI bridge.** Whether to land a frozen-MinIO digest pin first to unbreak
   stack-smoke on `main` while the implementation PR is reviewed, or accept the
   red run until it merges.
4. **Conformance test placement.** stack-smoke via #303 (proposed), or an
   additional `integration`-marked api test job with a RustFS service container.

## Cross-references

- **Tracking issue:** [LegalQuants/lq-ai#572](https://github.com/LegalQuants/lq-ai/issues/572);
  related [#301](https://github.com/LegalQuants/lq-ai/issues/301),
  [#303](https://github.com/LegalQuants/lq-ai/issues/303).
- **Breakage evidence:** stack-smoke
  [run 34919920153](https://github.com/houfu/lq-ai/actions/runs/34919920153)
  (2026-09-15, `main`).
- **RustFS:** [repository](https://github.com/rustfs/rustfs);
  [1.0.0 release](https://github.com/rustfs/rustfs/releases/tag/1.0.0);
  in-place MinIO read [#4358](https://github.com/rustfs/rustfs/pull/4358);
  migration readiness bug [#7651](https://github.com/rustfs/rustfs/issues/7651)
  and fix [#7652](https://github.com/rustfs/rustfs/pull/7652).
- **MinIO status:** [maintenance mode](https://github.com/minio/minio/issues/21714).
- **Alternatives:** [Garage features and license](https://garagehq.deuxfleurs.fr/documentation/reference-manual/features/);
  [SeaweedFS trailing-checksum support](https://github.com/seaweedfs/seaweedfs/pull/6539).
- **In-repo:** ADR [0005](0005-file-storage-soft-delete-and-key-scheme.md), ADR
  [0025](0025-release-versioning-and-pipeline-ordering.md), `api/app/storage.py`,
  `docker-compose.yml`, `docker-compose.release.yml`,
  `deploy/helm/lq-ai/templates/statefulset-minio.yaml`,
  `deploy/helm/lq-ai/templates/deployment-api.yaml`, `desktop/src/core/types.ts`,
  PRD §2.1, §2.4, §6.5, Appendix B, DE-033, DE-271.
- Committee minutes (lq-ai-community), once published, for the ratification and
  the answers to the open questions above.
