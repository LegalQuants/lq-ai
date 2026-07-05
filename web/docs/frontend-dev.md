# Frontend dev loop: running `web/` natively with HMR

> **Problem this solves:** the `web` Compose service only builds a static
> SvelteKit bundle (see its Dockerfile) — there's no source bind-mount and no
> dev command wired up. Editing `web/src` and refreshing the browser shows
> nothing until you `docker compose build web && docker compose up -d web`.
> That's a multi-minute loop per change, which makes frontend iteration
> painful.
>
> **The fix:** run Vite's dev server natively on the host for HMR, but keep
> the dockerized `web` container running too, republished on port `8080`.
> That container still exists — see below for why — and everything else
> (`api`, `gateway`, `postgres`, `redis`, `minio`, workers) runs in Docker as
> usual.

## Why the dockerized `web` container is still needed

The `web/` fork is OpenWebUI, and OpenWebUI ships its own embedded Python
backend (`web/backend/`) inside the same image as the static bundle — this is
separate from LQ.AI's `api/` service. That embedded backend serves
`/api/config`, websockets, and other OpenWebUI-native endpoints that the SPA
needs on boot.

Vite's dev mode **hardcodes** the assumption that this backend lives at
`<hostname>:8080` (`web/src/lib/constants.ts`):

```ts
export const WEBUI_HOSTNAME = browser ? (dev ? `${location.hostname}:8080` : ``) : '';
```

Running `npm run dev` with nothing listening on `:8080` fails silently
(`getBackendConfig()` throws) and the SPA redirects to `/error` ("Backend
Required" / "unsupported method (frontend only)").

The upstream-correct fix is to also run OpenWebUI's own backend — it ships a
`web/backend/dev.sh` for exactly this. We deliberately **don't** do that
natively: its `requirements.txt` pulls in `torch`, `chromadb`,
`sentence-transformers`, `onnxruntime` — a slow, heavy native install for
code LQ.AI barely touches (LQ.AI's own customizations live in `web/src`; the
embedded backend's RAG bits are already disabled via
`RAG_EMBEDDING_ENGINE=openai` in `docker-compose.yml`).

Instead: keep using the already-built `web` Docker image (no native Python
install, no rebuild needed unless you touch `web/backend/`), just republish
its port as `8080` so it lands where Vite expects it, and let Vite handle
everything under `web/src`.

## One-time setup

Add Vite's origin (5173) to `LQ_AI_CORS_ORIGINS` in your repo-root `.env`,
alongside the dockerized shell's origin, so LQ.AI's `api/` accepts
cross-origin calls from both:

```bash
LQ_AI_CORS_ORIGINS=http://localhost:3000,http://localhost:5173
```

(The OpenWebUI-embedded backend on :8080 doesn't need a CORS change — its
`CORS_ALLOW_ORIGIN` is unset in `docker-compose.yml` and defaults to `*`.)

**Don't** change `WEB_HOST_PORT` in `.env` itself — `:3000` stays the default
for the normal fully-dockerized flow. Override it inline, per invocation,
only when starting `web` for this dev flow (see below).

Then install `web/`'s frontend dependencies on the host once:

```bash
cd web
npm install
```

## Day to day

Bring up the backend, including the dockerized `web` container — republished
on `:8080` for this session only via an inline env override:

```bash
WEB_HOST_PORT=8080 docker compose up -d postgres redis minio gateway api ingest-worker arq-worker web
```

Then run the frontend natively:

```bash
cd web
npm run dev
```

Browse to **`http://localhost:5173`** (not `:8080` or `:3000`). Vite serves
with full HMR: edits to `.svelte`, `.ts`, and CSS files apply immediately in
the browser, no rebuild, no container restart.

- OpenWebUI-native calls (config, auth shell, websockets) go to
  `http://localhost:8080` (the dockerized container).
- LQ.AI-specific calls go to `http://localhost:8000/api/v1` (the `api`
  container), per `web/.env`'s `PUBLIC_LQ_AI_API_BASE_URL`.

To go back to the fully-dockerized stack (e.g. to sanity-check the production
build before a PR), stop the Vite process and recreate `web` without the
override — `.env`'s default (`WEB_HOST_PORT=3000`) takes over:

```bash
docker compose up -d web
```

## Known gaps

- Vite dev mode is **not** a substitute for the production build. Before
  shipping a frontend change, run `docker compose build web && docker
  compose up -d web` at least once (with `WEB_HOST_PORT=3000`) and click
  through the change there — Vite dev and the static-adapter production
  build can diverge (see `svelte.config.js` / `web/Dockerfile`).
- If you touch `web/backend/` (OpenWebUI's embedded Python backend, not
  LQ.AI's `api/`), you must `docker compose build web` to pick up the
  change — there's no native/hot loop for that code in this setup.
- `npm run dev` runs `pyodide:fetch` first (downloads Pyodide artifacts into
  `web/static/pyodide`); this is a one-time cost per checkout, not per
  restart.
- This doc covers `web/` only. The Word add-in (`word-addin/`) has its own
  build step — see `word-addin/README.md`.
