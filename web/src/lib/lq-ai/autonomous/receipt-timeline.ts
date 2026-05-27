/**
 * Pure helper for the M4-C2 session receipt page.
 *
 * Merges `phase_transitions` and `tool_calls` from a SessionReceipt into a
 * single ascending-time thread. No side-effects; referentially transparent.
 * Extracted so vitest can exercise it without the SvelteKit / Svelte runtime.
 */

import type {
	SessionReceipt,
	ReceiptPhaseTransition,
	ReceiptToolCall
} from '$lib/lq-ai/api/autonomous';

export type TimelineNode =
	| { kind: 'phase'; at: string | null; phase: string | null }
	| { kind: 'tool'; at: string | null; tool: string | null; outcome: string | null; cost_usd?: number };

/**
 * Merge phase_transitions + tool_calls into one ascending-time thread.
 *
 * Entries are sorted by their `timestamp` field (ISO-8601 string comparison
 * is lexicographic and therefore chronologically correct for UTC strings).
 * Entries with a null timestamp sort to the end, stably.
 */
export function buildTimeline(receipt: SessionReceipt): TimelineNode[] {
	const phases: TimelineNode[] = receipt.phase_transitions.map((p: ReceiptPhaseTransition) => ({
		kind: 'phase',
		at: p.timestamp,
		phase: p.to_phase
	}));
	const tools: TimelineNode[] = receipt.tool_calls.map((t: ReceiptToolCall) => ({
		kind: 'tool',
		at: t.timestamp,
		tool: t.tool,
		outcome: t.outcome,
		cost_usd: t.cost_usd
	}));
	return [...phases, ...tools].sort((a, b) => {
		if (a.at == null) return 1;
		if (b.at == null) return -1;
		return a.at < b.at ? -1 : a.at > b.at ? 1 : 0;
	});
}
