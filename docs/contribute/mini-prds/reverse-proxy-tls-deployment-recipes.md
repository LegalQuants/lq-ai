# Mini-PRD: Reverse-Proxy + TLS Deployment Recipes

> **Status:** Shipped in #429 — the three recipes live under `deploy/reverse-proxy/` (see its README for their evidence level). This document is kept as the design record.
> **Effort:** S
> **Contributor profile:** Junior-to-mid DevOps engineer. Familiar with Docker Compose, reverse proxies (at least one of Caddy, Traefik, nginx), and TLS certificate flows (Let's Encrypt for auto-issuance; operator-provided for manual). ~one focused day.
> **Mentor:** Maintainer (Kevin Keller, via PR review)

## What this is

Three reverse-proxy + TLS deployment recipes under `deploy/reverse-proxy/`, one each for Caddy, Traefik, and nginx. Each recipe is a docker-compose overlay that terminates TLS at the proxy and routes to the existing LQ.AI services (`web` on port 8080 and `api` on port 8000), with a short README per recipe covering: when to choose this proxy, how the cert source is configured (Let's Encrypt for Caddy and Traefik; operator-provided for nginx), and a smoke command to verify TLS is live.

The recipes are operator-facing deployment artifacts. They are not added to CI as integration tests in this PR (a follow-on PR can add smoke-test CI for at least the Caddy recipe). What ships is documentation and configuration the operator can copy-paste-and-go.

## Why it matters

[PRD §6.3 Deployment Topology](../../PRD.md#6-deployment) and [PRD §1.8 Security Posture](../../PRD.md#18-security-posture) commit to production-quality TLS as a deployment posture; the existing [`docker-compose.yml`](../../../docker-compose.yml) brings up the services on plain HTTP for local development. Operators deploying LQ.AI into a production environment need a reverse-proxy + TLS configuration; "build your own" is a friction point that procurement reviewers raise routinely.

The three proxies cover the operator population:

- **Caddy** is the simplest path. Automatic Let's Encrypt issuance and renewal, minimal config, suitable for operators who want TLS to work out of the box.
- **Traefik** is the Kubernetes-adjacent path. Routes via Docker labels, integrates with cert-manager, suitable for operators who plan to migrate to Kubernetes later (with the Helm chart, when shipped).
- **nginx** is the traditional path. Most familiar to operators with existing nginx infrastructure, suitable for environments where the operator brings their own certificates (e.g., internal CA, wildcard cert from a corporate cert program).

Shipping all three closes the "what does production TLS look like?" question that procurement reviewers ask in every cycle. The recipes are also the entry point for operators evaluating LQ.AI on a real domain — the first thing they need after `docker compose up` is a TLS-terminated front door so they can share a URL with the rest of their team. The recipes make that path a copy-paste-and-go.

The recipes also strengthen the project's operational-maturity signal. A serious project ships production-deployment recipes; a hobby project ships only the development-mode compose file. The presence of `deploy/reverse-proxy/` with three working recipes is the kind of signal an experienced operator reads as "this project has thought about production."

## What we'd ship

A new subtree under `deploy/`:

```
deploy/
├── helm/                                # exists (M2 deferred per DE-030; out of scope here)
└── reverse-proxy/                       # NEW
    ├── README.md                        # NEW — overview, when to choose which recipe
    ├── caddy/
    │   ├── README.md                    # NEW — when to use, cert source, smoke verification
    │   ├── docker-compose.proxy.yml     # NEW — Caddy service + overlays
    │   ├── Caddyfile                    # NEW — Caddy config (TLS auto, routes to web/api)
    │   └── .env.example                 # NEW — required env vars (FQDN, ACME_EMAIL)
    ├── traefik/
    │   ├── README.md                    # NEW
    │   ├── docker-compose.proxy.yml     # NEW
    │   ├── traefik.yml                  # NEW — static config
    │   ├── dynamic.yml                  # NEW — dynamic config (TLS, middlewares)
    │   └── .env.example                 # NEW
    └── nginx/
        ├── README.md                    # NEW
        ├── docker-compose.proxy.yml     # NEW
        ├── nginx.conf                   # NEW — operator-provided certs; sample server block
        ├── certs/                       # NEW — empty directory with .gitkeep + README
        │   └── README.md                # documents what the operator places here
        └── .env.example                 # NEW
```

**`deploy/reverse-proxy/README.md`** — overview document. Compares the three recipes (auto-TLS via Let's Encrypt vs. operator-provided certs; Docker-label routing vs. file-based config; Kubernetes-migration trajectory). Helps the operator decide which recipe to start with.

**Per-recipe `README.md`** — when to use this recipe; prerequisites (a public DNS A record pointing at the host; for Let's Encrypt recipes, port 80 reachable for HTTP-01 challenge); how to run it (`docker compose -f docker-compose.yml -f deploy/reverse-proxy/caddy/docker-compose.proxy.yml up -d`); how to verify TLS is live (a `curl` command with cert verification, plus a pointer to an SSL Labs / `testssl.sh` scan); operator-side caveats (rate-limiting, log rotation, what to do when the cert expires or the renewal flow fails).

**Per-recipe `docker-compose.proxy.yml`** — overlay file that adds the proxy service and reconfigures the `web` and `api` services to expose ports only on the internal compose network (not the host). The overlay is composed with the base `docker-compose.yml` via the `-f` flag.

**Per-recipe proxy configuration** — `Caddyfile`, `traefik.yml`/`dynamic.yml`, or `nginx.conf` as appropriate. Each routes the FQDN to the `web` service for browser routes and to the `api` service for API routes (per the existing port mapping conventions: `web` on 8080, `api` on 8000). Each handles WebSocket upgrades correctly (the chat surface uses SSE / WebSockets per the existing setup).

**Per-recipe `.env.example`** — the env vars the operator must set (FQDN, ACME email for Let's Encrypt recipes, paths for operator-provided cert recipes).

**`nginx/certs/README.md`** — documents the operator-provided cert workflow: where to place the cert (`certs/fullchain.pem`), where to place the key (`certs/privkey.pem`), and how to reload nginx when the cert is rotated. The `certs/` directory ships with `.gitkeep` only; no actual certs in source.

## How we'd know it's done

- [ ] `deploy/reverse-proxy/` exists with the four directories above.
- [ ] Each recipe brings up cleanly on a host with a public DNS A record pointing at it (Caddy and Traefik) or with operator-provided certs in place (nginx).
- [ ] Each recipe's overlay composes correctly with the base [`docker-compose.yml`](../../../docker-compose.yml) — `docker compose -f docker-compose.yml -f deploy/reverse-proxy/<recipe>/docker-compose.proxy.yml config` produces a valid merged config.
- [ ] Each recipe's README is reproducible by a non-maintainer following the steps verbatim — bring up the stack, hit the FQDN with a browser, see TLS termination working.
- [ ] WebSocket / SSE upgrades work through each proxy (the chat surface uses streaming).
- [ ] Each recipe's smoke-verification command produces a green result on a working deployment (e.g., `curl -fI https://${FQDN}/api/healthz` returns 200 with a valid cert).
- [ ] Operator-provided env vars (FQDN, ACME email, cert paths) are documented in each `.env.example` and referenced in the recipe README.
- [ ] The top-level `deploy/reverse-proxy/README.md` helps the operator choose between the three recipes.
- [ ] The main [`README.md`](../../../README.md) (or the deployment section of the docs) links to `deploy/reverse-proxy/` from the production-deployment guidance.

## Where to start

1. Read the existing [`docker-compose.yml`](../../../docker-compose.yml) in full — note the service names (`web`, `api`, `gateway`, `postgres`, `redis`, `rustfs`), the port mappings (`web` at 3000:8080 per the dev convention, `api` at 8000:8000), and the compose-network topology. The reverse-proxy overlays change the host-published ports; the inter-service traffic stays on the compose network.
2. Note the existing [`deploy/`](../../../deploy/) directory — currently contains only the (deferred) `helm/` subdirectory. The new `reverse-proxy/` subdirectory sits beside it.
3. Read the [PRD §6 Deployment](../../PRD.md#6-deployment) section for the deployment-topology context.
4. Pick one proxy to implement first and iterate against a real domain. Caddy is the easiest first target — the Caddyfile is short and the Let's Encrypt automation is built in. Get Caddy working end to end, then port the same routing rules to Traefik and nginx.
5. For Caddy: read the official documentation at https://caddyserver.com/docs/. The relevant features are automatic HTTPS, reverse_proxy directive, and WebSocket support.
6. For Traefik: read the official documentation at https://doc.traefik.io/traefik/. The relevant features are Docker provider (auto-discovery via labels), ACME / Let's Encrypt, and the file provider for static routing rules.
7. For nginx: read the existing public nginx documentation at https://nginx.org/en/docs/. The relevant features are `proxy_pass`, WebSocket upgrade handling (`Upgrade` / `Connection` headers), and TLS server-block configuration.
8. Test each recipe against a real test FQDN. Let's Encrypt has rate limits; use the staging endpoint while iterating, then switch to production once the recipe is solid.
9. For the nginx recipe, validate the operator-provided cert workflow by generating a self-signed cert + key, placing them in `certs/`, and confirming the recipe brings up TLS using them.
10. Write the recipe README last — it documents what you actually did, including any gotchas you hit during iteration.

## Scope cuts (what's out of scope for this PR)

- The Helm chart for Kubernetes deployment is deferred separately (DE-030) and is not in scope. The Traefik recipe leans toward Kubernetes-adjacent conventions (Docker labels for routing); when the Helm chart lands, the Traefik recipe's routing rules can be ported to a Kubernetes Ingress.
- Custom enterprise-CA workflows beyond the basic operator-provided-certs nginx recipe are out of scope. The nginx README points to "your enterprise CA's documentation" rather than re-deriving every certificate-procurement flow.
- DNS-01 challenge for Let's Encrypt (useful when port 80 is not reachable) is not in scope; the Caddy and Traefik recipes use HTTP-01 challenge. A follow-on PR can add DNS-01 examples for operators in restrictive network environments.
- HSTS, OCSP stapling, and the full battery of TLS hardening options are documented as "recommended next steps" in each recipe README but are not the focus of this PR — the focus is "TLS works."
- CI integration testing for the recipes is a follow-on PR. This PR ships the recipes as documentation and configuration; the CI test exercises them later.
- Reverse-proxy support for multi-domain deployments (separate FQDN for `web` vs. `api`) is out of scope; the recipes use a single FQDN with path-based routing for the API and the web app. Operators with multi-FQDN requirements can adapt the recipes.

## How this strengthens the project

Production TLS is a procurement-friction question that every operator asks. Shipping three working recipes — covering the easy path, the Kubernetes-adjacent path, and the traditional path — makes the answer concrete and the path to deployment a copy-paste. The recipes also strengthen the operational-maturity signal an experienced operator looks for: a serious project ships production-deployment artifacts, not just a development-mode compose file.

The recipes are also the entry point for operators evaluating LQ.AI on a real domain. Putting the project on a real URL is often the first non-trivial deployment step after `docker compose up`; the recipes make that step a one-page README rather than a research project.

## References

- [PRD §1.8 Security Posture](../../PRD.md#18-security-posture)
- [PRD §6 Deployment](../../PRD.md#6-deployment)
- [PRD §9 — DE-031 Reverse-proxy / TLS recipes (Caddy, Traefik, nginx)](../../PRD.md#9-deferred-enhancements-and-identified-future-work)
- [`docker-compose.yml`](../../../docker-compose.yml) — the compose stack the overlays compose against
- [`deploy/`](../../../deploy/) — existing deploy directory (currently `helm/` only, M2 deferred)
- Caddy documentation: https://caddyserver.com/docs/
- Traefik documentation: https://doc.traefik.io/traefik/
- nginx documentation: https://nginx.org/en/docs/
- Let's Encrypt: https://letsencrypt.org/
- Related: [Mini-PRD: Air-gap install verification CI test](air-gap-install-verification.md), [Mini-PRD: OpenSSF Scorecard + Best Practices Badge](openssf-scorecard-and-badges.md)

## Definition of "merged"

The PR is merged when (a) the acceptance criteria checklist is fully checked off, (b) the maintainer has reviewed each recipe and confirmed it brings up cleanly against a test FQDN (or has agreed with the contributor's recorded smoke verification), and (c) each recipe's README is reproducible by a non-maintainer following the steps verbatim. Practicing-attorney attestation is not required for this engineering-discipline contribution.
