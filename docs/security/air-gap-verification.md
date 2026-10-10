# Air-Gap Install Verification

> **Status:** AI-drafted, pending maintainer + security review (roadmap 3.5, DE-032 + DE-233). The CI job described here is the authoritative artifact; if this document and the workflow disagree, the workflow wins.

LQ.AI's Mode 2 (`docker compose --profile local`) uses local Ollama inference at
Tier 1 without provider keys. The proposed
[`airgap-verify` workflow](../../.github/workflows/airgap-verify.yml) restricts the
deployment network, boots the stack fresh, drives a login/chat journey and
publishes packet-capture evidence. The DNS regression suite and the full manual
verification sequence passed locally on Linux arm64 (2026-10-10). Hosted Ubuntu
CI acceptance and security review are still pending.

This page explains exactly what that proof covers, how to reproduce it, what an air-gapped operator must pre-fetch, and — following the strongest structural idea in GitLab's and Mattermost's offline docs — an explicit list of what does **not** work air-gapped.

---

## 1. What the CI job proves

On every run (weekly, on demand, and on PRs touching the compose topology, gateway config, or the harness), the job:

1. **Builds and fetches everything while the network is open** — the four locally-built images (`api`, `gateway`, `web`, plus worker tags of the api image), the four digest-pinned third-party images (`pgvector`, `redis`, `rustfs`, `ollama`), and one Ollama model.
2. **Isolates container DNS before fresh boot** — a generated DNS-only Compose
   override sets each service's external DNS upstream to its own `127.0.0.1`.
   Docker's embedded resolver still answers internal service names. It cannot
   forward external names to host DNS; the runner's resolver is untouched.
3. **Seals the compose bridge** — an iptables `DOCKER-USER` chain drops DNS
   outside the stack subnet before the private-address allowlist. Other packets
   outside RFC1918/loopback are dropped as before
   ([`scripts/airgap/deny-egress.sh`](../../scripts/airgap/deny-egress.sh)).
4. **Starts an egress canary** — tcpdump on the bridge records direct DNS
   attempts outside the stack, public destinations and public-source replies
   ([`scripts/airgap/capture-egress.sh`](../../scripts/airgap/capture-egress.sh)).
5. **Boots the full stack fresh, under the seal** — every first-boot path runs offline: Alembic migrations, gateway config seeding from `gateway.yaml.example`, RustFS object-store setup (ADR 0036), first-run admin bootstrap.
6. **Drives a real user journey** — bootstrap-password login → forced password rotation → chat creation → a message routed to `ollama-local` → non-empty assistant response ([`scripts/airgap/drive-smoke.sh`](../../scripts/airgap/drive-smoke.sh)). It then asserts the gateway's `inference_routing_log` recorded the turn as `routed_provider='ollama-local'`, `routed_inference_tier=1`, with **zero** non-refused rows at any other tier.
7. **Asserts no direct outside DNS attempts or public-source replies** — fail on
   any UDP/TCP port-53 attempt outside the stack subnet, even without a reply,
   or on a packet from a non-private source. DNS failures produce
   `sealed.dns-attempts.txt` with packet evidence and a container IP map.
   Other observed outbound attempts remain inventoried in `sealed.attempts.txt`.
   Loopback lookups handled by Docker's embedded resolver are covered by the
   DNS upstream policy and resolver controls, rather than the bridge capture.
   An absence of replies alone does not prove that every outbound packet was
   dropped; the connection claim also depends on the installed firewall rules.
8. **Runs a connection negative control** — from inside the sealed gateway container (the one component that legitimately egresses in cloud mode), a TCP connect to a fixed public IP and an HTTPS request to `https://api.anthropic.com` must both **fail**, and the blocked attempts must **appear** in a second capture. This proves the seal blocks and the canary sees — a clean pcap cannot be a mis-wired no-op. No provider key is involved; unreachability of the cloud endpoint is the whole proof.

The DNS controls additionally check internal service names and fresh external
queries over both UDP and TCP. A separate `dns-negative.pcap` contains deliberate
direct public-DNS attempts: those must be blocked, captured, and rejected by the
same `assert-clean` acceptance check. A fast regression job exercises the resolver
against a controlled DNS server and checks synthetic captures without booting the
application stack. `dns-seal.compose.yml` is included in the evidence artifact.

Both connection pcaps (the sealed one — attempts only, zero replies — and the non-empty negative one) plus the `sealed.attempts.txt` inventory upload as the `airgap-evidence` workflow artifact — the audit trail for procurement conversations.

**Known attempted-egress sources (blocked under the seal; expect connection timeouts, not breakage, on a real air-gapped site):** the sealed boot surfaces phone-home attempts from upstream components — version/update checks and telemetry from the web UI and third-party base images. None of these are LQ.AI code paths (the api's only egress door is the gateway; the gateway's egress is provider-config-driven and Tier 1 is local). The per-run inventory in the evidence artifact is the authoritative, current list; if a new LQ.AI-authored component ever appears in it, that is a regression to treat as a bug.

### What it does NOT prove

Honesty about scope, per the project's conservative posture:

- **Not the transfer step.** CI builds images on the connected side of the fence; it proves the artifact set is *sufficient* once present, not the operator's media-transfer procedure (§3 covers that).
- **Not the ingestion pipeline offline.** The smoke covers login → chat → Tier-1 inference. Document ingestion has its own first-run downloads (§4) and is not yet exercised under the seal.
- **Explicit DNS test policy.** The bridge topology, service images, ports and
  application configuration stay unchanged, but the test overrides DNS upstream
  selection. It certifies operation with external DNS unavailable, not the
  operator's ordinary DNS configuration. DNS-over-HTTPS/TLS and private proxies
  are not independently classified by this port-53 assertion; the existing
  connection seal and its documented allowlist still apply.
- **Not the pinned-alias models.** The smoke routes to a small CPU-viable model via the gateway's raw `ollama-local/<model>` passthrough so the shipped `gateway.yaml.example` is used byte-identical. Tier derivation comes from the provider entry, not the model name, so the air-gap property is model-independent — but the qwen3.5 models the `local*` aliases pin are not themselves exercised in CI.

---

## 2. Reproducing locally

### Linux (exact CI mechanism)

```bash
cp .env.example .env   # no provider keys needed
docker compose build gateway web && docker compose build api
docker tag lq-ai-api:latest lq-ai-ingest-worker:latest
docker tag lq-ai-api:latest lq-ai-arq-worker:latest
docker compose --profile local pull postgres redis rustfs ollama
docker compose --profile local up -d --wait ollama
docker compose exec ollama ollama pull llama3.2:1b

./scripts/airgap/seal-dns.sh configure airgap-artifacts/dns-seal.compose.yml
export COMPOSE_FILE=docker-compose.yml:airgap-artifacts/dns-seal.compose.yml
trap './scripts/airgap/capture-egress.sh stop sealed || true; ./scripts/airgap/deny-egress.sh unseal' EXIT
./scripts/airgap/deny-egress.sh seal
./scripts/airgap/capture-egress.sh start sealed
docker compose --profile local up -d --wait --no-build --force-recreate
./scripts/airgap/seal-dns.sh verify
docker compose exec -T gateway python - < scripts/airgap/check-dns.py
./scripts/airgap/drive-smoke.sh
./scripts/airgap/capture-egress.sh stop sealed
./scripts/airgap/capture-egress.sh assert-clean sealed
./scripts/airgap/deny-egress.sh unseal   # when done
unset COMPOSE_FILE
trap - EXIT
```

Requires Docker Compose 2.24.4+ (`!override` replaces existing DNS upstreams), `sudo` for iptables/tcpdump; `jq`, `curl`, `openssl` for the harness. The regression suite additionally uses Python/pytest and Docker. The smoke assumes a **fresh database** (it reads the first-run admin password from the api logs) — don't run it against a dev stack you care about, and never `docker compose down -v` a stack you care about to get one.

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
| RustFS | `rustfs/rustfs:1.0.0@sha256:…` (pinned, ADR 0036) | same |
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
3. `docker compose --profile local pull postgres redis rustfs ollama`.
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
