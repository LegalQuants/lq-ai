# Back up and restore

A useful backup includes everything needed to bring the app and its data back together. Restore it to a separate installation before you rely on it.

## What to include

Keep the Postgres database, the uploaded files, the working gateway settings, and the key needed to decrypt those settings. Redis holds queued work too, so account for jobs that were running when the backup was taken.

## Restore before restarting work

Stop the app and background workers while you restore data and settings. Then start them and check sign-in, access to documents, and a test task. Starting against empty storage before the restore is done can create records you didn't intend — the api would migrate an empty database, and the gateway would seed a fresh `gateway.yaml`, either of which then has to be undone by hand.

## What was tested here

This page describes the shape of a backup and restore, built directly from the compose files' own volume declarations — it has not been exercised end-to-end as a restore drill in this repository. Rehearse it against a separate, disposable installation before you rely on it during an actual incident.

## Which storage to preserve

Keep the `pgdata`, `miniodata` and `gateway-config` volumes consistent with each other — restoring one without the others can leave the app in a state it was never actually in. `redisdata` and the model/OCR caches don't need the same care: nothing durable lives only in Redis, and the caches can simply be re-downloaded.

| Named volume | Holds | If you lose it |
|---|---|---|
| `pgdata` | Every relational row — users, chats, messages, projects, audit log, citations, playbooks, skills you've forked into the DB | Everything: history, matter context, the audit trail |
| `miniodata` | Uploaded file bytes and export bundles, referenced by `files.storage_path` in Postgres | Every document ever uploaded, even though the DB rows describing them survive |
| `gateway-config` | The live `gateway.yaml`, including any `api_key_encrypted` tokens the runtime provider-key surface has written | Every runtime-managed provider key, and any model-alias edits made in-app |
| `redisdata` | The arq job queue and rate-limit counters | Nothing durable — in-flight background jobs, not history |
| `ollamadata`, `ingest-hf-cache`, `ingest-easyocr-cache` | Downloaded model weights and layout/OCR models | Nothing you can't re-pull; costs bandwidth and time, not data |

The first three are the ones a restore actually depends on. The last three are caches — recreate them by re-pulling, not by restoring. `redisdata` sits between the two: nothing durable is lost, but recovery differs by job type. A fresh `ingest-worker` start re-sweeps files stuck at `pending`/`processing` and re-enqueues them automatically (`api/app/workers/document_pipeline.py`'s `on_startup` sweep), so document ingestion self-heals. Easy Playbook generation, Tabular Review execution and Autonomous Session jobs don't have that sweep (`api/app/workers/queue.py`) — if their enqueue was lost with Redis, the row stays at its last status and an operator has to re-enqueue it by hand.

The bundled object store is [RustFS](../adr/0036-bundled-object-store-rustfs.md), not MinIO — MinIO's image became unavailable and the project replaced it (ADR 0036). The compose service is named `rustfs`, but the volume is still named `miniodata` for continuity, and the S3-compatible client tooling below (`mc`) still works against it unchanged, since RustFS speaks the same S3 API on the same port. If you're upgrading an existing bundled-store deployment from a MinIO-era release, that migration is its own procedure — see [Upgrade](upgrade.md#operator-action-releases).

> [!NOTE]
> **Professional duty** — `pgdata` holds the audit log and every chat a privileged matter produced — this is client-confidential material by construction, not an incidental side effect of backing it up. Wherever your backup lands (a snapshot service, an offsite volume, a second disk), it inherits the same confidentiality obligation the live deployment carries. `privilege_marked` rows in `audit_log` ([`docs/security/audit-logging.md`](../security/audit-logging.md)) mark which rows that applies to most directly, but the whole database is in scope — deciding who may read a backup, and under what encryption, is a call for whoever is responsible for those matters.

## Keep the decryption key separately

Save `LQ_AI_GATEWAY_MASTER_KEY` in your protected recovery records as well as backing up `gateway-config`. The encrypted provider keys in that volume cannot be recovered without the matching master key. The gateway does not save the master key into its own data volume — it's supplied from the host's `.env` or another secrets store.

> [!CAUTION]
> **Silent failure** — The `LQ_AI_GATEWAY_MASTER_KEY` that decrypts every `api_key_encrypted` token in `gateway-config` is **not stored in any volume**, but it is on the host somewhere: both compose files read it from the `LQ_AI_GATEWAY_MASTER_KEY` environment variable (`docker-compose.yml`, `docker-compose.release.yml`), which normally comes from a `.env` file next to the compose file — or, for the macOS desktop app, its own `.env` under the app's per-user application-support directory, not the repo checkout (see [Install on Mac](../INSTALL-MAC.md)). Back up the `gateway-config` volume without also backing up this value separately, and you've backed up ciphertext you cannot decrypt. [`docs/security/encrypted-keys.md`](../security/encrypted-keys.md) is explicit: *"There is no recovery"* for a lost master key — the only path back is re-issuing every provider key at the upstream provider. Store `LQ_AI_GATEWAY_MASTER_KEY` in your secrets vault, independently of any volume snapshot, the same way you'd store it for [rotating a leaked key](rotate-a-leaked-key.md).

## Make a consistent copy

Use Postgres's `pg_dump` for the database backup — don't copy a live database volume as ordinary files and assume it's consistent. A hot backup of `pgdata` via `pg_dump` is consistent; a raw volume copy of a live `pgdata` is not (raw volume copies are only safe with the stack stopped). Coordinate the file-store copy with the database backup so uploads can't end up ahead of, or behind, the rows that reference them. Look up the actual Compose project's volume names rather than guessing them — see "Find and archive the gateway configuration" below for the command. Backups and host configuration carry the same sensitive material and credentials as the running app, so protect them accordingly.

## Check the restored installation

Restore into a separate, stopped installation, bringing up only the storage services the restore needs. Put the database, the uploaded files, the gateway settings and the matching master key in place before starting the api, gateway and other workers.

**Verify, don't assume.** Confirm the migration head matches what you expect (`docker compose exec api alembic current`), sign in, open a chat that existed before the incident, and confirm its history and any citations render. If provider keys were runtime-managed, open **Admin → Provider keys** and confirm each shows `configured` rather than a decrypt failure — a wrong or missing master key surfaces as `DecryptError` at adapter-build time per [`docs/security/encrypted-keys.md`](../security/encrypted-keys.md#verifying-the-setup), not as a restore error. The provider-health endpoint (`GET /admin/v1/providers/health`, `gateway/app/api/admin.py`) is a `501` stub as of this writing, so it can't serve as that check — the Provider keys page is the one that actually confirms decryption succeeded.

## Back up the file store and gateway settings too

The examples below copy the default `lq-ai-files` bucket and the named `gateway-config` volume. Identify the actual volume name with `docker volume ls` rather than assuming it — a different Compose project has different volumes: Compose derives the volume's name prefix from the project name, which varies by install (a plain checkout, a second clone, or the macOS desktop app's `-p lq-ai-desktop`). Pause writes while coordinating these copies with the database dump. If the host is offline, make sure the `alpine` image the archive step below uses is already pulled.

## Restore only into an empty recovery installation

Give the recovery installation a distinct Compose project name, free host ports, and the saved configuration and secrets. Set the target's `.env` with the **same** `LQ_AI_GATEWAY_MASTER_KEY` you saved earlier, before any container starts. Then bring up only the storage this restore needs and nothing else yet: `docker compose up -d postgres` (add `rustfs` to that command too if you're restoring the object store with `mc mirror` rather than a raw volume snapshot). The example `pg_restore` below uses `--clean`, which drops and replaces the objects in the target database — run it only against this empty recovery installation, never against the one you are running. Restore the file-store bytes and the gateway-config archive before starting the gateway, api and workers, so the gateway doesn't re-seed `gateway.yaml` from `gateway.yaml.example` instead. Start with the same app version you backed up from; treat a version upgrade as a separate step afterward.

## Example database backup

Adjust `-U`/`-d` if you've overridden `POSTGRES_USER` / `POSTGRES_DB` (both default to `lq_ai`). Coordinate this with the file-store backup below. Use a new filename each time so you don't overwrite an existing backup.

```bash
docker compose exec -T postgres pg_dump -U lq_ai -d lq_ai --format=custom \
  > lq-ai-postgres-$(date +%Y-%m-%d).dump
```

## Example file-store backup

Mirror the bucket with the MinIO client (`mc`) against the exposed API port (`OBJECT_STORE_API_HOST_PORT`, default `9000`, with `MINIO_API_HOST_PORT` accepted as a legacy fallback through at least v0.10.0). `OBJECT_STORE_ACCESS_KEY` / `OBJECT_STORE_SECRET_KEY` are the same credentials that configure the running `rustfs` service — keep them in your usual secrets tooling rather than pasting them somewhere a shell history keeps. Use a new destination directory and coordinate with the database dump.

```bash
mc alias set lq-ai-backup http://localhost:9000 <OBJECT_STORE_ACCESS_KEY> <OBJECT_STORE_SECRET_KEY>
mc mirror lq-ai-backup/lq-ai-files ./lq-ai-files-backup/
```

Alternatively, stop the stack and snapshot the `miniodata` volume directly — the same `docker run ... tar czf` pattern used for `gateway-config` below — but only while `rustfs` is stopped; a raw copy of a live volume is not guaranteed consistent, the same way a raw `pgdata` copy isn't.

## Find and archive the gateway configuration

Replace `<project>` with the volume name reported below — look it up rather than assuming `lq-ai_`. Run this from a protected backup directory and use a fresh archive filename each time.

```bash
docker volume ls --filter name=gateway-config
# or: docker compose config --volumes
docker run --rm -v <project>_gateway-config:/from -v "$PWD":/to alpine \
  tar czf /to/gateway-config-$(date +%Y-%m-%d).tar.gz -C /from .
```

Copy the matching `LQ_AI_GATEWAY_MASTER_KEY` into your protected recovery records separately — see "Keep the decryption key separately" above; it isn't in this archive.

## Example restore into a separate installation

Restore Postgres into the fresh `postgres` container:

```bash
docker compose exec -T postgres pg_restore -U lq_ai -d lq_ai --clean --if-exists \
  < lq-ai-postgres-2026-09-01.dump
```

Restore the object-store bucket (`mc mirror` in the reverse direction against the `rustfs` you started above, or extract the volume snapshot into a fresh `miniodata` volume before `rustfs` itself starts), and restore the `gateway-config` tarball into a fresh `gateway-config` volume before the gateway container starts. Only once Postgres, the object store and the gateway config are restored, start the rest of the stack: `docker compose up -d`. Then work through "Check the restored installation," above.
