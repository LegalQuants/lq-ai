# Traefik recipe — automatic HTTPS with Let's Encrypt, file-provider routing

Traefik v3 in front of LQ.AI with automatic certificate issuance and renewal.
Routing rules are declared in an explicit dynamic configuration file. Traefik
therefore needs no access to `/var/run/docker.sock` and cannot inspect or
control other containers through the Docker API.

Shared context — upstream topology, the `/lq-ai-api/v1` prefix, streaming and
HSTS guidance — is in [`../README.md`](../README.md).

## Prerequisites

- The base stack checked out and configured (root `.env` with the required
  secrets — see the repo README quick start).
- A **public DNS A/AAAA record** for your FQDN pointing at this host.
- Inbound **ports 80 and 443** reachable from the internet (80 is required for
  the ACME HTTP-01 challenge and the HTTP→HTTPS redirect).
- Nothing else on the host already bound to 80/443.

## Run it

1. Append the variables from [`.env.example`](.env.example) to the **root**
   `.env` and set your real FQDN and email.
2. From the repo root:

   ```bash
   docker compose \
     -f docker-compose.yml \
     -f deploy/reverse-proxy/traefik/docker-compose.proxy.yml \
     up -d
   ```

3. If you use the LQ.AI shell at `/lq-ai`, also rebuild `web` with
   `PUBLIC_LQ_AI_API_BASE_URL=/lq-ai-api/v1` (see
   [`../README.md`](../README.md#using-the-lqai-shell-lq-ai-from-other-devices)).

Watch issuance with `docker compose logs -f traefik`; the first certificate
lands within seconds of the entrypoints coming up.

**While iterating**, uncomment the staging `caserver` flag in
[`docker-compose.proxy.yml`](docker-compose.proxy.yml) so repeated failed
attempts don't hit Let's Encrypt's production rate limits. When switching back
to production, also clear the staged state:
`docker compose down traefik && docker volume rm lq-ai_traefik-letsencrypt`.

## Verify

```bash
curl -fsS -o /dev/null https://<fqdn>/health && echo "web health: ok"
curl -s -o /dev/null -w '%{http_code}\n' https://<fqdn>/lq-ai-api/v1/skills   # 401 = api routing works
curl -sI http://<fqdn>/ | head -1       # 30x redirect to https
docker run --rm ghcr.io/testssl/testssl.sh:3.2 https://<fqdn>   # optional full TLS scan
```

Then open `https://<fqdn>/`, log in, send a chat message, and confirm the
response streams token-by-token (`responseforwarding.flushinterval=-1` on both
services disables write batching; Traefik also auto-detects
`text/event-stream` and never buffers SSE bodies).

## How the routing works

| Router | Rule | Target |
| --- | --- | --- |
| `lq-api` | ``Host(`FQDN`) && PathPrefix(`/lq-ai-api/v1`)`` | `api:8000`, after `stripprefix` + `addprefix` middlewares rewrite the path to `/api/v1/*` |
| `lq-web` | ``Host(`FQDN`)`` | `web:8080` (catch-all; longer rules win automatically, so `lq-api` takes precedence) |

The gateway is **not** routed (see [`../README.md`](../README.md)). Traefik's
own dashboard/API is left disabled — don't enable `--api.insecure` on an
internet-facing host.

## Renewal, rotation, and operational notes

- Traefik renews automatically (~30 days before expiry); nothing to cron and
  nothing to reload.
- All ACME state (account key + certs) lives in `acme.json` inside the
  `traefik-letsencrypt` volume. Back it up; deleting it forces rate-limited
  re-issuance.
- Renewal failures (port 80 closed, DNS moved) appear in the Traefik logs
  while the old cert keeps serving until expiry — watch
  `docker compose logs traefik | grep -i acme` or monitor expiry externally.
- The dynamic routing file is mounted read-only. No Docker socket, privileged
  mode, or host networking is required.

## Variations

- **Port 80 can't be opened:** switch the resolver to the DNS-01 challenge
  (`--certificatesresolvers.letsencrypt.acme.dnschallenge=true` plus your DNS
  provider's flags and credential env vars — Traefik supports most providers
  natively, no plugin build needed). Out of scope here; see Traefik's ACME
  docs.
- **Air-gapped / no route to Let's Encrypt:** ACME cannot work. Use the
  [nginx recipe](../nginx/) with internal-CA certs, or point `caserver` at an
  internal ACME endpoint if your organization runs one.
- **HSTS:** a commented `lq-hsts` headers middleware ships in the overlay;
  read [`../README.md`](../README.md#hsts-read-before-enabling) before
  attaching it to the routers.

## Files

```
deploy/reverse-proxy/traefik/
├── README.md                 # this file
├── docker-compose.proxy.yml  # Traefik service and static flags
├── dynamic/
│   └── lq-ai.yml              # routers, middleware, and upstream services
└── .env.example              # LQ_AI_FQDN, LQ_AI_ACME_EMAIL (append to root .env)
```

*Why are there flags and a YAML file?* Entry points and the ACME resolver are
static configuration, supplied as flags. Routers and services are dynamic
configuration, supplied through the file provider. The dynamic file uses
Traefik's supported Go-template `env` function for `LQ_AI_FQDN`; Compose passes
the value from the same root `.env` as the rest of the stack.
