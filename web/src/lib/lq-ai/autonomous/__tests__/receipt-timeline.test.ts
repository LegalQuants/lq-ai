/**
 * Unit tests for buildTimeline() in receipt-timeline.ts.
 *
 * Mirrors the pattern from:
 *   web/src/routes/lq-ai/autonomous/__tests__/page-helpers.test.ts
 *   web/src/routes/lq-ai/playbook-executions/[id]/__tests__/page-helpers.test.ts
 *
 * All inputs are crafted to be independent of the SvelteKit / Svelte runtime.
 */
import { describe, expect, it } from 'vitest';

import { buildTimeline } from '../receipt-timeline';
import type { SessionReceipt } from '$lib/lq-ai/api/autonomous';

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function makeReceipt(overrides: Partial<SessionReceipt> = {}): SessionReceipt {
	return {
		session_id: 'sess-001',
		trigger_kind: 'manual',
		status: 'completed',
		halt_state: 'running',
		current_phase: 'delivery',
		cost_total_usd: 0.05,
		max_cost_usd: null,
		cost_cap_reached: false,
		created_at: '2026-05-26T10:00:00Z',
		completed_at: '2026-05-26T10:05:00Z',
		phase_transitions: [],
		tool_calls: [],
		terminal_reason: null,
		...overrides
	};
}

// ---------------------------------------------------------------------------
// buildTimeline — empty lists
// ---------------------------------------------------------------------------

describe('buildTimeline — empty lists', () => {
	it('returns an empty array when both lists are empty', () => {
		const receipt = makeReceipt({ phase_transitions: [], tool_calls: [] });
		expect(buildTimeline(receipt)).toEqual([]);
	});

	it('returns only phase nodes when tool_calls is empty', () => {
		const receipt = makeReceipt({
			phase_transitions: [{ to_phase: 'intake', timestamp: '2026-05-26T10:00:00Z' }],
			tool_calls: []
		});
		const timeline = buildTimeline(receipt);
		expect(timeline).toHaveLength(1);
		expect(timeline[0].kind).toBe('phase');
	});

	it('returns only tool nodes when phase_transitions is empty', () => {
		const receipt = makeReceipt({
			phase_transitions: [],
			tool_calls: [
				{ tool: 'extract', outcome: 'success', timestamp: '2026-05-26T10:01:00Z', cost_usd: 0.01 }
			]
		});
		const timeline = buildTimeline(receipt);
		expect(timeline).toHaveLength(1);
		expect(timeline[0].kind).toBe('tool');
	});
});

// ---------------------------------------------------------------------------
// buildTimeline — interleaved ascending sort
// ---------------------------------------------------------------------------

describe('buildTimeline — interleaved ascending sort', () => {
	it('merges 2 phases + 2 tool_calls and returns them in ascending timestamp order', () => {
		const receipt = makeReceipt({
			phase_transitions: [
				{ to_phase: 'intake', timestamp: '2026-05-26T10:00:00Z' },
				{ to_phase: 'analysis', timestamp: '2026-05-26T10:02:00Z' }
			],
			tool_calls: [
				{ tool: 'extract', outcome: 'success', timestamp: '2026-05-26T10:01:00Z', cost_usd: 0.01 },
				{ tool: 'summarise', outcome: 'success', timestamp: '2026-05-26T10:03:00Z' }
			]
		});

		const timeline = buildTimeline(receipt);

		expect(timeline).toHaveLength(4);
		expect(timeline[0]).toMatchObject({ kind: 'phase', at: '2026-05-26T10:00:00Z', phase: 'intake' });
		expect(timeline[1]).toMatchObject({ kind: 'tool', at: '2026-05-26T10:01:00Z', tool: 'extract' });
		expect(timeline[2]).toMatchObject({ kind: 'phase', at: '2026-05-26T10:02:00Z', phase: 'analysis' });
		expect(timeline[3]).toMatchObject({ kind: 'tool', at: '2026-05-26T10:03:00Z', tool: 'summarise' });
	});

	it('preserves kind and payload on each node', () => {
		const receipt = makeReceipt({
			phase_transitions: [
				{ to_phase: 'drafting', timestamp: '2026-05-26T10:00:00Z' }
			],
			tool_calls: [
				{ tool: 'draft', outcome: 'ok', timestamp: '2026-05-26T10:00:30Z', cost_usd: 0.02 }
			]
		});

		const [phaseNode, toolNode] = buildTimeline(receipt);

		// Phase node shape
		if (phaseNode.kind !== 'phase') throw new Error('Expected phase node first');
		expect(phaseNode.phase).toBe('drafting');
		expect(phaseNode.at).toBe('2026-05-26T10:00:00Z');

		// Tool node shape
		if (toolNode.kind !== 'tool') throw new Error('Expected tool node second');
		expect(toolNode.tool).toBe('draft');
		expect(toolNode.outcome).toBe('ok');
		expect(toolNode.cost_usd).toBe(0.02);
		expect(toolNode.at).toBe('2026-05-26T10:00:30Z');
	});
});

// ---------------------------------------------------------------------------
// buildTimeline — null-timestamp entries sort last
// ---------------------------------------------------------------------------

describe('buildTimeline — null timestamp sorts to end', () => {
	it('places a null-timestamp phase node after all timestamped nodes', () => {
		const receipt = makeReceipt({
			phase_transitions: [
				{ to_phase: null, timestamp: null },
				{ to_phase: 'intake', timestamp: '2026-05-26T10:00:00Z' }
			],
			tool_calls: [
				{ tool: 'extract', outcome: 'success', timestamp: '2026-05-26T10:01:00Z' }
			]
		});

		const timeline = buildTimeline(receipt);

		expect(timeline).toHaveLength(3);
		expect(timeline[0].at).toBe('2026-05-26T10:00:00Z');
		expect(timeline[1].at).toBe('2026-05-26T10:01:00Z');
		// null-timestamp node is last
		expect(timeline[2].at).toBeNull();
		expect(timeline[2].kind).toBe('phase');
	});

	it('places a null-timestamp tool node after all timestamped nodes', () => {
		const receipt = makeReceipt({
			phase_transitions: [
				{ to_phase: 'intake', timestamp: '2026-05-26T10:00:00Z' }
			],
			tool_calls: [
				{ tool: 'unknown', outcome: null, timestamp: null }
			]
		});

		const timeline = buildTimeline(receipt);

		expect(timeline).toHaveLength(2);
		expect(timeline[0].at).toBe('2026-05-26T10:00:00Z');
		expect(timeline[1].at).toBeNull();
		expect(timeline[1].kind).toBe('tool');
	});

	it('handles multiple null-timestamp entries — all sort to end in original order', () => {
		const receipt = makeReceipt({
			phase_transitions: [
				{ to_phase: 'intake', timestamp: null },
				{ to_phase: 'analysis', timestamp: null }
			],
			tool_calls: [
				{ tool: 'extract', outcome: 'ok', timestamp: '2026-05-26T10:00:00Z' }
			]
		});

		const timeline = buildTimeline(receipt);

		// Timestamped tool node comes first
		expect(timeline[0].kind).toBe('tool');
		expect(timeline[0].at).toBe('2026-05-26T10:00:00Z');
		// Both null-timestamp phase nodes at end
		expect(timeline[1].at).toBeNull();
		expect(timeline[2].at).toBeNull();
	});
});

// ---------------------------------------------------------------------------
// buildTimeline — optional cost_usd field
// ---------------------------------------------------------------------------

describe('buildTimeline — cost_usd', () => {
	it('propagates cost_usd when present on a tool node', () => {
		const receipt = makeReceipt({
			tool_calls: [
				{ tool: 'analyze', outcome: 'done', timestamp: '2026-05-26T10:00:00Z', cost_usd: 0.005 }
			]
		});
		const [node] = buildTimeline(receipt);
		if (node.kind !== 'tool') throw new Error('Expected tool node');
		expect(node.cost_usd).toBe(0.005);
	});

	it('leaves cost_usd undefined when absent from the tool entry', () => {
		const receipt = makeReceipt({
			tool_calls: [{ tool: 'analyze', outcome: 'done', timestamp: '2026-05-26T10:00:00Z' }]
		});
		const [node] = buildTimeline(receipt);
		if (node.kind !== 'tool') throw new Error('Expected tool node');
		expect(node.cost_usd).toBeUndefined();
	});
});
