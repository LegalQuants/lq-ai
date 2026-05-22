/**
 * Pure helpers for the Tabular result view (`/lq-ai/tabular/[id]`).
 *
 * The +page.svelte holds the imperative polling + rendering; these
 * functions hold the deterministic decisions so the polling
 * machinery + progress display are testable without a browser
 * (mirrors the M3-A4 playbook-executions/page-helpers.ts pattern).
 *
 * Constants:
 * - `TABULAR_POLL_INTERVAL_MS` = 3000 — matches the M3-A4 playbook
 *   execution view's 3-second poll. Tabular runs are much longer
 *   (potentially hours), so the choice trades server load for grid
 *   freshness; 3s is the existing accepted default.
 */
import type {
	TabularCellConfidence,
	TabularCellResult,
	TabularExecutionStatus,
	TabularResults
} from '$lib/lq-ai/types';

export const TABULAR_POLL_INTERVAL_MS = 3000;

/** Status the worker won't change without external operator action. */
export function isTerminalStatus(status: TabularExecutionStatus): boolean {
	return status === 'completed' || status === 'failed' || status === 'cancelled';
}

/**
 * Fraction of the grid that has been populated, in [0, 1]. The result
 * view's progress bar binds to this on running rows; the completed
 * state always returns 1 (the grid is full by definition).
 */
export function progressFraction(
	status: TabularExecutionStatus,
	results: TabularResults | null,
	documentCount: number,
	columnCount: number
): number {
	if (status === 'completed') return 1;
	if (!results) return 0;
	const expected = documentCount * columnCount;
	if (expected <= 0) return 0;
	let populated = 0;
	for (const row of results.rows) {
		populated += Object.keys(row.cells).length;
	}
	return Math.min(1, populated / expected);
}

/** Render a 0..1 fraction as `'N%'` with integer rounding. */
export function formatProgress(fraction: number): string {
	return `${Math.round(fraction * 100)}%`;
}

/**
 * Discriminator for the cell renderer:
 * - `'empty'` → cell hasn't been populated yet (still running).
 * - `'failed'` → extraction errored (Decision C-10: italic "not
 *   found" + amber chip).
 * - `'high' | 'medium' | 'low'` → Citation Engine confidence; chip
 *   colour comes from this.
 */
export type CellRenderState = 'empty' | 'failed' | 'high' | 'medium' | 'low';

export function cellRenderState(cell: TabularCellResult | undefined): CellRenderState {
	if (cell === undefined) return 'empty';
	return cell.confidence;
}

/** Short human-readable label for a confidence chip. */
export function confidenceChipLabel(confidence: TabularCellConfidence): string {
	switch (confidence) {
		case 'high':
			return 'High';
		case 'medium':
			return 'Med';
		case 'low':
			return 'Low';
		case 'failed':
			return 'Failed';
	}
}
