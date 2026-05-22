/**
 * Pure-helper tests for the /lq-ai/tabular list-page helpers (M3-C3).
 *
 * Mirrors the playbooks page-helpers test shape: helpers extracted to a
 * sibling `.ts` so vitest can exercise them without the svelte
 * transformer.
 */
import { describe, expect, it } from 'vitest';

import {
	sortTabularExecutionsByCreatedDesc,
	formatTabularStatus,
	formatCellCount,
	formatCostUsd,
	skillNameDisplay
} from '../page-helpers';
import type { TabularExecutionSummary } from '$lib/lq-ai/types';

function summary(over: Partial<TabularExecutionSummary> = {}): TabularExecutionSummary {
	return {
		id: 'tex-x',
		user_id: 'u1',
		parent_execution_id: null,
		skill_name: 'contract-snapshot',
		status: 'completed',
		document_count: 5,
		column_count: 4,
		cost_estimate_usd: '0.0500',
		cost_actual_usd: '0.0480',
		created_at: '2026-05-22T15:00:00Z',
		completed_at: '2026-05-22T15:02:00Z',
		...over
	};
}

describe('tabular page-helpers', () => {
	describe('sortTabularExecutionsByCreatedDesc', () => {
		it('returns newest first by created_at', () => {
			const rows = [
				summary({ id: 'a', created_at: '2026-05-20T10:00:00Z' }),
				summary({ id: 'b', created_at: '2026-05-22T10:00:00Z' }),
				summary({ id: 'c', created_at: '2026-05-21T10:00:00Z' })
			];
			const sorted = sortTabularExecutionsByCreatedDesc(rows);
			expect(sorted.map((r) => r.id)).toEqual(['b', 'c', 'a']);
		});

		it('does not mutate the input array', () => {
			const rows = [
				summary({ id: 'a', created_at: '2026-05-20T10:00:00Z' }),
				summary({ id: 'b', created_at: '2026-05-22T10:00:00Z' })
			];
			const before = rows.map((r) => r.id);
			sortTabularExecutionsByCreatedDesc(rows);
			expect(rows.map((r) => r.id)).toEqual(before);
		});
	});

	describe('formatTabularStatus', () => {
		it('renders human-friendly labels for each status', () => {
			expect(formatTabularStatus('pending')).toBe('Pending');
			expect(formatTabularStatus('running')).toBe('Running');
			expect(formatTabularStatus('completed')).toBe('Completed');
			expect(formatTabularStatus('failed')).toBe('Failed');
			expect(formatTabularStatus('cancelled')).toBe('Cancelled');
		});
	});

	describe('formatCellCount', () => {
		it('renders docs × cols = cells', () => {
			expect(formatCellCount(5, 4)).toBe('5 docs × 4 cols = 20 cells');
		});

		it('singularises correctly', () => {
			expect(formatCellCount(1, 1)).toBe('1 doc × 1 col = 1 cell');
			expect(formatCellCount(1, 4)).toBe('1 doc × 4 cols = 4 cells');
			expect(formatCellCount(5, 1)).toBe('5 docs × 1 col = 5 cells');
		});
	});

	describe('formatCostUsd', () => {
		it('renders cost as $0.XX style', () => {
			expect(formatCostUsd('0.0500')).toBe('$0.05');
			expect(formatCostUsd('1.2345')).toBe('$1.23');
			expect(formatCostUsd('0.0001')).toBe('$0.00');
			expect(formatCostUsd('12.50')).toBe('$12.50');
		});

		it('renders null / empty as em-dash', () => {
			expect(formatCostUsd(null)).toBe('—');
			expect(formatCostUsd('')).toBe('—');
		});

		it('renders an invalid number defensively as em-dash', () => {
			expect(formatCostUsd('not a number')).toBe('—');
		});
	});

	describe('skillNameDisplay', () => {
		it('returns the skill name when set', () => {
			expect(skillNameDisplay('contract-snapshot')).toBe('contract-snapshot');
		});

		it('returns "Ad-hoc" when null', () => {
			expect(skillNameDisplay(null)).toBe('Ad-hoc');
		});
	});
});
