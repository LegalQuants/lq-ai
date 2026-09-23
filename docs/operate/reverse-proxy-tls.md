# Reverse proxy and TLS

`docker compose up -d` binds every published port to `127.0.0.1` by default — a
fresh install is not reachable from another device until you put a reverse proxy in
front of it. Two shapes of recipe ship in this repository today, covering different
audiences:

| Recipe | Reachable from | Certificates | Where |
| --- | --- | --- | --- |
| [Caddy + Tailscale](../../deploy/caddy-tailscale/README.md) | Your tailnet only, no public DNS | Tailscale (auto-renewing) | [`deploy/caddy-tailscale/`](../../deploy/caddy-tailscale/) |
| Caddy / Traefik / nginx | A public FQDN | Let's Encrypt (Caddy, Traefik) or operator-provided (nginx) | [`deploy/reverse-proxy/`](../../deploy/reverse-proxy/) |

Pick the tailnet recipe if you want a private, share-with-the-team URL and don't want
to manage public DNS or certificates yourself — see
[Recipe: Caddy + Tailscale](../../deploy/caddy-tailscale/README.md) for the runnable steps. Pick
one of the three public-domain recipes under `deploy/reverse-proxy/` if you need a
publicly resolvable domain; each is a Docker Compose overlay with its own README
covering setup, the smoke checks, and what "reference configuration, not a supported
production distribution" means for that proxy. All four share the same upstream
routing shape (path-based split between `web` and `api`, the gateway left off the
proxy — see below).

OpenWebUI's embedded backend and LQ.AI's API are separate services on that split, so
a homepage that loads only proves `/` reached `web`. Check a streamed chat answer
before trusting a new proxy — the shared smoke checks in
[`deploy/reverse-proxy/README.md`](../../deploy/reverse-proxy/README.md#smoke-checks-all-recipes)
(health, the api's 401 on `/lq-ai-api/v1/skills`, the `/ws/socket.io/` probe, and
streaming) are what show both `/api/v1` namespaces landed on the right service. Try a
document upload too — nginx caps body size explicitly (`client_max_body_size`) while
Caddy and Traefik don't by default — even though it isn't one of the scripted checks.

> [!CAUTION]
> **Silent failure** — `docker run --rm ghcr.io/testssl/testssl.sh:3.2 https://<fqdn>`
> and each recipe's smoke checks confirm the proxy is *working*; none of them are a
> substitute for reading the HSTS warning in the `deploy/reverse-proxy/` recipes
> before enabling `Strict-Transport-Security` — `preload` in particular is a one-way
> door that can take months to undo if your certificate pipeline ever breaks.

> [!NOTE]
> **Professional duty** — Widening who can reach this deployment widens who can reach
> the client material in it. For the tailnet recipe, `CADDY_BIND_ADDR` decides that:
> `127.0.0.1` keeps it on loopback for `tailscale serve`, a `100.x.y.z` tailnet
> address keeps it inside your tailnet, and `0.0.0.0` publishes it on every host
> interface including LAN and WAN
> ([`deploy/caddy-tailscale/README.md`](../../deploy/caddy-tailscale/README.md)). For
> a public-domain recipe, the equivalent decision is which FQDN and DNS record you
> point at it, and whether you put it behind an allowlist. Who may reach a system
> holding privileged material — and what access controls your professional
> obligations require around it — is a call for whoever is responsible for those
> matters, not a default.

## Why the gateway stays off the proxy

Every recipe deliberately does not route the Inference Gateway through the proxy —
admin access to it stays on `127.0.0.1`. That's not an oversight. Per
[PRD §4](../PRD.md#4-the-lq-ai-inference-gateway) the gateway is the only component
holding privileged provider keys, and [ADR 0014](../adr/0014-gateway-egress-boundary-for-tool-providers.md)
fixes it as the platform's single audited egress boundary. Putting a second network
path in front of it — even a private one — is a second thing to secure for no
operational gain, since nothing your browser needs is served there.

The gateway applies the same discipline to its own outbound side: it refuses to send
a provider request over plaintext HTTP to anything but a small allowlist of genuinely
local targets, even across a private tailnet, and returns an explicit refusal rather
than silently downgrading the connection. The [tailnet-Ollama recipe](../../deploy/tailnet-ollama/README.md)
documents this refusal directly, with the exact error text and the HTTPS-based fix.
If you see a similar refusal from the gateway on your own topology, read it as the
boundary doing its job — the fix is almost always "use the HTTPS endpoint," not
"route around it."

## Next

- [Air-gapped and local-only inference](air-gapped.md)
- [Recipe: Caddy + Tailscale](../../deploy/caddy-tailscale/README.md) — the tailnet-private path, with runnable steps
- [Install with Docker Compose](../../README.md#quick-start)
