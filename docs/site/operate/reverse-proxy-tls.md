---
title: Reverse proxy and TLS
description: Put a stable, encrypted URL in front of LQ.AI — the shipped tailnet recipe, and what is still an open contribution.
audience: [operator]
status: draft
sources:
  - deploy/caddy-tailscale/README.md
  - docs/contribute/mini-prds/reverse-proxy-tls-deployment-recipes.md
  - docs/adr/0014-gateway-egress-boundary-for-tool-providers.md
  - deploy/tailnet-ollama/README.md
sidebar:
  order: 13
---

One deployment recipe for TLS ships today, and it's for a private tailnet rather than a public domain. If you want a publicly reachable HTTPS URL on your own domain, that recipe doesn't exist yet in this repository — see "What isn't here yet" before you go looking for it.

:::note[Professional duty]
Widening who can reach this deployment widens who can reach the client material in it. `CADDY_BIND_ADDR` decides that: `127.0.0.1` keeps it on loopback for `tailscale serve`, a `100.x.y.z` tailnet address keeps it inside your tailnet, and `0.0.0.0` publishes it on every host interface including LAN and WAN (`deploy/caddy-tailscale/README.md`). Who may reach a system holding privileged material — and what access controls your professional obligations require around it — is a call for whoever is responsible for those matters, not a default.
:::

<!-- include: deploy/caddy-tailscale/README.md -->

## Why the gateway stays off the proxy

The recipe above deliberately does not route the Inference Gateway through Caddy — admin access to it stays on `127.0.0.1`. That's not an oversight. Per [PRD §4](../../PRD.md#4-the-lq-ai-inference-gateway) the gateway is the only component holding privileged provider keys, and [ADR 0014](../../adr/0014-gateway-egress-boundary-for-tool-providers.md) fixes it as the platform's single audited egress boundary. Putting a second network path in front of it — even a private one — is a second thing to secure for no operational gain, since nothing your browser needs is served there.

The gateway applies the same discipline to its own outbound side: it refuses to send a provider request over plaintext HTTP to anything but a small allowlist of genuinely local targets, even across a private tailnet, and returns an explicit refusal rather than silently downgrading the connection. The [tailnet-Ollama recipe](recipes/tailnet-ollama.md) documents this refusal directly, with the exact error text and the HTTPS-based fix. If you see a similar refusal from the gateway on your own topology, read it as the boundary doing its job — the fix is almost always "use the HTTPS endpoint," not "route around it."

## What isn't here yet

A mini-PRD (`docs/contribute/mini-prds/reverse-proxy-tls-deployment-recipes.md`) proposes three public-domain recipes — Caddy, Traefik, and nginx, each terminating TLS at the proxy with Let's Encrypt or an operator-provided certificate — under `deploy/reverse-proxy/`. As of the checked commit it is **open for contribution**; none of the three exist in this repository. If your deployment needs a public domain rather than a private tailnet, there is no shipped recipe for it — you're building the equivalent of one of those three yourself, routing to `web` on `8080` and `api` on `8000` and leaving the gateway off the public path as above.

## Next

- [Air-gapped / local-only inference](air-gapped.md)
- [tailnet-Ollama recipe](recipes/tailnet-ollama.md) — the gateway's transport policy applied to a remote inference host
- [Install with Docker Compose](install-docker-compose.md)
