# OpenWebUI fork rebase — runbook

> **Governing decision:** [ADR 0001](adr/0001-openwebui-fork-pin.md) — the fork pin, the quarterly refresh cadence, and the procedure this runbook implements. ADR 0001 is authoritative; where this document and the ADR disagree, the ADR wins and this file is the one that gets fixed.

`web/` is a pinned vendor fork of [OpenWebUI](https://github.com/open-webui/open-webui). ADR 0001 sets a **quarterly rebase onto the latest upstream stable tag**, or earlier if an upstream security fix affects us. This runbook is the step-by-step for performing one.

**Written for the first refresh** (v0.9.2 → v0.11.0, tracked in [#498](https://github.com/LegalQuants/lq-ai/issues/498)), but written to be reusable: the version-specific parts are marked **[v0.11.0]** and the rest is the standing procedure. Update the marked parts each quarter and leave the rest alone.

**Nobody has executed this for real.** ADR 0001 has no Revisions section and there is no `chore(web): rebase OpenWebUI fork to …` commit in history.

**A merge dry-run has now been done** (2026-08-24, throwaway branch, discarded). It corrected this runbook in four material ways, all folded in below:

1. **§3's merge command does not work at all.** The fork has no shared ancestry with upstream. `git merge v0.11.0` fails with `fatal: refusing to merge unrelated histories`, and the obvious workaround is *worse* than the error. §3 now carries a procedure that was actually executed.
2. **The conflict set is 6 files, not 10** — and it is a different 6 than §5 predicted. §5 is rewritten from the real merge output.
3. **Upstream deleted Cypress entirely at v0.11.0.** Two files §5 listed as content merges are modify/delete conflicts, and this is a live decision that touches #432 and #437. See §5.2.
4. **The "970 added files" figure was misleading** — 657 of them are upstream files, not ours. See the table below.

---

## 0. Before you start

**Confidence note.** §1–§5 were verified against the clone at `9f6f51c3` on 2026-08-24, and §3–§6 additionally against a real merge dry-run at that commit. Re-confirm the tag is still current before you begin — ADR 0001 says "latest upstream stable tag", and if a v0.11.x patch has landed since, that is your target instead. **As of 2026-08-24, v0.11.0 (published 2026-07-27) is still the latest upstream stable**, so the target is unchanged.

```bash
# The upstream remote is NOT configured by default — this is step zero.
git remote add upstream https://github.com/open-webui/open-webui.git
git fetch upstream --tags

# Confirm the target is still the latest stable.
git tag -l 'v0.11*' --sort=-version:refname | head
```

**Our fork point** is `333fe654` — `feat(web): vendor-import OpenWebUI v0.9.2 fork (ADR 0001)`.

**Do not measure the delta from the fork point.** `333fe654`'s tree is *not* upstream v0.9.2: the vendor import landed 660 files short (657 of them under `src/`, mostly `src/lib/components/`), and later commits restored them. So the `333fe654..main` diff reports **970 added / 11 modified / 1 deleted**, and that "970 added" reads as 970 LQ.AI-original files when **657 of them are upstream's own files arriving late**. Measuring from the fork point overstates how much of `web/` is ours and understates the merge surface.

**Measure against the upstream tag instead.** The rebase is a three-way merge: upstream v0.9.2 (base), upstream v0.11.0 (theirs), and `main`'s `web/` subtree (ours). Classified that way, verified 2026-08-24:

| Bucket | Count | Rebase impact |
| --- | --- | --- |
| Untouched by either side | **4227** | Nothing to do. |
| Upstream changed it, we never did | **638** | Take theirs; auto-resolves. |
| New in upstream v0.11.0 | **153** | Straight adds. |
| Deleted upstream, we never touched | **78** | Straight deletes. |
| **LQ.AI-original files** | **313** | Carry clean — 203 under `src/lib/lq-ai/`, 68 under `src/routes/lq-ai/`, 24 under `static/learn/playgrounds/`. Not in upstream's tree, nothing to merge. |
| We changed it, upstream did not | **1** | `.dockerignore`. Keep ours. |
| **Both sides changed it** | **12** | The real merge surface. §5 covers each one. |

That 313-file isolation is ADR 0001's "isolate customizations where possible" mitigation actually working, and it is the single biggest reason a 1402-commit upstream delta is tractable at all. **Protect it:** if this rebase tempts you to modify an upstream file rather than add one of ours, that trade compounds every quarter.

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

**[v0.11.0] #432 and #437 need more than a parking notice.** Upstream **deleted Cypress entirely** at v0.11.0 (§5.2). Both PRs build out the Cypress track, so they are not merely rebase-blocked — they are extending a harness upstream has dropped, which makes "does the fork keep Cypress?" a question that should be answered *before* either contributor reworks anything. Nothing about this rejects either PR, and the likely answer is that we keep it. But telling them only "we're parking you for a rebase" would be an incomplete account of what changed. Settle the Cypress question, then unpark with the answer.

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

**The obvious command does not work. Do not start with it.**

```bash
git merge v0.11.0 --no-commit --no-ff
# fatal: refusing to merge unrelated histories
```

Two independent reasons, both structural:

1. **No shared ancestry.** The vendor import `333fe654` is an ordinary single-parent commit in *our* history — its parent `7bef52f8` is ours, and our root is `91990aca`. Nothing in our history descends from upstream; `git merge-base HEAD v0.11.0` returns nothing.
2. **Different path layout.** Upstream keeps `package.json`, `src/`, and `backend/` at the repo root. Ours live under `web/`. Upstream's tree and our `web/` subtree share no paths.

**Do not "fix" this with `--allow-unrelated-histories`.** It is far worse than the error it silences. Measured on the dry-run: **5020 staged additions, none under `web/`** — it dumps upstream's whole tree at *our* repo root — plus 11 conflicts in our own top-level files (`LICENSE`, `README.md`, `Makefile`, `CODE_OF_CONDUCT.md`, `.github/dependabot.yml`, `.github/workflows/release.yml`, `.gitignore`, `.dockerignore`, `.env.example`, `.gitattributes`, `.github/ISSUE_TEMPLATE/config.yml`). It would replace LQ.AI's licence and README with OpenWebUI's and add upstream's CI workflows under `.github/` — a security-sensitive path per [CODEOWNERS](../.github/CODEOWNERS) — while touching nothing under `web/`. If a merge proposes thousands of root-level additions, you ran this. Abort.

### What actually works: synthesise the base, graft it, then merge normally

Give git the merge base it lacks. Rewrite both upstream endpoints under the `web/` prefix, then graft the v0.9.2 one in as a second parent of the vendor import. After that, ordinary `git merge` does a correct three-way merge. **This whole sequence was executed on the dry-run and is what produced §5's conflict list.**

```bash
# 1. Build the two upstream endpoints as commits whose trees sit under web/.
#    A scratch index keeps this off your real one.
export GIT_INDEX_FILE=$(mktemp)

git read-tree --empty
git read-tree --prefix=web/ 'v0.9.2^{tree}'
BASE=$(git commit-tree $(git write-tree) -m 'synthetic: upstream v0.9.2 under web/')

git read-tree --empty
git read-tree --prefix=web/ 'v0.11.0^{tree}'
THEIRS=$(git commit-tree $(git write-tree) -p "$BASE" -m 'synthetic: upstream v0.11.0 under web/')

unset GIT_INDEX_FILE
echo "BASE=$BASE THEIRS=$THEIRS"   # record these; the PR body needs them
```

`$BASE` alone is not enough — `HEAD` does not descend from it either, so `git merge "$THEIRS"` would still refuse, and forcing it with `--allow-unrelated-histories` degenerates to an *empty* base and turns every co-existing file into an add/add conflict. Graft instead:

```bash
# 2. Make the vendor import descend from the synthetic base.
git replace --graft 333fe654 7bef52f8 "$BASE"

# Confirm git now sees a real merge base — this must print $BASE.
git merge-base HEAD "$THEIRS"
```

```bash
# 3. Merge. No --allow-unrelated-histories needed once the graft is in place.
git merge --no-commit --no-ff "$THEIRS"
```

Expect it to stop with the six conflicts in §5. That is the normal path, not a failure.

**Check the blast radius before you resolve anything:**

```bash
git diff --cached --name-only | grep -v '^web/' | head
# must print nothing — anything outside web/ means the prefix step went wrong
```

On the dry-run this staged **880 changes, every one of them under `web/`**.

**Preview without touching the working tree.** Useful for re-deriving the conflict list each quarter before committing to anything. Needs no graft, since the base is passed explicitly:

```bash
git merge-tree --write-tree --merge-base="$BASE" HEAD "$THEIRS"
```

It prints the merged tree SHA, the unmerged stage entries, then a readable conflict log; non-zero exit just means conflicts exist.

**Clean up the graft when you are done** — `git replace` refs are local, and leaving one in place quietly rewrites history for every later command in that clone:

```bash
git replace -d 333fe654
```

**Record the two synthetic *tree* SHAs in the PR body**, not the commit SHAs. `git commit-tree` stamps author and committer time into the commit, so `$BASE`/`$THEIRS` differ on every run and are useless to a reviewer. The trees are content-addressed and reproducible:

```bash
git rev-parse "$BASE^{tree}" "$THEIRS^{tree}"
```

A reviewer who re-runs step 1 against the same two tags must get those same two tree SHAs. That is what makes the merge base auditable.

---

## 4. Regenerate, don't hand-merge

Two of the changed files are generated artifacts. **Both auto-merge cleanly** — they are not in §5's conflict list — but a textually clean merge of a lockfile is not a correct lockfile. Take upstream's and regenerate:

```bash
git checkout --theirs web/package-lock.json web/static/pyodide/pyodide-lock.json
# after package.json is settled:
cd web && npm install    # regenerates package-lock.json
```

Regenerate `pyodide-lock.json` by whatever upstream's build does at this version — check their Dockerfile and build scripts rather than assuming last quarter's method still applies.

**`web/package.json` also auto-merges**, and that is precisely why it needs reading rather than trusting: it is where upstream's newer pins land, where our added dependencies have to survive, and where the superseded Dependabot PRs get resolved (§9). Watch for a dependency we added having been adopted upstream at a different version.

---

## 5. The conflict set — six files

**Verified by executing the §3 merge on 2026-08-24**, not inferred. The earlier edition of this runbook listed ten conflict files derived from blob-SHA comparison; the real merge produces **six**, and two of those are a different *kind* of conflict than predicted.

```
web/backend/open_webui/main.py                  CONFLICT (content)
web/backend/open_webui/routers/configs.py       CONFLICT (content)
web/backend/open_webui/utils/middleware.py      CONFLICT (content)
web/backend/open_webui/utils/mcp/client.py      CONFLICT (modify/delete)
web/cypress.config.ts                           CONFLICT (modify/delete)
web/cypress/support/e2e.ts                      CONFLICT (modify/delete)
```

### 5.1 The three content conflicts

All three are our integration hooks meeting upstream's rewiring. v0.11.0 is a "redesigned interface" release, so app wiring has moved. **Resolve by re-applying our hooks onto upstream's new structure, not by keeping our version of the file.**

- **`backend/open_webui/main.py`** — our hooks into upstream's FastAPI app.
- **`backend/open_webui/utils/middleware.py`** — same posture. Also carries an ADR 0014 import strip; see §6.
- **`backend/open_webui/routers/configs.py`** — same posture. Also carries an ADR 0014 import strip; see §6.

### 5.2 Cypress — upstream deleted it, and this is a decision, not a merge

**Upstream removed Cypress wholesale at v0.11.0.** v0.9.2 shipped 9 Cypress files; v0.11.0 ships **zero**. We have 23, of which 14 are LQ.AI-original specs under `cypress/e2e/`.

So `cypress.config.ts` and `cypress/support/e2e.ts` are **modify/delete** conflicts — ours modified, theirs deleted. There is no "upstream drift" to merge, contrary to the previous edition of this section. Git leaves our version in the tree; keeping it is a deliberate choice to carry a test harness upstream has abandoned.

```bash
# Keep ours — our e2e suite depends on both files.
git add web/cypress.config.ts web/cypress/support/e2e.ts
```

Keeping them is almost certainly right — 14 of our own specs depend on the harness, and dropping it would delete LQ.AI test coverage to match an upstream decision that has nothing to do with us. But **flag it in the PR**, because it changes what the fork now owns: Cypress moves from "shared with upstream" to "ours to maintain", including its dependencies in `package.json`, which upstream will no longer be updating for us.

**This also changes the §1 parking story for [#432](https://github.com/LegalQuants/lq-ai/pull/432) and [#437](https://github.com/LegalQuants/lq-ai/pull/437).** Both build out the Cypress track. They are not merely rebase-blocked — they are now building on a harness upstream has dropped. Neither PR is wrong, and this is not a reason to reject either, but both contributors deserve to hear it before they rework, and the "will the fork keep Cypress?" question should be settled *before* they are unparked. It is not settled by this runbook.

### 5.3 The ADR 0014 deletion

`backend/open_webui/utils/mcp/client.py` — see §6.

### 5.4 What auto-merges but still needs eyes

Six files changed on both sides yet resolve without conflict markers. Git is right about the text in each case; that is not the same as being right about the intent.

| File | Why it still needs reading |
| --- | --- |
| `src/lib/components/AddToolServerModal.svelte` | **Read this one properly.** See below. |
| `package.json` | §4 — our deps, upstream's pins, the Dependabot supersessions. |
| `package-lock.json` | §4 — regenerate, don't trust. |
| `static/pyodide/pyodide-lock.json` | §4 — regenerate, don't trust. |
| `Dockerfile` | Cross-check the result against `docker-compose.yml`'s `web` service. |
| `.gitignore` | Trivial union; skim it. |

**`AddToolServerModal.svelte` is the one to actually read.** Our fork strips the OpenAPI/MCP type toggle from this modal — the UI half of ADR 0014's "the gateway is the sole MCP speaker", the other half being the `mcp/client.py` deletion. Upstream rewrote the same file heavily at v0.11.0 (+126/−74), adding MCP OAuth 2.1 registration flows.

The merge **resolves this correctly**: the toggle stays removed, `type` cannot reach `'mcp'` from the UI, and the ADR 0014 posture holds. Verified on the dry-run — the merged file contains zero occurrences of the toggle, against one upstream.

What it *does* pull in is roughly 277 lines of upstream change including a full set of unreachable `type === 'mcp'` branches, an MCP OAuth registration path, and an "MCP support is experimental" warning block. That code is dead as merged, because nothing can set `type` to `'mcp'`. It is still worth a decision: dead MCP code sitting in an ADR-0014-constrained component is latent — any future change that sets `type` from config, a URL parameter, or a later upstream refactor lights it up, and it will arrive with no conflict marker to prompt review. Either strip it while resolving, or note explicitly in the PR that it was left in place and why.

The general lesson for future quarters: **the boundary-critical file was the one git waved through.** A clean auto-merge is not evidence that an architectural constraint survived.

---

## 6. Re-assert the deletion

We removed `web/backend/open_webui/utils/mcp/client.py` under [ADR 0014](adr/0014-gateway-egress-boundary-for-tool-providers.md) — the gateway is the sole MCP speaker. **Upstream still ships that file at v0.11.0 and has changed it**, so git raises a modify/delete conflict.

```bash
git rm web/backend/open_webui/utils/mcp/client.py
```

**The import question is already answered for v0.11.0 — the answer is "no new imports, but two existing ones".** The dry-run ran this check against the upstream tag directly:

```bash
git grep -n "utils\.mcp\.client" v0.11.0 -- backend/
# v0.11.0:backend/open_webui/routers/configs.py:17:from open_webui.utils.mcp.client import MCPClient
# v0.11.0:backend/open_webui/utils/middleware.py:99:from open_webui.utils.mcp.client import MCPClient
```

Both imports **also existed at v0.9.2** (at lines 20 and 117), and our fork already strips both — which is part of why `configs.py` and `middleware.py` are modified on our side at all. So this is the established pattern continuing, not a new decision, and the stop-and-raise at the end of this section does **not** fire for v0.11.0.

What it does mean: **the deletion is not self-contained.** `git rm`-ing the module while resolving `configs.py` and `middleware.py` from upstream's side would leave two dangling imports and a startup `ImportError`. Strip both imports as part of resolving those two conflicts, then verify against the merged tree rather than the tag:

```bash
grep -rn "utils\.mcp\.client\|utils/mcp/client" web/backend/
# must print nothing
```

**Re-run the tag-side check each quarter.** If a future release adds a *third* importer, or moves the import into a file we do not otherwise modify, that is a genuine decision point — re-adding upstream's client to satisfy an import would quietly cross ADR 0014's boundary. Stop and raise it.

Note that ADR 0014 is enforced in **two** places, not one: this module, and the MCP type toggle in `src/lib/components/AddToolServerModal.svelte` (§5.4). The second one auto-merges silently. Check both.

---

## 7. Verify before you open anything

> **What the 2026-08-24 dry-run did not do.** It resolved nothing and built nothing — it established the merge mechanics (§3) and the conflict inventory (§5) and was then discarded. **Every gate in this section is still entirely unexercised.** In particular, nobody has yet confirmed that the merged tree installs, builds, type-checks, or boots. Treat the effort estimate for §7 as unknown, not small: three hand-resolved backend files plus a regenerated lockfile across a 1402-commit jump is where the real work lives, and it is all still ahead.

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

**[v0.11.0] Close these Dependabot PRs as superseded** once the rebase lands — `web/package.json` changes in the merge and upstream's own newer pins arrive with it. **List re-checked 2026-08-24:** [#533](https://github.com/LegalQuants/lq-ai/pull/533) (the current `web-minor-patch` group, 55 updates), [#459](https://github.com/LegalQuants/lq-ai/pull/459), [#460](https://github.com/LegalQuants/lq-ai/pull/460), [#474](https://github.com/LegalQuants/lq-ai/pull/474), [#475](https://github.com/LegalQuants/lq-ai/pull/475). (#461 and #473 are already closed — #473 was superseded by #533.)

Re-check this list immediately before opening the PR rather than trusting it; the grouped `web-minor-patch` PR is replaced by a new one whenever Dependabot regroups, so the number moves.

> **Standing note on `web/` dependencies:** they are **vendored** and move on this rebase, not through Dependabot. `.github/dependabot.yml` covers `/web` with **npm only** and by design. A stale-looking pin under `web/` is a fork-currency question — i.e. this runbook — not a missed advisory subscription.

---

## 10. Update ADR 0001

ADR 0001 closes with: *"Updating the pinned version … is an in-place edit to this document — record the new version, the date, and a one-line rationale in a 'Revisions' section at the bottom."* Superseding the ADR would need a follow-on ADR; a version bump does not.

Add, in the same PR:

```markdown
## Revisions

- **2026-XX-XX — v0.9.2 → v0.11.0.** First quarterly refresh under this ADR. Latest upstream stable at the time; 1402 upstream commits, 12 files changed on both sides of which 6 conflicted, one deletion re-asserted (ADR 0014), and Cypress carried forward after upstream dropped it.
```

Also update the pinned version wherever else it appears — grep for `v0.9.2` across `docs/` and `README.md` before opening the PR.

---

## 11. After it merges

1. **Reopen the four parked PRs** (§1) against the new base, and tell both contributors it is unblocked. They will need to rebase; #282 and #286 also still need CI to run for the first time. For #432 and #437, include the Cypress answer (§5.2) — they need it to know what they are building on.
2. **Re-run CI on the eleven non-conflicting web PRs** — #263, #264, #267, #280, #314, #315, #402, #416, #417, #418, #430. No file conflicts, but the upstream code they integrate against has moved.
3. **Close the superseded Dependabot PRs** (§9).
4. **Fix this runbook** wherever it was wrong. §3–§6 were already corrected against a merge dry-run on 2026-08-24, but nothing downstream of the merge has been exercised — §7's gates especially. What the first real execution learns is worth more than anything written in advance.
5. **Diarise the next refresh** — quarterly from the merge date.
