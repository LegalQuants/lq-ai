# OpenWebUI fork rebase — runbook

> **Governing decision:** [ADR 0001](adr/0001-openwebui-fork-pin.md) — the fork pin, the quarterly refresh cadence, and the procedure this runbook implements. ADR 0001 is authoritative; where this document and the ADR disagree, the ADR wins and this file is the one that gets fixed.

`web/` is a pinned vendor fork of [OpenWebUI](https://github.com/open-webui/open-webui). ADR 0001 sets a **quarterly rebase onto the latest upstream stable tag**, or earlier if an upstream security fix affects us. This runbook is the step-by-step for performing one.

**Written for the first refresh** (v0.9.2 → v0.11.0, tracked in [#498](https://github.com/LegalQuants/lq-ai/issues/498)), but written to be reusable: the version-specific parts are marked **[v0.11.0]** and the rest is the standing procedure. Update the marked parts each quarter and leave the rest alone.

**This has now been executed end to end** (2026-08-24/25, v0.9.2 → v0.11.0): the merge, all six conflict resolutions, every gate in §7, the §8 branding check, and the ADR 0001 Revisions entry. The stack was brought up on a fresh database, all 15 new upstream migrations applied, and the LQ.AI shell, delegated login and the ADR 0014 constraint were confirmed by hand in the browser. Everything below is written from that execution rather than from inference.

**What execution changed that a dry-run could not.** Worth reading before you start, because each cost real time:

- **§5.1 was the dangerous one.** Replaying our saved `middleware.py` patch would have silently deleted upstream's new plugin-tool handling — no conflict, no error, no failing test. §5.1 now treats a fork patch as a statement of intent to re-derive, not a diff to replay.
- **§7 named commands CI does not run.** Bare `npx svelte-check` reports 8320 errors from upstream's tree and looks like catastrophe; the real gate is `npm run check:lq-ai` and it reports zero.
- **Nothing in CI builds the bundle**, and v0.11.0 needs more build heap than v0.9.2 did — caught only by walking §7 by hand, and it would otherwise have surfaced as a broken Docker image.
- **§5.2 contradicted itself**, telling you to `git rm` four files the merge had already removed.
- **§10 pointed at the wrong files.** The one version string users actually see lives in `web/src/`, which it never mentioned — while its instruction to update the version "wherever it appears" would have rewritten ADR 0009 and the M1 progress records, which are history, not stale pins.

**The earlier merge dry-run** (also 2026-08-24, throwaway branch, discarded) corrected this runbook in five material ways, all folded in below:

1. **§3's merge command does not work at all.** The fork has no shared ancestry with upstream. `git merge v0.11.0` fails with `fatal: refusing to merge unrelated histories`, and the obvious workaround is *worse* than the error. §3 now carries a procedure that was actually executed.
2. **The conflict set is 6 files, not 10** — and it is a different 6 than §5 predicted. §5 is rewritten from the real merge output.
3. **Upstream deleted Cypress entirely at v0.11.0.** Two files §5 listed as content merges are modify/delete conflicts. We keep the harness, and #432/#437 need to hear that it is now fork-owned. See §5.2.
4. **The "970 added files" figure was misleading** — 657 of them are upstream files, not ours. See the table below.
5. **A six-conflict merge is not a six-risk merge.** New §5.5 covers what carries no conflict marker at all: the root layout our shell nests inside (+362/−123), 15 new database migrations, 61 bumped Python packages including a JWT library swap, and four inherited upstream Cypress specs pointed at a redesigned UI. It also records the measurement that makes the rest tractable — our LQ.AI code has **zero** imports into upstream's tree.

---

## At a glance

The whole procedure, in order. Each step links to the section that explains it — read that section before running the step; this list is a map, not a substitute.

| # | Step | Section |
| --- | --- | --- |
| 1 | Add the `upstream` remote, fetch tags, confirm the target is still latest stable | [§0](#0-before-you-start) |
| 2 | Decide: park in-flight PRs, or rebase first and ask them to rebase | [§1](#1-decide-how-to-handle-in-flight-prs--before-you-branch) |
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
| 14 | Tell the affected PRs to rebase, close superseded Dependabot PRs, fix this file | [§11](#11-after-it-merges) |

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

## 1. Decide how to handle in-flight PRs — before you branch

Some open PRs will touch files the rebase changes. You have two options, and **which one is right depends on how close those PRs are to merging** — not on how many there are.

**Park first** if the PRs are in active review and might land during the rebase window. A rebase merging *underneath* a PR you were about to approve turns it into a silent rework, discovered at merge time.

**Rebase first, then ask them to rebase** if review has not started. The PRs sit in the queue either way, so parking buys nothing and costs a confusing interruption — a "we're parking you" notice makes a contributor think something is wrong when the honest answer is that we simply have not got to them yet.

**Decision for this refresh, 2026-08-24 (houfu): rebase first.** Review had not started on any of the four, so the silence was not costing them much, and parking would have been ceremony. This supersedes the 2026-08-15 decision to park all four, which was made before the dry-run showed how small the real overlap was.

**Accept the tradeoff knowingly:** a contributor who pushes work during the rebase window redoes a little of it. That is minor, since they have to rebase either way.

**The PRs that will need a rebase afterwards** — real overlap only, verified against the dry-run on 2026-08-24:

| PR | Author | Files the merge actually changes | Rebase difficulty |
| --- | --- | --- | --- |
| [#282](https://github.com/LegalQuants/lq-ai/pull/282) | @sgbooth | `package.json`, `package-lock.json` | lockfile regenerates — re-run `npm install` |
| [#286](https://github.com/LegalQuants/lq-ai/pull/286) | @sgbooth | `package.json`, `package-lock.json` | same |
| [#432](https://github.com/LegalQuants/lq-ai/pull/432) | @SaifAlYounan | `package.json` only | small |
| [#437](https://github.com/LegalQuants/lq-ai/pull/437) | @SaifAlYounan | `package-lock.json`, `package.json`, `.gitignore` | lockfile conflict is **certain** |

**Check the overlap yourself rather than inheriting this table.** The obvious candidates are often wrong: `cypress.config.ts` and `cypress/support/e2e.ts` look like conflicts because both sides changed them, but they resolve **keep-ours** (§5.2) and come out byte-identical — so PRs touching them are unaffected. Likewise all four PRs touch `.github/workflows/*`, which the rebase never goes near, since the merge is confined to `web/`.

The reusable rule: **a file is only a rebase hazard for a contributor if the merge actually changes it.** Files we resolve keep-ours are not hazards, however conflicted they looked.

**[v0.11.0] #432 and #437 need more than "please rebase".** Upstream **deleted Cypress entirely** at v0.11.0 (§5.2). Both build out the Cypress track, so both are extending a harness that is now fork-owned rather than upstream-shared — dependencies included. That is context they need in order to plan, not a reason to reject either PR. #437 additionally modifies `cypress/support/e2e.ts`, which §5.5 identifies as the single place our suite touches upstream's DOM; worth telling them while they are in there.

**Be honest about what the rebase costs them.** These are two contributors and roughly 4,600 added lines of work in flight. The rebase lands work on them that they did not create. Say so plainly, and be specific about which files — a contributor told "please rebase" guesses at scope; one told "your lockfile will conflict, regenerate rather than hand-merge it" does not.

Drafted comments live in `.maintainer/pr-drafts/` (maintainer-local, not in this repo).

**The other eleven web PRs need nothing but a CI re-run.** #263, #264, #267, #280, #314, #315, #402, #416, #417, #418, #430 touch only files we added, so they carry no file-level conflict — but the upstream code they integrate against has moved, so re-run CI on each.

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

**`pyodide-lock.json` regenerates itself** — `npm run build` runs `pyodide:fetch` (`scripts/prepare-pyodide.js`) before `vite build`, so there is no separate step. Note that script resolves versions live from PyPI, so the file can drift for reasons unrelated to the rebase (observed: `black` 26.3.1 → 26.5.1 on an unrelated `npm ci`). Do not read a rebase signal into a diff there.

**Expect the regeneration to change nothing, and treat that as a pass.** On the v0.11.0 refresh, `npm install` produced a `package-lock.json` byte-identical to the auto-merged one, and `pyodide-lock.json` came out identical to upstream's. That does not mean the step was skippable — it is how you learn the auto-merge was correct. Verify the result rather than the diff:

```bash
grep -m1 '"version"'                 web/package.json   # upstream's new version
grep -m1 '"@fontsource-variable/inter"' web/package.json   # our added dep survived
grep -A1 '"node_modules/pyodide"'    web/package-lock.json  # upstream's bump resolved
```

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

All three are ADR 0014 deviations meeting upstream's rewiring, and v0.11.0 is a "redesigned interface" release, so app wiring has moved. **Resolve by re-applying our intent onto upstream's new structure — never by keeping our version of the file, and never by replaying our old patch.**

They are *not* the same kind of change, and treating them alike is how you break something. Establish what our deviation actually is before touching the conflict:

```bash
# The only reliable starting point: our delta from the OLD upstream tag.
git show <pre-merge-main>:web/backend/open_webui/main.py > /tmp/ours.py
git show v0.9.2:backend/open_webui/main.py > /tmp/base.py
diff /tmp/base.py /tmp/ours.py
```

Then take upstream's file wholesale and re-apply that delta onto it:

```bash
git checkout --theirs web/backend/open_webui/<file>
# ...re-apply our deviation...
python3 -m py_compile web/backend/open_webui/<file>
```

**`main.py` — a pure deletion.** Our entire delta is a 21-line MCP cleanup block in the streaming `finally:` handler. At v0.11.0 upstream rewrote that block *and* added a task-deregistration / `chat:active` block immediately after it. Drop the MCP half, keep upstream's new task deregistration — it is unrelated to MCP and per §Scope we take upstream's.

**`middleware.py` — a structural re-application, and the trap in this whole procedure.** Our v0.9.2 delta deleted the entire `for tool_id in tool_ids:` loop, because at v0.9.2 that loop existed *solely* to handle `server:mcp:`. **At v0.11.0 upstream gave the same loop a second, non-MCP job:**

```python
for tool_id in tool_ids:
    if tool_id.startswith('server:mcp:'):
        ...                              # ours to remove
    elif ENABLE_PLUGINS:
        db_tool_ids.append(tool_id)      # upstream's, and load-bearing
```

and `get_tools()` now takes `db_tool_ids` rather than `tool_ids`. **Replaying our old deletion would silently remove plugin-tool handling** — no conflict, no error, no test failure, just a feature quietly gone. Keep the loop, delete only the MCP branch, and **promote the `elif` to an `if`**. Also remove: the `MCPClient` import, the `mcp_clients`/`mcp_tools_dict` init, the `tools_dict` merge, `metadata['mcp_clients']`, and upstream's new `connect_mcp_server()` helper, which did not exist at v0.9.2 and is pure MCP.

**`configs.py` — a replacement, not a deletion.** Our fork answers the tool-server verify endpoint's mcp branch with an explicit refusal, because MCP servers are operator-configured via the gateway:

```python
if form_data.type == 'mcp':
    raise HTTPException(
        status_code=400,
        detail='MCP tool servers are configured by the operator via the gateway, not added here.',
    )
```

Upstream's OAuth 2.1 discovery and `MCPClient` probe are dropped, the `else:  # openapi` branch de-indented out of the conditional, and three imports removed (`MCPClient`, `get_discovery_urls`, `OAuthMetadata`). Note this file has a *second* `== 'mcp'` block, in the connection-persistence path — we already carry that one unchanged. Leave it.

**The general lesson, worth more than the specifics: a fork patch is a statement of intent, not a diff to replay.** Ours is "the gateway is the sole MCP speaker." Re-derive what that means against the new code each quarter. If you find yourself applying a saved patch, stop.

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

**2. The e2e suite has an upstream-DOM dependency our own specs inherit.** Our 13 LQ.AI specs assert on our own `data-testid="lq-ai-*"` hooks and are decoupled — but they log in through the shared `cy.session` helper in `cypress/support/e2e.ts`, which drives *upstream's* auth form and waits on `#chat-search`, then dismisses upstream's changelog modal by its button text. So every spec is transitively coupled to upstream's markup through one file — and that file is one of the six conflicts.

Both anchors survive v0.11.0 (`#chat-search` is still in `Sidebar/SearchInput.svelte`; `"Okay, Let's Go!"` is still in `ChangelogModal.svelte`), so **this does not fire this quarter**. Re-check both before trusting the suite:

```bash
git grep -c "chat-search" v0.11.0 -- src/
git grep -c "Okay, Let" v0.11.0 -- src/lib/components/ChangelogModal.svelte
```

Separately, four of our Cypress specs are **upstream's own, inherited at the vendor import** — `chat.cy.ts`, `documents.cy.ts`, `registration.cy.ts`, `settings.cy.ts` — plus `support/index.d.ts` and `cypress/tsconfig.json`. They select upstream markup (`#chat-input`, `.chat-user`, `#chat-share-button`, `#copy-and-share-chat-button`) and upstream deleted every one of them at v0.11.0.

**Take upstream's deletion.** They were never ours, they test upstream's UI, and that UI was redesigned — so they would fail. Deleting them is the default resolution, costs nothing, and is what "upgrade to v0.11.0" means for files upstream removed. Adopting and rewriting them against the new UI would be new test-authoring work, not an upgrade; if anyone wants that coverage back later it is a DE, not a merge task.

**No command needed — the merge already removed them.** We never modified those four, so they are clean deletions and drop out automatically; an explicit `git rm` fails with *pathspec did not match any files*. Just confirm:

```bash
git ls-files web/cypress/e2e/ | wc -l    # expect 13 — ours only
```

**Keep `cypress/tsconfig.json` and `cypress/support/index.d.ts`, even though upstream deleted both.** They are infrastructure, not specs: `tsconfig.json` (`extends: ../tsconfig.json`) types every `.ts` file in `cypress/`, including our 13, and `index.d.ts` declares the `Chainable` custom commands that `support/e2e.ts` still defines. Deleting either breaks type-checking on our own suite. Carrying them is the same posture as `cypress.config.ts`.

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

> **Status after the 2026-08-24/25 execution — all gates run and passing.** Backend compiles; `check:lq-ai` clean (0 errors / 708 files); Vitest green (738 tests); host bundle builds at 6144; Docker frontend stage builds; full 6.5 GB image builds clean; §8's static branding check passes. **On a fresh stack:** all 8 services healthy, **all 15 new upstream migrations applied cleanly** (ending `f0bd01a18a3d`; the only log "error" is a benign SQLAlchemy warning inside an upstream migration), delegated login works, the `/lq-ai` shell renders correctly despite nesting in the rewritten root layout, dual branding renders, and **the ADR 0014 constraint holds** — the Add Connection modal's Type row is static `OpenAPI` with no MCP toggle.
>
> **Run the stack isolated, not in place.** `docker-compose.yml` pins `name: lq-ai`, so a `docker compose up` from a worktree targets your normal project and would upgrade your dev database's OpenWebUI schema one-way. Use a separate project instead — this also gives you the clean-migration check for free:
>
> ```bash
> cd <main checkout> && docker compose stop        # NOT down -v
> cd <worktree> && cp <main checkout>/.env .env
> docker compose -p lqai-v11 up -d --build
> docker compose -p lqai-v11 exec api python -m app.cli reset-admin-password \
>   --email admin@lq.ai --password 'LQ-AI-smoke-test-Pw1!' --no-force-change
> ```
>
> Deep links into the OpenWebUI admin bounce to `/lq-ai` on a cold session — load `/admin` first, then navigate. Integrations moved under **Services** in the redesigned settings panel.

**Run the gates CI actually runs — not the bare tools.** This bit the first execution:

```bash
cd web
npm run check:lq-ai              # THE typecheck gate (tsconfig.lq-ai.json)
npm run test:frontend -- --run   # THE unit-test gate
```

**Do not run bare `npx svelte-check`.** It types upstream's entire tree and reports **8320 errors / 353 files** — all pre-existing upstream state, none of it ours, and it looks exactly like the rebase destroyed everything. The real gate is scoped by `tsconfig.lq-ai.json` and reported **0 errors across 708 files** on the merged v0.11.0 tree.

**The bundle build needs more heap than the default, and CI does not run it at all.**

```bash
NODE_OPTIONS=--max-old-space-size=6144 npm run build
```

CI's web job runs `check:lq-ai` and Vitest only. **Nothing in CI builds the bundle** — the first thing to fail is the Docker image build, for whoever deploys next. So this step is not optional, and it is the reason §7 exists.

**[v0.11.0]** Measured on the merged tree: **4096 fails** (OOM while rendering client chunks, exit 134), **6144 and 8192 succeed**. Pre-merge `main` builds fine at 4096, so this is a genuine regression from the upgrade — `web/Dockerfile`'s `NODE_OPTIONS` was raised 4096 → 6144 in the same PR. Upstream ships that line commented out; we set it because our tree needs it, and the requirement has now grown twice. **Re-measure each quarter** rather than assuming the current value still holds.

`npm run build` also runs `pyodide:fetch` (`scripts/prepare-pyodide.js`) first, which is what regenerates `static/pyodide/pyodide-lock.json` — see §4. That script resolves package versions live from PyPI, so the file can drift for reasons unrelated to the rebase.

### The Docker build — two things the one-liner hides

**`docker compose` does not work from a git worktree.** There is no `.env` there (gitignored, it lives in the main checkout), so interpolation fails on `POSTGRES_PASSWORD` before any build starts. Either run the compose steps from the main checkout, or copy `.env` into the worktree. This bites immediately if you followed §2 into a worktree.

**Verify the frontend stage on its own first.** It is where the heap risk lives, it needs no `.env`, and it finishes in a couple of minutes instead of the better part of an hour:

```bash
docker build --target build --build-arg PUBLIC_LQ_AI_API_BASE_URL=/api/v1 -t web-fe-check ./web
```

**Then the full image, which is much heavier than it looks.** `backend/requirements.txt` changes every refresh (61 packages this time, §5.5), so that layer fully invalidates and reinstalls torch, sentence-transformers and whisper — downloading models at build time. **[v0.11.0] measured: 6.5 GB image, clean build.**

```bash
docker build --build-arg PUBLIC_LQ_AI_API_BASE_URL=/api/v1 -t web-full-check ./web
```

Clean up the throwaway tags afterwards (`docker image rm web-fe-check web-full-check`).

**Then the migrations and the locale check (§5.5):**

```bash
# 15 new upstream migrations must apply cleanly on a fresh DB.
# NEVER host-side alembic against the live dev DB — see CLAUDE.md.
# Run these from the MAIN CHECKOUT, not a worktree — see above.
docker compose build web && docker compose up -d web
docker compose logs web | grep -i "alembic\|migration\|Running upgrade"
```

```bash
# The case-only locale rename — macOS is case-insensitive, the container is not.
git ls-files web/src/lib/i18n/locales/ | grep -i uz-latn   # expect one entry: uz-Latn-UZ
```

ADR 0001 §Mitigations requires **testing against the M1 quickstart end-to-end before merge**. That is the gate, not a suggestion.


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

### The static check settles it in two commands

Compliance turns on one question — **do we alter, remove, or obscure any upstream branding identifier?** — and that is answerable from the deviation diff without running anything:

```bash
# Which upstream UI files do we touch at all? (excluding our own namespace)
git diff --name-only $THEIRS_TREE HEAD -- web/src/ \
  | grep -v '^web/src/lib/lq-ai/\|^web/src/routes/lq-ai/'

# Upstream's identifiers still present in the merged tree
grep -rc "Open WebUI" web/src/ | awk -F: '{s+=$2} END {print s}'
```

**[v0.11.0] result, verified 2026-08-24:** exactly two files outside our namespace — `AddToolServerModal.svelte` (the ADR 0014 MCP toggle, not branding) and `src/routes/(app)/+page.ts` (a *new* file, the ADR 0009 `/` → `/lq-ai` redirect). **1626 "Open WebUI" occurrences intact.** We remove nothing. Clause 4 is satisfied.

This works because of the isolation measured in §5.5: our code lives in its own namespace and overrides no upstream component, so upstream's branding cannot be displaced by our patches. **If that ever stops being true, this check is what tells you.**

**What the static check does not cover:** whether the redesigned UI still *renders* those identifiers where a user sees them. That needs the stack and human eyes — do it during the M1 quickstart walk (§7), not from the diff.

**A pre-existing inaccuracy, noted rather than fixed** (out of scope per §Scope, and not introduced by any rebase): `DualBrandingFooter.svelte`'s docstring claims it renders "in every LQ.AI shell route **and in the OpenWebUI shell's `+layout.svelte`**". It does not — on `main` and after the merge alike it is mounted only in `routes/lq-ai/+layout.svelte` and `routes/lq-ai/login/+page.svelte`. Compliance does not depend on it, because upstream's own shell carries upstream's own branding natively. But the comment overclaims. Worth a DE.

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

- **2026-08-25 — v0.9.2 → v0.11.0.** First quarterly refresh under this ADR. Latest upstream stable at the time (released 2026-07-27); 1402 upstream commits, 880 changed paths, 12 files changed on both sides of which 6 conflicted. The ADR 0014 deletion of `utils/mcp/client.py` was re-asserted, and Cypress was carried forward after upstream removed it entirely.
```

### The version string that actually matters is not in `docs/`

**Grep `web/src/` too, and do it first.** The dual-branding footer states the upstream version to every user on every LQ.AI route:

```bash
grep -rn "v0\.9\.2" web/src/
# web/src/lib/lq-ai/components/DualBrandingFooter.svelte
#   (forked at v0.9.2; see ADR 0001).
```

**[v0.11.0]** That was the only occurrence under `web/src/`, and the only *user-visible* one anywhere. It was caught by looking at the running stack, not by grep — the earlier edition of this section named only `docs/` and `README.md`. Fixed in the same PR.

### Do not rewrite the historical references

The instruction to "update the pinned version wherever it appears" is **too broad and will corrupt the record.** Of the nine occurrences outside this runbook at the v0.11.0 refresh, **none should have been rewritten**:

| Location | Why it stays |
| --- | --- |
| ADR 0001 §Decision, §Consequences, §Mitigations | The position *when the ADR was accepted*. ADRs are historical records — amended by Revisions or superseded by a follow-on ADR, never edited in place. |
| [ADR 0009](adr/0009-web-lq-ai-shell-coexistence.md) | Describes the fork as it stood when shell coexistence was decided; its rebase-cost reasoning is about *that* patch surface. |
| `M1-PROGRESS.md`, `M1-IMPLEMENTATION-ORDER.md` | Statements about what landed during M1. "OpenWebUI v0.9.2 imported into `web/`" is true and stays true. |

`README.md` had no occurrences at all.

**The rule:** a `v0.9.2` reference is a stale pin only if it asserts *what we currently run*. If it records *what happened*, leave it. The Revisions entry added above carries a note saying so, to stop a future refresh mistaking those for stale pins.

---

## 11. After it merges

1. **Tell the four affected PRs to rebase** (§1), and be specific about which files rather than leaving them to guess: #282, #286 and #437 all need `package-lock.json` **regenerated with `npm install`, not hand-merged**; #432's overlap is `package.json` alone. #282 and #286 also still need CI to run for the first time. For #432 and #437, include the Cypress ownership change (§5.2) and, for #437, the `cy.session` coupling note (§5.5) — they are modifying that exact file.
2. **Re-run CI on the eleven non-conflicting web PRs** — #263, #264, #267, #280, #314, #315, #402, #416, #417, #418, #430. No file conflicts, but the upstream code they integrate against has moved.
3. **Close the superseded Dependabot PRs** (§9).
4. **Fix this runbook** wherever it was wrong. §3–§6 were already corrected against a merge dry-run on 2026-08-24, but nothing downstream of the merge has been exercised — §7's gates especially. What the first real execution learns is worth more than anything written in advance.
5. **Diarise the next refresh** — quarterly from the merge date.
