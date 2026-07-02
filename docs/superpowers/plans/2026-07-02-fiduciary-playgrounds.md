# Fiduciary-grade Learn Playgrounds Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build 5 self-contained interactive Learn playgrounds covering the fiduciary-grade milestone (authority-sources, citation-ledger, fiduciary-gate, treatment-layer, matter-session-flow) and wire them into the Learn "how it works" page as a labeled cluster.

**Architecture:** Each playground is a single self-contained HTML file in `web/static/learn/playgrounds/<slug>.html`, served directly by the `web` container at `/learn/playgrounds/<slug>.html`. They reuse the established shell (dark CSS-variable theme, `↩ Learn` / `View source ↗` header, verify-in-source links, "no live network calls" disclaimer) with a bespoke core interaction per capability and a shared cluster accent. They are embedded as `<iframe>` sections in the SvelteKit how-page. No backend, no API, no DB changes.

**Tech Stack:** Plain HTML5 + CSS + vanilla JS (no framework, no build step, no external assets) for the playgrounds; SvelteKit (OpenWebUI fork) for the how-page. Built with the **playground skill**.

**Spec:** `docs/superpowers/specs/2026-07-02-fiduciary-playgrounds-design.md`

## Global Constraints

- **Self-contained:** each playground is ONE `.html` file — no external CSS/JS/images/fonts, no network calls at runtime. All data is synthetic/static and inlined.
- **Honest, no overclaim (CLAUDE.md §4):** every playground surfaces its **real caveat** inline (not just the happy path). Caveat text and verdict/enum terms must match the actual code, not summaries. Use real terms: gate tiers are **PASS / SUPPORTED / FAIL** (provenance excluded); brake order is **R5 → R6 → R4**.
- **Verify-in-source:** every claim links to the canonical source via `const REPO = 'https://github.com/LegalQuants/lq-ai/blob/main/'`. Links must resolve to real paths on `main`.
- **Vendor-neutral:** no named competitor anywhere.
- **Standing disclaimer** on every playground: **"Illustrative walkthrough — this page makes no live network calls."**
- **Shared shell** (copy from `web/static/learn/playgrounds/governed-tool-flow.html`): the `:root` CSS-variable dark theme, `* { box-sizing: border-box }`, `html,body` reset (`height:100vh; overflow:hidden`), the `header` with `<h1>LQ.AI — <title></h1>`, a `.subtitle`, `.spacer`, `<a href="../../">↩ Learn</a>`, and `<a href="https://github.com/LegalQuants/lq-ai" target="_blank" rel="noopener">View source ↗</a>`.
- **Cluster accent:** the 5 share one distinct fiduciary hue (amber/gold, e.g. `--fid: #f5b544;`) used for the cluster's primary accent, distinct from the existing blue `--accent: #7dd3fc`. Keep the blue for neutral UI chrome; use the amber for the fiduciary-specific highlight so the set reads as one cluster. If it clashes in-context, fall back to blue.
- **Web dev-env rule:** the `web` container serves a **pre-built static bundle (no HMR)** — rebuild `web` before eyeballing UI changes.
- **Prettier + ESLint** on the Svelte edit (CI runs them as separate gates). The static `.html` files are not Prettier-governed the same way; match the existing playgrounds' hand-formatting.
- **No api test coupling:** no new API routes → do NOT touch `IMPLEMENTED_ROUTES` / `EXPECTED_PATHS` / OpenAPI guards.

---

## Shared shell reference

Every playground task below assumes this shell. Copy it from `governed-tool-flow.html` (lines 1–56 for `<head>`/theme, 216–224 for the header, and the `REPO` const + closing tags). The concrete deliverable of each playground task is: **shell + bespoke core interaction + honest caveat panel + verify-in-source links**.

Acceptance criteria shared by all 5 playground tasks (Tasks 1–5):
1. Single self-contained `.html` file, opens standalone in a browser with no console errors and no network requests.
2. Header matches the shell (title, `↩ Learn`, `View source ↗`).
3. The bespoke core interaction works (described per task).
4. The honest caveat is visible in-viz (exact text per task).
5. Every verify-in-source link uses `REPO + <real path>` and resolves on `main`.
6. The "makes no live network calls" disclaimer is present.
7. Uses the amber cluster accent for the fiduciary highlight.

---

### Task 1: `authority-sources` playground

**Files:**
- Create: `web/static/learn/playgrounds/authority-sources.html`

**Grounding (read before authoring — accuracy is load-bearing):**
- `api/app/research/registry.py` — `SOURCE_REGISTRY` (the four `SourceSpec` entries: `courtlistener`, `govinfo`, `edgar`, `eurlex`, each with `jurisdiction` / `coverage` / `content_kinds` / `ops` / `adapter`) and `resolve_available_sources` (joins the static registry against the gateway's live provider list → `AvailableSource(enabled=True|False)`).
- `docs/adr/0021-content-source-registry-and-free-source-expansion.md`.

**Core interaction:** a **registry explorer**. Left panel: 4 toggles, one per source — "operator configured this provider in `gateway.yaml`?" Main panel: for each registry entry, render an `AvailableSource` card showing `enabled=True` (green) when its provider toggle is on, or **`enabled=False` — unavailable (reason: no configured provider)** (dimmed, NOT hidden) when off. Selecting an enabled source expands its `jurisdiction` / `coverage` / `content_kinds` / `ops`, and shows a small "retrieve by identifier → character-verify" sketch (illustrative, static).

**Honest caveats (must appear in-viz, verbatim intent):**
- "**EUR-Lex is get-by-CELEX only** — its `ops` is `('get_authority',)`. No keyword search (DE-374) or treaty lookup (DE-375) yet."
- "A registered source with no configured provider is reported **unavailable-with-reason, never silently omitted**."
- "The registry exposes **name / type / jurisdiction / coverage / content_kinds / ops only — never auth keys, cost, or secrets** (P3 / ADR 0016)."

**Verify-in-source links:** `api/app/research/registry.py`; `docs/adr/0021-content-source-registry-and-free-source-expansion.md`.

- [ ] **Step 1: Read the grounding sources** (`registry.py`, ADR 0021). Note the exact four types, their `ops` tuples, and the `resolve_available_sources` enabled/disabled/excluded rules.
- [ ] **Step 2: Build the playground** using the playground skill and the shared shell. Implement the registry-explorer interaction and the caveat panel.
- [ ] **Step 3: Self-check against the 7 shared acceptance criteria + the 3 caveats above.** Open the file in a browser; confirm no console errors, toggles flip enabled/disabled cards, EUR-Lex shows the get-by-CELEX caveat, all links resolve.
- [ ] **Step 4: Commit**

```bash
git add web/static/learn/playgrounds/authority-sources.html
git commit -s -m "feat(DE-365 sub-2): authority-sources Learn playground

Refs DE-365"
```

---

### Task 2: `citation-ledger` playground

**Files:**
- Create: `web/static/learn/playgrounds/citation-ledger.html`

**Grounding:**
- `api/app/citation/ledger.py` — how ledger entries are assembled per turn; the id/offset references; provenance-only entries (tool sources, no quote) are **not assertions**.
- `docs/adr/0018-citation-ledger-and-fiduciary-grade-output.md`.

**Core interaction:** a **read-trail**. Show a turn's ordered ledger entries (synthetic: a mix of quote-bearing entries and provenance-only entries). The user clicks an entry's claim → it **traces to source + character offset** (an id + `[start:end]` offset resolving into a synthetic source doc panel, highlighting the offset span). Provenance-only entries render with a distinct "provenance — not an assertion" badge and cannot be "traced to a quote."

**Honest caveat (in-viz):**
- "The ledger references content **by id + character offset only — no raw payloads** live in the audit layer (P3). A trace resolves an id+offset; the quoted text is not stored in the ledger."

**Verify-in-source links:** `api/app/citation/ledger.py`; `docs/adr/0018-citation-ledger-and-fiduciary-grade-output.md`.

- [ ] **Step 1: Read the grounding sources** (`ledger.py`, ADR 0018).
- [ ] **Step 2: Build the playground** (playground skill + shared shell): the read-trail, click-to-trace, provenance-vs-assertion distinction, caveat panel.
- [ ] **Step 3: Self-check** against the 7 shared criteria + the caveat. Confirm clicking a quote-bearing entry highlights an offset span in a source panel; provenance entries show the badge and no quote trace; no network calls.
- [ ] **Step 4: Commit**

```bash
git add web/static/learn/playgrounds/citation-ledger.html
git commit -s -m "feat(DE-365 sub-2): citation-ledger Learn playground

Refs DE-365"
```

---

### Task 3: `fiduciary-gate` playground

**Files:**
- Create: `web/static/learn/playgrounds/fiduciary-gate.html`

**Grounding:**
- `api/app/citation/gate.py` — `compute_and_record_gate`, and the exact buckets:
  - `PASS_STATUSES = {"exact_match", "tolerant_match"}`
  - `SUPPORTED_STATUSES = {"paraphrase_judge", "ensemble_strict", "ensemble_majority"}`
  - `FAIL_STATUSES = {"unverified", "failed"}`
  - `_PROVENANCE = "provenance"` → **excluded** (not an assertion).
- `docs/adr/0018-citation-ledger-and-fiduciary-grade-output.md` (D3: work product is fiduciary-grade only when every citation is ledger-backed).

**Core interaction:** a **verdict computer**. The user assembles a turn's citation set — each citation a chip with a selectable `verification_status` (the 8 statuses above + `provenance`). As statuses change, the viz **deterministically buckets** them into PASS / SUPPORTED / FAIL counts (provenance excluded from counts) and shows the resulting per-message verdict, plus the ADR 0018 D3 rule ("fiduciary-grade only when every citation is ledger-backed").

**Honest caveat (in-viz):**
- "**Chat vs autonomous verdict-tier parity gaps remain** (DE-370 / DE-371) — the gate runs on both the chat and autonomous paths, but tier handling is not yet identical across them."

**Must use the real tiers PASS / SUPPORTED / FAIL — not 'flagged'.**

**Verify-in-source links:** `api/app/citation/gate.py`; `docs/adr/0018-citation-ledger-and-fiduciary-grade-output.md`.

- [ ] **Step 1: Read the grounding sources** (`gate.py`, ADR 0018). Copy the three status frozensets exactly.
- [ ] **Step 2: Build the playground** (playground skill + shared shell): citation chips with status selectors, live PASS/SUPPORTED/FAIL bucketing, provenance-excluded handling, D3 rule, DE-370/371 caveat panel.
- [ ] **Step 3: Self-check** against the 7 shared criteria + the caveat. Confirm each status maps to the correct bucket per `gate.py`; provenance is excluded from counts; tiers read PASS/SUPPORTED/FAIL; no network calls.
- [ ] **Step 4: Commit**

```bash
git add web/static/learn/playgrounds/fiduciary-gate.html
git commit -s -m "feat(DE-365 sub-2): fiduciary-gate Learn playground

Refs DE-365"
```

---

### Task 4: `treatment-layer` playground

**Files:**
- Create: `web/static/learn/playgrounds/treatment-layer.html`

**Grounding:**
- `api/app/citation/treatment.py` — graph pass (PR1) + judge pass (PR2); signals `followed` / `distinguished` / `criticized`; `derived_method='citation_graph+judge'`; snippets are transient judge input **never stored** (P3); `TREATMENT_TTL_DAYS = 30`; `N_JUDGED_CAP = 10`; bounded judge budget.
- `docs/adr/0019-transparent-validity-treatment-layer.md`.

**Core interaction:** a **treatment explorer**. The user picks a cited case (synthetic). The viz shows its **derived treatment rollup** (e.g. "mostly followed, 1 distinguished") and the underlying citing-case signals that produced it — each citing case a row with its signal (followed/distinguished/criticized) and a trace link to that citing opinion. Show the two-pass derivation: citation graph → judge on top-N snippets → rollup.

**Honest caveats (in-viz):**
- "**Derived, not editorial** — computed from the citation graph + a judge pass, **not** an authoritative citator."
- "Judge input snippets are **transient — never stored** (P3). The stored row is a rollup (`derived_method='citation_graph+judge'`) with a 30-day TTL and a bounded judge budget."

**Verify-in-source links:** `api/app/citation/treatment.py`; `docs/adr/0019-transparent-validity-treatment-layer.md`.

- [ ] **Step 1: Read the grounding sources** (`treatment.py`, ADR 0019). Note the three signal values, `derived_method`, TTL, and the never-stored-snippets rule.
- [ ] **Step 2: Build the playground** (playground skill + shared shell): case picker, derived rollup, citing-case signal rows with trace links, two-pass derivation, caveat panel.
- [ ] **Step 3: Self-check** against the 7 shared criteria + the 2 caveats. Confirm signals read followed/distinguished/criticized; "derived not editorial" is prominent; no network calls.
- [ ] **Step 4: Commit**

```bash
git add web/static/learn/playgrounds/treatment-layer.html
git commit -s -m "feat(DE-365 sub-2): treatment-layer Learn playground

Refs DE-365"
```

---

### Task 5: `matter-session-flow` playground (capstone)

**Files:**
- Create: `web/static/learn/playgrounds/matter-session-flow.html`

**Grounding:**
- `api/app/autonomous/planner.py` — the `plan → act → observe → replan` loop; the planner proposes a closed-set `ToolIntent` from the current phase's `PHASE_GRANTS` allowlist + a one-line rationale; an out-of-allowlist proposal is **rejected, not executed** (ADR 0015).
- `api/app/autonomous/guard.py` — `guarded_tool_call` enforces brakes **in order R5 → R6 → R4**: R5 temporal (halt if `halt_requested`), R6 contextual (intent must be within the phase grant), R4 economic (projected spend under `max_cost_usd`, default **$5**, always armed). Plus a **per-phase step cap** (the one new bound; no new brake class).
- `docs/adr/0020-governed-agentic-legal-matter-sessions.md`.

**Core interaction:** a **step-walkthrough with brake toggles** (kin: `governed-tool-flow.html` / `autonomous-flow.html`). Walk the loop station-by-station (plan → act → observe → replan, over a couple of iterations). Provide toggles for R5 (temporal halt), R6 (phase grant), R4 ($5 economic cap), and the step cap. Flipping a brake off shows the session **halt honestly** at the correct chokepoint with a **partial, traceable result** — never a fabricated completion. Show the planner choosing among closed-set ToolIntents (and an out-of-set proposal being rejected).

**Honest caveats (in-viz):**
- "Backend shipped; **no dedicated matter-intake UI yet** — this capability reuses the autonomous session UI."
- "An **out-of-allowlist planner proposal is rejected, not executed** (ADR 0015). The model chooses which governed tool and when — never invents one."

**Brakes must be labeled and ordered R5 → R6 → R4.**

**Verify-in-source links:** `api/app/autonomous/planner.py`; `api/app/autonomous/guard.py`; `docs/adr/0020-governed-agentic-legal-matter-sessions.md`.

- [ ] **Step 1: Read the grounding sources** (`planner.py`, `guard.py`, ADR 0020). Confirm brake order R5→R6→R4, the $5 default cap, the step cap, and the closed-set rejection rule.
- [ ] **Step 2: Build the playground** (playground skill + shared shell): the plan/act/observe/replan walkthrough, the four brake toggles, honest halt states, closed-set planner selection, caveat panel.
- [ ] **Step 3: Self-check** against the 7 shared criteria + the 2 caveats. Confirm each brake toggle halts at the right station in R5→R6→R4 order; a halt yields a partial+traceable result; no network calls.
- [ ] **Step 4: Commit**

```bash
git add web/static/learn/playgrounds/matter-session-flow.html
git commit -s -m "feat(DE-365 sub-2): matter-session-flow Learn playground

Refs DE-365"
```

---

### Task 6: Wire the cluster into the how-page

**Files:**
- Modify: `web/src/routes/lq-ai/learn/how/+page.svelte`

**Depends on:** Tasks 1–5 (all 5 slugs must exist).

**Interfaces consumed:** the 5 runtime URLs `/learn/playgrounds/{authority-sources,citation-ledger,fiduciary-gate,treatment-layer,matter-session-flow}.html`.

Add a cluster after section 17 (`governed-tool-flow`, the last existing section, ending near line 880). Each new section copies the existing per-section markup shape exactly (see sections 1–17): `<section class="lq-how-section" data-testid="lq-ai-learn-how-section-<slug>">`, an `<h2 class="lq-section-h">N. <title></h2>`, a `<p class="lq-text-body">` framing paragraph, a **second `<p class="lq-text-body">` honest-state paragraph** styled like the anonymization/intake ones (`style="font-size: 13px; color: var(--lq-text-secondary);"` with a `<strong>Honest state:</strong>` lead) carrying the caveat, the `.lq-playground-wrap` > `<iframe ... data-testid="learn-playground-<slug>">`, and the `.lq-playground-foot` with the "Open full-screen ↗" link + source refs.

Section numbering and titles:
- **Cluster divider** (an `lq-transition` paragraph before section 18): frame the fiduciary-grade loop — how these 5 build on the governed boundary (section 17): what the boundary retrieves → where it's recorded → how it's verified → what's derived → the session that orchestrates it.
- **18. Where authority comes from: the content-source registry** → `authority-sources`
- **19. The record of what was read: the Citation Ledger** → `citation-ledger`
- **20. Derive, don't assert: the fiduciary-grade gate** → `fiduciary-gate`
- **21. Is it still good law? the derived treatment layer** → `treatment-layer`
- **22. Putting it together: a governed agentic matter session** → `matter-session-flow`

Each section's honest-state paragraph carries the caveat from its playground task (EUR-Lex get-by-CELEX / id+offset only / DE-370-371 parity / derived-not-editorial / no-matter-intake-UI) and links every source ref to the same real paths the playground uses.

- [ ] **Step 1: Read** `web/src/routes/lq-ai/learn/how/+page.svelte` fully; copy the exact section markup shape from an existing section (e.g. section 6 anonymization, which has the honest-state paragraph pattern).
- [ ] **Step 2: Fix the stale intro.** In the header `<p class="lq-text-body lq-page-intro">`, change "Sixteen interactive surfaces" → "Twenty-two interactive surfaces" (17 existing + 5 new). Update the count sentence accordingly. Update the leading `<!-- ... -->` comment block to add the fiduciary-grade cluster to the narrative-order inventory.
- [ ] **Step 3: Add the cluster divider + sections 18–22** after section 17, each with heading, framing paragraph, honest-state paragraph, iframe (`height: 900px`, matching existing inline style), full-screen link, and source refs.
- [ ] **Step 4: Format + lint.**

```bash
cd web && npx prettier --write src/routes/lq-ai/learn/how/+page.svelte && npx eslint src/routes/lq-ai/learn/how/+page.svelte
```
Expected: Prettier reformats if needed; ESLint passes with no errors.

- [ ] **Step 5: Verify counts.**

```bash
cd /Users/kevinkeller/Code/lq-ai
grep -c 'data-testid="lq-ai-learn-how-section-' web/src/routes/lq-ai/learn/how/+page.svelte   # expect 22
grep -c '<iframe' web/src/routes/lq-ai/learn/how/+page.svelte                                  # expect 22
```
Expected: both print `22`.

- [ ] **Step 6: Commit**

```bash
git add web/src/routes/lq-ai/learn/how/+page.svelte
git commit -s -m "feat(DE-365 sub-2): wire fiduciary-grade playground cluster into learn/how

Adds sections 18-22 (authority-sources, citation-ledger, fiduciary-gate,
treatment-layer, matter-session-flow) as a labeled cluster after the
governed tool boundary; fixes the stale surface count.

Refs DE-365"
```

---

### Task 7: Rebuild-web verification + donna-sync update

**Files:**
- Modify: `docs/LQVern/donna-sync-2026-07-02.md`

**Depends on:** Tasks 1–6.

- [ ] **Step 1: Rebuild the `web` container** (pre-built static bundle — no HMR) so the new static playgrounds + the Svelte edit are served.

```bash
cd /Users/kevinkeller/Code/lq-ai
docker compose build web && docker compose up -d web
```
(Do NOT `docker compose down -v`. Rebuild only the `web` service.)

- [ ] **Step 2: Eyeball verification.** Load `/lq-ai/learn/how` in a browser. Confirm: the cluster divider renders; all 22 iframes load; each of the 5 new playgrounds' core interaction works (toggles/steps/clicks); each honest caveat is visible; every "Verify in source" link resolves to a real path on `main`; no console errors; no network requests from the playgrounds. Also open each of the 5 at `/learn/playgrounds/<slug>.html` full-screen.
- [ ] **Step 3: Update `docs/LQVern/donna-sync-2026-07-02.md`.** In §2 bump "19 live playgrounds" → 24 and add the 5 slugs to the full-set list; remove the §2 "coverage gap" ⚠️ callout (now closed). In §3, move the 5 from "Planned — NOT YET BUILT" to available, with their final slugs and `/learn/playgrounds/<slug>.html` URLs and their how-page section numbers; update the recommendation line (Donna may now link them). Keep it honest — these are illustrative viz, the caveats still live in §1.
- [ ] **Step 4: Commit**

```bash
git add docs/LQVern/donna-sync-2026-07-02.md
git commit -s -m "docs(DE-365 sub-2): mark fiduciary-grade playgrounds available in donna-sync

Moves the 5 playgrounds from planned to available with final slugs/URLs;
closes the §2 coverage-gap callout.

Refs DE-365"
```

---

## Self-Review

**Spec coverage:**
- Spec §4 five playgrounds → Tasks 1–5. ✓
- Spec §5 how-page wiring (cluster divider, sections 18–22, testids, stale-count fix) → Task 6. ✓
- Spec §6 honesty posture (inline caveats, verify-in-source, vendor-neutral, no-network disclaimer) → Global Constraints + per-task caveats + acceptance criteria. ✓
- Spec §7 verification (rebuild web, no api coupling, Prettier/ESLint, e2e if present) → Task 6 Step 4/5 + Task 7 Steps 1–2. (No e2e test asserts the count — verified during planning — so none to update.) ✓
- Spec §8 process (branch first, mirror, donna-sync update) → branch already created; donna-sync → Task 7; mirror origin→tucuxi happens at ship time (subagent-driven-development / finishing-a-development-branch), not a plan task. ✓
- Spec §3 shared shell → "Shared shell reference" + Global Constraints. ✓

**Placeholder scan:** no TBD/TODO; each task names exact files, exact grounding sources, exact caveat text, exact verify links, exact commands. The playground *visual* code is intentionally authored by the playground skill per task (not pre-written here) — the acceptance criteria + grounding + caveats fully constrain it. ✓

**Type/name consistency:** slugs are identical across Tasks 1–5, Task 6 (iframe src + testids), and Task 7 (donna-sync). Gate tiers PASS/SUPPORTED/FAIL and brake order R5→R6→R4 are stated identically in the spec, Global Constraints, and Tasks 3/5. Counts: 17 existing → 22 total, stated consistently in Task 6 Steps 2/5 and Task 7 Step 3 (19→24 playground files). ✓
