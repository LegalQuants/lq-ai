/**
 * Pure helpers for the `/lq-ai/tabular` list page (M3-C3), extracted to
 * a sibling `.ts` file so vitest can exercise them without the svelte
 * transformer (mirrors the M3-A4 playbooks page-helpers pattern).
 */
import type {
	TabularExecutionStatus,
	TabularExecutionSummary
} from '$lib/lq-ai/types';

/**
 * Returns a new array sorted newest-first by `created_at` (ISO-8601
 * lexical comparison — safe because the strings are timezone-Z normal).
 */
export function sortTabularExecutionsByCreatedDesc(
	rows: TabularExecutionSummary[]
): TabularExecutionSummary[] {
	return [...rows].sort((a, b) => (a.created_at > b.created_at ? -1 : a.created_at < b.created_at ? 1 : 0));
}

/** Human-friendly label for the status enum (title-case English). */
export function formatTabularStatus(status: TabularExecutionStatus): string {
	switch (status) {
		case 'pending':
			return 'Pending';
		case 'running':
			return 'Running';
		case 'completed':
			return 'Completed';
		case 'failed':
			return 'Failed';
		case 'cancelled':
			return 'Cancelled';
	}
}

/**
 * `5 docs × 4 cols = 20 cells` style string — handles singular /
 * plural for docs, cols, cells independently.
 */
export function formatCellCount(documentCount: number, columnCount: number): string {
	const cells = documentCount * columnCount;
	const docs = `${documentCount} ${documentCount === 1 ? 'doc' : 'docs'}`;
	const cols = `${columnCount} ${columnCount === 1 ? 'col' : 'cols'}`;
	const cellsStr = `${cells} ${cells === 1 ? 'cell' : 'cells'}`;
	return `${docs} × ${cols} = ${cellsStr}`;
}

/**
 * Render a USD decimal-string as `$X.YY`. Null / empty / non-numeric
 * inputs return `—` so the list view stays readable when cost columns
 * are unset (pre-execute previews never persist; pending runs haven't
 * settled actual cost yet).
 */
export function formatCostUsd(value: string | null): string {
	if (value === null || value === '') return '—';
	const n = Number(value);
	if (!Number.isFinite(n)) return '—';
	return `$${n.toFixed(2)}`;
}

/**
 * Display label for the `skill_name` column. Ad-hoc executions (no
 * skill bound) render as the literal "Ad-hoc" — keeps the list
 * scannable without mixing nulls into a string column.
 */
export function skillNameDisplay(skillName: string | null): string {
	return skillName ?? 'Ad-hoc';
}
