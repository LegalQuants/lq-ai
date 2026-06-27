# WS-G PR1-UI — Treatment signal in the Citation Ledger trace — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Render the citation-graph treatment signal (cited-by count + capped citing list) on caselaw entries in the C1 one-click trace — as neutral provenance, never a "good law" verdict.

**Architecture:** Add the `LedgerTreatment` types (the API already returns the data), a pure Vitest-tested `treatment-display.ts` helper, and a compact "Cited by N · derived <date>" line + disclosure in `LedgerEntryRow.svelte` with local, token-driven CSS. No backend, no panel change.

**Tech Stack:** SvelteKit (OpenWebUI fork), TypeScript, Vitest, svelte-check. No new dependency.

## Global Constraints

- **Web-only, NOT security-gated.** Touch only `web/**`. Self-merge after CI.
- **Anti-overclaiming (ADR 0019 D1):** the treatment line is **neutral/muted — no green/red validity coloring**, carries the word "derived", and a `title`/`aria-label` stating it is *not* an editorial verdict. The capped microcopy ("N most recent of TOTAL") must show when the stored list is a subset. No "good law"/"bad law" text anywhere.
- **Logic in the pure helper; thin `.svelte`.** All formatting in `treatment-display.ts` (Vitest-tested). The component is render-only (svelte-check only — the repo has NO Svelte component-test harness).
- **Local CSS only** (P1-C1 lesson): define every class in the component's own `<style>` with `--lq-*` tokens; never depend on another component's scoped classes.
- **Null/absent treatment → render nothing.** Non-caselaw entries and entries with `treatment` null/undefined show no treatment UI.
- **Gates:** `npm run check:lq-ai` (svelte-check) + `npm run test:frontend` (Vitest) must pass. **Format only touched files** — do NOT run repo-wide `npm run format` (it rewrites 161 unrelated files).
- **Commits:** `git commit -s` + `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`.

---

### Task 1: Types + pure `treatment-display` helper (+ Vitest)

**Files:**
- Modify: `web/src/lib/lq-ai/types.ts` (add `LedgerCitingRef`, `LedgerTreatment`; add `treatment?` to `LedgerEntry`)
- Create: `web/src/lib/lq-ai/citations/treatment-display.ts`
- Create: `web/src/lib/lq-ai/__tests__/treatment-display.test.ts`

**Interfaces:**
- Produces:
  ```ts
  interface LedgerCitingRef { cluster_id?: number|null; opinion_id?: number|null; case_name?: string|null; court?: string|null; date_filed?: string|null; }
  interface LedgerTreatment { cited_by_count: number; as_of: string; derived_method: string; citing: LedgerCitingRef[]; }
  interface TreatmentSummary { label: string; asOf: string; preview: LedgerCitingRef[]; moreCount: number; capped: boolean; total: number; shown: number; }
  function treatmentSummary(t: LedgerTreatment): TreatmentSummary
  function formatCitingRef(ref: LedgerCitingRef): string
  ```

- [ ] **Step 1: Write the failing tests**

Create `web/src/lib/lq-ai/__tests__/treatment-display.test.ts`:

```ts
import { describe, expect, it } from 'vitest';
import { treatmentSummary, formatCitingRef } from '../citations/treatment-display';
import type { LedgerTreatment, LedgerCitingRef } from '../types';

function ref(o: Partial<LedgerCitingRef> = {}): LedgerCitingRef {
	return { cluster_id: 1, opinion_id: 2, case_name: 'Allen v. Wright', court: 'scotus', date_filed: '1984-07-03', ...o };
}
function treatment(o: Partial<LedgerTreatment> = {}): LedgerTreatment {
	return { cited_by_count: 412, as_of: '2026-06-26T12:00:00+00:00', derived_method: 'citation_graph', citing: Array.from({ length: 30 }, (_, i) => ref({ case_name: `Case ${i}` })), ...o };
}

describe('treatmentSummary', () => {
	it('labels plural count and slices the preview to 5', () => {
		const s = treatmentSummary(treatment());
		expect(s.label).toBe('Cited by 412 later opinions');
		expect(s.asOf).toBe('2026-06-26');
		expect(s.preview).toHaveLength(5);
		expect(s.moreCount).toBe(25);
		expect(s.shown).toBe(30);
		expect(s.total).toBe(412);
		expect(s.capped).toBe(true); // 412 > 30
	});

	it('singularizes a count of 1', () => {
		const s = treatmentSummary(treatment({ cited_by_count: 1, citing: [ref()] }));
		expect(s.label).toBe('Cited by 1 later opinion');
		expect(s.capped).toBe(false); // 1 == 1
		expect(s.moreCount).toBe(0);
	});

	it('handles an empty citing list', () => {
		const s = treatmentSummary(treatment({ cited_by_count: 7, citing: [] }));
		expect(s.preview).toEqual([]);
		expect(s.moreCount).toBe(0);
		expect(s.shown).toBe(0);
		expect(s.capped).toBe(true); // 7 > 0
	});

	it('falls back to citing.length when cited_by_count is missing/NaN', () => {
		// @ts-expect-error simulate a malformed payload
		const s = treatmentSummary(treatment({ cited_by_count: undefined, citing: [ref(), ref()] }));
		expect(s.label).toBe('Cited by 2 later opinions');
		expect(s.total).toBe(2);
		expect(s.capped).toBe(false);
	});

	it('is not capped when count equals the stored list length', () => {
		const s = treatmentSummary(treatment({ cited_by_count: 3, citing: [ref(), ref(), ref()] }));
		expect(s.capped).toBe(false);
		expect(s.moreCount).toBe(0); // 3 - 3
	});
});

describe('formatCitingRef', () => {
	it('joins present fields with commas', () => {
		expect(formatCitingRef(ref({ case_name: 'Roe v. Wade', court: 'scotus', date_filed: '1973-01-22' }))).toBe('Roe v. Wade, scotus, 1973-01-22');
	});
	it('omits missing fields without stray commas', () => {
		expect(formatCitingRef({ case_name: 'X v. Y', court: null, date_filed: undefined })).toBe('X v. Y');
		expect(formatCitingRef({ case_name: 'X v. Y', court: 'ca9' })).toBe('X v. Y, ca9');
	});
	it('returns empty string when all fields missing', () => {
		expect(formatCitingRef({})).toBe('');
	});
});
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd web && npx vitest run src/lib/lq-ai/__tests__/treatment-display.test.ts`
Expected: FAIL — cannot resolve `../citations/treatment-display`.

- [ ] **Step 3: Add the types**

In `web/src/lib/lq-ai/types.ts`, immediately before `export interface LedgerEntry {`:

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
	as_of: string;
	derived_method: string;
	citing: LedgerCitingRef[];
}
```

In `LedgerEntry`, after the `treatment_id: string | null;` line, add:

```ts
	treatment?: LedgerTreatment | null;
```

- [ ] **Step 4: Implement the helper**

Create `web/src/lib/lq-ai/citations/treatment-display.ts`:

```ts
/**
 * Pure formatting for the WS-G citation-graph treatment signal (PR1-UI).
 *
 * Graph-only provenance ("cited by N later opinions; here are the most recent
 * few") — NOT an editorial validity verdict (ADR 0019 D1). Treatment
 * classification + any severity coloring arrive with WS-G PR2.
 */
import type { LedgerCitingRef, LedgerTreatment } from '../types';

export const PREVIEW_N = 5;

export interface TreatmentSummary {
	label: string;
	asOf: string;
	preview: LedgerCitingRef[];
	moreCount: number;
	capped: boolean;
	total: number;
	shown: number;
}

export function treatmentSummary(t: LedgerTreatment): TreatmentSummary {
	const citing = Array.isArray(t.citing) ? t.citing : [];
	const shown = citing.length;
	const total =
		typeof t.cited_by_count === 'number' && !Number.isNaN(t.cited_by_count) ? t.cited_by_count : shown;
	const preview = citing.slice(0, PREVIEW_N);
	return {
		label: `Cited by ${total} later opinion${total === 1 ? '' : 's'}`,
		asOf: formatAsOf(t.as_of),
		preview,
		moreCount: shown - preview.length,
		capped: total > shown,
		total,
		shown
	};
}

function formatAsOf(as_of: string): string {
	// Stable, locale-independent date portion of the ISO timestamp.
	if (typeof as_of === 'string' && /^\d{4}-\d{2}-\d{2}/.test(as_of)) return as_of.slice(0, 10);
	return as_of ?? '';
}

export function formatCitingRef(ref: LedgerCitingRef): string {
	return [ref.case_name, ref.court, ref.date_filed].filter((p) => p != null && p !== '').join(', ');
}
```

- [ ] **Step 5: Run to verify pass + svelte-check**

Run: `cd web && npx vitest run src/lib/lq-ai/__tests__/treatment-display.test.ts && npm run check:lq-ai`
Expected: Vitest PASS; svelte-check clean (the new types resolve).

- [ ] **Step 6: Format touched files + commit**

```bash
cd web && npx prettier --write src/lib/lq-ai/types.ts src/lib/lq-ai/citations/treatment-display.ts src/lib/lq-ai/__tests__/treatment-display.test.ts
git add web/src/lib/lq-ai/types.ts web/src/lib/lq-ai/citations/treatment-display.ts web/src/lib/lq-ai/__tests__/treatment-display.test.ts
git commit -s -m "feat(web): LedgerTreatment types + treatment-display helper (WS-G PR1-UI)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: Render the treatment line + disclosure in `LedgerEntryRow.svelte`

**Files:**
- Modify: `web/src/lib/lq-ai/components/LedgerEntryRow.svelte`

**Interfaces:**
- Consumes: `treatmentSummary`, `formatCitingRef` (Task 1); `entry.treatment` (Task 1 type).

- [ ] **Step 1: Add imports + local state**

In the `<script>` block of `LedgerEntryRow.svelte`, after the existing imports add:

```ts
	import { treatmentSummary, formatCitingRef } from '../citations/treatment-display';
```

After `$: src = entry.source;` add:

```ts
	let treatmentOpen = false;
```

- [ ] **Step 2: Add the render block**

Immediately after the closing `{/if}` of the passages block (the `{#if src.passages...}{:else}...{/if}`) and before the closing `</li>`, add:

```svelte
	{#if entry.treatment}
		{@const t = treatmentSummary(entry.treatment)}
		<div class="lq-ledger-treatment">
			<button
				type="button"
				class="lq-ledger-treatment-line"
				aria-expanded={treatmentOpen}
				aria-label="Citation-graph treatment, derived — not an editorial good-law judgment"
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

- [ ] **Step 3: Add local CSS**

In the component's `<style>` block (append after the existing rules), add — **token-driven, no state coloring**:

```css
	.lq-ledger-treatment {
		display: flex;
		flex-direction: column;
		gap: var(--lq-space-1);
	}
	.lq-ledger-treatment-line {
		display: inline-flex;
		align-items: center;
		gap: 6px;
		align-self: flex-start;
		padding: 0;
		border: none;
		background: transparent;
		font: inherit;
		font-size: 11px;
		color: var(--lq-text-tertiary);
		cursor: pointer;
	}
	.lq-ledger-treatment-line:hover {
		color: var(--lq-text-secondary);
	}
	.lq-ledger-treatment-icon {
		font-size: 12px;
	}
	.lq-ledger-treatment-label {
		font-weight: 500;
	}
	.lq-ledger-treatment-asof {
		color: var(--lq-text-tertiary);
	}
	.lq-ledger-treatment-list {
		list-style: none;
		margin: 0;
		padding: 0 0 0 var(--lq-space-4);
		display: flex;
		flex-direction: column;
		gap: 2px;
		font-size: 11px;
		color: var(--lq-text-tertiary);
	}
	.lq-ledger-treatment-more {
		color: var(--lq-text-tertiary);
		font-style: italic;
	}
```

- [ ] **Step 4: svelte-check**

Run: `cd web && npm run check:lq-ai`
Expected: clean (0 errors). If `--lq-text-secondary` or `--lq-space-4` are not defined tokens in this codebase, substitute the nearest existing token (grep `--lq-text-` / `--lq-space-` in `web/src/`) and note the swap.

- [ ] **Step 5: Format + commit**

```bash
cd web && npx prettier --write src/lib/lq-ai/components/LedgerEntryRow.svelte
git add web/src/lib/lq-ai/components/LedgerEntryRow.svelte
git commit -s -m "feat(web): render citation-graph treatment line + disclosure in the ledger trace (WS-G PR1-UI)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: Gates + visual evidence

**Files:** none (verification; any token/lint fixes land in the owning task's file).

- [ ] **Step 1: Full lq-ai gates**

Run: `cd web && npm run check:lq-ai && npm run test:frontend`
Expected: svelte-check 0 errors; Vitest all pass (incl. the new treatment-display tests). Fix any failure in the owning task's file and re-run.

- [ ] **Step 2: Visual render evidence (headless Chrome)**

Build a throwaway harness that mounts `LedgerEntryRow` with a caselaw entry carrying a `treatment`, render collapsed + expanded, light + dark. Recipe (run from a scratch dir, NOT committed):

```bash
SCRATCH=/private/tmp/claude-501/-Users-kevinkeller-Code-lq-ai/48141084-6384-4b9c-88a1-ebea8ef20a34/scratchpad/wsg-ui
mkdir -p "$SCRATCH"
# Author a minimal Vite + Svelte page that imports the real component with a
# sample entry { source.kind:'caselaw', treatment:{ cited_by_count:412, as_of:'2026-06-26T..', derived_method:'citation_graph', citing:[30 refs] } },
# plus a null-treatment entry, in both light and a .dark wrapper, with the --lq-* token
# CSS vars defined. Build with vite, serve, and screenshot:
"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" --headless=new \
  --screenshot="$SCRATCH/treatment-light.png" --window-size=520,640 "file://$SCRATCH/dist/index.html"
```

Confirm by viewing the screenshots (Read the PNGs): (a) the line renders muted/neutral — **no green or red**; (b) the caret toggles the citing list; (c) the "+25 more · 30 most recent of 412" microcopy shows; (d) the null-treatment entry renders nothing; (e) dark mode is legible. Record the observations in the task report. (If the throwaway-harness build is impractical in this environment, render a static HTML mock of the component's exact markup + the local CSS as the fallback evidence, and say so.)

- [ ] **Step 3: Commit (if any gate fix landed)** — otherwise no commit; the evidence lives in the task report.

---

## Final review (after Task 3)

- [ ] **Opus whole-branch review** vs `main`. Focus: the anti-overclaiming posture holds (no validity coloring; "derived" framing + the not-editorial title; capped microcopy honest); the helper is pure + fully covered; the component is render-only with local CSS (no cross-component scoped-class dependency — the P1-C1 trap); null/non-caselaw treatment renders nothing; no backend/panel change crept in.
- [ ] **Push origin + tucuxi.**
- [ ] **Open the PR** (origin). **NOT security-gated** (web-only) → self-merge after CI green; then mirror `origin/main → tucuxi` and confirm `origin == tucuxi`.

## Self-review against the spec

- **Spec coverage:** Component 1 (types) → Task 1 Step 3; Component 2 (helper) → Task 1; Component 3 (render) → Task 2; Component 4 (local CSS) → Task 2 Step 3; anti-overclaiming → Global Constraints + Task 2 (no coloring, title/aria, capped microcopy); testing (Vitest + visual) → Task 1 + Task 3.
- **Placeholder scan:** the `--lq-text-secondary`/`--lq-space-4` token note and the visual-harness recipe are real verify-and-adapt steps with named fallbacks, not vague placeholders.
- **Type consistency:** `TreatmentSummary { label, asOf, preview, moreCount, capped, total, shown }`, `treatmentSummary(t) -> TreatmentSummary`, `formatCitingRef(ref) -> string`, `PREVIEW_N = 5` — used consistently in the helper, its tests, and the component render (`t.shown`/`t.total` in the microcopy).
