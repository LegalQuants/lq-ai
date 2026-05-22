/**
 * Pure-helper tests for the Tabular result view (M3-C3 sub-phase 4).
 *
 * The Svelte +page.svelte holds rendering + the polling timer; these
 * helpers carry the deterministic decisions (terminal? progress
 * fraction? cell-render-state classification?) so the polling
 * machinery is testable without a browser.
 */
import { describe, expect, it } from 'vitest';

import {
	isTerminalStatus,
	progressFraction,
	formatProgress,
	cellRenderState,
	confidenceChipLabel,
	TABULAR_POLL_INTERVAL_MS
} from '../page-helpers';
import type { TabularCellResult, TabularResults } from '$lib/lq-ai/types';

function cell(over: Partial<TabularCellResult> = {}): TabularCellResult {
	return {
		value: '3 years',
		citations: [],
		confidence: 'high',
		tier_used: 2,
		cost_usd: '0.0050',
		error: null,
		...over
	};
}

describe('tabular result page-helpers', () => {
	describe('TABULAR_POLL_INTERVAL_MS', () => {
		it('matches the M3-A4 playbook execution view (3s)', () => {
			expect(TABULAR_POLL_INTERVAL_MS).toBe(3000);
		});
	});

	describe('isTerminalStatus', () => {
		it('is true for completed / failed / cancelled', () => {
			expect(isTerminalStatus('completed')).toBe(true);
			expect(isTerminalStatus('failed')).toBe(true);
			expect(isTerminalStatus('cancelled')).toBe(true);
		});

		it('is false for pending / running', () => {
			expect(isTerminalStatus('pending')).toBe(false);
			expect(isTerminalStatus('running')).toBe(false);
		});
	});

	describe('progressFraction', () => {
		it('returns 1 when results are null but status is completed', () => {
			expect(progressFraction('completed', null, 5, 4)).toBe(1);
		});

		it('returns 0 when results are null and not terminal', () => {
			expect(progressFraction('pending', null, 5, 4)).toBe(0);
			expect(progressFraction('running', null, 5, 4)).toBe(0);
		});

		it('returns the populated-cell fraction during running', () => {
			const results: TabularResults = {
				rows: [
					{
						document_id: 'd1',
						document_name: 'NDA 1',
						cells: { Term: cell(), Survival: cell() }
					},
					{
						document_id: 'd2',
						document_name: 'NDA 2',
						cells: { Term: cell() }
					}
				]
			};
			// 3 populated cells out of 2 docs × 2 columns = 4 expected
			expect(progressFraction('running', results, 2, 2)).toBe(0.75);
		});

		it('caps at 1', () => {
			const results: TabularResults = {
				rows: [
					{
						document_id: 'd1',
						document_name: 'NDA 1',
						cells: { Term: cell(), Survival: cell(), Extra: cell() }
					}
				]
			};
			expect(progressFraction('running', results, 1, 2)).toBeLessThanOrEqual(1);
		});
	});

	describe('formatProgress', () => {
		it('renders 75% style', () => {
			expect(formatProgress(0.75)).toBe('75%');
			expect(formatProgress(0)).toBe('0%');
			expect(formatProgress(1)).toBe('100%');
		});

		it('rounds to integer percent', () => {
			expect(formatProgress(0.5555)).toBe('56%');
			expect(formatProgress(0.123)).toBe('12%');
		});
	});

	describe('cellRenderState', () => {
		it('returns "empty" when the cell is undefined (not yet computed)', () => {
			expect(cellRenderState(undefined)).toBe('empty');
		});

		it('returns "failed" for confidence=failed cells', () => {
			expect(cellRenderState(cell({ confidence: 'failed', value: null, error: 'boom' }))).toBe(
				'failed'
			);
		});

		it('returns "high" / "medium" / "low" mirroring the cell confidence', () => {
			expect(cellRenderState(cell({ confidence: 'high' }))).toBe('high');
			expect(cellRenderState(cell({ confidence: 'medium' }))).toBe('medium');
			expect(cellRenderState(cell({ confidence: 'low' }))).toBe('low');
		});
	});

	describe('confidenceChipLabel', () => {
		it('renders short human-readable labels', () => {
			expect(confidenceChipLabel('high')).toBe('High');
			expect(confidenceChipLabel('medium')).toBe('Med');
			expect(confidenceChipLabel('low')).toBe('Low');
			expect(confidenceChipLabel('failed')).toBe('Failed');
		});
	});
});
