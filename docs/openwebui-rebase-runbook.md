# OpenWebUI fork rebase — runbook

> **Governing decision:** [ADR 0001](adr/0001-openwebui-fork-pin.md) — the fork pin, the quarterly refresh cadence, and the procedure this runbook implements. ADR 0001 is authoritative; where this document and the ADR disagree, the ADR wins and this file is the one that gets fixed.

`web/` is a pinned vendor fork of [OpenWebUI](https://github.com/open-webui/open-webui). ADR 0001 sets a **quarterly rebase onto the latest upstream stable tag**, or earlier if an upstream security fix affects us. This runbook is the step-by-step for performing one.

**Written for the first refresh** (v0.9.2 → v0.11.0, tracked in [#498](https://github.com/LegalQuants/lq-ai/issues/498)), but written to be reusable: the version-specific parts are marked **[v0.11.0]** and the rest is the standing procedure. Update the marked parts each quarter and leave the rest alone.

**Nobody has executed this before.** ADR 0001 has no Revisions section and there is no `chore(web): rebase OpenWebUI fork to …` commit in history. The conflict analysis in §5 is derived from comparing blob SHAs at the two tags, **not** from an attempted merge — treat it as a good map, not a guarantee. Where it turns out wrong, fix this file in the same PR.

---

## 0. Before you start

**Confidence note.** Every fact in §1–§5 below was verified against the clone at `869e0cc7` on 2026-08-15. Anything about upstream's *content* at v0.11.0 was derived from tag-to-tag blob comparison, not from a merge attempt. Re-confirm the tag is still current before you begin — ADR 0001 says "latest upstream stable tag", and if a v0.11.x patch has landed since, that is your target instead.

```bash
# The upstream remote is NOT configured by default — this is step zero.
git remote add upstream https://github.com/open-webui/open-webui.git
git fetch upstream --tags

# Confirm the target is still the latest stable.
git tag -l 'v0.11*' --sort=-version:refname | head
```

**Our fork point** is `333fe654` — `feat(web): vendor-import OpenWebUI v0.9.2 fork (ADR 0001)`.

**The delta on our side** (`333fe654..main`, restricted to `web/`), verified 2026-08-15:

| Change | Count | Rebase impact |
| --- | --- | --- |
| Added | **970** | Carry clean — our own files, 203 of them under `web/src/lib/lq-ai/`. Not in upstream's tree, nothing to merge. |
| Modified | **11** | The entire conflict surface. §5 covers each one. |
| Deleted | **1** | `web/backend/open_webui/utils/mcp/client.py` — needs re-asserting, see §6. |

That 970/11 split is ADR 0001's "isolate customizations where possible" mitigation actually working, and it is the single biggest reason a 1402-commit upstream delta is tractable at all. **Protect it:** if this rebase tempts you to modify an upstream file rather than add one of ours, that trade compounds every quarter.

**[v0.11.0]** Upstream delta: **1402 commits**, two minor bumps (0.9 → 0.10 → 0.11).

---

## 1. Park the four conflicting PRs — do this first

**Decision, 2026-08-15 (houfu): park all four, rebase clean, reopen against the new base.** The alternative — landing them first — was considered and rejected; #282 and #286 have never had CI run at all, so gating a due rebase behind them is open-ended.

Four open PRs touch files in the conflict set. A rebase landing *underneath* them turns each into a silent rework, discovered at merge time.

| PR | Author | Size | Conflict files | CI |
| --- | --- | --- | --- | --- |
| [#282](https://github.com/LegalQuants/lq-ai/pull/282) | @sgbooth | +1511/-569, 29 files | `package.json`, `package-lock.json` | **never run** |
| [#286](https://github.com/LegalQuants/lq-ai/pull/286) | @sgbooth | +1958/-585, 33 files | `package.json`, `package-lock.json` | **never run** |
| [#432](https://github.com/LegalQuants/lq-ai/pull/432) | @SaifAlYounan | +189/-4, 5 files | `cypress.config.ts`, `package.json` | green |
| [#437](https://github.com/LegalQuants/lq-ai/pull/437) | @SaifAlYounan | +961/-5, 14 files | `cypress.config.ts`, `cypress/support/e2e.ts`, `package.json`, `package-lock.json` | green |

**Be honest about what parking costs.** These are two contributors and roughly 4,600 added lines of work in flight. Parking pushes a rebase onto them that they did not create. The compensating argument — which is real, and worth stating to them — is that the rework happens **once, against a known-good base**, instead of arriving as merge conflicts in a PR they thought was finished. #432 and #437 are green and were only ever waiting on review, so those two deserve particular care.

**Park, don't close.** Leave the branches alone and the PRs open where possible; if the workflow needs them closed, say explicitly in the comment that reopening is expected and that nothing is being rejected.

Drafted comments are in `.maintainer/pr-drafts/` (maintainer-local, not in this repo). Post them before creating the vendor branch, so nobody pushes into a PR that is about to be parked.

**The other eleven web PRs need no parking.** #263, #264, #267, #280, #314, #315, #402, #416, #417, #418, #430 touch only files we added, so they carry no file-level conflict. They still need **a CI re-run after the rebase**, because the upstream code they integrate against will have moved.

---

## 2. Create the vendor branch

ADR 0001 §Consequences is specific: rebase work happens in a **`vendor/openwebui-upstream`** branch, not a feature branch off `main`.

```bash
git checkout main && git pull
git checkout -b vendor/openwebui-upstream
```

---

## 3. Bring upstream in

Merge rather than rebase, despite the ADR's word "rebase": we have 970 added files and 1402 upstream commits, and replaying our history onto theirs would ask you to resolve the same conflicts repeatedly. One merge commit gives you each conflict exactly once.

```bash
git merge v0.11.0 --no-commit --no-ff
```

Expect it to stop with conflicts. That is the normal path, not a failure — work §5 and §6, then commit once.

If the merge base looks wrong (a vendor import can arrive as a squashed commit with no shared ancestry), stop and check before forcing anything. Getting this wrong quietly produces a "clean" merge that silently drops upstream changes.

---

## 4. Regenerate, don't hand-merge

Two of the eleven are generated artifacts. Never resolve them by hand — take upstream's, then regenerate:

- `web/package-lock.json`
- `web/static/pyodide/pyodide-lock.json`

```bash
git checkout --theirs web/package-lock.json web/static/pyodide/pyodide-lock.json
# after package.json is settled in §5:
cd web && npm install    # regenerates package-lock.json
```

Regenerate `pyodide-lock.json` by whatever upstream's build does at this version — check their Dockerfile and build scripts rather than assuming last quarter's method still applies.

---

## 5. The conflict set — ten files

`.dockerignore` is the eleventh modified file and **the only clean carry** — upstream did not touch it.

> **How this table was built:** by comparing each file's blob SHA at v0.9.2 against v0.11.0. Note for whoever re-checks: `GET /compare` truncates its `files` array at 300 entries, so intersecting that list understates the conflicts — it initially suggested five.

### Substantive — real merge judgment required

**`web/backend/open_webui/main.py`** — our integration hooks into upstream's FastAPI app. Upstream's v0.11.0 is a "redesigned interface" release, so app wiring is likely to have moved. Resolve by re-applying our hooks to upstream's new structure, not by keeping our version of the file.

**`web/backend/open_webui/utils/middleware.py`** — same posture.

**`web/backend/open_webui/routers/configs.py`** — same posture.

**`web/Dockerfile`** — builds the container that serves the bundle. Take upstream's changes and re-apply ours. Cross-check against `docker-compose.yml`'s `web` service afterwards.

### Mechanical, but read them

**`web/package.json`** — upstream's newer pins arrive here for free. Re-apply our added dependencies on top. **This is also where the superseded Dependabot PRs get resolved** (see §9). Watch for our deps having been added upstream at a different version.

**`web/cypress.config.ts`** and **`web/cypress/support/e2e.ts`** — ours plus upstream drift. These are the files #432/#437 also touch; since those are parked, resolve for upstream + our current `main` only.

**`web/.gitignore`** — trivial, union the two.

---

## 6. Re-assert the deletion

We removed `web/backend/open_webui/utils/mcp/client.py` under [ADR 0014](adr/0014-gateway-egress-boundary-for-tool-providers.md) — the gateway is the sole MCP speaker. **Upstream still ships that file at v0.11.0 and has changed it**, so git raises a modify/delete conflict.

```bash
git rm web/backend/open_webui/utils/mcp/client.py
```

Then confirm nothing upstream *newly* imports it:

```bash
grep -rn "utils.mcp.client\|utils/mcp/client\|from .mcp import\|mcp.client" web/backend/ | grep -v "^web/backend/open_webui/utils/mcp/client.py"
```

If v0.11.0 added an import of this module, that is a genuine decision point, not a merge conflict — the gateway-sole-MCP-speaker boundary is ADR 0014's, and re-adding upstream's client to satisfy an import would quietly cross it. Stop and raise it.

---

## 7. Verify before you open anything

ADR 0001 §Mitigations requires **testing against the M1 quickstart end-to-end before merge**. That is the gate, not a suggestion.

```bash
cd web
npm run build          # the bundle must build
npx svelte-check       # matches the CI gate
npx vitest run         # matches the CI gate
```

Then the stack:

```bash
docker compose build web      # rebuild — see the warning below
docker compose up -d
```

**The `web` container serves a pre-built static bundle with no HMR.** A rebase that "looks broken" in the browser is very often a stale bundle. Rebuild `web` before believing any UI symptom. (`CLAUDE.md`, dev-environment rules — and never `docker compose down -v`.)

Walk the M1 quickstart end-to-end, then specifically exercise our customizations, since those are what the merge put at risk:

- the `/lq-ai` routes and the LQ.AI shell ([ADR 0009](adr/0009-web-lq-ai-shell-coexistence.md))
- delegated auth ([ADR 0002](adr/0002-backend-owned-auth.md)) — log in
- the tier badge and the Skill Inspector
- **branding** — see §8

---

## 8. Re-verify the branding clause

Not optional, and easy to forget. ADR 0001 §Risks records that OpenWebUI's **license clause 4** prohibits altering, removing, obscuring, or replacing "Open WebUI" branding — name, logo, visual/textual/symbolic identifiers — above **50 end users in any rolling 30-day period**, absent written permission or an enterprise license. Our posture is **dual-branding**: LQ.AI chrome added *alongside*, never replacing.

**[v0.11.0] is a "redesigned interface" release**, which makes this the most likely quarter for upstream's identifiers to have moved. Re-verify placement after the merge rather than assuming the old arrangement survived. If upstream moved its branding into a component our shell overrides, that is a compliance issue and it blocks the merge.

---

## 9. The PR

ADR 0001 §Consequences, verbatim requirements:

- **Title:** `chore(web): rebase OpenWebUI fork to v0.11.0`
- **One PR into `main`** from `vendor/openwebui-upstream`
- **Body lists every upstream commit included** and **every one of our patches that needed rework**
- **Two maintainer approvals** — "because the merge cost is real and the integration surface is large"

For the commit list, generate rather than curate:

```bash
git log --oneline v0.9.2..v0.11.0 > /tmp/upstream-commits.txt
```

**[v0.11.0] Close these Dependabot PRs as superseded** once the rebase lands — `web/package.json` is a conflict file and upstream's own newer pins arrive with it: [#473](https://github.com/LegalQuants/lq-ai/pull/473), [#459](https://github.com/LegalQuants/lq-ai/pull/459), [#460](https://github.com/LegalQuants/lq-ai/pull/460), [#474](https://github.com/LegalQuants/lq-ai/pull/474), [#475](https://github.com/LegalQuants/lq-ai/pull/475). (#461 is already superseded by #475.)

> **Standing note on `web/` dependencies:** they are **vendored** and move on this rebase, not through Dependabot. `.github/dependabot.yml` covers `/web` with **npm only** and by design. A stale-looking pin under `web/` is a fork-currency question — i.e. this runbook — not a missed advisory subscription.

---

## 10. Update ADR 0001

ADR 0001 closes with: *"Updating the pinned version … is an in-place edit to this document — record the new version, the date, and a one-line rationale in a 'Revisions' section at the bottom."* Superseding the ADR would need a follow-on ADR; a version bump does not.

Add, in the same PR:

```markdown
## Revisions

- **2026-XX-XX — v0.9.2 → v0.11.0.** First quarterly refresh under this ADR. Latest upstream stable at the time; 1402 upstream commits, 10 conflict files, one deletion re-asserted (ADR 0014).
```

Also update the pinned version wherever else it appears — grep for `v0.9.2` across `docs/` and `README.md` before opening the PR.

---

## 11. After it merges

1. **Reopen the four parked PRs** (§1) against the new base, and tell both contributors it is unblocked. They will need to rebase; #282 and #286 also still need CI to run for the first time.
2. **Re-run CI on the eleven non-conflicting web PRs** — #263, #264, #267, #280, #314, #315, #402, #416, #417, #418, #430. No file conflicts, but the upstream code they integrate against has moved.
3. **Close the superseded Dependabot PRs** (§9).
4. **Fix this runbook** wherever it was wrong. It has now been executed once; that is worth more than anything written in advance.
5. **Diarise the next refresh** — quarterly from the merge date.
