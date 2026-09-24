# Run the services without the website

You can run the API, gateway and storage services without starting the website. The API serves the same requests the website uses — the website is a client of this surface, not a different code path. If you came here expecting an API reference, a client-library guide, or a cookbook, there isn't one; see [What this page does not do](#what-this-page-does-not-do) below.

## Choose the services

```bash
docker compose up -d postgres redis rustfs gateway api
```

This starts those services and their dependencies (`rustfs` is the bundled object store, RustFS — see [ADR 0036](../adr/0036-bundled-object-store-rustfs.md); its `rustfs-init` dependency comes up automatically). There's no dedicated headless Compose profile — you opt in service-by-service by naming exactly the containers you want, and nothing in `docker-compose.yml`'s dependency graph pulls in `web`, so it stays off unless you add it. Add `ingest-worker` for document processing and `arq-worker` for longer background jobs (tabular review, easy-playbook generation) — they're separate containers regardless of whether the website runs:

```bash
docker compose up -d ingest-worker arq-worker
```

The `api` container is the sole schema migrator and serves its OpenAPI documentation at `/docs`; the `gateway` container has its own documentation at a separate port. Authentication, chat, skills, projects, playbooks, and tabular review are all reachable over HTTP this way.

As of the checked commit that surface is **182 operations**, generated straight from the running FastAPI app rather than hand-maintained (`docs/api/backend-openapi.generated.yaml`; a CI check, `api/tests/test_openapi_export.py`, fails the build if the committed export and the live app disagree).

## First-run access

The API creates the first admin account and records its password in the logs. If an admin already exists, it does not create another. The backend email setting is `FIRST_RUN_ADMIN_EMAIL`; Compose must pass it to the API before the account is created — the shipped `docker-compose.yml` does not forward it, so add it to the `api` service's `environment:` block (for example in a `docker-compose.override.yml`) before the first `docker compose up` if you need a non-default address. See [Quickstart, Step 4](../quickstart.md#4-sign-in) for the same setting from the web-sign-in side.

## If you build another client

Its OpenAPI docs, noted above, are the closest thing to a reference. Check the project's current support policy before depending on it from your own application — this page does not establish a promise of compatibility across releases.

**Acknowledged, not supported.** That CI check protects the project's *own* clients — the web shell, the desktop launcher, the Word add-in, the chat-platform bridges. It is not a versioned, public compatibility contract. A patch release's "safe to take blind" promise, and a minor release's "read the notes first" promise, are both about *those* clients — [release versioning](../adr/0025-release-versioning-and-pipeline-ordering.md) never extended either promise to a client the project doesn't build and can't test against.

Bug reports against this HTTP surface from a client that isn't one of the project's own are triaged as unsupported. That doesn't mean closed on sight — a PR with a test is welcome and reviewed on its merits — but there is no promise the endpoint you depend on keeps its shape, its status codes, or its existence across a release.

This position comes from a draft ADR (**ADR 0031**, opened for committee comment as **PR #564**, status **Proposed** as of the checked commit — not yet merged into this repository, so there is no `docs/adr/0031-*.md` file here to link, and that is still true after the latest merge from `main`). The draft records the underlying question as genuinely contested: a project-member survey split **4** votes for acknowledge-but-don't-support, **2** for a supported "headless edition," **2** for "ship it and build on it," and **1** for treating this as a fork's job — the draft's own words are that this is "the least settled of the key decisions," not a landslide. This page follows the position that held as the survey default; if the committee's ratification changes it, this page is stale until it's rewritten to match — the ADR itself, once merged, is the tie-breaker on any disagreement.

The draft names two triggers that reopen the question: a slim, lite-mode image shipping (a 12 GB image mostly spent on document-processing models isn't something anyone deploys headless today), or a design partner with a demonstrated — not speculative — API-only need.

## What this page does not do

No API reference, no client-library or SDK guide, no streaming cookbook, no "gateway as a drop-in" page. If you're building something that depends on this surface staying stable, the honest read is that nothing in this repository promises it will, today.
