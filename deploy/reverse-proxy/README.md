# Reverse-proxy + TLS recipes (DE-031 / DE-234)

Three compose overlays that put a TLS-terminating reverse proxy in front of the
LQ.AI stack, so the deployment is reachable at `https://<your-fqdn>/` instead
of plain HTTP on the Docker host's loopback. Pick **one** recipe:

| Recipe | Certificates | Config style | Choose it when |
| --- | --- | --- | --- |
| [`caddy/`](caddy/) | Let's Encrypt, automatic (issuance **and** renewal) | One short Caddyfile | You want TLS with the least configuration. Recommended default. |
| [`traefik/`](traefik/) | Let's Encrypt, automatic | Docker labels on the services | You already run Traefik, or you plan to migrate to Kubernetes later (the label-based routing ports naturally to an Ingress). |
| [`nginx/`](nginx/) | **Operator-provided** (corporate/internal CA, wildcard cert, certbot on the host) | Classic nginx server block | Your organization already standardizes on nginx, or you are **air-gapped / cannot reach Let's Encrypt** and must bring your own certificates. |

> **Tailnet-private alternative:** if you don't want a public URL at all, use
> [`deploy/caddy-tailscale/`](../caddy-tailscale/) instead — it serves the UI
> only over your Tailscale tailnet, with the certificate handled by Tailscale.
> The recipes here are for a **publicly resolvable FQDN** (Caddy/Traefik) or an
> internally resolvable one with operator-supplied certs (nginx).

## What all three recipes share

### Upstream topology

Each proxy serves a **single origin** and routes by path:

| Path | Destination | Notes |
| --- | --- | --- |
| `/lq-ai-api/v1/*` | `api:8000` | LQ.AI backend. The proxy rewrites the prefix to `/api/v1` before forwarding. |
| everything else | `web:8080` | OpenWebUI shell, its own `/api/v1` and `/api/config`, WebSockets (`/ws/socket.io`), static assets. |

Why the prefix: the web container serves OpenWebUI, which is full-stack and
mounts its **own** `/api/v1` (and `/api/config`, fetched at first paint). The
LQ.AI backend *also* mounts `/api/v1`. On one origin those namespaces collide,
so the LQ.AI backend gets its own public prefix, `/lq-ai-api/v1`, rewritten
back to `/api/v1` at the proxy. This matches the routing shape used by
[`deploy/caddy-tailscale/`](../caddy-tailscale/README.md#routing) and (with a
different prefix) the release stack's bundled proxy.

The **gateway is deliberately not routed** through any of these proxies. Per
PRD §4 it is the security boundary holding privileged provider keys; its admin
surface stays on the Docker host at `127.0.0.1:${GATEWAY_HOST_PORT}`.

### The base stack stays private

The base `docker-compose.yml` binds every published port to `127.0.0.1` by
default (`*_BIND_ADDR` vars), so adding a proxy overlay makes the proxy's
80/443 the **only** ports reachable from other machines. Do not set any
`*_BIND_ADDR` to `0.0.0.0` when running behind one of these proxies.

### Using the LQ.AI shell (`/lq-ai`) from other devices

The web image bakes `PUBLIC_LQ_AI_API_BASE_URL` into its static bundle at
**build** time. The dev default (`/api/v1`, or `http://localhost:8000/api/v1`
from `.env`) breaks LQ.AI-shell API calls from any browser that is not the
Docker host. To use the LQ.AI shell through a proxy, set in your root `.env`:

```
PUBLIC_LQ_AI_API_BASE_URL=/lq-ai-api/v1
```

then rebuild `web` so Vite re-bakes the prefix:

```bash
docker compose -f docker-compose.yml -f deploy/reverse-proxy/<recipe>/docker-compose.proxy.yml build web
docker compose -f docker-compose.yml -f deploy/reverse-proxy/<recipe>/docker-compose.proxy.yml up -d
```

If you only use the OpenWebUI shell at `/`, you can skip this — its API is
same-origin relative and works unmodified behind all three proxies.

### Streaming, WebSockets, and timeouts

Chat responses are **streamed** (SSE over HTTP plus a socket.io WebSocket), and
a long generation or an autonomous-session run can legitimately hold a
connection open for many minutes with output trickling out token by token. A
default-configured proxy breaks this in two ways: response **buffering** (the
user sees nothing until the full answer is done, or the buffer flushes at 4 kB
boundaries) and short **read timeouts** (the connection is cut mid-answer).
Each recipe therefore:

- disables (or auto-detects around) response buffering for proxied responses;
- allows long-lived upstream reads (Caddy: no timeout by default; Traefik and
  nginx: explicitly configured — see each README);
- forwards WebSocket `Upgrade`/`Connection` handshakes (automatic in Caddy and
  Traefik; explicit headers in the nginx config);
- allows large request bodies for document upload (nginx sets
  `client_max_body_size`; Caddy and Traefik impose no body-size limit by
  default).

If a chat stream stalls at the start and then "arrives all at once", or dies
after exactly N seconds, suspect a second proxy/CDN in front of this one.

### HSTS (read before enabling)

Each config ships with a **commented-out** `Strict-Transport-Security` header.
Once served, HSTS makes browsers refuse plain-HTTP access to the domain until
`max-age` expires — there is no quick rollback if your certificate pipeline
breaks. Enable it only after HTTPS has been stable for a while, starting with a
small `max-age`. Treat `includeSubDomains` and especially `preload` as one-way
doors: preload submission bakes your domain into browser binaries and can take
months to undo. For an internal legal-ops deployment, plain
`max-age=31536000` with **no** `preload` is the sensible ceiling.

### Smoke checks (all recipes)

```bash
# TLS terminates and the web shell answers (expect 200; drop -k once using a
# publicly trusted or locally trusted cert):
curl -skI https://<fqdn>/health

# Path routing to the LQ.AI backend works (expect HTTP 401 with a JSON
# {"detail":"Not authenticated"} body — proof the rewrite reached api:8000):
curl -sk -o /dev/null -w '%{http_code}\n' https://<fqdn>/lq-ai-api/v1/skills

# WebSocket endpoint answers through the proxy (engine.io responds; any
# HTTP answer here — not a proxy 502/504 — means the route works):
curl -sk -o /dev/null -w '%{http_code}\n' "https://<fqdn>/ws/socket.io/?EIO=4&transport=polling"

# Streaming: open the UI, send a chat message, and confirm tokens render
# incrementally rather than appearing in one block at the end.

# Full TLS posture scan (protocol versions, ciphers, HSTS, cert chain):
docker run --rm drwetter/testssl.sh https://<fqdn>
```

## Files

```
deploy/reverse-proxy/
├── README.md                # this file — pick a recipe
├── caddy/                   # Let's Encrypt, automatic; simplest
├── traefik/                 # Let's Encrypt, automatic; label-based routing
└── nginx/                   # operator-provided certs; internal-CA / air-gap path
```
