# Give the app a secure web address

`docker compose up -d` binds every published port to `127.0.0.1` by default —
a fresh install is not reachable from another device until you put a web
server (a reverse proxy) in front of it and give it an HTTPS address. Two
shapes of recipe ship in this repository today, covering different audiences:

| Recipe | Reachable from | Certificates | Where |
| --- | --- | --- | --- |
| [Caddy + Tailscale](../../deploy/caddy-tailscale/README.md) | Your tailnet only, no public DNS | Tailscale (auto-renewing) | [`deploy/caddy-tailscale/`](../../deploy/caddy-tailscale/) |
| Caddy / Traefik / nginx | A public FQDN | Let's Encrypt (Caddy, Traefik) or operator-provided (nginx) | [`deploy/reverse-proxy/`](../../deploy/reverse-proxy/) |

Pick the tailnet recipe if you want a private, share-with-the-team URL and
don't want to manage public DNS or certificates yourself — see "A private
team address" below for what it does, and
[Recipe: Caddy + Tailscale](../../deploy/caddy-tailscale/README.md) for the
runnable steps. Pick one of the three public-domain recipes under
`deploy/reverse-proxy/` if you need a domain the public internet can
resolve; each is a Docker Compose overlay with its own README covering
setup, the smoke checks, and what "reference configuration, not a supported
production distribution" means for that proxy. All four recipes share the
same upstream routing shape — a path-based split between `web` and `api`,
with the gateway left off the proxy (see "Why the gateway stays off the
proxy" below).

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

## Keep the addresses consistent

Serving the web app and the API from the same address is the simplest
setup, and it's what every recipe here does — Caddy, Traefik and nginx each
route both under one origin, split by path. If you serve them at different
addresses instead, the API needs the website's address on its CORS
allowlist: set `LQ_AI_CORS_ORIGINS` in your `.env` to a comma-separated
list of the origins allowed to call it, and leave it unset when web and api
share an origin (`.env.example`). That variable only covers LQ.AI's own
API — the OpenWebUI backend embedded in the `web` container has a separate
`CORS_ALLOW_ORIGIN` setting, which falls back to `*` if left unset
(`web/backend/open_webui/config.py`).

## Try the complete route

Check sign-in, a document upload, and a streamed chat answer arriving
through the shared address — a homepage that loads only proves `/` reached
`web`. The shared smoke checks in
[`deploy/reverse-proxy/README.md`](../../deploy/reverse-proxy/README.md#smoke-checks-all-recipes)
(health, the api's 401 on `/lq-ai-api/v1/skills`, the `/ws/socket.io/`
probe, and streaming) are what show both `/api/v1` namespaces landed on
the right service — sign-in and the upload aren't part of that script, so
check them by hand. Try the upload specifically — nginx caps body size
explicitly (`client_max_body_size`) while Caddy and Traefik don't by
default. Keep database, storage and administration ports private unless
you have a specific reason to share them.

## A private team address

The Caddy and Tailscale recipe is under
[`deploy/caddy-tailscale/`](../../deploy/caddy-tailscale/README.md).
Tailscale runs on the host, supplies HTTPS and forwards to Caddy on the
host's loopback address; Caddy then routes to the website and API, and the
gateway is not exposed through this proxy. This setup needs Tailscale
installed and authenticated on the host, with MagicDNS and HTTPS
Certificates enabled for your tailnet (admin console → DNS → HTTPS
Certificates).

## Make the LQ.AI workspace call the right API

This only matters if you use the LQ.AI shell at `/lq-ai` — OpenWebUI's own
shell at `/` calls a same-origin relative API and needs no change. For the
LQ.AI shell, set `PUBLIC_LQ_AI_API_BASE_URL=/lq-ai-api/v1` in your `.env`
and rebuild `web`: Vite bakes this value into the static bundle at
image-build time, so changing a running container's environment alone will
not change it. The proxy rewrites that prefix to LQ.AI's `/api/v1` and
leaves OpenWebUI's own `/api/v1` untouched. Left at its local-dev default, a
browser on another device can't reach `localhost:8000`.

## When changing ports

If you change `CADDY_HOST_PORT` in the Tailscale recipe, also point the
host's `tailscale serve` command at the new port — that command runs on the
host, outside Compose, so it won't pick up the change on its own. Then
confirm the HTTPS address, sign-in, uploads and a streamed answer again
from another permitted device.

## Keep the two API paths distinct

OpenWebUI's embedded backend and LQ.AI's API are separate services sharing
that one address: OpenWebUI mounts its own `/api/v1` inside the `web`
container, and the LQ.AI backend mounts `/api/v1` too, so each recipe gives
LQ.AI's API its own public prefix (`/lq-ai-api/v1`) and rewrites it back
before proxying. When adapting a recipe, check streamed answers and
uploads as well as sign-in — a working homepage alone doesn't establish
that those routes reached the correct service.

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
