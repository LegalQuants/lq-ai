# LQ.AI — Quickstart Walkthrough

> **Goal:** Take a new user from `git clone` through running their first skill against a sample document and reading the output critically — in about 20 minutes. By the end, you will have LQ.AI deployed on your machine, an Organization Profile reflecting your team, a Project for the matter at hand, and a citation-grounded NDA review you can read alongside the source document.

This is the long-form quickstart. The README has the 5-line version; this document is the elaboration with explanation of what each step does and what the output means.

If you run into trouble, the [Troubleshooting](#troubleshooting) section at the end covers the most common gotchas. If your gotcha isn't there, file a GitHub issue with the `quickstart` label and we'll add it.

---

## Before you start

You need three things:

1. **Docker Desktop** (or compatible runtime) installed and running. Docker Engine 24+ on Linux works as well. Verify with `docker info`.
2. **Either** a cloud LLM provider API key (Anthropic, OpenAI, Google Vertex, Cohere, Azure OpenAI, or AWS Bedrock — at least one), **or** a local Ollama setup if you want to run fully offline (Mode 2). For the quickstart we use Mode 1 with a cloud key because it's faster to set up; Mode 2 is the same flow with `--profile local`.
3. **About 15 minutes**. Most of that is waiting for Docker images to pull on the first run; subsequent runs are seconds.

What you don't need: an internet connection during the demo (after the initial `docker compose up`); any pre-existing legal AI experience; a working knowledge of LangGraph, OpenWebUI, or any of the other components.

---

## Step 1 — Clone and run

```bash
git clone https://github.com/legalquants/lq-ai.git
cd lq-ai
cp .env.example .env
```

Open `.env` in your editor. The relevant lines for the quickstart:

```bash
# Anthropic (recommended for quickstart — Claude is what the starter skills are calibrated to)
ANTHROPIC_API_KEY=sk-ant-...your-key-here...

# OR OpenAI
# OPENAI_API_KEY=sk-...your-key-here...

# Optional but recommended: pin to a specific model alias for reproducibility
LQ_AI_DEFAULT_MODEL=smart  # resolves to claude-opus-4-7 by default
```

Set at least one provider key. The starter skills are model-agnostic but were drafted and calibrated against Anthropic's Claude family; if you use a different provider, output will be similar in shape but may differ in calibration nuance.

Then start the stack:

```bash
docker compose up -d
```

First run pulls images (about 1.5 GB across 6 services — web, api, gateway, postgres, redis, minio). On a reasonable connection this takes 2–4 minutes. Subsequent runs reuse the images and start in seconds.

When the stack is up, you should see something like this in the API container's logs:

```
✓ LQ.AI is ready at http://localhost:3000
✓ First-run admin account: see logs for password
✓ API documentation: http://localhost:8000/docs
✓ Inference Gateway: http://localhost:8001/docs
```

The first-run admin password is printed once in the API container's logs. Find it with:

```bash
docker compose logs api | grep "First-run admin password"
```

Save the password. You'll use it momentarily.

---

## Step 2 — First-run setup

Open <http://localhost:3000/lq-ai> in your browser. The LQ.AI chat shell lives at `/lq-ai` per [ADR 0009](adr/0009-web-lq-ai-shell-coexistence.md); the upstream OpenWebUI shell at `/` is preserved untouched and is not the canonical experience for this quickstart. Sign in with email `admin@lq.ai` (the default — configurable via `LQ_AI_FIRST_RUN_ADMIN_EMAIL`) and the password from the previous step. The first time you sign in, you're prompted to set a permanent password; do so.

> **Forgot to copy the bootstrap password?** Type any password and submit. If the deployment is still in fresh-install state, the login screen surfaces an inline hint with the exact `docker compose logs` command above and a one-click copy button (M3-0.1 / DE-283). The hint hides itself automatically once you've set your permanent password.

> **Admin tip — Settings → Models.** Once signed in as an admin you'll see a **Settings** link in the top-right of the LQ.AI shell. It opens the model alias editor (D0.5) at `/lq-ai/admin/models`, where you can edit the `smart` / `fast` / `budget` / `local` / `embedding` aliases without restarting the gateway. Edits write `gateway.yaml` atomically and hot-reload the gateway in process; in-flight requests finish on the prior config and the next request picks up the new mapping. See [ADR 0010](adr/0010-gateway-config-hot-reload.md) for the full design.

You then land on the first-run setup checklist. Four steps, in order, none blocking:

### Setup item 1: Create your Organization Profile

Click **Create Organization Profile** (or **Skip and create later** if you want to come back). The profile is a markdown document at the deployment level capturing your team's voice, jurisdiction, industry, standard positions, and escalation thresholds. Skills draw on it as context; without it, every skill has to relearn the org from scratch every time, and outputs feel generic.

For the demo, the simplest version is fine. A starter Profile looks like this:

```markdown
# Northbrook Legal Department

We are the in-house legal team at Northbrook Technologies, Inc., a B2B SaaS
company headquartered in California. Our customers are mid-market and
enterprise organizations across financial services, healthcare, and
professional services.

## Voice and tone
- Direct, plain-language. We avoid legalese where common-language equivalents
  exist; we preserve technical legal terminology where precision matters.
- Conservative on enforceability questions; we surface issues for escalation
  rather than asserting outcomes.

## Standard positions
- Customer-side MSAs: 12-month-fees liability cap is acceptable; uncapped
  indemnification for data-breach scenarios is not.
- Vendor-side MSAs: we negotiate suspension rights for non-payment; we do
  not accept unlimited customer-favorable IP indemnification.
- DPAs: GDPR Article 28(3) compliance is non-negotiable; SCCs are the
  preferred international transfer mechanism.

## Escalation thresholds
- Any contract value > $500K → engage outside counsel for review.
- Any litigation hold → escalate to GC.
- Any data breach affecting > 1,000 records → escalate to GC and Privacy Officer.
```

Paste it into the editor and click **Save**. The Profile is now a singleton skill that prepends to every other skill's prompt unless explicitly disabled. You can read it (and edit it, and fork it) like any other skill — there is no hidden layer.

### Setup item 2: Configure Inference Tier policy

Click **Configure Tier Policy**. By default the deployment allows Tiers 1–4 and warns on Tier 4. For the quickstart, leave the defaults — your cloud LLM provider running under your standard commercial API terms is most likely Tier 4, and the warning surfaces transparently in the chat UI rather than blocking.

If your provider account has enterprise terms with ZDR (zero data retention), you can configure that provider as Tier 3 in the gateway YAML and the badge will reflect Tier 3 going forward. The Provider Compliance Matrix at `docs/compliance/provider-compliance-matrix.md` documents which providers support which tiers under which agreements.

### Setup item 3: Optionally enable MFA

Recommended for any deployment handling client-confidential data; skippable for the quickstart on a personal machine. If you enable, you'll set up TOTP with your authenticator app on next sign-in.

### Setup item 4: Create your first Project and try a starter skill

Click **Create First Project**. This is where the demo begins.

---

## Step 3 — Create a Project

A Project is a matter-scoped container — chats, files, skills, playbooks, and a free-form context document scoped to a single matter (a deal, a counterparty, a regulatory question). Chats inside a Project automatically inherit the Project's attachments and context.

For the quickstart, create a Project for the demo NDA:

- **Name:** `Acme Discussions`
- **Description:** `Northbrook–Acme NDA review for potential business relationship`
- **Context document:**
  ```
  We are Northbrook (the user's organization). Acme has sent us their
  standard mutual NDA. Initial business discussions have not yet started.
  Standard counterparty evaluation; no specific data-handling concerns
  flagged at this stage.
  ```
- **Privileged flag:** off for the quickstart. (For privileged matters, this flag forces minimum Inference Tier and marks every chat in the Project as privileged in the audit log. See [PRD §3.11](PRD.md#311-projects-m1) for the full mechanics.)

Click **Create Project**. You're now in the Project view, with a chat sidebar scoped to this Project on the left and the context document visible on the right.

---

## Step 4 — Run NDA Review against the sample document

The repository ships with a sample NDA at `docs/quickstart/sample-nda.md` (the same document linked from this walkthrough). It's a short, synthetic mutual NDA between Acme and Northbrook with several deliberate issues for the skill to surface — this is what the demo exercises against.

In the Project view:

1. Click **+ New Chat**. The chat opens with the Project's attachments (none yet) and context document already in the chat's context.
2. Click **+ Files** and upload `sample-nda.md` from the repository (or download it from [`docs/quickstart/sample-nda.md`](quickstart/sample-nda.md) on GitHub).
3. Click **+ Skills** and select **NDA Review**.
4. The skill exposes its inputs as form elements (this is the skill-input-form pattern from PRD §3.4 / DE-010). Fill in:
   - **Perspective:** `recipient` (Northbrook is receiving the NDA from Acme; we are the recipient party in this exchange).
   - **Deal type:** `vendor procurement` (Acme is a potential business partner; we're not in M&A diligence).
   - Other inputs: leave defaults.
5. In the chat input, type something like: *"Please review."* (Or click the **Run skill** button — the skill is already attached, so you don't need a verbose prompt. This is a chance to also try Enhance Prompt; click the lightning-bolt icon next to the chat input and watch your "Please review." get rewritten into a structured legal prompt before submission.)
6. Hit Send.

The skill runs. Streaming output appears in the chat over ~30–60 seconds depending on your model and connection.

---

## Step 5 — Walk through the output

The output is a structured markdown report. Let's walk through what you'll see and what each section means.

### Bottom line

Two-three sentences leading with the recommendation, not with analysis. For the sample NDA, expect something like:

> *"Bottom line: We recommend negotiating before executing. The 5-year survival period and the asymmetric return-or-destruction certification are material to a recipient party; the 12-month non-solicitation provision is unusual in a mutual NDA and warrants discussion. After targeted edits, this NDA is acceptable for the stated business-discussion purpose."*

The exact phrasing will vary — LLM outputs do — but the *structure* (recommendation first, two-three sentences, calibrated to recipient perspective) is what the skill is committing to.

If the output starts with "This NDA contains the following provisions..." instead of with a recommendation, that's a calibration regression — flag it as an issue. The "Bottom line opens with recommendation, not analysis" convention is documented in the skill-authoring guide and is what acceptance tests verify.

### Findings

Severity-tagged findings with citations. For the sample NDA, expect:

- **`[Material]` Survival period (Section 4)** — *"The five-year survival period is unusually long for a routine business-discussion NDA. From a recipient perspective, this extends Northbrook's confidentiality obligations well beyond the period of active discussion. Recommended: negotiate to a two- or three-year survival period from the date of disclosure."*
- **`[Material]` Asymmetric return-or-destruction certification (Section 5)** — *"In a 'mutual' NDA, only Northbrook is required to certify return or destruction; Acme has no equivalent obligation. This is asymmetric and inconsistent with the mutual framing. Recommended language is provided below."*
- **`[Material]` Non-solicitation provision (Section 6)** — *"A 12-month non-solicitation of employees with whom either Party had 'material contact' is unusual scope for a mutual NDA at the discussion stage. From the recipient perspective, this constrains hiring even before any business relationship has formed. Recommended: limit to specific employees disclosed during discussions or remove entirely."*
- **`[Minor]` Confidential Information definition breadth (Section 1)** — *"The definition includes 'any information... that, by its nature, should reasonably be understood to be confidential.' This is common but creates interpretive ambiguity at the margin. Consider adding a marking requirement for written disclosures."*

A few things to notice about the output:

**Citations are visibly verified.** Every `"<quote>" (Source: [N])` the skill emits is run through the [Citation Engine](citation-engine.md) — a 4-stage cascade (exact match → tolerant match → paraphrase judge → optional ensemble) that re-reads the cited text against the source document before rendering. The chat surface (M2-C2) shows the verification state inline:

- **Green check + green underline** — verified verbatim against the source (Stage 1 `exact_match`) or verified after minor formatting normalization for whitespace, smart quotes, or OCR confusions (Stage 2 `tolerant_match`). The model quoted the source faithfully.
- **Yellow check + yellow underline** — verified by the paraphrase judge (Stage 3 `paraphrase_judge`) or by ensemble (Stage 4 `ensemble_strict` / `ensemble_majority` when activated). The source supports the claim, possibly with caveats; hover the citation chip for the judge's confidence, partial-support framing, and the tier envelope when ensemble fired.
- **Greyed text + `[unverified]` marker** — the cascade could not match the model's quote against the source. Treat as unverified; the model may have produced a claim that doesn't follow from the cited content. The visual treatment is deliberate: scrolling the report, a reviewer should spot unverified citations without reading tooltips.

Procurement reviews and document-review work both benefit from being able to quickly distinguish citations the system stands behind from ones it does not. The 5th `system-error` state (verification-pipeline errors surfaced as their own signal rather than collapsed into "unverified") is tracked at [DE-275](PRD.md#de-275--embed-m2-citations-in-chat-message-envelope) for a future release; the M2-C2 surface ships the four states above.

Click-through-to-source-viewer (highlighting the cited span in the source document with PDF.js bbox overlay) is intentionally out of scope for M2 — the visual contract and the data plumbing are in place; the viewer surface is a follow-on for v0.3+ when the docling-side citable-chunk schema is fully wired through the UI.

**Severity tags follow the rubric.** Critical / Material / Minor — the [Skill-Authoring Guide](skill-authoring-guide.md#severity-rubric-for-review-skills) documents the calibration. None of the issues in the sample NDA rise to "Critical" because the sample is calibrated to be *plausibly real, with material issues*, not catastrophic.

**Recommended language is operationally usable.** Where the skill recommends specific replacement language, it's clean and ready to drop in with minor party-name edits. You're not starting from scratch.

**The skill defers enforceability questions.** Notice the language: "unusually long," "warrants discussion," "creates interpretive ambiguity." Not "is unenforceable" or "will not hold up in court." This is the conservative-posture convention — the skill surfaces issues for your judgment rather than asserting legal outcomes. The "What this skill does not do" section at the end of the report makes this explicit.

### What this skill does not do

Every starter skill enumerates its own limits. For NDA Review:

> *"This skill does not provide jurisdiction-specific enforceability opinions on any provision; does not address transactional structuring; does not assess employment-law-specific implications of non-solicitation provisions in jurisdictions where they may face restriction (e.g., California); and does not substitute for review by qualified legal counsel."*

This enumeration is *a feature, not a defensive disclaimer*. It tells you when to escalate to expert legal counsel rather than relying on the skill's output for the answer.

---

## Step 6 — Inspect the skill itself

Click the **NDA Review** badge in the chat header. A side panel slides in showing the skill's actual `SKILL.md` and its supporting reference files (the severity rubric, the perspective-lens reference, the report-structure reference). This is the skill the model just ran — not a stylized version, the actual prompt and reference files in the agentskills.io format.

This is the transparency principle from [PRD §1.3](PRD.md#13-transparency-as-a-founding-principle) made operational. **Every artifact that shapes the user's experience is visible work product.** If the skill's calibration disagrees with your team's practice — say, you think the 5-year survival should be flagged Critical rather than Material in a vendor procurement context — you can:

1. Click **Fork this skill** to create a copy under your scope.
2. Edit the severity rubric in `reference/severity_rubric.md` to reflect your team's calibration.
3. Save your fork; use it instead of the upstream version going forward.

This is the customer-can-disagree-with-the-vendor pattern that closed-source legal AI structurally cannot match. The skill is open source. Your fork is yours.

---

## Step 7 — Look at the Inference Tier badge

Click the **Tier** badge in the top-right corner of the chat header. A panel opens showing:

- The current routed tier (likely Tier 4 if you're using a standard cloud API key without enterprise ZDR terms).
- The provider routed to (Anthropic, OpenAI, etc.).
- What the tier implies: where the data is going, what the provider's retention policy is, whether the audit log captured this routing decision (it did — every routing decision is in the audit log).

If you want to verify against the audit log, navigate to **Admin → Audit Log** and search for your chat ID. You'll see entries for each message with `routed_inference_tier` populated. M2 added two more audit signals visible in the same view:

- **`anonymization_applied: true`** — the gateway's Anonymization Layer (M2-B3) substituted detected entities with pseudonyms before forwarding to the model provider. The audit row records that pseudonymization happened; the pseudonym table itself is held only in process memory for the request duration and never persists. If `anonymization_applied: false`, the request bypassed the middleware (typically because the request was a Citation Engine judge call with `lq_ai_purpose: 'judge_paraphrase'` or the deployment has anonymization disabled in `gateway.yaml`). See [`docs/security/anonymization.md`](security/anonymization.md) for the full mechanism and the honest validation-posture note.
- **`privilege_marked: true` + `privilege_basis: <reason>`** — the chat sat in a privileged matter (Project with `privileged: true`); the tier floor enforcement bumped routing to Tier ≥ 3 and the audit log records both the privilege state and which signal triggered it (project flag, skill frontmatter, or admin override). Pinned end-to-end by `api/tests/test_chat_citations.py::test_chat_send_privileged_project_full_audit_trail`.

If your team's matter requires a tier floor (e.g., privileged matters require Tier 1 or 2), you can:

- Set `minimum_inference_tier` on the Project — every chat in the Project then refuses to route to a weaker (higher-numbered) tier than the floor.
- Set `minimum_inference_tier` on a specific skill — the skill refuses to run if the routed tier is weaker than its declared floor.
- Configure `allowed_tiers_global` in `gateway.yaml` to disallow tiers globally.

Under PRD §1.5.2, lower tier numbers are stronger: `minimum_inference_tier: 2` requires Tier 2 or stronger (Tier 1 and Tier 2 are allowed; Tier 3–5 are refused).

The PRD's [Inference Choice Spectrum (§1.5.2)](PRD.md#15-deployment-modes-and-the-inference-choice-spectrum) and [Security Posture (§1.8)](PRD.md#18-security-posture) cover the model in detail.

---

## What you've just done

In about 20 minutes you have:

- Deployed LQ.AI on your machine, with all data in your environment.
- Created an Organization Profile that shapes every subsequent skill's output to your team's voice.
- Created a Project scoping a matter (the Acme NDA review).
- Run a citation-grounded NDA Review against a sample document.
- Read the output critically, with each finding traceable to the source clause.
- Inspected the skill that produced the output — and learned that you can fork it.
- Verified the Inference Tier the request actually routed against, and the audit log entry that captured it.

That is the full M1 experience compressed into one walkthrough. The same flow applies to the other starter skills (MSA Review — SaaS, DPA Checklist Review, Contract QA, etc.) — pick a skill, attach a document, and run.

---

## Where to go next

### Try other starter skills

The 10 starter skills are listed in the [README](README.md#starter-skills-ship-with-m1). Each has its own input schema and output style; calibration is documented in the per-skill test plan ([NDA Review test plan](skills/nda-review/test-plan.md), [MSA Review SaaS test plan](skills/msa-review-saas/test-plan.md), etc.). The most informative second skill to try, depending on your practice:

- **Contract QA** if you want to see citation-grounded Q&A against the same sample NDA.
- **MSA Review — SaaS** if you have a SaaS contract handy. (For a public sample, see SEC EDGAR — many tech-company 10-Ks include SaaS-style MSAs as exhibits.)
- **DPA Checklist Review** if you want to see regime-aware analysis.
- **Comms Improver** if you want to see audience-calibrated rewriting.
- **Skill Creator** if you want to author a new skill via conversation.

### Generate your own playbook from prior agreements (M3-A6)

LQ.AI ships with the **Easy Playbook wizard** — a 4-step flow that turns a corpus of prior contracts into a draft playbook (Playbooks tab → "Generate from prior agreements"). To exercise it without authoring your own corpus, the repo ships five synthetic mutual NDAs designed for this purpose at [`docs/quickstart/sample-ndas/`](quickstart/sample-ndas/) — same base form, intentional variants on five negotiation axes. See [`docs/quickstart/sample-ndas/README.md`](quickstart/sample-ndas/README.md) for the full variant matrix and what a good wizard run should produce.

### Source documents from your practice

The sample NDA is a synthetic demo; for real value, run the skills against documents from your actual practice (or SEC EDGAR for public-domain alternatives). The acceptance-testing framework documents what corpus a thorough evaluation needs ([acceptance-testing-framework.md](docs/acceptance-testing-framework.md#test-corpus-requirements-operator-provided)).

### SEC EDGAR for public-domain test documents

Many corporate filings include contracts as exhibits — NDAs, MSAs, employment agreements, settlement agreements, and similar. To find them:

1. Visit <https://www.sec.gov/edgar/searchedgar/companysearch>.
2. Search for a public company in your industry of interest.
3. Open a recent 10-K or 8-K filing and look at the exhibit list.
4. Exhibits 10.x are typically material contracts.

These are public documents — no anonymization required for testing — and represent real practice. Don't use them in production work without independent counsel review; they are illustrative, not operational.

### Read the PRD

The [Product Requirements Document](PRD.md) is the canonical specification of what LQ.AI is and what every capability does. It's longer than this walkthrough by an order of magnitude, but the table of contents at the top lets you jump to the sections that matter. Particularly worth reading:

- [§1.3 Transparency as a Founding Principle](PRD.md#13-transparency-as-a-founding-principle) — the project's reason for existing.
- [§1.5 Deployment Modes and the Inference Choice Spectrum](PRD.md#15-deployment-modes-and-the-inference-choice-spectrum) — the five-tier model.
- [§1.8 Security Posture](PRD.md#18-security-posture) and [Appendix E Pre-Empted Procurement Objections](PRD.md#appendix-e--pre-empted-procurement-objections) — for procurement reviewers.
- [§3.11 Projects](PRD.md#311-projects-m1) and [§3.12 Organization Profile](PRD.md#312-organization-profile-m1) — what you just used.

### Contribute back

If your team's practice diverges from a starter skill (different severity calibration, different jurisdiction-specific conventions), fork the skill and contribute the variant back. The skill contribution path is documented in [`skills/CONTRIBUTING.md`](../skills/CONTRIBUTING.md); the engineering contribution path (for code, infrastructure, deployment recipes) is in [`CONTRIBUTING.md`](CONTRIBUTING.md).

The fastest way to make LQ.AI better for your practice is to fork a skill, fix the calibration, and propose the fix back. Each accepted skill contribution helps the next user with similar practice see better output without doing the same work.

---

## Troubleshooting

### `docker compose up` hangs on first run

First-run image pulls are typically the slow step. Verify with `docker compose logs -f` — if you see images downloading, it's working. If logs are silent, check Docker Desktop is running and `docker info` succeeds.

### "First-run admin password" doesn't appear in logs

The password is printed on the API container's first start. If you missed it, reset with:

```bash
docker compose down -v   # WARNING: this destroys local data; only use on first run
docker compose up -d
docker compose logs api | grep "First-run admin password"
```

For an established deployment, the admin password is reset via `docker compose exec api python -m app.cli reset-admin-password`. The CLI prints the new password and sets `must_change_password=true` on the user, so they will be forced to set a fresh password on the next login.

### Chat returns "no model configured"

Verify your `.env` has at least one provider key set and matches the model alias in your chat. Default model alias is `smart`; verify the alias resolves to a configured provider in `gateway.yaml`.

### Citation engine fails on the sample NDA

The sample is markdown rather than PDF. The Citation Engine handles markdown with synthetic page boundaries; if you see verification errors, check the API logs. Most often this is a PaddleOCR/Mistral OCR configuration issue triggered when the pipeline tries to OCR a document that doesn't need OCR — the workaround is to upload the document with explicit `format=markdown` (the file picker should detect this, but some configurations require it explicit).

### "Tier 4 not allowed" message

You configured `allowed_tiers_global` to disallow Tier 4 in setup item 2; either re-enable Tier 4 for the quickstart or upgrade your provider configuration to Tier 3 in `gateway.yaml`.

### "I want to use Mode 2 (local Ollama) instead"

Replace `docker compose up -d` with `docker compose --profile local up -d`. The local profile starts an `ollama` container alongside the rest of the stack; pull a model into it once with `docker compose exec ollama ollama pull qwen3.5:9b` (a few GB) before the first inference call. The gateway-side wiring is automatic — `gateway.yaml.example` ships with `local-fast` (Qwen 3.5 4B) and `local-thinking` (Qwen 3.5 9B) aliases that route to the local Ollama service at `http://ollama:11434`. Operators are free to repoint either alias at any model the local Ollama can serve; change `gateway.yaml.example` accordingly and pull the corresponding tag.

To exercise the local path with `curl`:

```bash
# After the stack is up, the local-fast alias dispatches to Ollama at Tier 1.
curl -X POST http://localhost:8001/v1/chat/completions \
  -H "X-LQ-AI-Gateway-Key: ${LQ_AI_GATEWAY_KEY}" \
  -H "content-type: application/json" \
  -d '{"model": "local-fast", "messages": [{"role": "user", "content": "hello"}]}'
```

Operators running Ollama on the host (rather than in the Compose stack) set `OLLAMA_BASE_URL=http://host.docker.internal:11434` in their `.env` and skip `--profile local` when running compose. Mode 2 is the air-gap-capable mode; once images are pulled and models are downloaded, the deployment runs without internet.

The starter skills run against the local model with calibration nuance that differs from the cloud Tier 4 path — expect different (typically slightly less polished) output than Claude / GPT-4. Refer to PRD §1.5.2 for the tier semantics.

### "I see the OpenWebUI shell at `/`, not the LQ.AI shell"

That's expected: the upstream OpenWebUI fork's chat shell lives at `/` and is preserved untouched per [ADR 0009](adr/0009-web-lq-ai-shell-coexistence.md). The LQ.AI canonical experience is at `/lq-ai` — point your bookmark there. If you want `/` to redirect to `/lq-ai` (i.e., not expose the OpenWebUI shell at all), add a one-line `+page.svelte` at `web/src/routes/+page.svelte` (or `(app)/+page.svelte`) that calls `goto('/lq-ai')` on mount. This is an operator-side decision; the upstream-shell-at-`/` posture is the default so the OpenWebUI fork's other features (admin, RAG, model management) remain reachable for operators who want them.

### My issue isn't here

File a GitHub issue with the `quickstart` label. Include: your OS and Docker version, the output of `docker compose ps`, the relevant log excerpt, and what you were doing when the issue surfaced. We'll add common gotchas to this section as they surface.

---

*Quickstart maintained alongside the PRD. Updates land in the same release cadence; substantive changes warrant cross-reference updates in the README.*
