---
title: "Recipe: tailnet-hosted Ollama"
description: Point the gateway at Ollama running on a separate GPU host, reached over your tailnet, HTTPS-only.
audience: [operator]
status: draft
sources:
  - deploy/tailnet-ollama/README.md
sidebar:
  order: 32
---

**Problem.** Your local-inference GPU box isn't the same machine as the LQ.AI gateway — Ollama runs on separate hardware, and you want the gateway to reach it without exposing it to the public internet.

**Context.** Both machines need to be on the same Tailscale tailnet with MagicDNS and HTTPS Certificates enabled. This is a variant of the [Caddy + Tailscale](caddy-tailscale.md) pattern applied to a backend service instead of the web shell — same underlying mechanism (`tailscale serve` terminating HTTPS on loopback), different thing being served.

<!-- include: deploy/tailnet-ollama/README.md from="## Prerequisites" to="## Technical Details" -->

## Refusal errors explained

The gateway's egress policy is why step 3 above uses `https://`, not `http://`, even though Tailscale addresses look local. The next two sections are the exact reasoning and the exact refusal text, so you can match it if you hit it.

<!-- include: deploy/tailnet-ollama/README.md from="## Technical Details" to="## Alternatives to Tailscale Serve" shift=1 -->

## After you've set it

Step 3 above is explicit that setting `OLLAMA_BASE_URL` isn't enough on its own — you have to recreate or restart the gateway so the new value actually loads; an env-var edit with no restart leaves the gateway dispatching against whatever `base_url` it resolved at its last start. If step 4's `curl` succeeds against the tailnet endpoint but a chat routed through the gateway still fails, that's the most likely gap to check first.

This is one instance of a wider rule worth internalizing rather than memorizing per-recipe: any remote inference or tool-provider host reached over plaintext HTTP gets the same refusal unless it's on the guard's small local allowlist. Once you've seen the reasoning here, the same shape applies to a remote vLLM host, a self-hosted OpenAI-compatible server, or any other non-local `base_url` you point the gateway at.

## Next

- [Caddy + Tailscale](caddy-tailscale.md) — the same pattern, for the web shell
- [Air-gapped and local-only inference](../air-gapped.md) — a Tier-1 host on your own network isn't the same as air-gapped
- [Recipes](index.md)
