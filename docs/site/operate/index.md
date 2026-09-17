---
title: Operate LQ.AI
description: Install, secure, and run LQ.AI in your own environment — indexed by hosting shape.
audience: [operator, evaluator]
status: draft
sources:
  - docs/INSTALL-MAC.md
  - README.md
  - deploy/helm/lq-ai/Chart.yaml
  - deploy/caddy-tailscale/README.md
  - docs/contribute/mini-prds/reverse-proxy-tls-deployment-recipes.md
  - deploy/tailnet-ollama/README.md
  - docs/site/_data/supported-shapes.yaml
sidebar:
  order: 1
---

This is the operator's namespace: getting LQ.AI running, keeping it running, and knowing what to do when it doesn't. Start with install; come back for the week-two work once it's up.

## Install

Five install paths have a recipe today. Pick the one that matches how you plan to run LQ.AI — each page names what it covers and what it doesn't.

- **[macOS desktop app](install-macos.md)** — a signed, notarized launcher for Apple Silicon. No terminal, no cloned repository.
- **[Docker Compose](install-docker-compose.md)** — the reference deployment: clone, edit `.env`, `docker compose up -d`.
- **[Kubernetes via Helm](install-helm.md)** — a chart for the core chat services. Read the page before you rely on it for more than that.
- **[Reverse proxy and TLS](reverse-proxy-tls.md)** — putting a certificate and a stable URL in front of either install above.
- **[Air-gapped / local-only inference](air-gapped.md)** — the same Compose stack with local inference instead of a cloud key, and what's actually been verified about its network behavior.

## Which hosting shape is mine?

<!-- supported-shapes -->

If your shape isn't on this list, treat it as untried: nothing in the repository documents it as of the checked commit. The table is rendered at build time from [`_data/supported-shapes.yaml`](../_data/supported-shapes.yaml), so what you read here and what the repository records are the same list.

## Week two — keeping it running

Once LQ.AI is up: [hardware sizing](hardware-sizing.md), [backup and restore](backup-and-restore.md), [upgrading](upgrade.md), [rotating a leaked provider key](rotate-a-leaked-key.md), and [triage when something is wrong](something-is-wrong.md). [Moving or uninstalling](move-or-uninstall.md) and the [troubleshooting index](troubleshooting.md) round these out.

## Building against LQ.AI

[Headless boot](headless-boot.md) is the one page on running the stack without the web UI — acknowledged, not supported, no compatibility promised.

## Recipes

The [recipes index](recipes/index.md) collects topology-specific instructions in one format: problem, context, steps, verify, and the refusal errors you might hit.

## Next

- [Is LQ.AI for you?](../start/is-it-for-you.md)
- [Trust centre](../trust/index.md) — the security and compliance picture behind this operational one.
- [Skills](../skills/index.md)
