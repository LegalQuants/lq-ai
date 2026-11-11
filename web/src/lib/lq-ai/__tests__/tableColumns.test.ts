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
	normalizeColumnEnsemble,
	normalizeColumnTier,
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

	it.each(['Term', ' term ', 'TERM'])(
		'rejects duplicate column names after trim/case normalization: %s',
		(name) => {
			const result = validateColumns([col(), col({ name }), col({ name: 'Law' })]);
			expect(result.valid).toBe(false);
			expect(result.columnErrors).toEqual([
				{},
				{ name: `Duplicate column name: ${name.trim()}.` },
				{}
			]);
		}
	);

	it('allows distinct names and keeps required-name errors for blank names', () => {
		expect(validateColumns([col(), col({ name: 'Termination' })]).valid).toBe(true);
		const result = validateColumns([col({ name: '' }), col({ name: '  ' })]);
		expect(result.columnErrors.map((error) => error.name)).toEqual([
			EMPTY_NAME_ERROR,
			EMPTY_NAME_ERROR
		]);
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

describe('metadata-only edit preservation', () => {
	it.each(['report', 'issues_list', 'custom-format', undefined])(
		'preserves dormant columns and unrelated extensions in prose (%s)',
		(outputFormat) => {
			const prev = {
				...(outputFormat === undefined ? {} : { output_format: outputFormat }),
				columns: [{ name: '  Term  ', query: '  q\n', minimum_inference_tier: null }],
				inputs: [{ name: 'agreement', required: true }],
				custom: { nested: ['retain', null] }
			};
			const result = buildFrontmatterExtra(prev, 'prose', [newEditableColumn()]);
			expect(JSON.stringify(result)).toBe(JSON.stringify(prev));
			expect(result.columns).toBe(prev.columns);
		}
	);

	it('preserves raw table specs when editor fields are unchanged', () => {
		const prev = {
			output_format: 'table',
			columns: [
				{
					query: '  Extract the term.\n',
					name: '  Term  ',
					ensemble_verification: null,
					minimum_inference_tier: null,
					custom: { retained: true }
				},
				{ name: 'Law', query: 'Find the law.', ensemble_verification: false }
			],
			jurisdiction: 'sg',
			custom: { nested: ['retain', null] }
		};
		const original = JSON.stringify(prev);
		const result = buildFrontmatterExtra(prev, 'table', columnsFromRaw(prev.columns)!);
		expect(JSON.stringify(result)).toBe(original);
		expect(result.columns).toBe(prev.columns);
		expect(JSON.stringify(prev)).toBe(original);
	});

	it.each([undefined, [], ['legacy'], [{ name: 'Term' }]])(
		'preserves legacy table data rather than repairing it on an unrelated save: %j',
		(raw) => {
			const prev = { output_format: 'table', columns: raw };
			const parsed = columnsFromRaw(raw);
			const editor = parsed?.length ? parsed : [newEditableColumn()];
			expect(buildFrontmatterExtra(prev, 'table', editor)).toEqual(prev);
		}
	);

	it.each([
		{ name: 'Changed' },
		{ query: 'Changed query' },
		{ ensemble_verification: false },
		{ minimum_inference_tier: 3 }
	])('persists an intentional column field edit: %j', (change) => {
		const prev = { output_format: 'table', columns: serializeColumns([col()]), icon: 'keep' };
		const edited = [col(change)];
		expect(buildFrontmatterExtra(prev, 'table', edited)).toEqual({
			...prev,
			columns: serializeColumns(edited)
		});
		expect(prev.columns).toEqual(serializeColumns([col()]));
	});

	it('persists adding, removing and reordering columns', () => {
		const columns = [col(), col({ name: 'Law' })];
		const prev = { output_format: 'table', columns: serializeColumns(columns), custom: 'keep' };
		for (const edited of [
			columns.slice(0, 1),
			[...columns, col({ name: 'Date' })],
			moveColumn(columns, 1, -1)
		]) {
			expect(buildFrontmatterExtra(prev, 'table', edited)).toEqual({
				...prev,
				columns: serializeColumns(edited)
			});
		}
	});

	it('persists a Prose-to-Table transition even with unchanged dormant columns', () => {
		const prev = { output_format: 'report', columns: serializeColumns([col()]), custom: 'keep' };
		expect(buildFrontmatterExtra(prev, 'table', columnsFromRaw(prev.columns)!)).toEqual({
			...prev,
			output_format: 'table'
		});
	});
});

describe('stored column scalar normalization', () => {
	it.each([false, 0, '0', 'off', 'f', 'false', 'n', 'no', 'FALSE', 'Off'])(
		'normalizes false alias %j',
		(raw) => {
			expect(normalizeColumnEnsemble(raw)).toBe(false);
		}
	);
	it.each([true, 1, '1', 'on', 't', 'true', 'y', 'yes', 'TRUE', 'Yes'])(
		'normalizes true alias %j',
		(raw) => {
			expect(normalizeColumnEnsemble(raw)).toBe(true);
		}
	);
	it.each([null, undefined, '', ' false ', 'sometimes', 2, [], {}])(
		'does not coerce unsupported boolean input %j',
		(raw) => {
			expect(normalizeColumnEnsemble(raw)).toBeNull();
		}
	);
	it.each([
		['1', 1],
		['2', 2],
		[' 3 ', 3],
		['+4', 4],
		['5.0', 5],
		[true, 1]
	])('normalizes tier %j to %j', (raw, expected) => {
		expect(normalizeColumnTier(raw)).toBe(expected);
	});
	it.each([0, 6, 2.5, NaN, Infinity])('retains invalid numeric tier %j for validation', (raw) => {
		expect(normalizeColumnTier(raw)).toBe(raw);
		expect(validateColumns([col({ minimum_inference_tier: normalizeColumnTier(raw) })]).valid).toBe(
			false
		);
	});
	it.each([null, undefined, '', 'four', '2.5', '0x2', '2e0', [], {}])(
		'does not coerce unsupported tier %j',
		(raw) => {
			expect(normalizeColumnTier(raw)).toBeNull();
		}
	);
	it('preserves raw metadata on no-op saves and retains coerced values on intentional edits', () => {
		const prev = {
			output_format: 'table',
			columns: [
				{
					name: 'Term',
					query: 'Original query',
					ensemble_verification: 'false',
					minimum_inference_tier: '2'
				}
			],
			icon: 'keep'
		};
		const parsed = columnsFromRaw(prev.columns)!;
		expect(parsed[0]).toEqual(
			col({ query: 'Original query', ensemble_verification: false, minimum_inference_tier: 2 })
		);
		expect(buildFrontmatterExtra(prev, 'table', parsed).columns).toBe(prev.columns);
		parsed[0].query = 'Changed query';
		expect(buildFrontmatterExtra(prev, 'table', parsed)).toEqual({
			...prev,
			columns: [
				{
					name: 'Term',
					query: 'Changed query',
					ensemble_verification: false,
					minimum_inference_tier: 2
				}
			]
		});
		expect(prev.columns[0].ensemble_verification).toBe('false');
	});
});
