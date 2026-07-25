/**
 * DE-298 — pure-helper tests for the /lq-ai/skills built-ins browser:
 * output-format chip filter (+ URL-param round-trip), recently-used
 * sort with never-used alphabetical fallback, and fork-seed column
 * extraction from a source skill's `content_yaml`.
 */
import { describe, expect, it } from 'vitest';

import {
	FORMAT_ALL,
	FORMAT_PROSE,
	columnsFromContentYaml,
	forkTableSeed,
	formatChips,
	formatFilterFromParam,
	matchesFormat,
	normalizeFormat,
	sortFromParam,
	sortSkillRows
} from '../skills/builtinsBrowser';

describe('builtinsBrowser helpers (DE-298)', () => {
	describe('normalizeFormat', () => {
		it('buckets absent / blank formats as prose', () => {
			expect(normalizeFormat(undefined)).toBe(FORMAT_PROSE);
			expect(normalizeFormat(null)).toBe(FORMAT_PROSE);
			expect(normalizeFormat('   ')).toBe(FORMAT_PROSE);
		});

		it('lowercases and trims declared formats', () => {
			expect(normalizeFormat(' Table ')).toBe('table');
			expect(normalizeFormat('report')).toBe('report');
		});
	});

	describe('formatChips', () => {
		it('derives distinct chips from the rows present, "all" first then alphabetical', () => {
			expect(formatChips(['table', undefined, 'report', 'table', null])).toEqual([
				FORMAT_ALL,
				FORMAT_PROSE,
				'report',
				'table'
			]);
		});

		it('empty catalog yields only the "all" chip', () => {
			expect(formatChips([])).toEqual([FORMAT_ALL]);
		});
	});

	describe('formatFilterFromParam (URL round-trip)', () => {
		const chips = [FORMAT_ALL, FORMAT_PROSE, 'table'];

		it('absent param means no filter', () => {
			expect(formatFilterFromParam(null, chips)).toBe(FORMAT_ALL);
		});

		it('a known chip value round-trips (case-insensitively)', () => {
			expect(formatFilterFromParam('table', chips)).toBe('table');
			expect(formatFilterFromParam(' TABLE ', chips)).toBe('table');
		});

		it('a stale / unknown param degrades to "all", never an empty page', () => {
			expect(formatFilterFromParam('report', chips)).toBe(FORMAT_ALL);
			expect(formatFilterFromParam('nonsense', chips)).toBe(FORMAT_ALL);
		});
	});

	describe('matchesFormat', () => {
		it('"all" passes everything', () => {
			expect(matchesFormat('table', FORMAT_ALL)).toBe(true);
			expect(matchesFormat(undefined, FORMAT_ALL)).toBe(true);
		});

		it('a specific chip matches only its bucket, with prose catching undeclared', () => {
			expect(matchesFormat('table', 'table')).toBe(true);
			expect(matchesFormat('report', 'table')).toBe(false);
			expect(matchesFormat(undefined, FORMAT_PROSE)).toBe(true);
			expect(matchesFormat('table', FORMAT_PROSE)).toBe(false);
		});
	});

	describe('sortFromParam', () => {
		it('recognises "name"; everything else defaults to "recent"', () => {
			expect(sortFromParam('name')).toBe('name');
			expect(sortFromParam('recent')).toBe('recent');
			expect(sortFromParam(null)).toBe('recent');
			expect(sortFromParam('garbage')).toBe('recent');
		});
	});

	describe('sortSkillRows', () => {
		const rows = [
			{ slug: 'zeta', title: 'Zeta' },
			{ slug: 'alpha', title: 'Alpha' },
			{ slug: 'mid', title: 'Mid' }
		];
		const slugOf = (r: { slug: string }) => r.slug;
		const titleOf = (r: { title: string }) => r.title;

		it('recent sort orders by recents position, never-used fall back alphabetical', () => {
			const sorted = sortSkillRows(rows, 'recent', ['mid', 'zeta'], slugOf, titleOf);
			expect(sorted.map(slugOf)).toEqual(['mid', 'zeta', 'alpha']);
		});

		it('with no recents, recent sort degrades to alphabetical-by-title', () => {
			const sorted = sortSkillRows(rows, 'recent', [], slugOf, titleOf);
			expect(sorted.map(slugOf)).toEqual(['alpha', 'mid', 'zeta']);
		});

		it('name sort is alphabetical regardless of recents', () => {
			const sorted = sortSkillRows(rows, 'name', ['zeta'], slugOf, titleOf);
			expect(sorted.map(slugOf)).toEqual(['alpha', 'mid', 'zeta']);
		});

		it('does not mutate the input array', () => {
			const input = [...rows];
			sortSkillRows(input, 'recent', ['zeta'], slugOf, titleOf);
			expect(input).toEqual(rows);
		});
	});

	// The shape a built-in table skill actually carries on the wire —
	// lq_ai.columns with block-scalar queries and per-column overrides
	// (mirrors skills/contract-snapshot/SKILL.md).
	const BUILTIN_YAML = [
		'name: contract-snapshot',
		'description: Compare terms across contracts.',
		'lq_ai:',
		'  title: Contract Snapshot',
		'  version: 1.0.0',
		'  output_format: table',
		'  columns:',
		'    - name: Term',
		'      query: |',
		'        What is the term length of this agreement?',
		'    - name: Survival',
		'      query: What survives termination?',
		'      ensemble_verification: true',
		'    - name: Governing Law',
		'      query: What law governs?',
		'      minimum_inference_tier: 3',
		''
	].join('\n');

	describe('columnsFromContentYaml', () => {
		it('extracts lq_ai.columns with overrides normalized to EditableColumn rows', () => {
			const cols = columnsFromContentYaml(BUILTIN_YAML);
			expect(cols).not.toBeNull();
			expect(cols).toHaveLength(3);
			expect(cols?.[0]).toEqual({
				name: 'Term',
				query: 'What is the term length of this agreement?\n',
				ensemble_verification: null,
				minimum_inference_tier: null
			});
			expect(cols?.[1].ensemble_verification).toBe(true);
			expect(cols?.[2].minimum_inference_tier).toBe(3);
		});

		it('accepts a top-level columns key as fallback', () => {
			const cols = columnsFromContentYaml(
				'name: x\ncolumns:\n  - name: A\n    query: Q\n'
			);
			expect(cols).toEqual([
				{ name: 'A', query: 'Q', ensemble_verification: null, minimum_inference_tier: null }
			]);
		});

		it('returns null for absent input, unparseable YAML, and column-less frontmatter', () => {
			expect(columnsFromContentYaml(null)).toBeNull();
			expect(columnsFromContentYaml('')).toBeNull();
			expect(columnsFromContentYaml(': not: valid: [yaml')).toBeNull();
			expect(columnsFromContentYaml('name: x\nlq_ai:\n  title: X\n')).toBeNull();
			expect(columnsFromContentYaml('name: x\nlq_ai:\n  columns: []\n')).toBeNull();
		});
	});

	describe('forkTableSeed', () => {
		it('seeds table mode + columns for a table-mode source', () => {
			const seed = forkTableSeed({ output_format: 'table', content_yaml: BUILTIN_YAML });
			expect(seed).not.toBeNull();
			expect(seed?.outputMode).toBe('table');
			expect(seed?.columns.map((c) => c.name)).toEqual(['Term', 'Survival', 'Governing Law']);
		});

		it('returns null for prose sources (fork opens in prose mode unchanged)', () => {
			expect(forkTableSeed({ output_format: undefined, content_yaml: BUILTIN_YAML })).toBeNull();
			expect(forkTableSeed({ output_format: 'report', content_yaml: BUILTIN_YAML })).toBeNull();
		});

		it('returns null when a table source has no recoverable columns', () => {
			expect(forkTableSeed({ output_format: 'table', content_yaml: 'name: x\n' })).toBeNull();
		});
	});
});
