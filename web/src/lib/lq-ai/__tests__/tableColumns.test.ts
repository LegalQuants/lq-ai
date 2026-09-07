/**
 * DE-297 — unit tests for the table-mode column helpers.
 *
 * These helpers carry the backend-parity contract for skill authoring:
 * validation mirrors `app.skills.schema.LQAIFrontmatter` /
 * `ColumnSpec` (min one column for table mode, non-empty name + query,
 * tier 1-5), and serialization produces exactly the
 * `frontmatter_extra.{output_format, columns}` shape
 * `POST /api/v1/user-skills` validates and the tabular resolver
 * hydrates.
 */
import { describe, expect, it } from 'vitest';

import {
	EMPTY_NAME_ERROR,
	EMPTY_QUERY_ERROR,
	MIN_ONE_COLUMN_ERROR,
	TIER_RANGE_ERROR,
	buildFrontmatterExtra,
	columnsFromRaw,
	modeFromExtra,
	moveColumn,
	newEditableColumn,
	serializeColumns,
	validateColumns,
	type EditableColumn
} from '../skills/tableColumns';

function col(overrides: Partial<EditableColumn> = {}): EditableColumn {
	return {
		name: 'Term',
		query: 'What is the term of this agreement?',
		ensemble_verification: null,
		minimum_inference_tier: null,
		...overrides
	};
}

describe('validateColumns', () => {
	it('accepts a well-formed single column', () => {
		const v = validateColumns([col()]);
		expect(v.valid).toBe(true);
		expect(v.listError).toBeNull();
		expect(v.columnErrors).toEqual([{}]);
	});

	it('rejects an empty list (backend _table_mode_requires_columns parity)', () => {
		const v = validateColumns([]);
		expect(v.valid).toBe(false);
		expect(v.listError).toBe(MIN_ONE_COLUMN_ERROR);
	});

	it('flags an empty query inline on the offending column only', () => {
		const v = validateColumns([col(), col({ query: '   ' })]);
		expect(v.valid).toBe(false);
		expect(v.columnErrors[0]).toEqual({});
		expect(v.columnErrors[1].query).toBe(EMPTY_QUERY_ERROR);
	});

	it('flags an empty name', () => {
		const v = validateColumns([col({ name: '' })]);
		expect(v.valid).toBe(false);
		expect(v.columnErrors[0].name).toBe(EMPTY_NAME_ERROR);
	});

	it('rejects tiers outside 1-5 and non-integer tiers', () => {
		for (const tier of [0, 6, 2.5]) {
			const v = validateColumns([col({ minimum_inference_tier: tier })]);
			expect(v.valid).toBe(false);
			expect(v.columnErrors[0].tier).toBe(TIER_RANGE_ERROR);
		}
	});

	it('accepts every in-range tier and null (inherit)', () => {
		for (const tier of [1, 2, 3, 4, 5, null]) {
			expect(validateColumns([col({ minimum_inference_tier: tier })]).valid).toBe(true);
		}
	});
});

describe('serializeColumns', () => {
	it('trims name and query', () => {
		const [c] = serializeColumns([col({ name: '  Term  ', query: '  q  ' })]);
		expect(c).toEqual({ name: 'Term', query: 'q' });
	});

	it('drops null overrides (absent key = inherit, matching SKILL.md frontmatter)', () => {
		const [c] = serializeColumns([col()]);
		expect('ensemble_verification' in c).toBe(false);
		expect('minimum_inference_tier' in c).toBe(false);
	});

	it('keeps explicit overrides, including false', () => {
		const [c] = serializeColumns([
			col({ ensemble_verification: false, minimum_inference_tier: 4 })
		]);
		expect(c.ensemble_verification).toBe(false);
		expect(c.minimum_inference_tier).toBe(4);
	});
});

describe('moveColumn', () => {
	const three = [col({ name: 'A' }), col({ name: 'B' }), col({ name: 'C' })];

	it('moves a column up', () => {
		expect(moveColumn(three, 1, -1).map((c) => c.name)).toEqual(['B', 'A', 'C']);
	});

	it('moves a column down', () => {
		expect(moveColumn(three, 1, 1).map((c) => c.name)).toEqual(['A', 'C', 'B']);
	});

	it('returns the same reference on boundary moves (no-op)', () => {
		expect(moveColumn(three, 0, -1)).toBe(three);
		expect(moveColumn(three, 2, 1)).toBe(three);
	});

	it('does not mutate the input array', () => {
		const before = three.map((c) => c.name);
		moveColumn(three, 0, 1);
		expect(three.map((c) => c.name)).toEqual(before);
	});
});

describe('modeFromExtra', () => {
	it('reads table mode', () => {
		expect(modeFromExtra({ output_format: 'table' })).toBe('table');
	});

	it('treats anything else as prose', () => {
		expect(modeFromExtra({ output_format: 'report' })).toBe('prose');
		expect(modeFromExtra({})).toBe('prose');
		expect(modeFromExtra(null)).toBe('prose');
		expect(modeFromExtra(undefined)).toBe('prose');
	});
});

describe('columnsFromRaw', () => {
	it('parses a persisted columns array, normalizing missing overrides to null', () => {
		const parsed = columnsFromRaw([
			{ name: 'Term', query: 'q' },
			{ name: 'Law', query: 'q2', ensemble_verification: true, minimum_inference_tier: 4 }
		]);
		expect(parsed).toEqual([
			{ name: 'Term', query: 'q', ensemble_verification: null, minimum_inference_tier: null },
			{ name: 'Law', query: 'q2', ensemble_verification: true, minimum_inference_tier: 4 }
		]);
	});

	it('returns null for non-array input', () => {
		expect(columnsFromRaw(undefined)).toBeNull();
		expect(columnsFromRaw('columns')).toBeNull();
		expect(columnsFromRaw({ name: 'x' })).toBeNull();
	});

	it('skips non-object rows and tolerates wrong-typed fields', () => {
		const parsed = columnsFromRaw([
			'junk',
			null,
			{ name: 42, query: ['not a string'], minimum_inference_tier: 'four' }
		]);
		expect(parsed).toEqual([
			{ name: '', query: '', ensemble_verification: null, minimum_inference_tier: null }
		]);
	});

	it('round-trips serializeColumns output', () => {
		const original = [col({ ensemble_verification: true, minimum_inference_tier: 2 })];
		expect(columnsFromRaw(serializeColumns(original))).toEqual(original);
	});
});

describe('buildFrontmatterExtra', () => {
	it('sets output_format + columns for table mode, preserving unrelated keys', () => {
		const extra = buildFrontmatterExtra({ jurisdiction: 'us' }, 'table', [col()]);
		expect(extra.jurisdiction).toBe('us');
		expect(extra.output_format).toBe('table');
		expect(extra.columns).toEqual(serializeColumns([col()]));
	});

	it('strips table keys when switching back to prose', () => {
		const prev = { output_format: 'table', columns: [{ name: 'x', query: 'y' }], icon: 'i' };
		expect(buildFrontmatterExtra(prev, 'prose', [])).toEqual({ icon: 'i' });
	});

	it('leaves a hand-set non-table output_format alone in prose mode', () => {
		const prev = { output_format: 'report' };
		expect(buildFrontmatterExtra(prev, 'prose', [])).toEqual({ output_format: 'report' });
	});

	it('does not mutate the previous extra object', () => {
		const prev: Record<string, unknown> = { output_format: 'table', columns: [] };
		buildFrontmatterExtra(prev, 'prose', []);
		expect(prev).toEqual({ output_format: 'table', columns: [] });
	});

	it('is idempotent for an unchanged prose skill (no spurious PATCH diff)', () => {
		const prev = { jurisdiction: 'us' };
		expect(JSON.stringify(buildFrontmatterExtra(prev, 'prose', [newEditableColumn()]))).toBe(
			JSON.stringify(prev)
		);
	});
});
