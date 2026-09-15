---
title: Upgrade
description: The runbook for taking a new release — read the notes, back up, rebuild the right services together, and verify.
audience: [operator]
status: draft
sources:
  - docs/adr/0025-release-versioning-and-pipeline-ordering.md
  - docs/releases/v0.7.0.md
  - docker-compose.yml
  - docker-compose.release.yml
  - CLAUDE.md
  - desktop/src/core/compose.ts
sidebar:
  order: 24
---

[Release versioning](../reference/versioning.md) explains what a patch vs. a minor bump promises. This page is the procedure that applies that promise to a running deployment — read that page first if you haven't; this one assumes you have.

## 1. Read the release notes before you touch anything

Every release under [ADR 0025](../../adr/0025-release-versioning-and-pipeline-ordering.md) states plainly whether it needs operator action. `v0.7.0` is the worked example the ADR itself uses: three of its changes required action, called out in an explicit "Operator note" — the gateway started requiring a key on every inference call, an install still on the published dev `JWT_SECRET` would refuse to boot, and a provider `base_url` over plaintext HTTP to a non-local host became a fatal startup error. Find the target release's notes under [Changelog](../changelog/index.intro.md) and read the equivalent note before you upgrade, not after something fails to start.

## 2. Back up first

Take a Postgres dump and a `gateway-config` snapshot per [Backup and restore](backup-and-restore.md) before you touch the image tags. A schema migration that turns out to be wrong is much cheaper to walk back from a dump than from a half-migrated live database.

## 3. Pull the new images

If you run the pre-built stack (`docker-compose.release.yml`), set `LQ_AI_IMAGE_TAG` in `.env` to the target release tag — not `latest`. [Release versioning](../reference/versioning.md) already notes that the desktop launcher still defaults to the floating `latest` tag as an open gap; don't repeat that gap on a server deployment you control, where pinning is one line:

```bash
# .env
LQ_AI_IMAGE_TAG=v0.7.0
```

```bash
docker compose -f docker-compose.release.yml pull
```

If you build from source (`docker-compose.yml`), pull the matching tag of the repository instead (`git fetch --tags && git checkout v0.7.0`), then rebuild the images yourself in step 4 — a source build only picks up new code on `--build`.

## 4. Rebuild the right services together

The `api` container is the sole schema migrator — it runs `alembic upgrade head` on boot; `ingest-worker` and `arq-worker` set `LQ_AI_SKIP_MIGRATIONS=1` and wait on `api`'s health check before starting (`docker-compose.yml`). CLAUDE.md's own dev-environment rule states the consequence directly: **when a migration lands, rebuild `api` + `arq-worker` + `ingest-worker` together** — stale siblings crash-loop on a revision mismatch if you bring up a new `api` against old worker images (or vice versa) instead of moving all three at once.

If you run the pre-built stack:

```bash
docker compose -f docker-compose.release.yml up -d
```

If you build from source:

```bash
docker compose up -d --build api arq-worker ingest-worker gateway web
```

An `up -d` with neither `pull` (release path) nor `--build` (source path) behind it starts the old images with no error — the desktop launcher's own `pull` step exists for exactly this reason: `up -d` alone "reuses whatever `:latest` (or pinned tag) is already cached locally and never picks up a new release" (`desktop/src/core/compose.ts`). Step 5's `alembic current` output plus the running image tag (`docker compose images`) is the only signal the upgrade actually took.

## 5. Verify

```bash
docker compose exec api alembic current
```

Confirm the output names the head revision the target release's Schema section states. Then sign in, open an existing chat, and confirm it loads — a migration that "succeeds" but leaves the app unable to read its own data is the failure this step exists to catch, not the alembic exit code alone.

## If it fails halfway

The dependency chain in step 4 means a migration failure is loud, not partial: `api` fails its health check, and both workers — gated on `api: condition: service_healthy` — never start rather than running against a half-migrated schema. `docker compose ps` shows `api` unhealthy; `docker compose logs api` carries the alembic error.

Every migration in this repository defines a `downgrade()` step, but "defines one" and "safely reverses the upgrade" are not the same claim — some are deliberately written as no-ops when reversing would destroy data written since the upgrade (migration `0066` is exactly this case: it declines to delete rows a downgrade can no longer distinguish from legitimately created ones). Before running `alembic downgrade <previous-revision>`, read that migration's own `downgrade()` function, or read the release's Schema section for a reversibility note if it gives one — not every release notes this explicitly, so treat its absence as unstated rather than as a promise either way. The more conservative rollback is restoring the Postgres dump you took in step 2 and redeploying the previous image tag, rather than trusting an untested downgrade path on a live database.

## Next

- [Release versioning](../reference/versioning.md)
- [Backup and restore](backup-and-restore.md)
- [Changelog](../changelog/index.intro.md)
- [Something is wrong](something-is-wrong.md)
