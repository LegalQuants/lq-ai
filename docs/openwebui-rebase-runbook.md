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
5. **A six-conflict merge is not a six-risk merge.** New §5.5 covers what carries no conflict marker at all: the root layout our shell nests inside (+362/−123), 15 new database migrations, 61 bumped Python packages including a JWT library swap, and four inherited upstream Cypress specs pointed at a redesigned UI. It also records the measurement that makes the rest tractable — our LQ.AI code has **zero** imports into upstream's tree.

---

## At a glance

The whole procedure, in order. Each step links to the section that explains it — read that section before running the step; this list is a map, not a substitute.

| # | Step | Section |
| --- | --- | --- |
| 1 | Add the `upstream` remote, fetch tags, confirm the target is still latest stable | [§0](#0-before-you-start) |
| 2 | Park the conflicting PRs — post the comments *before* branching | [§1](#1-park-the-four-conflicting-prs--do-this-first) |
| 3 | `git checkout -b vendor/openwebui-upstream` off current `main` | [§2](#2-create-the-vendor-branch) |
| 4 | Build the two synthetic `web/`-prefixed trees, graft, merge | [§3](#3-bring-upstream-in) |
| 5 | Confirm nothing staged outside `web/` | [§3](#3-bring-upstream-in) |
| 6 | Resolve the conflicts — 6 for v0.11.0 | [§5](#5-the-conflict-set--six-files) |
| 7 | Re-assert the ADR 0014 deletion and strip its two importers | [§6](#6-re-assert-the-deletion) |
| 8 | Regenerate both lockfiles | [§4](#4-regenerate-dont-hand-merge) |
| 9 | Read the diffs that carry no conflict marker | [§5.5](#55-what-a-clean-merge-does-not-tell-you) |
| 10 | Build, type-check, test, migrate, walk the M1 quickstart | [§7](#7-verify-before-you-open-anything) |
| 11 | Re-verify the branding clause | [§8](#8-re-verify-the-branding-clause) |
| 12 | Open one PR, stacked commits, reviewers get the deviation diff | [§9](#9-the-pr) |
| 13 | Add the ADR 0001 Revisions entry, update version references | [§10](#10-update-adr-0001) |
| 14 | Reopen the parked PRs, close superseded Dependabot PRs, fix this file | [§11](#11-after-it-merges) |

**The two things most likely to cost you a day if skipped:** step 4's graft (the obvious `git merge` cannot work — [§3](#3-bring-upstream-in)) and step 9 (the highest-risk changes produce no conflict — [§5.5](#55-what-a-clean-merge-does-not-tell-you)).

---

## Scope — read this before §5

**The job is to be running v0.11.0. Nothing else.**

A rebase surfaces a lot of things worth doing. Almost none of them belong in this PR. The default resolution for every upstream file is **take upstream's version**, including files that got worse, files carrying dead code, and dependency choices we would not have made. Every deviation from upstream is a patch we re-resolve every quarter, which is why §0 tells you to protect the 313-file isolation.

In scope:

- Resolving the six conflicts so the tree builds and boots.
- Re-asserting our existing ADR-mandated deviations (§6) — these already exist; we are preserving them, not adding to them.
- Preserving existing LQ.AI capability that upstream's changes would otherwise remove (§5.2).
- Verifying the result (§7, §8) and disclosing what changed (§9).

Out of scope, however tempting:

- Cleaning up dead or unreachable upstream code (§5.4).
- Rewriting tests against the new UI (§5.2).
- Second-guessing upstream's dependency choices (§5.5).
- Refactoring our own code because the merge made it visible.

When one of these surfaces, **file it as a DE-XXX in PRD §9 and move on** — the project's standing rule for out-of-scope ideas ([CLAUDE.md](../CLAUDE.md)). A rebase PR that also improves things is a rebase PR that cannot be reviewed against upstream's diff.

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

### 5.2 Cypress — upstream deleted it; keep ours, drop theirs

**Upstream removed Cypress wholesale at v0.11.0.** v0.9.2 shipped 9 Cypress files; v0.11.0 ships **zero**. We have 23, of which 14 are LQ.AI-original specs under `cypress/e2e/`.

So `cypress.config.ts` and `cypress/support/e2e.ts` are **modify/delete** conflicts — ours modified, theirs deleted. There is no "upstream drift" to merge, contrary to the previous edition of this section.

**The resolution is not a judgement call.** Our 14 specs are existing, passing coverage; deleting the harness would remove working LQ.AI capability to match an upstream decision about upstream's own tests. Preserving what we have is the minimal upgrade action:

```bash
# Keep ours — our e2e suite depends on both files.
git add web/cypress.config.ts web/cypress/support/e2e.ts
```

**Flag it in the PR** — not as a question, as a fact: Cypress moves from "shared with upstream" to "ours to maintain", including its `package.json` dependencies, which upstream will no longer update for us. Whether to keep investing in Cypress long-term is a roadmap question for another day, not something this PR decides.

**Tell [#432](https://github.com/LegalQuants/lq-ai/pull/432) and [#437](https://github.com/LegalQuants/lq-ai/pull/437) before they rework.** Both build out the Cypress track, and both should know the harness is now fork-owned rather than upstream-shared. That is information they need, not a reason to reject either PR — the answer for this rebase is simply "yes, the harness stays".

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

What it *does* pull in is roughly 277 lines of upstream change including a full set of unreachable `type === 'mcp'` branches, an MCP OAuth registration path, and an "MCP support is experimental" warning block. That code is dead as merged, because nothing can set `type` to `'mcp'`.

**Leave it. Do not strip it as part of the rebase.** Taking upstream's file wholesale *is* the upgrade; removing dead code from it is a separate change that would put us further from upstream and make next quarter's merge harder — the exact trade §0 warns against. Read it, confirm the toggle is still absent, move on.

The latent risk is real but deferred, not ignored: dead MCP code in an ADR-0014-constrained component lights up if anything later sets `type` from config or a URL parameter, and it will arrive with no conflict marker. That is a **DE-XXX** for PRD §9, not merge work.

The general lesson for future quarters: **the boundary-critical file was the one git waved through.** A clean auto-merge is not evidence that an architectural constraint survived.

---

### 5.5 What a clean merge does not tell you

Everything above is about *textual* conflicts. A merge with six conflicts is not a merge with six risks. These were checked on 2026-08-24 and none of them produces a conflict marker.

**The good news first, because it is load-bearing.** Our LQ.AI code is genuinely self-contained. Across the **269** TypeScript/Svelte files under `src/lib/lq-ai/` and `src/routes/lq-ai/` there are **277 `$lib` imports and every single one points into `$lib/lq-ai/`** — zero imports of upstream's `$lib/apis`, `$lib/components`, `$lib/stores`, or anything else in their tree. Zero of our files import anything upstream deleted at v0.11.0. This is why a 1402-commit jump is survivable, and it is worth re-measuring each quarter, because it is the property that makes everything else cheap:

```bash
grep -rhoE "from '\\\$lib/[^']+'" web/src/lib/lq-ai web/src/routes/lq-ai | grep -v '\$lib/lq-ai/' | sort -u
# must print nothing
```

**Now the four things that are coupled anyway.**

**1. Our shell inherits upstream files we never touch.** `src/routes/+layout.svelte` changed **+362/−123** and `src/app.css` changed **+141**, and because we do not modify either, both are clean take-theirs with no conflict. Every `/lq-ai` route nests inside that root layout ([ADR 0009](adr/0009-web-lq-ai-shell-coexistence.md)), and our `practice.css`/`typography.css` layer onto that app CSS. A "redesigned interface" release rewriting the layout our shell hangs off is the single most likely source of post-merge visual and behavioural surprise, and git will say nothing about it. Read both diffs deliberately.

**2. The e2e suite has an upstream-DOM dependency our own specs inherit.** Our 14 LQ.AI specs assert on our own `data-testid="lq-ai-*"` hooks and are decoupled — but they log in through the shared `cy.session` helper in `cypress/support/e2e.ts`, which drives *upstream's* auth form and waits on `#chat-search`, then dismisses upstream's changelog modal by its button text. So every spec is transitively coupled to upstream's markup through one file — and that file is one of the six conflicts.

Both anchors survive v0.11.0 (`#chat-search` is still in `Sidebar/SearchInput.svelte`; `"Okay, Let's Go!"` is still in `ChangelogModal.svelte`), so **this does not fire this quarter**. Re-check both before trusting the suite:

```bash
git grep -c "chat-search" v0.11.0 -- src/
git grep -c "Okay, Let" v0.11.0 -- src/lib/components/ChangelogModal.svelte
```

Separately, four of our Cypress specs are **upstream's own, inherited at the vendor import** — `chat.cy.ts`, `documents.cy.ts`, `registration.cy.ts`, `settings.cy.ts` — plus `support/index.d.ts` and `cypress/tsconfig.json`. They select upstream markup (`#chat-input`, `.chat-user`, `#chat-share-button`, `#copy-and-share-chat-button`) and upstream deleted every one of them at v0.11.0.

**Take upstream's deletion.** They were never ours, they test upstream's UI, and that UI was redesigned — so they would fail. Deleting them is the default resolution, costs nothing, and is what "upgrade to v0.11.0" means for files upstream removed. Adopting and rewriting them against the new UI would be new test-authoring work, not an upgrade; if anyone wants that coverage back later it is a DE, not a merge task.

```bash
# The four upstream specs only. Verified: nothing of ours references them.
git rm web/cypress/e2e/chat.cy.ts web/cypress/e2e/documents.cy.ts \
       web/cypress/e2e/registration.cy.ts web/cypress/e2e/settings.cy.ts
```

**Keep `cypress/tsconfig.json` and `cypress/support/index.d.ts`, even though upstream deleted both.** They are infrastructure, not specs: `tsconfig.json` (`extends: ../tsconfig.json`) types every `.ts` file in `cypress/`, including our 14, and `index.d.ts` declares the `Chainable` custom commands that `support/e2e.ts` still defines. Deleting either breaks type-checking on our own suite. Carrying them is the same posture as `cypress.config.ts`.

Our own 14 specs under `cypress/e2e/` are unaffected — they assert on our `lq-ai-*` test ids and, verified, none of them calls the custom commands (`cy.login`, `cy.registerAdmin`, `cy.uploadTestDocument`, …); only upstream's `chat.cy.ts` and `settings.cy.ts` did.

**3. Fifteen new upstream database migrations.** The runbook has never mentioned migrations and it should. Upstream's `backend/open_webui/migrations/versions/` goes **44 → 59 revisions**: 15 new forward migrations (new tables, columns, indexes) plus 42 existing ones modified. The modifications are benign — idempotency guards and type-hint modernisation — and **the revision chain is intact**: no `down_revision` is re-pointed and `7e5b5dc7342b_init.py` is modified, not re-baselined, so this is not a history rewrite. Verified.

But it does mean the merge carries a schema change for the `web` backend, and **the project's dev-environment rules apply** ([CLAUDE.md](../CLAUDE.md)): never run host-side `alembic upgrade` against the live dev DB, and rebuild the affected services rather than migrating in place. Add a migration step to your §7 walk-through and confirm a fresh boot applies all 15 cleanly.

**4. A substantial backend dependency change, including an auth library swap.** `backend/requirements.txt` is clean take-theirs — we do not modify it — so **61 bumped packages, 7 added and 4 removed land with zero conflict**. The ones worth naming:

| Change | Note |
| --- | --- |
| `python-jose` **removed**, `joserfc` **added** | A JWT library swap in a service that authenticates users. Worth security-reviewer eyes given [ADR 0002](adr/0002-backend-owned-auth.md). |
| `cryptography` 46.0.5 → **48.0.0** | Two majors. |
| `peewee`, `peewee-migrate` **removed** | Upstream dropped the legacy ORM/migration path. |
| `uvicorn` 0.41.0 → 0.51.0, `authlib` 1.6.10 → 1.7.2, `PyJWT` 2.11.0 → 2.13.0 | Auth/serving surface. |
| added: `lxml`, `orjson`, `aiodns`, `hiredis`, `regex`, `rapidocr` | New SBOM entries. |

The npm side is by contrast almost static — 102 dependencies unchanged in number, **4 bumped**, our single added dep (`@fontsource-variable/inter`) untouched by upstream. One of those bumps is `pyodide ^0.28.2 → ^314.0.3`, which is why §4's `pyodide-lock.json` regeneration is load-bearing rather than ceremonial.

**Disclose it; do not act on it.** These are upstream's choices arriving with the version we are adopting — not ours to relitigate, and not something to pin, patch around, or partially adopt. Taking them wholesale *is* the upgrade. [CLAUDE.md](../CLAUDE.md) treats new dependencies as reviewable surface, so the PR body should list this delta plainly rather than let it ride in under "1402 upstream commits", and the JWT swap is worth naming explicitly so a security reviewer sees it. That is a disclosure obligation, satisfied by writing it down.

**5. One case-only rename, and we are on macOS.** Upstream renamed `src/lib/i18n/locales/uz-Latn-Uz/` → `uz-Latn-UZ/`. macOS is case-insensitive by default and git handles case-only renames badly there — you can end up with the old casing on disk, a phantom dirty file, or both spellings in the index, while the Linux container build is case-sensitive and sees something different. Check after checkout:

```bash
git ls-files web/src/lib/i18n/locales/ | grep -i uz-latn
# expect exactly one entry, spelled uz-Latn-UZ
```

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

> **What the 2026-08-24 dry-run did not do.** It resolved nothing and built nothing — it established the merge mechanics (§3), the conflict inventory (§5), and the non-conflicting risk surface (§5.5), then was discarded. **Every gate in this section is still entirely unexercised.** Nobody has confirmed that the merged tree installs, builds, type-checks, migrates, or boots. Treat the effort estimate for §7 as unknown, not small: three hand-resolved backend files, a regenerated lockfile, 15 new migrations and 61 bumped Python packages across a 1402-commit jump is where the real work lives, and all of it is still ahead.

**Before the build gates, two steps §5.5 added:**

```bash
# 15 new upstream migrations must apply cleanly on a fresh DB.
# NEVER host-side alembic against the live dev DB — see CLAUDE.md.
docker compose build web && docker compose up -d web
docker compose logs web | grep -i "alembic\|migration\|Running upgrade"
```

```bash
# The case-only locale rename — macOS is case-insensitive, the container is not.
git ls-files web/src/lib/i18n/locales/ | grep -i uz-latn   # expect one entry: uz-Latn-UZ
```

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

ADR 0001 **§Decision → Refresh cadence**, verbatim requirements:

- **Title:** `chore(web): rebase OpenWebUI fork to v0.11.0`
- **One PR into `main`** from `vendor/openwebui-upstream`
- **Body lists every upstream commit included** and **any of our patches that needed rework**
- **Two maintainer approvals** — "because the merge cost is real and the integration surface is large"

For the commit list, generate rather than curate:

```bash
git log --oneline v0.9.2..v0.11.0 > /tmp/upstream-commits.txt
```

### Stack the commits; do not stack the PRs

The single-PR rule is ADR 0001's, so a stack of dependent PRs would need an ADR amendment — don't open that casually. Stacking *commits* inside the one branch is fully compatible and is what keeps the PR reviewable:

```
1. chore(web): rebase OpenWebUI fork to v0.11.0     the merge, all conflicts resolved
2. chore(web): regenerate lockfiles for v0.11.0     package-lock + pyodide-lock (§4)
3. docs: record the v0.11.0 refresh in ADR 0001     Revisions entry + version references (§10)
```

The merge itself cannot be split — git will not commit a conflicted tree, so every conflict resolution lands in commit 1. Files upstream deleted (including the four abandoned Cypress specs, §5.2) drop out of that merge automatically and need no commit of their own.

Resist the temptation to make commit 1 "upstream-only" and re-apply our deviations in commit 2. It reads well but leaves an intermediate commit that crosses the [ADR 0014](adr/0014-gateway-egress-boundary-for-tool-providers.md) boundary and does not build, and the diff below gets the same review benefit without a broken tree in history.

### Give reviewers the diff that actually matters

Nobody can review 880 changed files, and the two mandated approvals are worthless if given against a diff nobody read. They do not have to: because §3 built upstream v0.11.0 as a `web/`-prefixed tree, a reviewer can see **only our deviations from pristine upstream**.

```bash
# $THEIRS_TREE is the v0.11.0 synthetic tree from §3 — for this refresh,
# 8450ab69e6b5f8a46802bc56646647679560a2e3
git diff $THEIRS_TREE HEAD -- web/
```

That output *is* "every one of our patches that needed rework" in reviewable form, and it is the same auditability ADR 0001 §Consequences already promises ("anyone can diff `web/` against the upstream tag and see exactly what we changed"). **Put this command in the PR body** and ask for the approvals against it rather than against the raw merge.

Sanity-check it before you open the PR — the file count should be close to our known deviation set (313 LQ.AI-original files plus the dozen we patch), not thousands:

```bash
git diff --stat $THEIRS_TREE HEAD -- web/ | tail -1
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
