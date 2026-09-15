---
title: Recipes
description: Topology-specific deployment instructions, one format — problem, context, steps, verify, and the refusal errors explained.
audience: [operator]
status: draft
sources:
  - deploy/caddy-tailscale/README.md
  - deploy/tailnet-ollama/README.md
  - deploy/observability/README.md
sidebar:
  order: 30
---

A recipe answers one specific topology question — not "how do I run LQ.AI" (that's [Install](../index.md)), but "how do I run it *this* way." Every recipe in this section follows the same shape, so once you've read one you know where to find the part you need in the next:

- **Problem** — the one-sentence situation the recipe is for.
- **Context** — how it relates to the other options, so you can bail out to a different recipe if you picked the wrong one.
- **Steps** — the commands, in order, copy-pasteable from the source `README.md` this recipe curates.
- **Verify** — a command whose output tells you the recipe actually worked, not only that nothing errored.
- **Refusal errors explained** — where the gateway's egress guard or another fail-closed control refuses a configuration this recipe touches, the recipe names the exact refusal text and why it's there — not a bug to route around, a boundary doing its job.

## Which hosting shape is mine?

If you haven't picked a topology yet, [Operate → Which hosting shape is mine?](../index.md#which-hosting-shape-is-mine) is the index — one row per shape, its status (recipe published / known to work / not tried), and which page or recipe covers it.

A shape marked **not tried** has no page below because nothing in the repository documents it as of the checked commit — not because it's known to fail. If you make one of those shapes work (a Windows host, a corporate cloud VM, a public-domain reverse proxy), you're the person with the evidence to file the recipe: open a PR against `docs/site/operate/recipes/` in the same problem/context/steps/verify/refusal-errors shape as the ones below, and update the shape's row in [`_data/supported-shapes.yaml`](../../_data/supported-shapes.yaml) from "not tried" to "recipe published."

## The recipes

- **[Caddy + Tailscale](caddy-tailscale.md)** — a private, tailnet-only URL with auto-renewing HTTPS and no public DNS or open inbound ports.
- **[tailnet-Ollama](tailnet-ollama.md)** — the gateway reaching a local-inference model on a separate GPU host over your tailnet, HTTPS-only by the gateway's own egress policy.
- **[Observability](observability.md)** — wiring a traces/metrics backend, self-hosted or against an existing SaaS collector.

## Next

- [Operate](../index.md)
- [Air-gapped and local-only inference](../air-gapped.md)
- [Reverse proxy and TLS](../reverse-proxy-tls.md)
