import { readFileSync } from 'node:fs';

import { describe, expect, it } from 'vitest';
import { render } from 'svelte/server';
import { parse } from 'svelte/compiler';

import TabularEnsembleHaltNotice from '../components/TabularEnsembleHaltNotice.svelte';
import type { TabularResults } from '../types';

function markup(results: TabularResults | null): string {
	return render(TabularEnsembleHaltNotice, { props: { results } }).body;
}

describe('ensemble halt feedback', () => {
	it.each([
		null,
		{ rows: [] },
		{ rows: [], ensemble_halted_at_ceiling: false, ensemble_halted_cells: 2 }
	] satisfies (TabularResults | null)[])('omits the notice without a halt: %j', (results) => {
		expect(markup(results)).not.toContain('lq-tabres-ensemble-halt');
	});

	it.each([
		[1, '1 eligible cell.'],
		[2, '2 eligible cells.']
	])('shows the reason and skipped count for %i cells', (count, wording) => {
		const html = markup({
			rows: [],
			ensemble_halted_at_ceiling: true,
			ensemble_halted_cells: count as number
		});
		expect(html).toContain('role="status"');
		expect(html).toContain('estimated cost backstop');
		expect(html).toContain(wording);
		expect(html).toContain('Extraction continued');
		expect(html).toContain('individual failures');
		expect(html).toContain('Final charges may exceed the estimate');
	});

	it.each([undefined, 0, -1, 1.5, Number.NaN])(
		'shows the reason without inventing an absent or invalid count: %s',
		(count) => {
			const html = markup({
				rows: [],
				ensemble_halted_at_ceiling: true,
				ensemble_halted_cells: count
			});
			expect(html).toContain('estimated cost backstop');
			expect(html).not.toContain('Verification was skipped for');
		}
	);

	it('connects the notice to the result page execution results', () => {
		const source = readFileSync(
			new URL('../../../routes/lq-ai/tabular/[id]/+page.svelte', import.meta.url),
			'utf8'
		);
		const tree = parse(source);
		const notices: Record<string, unknown>[] = [];
		function walk(value: unknown): void {
			if (!value || typeof value !== 'object') return;
			const node = value as Record<string, unknown>;
			if (node.type === 'InlineComponent' && node.name === 'TabularEnsembleHaltNotice') {
				notices.push(node);
			}
			Object.values(node).forEach(walk);
		}
		walk(tree.html);
		expect(notices).toHaveLength(1);
		expect(notices[0].attributes).toEqual(
			expect.arrayContaining([
				expect.objectContaining({
					name: 'results',
					value: expect.arrayContaining([
						expect.objectContaining({
							expression: expect.objectContaining({
								type: 'MemberExpression',
								object: expect.objectContaining({ name: 'execution' }),
								property: expect.objectContaining({ name: 'results' })
							})
						})
					])
				})
			])
		);
	});
});
