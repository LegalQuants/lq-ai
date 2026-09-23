# Dev-environment guide

LQ.AI is three services with no shared in-process code — `api/` (FastAPI), `gateway/` (the
Inference Gateway), and `web/` (a SvelteKit fork of OpenWebUI) — talking over HTTP through
OpenAPI contracts. This page is the practical loop for running all three, plus the
database, worker, and object-store services they depend on.

## Bring up the stack

```bash
git clone https://github.com/legalquants/lq-ai.git
cd lq-ai
cp .env.example .env
# Edit .env with at least one LLM provider API key — or use the local profile
docker compose up -d                    # Mode 1: bring-your-own-key providers
# OR
docker compose --profile local up -d    # Mode 2: local Ollama, no external key
```

This starts `postgres`, `redis`, `rustfs`, `gateway`, `api`, `ingest-worker`, `arq-worker`,
and `web`; the local profile adds `ollama` (`docker-compose.yml`). `rustfs` is the object
store — it replaced a bundled MinIO ([ADR 0036](../adr/0036-bundled-object-store-rustfs.md)); the
`OBJECT_STORE_*` environment variables are the current contract, with the old `MINIO_*`
names still accepted as a fallback. `make run-dev` wraps the same bring-up command; `make
stop-dev` stops the stack without touching volumes.

## Python dependencies: `api/` and `gateway/`

Both subsystems lock dependencies with [uv](https://docs.astral.sh/uv/), decided in
[ADR 0023](../adr/0023-uv-lockfiles-gateway-api.md) so the transitive dependency tree is
deterministic and dependency pull requests at the Gateway's security boundary carry
concrete versions in the diff. For ordinary setup:

```bash
make install-api        # or install-gateway
cd api && .venv/bin/uvicorn app.main:app --reload --port 8000
```

`uv sync --frozen --extra dev` creates `.venv/` from the committed `uv.lock` without
changing it. Only run `uv lock` in a subsystem when you are deliberately changing
`pyproject.toml`, and commit the updated lockfile — CI gates on `uv lock --check`, so a
`pyproject.toml` edit without a relocked `uv.lock` fails CI, not only review.

Run the Python test suite in Docker if you don't want a local venv:

```bash
docker build -f api/Dockerfile.dev -t lq-ai-api-dev api/
docker run --rm lq-ai-api-dev python -m pytest tests/ -x
```

`Dockerfile.dev` installs the `[dev]` extras (pytest, respx, pytest-cov) on top of the
production image; the production `Dockerfile` deliberately does not, to keep the runtime
image's surface area minimal.

## Web: dependencies and the HMR gap

```bash
make install-web         # installs the committed package-lock.json
cd web && npm run dev
```

`web`'s Docker image, though, only builds a static SvelteKit bundle — there is no source
bind-mount and no dev server wired into the compose service. Editing `web/src` and
refreshing the browser shows nothing until you rebuild the image, which is a multi-minute
loop per change. [`web/docs/frontend-dev.md`](../../web/docs/frontend-dev.md) documents the
fix: run Vite natively on the host for hot-module reload, while keeping the dockerized
`web` container running (republished on port 8080) because OpenWebUI's own embedded
backend, which the SPA depends on at boot, only ships inside that image. The one-time
setup adds Vite's origin to `LQ_AI_CORS_ORIGINS` and points `web/.env` at the `api`
container; day to day, it's `WEB_HOST_PORT=8080 docker compose up -d …` followed by `npm
run dev`, then browsing to `:5173` rather than `:8080` or `:3000`. Before shipping a
frontend change, build the production image at least once and click through it there —
Vite dev and the static-adapter build can diverge.

When deliberately changing a Web dependency, use `npm install <package>` (or `npm
uninstall`) and commit both `web/package.json` and `web/package-lock.json`; use `npm ci`
for ordinary setup.

## Migrations

```bash
make migrate           # run Alembic migrations against the running api container
make migrate-status    # show the current head
```

> [!CAUTION]
> **Dev-environment hazard** — Never run host-side `alembic upgrade` against the live dev
> database (`127.0.0.1:15432/lq_ai`). It is the running stack's own database; a host-side
> migration desyncs it from what the containers expect and crash-loops the `api` trio.
> Verify a migration first against a throwaway `pgvector/pgvector:pg16` container instead,
> then apply it to the dev stack by rebuilding the workers — never by running Alembic from
> the host against `:15432`.

When a migration lands, rebuild `api`, `arq-worker`, and `ingest-worker` together. All
three are built from the `api` image and pin the same revision; rebuilding one alone
leaves the others crash-looping on a revision mismatch after the next restart.

## Two more rules that corrupt a shared stack

**Never `docker compose down -v`.** It wipes named volumes, including Postgres data,
object-store data, and any acceptance data that is expensive to recreate. Rebuild a single
service instead: `docker compose build web && docker compose up -d web`.

**Run both `ruff format` and `ruff check`** before pushing — CI runs them as separate
gates, and a format pass does not imply a lint pass.

## Next

- [On-ramp for engineers](../../CONTRIBUTING.md) — the gates and PR process this environment feeds into
- [Point a coding agent at the repository](coding-agent-onboarding.md)
