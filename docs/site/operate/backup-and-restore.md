---
title: Back up and restore
description: What actually has to survive a disaster, what's safe to lose, and a restore runbook that ends in a verification step.
audience: [operator]
status: draft
sources:
  - docker-compose.yml
  - docker-compose.release.yml
  - docs/db-schema.md
  - docs/security/encrypted-keys.md
  - docs/security/audit-logging.md
sidebar:
  order: 23
---

No runbooks directory exists in this repository as of the checked commit, and no `pg_dump` or restore script ships anywhere in it — this page is built from the compose files' own volume declarations and the schema doc, not curated from an existing backup guide. Where the repository is silent on a step, this page says so.

## What has to survive

| Named volume | Holds | If you lose it |
|---|---|---|
| `pgdata` | Every relational row — users, chats, messages, projects, audit log, citations, playbooks, skills you've forked into the DB | Everything: history, matter context, the audit trail |
| `miniodata` | Uploaded file bytes and export bundles, referenced by `files.storage_path` in Postgres | Every document ever uploaded, even though the DB rows describing them survive |
| `gateway-config` | The live `gateway.yaml`, including any `api_key_encrypted` tokens the runtime provider-key surface has written | Every runtime-managed provider key, and any model-alias edits made in-app |
| `redisdata` | The arq job queue and rate-limit counters | Nothing durable — in-flight background jobs, not history |
| `ollamadata`, `ingest-hf-cache`, `ingest-easyocr-cache` | Downloaded model weights and layout/OCR models | Nothing you can't re-pull; costs bandwidth and time, not data |

The first three are the ones a restore actually depends on. The last three are caches — recreate them by re-pulling, not by restoring.

:::caution[Silent failure]
The `LQ_AI_GATEWAY_MASTER_KEY` that decrypts every `api_key_encrypted` token in `gateway-config` is **not stored in any volume** — it lives only in the gateway process's environment (`docker-compose.yml`, `docker-compose.release.yml`). Back up the `gateway-config` volume without also backing up this value separately, and you've backed up ciphertext you cannot decrypt. [`docs/security/encrypted-keys.md`](../../security/encrypted-keys.md) is explicit: *"There is no recovery"* for a lost master key — the only path back is re-issuing every provider key at the upstream provider. Store `LQ_AI_GATEWAY_MASTER_KEY` in your secrets vault, independently of any volume snapshot, the same way you'd store it for [rotating a leaked key](rotate-a-leaked-key.md).
:::

:::note[Professional duty]
`pgdata` holds the audit log and every chat a privileged matter produced — this is client-confidential material by construction, not an incidental side effect of backing it up. Wherever your backup lands (a snapshot service, an offsite volume, a second disk), it inherits the same confidentiality obligation the live deployment carries. `privilege_marked` rows in `audit_log` ([`docs/security/audit-logging.md`](../../security/audit-logging.md)) mark which rows that applies to most directly, but the whole database is in scope — deciding who may read a backup, and under what encryption, is a call for whoever is responsible for those matters.
:::

## Back it up

Run from the host, with the stack up (a hot backup of `pgdata` via `pg_dump` is consistent; a raw volume copy of a live `pgdata` is not):

1. **Postgres** — a logical dump, not a raw volume copy of `pgdata`:
   ```bash
   docker compose exec -T postgres pg_dump -U lq_ai -d lq_ai --format=custom \
     > lq-ai-postgres-$(date +%Y-%m-%d).dump
   ```
   Adjust `-U`/`-d` if you've overridden `POSTGRES_USER` / `POSTGRES_DB`.
2. **MinIO** — mirror the bucket with the MinIO client (`mc`) against the exposed API port (`MINIO_API_HOST_PORT`, default `9000`), or snapshot the `miniodata` volume directly while the stack is stopped:
   ```bash
   mc alias set lq-ai-backup http://localhost:9000 <MINIO_ROOT_USER> <MINIO_ROOT_PASSWORD>
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
3. Restore the MinIO bucket (`mc mirror` in the reverse direction, or extract the volume snapshot into a fresh `miniodata` volume before first boot).
4. Restore the `gateway-config` tarball into a fresh `gateway-config` volume before the gateway container starts, so it doesn't re-seed from `gateway.yaml.example` instead.
5. Bring the stack up: `docker compose up -d`.
6. **Verify, don't assume.** Confirm the migration head matches what you expect (`docker compose exec api alembic current`), sign in, open a chat that existed before the incident, and confirm its history and any citations render. If provider keys were runtime-managed, open **Admin → Provider keys** and confirm each shows `configured` rather than a decrypt failure — a wrong or missing master key surfaces as `DecryptError` at adapter-build time per [`docs/security/encrypted-keys.md`](../../security/encrypted-keys.md#verifying-the-setup), not as a restore error.

This is the general shape the compose volumes support, not a tested, ready-to-run script — file an issue (or contribute one) if you build a backup script from this and want it in the repository for the next operator.

## Next

- [Rotate a leaked provider key](rotate-a-leaked-key.md)
- [Upgrade](upgrade.md)
- [Move machines or uninstall](move-or-uninstall.md)
