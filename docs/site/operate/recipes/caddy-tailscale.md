---
title: "Recipe: Caddy + Tailscale"
description: The runnable steps for a private, tailnet-only URL with auto-renewing HTTPS — no public DNS, no open inbound ports.
audience: [operator]
status: draft
sources:
  - deploy/caddy-tailscale/README.md
sidebar:
  order: 31
---

**Problem.** You want the LQ.AI web shell reachable from more than one device, but only from devices on your own tailnet — not the public internet — and you don't want to run Let's Encrypt or manage a certificate yourself.

**Context.** This is the tailnet alternative to a public-domain reverse proxy: Caddy routes plain HTTP inside the Compose network, and the host's own Tailscale terminates HTTPS and issues the certificate — Caddy issues none of its own. If you need a publicly reachable domain instead, this isn't that recipe; see [Reverse proxy and TLS](../reverse-proxy-tls.md) for the fuller explanation of why the gateway itself is deliberately left off any proxy, public or private, and for what a public-domain recipe would need (none ships yet).

<!-- include: deploy/caddy-tailscale/README.md from="## Prerequisites" to="## Configuration" -->

## Refusal errors explained

This recipe has no LQ.AI-side refusal of its own — Caddy speaks plain HTTP internally and the gateway isn't routed through it at all. If `tailscale serve` itself prompts you with a consent URL instead of running, that's Tailscale asking you to enable **MagicDNS** and **HTTPS Certificates** for the tailnet, a one-time admin-console step, not a fail-closed control in this repository.

## What's actually persisted

Caddy's `/data` (its own state) and `/config` (its autosave config) live in the `caddy-data` and `caddy-config` named volumes — a `docker compose down` between restarts doesn't lose them; only an explicit `-v` would. The `tailscale serve --bg` command itself lives in the **host's** Tailscale configuration, outside any container, and survives both host and stack reboots — you run it once, not on every `docker compose up`.

If you'd rather skip `tailscale serve` and bind Caddy straight to the host's Tailscale IP instead, the source README documents that path too (`CADDY_BIND_ADDR` set to `tailscale ip -4`) — plain HTTP over the tailnet rather than TLS, which the source recommends against for cookie and Service Worker behavior. This recipe's quick start above is the recommended path for exactly that reason.

## Next

- [Reverse proxy and TLS](../reverse-proxy-tls.md) — why the gateway stays off the proxy, and the routing/configuration detail this recipe leaves out
- [tailnet-Ollama](tailnet-ollama.md) — the same Tailscale pattern, applied to a remote inference host instead of the web shell
- [Recipes](index.md)
