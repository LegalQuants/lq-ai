# Update LQ.AI

Record your current version, make a backup you can restore, and read the new release's notes before updating.

## Updating the source

If you run the pre-built stack, there's no local source checkout to update — skip ahead to choosing the release tag below. If you build from source, updating means moving your checkout to the release tag you're targeting, not merging in local history. If you have local edits or extra commits on top of the previous release, review and resolve them before you switch tags.

## Updating the running app

Build or download the version you're targeting and recreate the services as needed. Moving back to an older app version may also require restoring its database — older code may not understand schema changes made by a newer version.

### Details

Back up before you touch anything: take a Postgres dump and a `gateway-config` snapshot per [Backup and restore](backup-and-restore.md). A schema migration that turns out to be wrong is much cheaper to walk back from a dump than from a half-migrated live database.

## Choose the release and installation method

For prebuilt images, set `LQ_AI_IMAGE_TAG` in `.env` to the target release tag — not `latest`:

```bash
# .env
LQ_AI_IMAGE_TAG=v0.8.0
```

then pull:

```bash
docker compose -f docker-compose.release.yml pull
```

For a source installation, fetch the tag and check it out instead:

```bash
git fetch --tags && git checkout v0.8.0
```

then rebuild in the next step — a source build only picks up new code on `--build`.

A locally-built desktop launcher still defaults to the floating `latest` tag ([Release versioning](../adr/0025-release-versioning-and-pipeline-ordering.md) describes this as a historical gap); signed release builds now bake in their own version tag. Either way, don't repeat the `latest`-floating pattern on a server deployment you control, where pinning is one line, as above.

### Operator-action releases

Some releases need more than a pull and rebuild. Read the target release's own notes under [`docs/releases/`](../releases/) before you upgrade, not after something fails to start — every release states plainly whether it needs operator action. `v0.7.0` is the worked example the [Release versioning](../adr/0025-release-versioning-and-pipeline-ordering.md) ADR itself uses: three of its changes required action, called out in an explicit "Operator note" — the gateway started requiring a key on every inference call, an install still on the published dev `JWT_SECRET` would refuse to boot, and a provider `base_url` over plaintext HTTP to a non-local host became a fatal startup error.

The most recent release as of the checked commit, [`v0.8.0`](../releases/v0.8.0.md), is squarely this kind: it replaces the bundled MinIO image (which became unavailable) with RustFS, and existing bundled-store installations must snapshot and migrate their object-store volume before RustFS starts — the ordinary pull-and-rebuild steps on this page are not sufficient for that release on their own. Follow the dedicated [MinIO to RustFS migration runbook](../runbooks/minio-to-rustfs.md) instead of those steps if you are moving a bundled-store deployment across that boundary; it covers prerequisites, the `pg_dump` and free-space checks, the exact Compose commands, the macOS launcher's own migration path (the old launcher cannot perform it and must be replaced), Helm and external/multi-drive paths, and rollback. `docker compose down -v` must not be run during that migration, same as everywhere else on this page. Legacy `MINIO_*` environment variables are accepted as a fallback for the new `OBJECT_STORE_*` names through at least v0.10.0, so an existing `.env` does not need to be renamed to take the release.

For any other release, read its own notes for an "Operator action" section before assuming the ordinary steps on this page are enough.

## Update the API and workers together

The `api` container is the sole schema migrator — it runs `alembic upgrade head` on boot. `ingest-worker` and `arq-worker` set `LQ_AI_SKIP_MIGRATIONS=1` and wait on `api`'s health check before starting. Keep `api`, `ingest-worker`, and `arq-worker` on the same version and rebuild them together with any other changed services — CLAUDE.md's own dev-environment rule states the consequence directly: rebuild `api` + `arq-worker` + `ingest-worker` together whenever a migration lands, because stale siblings crash-loop on a revision mismatch if you bring up a new `api` against old worker images (or vice versa).

If you run the pre-built stack:

```bash
docker compose -f docker-compose.release.yml up -d
```

If you build from source:

```bash
docker compose up -d --build api arq-worker ingest-worker gateway web
```

Running `up -d` alone, without a `pull` (pre-built stack) or `--build` (source) behind it, starts the old images with no error — the desktop launcher's own `pull` step exists for exactly this reason (`desktop/src/core/compose.ts`). The next step's `alembic current` output, plus the running image tag from `docker compose images`, is the only signal the upgrade actually took.

## Confirm the update worked

Check the running image tag and the applied migration:

```bash
docker compose images
docker compose exec api alembic current
```

Confirm the output names the head revision the target release's Schema section states, when it gives one. Then sign in, open an existing chat, and confirm it loads — a migration that "succeeds" but leaves the app unable to read its own data is the failure this step exists to catch, not the alembic exit code alone.

If startup fails instead, inspect `docker compose ps` and `docker compose logs api` — see the next section for what that failure looks like and how to recover.

## If you need to go back

Read the target release's own notes for a reversibility note before you upgrade. Keep the previous image tag (or source checkout) and a matching backup on hand. Some migration `downgrade()` functions deliberately do not undo every change, so do not assume a downgrade will restore the old state — a rehearsed restore from a backup is the more dependable basis for a rollback plan.

### If it fails halfway

The same health-check dependency means a migration failure is loud, not partial: `api` fails its health check, and both workers — gated on `api: condition: service_healthy` — never start rather than running against a half-migrated schema. `docker compose ps` shows `api` unhealthy; `docker compose logs api` carries the alembic error.

Every migration in this repository defines a `downgrade()` step, but "defines one" and "safely reverses the upgrade" are not the same claim — some are deliberately written as no-ops when reversing would destroy data written since the upgrade (migration `0066` is exactly this case: it declines to delete rows a downgrade can no longer distinguish from legitimately created ones). Before running `alembic downgrade <previous-revision>`, read that migration's own `downgrade()` function, or read the release's Schema section for a reversibility note if it gives one — not every release notes this explicitly, so treat its absence as unstated rather than as a promise either way. The more conservative rollback is restoring the Postgres dump you took earlier and redeploying the previous image tag, rather than trusting an untested downgrade path on a live database.
