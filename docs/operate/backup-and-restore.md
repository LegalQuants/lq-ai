# Back up and restore

No runbooks directory covering this existed in the repository before this page, and no `pg_dump` or restore script ships anywhere in it — this page is built from the compose files' own volume declarations and the schema doc, not curated from an existing backup guide. Where the repository is silent on a step, this page says so.

## What has to survive

| Named volume | Holds | If you lose it |
|---|---|---|
| `pgdata` | Every relational row — users, chats, messages, projects, audit log, citations, playbooks, skills you've forked into the DB | Everything: history, matter context, the audit trail |
| `miniodata` | Uploaded file bytes and export bundles, referenced by `files.storage_path` in Postgres | Every document ever uploaded, even though the DB rows describing them survive |
| `gateway-config` | The live `gateway.yaml`, including any `api_key_encrypted` tokens the runtime provider-key surface has written | Every runtime-managed provider key, and any model-alias edits made in-app |
| `redisdata` | The arq job queue and rate-limit counters | Nothing durable — in-flight background jobs, not history |
| `ollamadata`, `ingest-hf-cache`, `ingest-easyocr-cache` | Downloaded model weights and layout/OCR models | Nothing you can't re-pull; costs bandwidth and time, not data |

The first three are the ones a restore actually depends on. The last three are caches — recreate them by re-pulling, not by restoring.

The bundled object store is [RustFS](../adr/0036-bundled-object-store-rustfs.md), not MinIO — MinIO's image became unavailable and the project replaced it (ADR 0036). The compose service is named `rustfs`, but the volume is still named `miniodata` for continuity, and the S3-compatible client tooling below (`mc`) still works against it unchanged, since RustFS speaks the same S3 API on the same port. If you're upgrading an existing bundled-store deployment from a MinIO-era release, that migration is its own procedure — see [Upgrade](upgrade.md#operator-action-releases).

> [!CAUTION]
> **Silent failure** — The `LQ_AI_GATEWAY_MASTER_KEY` that decrypts every `api_key_encrypted` token in `gateway-config` is **not stored in any volume** — it lives only in the gateway process's environment (`docker-compose.yml`, `docker-compose.release.yml`). Back up the `gateway-config` volume without also backing up this value separately, and you've backed up ciphertext you cannot decrypt. [`docs/security/encrypted-keys.md`](../security/encrypted-keys.md) is explicit: *"There is no recovery"* for a lost master key — the only path back is re-issuing every provider key at the upstream provider. Store `LQ_AI_GATEWAY_MASTER_KEY` in your secrets vault, independently of any volume snapshot, the same way you'd store it for [rotating a leaked key](rotate-a-leaked-key.md).

> [!NOTE]
> **Professional duty** — `pgdata` holds the audit log and every chat a privileged matter produced — this is client-confidential material by construction, not an incidental side effect of backing it up. Wherever your backup lands (a snapshot service, an offsite volume, a second disk), it inherits the same confidentiality obligation the live deployment carries. `privilege_marked` rows in `audit_log` ([`docs/security/audit-logging.md`](../security/audit-logging.md)) mark which rows that applies to most directly, but the whole database is in scope — deciding who may read a backup, and under what encryption, is a call for whoever is responsible for those matters.

## Back it up

Run from the host, with the stack up (a hot backup of `pgdata` via `pg_dump` is consistent; a raw volume copy of a live `pgdata` is not):

1. **Postgres** — a logical dump, not a raw volume copy of `pgdata`:
   ```bash
   docker compose exec -T postgres pg_dump -U lq_ai -d lq_ai --format=custom \
     > lq-ai-postgres-$(date +%Y-%m-%d).dump
   ```
   Adjust `-U`/`-d` if you've overridden `POSTGRES_USER` / `POSTGRES_DB`.
2. **Object store (RustFS)** — mirror the bucket with the MinIO client (`mc`) against the exposed API port (`OBJECT_STORE_API_HOST_PORT`, default `9000`, with `MINIO_API_HOST_PORT` accepted as a legacy fallback through at least v0.10.0), or snapshot the `miniodata` volume directly while the stack is stopped:
   ```bash
   mc alias set lq-ai-backup http://localhost:9000 <OBJECT_STORE_ACCESS_KEY> <OBJECT_STORE_SECRET_KEY>
   mc mirror lq-ai-backup/lq-ai-files ./lq-ai-files-backup/
   ```
3. **Gateway config** — copy the volume's content, not only its existence. Compose derives the volume's name prefix from the project name, which varies by install (a plain checkout, a second clone, or the macOS desktop app's `-p lq-ai-desktop`) — look it up rather than assuming `lq-ai_`:
   ```bash
   docker volume ls --filter name=gateway-config
   # or: docker compose config --volumes
   docker run --rm -v <project>_gateway-config:/from -v "$PWD":/to alpine \
     tar czf /to/gateway-config-$(date +%Y-%m-%d).tar.gz -C /from .
   ```
4. **The master key** — confirm it's already in your secrets vault (see the caution above). Nothing to copy from the host; there's nothing on the host to copy.

## Restore

1. Bring up a fresh stack with the **same** `LQ_AI_GATEWAY_MASTER_KEY` you saved in step 4 above — set it in `.env` before the gateway container ever starts.
2. Restore Postgres into the fresh `postgres` container:
   ```bash
   docker compose exec -T postgres pg_restore -U lq_ai -d lq_ai --clean --if-exists \
     < lq-ai-postgres-2026-09-01.dump
   ```
3. Restore the object-store bucket (`mc mirror` in the reverse direction, or extract the volume snapshot into a fresh `miniodata` volume before first boot).
4. Restore the `gateway-config` tarball into a fresh `gateway-config` volume before the gateway container starts, so it doesn't re-seed from `gateway.yaml.example` instead.
5. Bring the stack up: `docker compose up -d`.
6. **Verify, don't assume.** Confirm the migration head matches what you expect (`docker compose exec api alembic current`), sign in, open a chat that existed before the incident, and confirm its history and any citations render. If provider keys were runtime-managed, open **Admin → Provider keys** and confirm each shows `configured` rather than a decrypt failure — a wrong or missing master key surfaces as `DecryptError` at adapter-build time per [`docs/security/encrypted-keys.md`](../security/encrypted-keys.md#verifying-the-setup), not as a restore error.

This is the general shape the compose volumes support, not a tested, ready-to-run script — file an issue (or contribute one) if you build a backup script from this and want it in the repository for the next operator.
