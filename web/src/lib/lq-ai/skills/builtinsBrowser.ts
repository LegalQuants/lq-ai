/**
 * DE-298 — built-ins browser polish on /lq-ai/skills: pure helpers.
 *
 * Three concerns, all deterministic so vitest can cover them without the
 * svelte transformer (repo page-helpers pattern):
 *
 * 1. Output-format chip filter — normalize a row's format ("prose" when
 *    the frontmatter declares none), derive the chip set from the rows
 *    actually present, and round-trip the active chip through the
 *    ``?format=`` URL param.
 * 2. Recently-used sort — order rows by the caller's per-user recents
 *    (``GET /skills/autocomplete`` with empty ``q`` returns the
 *    ``messages.applied_skills`` recents block first, then an
 *    alphabetical fill). Rows absent from that response fall back to
 *    alphabetical-by-title, so never-used skills stay stably ordered.
 * 3. Fork seeding for table-mode skills — extract ``lq_ai.columns``
 *    from a source skill's ``content_yaml`` (the only place built-ins
 *    carry their column spec on the wire) into `EditableColumn` rows so
 *    "Fork to my skills" pre-populates the wizard's column editor
 *    (DE-297 pairing).
 */

import { parse } from 'yaml';

import type { Skill } from '../types';
import { columnsFromRaw, type EditableColumn, type SkillOutputMode } from './tableColumns';

// ---------------------------------------------------------------------------
// 1. Output-format chip filter
// ---------------------------------------------------------------------------

/** Chip value meaning "no filter". */
export const FORMAT_ALL = 'all';

/** Format bucket for rows whose frontmatter declares no output_format. */
export const FORMAT_PROSE = 'prose';

/**
 * Normalize a raw ``output_format`` value into a chip bucket. Absent /
 * blank formats read as "prose" — the skill produces conversational
 * output, which is what an undeclared format means in practice.
 */
export function normalizeFormat(outputFormat: string | null | undefined): string {
	const v = (outputFormat ?? '').trim().toLowerCase();
	return v === '' ? FORMAT_PROSE : v;
}

/**
 * Distinct chip values for the rows on screen, "all" first, the rest
 * alphabetical. Derived from the data rather than hardcoded so corpus
 * formats beyond prose/table (``report``, ``markdown``, …) surface a
 * chip without a code change.
 */
export function formatChips(formats: Array<string | null | undefined>): string[] {
	const distinct = new Set(formats.map(normalizeFormat));
	return [FORMAT_ALL, ...[...distinct].sort((a, b) => a.localeCompare(b))];
}

/**
 * Resolve the ``?format=`` URL param to an active chip. Unknown /
 * absent values fall back to "all" so a stale deep-link (a format that
 * no longer exists in the catalog) degrades to the unfiltered view
 * rather than an empty page.
 */
export function formatFilterFromParam(param: string | null, chips: string[]): string {
	if (param === null) return FORMAT_ALL;
	const normalized = param.trim().toLowerCase();
	return chips.includes(normalized) ? normalized : FORMAT_ALL;
}

/** Does a row with (raw) ``outputFormat`` pass the active chip? */
export function matchesFormat(outputFormat: string | null | undefined, filter: string): boolean {
	return filter === FORMAT_ALL || normalizeFormat(outputFormat) === filter;
}

// ---------------------------------------------------------------------------
// 2. Recently-used sort
// ---------------------------------------------------------------------------

export type SkillSort = 'recent' | 'name';

/** Resolve the ``?sort=`` URL param; anything unrecognised = 'recent'. */
export function sortFromParam(param: string | null): SkillSort {
	return param === 'name' ? 'name' : 'recent';
}

/**
 * Sort rows for the browser. ``sort === 'name'`` is plain
 * alphabetical-by-title. ``sort === 'recent'`` orders by position in
 * ``recentSlugs`` (the autocomplete recents response — most recent
 * first); rows not in that list come after, alphabetical by title, so
 * a brand-new user with no chat activity sees a stable A–Z list.
 *
 * Pure: returns a new array, never mutates the input.
 */
export function sortSkillRows<T>(
	rows: T[],
	sort: SkillSort,
	recentSlugs: string[],
	slugOf: (row: T) => string,
	titleOf: (row: T) => string
): T[] {
	const byTitle = (a: T, b: T) =>
		titleOf(a).toLowerCase().localeCompare(titleOf(b).toLowerCase());
	if (sort === 'name') {
		return [...rows].sort(byTitle);
	}
	const rank = new Map(recentSlugs.map((slug, idx) => [slug, idx]));
	return [...rows].sort((a, b) => {
		const ra = rank.get(slugOf(a)) ?? Number.POSITIVE_INFINITY;
		const rb = rank.get(slugOf(b)) ?? Number.POSITIVE_INFINITY;
		if (ra !== rb) return ra - rb;
		return byTitle(a, b);
	});
}

// ---------------------------------------------------------------------------
// 3. Fork seeding — table-mode columns from content_yaml
// ---------------------------------------------------------------------------

/**
 * Extract the column spec from a skill's frontmatter YAML. Built-ins
 * carry columns at ``lq_ai.columns`` (authoring-guide shape); the
 * synthesized user/team-skill frontmatter re-emits ``frontmatter_extra``
 * under ``lq_ai:`` too, so one path covers both sources. A top-level
 * ``columns:`` key is accepted as a fallback for hand-authored
 * frontmatter that skipped the namespace.
 *
 * Returns ``null`` when the YAML is unparseable or carries no
 * recognisable column list — callers treat that as "no columns to
 * seed", never an error.
 */
export function columnsFromContentYaml(
	contentYaml: string | null | undefined
): EditableColumn[] | null {
	if (!contentYaml) return null;
	let doc: unknown;
	try {
		doc = parse(contentYaml);
	} catch {
		return null;
	}
	if (doc === null || typeof doc !== 'object' || Array.isArray(doc)) return null;
	const root = doc as Record<string, unknown>;
	const lqAi = root['lq_ai'];
	if (lqAi !== null && typeof lqAi === 'object' && !Array.isArray(lqAi)) {
		const nested = columnsFromRaw((lqAi as Record<string, unknown>)['columns']);
		if (nested && nested.length > 0) return nested;
	}
	const topLevel = columnsFromRaw(root['columns']);
	return topLevel && topLevel.length > 0 ? topLevel : null;
}

/** Wizard seed for a fork source's output mode + columns. */
export interface ForkTableSeed {
	outputMode: SkillOutputMode;
	columns: EditableColumn[];
}

/**
 * Build the DE-297 wizard seed from a fork source. Non-table sources
 * (or table sources whose columns can't be recovered from the
 * frontmatter) return ``null`` — the wizard then opens in prose mode
 * exactly as before, so the fork path never regresses on a parse
 * hiccup.
 */
export function forkTableSeed(
	source: Pick<Skill, 'output_format' | 'content_yaml'>
): ForkTableSeed | null {
	if (normalizeFormat(source.output_format) !== 'table') return null;
	const columns = columnsFromContentYaml(source.content_yaml);
	if (!columns) return null;
	return { outputMode: 'table', columns };
}
