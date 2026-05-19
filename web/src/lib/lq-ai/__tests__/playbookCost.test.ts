import { describe, it, expect } from 'vitest';

import {
	estimatePlaybookCost,
	formatCostUSD,
	DEFAULT_JUDGE_MODEL,
	PER_MODEL_RATES
} from '../playbookCost';
import type { Playbook } from '../types';

const mockPlaybook = (positionCount: number): Playbook => ({
	id: 'p1',
	name: 'Test',
	contract_type: 'NDA',
	description: '',
	version: '1.0.0',
	created_by: null,
	created_at: '2026-05-18T00:00:00Z',
	updated_at: '2026-05-18T00:00:00Z',
	positions: Array.from({ length: positionCount }, (_, i) => ({
		id: `pos-${i}`,
		issue: `Issue ${i}`,
		description: '',
		standard_language: '',
		fallback_tiers: [],
		redline_strategy: '',
		severity_if_missing: 'medium' as const,
		detection_keywords: [],
		detection_examples: [],
		position_order: i
	}))
});

describe('estimatePlaybookCost', () => {
	it('returns a non-negative cost for a 1-position playbook on the default model', () => {
		const cost = estimatePlaybookCost(mockPlaybook(1), DEFAULT_JUDGE_MODEL);
		expect(cost.estimated_cost_usd).toBeGreaterThan(0);
		expect(cost.judge_model).toBe(DEFAULT_JUDGE_MODEL);
		expect(cost.position_count).toBe(1);
	});

	it('scales linearly with position count', () => {
		const oneCost = estimatePlaybookCost(mockPlaybook(1), DEFAULT_JUDGE_MODEL).estimated_cost_usd;
		const tenCost = estimatePlaybookCost(mockPlaybook(10), DEFAULT_JUDGE_MODEL).estimated_cost_usd;
		// 10 positions cost ~10x one position
		expect(tenCost).toBeCloseTo(oneCost * 10, 4);
	});

	it('falls back to a known model if the requested rate is missing', () => {
		const cost = estimatePlaybookCost(mockPlaybook(8), 'totally-unknown-model-xyz');
		// We don't crash; we use the fallback model's rate.
		expect(cost.estimated_cost_usd).toBeGreaterThan(0);
		expect(cost.judge_model).toBe(DEFAULT_JUDGE_MODEL);
	});

	it('returns 0 cost for 0 positions', () => {
		const cost = estimatePlaybookCost(mockPlaybook(0), DEFAULT_JUDGE_MODEL);
		expect(cost.estimated_cost_usd).toBe(0);
		expect(cost.position_count).toBe(0);
	});

	it('all listed rates have positive input + output rates', () => {
		for (const [modelId, rate] of Object.entries(PER_MODEL_RATES)) {
			expect(rate.input_usd_per_million, `${modelId} input`).toBeGreaterThan(0);
			expect(rate.output_usd_per_million, `${modelId} output`).toBeGreaterThan(0);
		}
	});
});

describe('formatCostUSD', () => {
	it('formats with $ + two decimals for ≥ $0.01', () => {
		expect(formatCostUSD(1.5)).toBe('$1.50');
		expect(formatCostUSD(0.01)).toBe('$0.01');
		expect(formatCostUSD(12.345)).toBe('$12.35');
	});

	it('shows < $0.01 for tiny non-zero costs', () => {
		expect(formatCostUSD(0.001)).toBe('< $0.01');
		expect(formatCostUSD(0.009)).toBe('< $0.01');
	});

	it('shows $0.00 for exactly 0', () => {
		expect(formatCostUSD(0)).toBe('$0.00');
	});
});
