---
title: Install on macOS
description: Install the signed LQ.AI desktop app on Apple Silicon, and verify what you downloaded.
audience: [operator]
status: draft
sources:
  - docs/INSTALL-MAC.md
  - docs/BUILD-AND-RELEASE.md
  - docker-compose.release.yml
sidebar:
  order: 10
---

If you have a Mac with Apple Silicon and Docker Desktop, this is the fastest way to run LQ.AI: one signed app, no terminal, no cloned repository. Everything runs locally. Network is needed for the first-run download of the engine images **and the document-processing models** (`docs/INSTALL-MAC.md`) and, if you add a cloud provider key, for the inference calls you choose to make.

<!-- include: docs/INSTALL-MAC.md to="## 2. Install" -->

## Verify what you downloaded

Before you drag the app to Applications: the app is signed and notarized by Apple (Developer ID: Tucuxi, Inc.) — `docs/INSTALL-MAC.md` — and that is checkable rather than merely asserted. This is the same check the maintainer runs by hand against the published artifact — `docs/BUILD-AND-RELEASE.md` records it precisely because a green CI run is not proof the shipped `.dmg` is signed and stapled. The paragraph below is addressed to the release maintainer; what you need as a reader are the two commands under it.

<!-- include: docs/BUILD-AND-RELEASE.md from="### Verify the *published* artifact (not the CI exit code)" to="## See also" shift=1 -->

A `Rejected` or an unstapled result means you downloaded something other than the official release artifact — stop and get the file again from the [Releases page](https://github.com/LegalQuants/lq-ai/releases) rather than proceeding.

<!-- include: docs/INSTALL-MAC.md from="## 2. Install" -->

## When this isn't the right install

The app wraps `docker-compose.release.yml`, which runs the same eight services as the Docker Compose install plus a ninth, `proxy` (`lq-ai-proxy`), that puts the web shell and the api on one origin and owns the user-facing port. That means the two installs share most of their operational surface underneath — the same data in Postgres/MinIO, the same reset-admin-password `docker compose exec` escape hatch — but the release stack fronts everything through that proxy instead of exposing `web` directly. If you outgrow the app — you want to run on Linux, put a real domain in front of it, or edit `gateway.yaml` directly — the [Docker Compose](install-docker-compose.md) and [reverse proxy and TLS](reverse-proxy-tls.md) pages pick up from where this one stops.

Two things worth knowing before you rely on this for anything beyond evaluation: the launcher's shipped default pins the image tag to `latest` rather than the specific release the `.dmg` was verified against, so a fresh install can float to newer images than the one you checked with `spctl` and `stapler` above (`docs/BUILD-AND-RELEASE.md`); and app data splits across two places — the launcher's own state (an encrypted `config.enc` plus a chmod-600 `.env`) lives at `~/Library/Application Support/lq-ai-desktop/` (`docs/INSTALL-MAC.md`), while the chats, files and audit log live in the Docker named volumes the launcher's compose project creates (`pgdata`, `redisdata`, `miniodata`, `gateway-config`, `ingest-hf-cache`, `ingest-easyocr-cache` — `docker-compose.release.yml`), which Docker holds, not that directory. A backup plan for this install path has to cover both.

## Next

- [Reverse proxy and TLS](reverse-proxy-tls.md) — reach this deployment from another device.
- [Rotate a leaked provider key](rotate-a-leaked-key.md) — the same runtime key-management surface this app uses.
- [Troubleshooting](troubleshooting.md) — for anything not covered by the app's own **Logs** view.
