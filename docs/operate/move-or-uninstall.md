# Move machines or uninstall

Moving to new hardware and removing LQ.AI entirely share the same first half: get your data out. This page assumes you've already read [Backup and restore](backup-and-restore.md) — it doesn't repeat that procedure, only what's specific to moving or removing rather than recovering from an incident.

## Moving to a new host

1. Follow [Backup and restore](backup-and-restore.md) in full on the old host: a Postgres dump, an object-store (RustFS) mirror, and the `gateway-config` volume.
2. **Carry your `.env` secrets over unchanged** — `POSTGRES_PASSWORD`, `OBJECT_STORE_SECRET_KEY` (or the legacy `MINIO_ROOT_PASSWORD`), `LQ_AI_GATEWAY_KEY`, `JWT_SECRET`, and `LQ_AI_GATEWAY_MASTER_KEY` if you use encrypted-at-rest provider keys. These aren't in any volume; they exist only where you put them (your secrets vault, or the `.env` file itself). The restore steps in Backup and restore assume the new host has the same `LQ_AI_GATEWAY_MASTER_KEY` as the old one — without it, the `gateway-config` volume you moved decrypts into nothing.
3. Bring the stack up on the new host with the restored volumes and the same secrets, then run through the restore procedure's verification step before you decommission the old host.

## Uninstalling

**The macOS desktop app.** The one documented data-wipe path is the launcher's own **Reset…** button (two clicks to confirm), which [`docs/INSTALL-MAC.md`](../INSTALL-MAC.md#everyday-use) describes as erasing all LQ.AI data on the Mac and re-running first-time setup. Removing the app is more than dragging the bundle to the Trash: quit LQ.AI first; use **Reset…** (or take a backup, per [Backup and restore](backup-and-restore.md)) to drop the `-p lq-ai-desktop` Compose volumes; then delete `~/Library/Application Support/lq-ai-desktop/` — "an encrypted `config.enc` plus a chmod-600 `.env`" per [`docs/INSTALL-MAC.md`](../INSTALL-MAC.md) — since it holds the deployment's secrets and survives deleting the app; only then remove `LQ.AI.app` from Applications.

**Docker Compose.** `docker compose down` stops and removes the containers but leaves the named volumes (`pgdata`, `miniodata`, `gateway-config`, and the rest) in place — your data survives a `down` and comes back on the next `up`. Deleting the volumes too is a separate, explicit flag:

```bash
docker compose down -v
```

> [!CAUTION]
> **Before you run this** — `down -v` is not a confirmation prompt — it deletes every named volume in the compose file the moment it runs, and there is no undo. CLAUDE.md carries this as a hard rule for the project's own dev environment for exactly this reason: *"NEVER `docker compose down -v` — it wipes volumes including expensive-to-recreate acceptance data. Rebuild a single service instead."* That rule is written for contributors working against a dev stack, but the mechanism it warns about is identical on a production deployment: `pgdata` and `miniodata` are gone the instant the command completes, with no confirmation step in between.

> [!NOTE]
> **Professional duty** — Decommissioning a deployment destroys client matter records and the audit trail that evidences what left the deployment, so record-retention and client-file obligations bear on whether a full export must be preserved (and for how long) before the volumes go — a call for whoever is responsible for those matters, not an infrastructure decision. No jurisdiction's retention period is universal; this page states none.

Run `-v` only once you've completed and **verified** a restore-tested backup per [Backup and restore](backup-and-restore.md) — verified means you've actually restored it somewhere and confirmed a chat loads, not only that the dump file exists on disk.

## What to export, either way

If you want a record rather than a running restore — closing out a deployment, or handing off to someone who only needs the data, not the infrastructure — the same three artifacts from Backup and restore (Postgres dump, object-store mirror, `gateway-config` snapshot) are the complete export. Per-user GDPR-aligned exports are a separate, narrower mechanism — a single user's own data via `POST /api/v1/users/me/export` (polled at `GET /api/v1/users/me/export/{job_id}`), with `POST /api/v1/users/me/delete` as the Article 17 deletion path — the export and deletion workers named in `docs/HONEST-STATE.md` §1 (`api/app/workers/user_export.py`, `api/app/workers/user_deletion.py`, `api/app/api/users.py`) — not a substitute for a full-deployment export.
