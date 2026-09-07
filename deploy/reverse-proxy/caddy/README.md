# Caddy recipe — automatic HTTPS with Let's Encrypt

The simplest TLS front door for LQ.AI: Caddy obtains and **renews**
certificates automatically, and the whole proxy config fits in one short
[`Caddyfile`](Caddyfile). If you have no existing proxy preference, use this
recipe.

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
     -f deploy/reverse-proxy/caddy/docker-compose.proxy.yml \
     up -d
   ```

3. If you use the LQ.AI shell at `/lq-ai`, also rebuild `web` with
   `PUBLIC_LQ_AI_API_BASE_URL=/lq-ai-api/v1` (see
   [`../README.md`](../README.md#using-the-lqai-shell-lq-ai-from-other-devices)).

First start-up: Caddy solves the HTTP-01 challenge and obtains the certificate
within seconds of the stack coming up; watch it with
`docker compose logs -f caddy` (look for `certificate obtained successfully`).

**While iterating**, uncomment the staging `acme_ca` line in the
[`Caddyfile`](Caddyfile) so repeated failed attempts don't hit Let's Encrypt's
production rate limits (5 duplicate certs/week). Switch back and restart Caddy
once the recipe works.

## Verify

```bash
curl -fI https://<fqdn>/health          # 200, no -k needed — publicly trusted cert
curl -s -o /dev/null -w '%{http_code}\n' https://<fqdn>/lq-ai-api/v1/skills   # 401 = api routing works
curl -sI http://<fqdn>/ | head -1       # 308 redirect to https
docker run --rm drwetter/testssl.sh https://<fqdn>   # full TLS scan
```

Then open `https://<fqdn>/`, log in, send a chat message, and confirm the
response streams token-by-token (the Caddyfile sets `flush_interval -1` so
SSE is never buffered).

## Renewal and rotation

- Caddy renews automatically in the background (at ~2/3 of cert lifetime).
  There is **no cron job to add** and nothing to reload.
- State lives in the `caddy-data` volume: the ACME account key and all issued
  certificates. Include it in backups; deleting it forces re-issuance, which
  is rate-limited.
- If renewal fails (port 80 blocked after setup, DNS moved), Caddy logs errors
  and keeps serving the old cert until it expires — alert on
  `docker compose logs caddy | grep -i 'error'` or scrape cert expiry
  externally.

## Variations

- **Port 80 can't be opened:** HTTP-01 is off the table; Caddy supports the
  DNS-01 challenge instead, but it requires a Caddy build with your DNS
  provider's module — out of scope here. Either use a custom Caddy image with
  the relevant `caddy-dns/*` plugin, or use the [nginx recipe](../nginx/) with
  certs issued out-of-band.
- **Air-gapped / no route to Let's Encrypt:** ACME cannot work. Use the
  [nginx recipe](../nginx/) with internal-CA certs, or point `acme_ca` at an
  internal ACME endpoint if your organization runs one (e.g. smallstep CA).
- **HSTS:** commented out in the Caddyfile; read
  [`../README.md`](../README.md#hsts-read-before-enabling) before enabling.

## Files

```
deploy/reverse-proxy/caddy/
├── README.md                 # this file
├── docker-compose.proxy.yml  # Caddy service overlaid onto the base stack
├── Caddyfile                 # site config: auto-HTTPS, path routing, streaming
└── .env.example              # LQ_AI_FQDN, LQ_AI_ACME_EMAIL (append to root .env)
```
