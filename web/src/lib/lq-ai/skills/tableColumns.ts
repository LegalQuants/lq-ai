/**
 * DE-297 — table-mode skill authoring: pure column-spec helpers.
 *
 * Shared by the Skill Creator wizard (`/lq-ai/skills/new` via
 * `SkillWizard.svelte`), the user-skill edit page
 * (`/lq-ai/skills/[id]/edit`), and `ColumnEditor.svelte`. Extracted
 * into a plain `.ts` module (repo convention: page-helpers pattern) so
 * vitest can exercise validation / serialization / reorder without the
 * svelte transformer.
 *
 * Backend parity contract: the backend validates
 * `frontmatter_extra.{output_format, columns}` through
 * `app.skills.schema.LQAIFrontmatter` (see
 * `api/app/api/user_skills.py::_validate_frontmatter_extra`). The
 * validation here mirrors — and never widens — that schema:
 *
 * - `output_format: table` requires >= 1 column
 *   (`_table_mode_requires_columns`);
 * - each column needs a non-empty `name` and `query`
 *   (`ColumnSpec` `min_length=1`);
 * - `minimum_inference_tier` is an integer 1-5 or unset (`ge=1, le=5`);
 * - `ensemble_verification` is boolean or unset (null = inherit the
 *   skill / deployment default).
 */

import type { TabularColumnSpec } from '../types';

export type SkillOutputMode = 'prose' | 'table';

/**
 * One column row as the editor holds it. `null` on the two override
 * fields means "inherit" (the backend's `None`) — distinct from an
 * explicit `false` / tier value, which overrides the skill level.
 */
export interface EditableColumn {
	name: string;
	query: string;
	ensemble_verification: boolean | null;
	minimum_inference_tier: number | null;
}

/** Per-column inline error slots. Absent key = field is valid. */
export interface ColumnFieldErrors {
	name?: string;
	query?: string;
	tier?: string;
}

export interface ColumnsValidation {
	valid: boolean;
	/**
	 * List-level error (currently only the min-one-column rule,
	 * mirroring the backend's `_table_mode_requires_columns`).
	 */
	listError: string | null;
	/** Index-aligned with the input columns. */
	columnErrors: ColumnFieldErrors[];
}

export const MIN_ONE_COLUMN_ERROR =
	'A table-mode skill needs at least one column.';
export const EMPTY_NAME_ERROR = 'Column name is required.';
export const EMPTY_QUERY_ERROR = 'Extraction query is required.';
export const TIER_RANGE_ERROR = 'Tier must be between 1 and 5.';

export function newEditableColumn(): EditableColumn {
	return {
		name: '',
		query: '',
		ensemble_verification: null,
		minimum_inference_tier: null
	};
}

/**
 * Validate the column list against the backend schema rules. Always
 * returns an index-aligned `columnErrors` array so the editor can
 * render inline errors next to the offending field.
 */
export function validateColumns(columns: EditableColumn[]): ColumnsValidation {
	const columnErrors: ColumnFieldErrors[] = columns.map((col) => {
		const errs: ColumnFieldErrors = {};
		if (!col.name.trim()) errs.name = EMPTY_NAME_ERROR;
		if (!col.query.trim()) errs.query = EMPTY_QUERY_ERROR;
		const tier = col.minimum_inference_tier;
		if (tier !== null && (!Number.isInteger(tier) || tier < 1 || tier > 5)) {
			errs.tier = TIER_RANGE_ERROR;
		}
		return errs;
	});
	const listError = columns.length === 0 ? MIN_ONE_COLUMN_ERROR : null;
	const valid =
		listError === null && columnErrors.every((e) => Object.keys(e).length === 0);
	return { valid, listError, columnErrors };
}

/**
 * Serialize editor rows to the backend `ColumnSpec` wire shape.
 * Trims name/query; drops `null` overrides entirely so the persisted
 * spec reads "inherit" the same way built-in SKILL.md frontmatter
 * does (absent key, not `null`).
 */
export function serializeColumns(columns: EditableColumn[]): TabularColumnSpec[] {
	return columns.map((col) => {
		const out: TabularColumnSpec = { name: col.name.trim(), query: col.query.trim() };
		if (col.ensemble_verification !== null) {
			out.ensemble_verification = col.ensemble_verification;
		}
		if (col.minimum_inference_tier !== null) {
			out.minimum_inference_tier = col.minimum_inference_tier;
		}
		return out;
	});
}

/**
 * Move the column at `index` by `delta` (-1 = up, +1 = down).
 * Out-of-range moves return the input array unchanged (same
 * reference), so callers can no-op cheaply on boundary clicks.
 */
export function moveColumn(
	columns: EditableColumn[],
	index: number,
	delta: -1 | 1
): EditableColumn[] {
	const target = index + delta;
	if (index < 0 || index >= columns.length) return columns;
	if (target < 0 || target >= columns.length) return columns;
	const next = [...columns];
	const [moved] = next.splice(index, 1);
	next.splice(target, 0, moved);
	return next;
}

/** Read the authoring mode off a stored `frontmatter_extra` block. */
export function modeFromExtra(extra: Record<string, unknown> | null | undefined): SkillOutputMode {
	return extra && extra['output_format'] === 'table' ? 'table' : 'prose';
}

/**
 * Defensively parse a raw `columns` value (from `frontmatter_extra` or
 * a localStorage draft) into editor rows. Non-array input or rows that
 * are not plain objects yield `null` / get skipped; missing overrides
 * normalize to `null` ("inherit"); non-integer tiers are kept only when
 * they are numbers so validation can flag them rather than silently
 * dropping user data.
 */
export function columnsFromRaw(raw: unknown): EditableColumn[] | null {
	if (!Array.isArray(raw)) return null;
	const out: EditableColumn[] = [];
	for (const entry of raw) {
		if (entry === null || typeof entry !== 'object' || Array.isArray(entry)) continue;
		const rec = entry as Record<string, unknown>;
		out.push({
			name: typeof rec.name === 'string' ? rec.name : '',
			query: typeof rec.query === 'string' ? rec.query : '',
			ensemble_verification:
				typeof rec.ensemble_verification === 'boolean' ? rec.ensemble_verification : null,
			minimum_inference_tier:
				typeof rec.minimum_inference_tier === 'number' ? rec.minimum_inference_tier : null
		});
	}
	return out;
}

/**
 * Build the next `frontmatter_extra` for the chosen mode, preserving
 * unrelated extension keys (jurisdiction, icon, inputs, …).
 *
 * - `table` → sets `output_format: 'table'` + the serialized columns.
 * - `prose` → strips `columns`, and strips `output_format` only when
 *   it was `'table'` (a hand-set `output_format: 'report'` etc. is not
 *   this surface's key to remove).
 */
export function buildFrontmatterExtra(
	prev: Record<string, unknown> | null | undefined,
	mode: SkillOutputMode,
	columns: EditableColumn[]
): Record<string, unknown> {
	const base: Record<string, unknown> = { ...(prev ?? {}) };
	if (mode === 'table') {
		base['output_format'] = 'table';
		base['columns'] = serializeColumns(columns);
		return base;
	}
	delete base['columns'];
	if (base['output_format'] === 'table') delete base['output_format'];
	return base;
}
