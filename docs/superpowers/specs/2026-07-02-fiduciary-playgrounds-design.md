# Design — DE-365 sub-project 2: Fiduciary-grade Learn playgrounds

**Date:** 2026-07-02
**Owner:** Claude Code (driven), maintainer review
**Tracking:** DE-365 (launch-docs + fiduciary positioning), sub-project 2 of 3
**Branch:** `feat/de365-sub2-fiduciary-playgrounds`
**Status:** Approved design — ready for implementation plan

---

## 1. Problem

The **fiduciary-grade agentic legal work** milestone (Phase 2) is fully merged on `main`, but the Learn tab has **zero** interactive coverage of it. The 19 existing playgrounds stop at the governed tool boundary (CourtListener era); the Citation Ledger / fiduciary gate / authority-source registry / treatment layer / governed matter session have **no visualization**. `docs/HONEST-STATE.md §11` flags this as the known viz gap, and `docs/LQVern/donna-sync-2026-07-02.md §3` records that Donna CC is waiting on final slugs/URLs before it can add fiduciary-grade back-links without 404s.

This sub-project closes that gap: **5 new interactive playgrounds**, wired into the Learn "how it works" page as a labeled cluster, each honest about its real caveat and each linking every claim to canonical source.

## 2. Goals / non-goals

**Goals**
- Build 5 self-contained playgrounds covering authority-sources, citation-ledger, fiduciary-gate, treatment-layer, and matter-session-flow.
- Wire them into `web/src/routes/lq-ai/learn/how/+page.svelte` as a labeled "fiduciary-grade" cluster (sections 18–22) with an arc-framing divider.
- Each viz surfaces its **real caveat** (not just the happy path) and links to the real code/ADR.
- Fix the stale how-page intro ("Sixteen interactive surfaces" → the true count) and its leading inventory comment.

**Non-goals (YAGNI)**
- No changes to the Learn landing or `use` page copy (decided: how-page only).
- No new API endpoints, DB columns, or backend code — this is `web/`-only (static HTML + one Svelte edit).
- No live network calls from any playground — all are illustrative, matching the existing pattern's disclaimer.
- No named competitor anywhere (vendor-neutral, per the DE-365 comparison posture).

## 3. The established pattern (reused verbatim)

Playgrounds are **self-contained single-file HTML** in `web/static/learn/playgrounds/<slug>.html`, served directly by the `web` container at runtime URL `/learn/playgrounds/<slug>.html`. Each reuses:

- The dark CSS-variable theme (`--bg`, `--bg-elev`, `--border`, `--text`, `--text-dim`, `--accent`, status colors) from `governed-tool-flow.html` / `citation-engine-cascade.html`.
- The header: `LQ.AI — <title>` + subtitle + `↩ Learn` link (`href="../../"`) + `View source ↗` link.
- **Verify-in-source** links (`const REPO = 'https://github.com/LegalQuants/lq-ai/blob/main/'`) to the real files/ADRs each claim rests on.
- The standing disclaimer: **"Illustrative walkthrough — this page makes no live network calls."**

Built with the **playground skill** (single-file HTML explorer with controls → live preview). Core interaction is **bespoke per capability** (decided), but the shell is shared.

### Cluster visual identity
The 5 share **one distinct cluster accent** (a fiduciary hue — amber/gold, distinct from the existing blue `--accent`) so they read as one set on the how-page. The shell, layout, and disclaimer are otherwise identical to the existing 19.

## 4. The 5 playgrounds

Order follows the fiduciary loop, picking up exactly where section 17 (governed tool boundary) leaves off: **what the boundary retrieves → where it's recorded → how it's verified → what's derived on top → the session that orchestrates all of it.**

Every honest caveat below is drawn from the actual code (read during design) and `donna-sync-2026-07-02.md` (code-canonical).

### 18 — `authority-sources`
**Covers:** the content-source registry + retrieve-and-verify across the four free sources.
**Core interaction:** a registry explorer. The user toggles **which providers the operator has configured** (CourtListener / GovInfo / SEC EDGAR / EUR-Lex) and watches `resolve_available_sources` join the static `SOURCE_REGISTRY` against live gateway config → each source shows **`enabled=True`** or **`enabled=False` (unavailable-with-reason, never silently omitted)**. Selecting an enabled source shows its jurisdiction / coverage / content-kinds / ops and a retrieve-by-identifier → character-verify sketch.
**Honest caveats (in-viz):**
- **EUR-Lex is `get_authority` (get-by-CELEX) only** — no keyword search (DE-374) or treaty lookup (DE-375). Its `ops` tuple is literally `("get_authority",)`.
- All sources are **operator-config-gated**; a registered type with no configured provider is reported unavailable-with-reason, not hidden.
- The registry exposes **name/type/jurisdiction/coverage/content_kinds/ops only — never auth keys, cost, or secrets** (P3 / ADR 0016).
**Verify-in-source:** ADR 0021, `api/app/research/registry.py` (`SOURCE_REGISTRY`, `resolve_available_sources`).

### 19 — `citation-ledger`
**Covers:** the matter/turn-scoped record of every source + passage the agent actually read, with one-click "trace this claim to its source."
**Core interaction:** a read-trail. The user steps through a turn's ledger entries and clicks a claim to **trace it to its source + character offset**. Provenance-only entries (tool sources with no quote) are shown as **not assertions** — distinct from quote-bearing entries.
**Honest caveat (in-viz):** the ledger references content **by id/offset only — no raw payloads** live in the audit layer (P3). The trace resolves an id+offset, it does not store the quoted text in the ledger.
**Verify-in-source:** ADR 0018, `api/app/citation/ledger.py`.

### 20 — `fiduciary-gate`
**Covers:** derive-don't-assert — the verification cascade's outcome bucketed into a per-message fiduciary verdict.
**Core interaction:** a verdict computer. The user assembles a turn's citations, each carrying a `verification_status`, and watches `compute_and_record_gate` bucket them deterministically:
- **PASS** ← `exact_match`, `tolerant_match`
- **SUPPORTED** ← `paraphrase_judge`, `ensemble_strict`, `ensemble_majority`
- **FAIL** ← `unverified`, `failed`
- **excluded** ← `provenance` (provenance-only entries are not assertions)

The work product is labeled **fiduciary-grade only when every citation is ledger-backed** (ADR 0018 D3). Use the **real verdict tiers PASS / SUPPORTED / FAIL** — not the "flagged" shorthand.
**Honest caveat (in-viz):** **chat vs autonomous verdict-tier parity gaps remain** (DE-370 / DE-371) — the gate runs on both paths but tier handling is not yet identical across them.
**Verify-in-source:** ADR 0018, `api/app/citation/gate.py`.

### 21 — `treatment-layer`
**Covers:** derived case-law treatment signals (followed / distinguished / criticized) with trace to each citing case.
**Core interaction:** a treatment explorer. The user picks a cited case and sees its **derived** treatment rollup plus the citing-case signals that produced it (graph pass + judge pass), each traceable to the citing opinion.
**Honest caveats (in-viz):**
- **"Derived, not editorial"** — a signal computed from the citation graph + a judge pass, **not** an authoritative citator.
- Judge input snippets are **transient — never stored** (P3); the treatment row is a rollup with `derived_method='citation_graph+judge'`; results carry a TTL and a bounded judge budget.
**Verify-in-source:** ADR 0019, `api/app/citation/treatment.py`.

### 22 — `matter-session-flow` (capstone)
**Covers:** the governed agentic matter session that orchestrates 18–21 — plan → act → observe → replan over a closed tool set, under the existing brakes.
**Core interaction:** a step-walkthrough with brake toggles (closest kin: `governed-tool-flow` / `autonomous-flow`). The user walks the loop: the **planner** proposes the next closed-set `ToolIntent` (from the current phase's `PHASE_GRANTS` allowlist) + a one-line rationale; the intent dispatches through the single `guarded_tool_call` chokepoint, which enforces the brakes **in order R5 → R6 → R4**:
- **R5 temporal** — halt if `halt_requested`.
- **R6 contextual** — the intent must be within the current phase's grant.
- **R4 economic** — projected spend must stay under `max_cost_usd` (default **$5**, always armed).

Plus a **per-phase step cap** (the one new bound; no new brake class). Flipping any brake shows the session **halt honestly** with a partial, traceable result — never a fabricated completion.
**Honest caveats (in-viz):**
- Backend shipped; **no dedicated matter-intake UI yet** — the capability reuses the autonomous session UI.
- An out-of-allowlist planner proposal is **rejected, not executed** (ADR 0015 closed set); the model chooses which governed tool and when, never invents one.
**Verify-in-source:** ADR 0020, `api/app/autonomous/planner.py`, `api/app/autonomous/guard.py` (`guarded_tool_call`, R5→R6→R4).

## 5. How-page wiring (`web/src/routes/lq-ai/learn/how/+page.svelte`)

- **Cluster divider:** after section 17, add a `lq-transition` framing paragraph introducing the fiduciary-grade loop (how these 5 build on the governed boundary), then the 5 sections **18–22** in the existing per-section shape: `<h2>` heading, `lq-text-body` framing paragraph **including the honest caveat** (mirroring the M2/anonymization/intake pattern of an explicit "honest state" paragraph), the `<iframe>`, an "Open full-screen ↗" link, and the source-ref links.
- **`data-testid` convention (match existing):** each section `data-testid="lq-ai-learn-how-section-<slug>"`; each iframe `data-testid="learn-playground-<slug>"`.
- **Fix the stale intro:** the header currently reads "Sixteen interactive surfaces" (already wrong — there are 17). Update the count to the true post-merge total (**22**) and refresh the leading `<!-- ... -->` inventory comment to list the new cluster.
- Iframe styling copies the existing inline style (`width:100%; height:900px; border; border-radius`).

## 6. Honesty posture (the core constraint)

Per CLAUDE.md §4 (don't overclaim) and the DE-365 "honest but unflinching" posture:
- Every viz surfaces its **real caveat inline**, and the how-page framing paragraph repeats it.
- Every claim links to the **canonical source** (ADR + code file on `main`).
- No named competitor anywhere (vendor-neutral).
- All 5 keep the **"makes no live network calls"** disclaimer — they are illustrative, using synthetic/static data, exactly like the existing 19.

## 7. Verification

- **Rebuild `web`** (the container serves a pre-built static bundle — no HMR) and eyeball the how-page: the cluster divider renders, all 5 iframes load, each viz's core interaction works, each caveat is visible, and every verify-in-source link resolves to a real path on `main`.
- **No api test coupling:** these are `web/`-only static files + one Svelte edit. No new API routes → the `IMPLEMENTED_ROUTES` / `EXPECTED_PATHS` / OpenAPI collision guards do **not** apply and must not be touched.
- Run **Prettier + ESLint** on the Svelte edit (CI runs them as separate gates).
- If the repo has a Playwright/e2e assertion on the how-page section count or testids, update it to include the 5 new sections.

## 8. Process

1. **Branch first** (done): `feat/de365-sub2-fiduciary-playgrounds` — spec + plan commit here, never on `main`.
2. This spec → self-review → user-review gate.
3. `writing-plans` → implementation plan.
4. `subagent-driven-development`: **one subagent per playground** (5 clean, independent units) via the playground skill, each: build → spec-compliance review → code-quality review → fix; then the how-page wiring as a 6th unit.
5. Rebuild-web verify (§7).
6. Normal review + merge (**not** security-gated — no `gateway/**`, no citation *code*, no CI/auth changes).
7. Mirror `origin` → `tucuxi` (kept identical on `main`).
8. **Update `docs/LQVern/donna-sync-2026-07-02.md §3`** — move the 5 from "planned" to "available" with final slugs/URLs so Donna's back-links resolve.

## 9. Risks / open items

- **Accuracy drift:** each playground's content must match the actual code, not the design summary. Mitigation: the building subagent reads the real module (`registry.py`, `ledger.py`, `gate.py`, `treatment.py`, `planner.py`/`guard.py`) before authoring viz content — the design already corrected one drift (gate tiers are PASS/SUPPORTED/FAIL, not "flagged").
- **Step-cap specifics** (value, tunability) for viz 22 are fixed in the WS-D PR1 code, not this design — the subagent reads them from source rather than inventing.
- **Cluster accent** is a deliberate aesthetic choice (amber/gold); if it clashes with the existing palette in-context, fall back to the shared blue `--accent`.
