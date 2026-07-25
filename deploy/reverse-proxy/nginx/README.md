# nginx recipe — operator-provided certificates (internal CA / air-gap path)

nginx in front of LQ.AI, terminating TLS with certificates **you supply** —
from a corporate/internal CA, a wildcard-cert program, or host-side certbot.
This is the recipe for organizations that already standardize on nginx, and
the **only** workable recipe for air-gapped or egress-restricted sites, where
ACME/Let's Encrypt is unreachable by definition.

Shared context — upstream topology, the `/lq-ai-api/v1` prefix, streaming and
HSTS guidance — is in [`../README.md`](../README.md).

## Prerequisites

- The base stack checked out and configured (root `.env` with the required
  secrets — see the repo README quick start).
- A DNS name for the host that your **clients** can resolve (public DNS or
  internal DNS — nothing here requires public resolution).
- A certificate + key pair for that name, placed per
  [`certs/README.md`](certs/README.md) (`fullchain.pem` + `privkey.pem`).
- Inbound ports 80 and 443 reachable from your clients; nothing else on the
  host bound to them.

## Run it

1. Place `fullchain.pem` and `privkey.pem` in
   [`certs/`](certs/) (or set `LQ_AI_TLS_CERT_DIR` in the root `.env` to the
   directory that holds them — see [`.env.example`](.env.example)).
2. From the repo root:

   ```bash
   docker compose \
     -f docker-compose.yml \
     -f deploy/reverse-proxy/nginx/docker-compose.proxy.yml \
     up -d
   ```

3. If you use the LQ.AI shell at `/lq-ai`, also rebuild `web` with
   `PUBLIC_LQ_AI_API_BASE_URL=/lq-ai-api/v1` (see
   [`../README.md`](../README.md#using-the-lqai-shell-lq-ai-from-other-devices)).

## Verify

```bash
# Config syntax check (runs inside the stack's network so the upstream
# hostnames api/web resolve):
docker compose -f docker-compose.yml -f deploy/reverse-proxy/nginx/docker-compose.proxy.yml \
  exec nginx nginx -t

# TLS terminates and the web shell answers. With an internal-CA cert, point
# curl at your CA bundle instead of using -k:
curl -kI https://<fqdn>/health                       # HTTP/2 200
curl --cacert /path/to/internal-ca.pem -fI https://<fqdn>/health

# Path routing to the LQ.AI backend (401 JSON = the /lq-ai-api/v1 → /api/v1
# rewrite reached api:8000):
curl -sk -o /dev/null -w '%{http_code}\n' https://<fqdn>/lq-ai-api/v1/skills

# HTTP→HTTPS redirect:
curl -sI http://<fqdn>/ | head -1                    # 301

# Full TLS posture scan:
docker run --rm drwetter/testssl.sh https://<fqdn>
```

Then open `https://<fqdn>/`, log in, send a chat message, and confirm the
response streams token-by-token — [`nginx.conf`](nginx.conf) sets
`proxy_buffering off` for exactly this reason.

## Internal CA guidance (air-gapped sites)

Air-gapped deployments cannot reach any public ACME endpoint, so certificate
issuance is an out-of-band, organization-level process. What this recipe
needs from that process:

- **Issue a server certificate** for the FQDN from your internal CA (follow
  your CA's documentation — a Windows AD CS "Web Server" template, a
  smallstep/step-ca instance, or an offline OpenSSL CA all work). Make sure
  the FQDN is in the **subjectAltName**; modern clients ignore the CN.
- **Build `fullchain.pem` correctly:** leaf certificate first, then each
  intermediate, root omitted. A missing intermediate is the most common
  "works in one browser, fails in another / fails in curl" symptom.
- **Distribute the CA root** to every client that will use the UI (browsers,
  and the OS trust store for CLI tools). This is your organization's existing
  managed-device trust-store process; LQ.AI needs nothing special.
- **Plan rotation manually.** There is no auto-renewal in this recipe:
  calendar the expiry, re-issue, replace the two files, and
  `nginx -s reload` (zero downtime — see [`certs/README.md`](certs/README.md)).
  Internal CAs often default to short lifetimes; 90 days–1 year is typical.
- **Scope note:** this covers *inbound* TLS to the proxy. The gateway's
  *outbound* TLS to LLM providers doesn't exist in a fully air-gapped
  deployment (Mode 2, local inference only); if you run a TLS-intercepting
  egress proxy in a partially connected environment, the gateway container —
  not nginx — needs your CA bundle in its trust store.

If your organization runs an **internal ACME service** (e.g. smallstep CA),
consider the [Caddy recipe](../caddy/) pointed at it via `acme_ca` instead —
you get automatic rotation back.

## Operational notes

- **Timeouts and streaming:** `proxy_read_timeout` is 3600 s on both routes so
  long generations and idle-but-alive WebSockets survive;
  `proxy_buffering off` keeps SSE tokens flowing. If you tighten these, test
  a long chat response before rolling out.
- **Upload size:** `client_max_body_size 200m`. Raise it if your document
  sets are larger; the symptom of hitting it is HTTP 413 on upload.
- **Logs:** the container logs to stdout/stderr (`docker compose logs nginx`);
  Docker's log driver handles rotation.
- **HSTS:** commented out in [`nginx.conf`](nginx.conf); read
  [`../README.md`](../README.md#hsts-read-before-enabling) before enabling.
- **cert-manager:** if you later move to Kubernetes (DE-030 Helm chart),
  cert-manager takes over the issuance role this recipe leaves manual; the
  nginx routing translates to an Ingress with the same two path rules.

## Files

```
deploy/reverse-proxy/nginx/
├── README.md                 # this file
├── docker-compose.proxy.yml  # nginx service overlaid onto the base stack
├── nginx.conf                # server blocks: TLS, path routing, streaming, websockets
├── .env.example              # optional LQ_AI_TLS_CERT_DIR (append to root .env)
└── certs/                    # place fullchain.pem + privkey.pem here (git-ignored)
    └── README.md             # filenames, rotation, self-signed smoke pair
```
