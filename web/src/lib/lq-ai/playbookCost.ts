/**
 * Client-side cost estimation for playbook execution.
 *
 * Per the M3-A4 §5.2 design decision, cost preview is informational —
 * computed in the browser against a static per-model rate table sourced
 * from public Anthropic / OpenAI pricing pages. A precise server-side
 * estimate (using M2-E2's rolling-average calibration) would be more
 * accurate but adds a new endpoint + tests + OpenAPI surface for
 * informational-only data.
 *
 * Update PER_MODEL_RATES periodically — public prices drift. Last
 * verified: 2026-05-18 against:
 *   https://www.anthropic.com/pricing
 *   https://openai.com/pricing
 */

import type { Playbook } from './types';

export interface ModelRate {
	input_usd_per_million: number;
	output_usd_per_million: number;
}

export const PER_MODEL_RATES: Record<string, ModelRate> = {
	'claude-sonnet-4-6': { input_usd_per_million: 3.0, output_usd_per_million: 15.0 },
	'claude-opus-4-7': { input_usd_per_million: 15.0, output_usd_per_million: 75.0 },
	'claude-haiku-4-5': { input_usd_per_million: 1.0, output_usd_per_million: 5.0 },
	'gpt-5': { input_usd_per_million: 5.0, output_usd_per_million: 20.0 },
	'gpt-5-mini': { input_usd_per_million: 0.5, output_usd_per_million: 2.0 }
};

export const DEFAULT_JUDGE_MODEL = 'claude-sonnet-4-6';

/**
 * Per-position token budget. Mirrors the executor's CLASSIFY_MAX_TOKENS
 * + REDLINE_MAX_TOKENS constants in api/app/playbooks/nodes.py, plus a
 * representative input budget for the system prompt + retrieved chunks.
 */
const CLASSIFY_INPUT_TOKENS = 2000;
const CLASSIFY_OUTPUT_TOKENS = 600;
const REDLINE_INPUT_TOKENS = 2000;
const REDLINE_OUTPUT_TOKENS = 800;

/**
 * Empirically, ~1/3 of positions deviate from standard in a typical
 * contract review and trigger the redline pass. Tune as M3-A4 produces
 * real-world data.
 */
const REDLINE_PROBABILITY = 1 / 3;

export interface CostEstimate {
	estimated_cost_usd: number;
	position_count: number;
	judge_model: string;
}

export function estimatePlaybookCost(playbook: Playbook, modelId: string): CostEstimate {
	const positionCount = playbook.positions.length;
	if (positionCount === 0) {
		return { estimated_cost_usd: 0, position_count: 0, judge_model: modelId };
	}

	const effectiveModel = modelId in PER_MODEL_RATES ? modelId : DEFAULT_JUDGE_MODEL;
	const rate = PER_MODEL_RATES[effectiveModel];

	const perPositionInputCost =
		(CLASSIFY_INPUT_TOKENS / 1_000_000) * rate.input_usd_per_million +
		REDLINE_PROBABILITY * ((REDLINE_INPUT_TOKENS / 1_000_000) * rate.input_usd_per_million);
	const perPositionOutputCost =
		(CLASSIFY_OUTPUT_TOKENS / 1_000_000) * rate.output_usd_per_million +
		REDLINE_PROBABILITY * ((REDLINE_OUTPUT_TOKENS / 1_000_000) * rate.output_usd_per_million);
	const perPositionCost = perPositionInputCost + perPositionOutputCost;

	return {
		estimated_cost_usd: perPositionCost * positionCount,
		position_count: positionCount,
		judge_model: effectiveModel
	};
}

/** Format a USD amount for display. */
export function formatCostUSD(amount: number): string {
	if (amount === 0) return '$0.00';
	if (amount < 0.01) return '< $0.01';
	return `$${amount.toFixed(2)}`;
}
