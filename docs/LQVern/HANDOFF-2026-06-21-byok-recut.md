# Handoff — re-cut release for the BYOK launcher fix (2026-06-21)

PR **#202** (`2ae0873`, on `main`) made provider keys self-service for a fresh `.dmg`
install: a first-run wizard key field, a launcher-minted `LQ_AI_GATEWAY_MASTER_KEY`,
and an in-app **Provider keys** admin page. The code is on `main` but the **shipped
artifacts predate it** — `v0.5.0` images and the `desktop-v0.5.1` `.dmg` do not have the
fix. This handoff re-cuts both so a real stranger's install works.

## Why both tags are required

- The new **web** image carries the Provider keys page → needs a new `v*` image tag.
- The `.dmg` bundles `docker-compose.release.yml` (now forwards `LQ_AI_GATEWAY_MASTER_KEY`)
  **and** the launcher migration code (`ensureMasterKey`) → needs a new `desktop-v*` tag.
- The launcher runs images at `:latest`, so once new images publish, installs pull them —
  but the master-key forwarding lives in the **bundled compose**, so the `.dmg` must be
  rebuilt regardless.

## Versions (bumped in this branch)

| Component | Was | Now | Tag |
|---|---|---|---|
| api / gateway `__version__` | 0.5.0 | **0.5.1** | `v0.5.1` |
| desktop `package.json` | 0.5.1 | **0.5.2** | `desktop-v0.5.2` |

## Pre-reqs (already satisfied — verify)

- Apple signing secrets set on `LegalQuants/lq-ai` (`MAC_CSC_LINK`, `MAC_CSC_KEY_PASSWORD`,
  `APPLE_*`) — see `docs/BUILD-AND-RELEASE.md` §1.
- GHCR `lq-ai-{api,gateway,web,proxy}` packages set **Public** — §2.
- Tagging from `main` (contains the release Dockerfiles + workflows).

## Cut steps (images first, then desktop — per BUILD-AND-RELEASE.md §3)

```bash
# (a) Images — release.yml publishes multi-arch lq-ai-{api,gateway,web,proxy}:v0.5.1 (+ :latest)
git tag v0.5.1 && git push origin v0.5.1
#     wait for the "CI / release" run to go green before the next step.

# (b) macOS app — desktop-release.yml builds the signed + notarized .dmg → GitHub Release
git tag desktop-v0.5.2 && git push origin desktop-v0.5.2
```

Release tags go to **origin only** (CI runs there; `tucuxi` carries no release tags).
`main` itself stays mirrored on both remotes.

## Post-cut verification (the release gate — do on a clean machine/VM)

1. Download the `desktop-v0.5.2` `.dmg` from the GitHub Release; install; open.
2. First-run wizard: **paste an Anthropic/OpenAI key** → sign in → send a chat → it answers.
3. Repeat leaving the key **blank**: stack boots; chat says "no provider"; add a key on
   **admin → Provider keys** (Set key) → it hot-applies and chat answers.
4. (Existing-install path) Upgrade a pre-0.5.2 install → confirm `ensureMasterKey` backfilled
   the master key (Provider keys page works, no 400).

## Loose end

- Regenerate `docs/images/launcher-wizard.png` during the `.dmg` smoke test (it now has the
  optional key field; an `INSTALL-MAC.md` TODO marks the stale image).
- Document ingestion still needs an **OpenAI** key specifically (embedding alias) — DE-355.
