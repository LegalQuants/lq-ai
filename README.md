# LQ.AI

> **Open-source AI for legal teams. Bring your own keys, run it where you want, own your data.**

[![License: Apache 2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)
[![PRD](https://img.shields.io/badge/PRD-v0.2-green.svg)](docs/PRD.md)
[![Status](https://img.shields.io/badge/Status-Pre--Release-orange.svg)](#project-status)
[![SLSA 3](https://img.shields.io/badge/SLSA-Level%203-green)](https://slsa.dev) [![Security Policy](https://img.shields.io/badge/Security-Policy-blue)](./SECURITY.md)

LQ.AI is a self-hosted AI platform purpose-built for legal teams. It delivers conversational chat with persistent history and matter-scoped projects, character-verifiable citations against source documents (M2's four-stage Citation Engine), a privacy-preserving anonymization layer for cloud inference (M2), reusable workflow skills authored in the open [agentskills.io / Anthropic Claude Skills](https://github.com/anthropics/skills) format, and a curated library of starter skills for the everyday work lawyers actually do — running on a laptop, an internal server, or a cloud VM, against the customer's choice of model (Anthropic, OpenAI, Azure OpenAI, or local Ollama out of the box), with zero license fees.

Playbooks (codified legal positions for automated contract review), a Microsoft Word add-in, multi-document tabular review, and a Slack/Teams light-intake bridge are committed for M3. The Autonomous Layer (background agents) and Contract Repository (relationship graph over contract sets) are committed for M4. See [Project status](#project-status) below for the current shipped-vs-roadmap split.

The project's reason for existing is simple: **legal teams should not have to choose between AI assistance and data sovereignty.** Every other capable tool in this category is a closed-source SaaS that requires sending privileged information to a third-party vendor. LQ.AI runs in your environment, with your keys, against your choice of model — including fully air-gapped deployments using local inference.

---

## Why this project exists

Commercial in-house legal AI products treat their prompt engineering as proprietary moat. The skills, playbooks, citation logic, and verification heuristics that shape what the user sees are hidden inside closed-source applications, presented as "AI" but functionally indistinguishable from "a system prompt the vendor refuses to show you." Customers pay significant per-seat fees for software whose only real innovation is a hidden prompt — without any way to see, debug, or improve it.

LQ.AI inverts this. **Every artifact that shapes the user's experience is visible work product.** The skills are open source. The playbooks are open source. The citation engine's verification logic is open source. The Enhance Prompt rewriter is open source. The Organization Profile that captures org-wide voice is open source. When a user clicks "view this skill" on any active skill, they see the actual `SKILL.md` and supporting files, formatted for human reading, with provenance and the ability to fork.

The position implied by all of this is uncomfortable for the rest of the legal-AI category, and that is intentional. Customers who have been paying for software whose only real innovation is a hidden system prompt are entitled to see what they have actually been buying. When the curtain is pulled back, some products will hold up. Many will not. LQ.AI's bet is that an open, transparent product built on community-curated skills is better than a closed, opaque product built on the assumption that the user cannot see what is happening — and that the resulting trust is worth more than the marketing.

For more on this philosophy, see [PRD §1.3 Transparency as a Founding Principle](docs/PRD.md#13-transparency-as-a-founding-principle) and [§7.1 Project Philosophy](docs/PRD.md#71-project-philosophy).

---

## What you can verify

The trust model for a self-hosted, open-source legal AI product is structurally different from the trust model for a closed-source SaaS product. You don't have to take our word for any claim in this document. The verification path for everything we say about LQ.AI runs through code you can read: the inference gateway's routing logic, the audit logger, the skills, the test suite, the build provenance. Compliance attestations and procurement questionnaire responses are useful where they apply; we publish them too ([Compliance Pack](docs/compliance/README.md), [Procurement Pack mini-PRD](docs/contribute/mini-prds/procurement-readiness-pack.md)). But the substantive verification of what LQ.AI does is in the source — including the parts that are not wired yet, which we list directly in [HONEST-STATE.md](docs/HONEST-STATE.md). If the README claims something and the code does not back it up, the code is canonical; please [open an issue](https://github.com/LegalQuants/lq-ai/issues).

---

## What it does

LQ.AI ships with a curated set of capabilities calibrated to legal work. The capability set in v1 (M1–M4):

**Conversational core with persistent history.** Multi-turn chat organized in a sidebar, with skills and files attached per chat. Search across all chat history. Streaming responses with markdown rendering. Export to Markdown, plain text, or DOCX.

**Skill Library.** Reusable structured prompt artifacts in the [agentskills.io / Anthropic Claude Skills format](https://github.com/anthropics/skills) — a folder containing `SKILL.md` (with YAML frontmatter) and optional supporting files. Three tiers: built-in skills (ship with the product), user skills (you create), and shared skills (your team or org shares). Every active skill is one click away from being readable, debuggable, and forkable. The Skill Creator is itself a skill — a meta-skill you invoke to build new skills via conversation.

**Citation Engine (M2).** Verifies every model-emitted citation against the source document at character precision before rendering. Four-stage cascade:

1. **Exact match** — byte-for-byte equality at the source offsets.
2. **Tolerant match** — normalized fuzzy match (smart-quote folding, whitespace collapse, OCR-confusion rules when the document was OCR'd) at a 95% similarity threshold.
3. **Paraphrase judge** — LLM judge call that returns `yes` / `partial` / `no` with `high` / `medium` / `low` confidence; partial verdicts persist with a `partial=true` flag so the UI can render "verified with caveats" distinctly.
4. **Ensemble verification** — opt-in (per-skill, per-project, or deployment-default) parallel dispatch across N judge models with strict (all-agree) or majority (simple-majority) aggregation. The privacy envelope (max tier across the judge ensemble) persists per row so operators can audit which chats had citations sent to weaker tiers.

The chat UI renders citations as four visual states: green (exact / tolerant match), yellow (paraphrase or ensemble judgment), red (unverified). Failed citations surface as "unverified" rather than as confident-looking wrong text. The full verification path is open source: an attorney whose work product depends on a citation can read exactly how it was verified. See [`docs/citation-engine.md`](docs/citation-engine.md) for the full cascade reference and [`api/app/citation/verification.py`](api/app/citation/verification.py) for the implementation.

**Projects (matter-scoped containers).** A user-curated container that scopes a set of chats, files, skills, playbooks, and a free-form context document around a single matter — a deal, a counterparty, a regulatory question, a policy refresh. Chats inside a Project automatically inherit the Project's attached files, skills, and context. Projects carry an optional `privileged: true` flag that forces minimum inference tier and marks every chat and audit-log entry as privileged.

**Organization Profile.** A singleton skill at the deployment level capturing your team's voice, jurisdiction, industry, standard positions, and escalation thresholds. Skills draw on it as context. Without it, every skill has to relearn the org from scratch every time. Like every other skill, it is open source and inspectable.

**Inference Tier Awareness.** A persistent badge in the chat UI shows which Inference Tier (1–5) your current chat is running on — from local-only inference (Tier 1) through enterprise managed inference with ZDR (Tier 3) to consumer/free endpoints (Tier 5). Click the badge for what the tier implies: where the data is going, what the provider's retention policy is, whether anonymization is on. **Tier-floor enforcement** is a first-class gateway feature: skills declare a `minimum_inference_tier` in their frontmatter, projects declare one in their database row, callers can override per-request, and the gateway refuses any routing weaker than the effective floor with HTTP 403 `tier_below_minimum`. A privileged project paired with `minimum_inference_tier=1` produces fully sealed local inference — no outbound network, no anonymization rewriting, audit trail captures the local routing.

**Audit log.** Append-only `audit_log` table records every state-changing action with first-class columns for `privilege_marked`, `privilege_basis`, `routed_inference_tier`, `routed_provider`, plus a JSONB `details` field for action-specific context. Admin-gated `GET /admin/audit-log` endpoint supports filtering by user, resource, action, privilege, tier, and timestamp range; paginated for large windows. Privileged-matter compliance evidence is one query: `?privilege_marked=true&from_timestamp=...&to_timestamp=...`. Cross-references to the gateway's `inference_routing_log` (which records `anonymization_applied`, latency, cost estimate, and request correlation id) via `request_id` for end-to-end pipeline audit. See [`docs/procurement/sig-lite.md`](docs/procurement/sig-lite.md) for the procurement-team-facing audit posture.

**Files / Knowledge Bases.** Persistent collections of documents accessible across chats. Hybrid retrieval combining vector similarity (text-embedding-3-small or operator-configured embedding model via pgvector) with Postgres full-text search; the per-KB `hybrid_alpha` slider tunes the vector/FTS weight at retrieval time. Document ingestion uses Docling for layout-aware parsing of complex PDFs (multi-column, tables, footnotes) with PyMuPDF as the fast path for simpler documents. (Scanned-PDF OCR is not yet implemented — the pipeline parses text-bearing PDFs only and sets `was_ocrd=false`; OCR is tracked as DE-320.) Character-level offsets land in `documents.normalized_content` for the Citation Engine to verify against. KB-attached chats automatically retrieve before each turn, prepend a citation-formatted context block, and write a `📎 KB retrieval` audit row visible in Receipts.

**Enhance Prompt.** A prompt-rewriting skill that runs as an optional pre-step. You type a short, natural-language question; Enhance Prompt expands it into a structured legal prompt (role, jurisdiction, audience, scope, output format, constraints, citation expectations) and shows you the expanded version before submission. The skill itself is inspectable — you can read the SKILL.md driving the enhancement at any time.

**Playbooks (M3, shipped).** Codified legal positions for automated contract review — a LangGraph executor (retrieve → classify → redline → compile) plus an Easy Playbook auto-generation wizard that drafts a Playbook from prior agreements. Five built-in playbooks are seeded: NDA — Mutual, NDA — Unilateral, MSA — SaaS, MSA — Commercial-Purchase, DPA — GDPR. Per-position assessments carry the verbatim matched clause text; full Citation-Engine verification for the playbook executor is deferred. See [`docs/playbooks.md`](docs/playbooks.md).

**Word Add-In (M3, plumbing shipped).** A Microsoft Office.js task pane add-in installable via the unsigned-manifest path (Microsoft 365 Admin Center), authenticated against your deployment with a version handshake. The in-pane feature surface (run skills, execute Playbooks, redlines-as-tracked-changes, comments, document Q&A) is deferred to M4 / community ([DE-287](docs/PRD.md#9-deferred-enhancements-and-identified-future-work)); the signed/distributed manifest is community-led ([DE-295](docs/PRD.md#9-deferred-enhancements-and-identified-future-work)). See [`docs/word-addin.md`](docs/word-addin.md).

**Tabular / Multi-Document Review (M3, shipped).** Structured grid output across N documents — a row per document, a column per question — with per-cell grounding chunks and XLSX/CSV export. "Show me the term length, survival period, carveouts, and governing law for each of these 30 NDAs." Per-cell citations are surfaced as display-only chunk references today ([DE-309](docs/PRD.md#9-deferred-enhancements-and-identified-future-work)). See [`docs/tabular-review.md`](docs/tabular-review.md).

**Slack / Teams Light Intake Bridge (M3, plumbing shipped).** Standalone `slack-bridge` + `teams-bridge` services (opt-in Compose profiles) with OAuth install + identity binding + an admin management surface. The `/lq` slash-command quick-skill surface is deferred to M4 / community ([DE-288](docs/PRD.md#9-deferred-enhancements-and-identified-future-work)); a real OAuth round-trip against a public tunnel has not yet been exercised end-to-end ([DE-312](docs/PRD.md#9-deferred-enhancements-and-identified-future-work)). Light intake, deliberately not full triage/SLA/approvals — that is Streamline AI's category. See [`docs/intake-bridges.md`](docs/intake-bridges.md).

**Anonymization Layer (M2).** Pre-processing step in the Inference Gateway that pseudonymizes sensitive entities (names, organizations, addresses, email addresses, phone numbers, case numbers, matter numbers) before requests leave for the model provider; rehydrates pseudonyms back to originals on the response path. Built on [Presidio](https://github.com/microsoft/presidio) + spaCy + two custom legal recognizers (`CaseNumberRecognizer`, `MatterNumberRecognizer`) that catch legal-specific identifiers the default Presidio config misses. Per-request `PseudonymMapper` is in-memory only — never persisted, never logged, dropped on function exit.

Streaming-aware: the response-path rehydrator holds a bounded tail buffer (~25 chars typical) so pseudonyms can crystallize cleanly when the SSE stream splits them across chunks. Per-request opt-out (`anonymize=false`) supported for callers that need raw content (the Citation Engine's judge calls use this so the judge sees actual cited text). Privileged-project chats skip the layer entirely (Decision A: rewriting privileged work product risks corrupting it). Retrieved source documents stay un-pseudonymized so the model has intact source quotes for citation grounding (Decision M2-1; opt-in opposite via the `lq_ai_skip_anonymization` field on messages).

The privacy fallback for Tier 3+ inference when local (Tier 1) is impractical but defensible privacy posture is still required. See [`docs/security/anonymization.md`](docs/security/anonymization.md) for the full middleware contract, recognizer set, decision basis, and known limitations.

**Honest validation posture.** The custom recognizers, middleware integration, round-trip correctness, and edge cases are exercised by ~24 unit + integration tests. The Presidio default-recognizer recall and precision **on legal-document corpus specifically** is empirically unmeasured — Presidio's published metrics target general English (news, social media), not legal prose. A recognizer miss is a silent confidentiality incident (unlike citation misses, which surface in the UI as "unverified"). Operators with high-confidentiality requirements should read [`docs/security/anonymization.md` §"What's validated vs what's unvalidated"](docs/security/anonymization.md#whats-validated-vs-whats-unvalidated) and consider Tier 1 (Ollama local) routing for matters where the unvalidated risk is unacceptable. Empirical validation on a curated legal-document corpus is welcomed as a community contribution — the bounded scope is documented at [PRD §9 / DE-282](docs/PRD.md#de-282--anonymization-layer-empirical-validation-on-legal-document-corpus). We win by being honest about where to trust and where to be careful, not by overclaiming.

**Autonomous Layer (M4).** Long-running per-user agents that observe activity, learn patterns, take proactive actions. Cron-scheduled tasks; watches that trigger on KB changes or document arrivals; per-user persistent memory store with user-curation UI.

**Contract Repository — Auto-Relationship Detection (M4).** Pipeline that produces a relationship graph over a Knowledge Base of contracts: amendments, restatements, references, master/sub. When you ask "which liability cap actually governs?", the system uses the graph to determine the operative document chain.

**Forward-looking (M5–M7, community-driven).** Workflow-aware context layer that integrates email, calendar, task systems, and document stores via [MCP (Model Context Protocol)](https://modelcontextprotocol.io); a Workspace Concierge that produces ranked Today views with rationales; agent dispatch with human-in-the-loop guardrails. See [PRD §8.5](docs/PRD.md#m5m7--forward-looking-workflow-intelligence-community-driven-not-committed) for the trajectory.

The full capability specification is in [PRD §3](docs/PRD.md#3-capability-specifications). The M3 capabilities above shipped at v0.3.0 — Playbooks and Tabular Review fully; the Word Add-In and Slack/Teams bridges as plumbing with their richer surfaces deferred to M4 (see each capability doc + the linked DEs). The Autonomous Layer and Contract Repository are M4. See [HONEST-STATE.md](docs/HONEST-STATE.md) for the current shipped-vs-deferred catalog with verification paths for every row.

---

## Starter skills (ship with M1)

Ten starter skills ship with the M1 release, calibrated to the everyday work lawyers actually do:

| # | Skill | What it does |
|---|---|---|
| 1 | **NDA Review** | Reviews mutual or unilateral NDAs for unusual provisions, calibrated by perspective (discloser / recipient / mutual) and deal context. |
| 2 | **MSA Review — SaaS** | Reviews SaaS Master Services Agreements from the customer or vendor perspective, with severity rubric and Playbook-aligned position. |
| 3 | **MSA Review — Commercial Purchase** | Same shape as SaaS MSA but calibrated to commercial purchase agreements (goods, services, professional services). |
| 4 | **DPA Checklist Review** | Reviews Data Processing Agreements against multiple regulatory regimes (GDPR, US state privacy, HIPAA BAA, general commercial). |
| 5 | **Vendor Privacy Policy First Pass** | Triage assessment of a vendor's privacy policy — structured summary plus red-flag identification. |
| 6 | **Contract QA** | Adaptive Q&A against a single contract, with citation-grounded answers. |
| 7 | **Action Items from Client Alert** | Extracts time-sensitive action items, deadlines, and obligations from a regulatory bulletin or law firm memo into a deadline-organized checklist. |
| 8 | **Comms Improver** | Rewrites legal-jargon-heavy text in plain language for a specified non-legal audience (executive, sales team, customer-facing, etc.). |
| 9 | **Enhance Prompt** | The prompt-rewriting skill that runs as an optional pre-step on any chat. |
| 10 | **Skill Creator** | Meta-skill for building new skills via conversation. |

Each starter skill is **open source**, **inspectable in the application**, and **forkable**. If a skill produces output you disagree with, you can read the `SKILL.md`, change it, save your fork, and use the version that reflects your team's actual practice.

The next layer of skills is on the deferred-enhancement list and welcomes community contribution. See [PRD §9](docs/PRD.md#9-deferred-enhancements-and-identified-future-work) for the backlog.

---

## Community skills

In addition to the 10 built-in starter skills in `skills/`, LQ.AI ships with a community skill catalog via the [LegalQuants/lq-skills](https://github.com/LegalQuants/lq-skills) git submodule, mounted at `skills/community/`.

- **30+ additional skills** authored by lawyer-builders across 17+ jurisdictions — covering areas like UK litigation, US state privacy law, corporate governance, statutory analysis, and more.
- **Same open format.** Every community skill is a `SKILL.md` in the same `agentskills.io` format as the built-ins — readable, debuggable, and forkable in the application.
- **Built-in wins on slug collision.** The 10 built-in skills always take precedence if their slug also appears in the community catalog; the community version is silently skipped (logged at INFO level for operator visibility).
- **Attribution in the API.** Community skills carry `source: "community"` in the API response; built-ins carry `source: "built-in"`. The frontend can use this field to render an attribution badge.
- **Upstream updates flow in.** New skills landed in [LegalQuants/lq-skills](https://github.com/LegalQuants/lq-skills) become available in any LQ.AI deployment on the next submodule update — operators do not rebuild the application to pick up new community skills. The relationship is intentionally a pull, not a push: each operator chooses when to refresh and which upstream commit to pin to.

To update the community catalog to the latest upstream commit:

```bash
git submodule update --remote skills/community
```

**Authoring a new community skill?** Open a PR against [LegalQuants/lq-skills](https://github.com/LegalQuants/lq-skills) — skills merged there flow into every downstream LQ.AI deployment that refreshes the submodule. The contribution guide and review norms live in that repository; the substance bar (practicing-attorney attestation, peer review for skills containing legal substance) mirrors `skills/CONTRIBUTING.md` in this repo. The `lq-skills` repo is the right home for skills meant to be shared across operators; this repo's `skills/` directory is for the 10 starter skills that ship with the application.

### LegalQuants ecosystem

LQ.AI sits inside a broader [LegalQuants](https://github.com/LegalQuants) ecosystem of open-source legal-AI tooling. The integration pattern — open-source, MIT/Apache-compatible licensing, deterministic and citation-grounded where possible, MCP-friendly — is consistent across the org. Adjacent projects under active development:

- **[LegalQuants/lq-skills](https://github.com/LegalQuants/lq-skills)** — the community skill catalog (already mounted as a submodule per the section above).
- **[LegalQuants/privacyquant](https://github.com/LegalQuants/privacyquant)** — versioned statutory knowledge graph and MCP workflow layer for US state consumer privacy law (146 nodes across 20 statutes; 18 MCP tools, 16 of them deterministic). Integration path with LQ.AI is documented as [DE-264](docs/PRD.md#de-264--legalquants-ecosystem-integration-privacyquant-statutory-graph--mcp-path): near-term as PrivacyQuant-backed community skills (`skills/community/pq-*`), and long-term as a first-party MCP server inside the LQ.AI deployment once the MCP-client subsystem (PRD §8.5, M5+) lands.

The shared posture across the ecosystem: substantive legal work product is open-source, citation-grounded, attorney-attested, and inspectable — the same posture LQ.AI takes with its starter skills, applied to a wider surface of legal-AI tooling.

---

## Quick Start

**Prerequisites:** [Docker Desktop 4.x+](https://www.docker.com/products/docker-desktop) (or Docker Engine 24+ on Linux) and `git`. No other host tooling required — no Python, no Node, no language-specific runtimes. Plan for ~8 GB of free disk space and ~6 GB of RAM available to Docker.

### Step 1 — Clone and configure

```bash
git clone --recurse-submodules https://github.com/LegalQuants/lq-ai.git
cd lq-ai
cp .env.example .env
```

> `--recurse-submodules` pulls in the [LegalQuants/lq-skills](https://github.com/LegalQuants/lq-skills) community skills catalog (30+ skills authored by lawyer-builders across 17+ jurisdictions). If you forgot the flag, run `git submodule update --init --recursive` from inside the cloned repo.

Open `.env` and set the four required secrets (the file explains each one):

- `POSTGRES_PASSWORD` — any long random string
- `MINIO_ROOT_PASSWORD` — any long random string
- `LQ_AI_GATEWAY_KEY` — any long random string
- `JWT_SECRET` — any long random string

Generate all four at once, labelled and ready to paste into `.env`:

```bash
python3 -c 'import secrets; [print(f"{name}={secrets.token_urlsafe(32)}") for name in ("POSTGRES_PASSWORD","MINIO_ROOT_PASSWORD","LQ_AI_GATEWAY_KEY","JWT_SECRET")]'
```

Provider API keys (`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`) are optional at this step. The stack starts without any; inference calls return "no provider configured" until you add at least one and restart the gateway.

### Step 2 — Start the stack

```bash
docker compose up -d
```

Seven services start: postgres, redis, minio, gateway, api, ingest-worker, web. The api container runs `alembic upgrade head` automatically as the first step of its entrypoint, so a fresh deployment lands a fully-migrated schema before uvicorn accepts traffic. Wait ~60 seconds for healthchecks, then confirm:

```bash
docker compose ps   # all 7 services should show "healthy" or "running"
```

> **First-run admin password.** On the first start (and only the first start), the api container's startup logs an auto-generated admin password — a one-time secret you can use if you skip Step 3. Grep `docker compose logs api` for `First-run admin password` to retrieve it. Most operators ignore this and just run Step 3 below, which sets a known password directly.

### Step 3 — Set the admin password

```bash
docker exec -w /app lq-ai-api-1 python -m app.cli reset-admin-password \
  --email admin@lq.ai \
  --password 'LQ-AI-smoke-test-Pw1!' \
  --no-force-change
```

This sets a known password for the bootstrap admin account so you can log in immediately without the must-change-password gate. Use a stronger password for anything beyond a local evaluation.

> If `docker exec` reports the container isn't found, run `docker compose ps` to see the actual container name on your setup — some Docker Compose versions use `lq-ai_api_1` (underscores) instead of `lq-ai-api-1` (hyphens). The `docker compose exec api python -m app.cli ...` form also works on most setups if you prefer it.

### Step 4 — Log in

Navigate to `http://localhost:3000/lq-ai/login` and sign in:

- **Email:** `admin@lq.ai`
- **Password:** `LQ-AI-smoke-test-Pw1!` (or whatever you set in step 3)

Other endpoints available after the stack is up:

```
LQ.AI app:          http://localhost:3000/lq-ai
Backend API docs:   http://localhost:8000/docs   (Swagger UI)
Backend API docs:   http://localhost:8000/redoc  (ReDoc)
Inference Gateway:  http://localhost:8001/docs
```

### Step 5 — First 5 minutes

After login you land on the LQ.AI home. Three good starting points:

- Click **Learn** in the top bar to take the interactive tour — eleven playgrounds walk through the architecture, the request lifecycle, the tier system, what the model sees, where your data lives, and how to author a skill. This is the fastest orientation for both evaluators and new contributors. (`http://localhost:3000/lq-ai/learn`)
- Click **Skills** to browse the 10 built-in skills. Each is inspectable: click any skill to read the `SKILL.md` driving it.
- Click **+ New matter** to create your first project workspace and attach a document to try a skill against.

---

### Providers and air-gapped deployments

LQ.AI ships with four provider adapters: **Anthropic** (Claude), **OpenAI** (GPT models + text-embedding-3-*), **Azure OpenAI** (M2-E1 — unblocks Azure-tenant enterprise deployments via the operator's existing Azure agreement), and **Ollama** (local). Any OpenAI-compatible local endpoint (vLLM, llama.cpp wrappers, LM Studio) works through the OpenAI adapter with a custom `base_url`. Google Vertex AI and AWS Bedrock adapters are on the deferred-enhancement list (DE-034 / DE-035) and welcome community contribution — see [docs/HONEST-STATE.md](docs/HONEST-STATE.md) for the current shipped-vs-deferred catalog.

Multiple providers can run in parallel: operators declare `model_aliases` in `gateway.yaml` that resolve to specific provider+model pairs with fallback chains. A request for `smart` might primary-route to `anthropic-prod/claude-opus-4-7` and fall back to `vertex-anthropic/claude-opus-4-7@anthropic` on failure; the routing log captures which target actually handled the request. Provider keys are encrypted at rest in the gateway (Fernet AES-128-CBC + HMAC-SHA256 per `gateway/app/secrets.py`); the api/ service never sees them — defense-in-depth around the highest-value secret in the deployment.

For a **fully air-gapped deployment** (no outbound network calls), start the stack with the `local` profile to add the Ollama sidecar for local inference:

```bash
docker compose --profile local up -d
```

In this mode, inference runs entirely on the local host via Ollama. The Inference Gateway is the only egress point in the stack — verify in `gateway/app/router.py`. Provider keys live only inside the Gateway, encrypted at rest (`gateway/app/secrets.py`); the API service never sees them.

---

### Troubleshooting

**`docker compose up` fails immediately** — confirm Docker Desktop is running and has at least 6 GB RAM allocated. On macOS: Docker Desktop → Settings → Resources. Also confirm all four required `.env` variables are set (the compose file requires them and will exit with an error message naming the missing variable).

**Fewer than 7 services are healthy** — wait 60 seconds; the postgres healthcheck can take time on first boot. If services are still unhealthy after that: `docker compose logs <service-name>` to see what is failing.

**Login rejected / password not accepted** — re-run step 3 (the reset command is idempotent). Confirm you are using the login URL `http://localhost:3000/lq-ai/login`, not `http://localhost:3000`.

**Inference returns "no provider configured"** — add at least one provider key to `.env` (e.g., `ANTHROPIC_API_KEY=sk-...`), then `docker compose restart gateway`. The gateway reads provider keys from environment variables at startup.

**A host port is already in use** (`bind: address already in use`) — every host-side port the stack uses is configurable via a `*_HOST_PORT` variable in `.env` (the compose file reads them; see `docker-compose.yml`). Override the colliding port and `docker compose up -d` again. The defaults shipped in `.env.example`:

```
POSTGRES_HOST_PORT=5432    # collides with Homebrew Postgres on macOS — set to 15432 if needed
WEB_HOST_PORT=3000         # change if another web app (Next.js dev, etc.) holds :3000
API_HOST_PORT=8000         # change if a host service (Django, FastAPI) holds :8000
GATEWAY_HOST_PORT=8001     # change if another service holds :8001
REDIS_HOST_PORT=6379       # change if a host redis holds :6379
MINIO_API_HOST_PORT=9000   # change if another service holds :9000
MINIO_CONSOLE_HOST_PORT=9001  # change if Portainer/Console holds :9001
```

The most common Mac collision is `POSTGRES_HOST_PORT=5432` against a Homebrew Postgres. Either set `POSTGRES_HOST_PORT=15432` in your `.env` (the compose stack's internal traffic still uses 5432; services talk to each other unchanged — only the host-side mapping shifts), or stop the host postgres first (`brew services stop postgresql@<version>` on macOS).

**Two clones of this repo sharing data** — Docker Compose derives its project name from the parent directory's basename. Two clones at `lq-ai/` will reuse each other's named volumes (`lq-ai_pgdata` etc.) — including the database, admin user, and MinIO objects — and `docker compose down` in one will tear down the shared stack. To isolate two parallel clones, set `COMPOSE_PROJECT_NAME` in each clone's `.env` to a unique name (e.g. `COMPOSE_PROJECT_NAME=lq-ai-dev` and `COMPOSE_PROJECT_NAME=lq-ai-prod-candidate`).

---

### How to verify what this project says about itself

The trust model for a self-hosted, open-source project is that every claim terminates in code you can read. Here are the five most important verification paths:

- **E2E test suite:** `web/cypress/e2e/` — every M1 user-facing flow has a Cypress spec. Read the test to understand what the claim covers.
- **Inference Gateway:** `gateway/app/router.py` — the only egress point, the security boundary, the place where routing decisions are made and logged.
- **Audit log writer:** `api/app/audit.py` — what gets written to the `audit_log` table, and for which actions.
- **Honest catalog:** [`docs/HONEST-STATE.md`](docs/HONEST-STATE.md) — the shipped-vs-deferred table with a verification path for every row. If you find a discrepancy between this document and the code, the code is canonical.
- **Interactive architecture tour:** Navigate to `http://localhost:3000/lq-ai/learn` after logging in. The eleven playgrounds each point at the relevant source files for that topic.

---

### First steps after login

**The Learn page is the guided tour.** New users and procurement evaluators start at `http://localhost:3000/lq-ai/learn`. Eleven interactive playgrounds walk through the architecture, the full request lifecycle, the five-tier inference model, what the model actually sees (and what it doesn't), where data lives, and how to author your own skill. Each playground links to the relevant source file.

**The honest catalog.** [`docs/HONEST-STATE.md`](docs/HONEST-STATE.md) names what is shipped, what is deferred, and how to verify each. We publish this because the verification path for an open-source product terminates in code, not in claims. If anything in this README is inconsistent with what the code does, please [open an issue](https://github.com/LegalQuants/lq-ai/issues) — the code is canonical.

**Want to contribute?** [`docs/ROADMAP.md`](docs/ROADMAP.md) is the live, ordered punch list of work that has not yet shipped — distilled from PRD §8/§9, HONEST-STATE, and the active milestone plans into one prioritized contributor view, labelled by complexity (🟢/🟡/🔴), effort (S/M/L), and contributor profile (engineer / attorney / security / DevOps). For the curated short-cycle subset where the foundation is already in source and the gap is written down in advance, see [`docs/contribute/EASIEST-CONTRIBUTIONS.md`](docs/contribute/EASIEST-CONTRIBUTIONS.md) — currently seven items, ranging from "a practicing attorney with no engineering background can pick this up" to "a security architect familiar with OWASP can pick this up." Each mini-PRD names the acceptance criteria, the contributor profile, and the files to start in.

---

## Architecture

LQ.AI is a fork of [OpenWebUI](https://github.com/open-webui/open-webui) for the chat UI, plus a FastAPI backend, a custom-built Inference Gateway (~3,000 lines of Python that we own end-to-end for security reasons), [LangGraph](https://github.com/langchain-ai/langgraph) for stateful agent workflows, [Docling](https://github.com/DS4SD/docling) + [PyMuPDF](https://github.com/pymupdf/PyMuPDF) for document parsing with character-level offsets, and PostgreSQL with [pgvector](https://github.com/pgvector/pgvector) for unified storage of application data, vectors, and full-text indexes. Optional [Langfuse](https://github.com/langfuse/langfuse) for LLM-specific observability; OpenTelemetry throughout.

```
┌──────────────────────────────────────────────────────────────────────┐
│                         CLIENT SURFACES                              │
│   Web App (OpenWebUI fork)    │    Word Add-In (Office.js)           │
└──────────────────┬─────────────┴────────────────┬────────────────────┘
                   │                              │
                   │  OpenAPI 3.1 over HTTPS      │
                   ▼                              ▼
┌──────────────────────────────────────────────────────────────────────┐
│                  LQ.AI Backend (FastAPI)                        │
│   Authn/Authz │ Audit Log │ RBAC │ Projects │ Org Profile │ ...      │
└──────┬───────────────┬─────────────┬────────────┬────────────────────┘
       ▼               ▼             ▼            ▼
┌─────────────┐ ┌─────────────┐ ┌───────────┐ ┌────────────┐
│ Inference   │ │   Skill     │ │  Document │ │ Knowledge  │
│  Gateway    │ │  Service    │ │  Pipeline │ │  Service   │
│ (multi-     │ │  (skills,   │ │ (Docling+ │ │  (pgvector │
│  provider,  │ │  Org Profile│ │  PyMuPDF, │ │  + FTS)    │
│  tier-aware,│ │  singleton) │ │  Citation │ │            │
│  anonym.    │ │             │ │  Engine)  │ │            │
│  middleware)│ │             │ │           │ │            │
└──────┬──────┘ └──────┬──────┘ └─────┬─────┘ └────┬───────┘
       │               │              │            │
       └───────────────┴──────────────┴────────────┘
                              │
       ┌──────────────────────┼─────────────────────┐
       ▼                      ▼                     ▼
┌──────────────┐      ┌──────────────┐      ┌──────────────┐
│ PostgreSQL   │      │    Redis     │      │   MinIO /    │
│ + pgvector   │      │  (sessions,  │      │   S3-compat  │
│              │      │   queues)    │      │   (files)    │
└──────────────┘      └──────────────┘      └──────────────┘

LLM PROVIDERS (any combination, configured by operator):
  Cloud:  Anthropic │ OpenAI │ Google Vertex │ Cohere │ Azure │ Bedrock
  Local:  Ollama │ vLLM │ llama.cpp │ any OpenAI-compatible endpoint
```

Two deployment modes, five inference tiers:

- **Mode 1 — Self-hosted with cloud LLM keys.** Inference happens at the configured cloud provider; the rest of the system stays in your environment. Spans Tiers 2–5 depending on which provider/account you use.
- **Mode 2 — Self-hosted with local inference.** Inference runs locally via Ollama, vLLM, llama.cpp, or any OpenAI-compatible local endpoint. Air-gap-capable. Tier 1 by definition.

For more, see [PRD §1.5 Deployment Modes and the Inference Choice Spectrum](docs/PRD.md#15-deployment-modes-and-the-inference-choice-spectrum), [§2 Architecture](docs/PRD.md#2-architecture), and [§4 The LQ.AI Inference Gateway](docs/PRD.md#4-the-lq-ai-inference-gateway).

---

## Security

LQ.AI ships with SLSA Level 3 build provenance, sigstore-signed
container images, and a Software Bill of Materials (SBOM) with every
release. See [`docs/security/`](docs/security/) for the threat model,
cryptography reference, audit-logging policy, and dependency-management
posture. Verify a release: [`docs/security/releases/README.md`](docs/security/releases/README.md).

Reporting a vulnerability: see [`SECURITY.md`](SECURITY.md).

### Security and procurement

LQ.AI's security posture is structurally different from closed-source commercial alternatives. Three principles:

- **The operator chooses the deployment's posture.** LQ.AI does not run a SaaS that holds your data on our infrastructure; you run it on yours. The most consequential security decisions — where the deployment lives, what inference provider it routes to, how the audit log is retained, who has access — are yours, and the application makes the implications of each decision explicit.
- **The Inference Choice Spectrum is the central security trade-off.** Inference is where customer data leaves the deployment, if it does. The five-tier spectrum maps the choice across local-only inference (Tier 1), customer-hosted cloud inference (Tier 2), enterprise managed inference with ZDR / no-training commitments (Tier 3), standard cloud API (Tier 4), and consumer or free tier (Tier 5). Tier 3 is recommended for most pragmatic enterprise deployments. Tier 1 is recommended for the most sensitive privileged work.
- **Transparency replaces opacity.** Every release ships with an SBOM (Software Bill of Materials), signed container images (Sigstore/cosign), SLSA-3 build provenance attestations, a published threat model, and alignment documentation for SOC 2, ISO 27001, ISO 42001, GDPR, HIPAA, and FedRAMP — mapping our design choices to each framework's controls. Where LQ.AI does not yet match a specific commercial competitor's control, it is named on the public deferred-enhancements list with a roadmap.

For procurement reviews, see:

- [PRD §1.8 Security Posture](docs/PRD.md#18-security-posture) — the full security philosophy and tier model.
- [PRD Appendix E — Pre-Empted Procurement Objections](docs/PRD.md#appendix-e--pre-empted-procurement-objections) — 17 common procurement-team objections with direct responses.
- [docs/compliance/](docs/compliance/) — Compliance Alignment Pack (SOC 2, ISO 27001, ISO 42001, GDPR, HIPAA, FedRAMP).
- [docs/security/](docs/security/) — SBOM, signed-release verification, build provenance, threat model, dependency security.

---

## Accessibility

LQ.AI is built to be **usable by every attorney on a team — including those who rely on assistive technology, keyboard navigation, or low-vision modes**. Most legal-tech products treat accessibility as a compliance afterthought; we treat it as a quality bar that ships from M1.

Concretely, this means:

- **WCAG 2.1 AA as the design target** for every shipped surface — color contrast, focus indication, keyboard reachability, semantic structure.
- **Semantic HTML + ARIA patterns by default** — every tab, dialog, button, and form control uses the correct role, label, and state attributes (the top-tab nav implements the WAI-ARIA tablist pattern with roving arrow-key focus; modals use `role="dialog"` + `aria-modal="true"` + escape-to-close).
- **Keyboard parity with mouse** for every power feature — Enhance Prompt (`⌘E`), Skill Creator, knowledge-base attach, and the launcher all reachable without a pointing device.
- **Tested both ways** — automated `axe-cli` scans across primary surfaces (target: 0 critical/serious findings), plus Cypress E2E coverage of the chrome's keyboard and screen-reader-relevant assertions, plus a manual keyboard pass before each release.
- **Theming respects user-agent preferences** — the Practice palette ships with light-mode defaults; downstream forks and operator deployments can override the semantic CSS variables (see [§10 of the M1 frontend design](docs/superpowers/specs/2026-05-10-m1-frontend-design.md#10-theming-customization-and-developer-extensibility-open-source-posture)) to match their own contrast and color-blindness needs.

Accessibility findings are treated as defects, not nice-to-haves. If you find one, [open an issue](https://github.com/LegalQuants/lq-ai/issues) — we'll prioritize it alongside functional bugs.

---

## Project status

**M1 and M2 shipped; M3 next.** The PRD is at v0.2; ten starter skills are authored and shipping; the Citation Engine's four-stage verification cascade is operational (exact → tolerant → paraphrase judge → ensemble); the Anonymization Layer is wired end-to-end with custom legal recognizers, streaming-aware rehydration, privileged-project carve-out, and a retrieval-context skip for direct citation grounding; the Azure OpenAI adapter rounds out the M2 provider set. Active work toward M3.

**Roadmap:**

| Milestone | Theme | Status |
|---|---|---|
| **M1 — Foundation** | Working self-hostable release with 10 starter skills, Projects, Organization Profile, Inference Tier Awareness, hybrid retrieval, Compliance Alignment Pack, Code & Supply-Chain Transparency, MFA option, per-user export/delete | ✓ **Shipped** |
| **M2 — Citation Engine and Anonymization** | Four-stage Citation Engine (exact / tolerant / paraphrase judge / ensemble) with character-level fidelity, audit-pinned privacy envelope on ensemble runs; Anonymization Layer in the Gateway with custom legal recognizers + streaming rehydration + privileged-project skip + retrieval-context skip; Azure OpenAI provider adapter | ✓ **Shipped** |
| **M3 — Playbooks, Word Add-In, Tabular Review, Slack/Teams** | Codified legal positions for automated contract review; Microsoft Office.js add-in (run skills, get redlines as Word tracked changes, get comments as Word comments); structured grid output across N documents with citation-grounded cells; Slack/Teams `/lq` slash command for light intake | **Next** (~8 weeks) |
| M4 — Autonomous Layer and Contract Repository | Background agents, watches, scheduled tasks; relationship graph over contract sets (amendments, restatements, master/sub) | After M3 (~8 weeks) |
| M5–M7 — Forward-Looking Workflow Intelligence | Community-driven; not committed. MCP-client subsystem operationalized; Signal Aggregation Service; Today view with prioritization; agent execution framework with human-in-the-loop guardrails. | TBD |

For the full ordered punch list of unshipped work — across the active milestone, PRD-committed deferrals, contributor-ready mini-PRDs, engineering discipline, compliance, and forward-looking M5+ — see **[`docs/ROADMAP.md`](docs/ROADMAP.md)**. The underlying sources of truth are [PRD §8 Roadmap](docs/PRD.md#8-roadmap) and [§9 Deferred Enhancements](docs/PRD.md#9-deferred-enhancements-and-identified-future-work); the roadmap doc threads ~150 entries into one prioritized view.

---

## Contributing

Substantive contributions are welcome and credited. **Skills, playbooks, jurisdictional adaptations, and verification heuristics contributed by practicing lawyers carry the same weight in the project as code contributed by engineers.** Both are work product. Both deserve attribution.

Two contribution paths, with separate contribution guides:

- **Code, infrastructure, deployment recipes, documentation:** see [`CONTRIBUTING.md`](CONTRIBUTING.md). DCO sign-off required (no CLA), code style enforced by `ruff` + `mypy` (Python) and Prettier + ESLint (JS), pytest coverage target 80%.
- **Skills (the canonical artifact of value in this project):** see [`skills/CONTRIBUTING.md`](skills/CONTRIBUTING.md). Skills containing legal substance require attestation that the substantive content is accurate to the contributor's knowledge and review by at least one practicing attorney plus one engineer. The skill-authoring guide ([`docs/skill-authoring-guide.md`](docs/skill-authoring-guide.md)) documents the patterns established by the M1 starter skills — perspective branching, severity rubrics, optional-input design, output-format conventions.

For the full picture of what's open, start with [`docs/ROADMAP.md`](docs/ROADMAP.md) — the live, ordered punch list across active milestone work, PRD-committed deferrals, mini-PRDs, engineering discipline, compliance, and forward-looking M5+, each entry labelled by complexity and contributor profile. For the curated short-cycle subset where the foundation is already in source and the scope is written down in advance, see [`docs/contribute/EASIEST-CONTRIBUTIONS.md`](docs/contribute/EASIEST-CONTRIBUTIONS.md) — each entry has a mini-PRD in [`docs/contribute/mini-prds/`](docs/contribute/mini-prds/) covering contributor profile, what ships, acceptance criteria, and where to start.

A few things that are easy and meaningful for first contributions:

- **Author a new starter skill** — pick one from [PRD DE-001 candidates](docs/PRD.md#de-001--additional-starter-skills-beyond-the-m1-set) (Settlement Agreement Review, Employment Offer Letter Review, Open Source License Compatibility Checker, etc.).
- **Add a regulatory regime to DPA Checklist Review** — Brazil LGPD, China PIPL, Singapore PDPA, India DPDP Act ([PRD DE-002](docs/PRD.md#de-002--additional-regimes-for-dpa-checklist-review)).
- **Translate a starter skill** — non-English jurisdictional adaptations.
- **File or fix a Compliance Alignment Pack control mapping** in `docs/compliance/`.
- **Write a deployment recipe** for your environment (Kubernetes flavor, reverse proxy, OAuth IdP integration).

The full backlog is in [PRD §9 Deferred Enhancements](docs/PRD.md#9-deferred-enhancements-and-identified-future-work) — bounded enhancements that have been deliberately scoped out of the v1 release and where the architectural slot exists. Pick one and propose a PR.

---

## License

[Apache License 2.0](LICENSE) for the LQ.AI codebase. The patent-grant clause is important given LegalQuants' broader ecosystem; the explicit trademark protection is enterprise-friendly; the license is compatible with most other OSS licenses for ecosystem integration.

The OpenWebUI fork (the `web` component) inherits OpenWebUI's license. We follow OpenWebUI's branding requirements and document the relationship clearly.

PyMuPDF (AGPL-3.0) is used server-side only and not redistributed as a library; the AGPL boundary is the HTTP API. Documented in [PRD Appendix B](docs/PRD.md#appendix-b--license-summary-matrix) and the [PyMuPDF AGPL boundary risk](docs/PRD.md#appendix-c--known-risks).

---

## Governance

**Initial model: BDFL.** Kevin Keller is the initial maintainer. LegalQuants stewards the project: owns the GitHub org, controls the trademark, employs the maintainer.

The project's commitment to community contribution: *"LQ.AI welcomes contributions from any lawyer, legal-ops practitioner, or engineer who wants to advance open legal AI."*

Path to broader governance is documented but not implemented in v1: as the project matures, transition to a maintainer team and formal governance (CNCF or Apache Software Foundation models). See [PRD §7.4 Governance](docs/PRD.md#74-governance).

**No "open core" gating.** Features useful to legal teams are in the open-source release. We will not move features behind a paid offering as the project matures. (LegalQuants may build commercial *services* — hosted deployments, custom skill authoring, training, support — but the software itself stays whole. See [PRD §7.1 Project Philosophy](docs/PRD.md#71-project-philosophy).)

---

## Project channels

- **GitHub Issues** for bugs and feature requests.
- **GitHub Discussions** for community Q&A.
- **Discord** (LegalQuants-hosted) for synchronous community.
- **Blog** at [legalquants.com/blog](https://legalquants.com/blog) for releases and roadmap updates.

For security disclosures, see [`SECURITY.md`](SECURITY.md). The disclosure process includes safe-harbor language for good-faith security researchers, response-time commitments (acknowledge within 72h, fix critical issues within 30d), and credit attribution for reporters.

---

## Documentation

- [Product Requirements Document](docs/PRD.md) — the canonical specification (v0.2).
- [`docs/HONEST-STATE.md`](docs/HONEST-STATE.md) — shipped-vs-deferred catalog with verification paths for every claim.
- [`docs/observability.md`](docs/observability.md) — OpenTelemetry traces/metrics, deployment recipes, operator guide.
- [`docs/contribute/EASIEST-CONTRIBUTIONS.md`](docs/contribute/EASIEST-CONTRIBUTIONS.md) — curated short-cycle contributions with mini-PRDs.
- [`docs/skill-authoring-guide.md`](docs/skill-authoring-guide.md) — how to write a high-quality skill.
- [`docs/playbook-authoring-guide.md`](docs/playbook-authoring-guide.md) — how to write a Playbook.
- [`docs/deployment-cookbook.md`](docs/deployment-cookbook.md) — recipes for production deployments.
- [`docs/compliance/`](docs/compliance/) — Compliance Alignment Pack.
- [`docs/security/`](docs/security/) — security artifacts (SBOM, threat model, supply-chain transparency).
- [`docs/procurement/`](docs/procurement/) — procurement-readiness templates (SIG Lite, CAIQ).

---

## Acknowledgments

LQ.AI builds on substantial open-source work. The most consequential dependencies:

- [OpenWebUI](https://github.com/open-webui/open-webui) — chat UI shell.
- [LangGraph](https://github.com/langchain-ai/langgraph) — agent runtime.
- [Docling](https://github.com/DS4SD/docling) and [PyMuPDF](https://github.com/pymupdf/PyMuPDF) — document parsing.
- [pgvector](https://github.com/pgvector/pgvector) — vector storage in PostgreSQL.
- [Anthropic Claude Skills](https://github.com/anthropics/skills) — the agentskills.io format the project adopts as its skill substrate.
- [OpenTelemetry](https://opentelemetry.io/) — observability.
- [Langfuse](https://github.com/langfuse/langfuse) — LLM-specific observability.

Each is acknowledged in the [License Summary Matrix](docs/PRD.md#appendix-b--license-summary-matrix). Contributions from these ecosystems are how LQ.AI exists at all.

---

*LQ.AI is authored by Kevin Keller and contributed to LegalQuants. Comments, corrections, and contributions welcomed via GitHub.*
