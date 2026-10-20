# DE-365 sub-3 — Vendor-neutral Comparison Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the vendor-neutral, evidence-linked comparison — a canonical `docs/comparison.md` matrix (every LQ.AI cell links to proof) + a `/lq-ai/learn/compare` Svelte page (three fundamental truths + highlights + playground links) — and fold in the vendor-neutral cleanup (genericize the DE-365 PRD entry; close DE-377).

**Architecture:** Three prose/markup units — (1) the canonical doc, (2) the Learn page + landing wiring, (3) the vendor-neutral cleanup + README links. The doc is the single source of truth; the Learn page is a condensed highlights surface that points at it. No backend/API code; the comparison axis is **verifiability, not capability**.

**Tech Stack:** Markdown (docs) + SvelteKit (the OpenWebUI fork's Learn surface). Prettier + ESLint on the Svelte page; the CI "Web" check runs svelte-check.

**Spec:** `docs/superpowers/specs/2026-07-03-de365-sub3-comparison-design.md`

## Global Constraints

- **Comparison axis = verifiability, not capability.** The "proprietary category" column states ONLY the verifiability/forkability gap ("may claim it; closed-source → not independently verifiable by the user"). NEVER assert the category *lacks* a capability. Strictly true, unflinching, never a dig.
- **No named vendor anywhere** — no "Thomson Reuters", "Westlaw", "CoCounsel", "Streamline" (or any product) in `docs/comparison.md`, the Learn page, `README.md`, or the edited DE entries.
- **Every LQ.AI ✓ links to a real proof artifact on `main`** (ADR + code path + one of the 24 playgrounds + HONEST-STATE). Links must resolve.
- **Every partial/roadmapped capability carries its caveat inline** — DE-370/371 (chat/autonomous gate parity), EUR-Lex get-by-CELEX-only (DE-374/375), no dedicated matter-intake UI, anonymization recall unmeasured on legal corpus.
- **Doc is canonical**; the Learn page is condensed highlights + a prominent pointer to the doc (avoids two full matrices drifting).
- **Web dev-env:** the `web` container serves a pre-built static bundle (no HMR) — rebuild `web` to eyeball UI changes (controller does this in the final verify).
- No new API routes → do NOT touch `IMPLEMENTED_ROUTES` / `EXPECTED_PATHS`.
- Commits: `git commit -s` (DCO) AND trailer `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`.

## Proof-artifact reference (all confirmed present on `main`)

The 14 matrix rows and their proof links are enumerated in the spec's **§4.3 table** — use it verbatim as the row data. Playground slugs live at `/learn/playgrounds/<slug>.html` (files in `web/static/learn/playgrounds/`). Repo blob base for doc links: relative paths from `docs/` (e.g. `adr/0018-...md`, `../api/app/citation/ledger.py`, `../skills/CONTRIBUTING.md`). Learn-page playground links use the runtime path `/learn/playgrounds/<slug>.html`.

---

## Task 1: Canonical `docs/comparison.md`

**Files:**
- Create: `docs/comparison.md`

**Deliverable:** the exhaustive, evidence-linked comparison doc.

Structure (write real prose; the row data is the spec §4.3 table verbatim):
1. **Title + one-paragraph frame:** LQ.AI vs. the proprietary "fiduciary-grade"-claiming legal-tech *category*; the axis is verifiability; their announced direction inspired this and (per their public statements) is not yet shipped; LQ.AI delivers it transparently, open-source, self-hosted, now.
2. **The three fundamental truths** (each 2–4 sentences, vendor-neutral):
   (i) demonstrable vs. asserted (every ✓ resolves to an artifact);
   (ii) show-the-work vs. trust-us (an opaque editorial verdict is architecturally un-inspectable; link [PRD §1.3](PRD.md#13-transparency-as-a-founding-principle));
   (iii) named accountability vs. committee-anonymized (link [skills/CONTRIBUTING.md](../skills/CONTRIBUTING.md) attestation process).
3. **How to read this table:** the axis is verifiability; the right column states the verifiability gap, never capability absence.
4. **The matrix:** a markdown table with columns `Capability | LQ.AI — verifiable (proof) | Proprietary category — closed → not user-verifiable | Honest caveat`. One row per spec §4.3 entry (14 rows). Each LQ.AI cell links its ADR + code path + playground; each partial row fills the caveat column (rows 3, 4, 5, 6, 9 per the spec).
5. **Where LQ.AI is partial or roadmapped:** a consolidated bullet list (DE-370/371, EUR-Lex DE-374/375, matter-intake UI, anonymization validation, Word/intake scaffolding) — mirrors HONEST-STATE.
6. **How to verify this comparison:** clone it, read the linked code, run the playgrounds, read [HONEST-STATE.md](HONEST-STATE.md); "if the table claims something the code doesn't back up, the code is canonical — [open an issue](https://github.com/LegalQuants/lq-ai/issues)."

- [ ] **Step 1: Read the spec §4.3 table** (`docs/superpowers/specs/2026-07-03-de365-sub3-comparison-design.md`) for the exact 14 rows + proof links, and skim `docs/HONEST-STATE.md §5.6` for the shipped fiduciary-grade catalog + caveats so the prose matches the honest state.
- [ ] **Step 2: Write `docs/comparison.md`** per the structure above. Use relative links from `docs/` for repo files/ADRs; use `/learn/playgrounds/<slug>.html` for playgrounds. Keep the "them" column strictly to the verifiability gap.
- [ ] **Step 3: Link-check** — every referenced repo path exists and every playground slug is real:

```bash
cd /Users/kevinkeller/Code/lq-ai
# extract repo-relative doc links + check they resolve from docs/
grep -oE '\]\((\.\./|adr/|[a-z])[^)]+\)' docs/comparison.md | sed -E 's/^\]\(//; s/\)$//' | grep -vE '^https?:|^#' | while read -r p; do
  f="docs/${p#../}"; [ "${p#../}" != "$p" ] && f="${p#../}"; [ -e "$f" ] || echo "MISSING: $p -> $f"
done
# check each playground slug referenced exists
grep -oE '/learn/playgrounds/[a-z-]+\.html' docs/comparison.md | sort -u | sed 's#/learn/playgrounds/##' | while read -r s; do
  [ -e "web/static/learn/playgrounds/$s" ] || echo "MISSING PLAYGROUND: $s"
done
```
Expected: no `MISSING` lines. Fix any that print.

- [ ] **Step 4: Vendor-neutral grep** — must return nothing:

```bash
grep -niE 'thomson|westlaw|cocounsel|streamline' docs/comparison.md || echo "CLEAN: no named vendor"
```
Expected: `CLEAN: no named vendor`.

- [ ] **Step 5: Commit**

```bash
git add docs/comparison.md
git commit -s -m "docs(DE-365 sub-3): canonical evidence-linked comparison matrix

Refs DE-365"
```

---

## Task 2: `/lq-ai/learn/compare` Svelte page + Learn landing card

**Files:**
- Create: `web/src/routes/lq-ai/learn/compare/+page.svelte`
- Modify: `web/src/routes/lq-ai/learn/+page.svelte` (add the 4th Learn card)

**Deliverable:** an in-app Learn page presenting the three truths + a condensed highlight matrix with playground links + a pointer to the canonical doc; reachable from the Learn landing.

The page follows the existing Learn page conventions — read `web/src/routes/lq-ai/learn/how/+page.svelte` (structure, `lq-*` classes, `data-testid`s, `<style>` block) and `web/src/routes/lq-ai/learn/use/+page.svelte` for the page shell. Content:
- `<main class="..." data-testid="lq-ai-learn-compare-page">` with a header (`← Learn` back-link, `<h1 class="lq-text-page-h">`, intro paragraph stating the verifiability axis + vendor-neutral framing).
- **Three fundamental truths** — three short blocks.
- **Condensed highlight matrix** — ~6–8 headline rows (pick the most load-bearing from the doc's 14: derive-don't-assert, Citation Ledger + P3, fiduciary gate, treatment layer, authority sources, governed matter sessions, governed egress, self-hosted/BYOK). Each row: capability + a one-line LQ.AI-verifiable vs proprietary-closed contrast + an inline link to its **playground** (`<a href="/learn/playgrounds/<slug>.html" target="_blank" rel="noopener">`) and its ADR/code. Partial rows carry their caveat.
- A prominent callout: **"Full evidence-linked comparison + verification paths → `docs/comparison.md`"** linking `https://github.com/LegalQuants/lq-ai/blob/main/docs/comparison.md`.
- Reuse the how-page's `<style>` idioms (`.lq-*`); do not invent a new design language.

For the Learn landing (`web/src/routes/lq-ai/learn/+page.svelte`), add a 4th `.lq-learn-card` after the `build` card:
```svelte
<a class="lq-learn-card" href="/lq-ai/learn/compare" data-testid="lq-ai-learn-card-compare">
	<span class="lq-learn-card-icon" aria-hidden="true">⚖️</span>
	<h2 class="lq-learn-card-title">How It Compares</h2>
	<p class="lq-learn-card-desc">
		An evidence-linked, vendor-neutral comparison — every capability claim links to the code, ADR, or interactive playground that proves it.
	</p>
	<span class="lq-learn-card-cta">Explore →</span>
</a>
```

- [ ] **Step 1: Read** `web/src/routes/lq-ai/learn/how/+page.svelte` (full) + `web/src/routes/lq-ai/learn/+page.svelte` to match the page shell, `lq-*` classes, and card pattern.
- [ ] **Step 2: Create** `web/src/routes/lq-ai/learn/compare/+page.svelte` with the content above. Every playground link uses `/learn/playgrounds/<slug>.html`; the canonical-doc link uses the GitHub blob URL. Keep the "them" phrasing to the verifiability gap.
- [ ] **Step 3: Add the 4th Learn card** to `web/src/routes/lq-ai/learn/+page.svelte` (verbatim block above).
- [ ] **Step 4: Format + lint:**

```bash
cd /Users/kevinkeller/Code/lq-ai/web
npx prettier --write src/routes/lq-ai/learn/compare/+page.svelte src/routes/lq-ai/learn/+page.svelte
npx eslint src/routes/lq-ai/learn/compare/+page.svelte src/routes/lq-ai/learn/+page.svelte
```
Expected: Prettier reformats if needed; ESLint passes (no errors).

- [ ] **Step 5: Structural checks:**

```bash
cd /Users/kevinkeller/Code/lq-ai
grep -c 'data-testid="lq-ai-learn-card-' web/src/routes/lq-ai/learn/+page.svelte   # expect 4
grep -c 'data-testid="lq-ai-learn-compare-page"' web/src/routes/lq-ai/learn/compare/+page.svelte  # expect 1
grep -niE 'thomson|westlaw|cocounsel|streamline' web/src/routes/lq-ai/learn/compare/+page.svelte || echo "CLEAN: no named vendor"
# every playground link in the page resolves
grep -oE '/learn/playgrounds/[a-z-]+\.html' web/src/routes/lq-ai/learn/compare/+page.svelte | sort -u | sed 's#/learn/playgrounds/##' | while read -r s; do [ -e "web/static/learn/playgrounds/$s" ] || echo "MISSING PLAYGROUND: $s"; done
```
Expected: `4`, `1`, `CLEAN: no named vendor`, no `MISSING` lines.

- [ ] **Step 6: Commit**

```bash
git add web/src/routes/lq-ai/learn/compare/+page.svelte web/src/routes/lq-ai/learn/+page.svelte
git commit -s -m "feat(DE-365 sub-3): /lq-ai/learn/compare page + Learn landing card

Refs DE-365"
```

---

## Task 3: Vendor-neutral cleanup + README links

**Files:**
- Modify: `docs/PRD.md` (DE-365 entry §4844; DE-377 entry §4957)
- Modify: `README.md` (genericize the "Streamline AI" reference; add links to the comparison doc + Learn compare page)

**Deliverable:** no named vendor remains in the public docs; README points at both comparison surfaces; DE-377 marked resolved; DE-365 entry genericized + sub-3 marked shipped.

- [ ] **Step 1: Genericize the DE-365 PRD entry** (`docs/PRD.md`, the `#### DE-365 —` block ~line 4844). Replace the three named vendors ("Thomson Reuters / Westlaw / CoCounsel") wherever they appear in that block with the generic category ("proprietary 'fiduciary-grade'-claiming legal tech" / "closed-source incumbents"), keeping the "their announced direction inspired this" framing generic. Update its **Status** line to note sub-project 3 shipped and that all three DE-365 sub-projects are complete.
- [ ] **Step 2: Close DE-377** (`docs/PRD.md`, the `#### DE-377 —` block ~line 4957). Update its Status to "resolved (DE-365 sub-3)" and note the README reference was genericized.
- [ ] **Step 3: Genericize the README "Streamline AI" reference** — find it:

```bash
grep -n 'Streamline' README.md
```
Replace the named reference with a generic category phrase (e.g. "dedicated legal-intake/triage platforms") while preserving the scope-narrowing intent of the sentence.

- [ ] **Step 4: Add README links to the comparison.** In a suitable existing README section (e.g. "Project status" or "What you can verify" or "Documentation"), add a one-line pointer to the evidence-linked comparison: the canonical `docs/comparison.md` and the in-app `/lq-ai/learn/compare` page. Keep it brief; do not bloat the README.
- [ ] **Step 5: Vendor-neutral grep across the touched public surfaces** — must be clean:

```bash
cd /Users/kevinkeller/Code/lq-ai
grep -niE 'thomson|westlaw|cocounsel|streamline' README.md docs/comparison.md web/src/routes/lq-ai/learn/compare/+page.svelte && echo "FOUND — fix above" || echo "CLEAN: no named vendor in public surfaces"
```
Expected: `CLEAN: no named vendor in public surfaces`. (The DE-365/DE-377 PRD entries now describe the genericization; they may still *mention* the words in a "was named X, now generic" note — that's acceptable in the backlog changelog, but keep README/comparison/Learn strictly clean.)

- [ ] **Step 6: Commit**

```bash
git add docs/PRD.md README.md
git commit -s -m "docs(DE-365 sub-3): vendor-neutral cleanup + README comparison links

Genericizes the DE-365 PRD entry vendor names, resolves DE-377 (README
Streamline reference), and links the evidence-linked comparison (doc + Learn
page) from the README.

Refs DE-365 DE-377"
```

---

## Self-Review

**Spec coverage:**
- §4.1 canonical doc (3 truths, how-to-read, matrix, partial list, how-to-verify) → Task 1. ✓
- §4.2 Learn page + landing wiring → Task 2. ✓
- §4.3 matrix rows + proof links → Task 1 (row data = spec §4.3 verbatim; link-check enforces resolution). ✓
- §4.4 vendor-neutral cleanup (DE-365 entry, DE-377, README) → Task 3. ✓
- §5 honesty guardrails (verifiability-only "them" column, inline caveats, no named vendor) → Global Constraints + per-task greps. ✓
- §6 verification (link-check, prettier/eslint, vendor grep, no route-guard edits; rebuild-web eyeball) → Task 1 Steps 3–4, Task 2 Steps 4–5, Task 3 Step 5; **rebuild-web + headless-render eyeball is the controller's final verify** (no browser in a subagent), same as sub-2. ✓
- §7 process (branch first, mirror, DE-365 completion) → branch already created; mirror + release-gate note happen at ship time. ✓

**Placeholder scan:** no TBD/TODO; each task names exact files, the row data source (spec §4.3), exact link-check + grep commands with expected output, and the Learn-card block verbatim. The doc/page *prose* is authored by the implementer against a fully-specified structure + row data — not a placeholder. ✓

**Type/name consistency:** slugs, the `data-testid` names (`lq-ai-learn-compare-page`, `lq-ai-learn-card-compare`), the canonical-doc path (`docs/comparison.md`), and the vendor-neutral word list are identical across Tasks 1–3 and match the spec. The Learn-landing card count goes 3→4, stated consistently in Task 2 Steps 3/5. ✓
