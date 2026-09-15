---
title: Quickstart
description: Clone to a citation-grounded skill result against a sample NDA in about 20 minutes, with recovery steps next to the step that needs them.
audience: [operator, evaluator]
status: draft
sources:
  - docs/quickstart.md
  - README.md
  - docs/HONEST-STATE.md
  - docs/PRD.md
sidebar:
  order: 4
---

LQ.AI is a self-hosted deployment: everything below runs in Docker containers on your machine. The Inference Gateway is the only component that talks to the outside world — inference requests, and, if an operator enables them, case-law and connector (MCP) tool calls (README.md; docs/HONEST-STATE.md §5.5). Tool connectors are off by default. The initial `docker compose up` also pulls container images. See [what it touches](what-it-touches.md) for the full boundary before you start.

You need Docker Desktop 4.x+ (or Docker Engine 24+) and `git`; no other host tooling — no Python, no Node (README.md "Quick Start"). You also need one provider API key, or a local Ollama setup if you want to run fully offline (docs/quickstart.md "Before you start"); the stack starts without a key, but inference returns "no provider configured" until you add one.

One scope check before you clone, since this is the last page on the path where it is cheap: v1 has no vendor-hosted option, no SAML or LDAP/AD sign-in, no litigation or e-discovery tooling, no CLM or billing integration, no intake/triage or matter-management workflow, and no native iOS/Android app (PRD §1.6). If any of those is a requirement rather than a preference, read [is LQ.AI for you?](is-it-for-you.md) first — it names the source for each one so you can check it yourself.

The walkthrough below is the same one at `docs/quickstart.md`, with a pointer to the relevant recovery step placed at each point where a first run commonly stalls; the full troubleshooting list follows at the end of the page.

<!-- include: docs/quickstart.md from="## Before you start" to="## Step 1 — Clone and run" -->

<!-- include: docs/quickstart.md from="## Step 1 — Clone and run" to="## Step 2 — First-run setup" -->

**Stuck here?** A hang on first run, a port collision (`address already in use`), or a missing admin-password log line are all covered in [Troubleshooting](#troubleshooting) below — jump there and come back.

<!-- include: docs/quickstart.md from="## Step 2 — First-run setup" to="## Step 3 — Create a Project" -->

<!-- include: docs/quickstart.md from="## Step 3 — Create a Project" to="## Step 4 — Run NDA Review against the sample document" -->

<!-- include: docs/quickstart.md from="## Step 4 — Run NDA Review against the sample document" to="## Step 5 — Walk through the output" -->

**Stuck here?** "No model configured" means no provider key is set. A verification error on the sample means checking the API logs — the sample is markdown, which the Citation Engine handles with synthetic page boundaries. On your own documents, a miss usually means the file has no extractable text; there is no OCR step (docs/quickstart.md, "Citation engine fails on the sample NDA"). Both are in [Troubleshooting](#troubleshooting).

<!-- include: docs/quickstart.md from="## Step 5 — Walk through the output" to="## Step 6 — Inspect the skill itself" -->

<!-- include: docs/quickstart.md from="## Step 6 — Inspect the skill itself" to="## Step 7 — Look at the Inference Tier badge" -->

<!-- include: docs/quickstart.md from="## Step 7 — Look at the Inference Tier badge" to="## Verify the M3 surfaces (fresh-install walkthrough)" -->

**Stuck here?** A "Tier not allowed" refusal, or wanting to run fully local instead — both are in [Troubleshooting](#troubleshooting).

The source document continues from here into an M3 verification pass (Playbooks, Tabular Review, the Word add-in) against a synthetic five-NDA corpus. That walkthrough is out of scope for a first run; this page stops at the M1 experience above.

<!-- include: docs/quickstart.md from="## Troubleshooting" -->

## Next

- [Choose your path](choose-your-path.md) — where to go once it's running
- [Skills](../skills/index.md) — the other nine starter skills
- [The trust centre](../trust/index.md) — verify the tier and audit-log claims above yourself
