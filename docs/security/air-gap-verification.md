# Air-Gap Install Verification

> **Status:** AI-drafted, pending maintainer + security review (roadmap 3.5, DE-032 + DE-233). The CI job described here is the authoritative artifact; if this document and the workflow disagree, the workflow wins.

LQ.AI's Mode 2 (`docker compose --profile local`) is the air-gap-capable deployment: local Ollama inference at Tier 1, no provider keys, no outbound calls. Most self-hosted projects document air-gap support; in our survey of the ecosystem (GitLab, Mattermost, Sentry, k3s, Ollama), **none proves it in CI**. LQ.AI does: the [`airgap-verify` workflow](../../.github/workflows/airgap-verify.yml) seals the deployment network, boots the stack from scratch inside the seal, drives a real user journey, and publishes packet-capture evidence on every run.

This page explains exactly what that proof covers, how to reproduce it, what an air-gapped operator must pre-fetch, and — following the strongest structural idea in GitLab's and Mattermost's offline docs — an explicit list of what does **not** work air-gapped.

---

## 1. What the CI job proves

On every run (weekly, on demand, and on PRs touching the compose topology, gateway config, or the harness), the job:

1. **Builds and fetches everything while the network is open** — the four locally-built images (`api`, `gateway`, `web`, plus worker tags of the api image), the four digest-pinned third-party images (`pgvector`, `redis`, `minio`, `ollama`), and one Ollama model.
2. **Seals the compose bridge** — an iptables `DOCKER-USER` chain drops every packet leaving the bridge whose destination is not RFC1918/loopback ([`scripts/airgap/deny-egress.sh`](../../scripts/airgap/deny-egress.sh)).
3. **Starts an egress canary** — tcpdump on the bridge records any packet with a non-private destination, so even *attempts* the seal drops (tolerated-failure telemetry) are evidence ([`scripts/airgap/capture-egress.sh`](../../scripts/airgap/capture-egress.sh)).
4. **Boots the full stack fresh, under the seal** — every first-boot path runs offline: Alembic migrations, gateway config seeding from `gateway.yaml.example`, MinIO bucket setup, first-run admin bootstrap.
5. **Drives a real user journey** — bootstrap-password login → forced password rotation → chat creation → a message routed to `ollama-local` → non-empty assistant response ([`scripts/airgap/drive-smoke.sh`](../../scripts/airgap/drive-smoke.sh)). It then asserts the gateway's `inference_routing_log` recorded the turn as `routed_provider='ollama-local'`, `routed_inference_tier=1`, with **zero** non-refused rows at any other tier.
6. **Asserts the pcap is empty** — zero non-private-destination packets during the entire sealed phase.
7. **Runs a negative control** — from inside the sealed gateway container (the one component that legitimately egresses in cloud mode), a TCP connect to a fixed public IP and an HTTPS request to `https://api.anthropic.com` must both **fail**, and the blocked attempts must **appear** in a second capture. This proves the seal blocks and the canary sees — a clean pcap cannot be a mis-wired no-op. No provider key is involved; unreachability of the cloud endpoint is the whole proof.

Both pcaps (the empty sealed one, the non-empty negative one) upload as the `airgap-evidence` workflow artifact — the audit trail for procurement conversations.

### What it does NOT prove

Honesty about scope, per the project's conservative posture:

- **Not the transfer step.** CI builds images on the connected side of the fence; it proves the artifact set is *sufficient* once present, not the operator's media-transfer procedure (§3 covers that).
- **Not the ingestion pipeline offline.** The smoke covers login → chat → Tier-1 inference. Document ingestion has its own first-run downloads (§4) and is not yet exercised under the seal.
- **DNS side channel.** Docker's embedded DNS resolves names via the *host's* resolver from the host network namespace, so name resolution from sealed containers may still succeed in CI; the seal blocks the subsequent connection and the canary records the attempt. A physical air gap has no resolver at all — this makes the CI environment slightly *more* permissive than reality, which is the safe direction for a proof (nothing can pass in CI that would fail on a real air gap for network reasons, only vice versa).
- **Not the pinned-alias models.** The smoke routes to a small CPU-viable model via the gateway's raw `ollama-local/<model>` passthrough so the shipped `gateway.yaml.example` is used byte-identical. Tier derivation comes from the provider entry, not the model name, so the air-gap property is model-independent — but the qwen3.5 models the `local*` aliases pin are not themselves exercised in CI.

---

## 2. Reproducing locally

### Linux (exact CI mechanism)

```bash
cp .env.example .env   # no provider keys needed
docker compose build gateway web && docker compose build api
docker tag lq-ai-api:latest lq-ai-ingest-worker:latest
docker tag lq-ai-api:latest lq-ai-arq-worker:latest
docker compose --profile local pull postgres redis minio ollama
docker compose --profile local up -d --wait ollama
docker compose exec ollama ollama pull llama3.2:1b

./scripts/airgap/deny-egress.sh seal
./scripts/airgap/capture-egress.sh start sealed
docker compose --profile local up -d --wait --no-build --force-recreate
./scripts/airgap/drive-smoke.sh
./scripts/airgap/capture-egress.sh stop sealed
./scripts/airgap/capture-egress.sh assert-clean sealed
./scripts/airgap/deny-egress.sh unseal   # when done
```

Requires `sudo` for iptables/tcpdump; `jq`, `curl`, `openssl` for the smoke driver. The smoke assumes a **fresh database** (it reads the first-run admin password from the api logs) — don't run it against a dev stack you care about, and never `docker compose down -v` a stack you care about to get one.

### Non-Linux / declarative alternative: `internal: true`

On Docker Desktop (macOS/Windows) the daemon runs in a VM, so host iptables never sees container traffic. The declarative alternative is a compose override that marks the network internal:

```yaml
# docker-compose.airgap-override.yml (local reproduction only — not shipped)
networks:
  default:
    internal: true
```

`docker compose --profile local -f docker-compose.yml -f docker-compose.airgap-override.yml up -d` gives containers no route out at all. Trade-offs, and why CI does **not** use this: it changes the topology under test (the proof should certify the shipped compose file), and `internal: true` disables published ports, so the host-side smoke driver can't reach `127.0.0.1:8000` — you must drive the smoke from a container attached to the network. Use it as a convenient local sanity check, not as the certified proof.

---

## 3. Artifact bill of materials

Everything the deployment needs at runtime, per component. Authoritative image digests live in [`docker-compose.yml`](../../docker-compose.yml) — they are pinned there precisely so this list stays short; do not duplicate digests here.

| Component | Artifact | How to carry it across the gap |
|---|---|---|
| Postgres | `pgvector/pgvector:pg16@sha256:…` (pinned in compose) | `docker save` → media → `docker load` |
| Redis | `redis:7-alpine@sha256:…` (pinned) | same |
| MinIO | `minio/minio:latest@sha256:…` (pinned) | same |
| Ollama server | `ollama/ollama:latest@sha256:…` (pinned) | same |
| api / ingest-worker / arq-worker | `lq-ai-api` image (one image, three service tags) | build on a connected host from a repo checkout, `docker save` |
| gateway | `lq-ai-gateway` image | same |
| web | `lq-ai-web` image (Vite production build happens at image build) | same |
| **Ollama model blobs** | The models your `gateway.yaml` aliases point at — by default `qwen3.5:9b` (`local`, `local-thinking`) and `qwen3.5:4b-nvfp4` (`local-fast`) | Ollama models are plain files: `ollama pull` on a connected host, then copy the model directory (`~/.ollama`, or the `ollamadata` volume; `OLLAMA_MODELS` overrides the path) to the offline host. The server detects them with zero phone-home. |
| **Ingestion models** (first-run download trap) | Docling's Hugging Face models + EasyOCR detection models (~700 MB total), fetched lazily on the *first document ingestion*, into the `ingest-hf-cache` and `ingest-easyocr-cache` volumes | Ingest one document on a connected staging host, then transfer the two volumes' contents. Without this, the first ingestion **fails offline**. |
| Gateway config | `gateway.yaml.example` (in the repo; seeds the writable `gateway-config` volume on first boot) | comes with the repo checkout / image bundle |
| Skills | `skills/` directory (filesystem-canonical, mounted read-only) | comes with the repo checkout |

**Not needed at runtime:** Python wheels, npm packages, or any package index. The images are self-contained — `pip`/`npm` never run in a booted container, and the CI proof would catch it if they did.

### Pre-fetch checklist (connected host)

1. `git clone` the repo at the release tag.
2. `docker compose build gateway web && docker compose build api` (+ tag the two worker images from `lq-ai-api`, as in §2).
3. `docker compose --profile local pull postgres redis minio ollama`.
4. `docker save` all seven images to a tarball; checksum it.
5. `ollama pull` every model referenced by your `gateway.yaml` `model_aliases` (defaults: `qwen3.5:9b`, `qwen3.5:4b-nvfp4`); copy the model directory.
6. Ingest one throwaway document on the staging stack; copy the `ingest-hf-cache` and `ingest-easyocr-cache` volume contents.
7. Transfer repo checkout + image tarball + model directory + caches on approved media; `docker load` on the offline host.
8. Edit `.env` (secrets only — no provider keys) and repoint the `embedding` alias per §4 before first use of knowledge bases.

---

## 4. What does NOT work air-gapped (degradation list)

Explicit, following the GitLab/Mattermost pattern. Most of these are **off by default**, which keeps this list an inventory rather than a hardening checklist.

| Capability | Behavior offline | Operator action |
|---|---|---|
| Cloud inference (Tiers 2–5): `smart`, `fast`, `budget` aliases; anthropic/openai/vertex/bedrock/azure providers | Unreachable; `local*` aliases have empty fallback chains by design, so Tier 1 requests never silently degrade to cloud — and cloud requests fail cleanly | Use `local`, `local-fast`, `local-thinking`, or raw `ollama-local/<model>`. Optionally delete the cloud provider entries from `gateway.yaml`. |
| `embedding` alias (defaults to OpenAI `text-embedding-3-small`) | Embedding calls fail; ingestion completes but chunks get no vectors, so KB retrieval degrades to keyword-only (`chunks_embedded: 0`) | Repoint the alias at a local embedding provider, or accept keyword-only retrieval |
| Citation-engine paraphrase judge (`citation_engine.judge_model: fast` → cloud) | Stage-3 judge calls fail; citations stop at the exact/tolerant-match stages | Repoint `judge_model` at a local alias |
| Anonymization middleware | Not applicable — bypassed for Tier 1 by design (no benefit when data never leaves) | None |
| Legal research sources: CourtListener, GovInfo, EDGAR, EUR-Lex | Unreachable | Leave disabled (they are opt-in and off by default) |
| Slack / Teams bridges (`--profile slack` / `--profile teams`) | Require cloud APIs and inbound webhooks | Do not enable the profiles |
| MCP to external servers | Unreachable | Configure only in-network MCP servers, or none |
| Telemetry: OpenTelemetry exporter, Langfuse | No-op / connection errors if pointed outside | Off by default; leave off, or point at in-network collectors |
| Budget alert email | Undeliverable without an in-network SMTP relay | Configure an internal relay or ignore |
| Let's Encrypt / ACME TLS issuance | Unreachable | Use an internal CA with manual rotation — see the reverse-proxy + TLS recipe (roadmap 3.7) |
| Word add-in | Office.js loads from Microsoft's CDN **on the client machine** — outside this deployment's boundary | Only usable where clients have that access; not an egress from the LQ.AI stack itself |
| Image/version update checks | None exist — images are digest-pinned and only change by explicit bump | None (the weekly CI run is the drift detector) |

---

## 5. Suggested follow-up (not built here)

**Release-bundle as a release asset** (k3s pattern; deserves a DE row in PRD §9): have `release.yml` publish a per-release `docker save` bundle of all seven images + checksums + provenance, and make this CI job consume *that exact bundle* instead of building in-job. The test would then certify the shipped artifact byte-for-byte — the procurement-grade version of this claim — and simultaneously eliminate steps 1–4 of the operator's pre-fetch checklist. Sentry's single first-class `SENTRY_AIR_GAP` flag is the other adoptable pattern; for LQ.AI this is likely a documented profile rather than new code, since egress is already confined to the gateway.
