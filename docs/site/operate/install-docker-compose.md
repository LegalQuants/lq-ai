---
title: Install with Docker Compose
description: The reference deployment — clone, configure, and run LQ.AI's eight services with Docker Compose.
audience: [operator]
status: draft
sources:
  - docs/adr/0026-document-ingestion-parser-and-docling.md
  - README.md
  - docker-compose.yml
  - docs/quickstart.md
  - .env.example
  - docs/security/encrypted-keys.md
sidebar:
  order: 11
---

LQ.AI is a self-hosted AI platform for in-house legal teams: it runs in your environment, on your own provider keys. Everything it stores — chats, files, the audit log — stays in containers on this host; the Inference Gateway is the only component that makes an outbound call, and only to the provider you configure ([what it touches](../start/what-it-touches.md), [trust centre](../trust/index.md)).

This is the reference deployment every other install path builds on — the macOS app runs a variant of this same compose file, and the Helm chart mirrors its service list. If you're comfortable with Docker and want the full service set under your own control, start here.

<!-- include: README.md from="## Quick Start" to="## Architecture" -->

## What's actually running

Eight services start by default — `postgres`, `redis`, `minio`, `gateway`, `api`, `ingest-worker`, `arq-worker`, `web` — plus whichever Compose profiles you opt into: `--profile local` adds the `ollama` sidecar for local inference, `--profile slack` and `--profile teams` add the chat-platform intake bridges. Every host port the stack publishes binds to `127.0.0.1` by default (`docker-compose.yml`), so a fresh `docker compose up -d` does not expose anything to your LAN or the public internet on its own — that's a deliberate default, not an accident, and it's why the [reverse proxy and TLS](reverse-proxy-tls.md) page exists as a separate step rather than something this one does for you.

The four required `.env` variables (`POSTGRES_PASSWORD`, `MINIO_ROOT_PASSWORD`, `LQ_AI_GATEWAY_KEY`, `JWT_SECRET`) are enforced at the Compose level — the stack refuses to start without them, naming whichever is missing. `LQ_AI_GATEWAY_MASTER_KEY` is optional but worth setting at install time: without it, the admin provider-keys and research-source screens return an error rather than working. The gateway binds the master key at process start (`docs/security/encrypted-keys.md`), so adding it later means restarting the gateway.

## Where your data lives

Everything the stack writes lands in seven named Compose volumes: `pgdata` (Postgres — chats, projects, the audit log, embeddings), `redisdata`, `miniodata` (uploaded files), `gateway-config` (the live `gateway.yaml`, including anything you set through the admin key screens), `ingest-hf-cache` and `ingest-easyocr-cache` (the ingest-worker's Docling and EasyOCR model caches — "persisting these volumes across `docker compose down` cycles avoids repeated ~700MB model downloads on first ingestion", per ADR 0006, `docker-compose.yml`; [ADR 0026](../../adr/0026-document-ingestion-parser-and-docling.md) has since found that the Docling pass never produced output and decided its removal, so these two volumes go with it), and, if you opt into local inference, `ollamadata`. None of these live inside a container — `docker compose down` on its own leaves them intact; only `-v` removes them, and CLAUDE.md's own dev-environment rules flag `down -v` as the thing never to run without a backup first. Treat that list as the scope of your [backup and restore](backup-and-restore.md) plan once you have one.

If you run two clones of this repository side by side, note that Compose derives its project name from the parent directory — two checkouts both named `lq-ai/` will silently share the volumes above (database, admin user, MinIO objects included), and tearing down one tears down both. Set a distinct `COMPOSE_PROJECT_NAME` in each `.env` to keep them apart.

## Next

- [Reverse proxy and TLS](reverse-proxy-tls.md) — put this behind a stable, encrypted URL.
- [Air-gapped / local-only inference](air-gapped.md) — the same stack with `--profile local`.
- [Architecture](architecture.md) — how these eight services fit together.
