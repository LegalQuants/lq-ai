# Hardware sizing

"Will it run on what I have?" has three honest answers in this repository, not one.
Below are the three configurations the canon actually gives numbers for. Outside
them, this page says so rather than guessing — a made-up minimum is worse than none.

## Configuration 1 — macOS desktop app

**Apple Silicon Mac (M1/M2/M3/M4), Docker Desktop installed and running, ~12 GB free
disk, an internet connection for first run.** [`docs/INSTALL-MAC.md`](../INSTALL-MAC.md)
states these as the prerequisites — no terminal, no cloned repository, but Docker
Desktop is a separate install the app links you to if it is missing or stopped.
Intel Macs are not named anywhere in the install doc — not documented as of the
checked commit, so treat Intel support as unconfirmed rather than assuming it works.
The ~12 GB is the install doc's planning figure, not a measured clean-install
footprint — nothing in the repository records disk use or elapsed time for this
path, and `docs/PRD.md`'s own fresh-install note for the same desktop launcher puts
the first-run image download alone at roughly 17 GB (see Configuration 2 below), so
leave headroom above the stated figure rather than treating it as a ceiling.

## Configuration 2 — Docker Compose, cloud provider keys (a small server or a laptop)

**~8 GB free disk and ~6 GB of RAM available to Docker**, per
[README.md](../../README.md#quick-start). This is the floor to bring the eight
always-on services up (`postgres`, `redis`, `rustfs`, `gateway`, `api`,
`ingest-worker`, `arq-worker`, `web`) — [`docker-compose.yml`](../../docker-compose.yml)
sets no CPU or memory `deploy.resources` limit on any of them, so nothing in the
compose file itself enforces or guarantees a ceiling either way.

> [!CAUTION]
> **Before you run this** — The 6 GB is guidance, not a boundary the stack enforces
> or the repository has measured: `docker-compose.yml` sets no memory limit, and
> nothing in the canon records at what allocation the stack stops coming up or how
> it fails. What the README's own troubleshooting section does say is that an
> immediate failure is a reason to check the allocation first: *"`docker compose up`
> fails immediately — confirm Docker Desktop is running and has at least 6 GB RAM
> allocated."* On macOS: Docker Desktop → Settings → Resources. Under memory
> pressure, expect a refused boot, a container killed after it started, or a build
> that crawls — not one predictable symptom. There is no in-app signal beyond the
> compose error itself; a container that never starts doesn't leave a growth curve
> to read.

What this floor does **not** cover: throughput under concurrent users, ingestion
latency for a large document corpus, or a recommended CPU core count. None of these
are measured anywhere in the repository as of the checked commit — if your
deployment plan depends on one of them, budget headroom above the floor rather than
treating it as sized.

The first `docker compose up -d` also *builds* `api`, `gateway`, `web`,
`ingest-worker`, and `arq-worker` from source rather than pulling them —
[`docker-compose.yml`](../../docker-compose.yml) gives each of those five a
`build:` block and no `image:` tag (`ingest-worker` and `arq-worker` reuse the
`./api` build context, so their layers are cached from the `api` build) — and pulls
the other three (`postgres`, `redis`, `rustfs`). How long the build takes and how
much disk it needs on an operator's own machine isn't measured anywhere in the
repository; the closest figures on record are two CI workflows' notes about their
GitHub-hosted runners, not a developer laptop: a cold compose build of roughly 20–30
minutes ([`.github/workflows/e2e.yml`](../../.github/workflows/e2e.yml)), and the
api-family image alone unpacking to ~12 GB with the BuildKit cache costing about as
much again
([`.github/workflows/stack-smoke.yml`](../../.github/workflows/stack-smoke.yml)) —
so read the README's ~8 GB as a planning figure for the images at rest, not a
verified minimum for a from-source build. A related, larger number from a different
install path: the macOS desktop launcher's first run downloads roughly 17 GB of
images (`api` ~9.5 GB, `web` ~6 GB, `gateway` ~1.6 GB, plus `proxy`) before it starts
pulling document-processing models — [docs/PRD.md](../PRD.md) records this as the
reason that first run can look frozen for 10–30 minutes on a slow connection. None of
these is the same number as the compose ~8 GB floor above (different install path,
different image set, different machine class), and none is reproduced here as a
general Compose expectation — cited so a slow first build or pull doesn't read as a
hang.

## Configuration 3 — Air-gapped / local-only inference

Start from Configuration 2's floor, then add:

- **`ollama` container** (`--profile local`) — no separate RAM/CPU minimum is stated
  in the repository; [`docker-compose.yml`](../../docker-compose.yml) ships GPU
  acceleration as an operator-uncommented block (`nvidia-docker`), so a GPU is
  optional, not required, but neither CPU-only nor GPU throughput is measured
  anywhere in the canon. Treat this as **not measured** rather than assuming either
  "works fine" or "needs a GPU."
- **Model storage** — [`docs/quickstart.md`](../quickstart.md) describes the
  `qwen3.5:9b` pull as "a few GB"; that is the only size figure the repository gives
  for any Ollama model. `local-fast` (`qwen3.5:4b-nvfp4`) and `local-thinking`
  (`qwen3.5:9b`) are the two aliases `gateway.yaml.example` ships pointed at Ollama —
  budget disk for whichever tag(s) you pull, on top of Configuration 2's floor.
- **First-ingestion download** — the ingest worker still pulls roughly 700 MB of
  Docling layout/OCR models from Hugging Face on the first document it processes
  (`lq_ai_docling_enabled` defaults to `True` in `api/app/config.py`), cached
  afterward in the `ingest-hf-cache` / `ingest-easyocr-cache` named volumes
  (`docker-compose.yml`). It is dead weight:
  [ADR 0026](../adr/0026-document-ingestion-parser-and-docling.md) records that
  Docling has never produced output here and decides its removal, so budget for the
  download only until that lands. It happens regardless of inference mode, but it
  matters most for an air-gapped plan: pull it while you still have network access.

See [Air-gapped and local-only inference](air-gapped.md) for the install steps and
what the repository can and cannot yet prove about Mode 2's network behavior.

## What isn't here

The Helm chart's
[`values.yaml`](../../deploy/helm/lq-ai/values.yaml) does set CPU and memory
requests and limits per component — `gateway` and `api` each request `200m`/`256Mi`,
limited to `1000m`/`1Gi` and `1000m`/`2Gi` respectively; `web` requests
`100m`/`256Mi`, limited to `500m`/`1Gi`; the Postgres, Redis, and object-store
StatefulSets carry only a storage request. Those are chart defaults to start from,
not a measured capacity recommendation, and the chart is **drafted** — it does not
deploy the two background workers at all (see
[Install with Helm](install-helm.md)) — so they aren't evidence the chart runs the
whole stack end to end. Beyond that: no per-seat or per-matter sizing, and no
benchmark of tokens-per-second on any hardware. If your plan needs one of those,
this page's honest answer is: not documented in the repository as of the checked
commit — measure it yourself against your own workload before you commit hardware
to it.

## Next

- [Air-gapped and local-only inference](air-gapped.md)
- [Install with Docker Compose](../../README.md#quick-start)
- [Install on macOS](../INSTALL-MAC.md)
