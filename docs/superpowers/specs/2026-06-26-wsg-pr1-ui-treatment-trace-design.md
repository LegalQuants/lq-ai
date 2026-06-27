# WS-G PR1-UI — Treatment signal in the Citation Ledger trace (design)

**Date:** 2026-06-26
**Milestone:** Fiduciary-grade agentic legal work — Phase 2 (WS-G)
**Branch:** `feat/wsg-pr1-ui-treatment-trace`
**Pins:** [ADR 0019](../../adr/0019-transparent-validity-treatment-layer.md) — surfaces the **D1** posture (derive-don't-assert; "derived, not editorial") and the **D4 PR1** graph-only signal in the UI. Renders the `treatment` object WS-G PR1 (#233) added to the `/chats/{id}/ledger` read. Extends the P1-C1 trace UI (#228).
**Security review:** **not required** — web-only (`web/**`), no gateway/citation/auth surface. Self-merge after CI (per the workflow: docs/`web/`-only PRs are not gated).

## Problem

WS-G PR1 (#233) derives a citation-graph signal per cited case ("cited by N later opinions; here are the ≤30 most recent") and now returns it as a `treatment` object on each caselaw entry of the `GET /chats/{chat_id}/ledger` read. **Nothing renders it yet** — the backend slice was intentionally backend-only. This slice makes the signal visible in the C1 one-click trace, so a lawyer inspecting a cited case sees how heavily it has been cited and can scan the citing cases — **as provenance, never as a "good law" verdict** (the signal is graph-only; treatment *classification* is PR2).

## Decisions (maintainer-approved 2026-06-26)

- **Web-only, not security-gated.** Touches `web/` only; self-merge after CI.
- **Compact line + disclosure.** A single muted line under the entry's passages — `⚖ Cited by N later opinions · derived <date>` — with an accessible expand toggle that reveals the citing list. Non-caselaw entries and entries whose `treatment` is null (derivation pending) render **nothing** (no clutter, honest interim state).
- **Preview 5 + "+N more".** The disclosed list shows the first 5 stored citing refs (most-recent-first, as stored) then `+N more`; when the stored list is a capped subset of the true total, a microcopy note ("30 most recent of 412") keeps it honest. No further in-trace expansion in PR1.
- **Anti-overclaiming framing (ADR 0019 D1) — load-bearing.** Neutral tone only — muted ⚖ + gray text, **no green/red validity coloring** (color/severity enters only with PR2's real classifications, and even then labeled "derived"). The word "derived" appears in the line; a tooltip/aria-label states it is *not* an editorial verdict. The `capped` microcopy prevents implying the shown subset is the full citing set.
- **Logic in a pure, unit-tested helper; thin `.svelte`.** Formatting lives in `treatment-display.ts` (Vitest), mirroring `ledger-state.ts`. The component is render-only (svelte-check; the repo has no Svelte component-test harness). CSS is defined **locally** with `--lq-*` tokens (the P1-C1 lesson: Svelte scopes `<style>` per component — never depend on another component's scoped classes).

## Design

### Component 1 — Types (`web/src/lib/lq-ai/types.ts`)

Add (next to `LedgerEntry`/`LedgerSource`):

```ts
export interface LedgerCitingRef {
	cluster_id?: number | null;
	opinion_id?: number | null;
	case_name?: string | null;
	court?: string | null;
	date_filed?: string | null;
}
export interface LedgerTreatment {
	cited_by_count: number;
	as_of: string;            // ISO timestamp
	derived_method: string;   // 'citation_graph' in PR1
	citing: LedgerCitingRef[];
}
```

Add to `LedgerEntry`: `treatment?: LedgerTreatment | null;` (optional — older cached responses and non-caselaw entries omit it).

### Component 2 — Pure helper (`web/src/lib/lq-ai/citations/treatment-display.ts`)

```ts
export interface TreatmentSummary {
	label: string;                  // "Cited by 412 later opinions"
	asOf: string;                   // "2026-06-26"
	preview: LedgerCitingRef[];     // citing.slice(0, PREVIEW_N)
	moreCount: number;              // citing.length - preview.length
	capped: boolean;                // cited_by_count > citing.length
	total: number;                  // cited_by_count (for the "of N" microcopy)
	shown: number;                  // citing.length (the stored/retrieved subset size)
}
export function treatmentSummary(t: LedgerTreatment): TreatmentSummary;
export function formatCitingRef(ref: LedgerCitingRef): string;  // "Allen v. Wright, scotus, 1984"
```

- `PREVIEW_N = 5`.
- `label`: `Cited by ${count} later opinion${count === 1 ? '' : 's'}`.
- `asOf`: the date portion of `as_of` (e.g. `as_of.slice(0, 10)` for a stable, locale-independent `YYYY-MM-DD`; a defensive guard returns the raw string if it is not ISO-shaped).
- `formatCitingRef`: join the present-and-nonempty of `case_name`, `court`, `date_filed` with `, ` (so a ref missing a field degrades gracefully — never renders stray commas or "null").
- Total-safety: if `cited_by_count` is missing/NaN, fall back to `citing.length` so the label never shows "Cited by undefined".

### Component 3 — Render (`web/src/lib/lq-ai/components/LedgerEntryRow.svelte`)

After the passages block (the `{#if src.passages...}{:else}...{/if}`), add:

```svelte
{#if entry.treatment}
	{@const t = treatmentSummary(entry.treatment)}
	<div class="lq-ledger-treatment">
		<button
			type="button"
			class="lq-ledger-treatment-line"
			aria-expanded={treatmentOpen}
			title="Derived from the citation graph — not an editorial ‘good law’ judgment. Treatment classification arrives in a later release."
			on:click={() => (treatmentOpen = !treatmentOpen)}
		>
			<span class="lq-ledger-treatment-icon" aria-hidden="true">⚖</span>
			<span class="lq-ledger-treatment-label">{t.label}</span>
			<span class="lq-ledger-treatment-asof">· derived {t.asOf}</span>
			{#if t.preview.length > 0}
				<span class="lq-ledger-treatment-caret" aria-hidden="true">{treatmentOpen ? '▾' : '▸'}</span>
			{/if}
		</button>
		{#if treatmentOpen && t.preview.length > 0}
			<ul class="lq-ledger-treatment-list">
				{#each t.preview as ref}
					<li>{formatCitingRef(ref)}</li>
				{/each}
				{#if t.moreCount > 0}
					<li class="lq-ledger-treatment-more">
						+ {t.moreCount} more{#if t.capped} · {t.shown} most recent of {t.total}{/if}
					</li>
				{/if}
			</ul>
		{/if}
	</div>
{/if}
```

- New local state: `let treatmentOpen = false;` and imports of `treatmentSummary`, `formatCitingRef`.
- A treatment with an empty `citing` (count but no stored refs) shows the line with no caret/list — still useful ("Cited by N").
- "derived, not editorial" is carried by the `title` (and an `aria-label` on the button mirroring it) — no separate visible verdict text.

> **Note on the "of N" microcopy.** The capped note uses the stored list length and the total. The exact wording is fixed in the plan; the requirement is: it must be visible that the shown list is the *most recent subset*, not the full citing set.

### Component 4 — Styling (local, `--lq-*` tokens)

- `.lq-ledger-treatment-line`: an unstyled-button reset (no default button chrome) → looks like a muted inline line; `font-size: 11px`, `color: var(--lq-text-tertiary)`, `cursor: pointer`, a hover that lifts to `var(--lq-text-secondary)`. **No state coloring.**
- `.lq-ledger-treatment-list`: small indented list, `font-size: 11px`, `color: var(--lq-text-tertiary)`.
- Dark mode inherits via the `--lq-*` tokens (no `:global(.dark)` overrides needed since there is no custom color — only token-driven text colors). Confirm in the visual render.

## Testing

Vitest unit (`web/src/lib/lq-ai/__tests__/treatment-display.test.ts`) — the bulk of the value:
- `treatmentSummary`: count label + **pluralization** (1 → "opinion", 412 → "opinions"); `asOf` = date slice; `preview` = first 5; `moreCount` = `citing.length - 5`; `capped` true when `cited_by_count > citing.length`, false when equal; empty `citing` → `preview=[]`, `moreCount=0`; missing `cited_by_count` → falls back to `citing.length` (no "undefined").
- `formatCitingRef`: all fields present → "Name, court, year"; a missing field is omitted with no stray comma; all-missing → empty string (caller still renders an `<li>`, acceptably blank — or guard in the plan).

Gate + visual:
- `npm run check:lq-ai` (svelte-check) + `npm run test:frontend` (Vitest) clean. **Format only the touched files** (not repo-wide `npm run format`).
- **Visual evidence** (the P1-C1 precedent): a throwaway Vite + headless-Chrome render of `LedgerEntryRow` with a caselaw entry carrying a `treatment` — capture **collapsed + expanded**, **light + dark** — and confirm: the line is muted/neutral (no green/red), the caret toggles the list, the "+N more · most recent of N" microcopy shows, and a null-treatment entry renders nothing.

## Out of scope / Deferred

- **Treatment classification** (followed / distinguished / criticized / …) and any **severity coloring** — WS-G PR2 (the judge). Only then does color enter, still "derived."
- **Linking citing cases to CourtListener** — the stored refs carry no URL; constructing one is a later enhancement.
- **A full citing-list detail view** beyond the 5-preview — later.
- **Lazy "deriving…" state** — DE-363 (null treatment renders nothing in PR1-UI; when DE-363 lands it can show a "deriving" affordance).

## Pointers

- Backend that produced the data: `api/app/citation/ledger.py` `resolve_ledger_entries` (the `treatment` object), WS-G PR1 spec `2026-06-26-wsg-pr1-citation-graph-treatment-design.md`.
- Reused patterns: `web/src/lib/lq-ai/citations/ledger-state.ts` (pure helper + Vitest), `web/src/lib/lq-ai/components/LedgerEntryRow.svelte` (the host component; note its local-CSS lesson in the existing comment), `web/src/lib/lq-ai/__tests__/citation-render-state.test.ts` (test style).
