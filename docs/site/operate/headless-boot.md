---
title: Headless boot
description: The stack boots and serves without the web UI. Here's what that gets you, and the one sentence about what it doesn't promise.
audience: [operator, contributor]
status: draft
sources:
  - docker-compose.yml
  - docs/api/backend-openapi.generated.yaml
  - api/tests/test_openapi_export.py
  - docs/quickstart.md
sidebar:
  order: 29
---

This is the site's one page on building against LQ.AI rather than operating it through the web shell. If you came here from anywhere else on the site expecting an API reference, a client-library guide, or a cookbook — there isn't one, and that's a deliberate scope decision, not an oversight. See [What this page does not do](#what-this-page-does-not-do) below.

## What actually boots

`postgres`, `redis`, `minio`, `gateway`, and `api` come up and serve a working HTTP surface with `web` never started — nothing in `docker-compose.yml`'s dependency graph requires it. Bring it up by naming the services you want rather than a dedicated Compose profile:

```bash
docker compose up -d postgres redis minio gateway api
```

Add `ingest-worker` and `arq-worker` if you need document ingestion or long-running background jobs (tabular review, easy-playbook generation) — they're separate containers regardless of whether `web` runs. The `api` container is the sole schema migrator and exposes its OpenAPI docs at `/docs`; the `gateway` container exposes its own at a separate port. Authentication, chat, skills, projects, playbooks, and tabular review are all reachable over HTTP exactly as the web shell reaches them — the shell is a client of this same surface, not a different code path.

As of the checked commit that surface is **182 operations**, generated straight from the running FastAPI app rather than hand-maintained (`docs/api/backend-openapi.generated.yaml`; a CI drift guard, `api/tests/test_openapi_export.py`, fails the build if the committed export and the live app disagree).

## What this does not promise

**Acknowledged, not supported.** That drift guard exists to protect the project's *own* clients — the web shell, the desktop launcher, the Word add-in, the chat-platform bridges. It is not a versioned, public compatibility contract. A patch release's "safe to take blind" promise, and a minor release's "read the notes first" promise, are both about *those* clients — [release versioning](../reference/versioning.md) never extended either promise to a client the project doesn't build and can't test against, and this page is where that gap is written down rather than left to be discovered by an upgrade that breaks something unannounced.

Bug reports against this HTTP surface from a client that isn't one of the project's own are triaged as unsupported. That doesn't mean closed on sight — a PR with a test is welcome and reviewed on its merits — but there is no promise the endpoint you depend on keeps its shape, its status codes, or its existence across a release.

This position comes from a draft ADR (**ADR 0031**, opened for committee comment as **PR #564**, status **Proposed** as of the checked commit — not yet merged into this repository, so there is no `docs/adr/0031-*.md` file here to link). The draft records the underlying question as genuinely contested: a project-member survey split **4** votes for acknowledge-but-don't-support, **2** for a supported "headless edition," **2** for "ship it and build on it," and **1** for treating this as a fork's job — the draft's own words are that this is "the least settled of the key decisions," not a landslide. This page follows the position that held as the survey default; if the committee's ratification changes it, this page is stale until it's rewritten to match — the ADR itself, once merged, is the tie-breaker on any disagreement.

The draft names two triggers that reopen the question: a slim, lite-mode image shipping (a 12 GB image mostly spent on document-processing models isn't something anyone deploys headless today), or a design partner with a demonstrated — not speculative — API-only need.

## What this page does not do

No API reference, no client-library or SDK guide, no streaming cookbook, no "gateway as a drop-in" page. If you're building something that depends on this surface staying stable, the honest read is that nothing in this repository promises it will, today.

## Next

- [Release versioning](../reference/versioning.md)
- [Recipes](recipes/index.md)
- [Architecture](architecture.md)
