# Move or remove an installation

Keep the old installation available until you've checked the new one. Moving LQ.AI means moving its data, settings and the keys needed to read them. This page assumes you've already read [Backup and restore](backup-and-restore.md) — it doesn't repeat that procedure, only what's specific to moving or removing rather than recovering from an incident.

## Before moving

Include the database, uploaded files, the working `gateway.yaml` and the gateway master key. Some settings and secrets live in `.env` on the host computer, outside Docker's data volumes.

1. On the old host, run [Backup and restore](backup-and-restore.md) in full: a Postgres dump, an object-store (RustFS) mirror, and a copy of the `gateway-config` volume.
2. Carry your `.env` secrets over unchanged — `POSTGRES_PASSWORD`, `OBJECT_STORE_SECRET_KEY` (or the legacy `MINIO_ROOT_PASSWORD`), `LQ_AI_GATEWAY_KEY`, `JWT_SECRET`, and `LQ_AI_GATEWAY_MASTER_KEY` if you use encrypted-at-rest provider keys. None of these live in a volume — they exist only where you put them, in your secrets vault or the `.env` file itself. The new host needs the **same** `LQ_AI_GATEWAY_MASTER_KEY` as the old one: without it, the `gateway-config` volume you moved decrypts into nothing.
3. Bring the stack up on the new host with the restored volumes and the same secrets, then run through Backup and restore's verification step before you decommission the old host.

## Before deleting anything

Check which Compose project and volumes you're removing. Keep recovery copies until you've decided what data must be retained.

> [!NOTE]
> **Professional duty** — Decommissioning a deployment destroys client matter records and the audit trail that evidences what left the deployment, so record-retention and client-file obligations bear on whether a full export must be preserved (and for how long) before the volumes go — a call for whoever is responsible for those matters, not an infrastructure decision. No jurisdiction's retention period is universal; this page states none.

## Stopping is different from deleting

Stopping containers keeps their named data volumes: `docker compose down` stops and removes the containers but leaves `pgdata`, `miniodata`, `gateway-config` and the rest in place — your data survives a `down` and comes back on the next `up`. Deleting the volumes too is a separate, explicit flag:

```bash
docker compose down -v
```

> [!CAUTION]
> **Before you run this** — `down -v` is not a confirmation prompt — it deletes every named volume in the compose file the moment it runs, and there is no undo. CLAUDE.md carries this as a hard rule for the project's own dev environment for exactly this reason: *"NEVER `docker compose down -v` — it wipes volumes including expensive-to-recreate acceptance data. Rebuild a single service instead."* That rule is written for contributors working against a dev stack, but the mechanism it warns about is identical on a production deployment: `pgdata` and `miniodata` are gone the instant the command completes, with no confirmation step in between.

Run `-v` only once you've completed and **verified** a restore-tested backup per [Backup and restore](backup-and-restore.md) — verified means you've actually restored it somewhere and confirmed a chat loads, not only that the dump file exists on disk.

Removing a desktop application does not necessarily remove its Docker data or host configuration — inventory both before you uninstall.

**The macOS desktop app.** The one documented data-wipe path is the launcher's own **Reset…** button (two clicks to confirm), which [`docs/INSTALL-MAC.md`](../INSTALL-MAC.md#everyday-use) describes as erasing all LQ.AI data on the Mac and re-running first-time setup. Removing the app is more than dragging the bundle to the Trash: quit LQ.AI first; use **Reset…** (or take a backup, per [Backup and restore](backup-and-restore.md)) to drop the `-p lq-ai-desktop` Compose volumes; then delete `~/Library/Application Support/lq-ai-desktop/` — "an encrypted `config.enc` plus a chmod-600 `.env`" per [`docs/INSTALL-MAC.md`](../INSTALL-MAC.md) — since it holds the deployment's secrets and survives deleting the app; only then remove `LQ.AI.app` from Applications.

## Keeping a record instead of a full restore

If you want a record rather than a running restore — closing out a deployment, or handing off to someone who only needs the data, not the infrastructure — the same three artifacts from [Backup and restore](backup-and-restore.md) (a Postgres dump, an object-store mirror, and a `gateway-config` snapshot) are the complete export.

A narrower option also exists: a single user can export just their own data via `POST /api/v1/users/me/export` (poll `GET /api/v1/users/me/export/{job_id}`), with `POST /api/v1/users/me/delete` as the GDPR Article 17 deletion path. These are the export and deletion workers named in `docs/HONEST-STATE.md` §1 (`api/app/workers/user_export.py`, `api/app/workers/user_deletion.py`, `api/app/api/users.py`) — not a substitute for a full-deployment export.
