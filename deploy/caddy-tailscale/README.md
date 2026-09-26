# Share access over a private Tailscale network

The repository includes an example that puts **Caddy** in front of the LQ.AI
web shell and backend and serves it privately over your tailnet, with HTTPS
handled by the host's own **Tailscale** rather than by the proxy itself.

> **How this relates to the other recipes.** The `reverse-proxy/{caddy,traefik,nginx}`
> recipes (DE-031) terminate TLS *at the proxy* for a **public** address —
> Let's Encrypt or your own certificates, a public DNS record, and port 80
> open for the certificate challenge. This recipe is the **tailnet**
> alternative: no public DNS, no inbound ports, no certificate process to
> run — the UI is reachable only from devices on your tailnet, and Tailscale
> itself issues the certificate. If you need a publicly reachable URL, use
> one of the `reverse-proxy` recipes instead.

## When to use this

- You want the UI on your **tailnet only**, not the public internet.
- You don't want to manage a public DNS record, open inbound ports, or run
  Let's Encrypt yourself.
- You already run Tailscale on the deployment host.

## How it works

```
Browser  →  https://<host>.<tailnet>.ts.net    valid, auto-renewing TLS cert
         →  127.0.0.1:${CADDY_HOST_PORT}        host loopback (tailscale serve)
         →  caddy container                      Docker port map
         →  api:8000  /  web:8080                Compose bridge network
```

Tailscale does **not** run in Docker here. The host's existing `tailscale`
publishes Caddy on the tailnet through `tailscale serve`, terminates TLS, and
forwards the decrypted traffic to Caddy on loopback. Caddy itself issues no
certificates (`auto_https off`) and only routes plain HTTP on `:80` inside
the container — Caddy is given no tailnet identity of its own; the host owns
that.

This recipe secures the network path — it isn't a substitute for securing the
underlying host itself; keep following your usual practices for that.

## Prerequisites

- A **Linux host** with Docker and Docker Compose.
- **Tailscale installed and authenticated** on that host, with `tailscale` in
  `PATH`.
- For the recommended (HTTPS) path, your tailnet needs **MagicDNS** and
  **HTTPS Certificates** turned on (admin console → **DNS** → *HTTPS
  Certificates* → **Enable HTTPS**). If they aren't on yet, the
  `tailscale serve` command below prompts you with a consent URL to enable
  them.
- The base `docker-compose.yml` stack (`web`, `api`, and their dependencies).

## Set the browser-facing API address

Edit your `.env` to include:

| Variable | Notes |
| --- | --- |
| `CADDY_BIND_ADDR=127.0.0.1` | The address you point `tailscale serve` at, together with the port below. |
| `CADDY_HOST_PORT=80` | Host port Caddy listens on. `80` keeps URLs port-free; pick a free non-privileged port (e.g. `8080`) if something else already owns 80 on the host, and remember to update the `tailscale serve` upstream target to match. |
| `PUBLIC_LQ_AI_API_BASE_URL=/lq-ai-api/v1` | Tells the browser client which base URL to call — baked into the web bundle at image-build time. Only needed if you use the LQ.AI shell (see "Using the LQ.AI shell over the tailnet" below); must match the Caddyfile route. |

Then rebuild the web bundle so Vite bakes `PUBLIC_LQ_AI_API_BASE_URL` in
(build-time, not runtime — skipping this leaves LQ.AI-shell calls pointing at
`localhost:8000`):

```bash
docker compose \
  -f docker-compose.yml \
  -f deploy/caddy-tailscale/docker-compose.proxy.yml \
  build web
```

## Start the private web address

Bring up the stack with this overlay composed onto the base file:

```bash
docker compose \
  -f docker-compose.yml \
  -f deploy/caddy-tailscale/docker-compose.proxy.yml \
  up -d
```

<!-- Adjust the overlay filename if yours differs from docker-compose.proxy.yml. -->

Then run this **once** on the host (not in a container):

```bash
sudo tailscale serve --bg --https=443 http://127.0.0.1:80
```

This lives in the host's Tailscale config and persists across host and stack
reboots. It terminates HTTPS with a valid, auto-renewing certificate for your
tailnet name (publicly trusted — no `-k` needed) and proxies to Caddy on
loopback.

If you change `CADDY_HOST_PORT`, point the `tailscale serve` upstream at the
new port (e.g. `http://127.0.0.1:8080`). That command runs on the host,
outside Compose, so it will not pick up the change on its own.

Open the UI from any device on your tailnet:

```
https://<host>.<tailnet>.ts.net
```

## Verify from another permitted device

From any tailnet device:

```bash
# TLS terminates and the web shell answers (expect HTTP/2 200, valid cert):
curl -fI https://<host>.<tailnet>.ts.net/

# Inspect the active serve config on the host:
tailscale serve status
```

A `200` over `https://` with no certificate warning confirms the full path:
Tailscale TLS → loopback → Caddy → `web`.

## Who can connect

Check which users and devices can reach the app through Tailscale, then try
sign-in, uploads and answers through that connection from a second device.
Users still need the appropriate access **inside** LQ.AI itself — reaching
the app over the tailnet does not by itself grant them anything once they're
in.

## Configuration

| Variable          | Default     | Purpose                            |
| ----------------- | ----------- | ---------------------------------- |
| `CADDY_BIND_ADDR` | `127.0.0.1` | Host interface Caddy publishes on. |
| `CADDY_HOST_PORT` | `80`        | Host port Caddy listens on.        |

**`CADDY_BIND_ADDR`**
- `127.0.0.1` — loopback only; pair with `tailscale serve` (recommended, HTTPS).
- `100.x.y.z` — bind directly to the host's Tailscale IP (`tailscale ip -4`);
  HTTP only over the tailnet (see "Alternative" below).
- `0.0.0.0` — all host interfaces, **including LAN/WAN**. Only use this behind a
  host firewall.

**`CADDY_HOST_PORT`** — `80` keeps URLs port-free. If something already owns 80
on the host, pick a free non-privileged port (e.g. `8080`) and update the
`tailscale serve` target to match.

## Routing

| Path              | Destination | Notes                                            |
| ----------------- | ----------- | ------------------------------------------------ |
| `/lq-ai-api/v1/*` | `api:8000`  | LQ.AI backend; prefix rewritten to `/api/v1`.    |
| `/*`              | `web:8080`  | Web container (OpenWebUI shell + its `/api/v1`). |

The gateway is **not** routed through Caddy. Per PRD §4 it is the security
boundary holding privileged provider keys; admin access stays on
`127.0.0.1:${GATEWAY_HOST_PORT}`.

### Why the `/lq-ai-api/v1` prefix?

Per ADR 0009 the web container serves two shells side by side:

- `/` — OpenWebUI's shell, which calls OpenWebUI's own `/api/v1` (OpenWebUI is
  full-stack, so that API lives inside the web container).
- `/lq-ai/*` — the LQ.AI shell, which calls the LQ.AI backend (the `api`
  container).

The LQ.AI backend also mounts at `/api/v1`, so same-origin behind Caddy the
two `/api/v1` namespaces collide. Caddy resolves this by giving the LQ.AI
backend its own public prefix, `/lq-ai-api/v1`, and rewriting it back to
`/api/v1` before proxying. Everything else falls through to the web
container, so OpenWebUI's own `/api/v1` is left untouched. WebSocket/SSE
upgrades (used by the chat surface) are handled automatically by Caddy's
`reverse_proxy`.

## Using the LQ.AI shell over the tailnet

This only matters if you use the LQ.AI shell at `/lq-ai`. If you only use
OpenWebUI's shell at `/`, skip this — the default
`PUBLIC_LQ_AI_API_BASE_URL=http://localhost:8000/api/v1` is fine, because the
LQ.AI client never gets called.

To make `/lq-ai` work from any tailnet device (not just the Docker host), set:

```
PUBLIC_LQ_AI_API_BASE_URL=/lq-ai-api/v1
```

in your root `.env` (see "Set the browser-facing API address" above), then
rebuild `web` so Vite bakes the new prefix into the static bundle:

```bash
docker compose -f docker-compose.yml -f deploy/caddy-tailscale/docker-compose.proxy.yml build web
docker compose -f docker-compose.yml -f deploy/caddy-tailscale/docker-compose.proxy.yml up -d
```

Leaving it as `http://localhost:8000/...` breaks LQ.AI-shell calls from any
device that is not the Docker host itself.

## Alternative: bind Caddy straight to the tailnet (HTTP only)

If you would rather skip `tailscale serve`, set `CADDY_BIND_ADDR` to the
host's Tailscale IP (`tailscale ip -4`). Caddy then listens on that IP
directly and the UI is reachable at `http://<host>:${CADDY_HOST_PORT}` over
the tailnet.

Traffic is still WireGuard-encrypted on the wire, but browsers treat the
connection as plain **HTTP**, which affects cookies and Service Workers. The
`tailscale serve` path is preferred for that reason.

## Operational notes

- **Certificates.** Tailscale provisions and auto-renews the TLS certificate
  for your tailnet name; there is nothing to rotate on your side. This is the
  main reason to choose this recipe over the ACME recipes.
- **Startup ordering.** Caddy depends on `web` (`service_started`) and `api`
  (`service_healthy`). `web` is not gated on health because its first boot
  pulls embedding models from HuggingFace and can take minutes to become
  healthy. `service_started` is enough for DNS resolution; until `web` is
  actually listening Caddy returns 502, which is a recoverable state —
  preferable to holding the whole tailnet entry point down.
- **Persistence.** Caddy's `/data` (state) and `/config` (autosave config)
  are kept in the `caddy-data` and `caddy-config` named volumes — a `docker
  compose down` between restarts doesn't lose them; only an explicit `-v`
  would. The `tailscale serve --bg` command itself lives in the **host's**
  Tailscale configuration, outside any container, and survives both host and
  stack reboots — you run it once, not on every `docker compose up`.
- **This recipe has no LQ.AI-side refusal of its own.** Caddy speaks plain
  HTTP internally and the gateway isn't routed through it at all (see
  "Routing" above). If `tailscale serve` itself prompts you with a consent
  URL instead of running, that's Tailscale asking you to enable **MagicDNS**
  and **HTTPS Certificates** for the tailnet, a one-time admin-console step,
  not a fail-closed control in this repository.

## Files

```
deploy/caddy-tailscale/
├── README.md                    # this file
├── docker-compose.proxy.yml     # Caddy service + overlays onto the base stack
└── Caddyfile                    # auto_https off; :80; path routing to web/api
```
